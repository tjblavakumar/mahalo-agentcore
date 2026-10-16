# Task 2 — HITL mechanism decision (Strands 1.61.1)

Step 0 deliverable. Decides how the write tools gate on human approval, based on
reading the INSTALLED `strands-agents` 1.61.1 source under
`agent/.venv/Lib/site-packages/strands`. Every symbol cited below was read in
that tree, not guessed.

## TL;DR decision

**Use the native Strands human-in-the-loop interrupt via a `HookProvider` on the
`BeforeToolCallEvent` hook.** A single `WriteApprovalHook` intercepts the six
write tools *before they run*, calls `event.interrupt(...)` to pause the agent
loop, and the agent returns an `AgentResult` with `stop_reason == "interrupt"`
carrying the proposal details. The caller (the REPL / later the API) shows the
proposal, gets a yes/no, and resumes the agent by re-invoking it with an
`interruptResponse`. On approval the hook lets the real tool run (which performs
the POST/PUT); on rejection the hook sets `event.cancel_tool` so no HTTP write
happens. We do **not** port mahalo-dock's `__PROPOSAL__…__END_PROPOSAL__` string
sentinel.

This is idiomatic: 1.61.1 ships a first-class interrupt system built exactly for
tool-approval HITL, and the SDK's own docstring example is a "delete tool
requires approval" flow — the same shape we need.

## What exists in 1.61.1 (confirmed by reading the source)

### 1. A dedicated interrupt module — `strands/interrupt.py`

Module docstring: *"Human-in-the-loop interrupt system for agent workflows."*
Public dataclass `Interrupt(id, name, reason, response)`, the control-flow
exception `InterruptException`, and `_InterruptState` (tracks raised interrupts,
activates/deactivates, serializes for session management, and `resume(prompt)`
applies user responses). The event loop (`strands/event_loop/event_loop.py`)
imports `InterruptException`/`PendingToolExecution`, catches the exception, lets
it bubble (it is in the "do not wrap" set alongside
`ContextWindowOverflowException`), and persists pending tool execution so a
resume replays the stored assistant message instead of re-calling the model.

**Resume re-fires `BeforeToolCallEvent` — verified (closes review finding 3).**
Reading `strands/interrupt.py` confirms the exact replay path, so the approve
path's load-bearing assumption is grounded, not inferred:

- `_InterruptState.resume(prompt)` (read in full): for each
  `{"interruptResponse": {"interruptId", "response"}}` content it does
  `self.interrupts[interrupt_id].response = interrupt_response`, i.e. it writes
  the user's response onto the **already-stored** `Interrupt` keyed by the id we
  returned. It raises `KeyError` if the id is unknown, so the id must survive
  between return and resume — and it does (see next bullet).
- `PendingToolExecution(assistant_message, completed_tool_results)` stores the
  assistant message that holds the pending tool uses; on resume the loop replays
  that stored message **instead of calling the model again**. So the same
  `toolUse` (same `toolUseId`) is re-processed, which means the same
  `BeforeToolCallEvent` fires a second time.
- The interrupt id is scoped per tool call —
  `BeforeToolCallEvent._interrupt_id(name)` =
  `f"v1:before_tool_call:{toolUseId}:{uuid5(name)}"`. Crucially, the interrupt
  id does **not** start with `_AGENT_STREAM_INTERRUPT_ID_PREFIX`
  (`"v1:middleware_agent_stream:"`), so `end_tool_cycle()` /
  `to_dict()`'s invocation-scoped filtering does not drop it before the resume
  applies the response. The `BeforeToolCallEvent.interrupt(name, ...)` call on
  the second pass therefore recomputes the identical id, finds the stored
  interrupt now carrying `response`, and **returns** that response instead of
  re-raising — so the hook proceeds (approve → body runs; reject → `cancel_tool`).

This is the single most important runtime behavior and it is now confirmed from
installed source (`strands/interrupt.py` `resume()` + `PendingToolExecution`;
`strands/hooks/events.py` `_interrupt_id`), not merely named by file. The manual
live check (design "Live end-to-end") still exercises it end to end as a
belt-and-suspenders confirmation before relying on it in a demo.

### 2. The interrupt API on hook events — `strands/types/interrupt.py`

Defines the `_Interruptible` protocol with `interrupt(self, name, reason=None,
response=None)`:

- First call with no stored response → raises `InterruptException(interrupt)`,
  which stops the agent loop.
- After the user resumes with a response → the second call **returns** that
  response.
- Passing `response=` preemptively → returns it immediately, no interrupt.

The module docstring carries a complete worked example — a `delete_tool` gated by
a `BeforeToolCallEvent` hook that calls `event.interrupt("for_delete_tool",
reason="APPROVAL")` and sets `event.cancel_tool` when approval != "A", then shows
the caller inspecting `result.stop_reason == "interrupt"`, building
`{"interruptResponse": {"interruptId": ..., "response": "A"}}` and re-invoking
the agent. This is the pattern we adopt almost verbatim.

### 3. The hook events — `strands/hooks/events.py` and `strands/hooks/__init__.py`

`strands/hooks/__init__.py` exports `BeforeToolCallEvent`, `AfterToolCallEvent`,
`BeforeToolsEvent`, `AfterToolsEvent`, `BeforeModelCallEvent`,
`AfterModelCallEvent`, `HookProvider`, `HookRegistry`, `HookEvent`, etc.

`BeforeToolCallEvent` (events.py) is declared
`class BeforeToolCallEvent(HookEvent[_LocalAgentT], _Interruptible)` — so it has
`interrupt()`. Its writable fields (`_can_write`) are `cancel_tool`,
`selected_tool`, `tool_use`. Key field:

- `cancel_tool: bool | str = False` — *"A user defined message that when set,
  will cancel the tool call. The message will be placed into a tool result with
  an error status."*
- `tool_use: ToolUse` — the tool name + input args (so the hook can read exactly
  what the model wants to write, which becomes the proposal payload).

`BeforeToolCallEvent._interrupt_id(name)` →
`f"v1:before_tool_call:{toolUseId}:{uuid5(name)}"`, i.e. the interrupt id is
scoped **per tool call**, which is exactly right for a per-write approval gate.

### 4. `HookProvider` / `HookRegistry` — `strands/hooks/registry.py`

Standard register pattern: a class implementing `register_hooks(self, registry,
**kwargs)` that calls `registry.add_callback(BeforeToolCallEvent, self.callback)`.
`Agent(...)` accepts `hooks=[...]` (confirmed by the `interrupt.py` example
`Agent(hooks=[ToolInterruptHook()], ...)`). This is how our `WriteApprovalHook`
plugs into the existing `build_agent()`.

### 5. `ToolContext` and middleware interrupts (noted, not chosen)

`strands/__init__.py` exports `ToolContext`; `strands/_middleware/stages.py`
exposes `ExecuteToolContext.interrupt(...)` and `AgentStreamContext.interrupt(...)`
for middleware-initiated interrupts. These are lower-level / partly internal
(`AgentStreamStage` is explicitly "not exported … @internal"). The hook route is
the public, documented one, so we use it rather than custom middleware.

## Why the native hook interrupt over porting the string sentinel

1. **It is the purpose-built mechanism.** 1.61.1 has a whole interrupt subsystem
   whose canonical example is tool approval. Using it is the idiomatic Strands
   way; the string sentinel was a LangChain-era workaround for the absence of
   such a mechanism.
2. **The write truly cannot execute before approval.** The gate runs in
   `BeforeToolCallEvent`, *before* the tool body. On reject we set `cancel_tool`
   and the tool body (the POST/PUT) never runs — enforced by the framework, not
   by the model's goodwill. The propose path makes zero HTTP write calls by
   construction.
3. **No brittle string parsing.** No `__PROPOSAL__…__END_PROPOSAL__` to emit,
   regex out of free text, and re-inject. The proposal is structured data on the
   `Interrupt`/`tool_use`, and `reason=` carries a human-readable summary.
4. **Resume is first-class and session-managed.** `_InterruptState` serializes
   interrupts between return and response, so the same approach extends cleanly
   to the AgentCore Runtime/Memory phases (Task 3+), where approval round-trips
   over the network.
5. **The write tools stay honest, single-purpose functions.** Each write tool is
   just "resolve params → POST/PUT → format result," identical in spirit to the
   Task 1 read tools. The approval concern lives in one hook, not smeared across
   six tools returning sentinel strings. This keeps the propose path trivially
   unit-testable (the gate is one object).

## Consequence for the fallback clause

The task said: *if 1.61.1 has no suitable native mechanism, fall back to an
explicit propose/approve design and document why.* **It does have one** (the
interrupt + `BeforeToolCallEvent` hook described above), so we take the native
path and the fallback does not apply. The design doc (`task2-design.md`) builds
on this decision.

## Exact symbols referenced

| Symbol | File (under `agent/.venv/Lib/site-packages/strands`) |
| --- | --- |
| `Interrupt`, `InterruptException`, `_InterruptState`, `PendingToolExecution` | `interrupt.py` |
| `_Interruptible.interrupt()`, `InterruptResponse`, `InterruptResponseContent` | `types/interrupt.py` |
| `BeforeToolCallEvent` (`.interrupt()`, `.cancel_tool`, `.tool_use`) | `hooks/events.py` |
| `HookProvider`, `HookRegistry`, `add_callback` | `hooks/registry.py`, `hooks/__init__.py` |
| event-loop interrupt handling (`stop_reason == "interrupt"`, resume replay) | `event_loop/event_loop.py` |
| `ToolContext` (export), `ExecuteToolContext.interrupt` (not used) | `__init__.py`, `_middleware/stages.py` |
