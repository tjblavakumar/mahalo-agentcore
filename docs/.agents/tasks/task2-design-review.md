# Task 2 — Design review (fresh, no authoring context)

Reviewed: `docs/.agents/tasks/task2-design.md` and `docs/.agents/tasks/task2-hitl-decision.md`.

This review was performed by reading the actual sources the design cites —
the installed Strands 1.61.1 SDK under `agent/.venv/Lib/site-packages/strands`,
the new `agent/` package, and the mahalo-dock originals under
`D:\lavakumar.baskaran\LavaCode\AI\mahalo-dock` — rather than taking the
design's word for any claim.

## Verdict

**APPROVED.** Zero HIGH and zero MEDIUM findings. Three NIT findings below are
precision/wording fixes that do not block implementation.

The three load-bearing requirements all hold under source verification:

1. The HITL mechanism decision is grounded in the real 1.61.1 SDK — every cited
   symbol exists and the resume/replay behavior is confirmed from source, not
   asserted.
2. All six write-tool contracts (names, params, verbs, endpoints, bodies,
   success strings, already-exists handling) trace to mahalo-dock
   `execute_proposed_action` and the mock backends.
3. The 6-vs-7 discrepancy is explicitly and correctly resolved to six.

---

## Findings

### 1. NIT — HITL decision's mechanistic explanation of `end_tool_cycle()` filtering is inaccurate (conclusion is still correct)

**Where:** `task2-hitl-decision.md`, "Resume re-fires `BeforeToolCallEvent` —
verified" bullet: *"the interrupt id does not start with
`_AGENT_STREAM_INTERRUPT_ID_PREFIX` … so `end_tool_cycle()` / `to_dict()`'s
invocation-scoped filtering does not drop it before the resume applies the
response."*

**Problem:** This reasoning is backwards. Reading
`strands/interrupt.py::_InterruptState.end_tool_cycle()`, it *keeps only*
interrupts whose id starts with `_AGENT_STREAM_INTERRUPT_ID_PREFIX` **and** has a
non-None response; everything else (including our `v1:before_tool_call:…` id) is
**dropped**. So the before-tool-call interrupt does not "survive
`end_tool_cycle()` filtering" — it would be cleared if that function ran.

The real reason the interrupt persists to the resume: in
`strands/event_loop/event_loop.py::_handle_tool_execution`, when an interrupt is
raised the code calls `_stop_for_interrupts(...)` and `return`s **before**
reaching the `agent._interrupt_state.end_tool_cycle()` line (that reset only
runs on the non-interrupt completion path). `_stop_for_interrupts` persists
`PendingToolExecution` and the raised `Interrupt` stays in
`agent._interrupt_state.interrupts`. On resume, `_InterruptState.resume()` writes
the user response onto that stored interrupt by id, the loop replays the stored
assistant message (same `toolUseId`), `BeforeToolCallEvent._interrupt_id`
recomputes the identical id, and `event.interrupt()` finds the stored interrupt
now carrying a response and **returns** it.

**Why NIT not MEDIUM:** the design's *conclusion* — that the second-pass
`event.interrupt()` returns the stored response — is correct and I verified it
end to end from source. Only the stated justification is wrong, so the design is
safe to build on; the explanation should be corrected so a future reader isn't
misled.

**Fix:** Replace the `end_tool_cycle()` sentence with:

> The interrupt is not cleared before resume because the interrupt path in
> `_handle_tool_execution` calls `_stop_for_interrupts(...)` and returns **before**
> the `end_tool_cycle()` reset (which only runs on the non-interrupt completion
> path). The raised `Interrupt` therefore stays in
> `agent._interrupt_state.interrupts`; `resume()` writes the response onto it by
> id, and the replayed `BeforeToolCallEvent` recomputes the same id and returns
> that response.

### 2. NIT — `jira_update_story` PUT body shape is stated ambiguously

**Where:** `task2-design.md`, Jira contract table, `jira_update_story` row:
*"PUT `/stories/{story_id}` (body = only provided fields, under the resolved
change set)"*.

**Problem:** "under the resolved change set" is ambiguous — it could be read as a
wrapped `{"changes": {...}}` body. The verified mahalo-dock executor sends the
**bare** changes dict: `client.put(f"{url}/stories/{story_id}",
json=params.get("changes", {}))`, and the mock's `UpdateStoryRequest` (verified
in `mock-services/jira/main.py`) expects top-level `status`/`assignee`/`priority`/
`sprint_id`/`story_points`. A wrapped body would be silently ignored by the mock
(all fields None → no-op update returning the unchanged story).

**Fix:** State explicitly: *"PUT body is the bare `changes` dict (top-level
`status`/`assignee`/`priority`/`sprint_id`/`story_points`), not wrapped under a
`changes` key — i.e. `make_request(..., method="PUT", body=changes)`."* The test
plan (item 5) already says "with only provided `changes`"; make the contract
table match that intent so the implementer does not wrap it.

### 3. NIT — pre-GET seam named as `make_request` but the frozen read module actually calls it via the `_jira_request` wrapper

**Where:** `task2-design.md`, Jira contract note: *"reuses the shared read seam
`make_request(settings.jira_url, settings.jira_token,
endpoint=f"/stories/{story_id}")` … the same call the read tool `jira_get_story`
already makes."*

**Problem:** Minor imprecision. Verified in `agent/tools/jira_tools.py`:
`jira_get_story` does not call `make_request` directly — it calls the
module-private `_jira_request(endpoint=...)`, which in turn calls
`make_request(settings.jira_url, settings.jira_token, endpoint=..., params=...)`.
Functionally identical (same URL, token, default GET), so this does not affect
correctness; the wording just over-claims "the same call."

**Fix:** Either call the pre-GET through `_jira_request` for exactness, or
reword to: *"issues the same GET `jira_get_story` makes — `make_request(...)`
via the module's `_jira_request` helper."* Note `_jira_request` is module-private
to the frozen read module, so if the write module calls it directly that adds a
third imported private symbol alongside `_resolve_assignee`/`_fetch_developers`;
calling `make_request` directly (as the design currently states) avoids that and
is the cleaner choice — just fix the "same call" wording.

---

## Verified Assumptions

Each item below was confirmed by reading the cited source this review iteration.

**Strands 1.61.1 HITL mechanism (the gating decision):**
- `strands/interrupt.py` docstring is exactly *"Human-in-the-loop interrupt
  system for agent workflows."* `Interrupt(id, name, reason, response)`,
  `InterruptException`, `_InterruptState`, and `PendingToolExecution` all exist
  as described.
- `_InterruptState.resume(prompt)` requires a list of `interruptResponse`
  contents, writes `response` onto the stored `Interrupt` by `interruptId`, and
  raises `KeyError` for an unknown id — matches the design.
- `strands/types/interrupt.py::_Interruptible.interrupt(name, reason, response)`
  raises `InterruptException` on first (unanswered) call and **returns** the
  stored response on the second call (`if interrupt_.response is not None:
  return`). Both `"APPROVE"` and `"REJECT"` are non-None, so the reject path
  correctly reaches the `cancel_tool` branch.
- The module docstring carries the worked `delete_tool` approval example using
  `BeforeToolCallEvent`, `event.interrupt("for_delete_tool", reason=...)`,
  `event.cancel_tool`, `result.stop_reason == "interrupt"`, and resume via
  `{"interruptResponse": {"interruptId", "response"}}` — the design adopts this
  pattern faithfully.
- `strands/hooks/events.py::BeforeToolCallEvent` is
  `HookEvent[...] , _Interruptible` with writable `cancel_tool`,
  `selected_tool`, `tool_use`, and
  `_interrupt_id = f"v1:before_tool_call:{self.tool_use['toolUseId']}:{uuid5(NAMESPACE_OID, name)}"`
  — exactly as cited, so a constant interrupt name is sufficient for per-call
  uniqueness (design finding 4 resolution holds).
- `event_loop.py` confirms: the resume replays `PendingToolExecution.
  assistant_message` as `tool_use` **without re-calling the model**; the same
  `toolUseId` is re-processed, re-firing `BeforeToolCallEvent`. `InterruptException`
  is in the "bubble, do not wrap" set. The interrupt is preserved across the
  return/resume boundary because `_stop_for_interrupts` returns before
  `end_tool_cycle()` (see Finding 1).
- The fallback clause ("if no native mechanism exists…") correctly does not
  apply — a native mechanism exists and is used.

**Write-tool contracts (traced to mahalo-dock `agent/agent.py::execute_proposed_action`):**
- `jira_create_story` → POST `/stories`, body = full params, 201 → `✅ Story
  created successfully: **{id}** - {title}`. ✓
- `jira_update_story` → PUT `/stories/{story_id}`, body = bare `changes` dict,
  200 → `✅ Story updated successfully: **{id}** - {title}`. ✓ (see Finding 2 for
  the body-shape wording.) The mock `@app.put("/stories/{story_id}")` returns
  default 200 and echoes the full story (has `id` and `title`), so the success
  string is valid against the real mock, not merely a test fixture — the design's
  finding-7 caveat is conservative.
- `github_create_branch` → POST `/repos/{repo_id}/branches`, body
  `{"name", "from_branch"}`, 201 → `✅ Branch created successfully: **{name}**`.
  ✓ Already-exists: executor treats `status in (409, 422)` or `"already exists"`
  in text as success; the mock `create_branch` raises `BackendError(409, "Branch
  already exists")` on a duplicate (verified in
  `mock-services/github/mock_backend.py`). The design's detection on the
  `make_request` error string (`"status 409"` / `"status 422"` / `"already
  exists"`) covers this.
- `github_commit_files` → POST `/repos/{repo_id}/commits`, body
  `{"branch", "message", "files"}`, 201 → `✅ Committed {files} to **{branch}**`
  (+ optional `🔗 {url}`). ✓
- `github_open_pull_request` → POST `/repos/{repo_id}/pulls`, body
  `{"head", "base", "title" or head, "body"}`, 201 → `✅ Pull request opened:
  **#{number}** {title}` (+ optional url). ✓
- `servicenow_create_incident` → POST `/incidents`, body = full params, 201 →
  `✅ Incident opened successfully: **{id}** - {title} ({severity})`. ✓
- All write-tool signatures/defaults/docstring tags (`[WRITE ACTION - REQUIRES
  APPROVAL]`, repo-NAME discipline, full-file-contents rule,
  `_normalize_files_arg` behavior) match the mahalo-dock tool modules verbatim.
- `agent/tools/http.py::make_request` supports GET/POST/PUT and returns
  `{"error": "Request failed with status {code}: {text}"}` on non-2xx — the seam
  the write tools reuse. Confirmed.

**Count / behavior requirements:**
- 6-vs-7: `docs/CONTINUATION.md` says "7 write tools/actions" in prose but every
  enumerated list ("The 7 write actions to add", "The 7 write actions" heading)
  contains exactly six names. The design resolves to six and drops nothing.
  Correct.
- `[SYSTEM]` chaining templates: transcribed verbatim from
  `mahalo-dock/backend/app/routers/chat.py::approve_action` (create_branch,
  commit_files, open_pull_request, plus the generic fallback). Verified
  character-for-character. The design uses `p['key']` direct indexing for
  required positional params (`branch_name`, `branch`, `head`, `repo_id` — always
  present in `tool_use["input"]`) and `p.get('base', 'main')` for the defaulted
  `base`; safe.
- Prompt coverage: `agent/prompts.py` already contains "do NOT execute the change
  — they return a proposal that the user approves separately" (mechanism-agnostic),
  the CHECK-IN-CODE FLOW sub-bullets under IMPORTANT RULE 2 (`[SYSTEM]` honoring,
  full-file-contents re-emit), and "Never fabricate a confirmation." So the
  design's "no prompt change needed" conclusion is correct.
- `_resolve_assignee` and `_fetch_developers` are module-level (private) in the
  new `agent/tools/jira_tools.py` and are exercised by `test_tools_unit.py`;
  the cross-module import plan is viable and one-way (no cycle).
- `agent/strands_agent.py` defines `READ_TOOLS` and `build_agent()` returns
  `Agent(model=..., tools=READ_TOOLS, system_prompt=...)` with no hooks today, so
  adding `WRITE_TOOLS` and `hooks=[WriteApprovalHook()]` is a clean append.
- `agent/chat.py::_ask` is currently `str(agent(message)).strip()`, matching the
  design's starting point for the approval-loop driver.

**Test plan:**
- Covers the propose path proving **no HTTP write** (spy on `make_request`
  failing the test if a POST/PUT fires during propose; first `interrupt()` raises).
- Covers the approve path with **mocked HTTP** per write module (endpoint, verb,
  body, success string, including the 409 already-exists success and the
  transport-error wrap).
- Keeps Task 1 green: new tools in new modules, `strands_agent.py` only appends;
  gates on "existing unit tests remain green" rather than a hard-coded count.

## Unverified / Wrong Assumptions

- **Wrong (NIT 1):** the claim that the `v1:before_tool_call:` interrupt id
  "survives `end_tool_cycle()` filtering." `end_tool_cycle()` would drop it; the
  interrupt actually persists because the interrupt path returns before that
  reset runs. Conclusion (resume returns the stored response) is nonetheless
  correct and independently verified.
- **Not independently verified (benign):** that `AgentResult` exposes
  `.interrupts` and `.stop_reason` as attributes. Not read in the
  `agent_result` source this pass, but both are used verbatim in the SDK's own
  documented `types/interrupt.py` worked example (`result.stop_reason ==
  "interrupt"`, `for interrupt in result.interrupts`), so the design's usage
  matches the documented contract. No action required.
- **Not verified (out of scope, by design):** live end-to-end interrupt
  stop/resume through Bedrock. The design explicitly defers this to a manual
  in-session check (same policy as Task 1's single skippable integration test);
  the driver loop is unit-tested with a fake agent. Acceptable.
