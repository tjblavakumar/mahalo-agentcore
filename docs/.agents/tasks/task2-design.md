# Task 2 — Design: propose/approve human-in-the-loop write tools

## Overview

Task 2 adds the six WRITE actions to the existing local Strands agent, gated by a
human-in-the-loop approval step so no write executes until the user approves it.
It builds directly on Task 1's `agent/` package and keeps the 19 read tools and
their tests untouched. The chosen gate is the **native Strands 1.61.1 interrupt
mechanism** — a `HookProvider` on `BeforeToolCallEvent` — not mahalo-dock's
`__PROPOSAL__…__END_PROPOSAL__` string sentinel (full rationale in
`task2-hitl-decision.md`). The write tools themselves are thin, single-purpose
functions that resolve params and perform the real POST/PUT; the "propose vs
execute" concern lives entirely in one hook plus a small approval-loop driver in
the REPL. The technology stack is locked to what Task 1 already uses: Python
3.13, `strands-agents` 1.61.1 (`Agent`, `@tool`, `strands.hooks`,
`strands.interrupt`), `httpx` via the shared `agent/tools/http.py` helper,
env-driven `agent/config.py`, Bedrock Claude Sonnet 4.5. **Zero LangChain
imports.**

## Count/name discrepancy (resolved)

The handoff text says "7 write tools/actions" in one place and lists **6** names
in another. The authoritative source is the mahalo-dock tool modules, which
define exactly **six** write tools:

1. `jira_create_story`
2. `jira_update_story`
3. `github_create_branch`
4. `github_commit_files`
5. `github_open_pull_request`
6. `servicenow_create_incident`

The "7" is a miscount in CONTINUATION.md (its own enumerated list has six). **We
implement six.** The "7 write actions" heading in CONTINUATION.md even lists six
items (`create_story, update_story, create_branch, commit_files,
open_pull_request, create_incident`). No seventh action exists in the source; no
action is dropped.

## Technology stack (locked)

- **Language/runtime:** Python 3.13, the existing `agent/.venv`.
- **Agent framework:** `strands-agents` 1.61.1 — `from strands import Agent, tool`;
  `from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry`;
  `from strands.interrupt import Interrupt` (type only, for the driver).
- **HITL:** native interrupt via `BeforeToolCallEvent.interrupt()` +
  `cancel_tool`; resume via `interruptResponse` content blocks.
- **HTTP:** `agent/tools/http.py::make_request` (already supports GET/POST/PUT).
- **Config:** `agent/config.py::settings` (env-driven base URLs + tokens).
- **Model:** Bedrock `us.anthropic.claude-sonnet-4-5-20250929-v1:0`,
  `read_timeout=300s` (unchanged from Task 1).
- **No new third-party dependencies.** `requirements.txt` is unchanged.

## Module layout and wiring

New files (mirroring the Task 1 per-service tool-module convention):

- `agent/tools/jira_write_tools.py` — `jira_create_story`, `jira_update_story`,
  exporting `JIRA_WRITE_TOOLS`.
- `agent/tools/github_write_tools.py` — `github_create_branch`,
  `github_commit_files`, `github_open_pull_request`, exporting
  `GITHUB_WRITE_TOOLS`. Also holds the ported `_normalize_files_arg` helper.
- `agent/tools/servicenow_write_tools.py` — `servicenow_create_incident`,
  exporting `SERVICENOW_WRITE_TOOLS`.
- `agent/approval.py` — the `WriteApprovalHook(HookProvider)` and the module-level
  `WRITE_TOOL_NAMES: set[str]` + a `build_proposal(tool_use) -> dict` helper used
  for the human-readable approval summary.

Why separate `*_write_tools.py` modules rather than extending the existing
`jira_tools.py` etc.: the read modules were ported to be byte-for-byte faithful
to Task 1 and are frozen by passing tests; keeping writes in sibling modules
keeps each file single-concern and avoids touching green code. The read tools and
write tools for one service still share `make_request` and `settings`.

**Assignee-resolution reuse (resolves review finding 1).** `jira_update_story`
needs the same name→dev-id resolution the read tools use. Both `_resolve_assignee`
and its dependency `_fetch_developers` are underscore-prefixed, **module-private**
functions local to `agent/tools/jira_tools.py` (confirmed by reading the file);
there is no neutral shared module for them today. We choose the lower-risk option:

> **`jira_write_tools.py` imports them directly from the frozen read module:**
> `from agent.tools.jira_tools import _resolve_assignee, _fetch_developers`.

Chosen over hoisting both helpers into a new `agent/tools/jira_common.py` because
hoisting would **edit** `jira_tools.py`, contradicting the "don't touch the green,
passing read modules" rationale and risking the Task 1 suite. The tradeoff we
accept is an explicit, documented new dependency direction: `jira_write_tools.py`
→ `jira_tools.py` (a write module importing two private symbols from a read
module). This is a one-way import with no cycle (the read module does not import
the write module), and the symbols are pure functions over `make_request`, so the
coupling is low. If a later task needs these helpers in a third place, hoist them
to `jira_common.py` then — out of scope here.

Changes to existing files:

- `agent/strands_agent.py`:
  - Import the three `*_WRITE_TOOLS` lists and `WriteApprovalHook`.
  - Add `WRITE_TOOLS = [*JIRA_WRITE_TOOLS, *GITHUB_WRITE_TOOLS,
    *SERVICENOW_WRITE_TOOLS]`.
  - `build_agent()` registers `tools=[*READ_TOOLS, *WRITE_TOOLS]` and
    `hooks=[WriteApprovalHook()]`. Nothing else in `build_agent` changes; the
    `BedrockModel` construction stays offline-safe and lazy.
- `agent/prompts.py`: **already contains the full propose/approve + behavioral
  rule language** (it was ported verbatim from mahalo-dock in Task 1, write-tool
  references intentionally intact). See "Prompt changes" below for the one small,
  mechanism-specific adjustment.
- `agent/chat.py`: add the approval-loop driver (see "REPL / approval driver").

## The HITL flow, concretely

### Propose path (model calls a write tool)

1. The model, following the prompt, calls e.g. `github_create_branch(repo_id=
   "payment-service", branch_name="feature/PAY-109-crypto", from_branch="main")`.
2. Before the tool body runs, `BeforeToolCallEvent` fires. `WriteApprovalHook`:
   - Returns immediately (no-op) if `event.tool_use["name"]` is **not** in
     `WRITE_TOOL_NAMES` (all read tools pass straight through).
   - For a write tool, builds a proposal summary from `event.tool_use` and calls
     `response = event.interrupt("write_approval", reason=proposal)`. We pass a
     **stable literal name** (`"write_approval"`) rather than embedding the
     tool-use id in the name (resolves review finding 4): per-call uniqueness
     already comes from `_interrupt_id` = `f"v1:before_tool_call:{toolUseId}:
     uuid5(name)"`, which hashes `toolUseId` into the id. A constant name per
     call is sufficient and avoids double-encoding the id. The positional form
     matches the SDK's own worked example (`event.interrupt("for_delete_tool",
     reason=...)`).
   - On the **first** pass there is no stored response, so `interrupt()` raises
     `InterruptException`; the agent loop stops and `agent(...)` returns an
     `AgentResult` with `stop_reason == "interrupt"` and `result.interrupts`
     holding our `Interrupt` (its `.reason` is the human-readable proposal, its
     `.id` is the opaque resume token).
3. **No HTTP write happens on this path** — the tool body never executed, so no
   POST/PUT was issued. (The model may have called read tools first, e.g.
   `github_list_repos`; those executed normally. Only the write body is gated.)

The proposal summary (`reason`) is a dict, mirroring mahalo-dock's proposal shape
so downstream/demo wording stays familiar:
`{"action", "system", "params", "description"}`, where `description` is the same
human sentence the old sentinel carried (e.g. *"Create branch
'feature/PAY-109-crypto' in payment-service from main"*). `build_proposal` derives
`action`/`system` from the tool name and copies `tool_use["input"]` into `params`.

### Approve path (user says yes)

1. The driver shows `interrupt.reason["description"]` and asks approve/reject.
2. On **approve**, it resumes: `agent([{ "interruptResponse": {"interruptId":
   interrupt.id, "response": "APPROVE"}}])`.
3. The loop replays; `BeforeToolCallEvent` fires again for the same tool call,
   `event.interrupt(...)` now **returns** `"APPROVE"`, the hook does nothing to
   cancel, and the **tool body runs** — performing the real POST/PUT via
   `make_request` and returning the success string to the model, which composes
   the final answer.
4. On **reject**, the driver resumes with `response="REJECT"`; the hook sees a
   non-approve response and sets `event.cancel_tool = "Write rejected by user."`.
   The framework turns that into an error-status tool result, **no HTTP write
   runs**, and the model reports the cancellation.

### Chaining (branch → commit → PR) and the `[SYSTEM]` signal

Each write is a separate tool call and therefore a separate interrupt/approval.
To stop the agent re-proposing a completed step, the driver appends a `[SYSTEM]`
message to the conversation **after each approved write**, reusing mahalo-dock's
exact wording (from `routers/chat.py::approve_action`, read and transcribed
below).

**Source of truth for the signal (resolves review finding 2).** The driver does
**not** try to read the executed tool from the post-resume `AgentResult`: verified
against the SDK, `AgentResult.message` after a resume is the model's follow-up
*text*, not a structured record of which tool body ran, so it cannot reliably
yield the action name or params. Instead the driver captures the proposal dict —
`itr.reason`, shaped `{"action", "system", "params", "description"}` — **before**
it resumes, remembers the user's decision for that interrupt, and **after** the
resume completes emits the `[SYSTEM]` message keyed on `proposal["action"]`,
substituting fields from `proposal["params"]` (which is a copy of
`tool_use["input"]`, so its keys are the tool's own parameter names:
`repo_id`, `branch_name`, `branch`, `head`, `base`). It appends **only when the
user approved**; on reject it appends nothing.

The three exact `[SYSTEM]` f-string templates, transcribed verbatim from
mahalo-dock `routers/chat.py` (param names remapped to the proposal's
`params` keys — identical to the tool signatures):

```python
# proposal["action"] == "create_branch"  (params: repo_id, branch_name)
f"[SYSTEM] The user APPROVED and the branch '{p['branch_name']}' "
f"now exists in repo '{p['repo_id']}'. Do NOT propose creating it "
f"again. Next, if the user asked to commit code, propose "
f"github_commit_files to that branch with the full file contents you "
f"prepared earlier."

# proposal["action"] == "commit_files"  (params: repo_id, branch)
f"[SYSTEM] The user APPROVED and the files were committed to branch "
f"'{p['branch']}' in repo '{p['repo_id']}'. Do NOT propose "
f"committing again. Next, if the user wants a PR, propose "
f"github_open_pull_request from '{p['branch']}' into main."

# proposal["action"] == "open_pull_request"  (params: repo_id, head, base)
f"[SYSTEM] The user APPROVED and a pull request was opened from "
f"'{p['head']}' into '{p.get('base', 'main')}' in repo "
f"'{p['repo_id']}'. The check-in flow is complete."
```

For the non-chaining writes (`jira_create_story`, `jira_update_story`,
`servicenow_create_incident`) the driver uses mahalo-dock's generic fallback,
`f"[SYSTEM] The user approved and the '{action}' action was executed."`, so every
approved write leaves a history breadcrumb even though only the GitHub chain needs
step-sequencing.

Because this agent holds history in the single long-lived `Agent` instance (the
REPL reuses one agent across turns), appending to `agent.messages` is how the next
turn sees the signal. The prompt already instructs the model to honor `[SYSTEM]`
messages — specifically the CHECK-IN-CODE FLOW sub-bullets under IMPORTANT RULE 2
of the ported BASE_PROMPT (resolves review finding 5) — so no prompt change is
needed for this.

## Exact tool contracts (names, params, verbs, endpoints)

Params, defaults, docstrings, and behavioral rules are ported **verbatim** from
the mahalo-dock tool modules; only the decorator (`langchain_core.tools.tool` →
`strands.tool`), the request seam (`_make_*_request` → shared `make_request`),
and the body (return a proposal string → perform the real write) change. Verbs
and endpoints are confirmed against both mahalo-dock
`agent/agent.py::execute_proposed_action` and the mock-service route tables.

Base URL/token per service come from `settings` (`settings.jira_url` +
`settings.jira_token`, etc.), exactly like the read tools.

### Jira (`settings.jira_url`, `settings.jira_token`)

| Tool | Signature (defaults) | Verb | Endpoint | Success |
| --- | --- | --- | --- | --- |
| `jira_create_story` | `(project_id, title, description, priority="medium", story_points=0, assignee=None)` | POST | `/stories` (body = all params) | 201 → `"✅ Story created successfully: **{id}** - {title}"` |
| `jira_update_story` | `(story_id, status=None, assignee=None, priority=None, story_points=None, sprint_id=None)` | PUT | `/stories/{story_id}` (body = only provided fields, under the resolved change set) | 200 → `"✅ Story updated successfully: **{id}** - {title}"` (the success string reads `data["id"]`/`data["title"]` from the PUT 200 body, matching the mahalo-dock executor — the mock is expected to echo `{id, title}` on a successful update, so test fixtures must shape the mocked PUT return accordingly) |

`jira_update_story` keeps its ported guards: first a **pre-GET** that reuses the
shared read seam `make_request(settings.jira_url, settings.jira_token,
endpoint=f"/stories/{story_id}")` (defaults to GET — it is the same call the read
tool `jira_get_story` already makes, no new helper) to confirm existence
(error/404 in the result → *"Story '…' was not found, so it cannot be
updated."*);
resolve a name assignee to a dev-id via the shared `_resolve_assignee`
(unresolved → list developers); build `changes` from only the provided fields;
*"No changes specified"* when empty. **These checks are the propose-time
parameter validation** and run inside the tool body, which only executes after
approval — so on reject none of them (and no PUT) run. (Note: the existence GET is
a read and is acceptable to run on the approve pass; see "Edge cases".)

Create-story docstring tag retained: *"[WRITE ACTION - REQUIRES APPROVAL]"*.

### GitHub (`settings.github_url`, `settings.github_token`)

| Tool | Signature (defaults) | Verb | Endpoint | Body |
| --- | --- | --- | --- | --- |
| `github_create_branch` | `(repo_id, branch_name, from_branch="main")` | POST | `/repos/{repo_id}/branches` | `{"name": branch_name, "from_branch": from_branch}` |
| `github_commit_files` | `(repo_id, branch, message, files)` | POST | `/repos/{repo_id}/commits` | `{"branch", "message", "files": normalized}` |
| `github_open_pull_request` | `(repo_id, head, base="main", title="", body="")` | POST | `/repos/{repo_id}/pulls` | `{"head", "base", "title": title or head, "body"}` |

- `github_commit_files.files` is normalized by the ported `_normalize_files_arg`
  (tolerates a JSON string, a single dict, or a list of dicts; keeps
  `{"path", "content"}`, content coerced to a string, empty if missing). The
  docstring **retains** the "COMPLETE file text, never a diff" rule and the
  re-emit-full-code instruction.
- All three retain the real-repo-NAME discipline docstring (*"repo_id MUST be a
  real repository NAME from github_list_repos … do NOT invent repo-1/repo-4"*).
- Success strings match mahalo-dock: branch → `"✅ Branch created successfully:
  **{name}**"`; commit → `"✅ Committed {files} to **{branch}**"` (+ optional
  `🔗 {url}`); PR → `"✅ Pull request opened: **#{number}** {title}"` (+ optional
  `🔗 {url}`).

**Branch-already-exists = success (resilience).** Confirmed: the GitHub mock's
`create_branch` returns **HTTP 409 "Branch already exists"** on a duplicate
(`mock-services/github/mock_backend.py`). The shared `make_request` maps any
non-2xx to `{"error": "Request failed with status 409: …Branch already exists…"}`.
`github_create_branch` MUST detect this and return a **success** string, not an
error, so the chain can proceed to commit — mirroring mahalo-dock's handling that
treated 409/422/"already exists" as success:

```
data = make_request(..., method="POST", endpoint=f"/repos/{repo_id}/branches", body=...)
if "error" in data:
    err = data["error"].lower()
    if "status 409" in err or "status 422" in err or "already exists" in err:
        return (f"✅ Branch **{branch_name}** already exists — reusing it. "
                f'Reply "commit the code" to proceed.')
    return f"❌ Failed to create branch: {data['error']}"
return f"✅ Branch created successfully: **{data['name']}**"
```

### ServiceNow (`settings.servicenow_url`, `settings.servicenow_token`)

| Tool | Signature (defaults) | Verb | Endpoint | Success |
| --- | --- | --- | --- | --- |
| `servicenow_create_incident` | `(title, affected_service, severity="P3", description="", assignee=None, linked_deployment=None)` | POST | `/incidents` (body = all params) | 201 → `"✅ Incident opened successfully: **{id}** - {title} ({severity})"` |

Docstring retains the affected-service enumeration (payment/cart/auth/product/
order-service), severity P1–P4 meaning, and the `[WRITE ACTION - REQUIRES
APPROVAL]` tag.

## Error handling (per operation)

Every write tool uses the single `make_request` seam, which already returns
`{"error": "Request failed with status {code}: {text}"}` on any non-2xx and
`{"error": "Unsupported method: …"}` for a bad verb. The tools translate that into
user-facing text and never raise, matching the Task 1 read-tool convention
(return a string, let the model relay it).

| Operation | Failure condition | Recoverable? | Caller receives | Logged? |
| --- | --- | --- | --- | --- |
| all writes | non-2xx from mock (network/4xx/5xx) | fatal for that step | `"❌ Failed to {verb} …: {error text}"` | not logged by the tool (mahalo-dock didn't); the agent surfaces it. Transport exceptions from `httpx` are the one gap — see below. |
| `github_create_branch` | 409/422/"already exists" | **recoverable → treated as SUCCESS** | `"✅ Branch … already exists — reusing it."` | no |
| `jira_update_story` | story GET returns error (missing) | fatal for the step | `"Story '…' was not found, so it cannot be updated."` | no |
| `jira_update_story` | assignee unresolvable | fatal for the step | `"Could not resolve assignee '…'. Available developers: …"` | no |
| `jira_update_story` | no fields provided | fatal (nothing to do) | `"No changes specified for {story_id}…"` | no |
| any write | user rejects at approval | expected | hook sets `cancel_tool="Write rejected by user."` → error-status tool result → model says it was cancelled | no |
| any write | `httpx` raises (e.g. connection refused — tunnel down) | fatal | **New vs Task 1:** wrap the body's `make_request` call so a transport exception becomes `{"error": "Request failed: {exc}"}`-style text rather than crashing the agent mid-approve. The read tools never added this, but a write is the first place a mid-run exception would surface post-approval. Implement by catching `httpx.HTTPError`/`OSError` around the write call and returning `"❌ Failed to {verb}: {exc}"`. |

The approval hook itself cannot "fail" in a way that writes data: if the user
never resumes, the agent simply stays stopped at `stop_reason == "interrupt"`;
if they reject, `cancel_tool` guarantees the body never runs.

## Input validation (per external input)

Inputs are the model-supplied tool arguments (indirectly user-driven). Rules:

- `jira_create_story`: `project_id`, `title`, `description` required (positional,
  no default); `priority` ∈ {critical, high, medium, low} documented but not
  enforced client-side (the mock is source of truth — invalid values surface as a
  non-2xx handled above); `story_points` int, default 0; `assignee` optional
  dev-id or None. On a missing required arg the model is instructed (prompt rule
  3) to ask the user for just that detail before calling.
- `jira_update_story`: `story_id` required; all change fields optional; existence
  validated by the pre-GET; assignee validated by `_resolve_assignee`; empty
  change set rejected with a message. These are the owning validations.
- `github_create_branch`: `repo_id`, `branch_name` required; `from_branch`
  default "main". `repo_id` validity is enforced by the mock (404 "Repository not
  found" → error text); the docstring forbids invented names and the prompt rule
  8 enforces "list first."
- `github_commit_files`: `repo_id`, `branch`, `message`, `files` required; `files`
  normalized/validated by `_normalize_files_arg` (entries without a path dropped;
  content coerced to str). An empty normalized list still proposes (count 0) and
  the mock decides — matching mahalo-dock behavior.
- `github_open_pull_request`: `repo_id`, `head` required; `base` default "main";
  `title` defaults to `head` if empty; `body` default "".
- `servicenow_create_incident`: `title`, `affected_service` required; `severity`
  default "P3"; others optional.

**Validation-layer ownership:** the mock services own domain validity (does the
repo/story exist, is severity legal) and remain the single source of truth —
returning a non-2xx we translate to text. The tools own only shape/normalization
(files normalization, update-story existence+assignee resolution, empty-change
guard) and the already-exists resilience. We deliberately do **not** duplicate the
mock's domain rules client-side, to avoid drift.

## Significant invariants and who enforces them

- **"No write executes before approval."** Enforced by the framework at the
  `BeforeToolCallEvent` boundary: the POST/PUT lives in the tool body, which runs
  only after `interrupt()` returns an approve response; on reject `cancel_tool`
  prevents the body. The tool code cannot bypass this because the gate is
  upstream of it. This is the core safety invariant and it lives in
  `WriteApprovalHook`, not in the tools.
- **"branch already exists = success."** Owned by `github_create_branch` (it is a
  per-tool semantic, not a framework concern).
- **"never re-propose a completed chain step."** Owned jointly by the driver (emits
  the `[SYSTEM]` signal) and the model (honors it per the CHECK-IN-CODE FLOW
  sub-bullets under IMPORTANT RULE 2 of the ported BASE_PROMPT). The agent's
  single long-lived message history is the carrier.
- **"commit carries full file contents."** Owned by the prompt (instructs re-emit)
  and `_normalize_files_arg` (preserves whatever content is passed; never diffs).
- **identity: current user = dev-6 for me/my.** Unchanged from Task 1 — enforced by
  the `CURRENT USER IDENTITY` block appended in `build_agent`.

## Prompt changes needed in `agent/prompts.py`

The ported BASE_PROMPT already says the write tools "do NOT execute the change —
they return a proposal that the user approves separately," describes the
check-in flow, the `[SYSTEM]` honoring, the full-file-contents rule, repo-NAME
discipline, people→dev-id resolution, and UPDATE-vs-CREATE. That language is
**mechanism-agnostic** ("return a proposal … approved separately") and remains
accurate under the interrupt mechanism — from the model's view calling the tool
still *is* proposing, and approval still happens out-of-band. So **no behavioral
rule is removed or reworded.**

One **minimal** addition only if end-to-end testing shows the model narrating a
fake confirmation after the interrupt: keep the existing "Never fabricate a
confirmation or claim the action was done" sentence (already present) — it covers
this. Therefore the baseline plan is **no change to `prompts.py`**; it is already
correct for the interrupt mechanism. (We call this out explicitly so a reviewer
doesn't expect a prompt diff.)

## REPL / approval driver (`agent/chat.py`)

Task 1's `_ask` is `str(agent(message))`. For Task 2 the driver must detect an
interrupt and loop:

```
def _ask(agent, message):
    result = agent(message)
    while getattr(result, "stop_reason", None) == "interrupt":
        responses = []
        approved = []  # (proposal_dict) captured BEFORE resume
        for itr in result.interrupts:
            proposal = itr.reason  # {"action","system","params","description"}
            print(f"\nPROPOSED: {proposal['description']}")
            ans = input("Approve this write? [y/N] ").strip().lower()
            decision = "APPROVE" if ans in {"y", "yes"} else "REJECT"
            if decision == "APPROVE":
                approved.append(proposal)       # remember what we approved
            responses.append({"interruptResponse": {"interruptId": itr.id,
                                                     "response": decision}})
        result = agent(responses)               # replay + run the approved body
        for proposal in approved:               # emit [SYSTEM] only on approve
            _emit_system_signal(agent, proposal)  # keyed on proposal["action"]
    return str(result).strip()
```

- The source of truth for the `[SYSTEM]` signal is the **proposal dict captured
  before the resume** (`itr.reason`), not the post-resume `AgentResult` — see
  "Chaining" above and review finding 2. `_emit_system_signal(agent, proposal)`
  switches on `proposal["action"]` and substitutes `proposal["params"]` into the
  verbatim templates, appending one assistant-role `[SYSTEM]` message to
  `agent.messages`.
- `result.interrupts` and `result.stop_reason` are read off the `AgentResult`
  (confirmed by the SDK's own `interrupt.py` example: `result.stop_reason ==
  "interrupt"`, iterate `result.interrupts`, re-invoke with a list of
  `interruptResponse` contents; `_InterruptState.resume` requires exactly that
  list shape).
- The single-shot path (`python -m agent.chat "…"`) uses the same `_ask`, so a
  one-off write command is interactive at the approval prompt — acceptable for the
  demo CLI; non-interactive callers (the API in a later task) will drive the same
  resume programmatically.

## Edge cases

- **Read tools interleaved before a write** (e.g. `github_list_repos` then
  `github_create_branch`): only the write's `BeforeToolCallEvent` interrupts; the
  reads already executed. Correct and desired.
- **Multiple write tool-uses in one assistant turn:** `result.interrupts` can hold
  more than one; the driver prompts for each and resumes with a list of
  responses. In practice the prompt drives one write per turn, but the loop
  handles N.
- **Re-proposing a done step:** prevented by the `[SYSTEM]` signal + the
  CHECK-IN-CODE FLOW sub-bullets under IMPORTANT RULE 2;
  if the model ignores it and re-proposes `create_branch`, the 409→success
  resilience still yields a benign "already exists" rather than an error.
- **`jira_update_story` pre-GET on the approve pass:** the existence check is a
  read and runs when the body runs (post-approval). This is intentional (it
  validates against live state at execution time) and issues no write. On the
  propose pass the body hasn't run, so even the GET hasn't fired — the approval
  summary is built from `tool_use` args only, so the summary cannot show the
  resolved assignee name the way the old sentinel did. **Decision:** accept the
  slightly less rich summary (shows raw args) to keep the propose path write-free
  and side-effect-light; the full resolution still happens at execute time. If a
  richer summary is later required, the hook can do read-only lookups — but that
  is out of scope here.
- **Tunnel down at approve time:** the post-approval `make_request` raises a
  transport error; the wrapped write returns `"❌ Failed to …"` text (see error
  handling) instead of crashing the loop.
- **User never answers:** agent stays at `stop_reason == "interrupt"`; nothing is
  written. Safe by default.

## Test plan

New file `agent/tests/test_write_tools_unit.py`, same style as
`test_tools_unit.py` (monkeypatch the shared `make_request` seam; assert endpoint,
verb, body, and byte-for-byte output). All offline, no network, no AWS.

**Propose path — proves NO HTTP write.** Unit-test `WriteApprovalHook` in
isolation with a fake `BeforeToolCallEvent`-shaped object:

1. For each write tool name, `hook.before_tool_call(event)` calls
   `event.interrupt(...)`; the first (unanswered) call raises `InterruptException`
   (assert it propagates) and `build_proposal` produced the right
   `{action, system, params, description}`.
2. Assert that on the propose path the tool **body is never invoked** — structured
   so the write tools' `make_request` is monkeypatched to a spy that fails the
   test if called with a POST/PUT during a propose. (The hook runs before the
   body, so a correctly-driven propose records zero write calls.)
3. For a non-write tool name, the hook is a no-op (no interrupt raised).

**Approve path — mocked HTTP write.** Monkeypatch `make_request` per write module
and call the tool body directly (this is what runs after resume):

4. `jira_create_story(...)` → asserts POST `/stories`, body = params, and the
   success string on a 201-shaped `{"id","title"}` return.
5. `jira_update_story(...)` → asserts the pre-GET `/stories/{id}`, then PUT
   `/stories/{id}` with only provided `changes`; plus the not-found, unresolved-
   assignee, and empty-change branches.
6. `github_create_branch` → POST `/repos/{repo}/branches`; **plus the
   already-exists case**: feed `{"error":"Request failed with status 409: Branch
   already exists"}` and assert the SUCCESS "already exists — reusing it" string.
7. `github_commit_files` → POST `/repos/{repo}/commits`; `_normalize_files_arg`
   unit cases (JSON string, single dict, list, missing path dropped, content
   coerced to str).
8. `github_open_pull_request` → POST `/repos/{repo}/pulls`, `title` defaulting to
   `head`.
9. `servicenow_create_incident` → POST `/incidents`, success string with
   `{id,title,severity}`.
10. Transport-error wrap: `make_request` raising `httpx.HTTPError` → tool returns
    the `"❌ Failed to …"` string, does not raise.

**Reject path.** Drive the hook with a resume response `"REJECT"`; assert it sets
`event.cancel_tool` to the rejection message and does **not** run the body.

**Resume/driver.** A light test of `_ask`'s loop using a fake agent that returns
an interrupt result once then a normal result: assert it builds the
`interruptResponse` with the correct `interruptId`, re-invokes, and emits the
`[SYSTEM]` signal into `agent.messages` on approve (and not on reject).

**Task 1 suites stay green.** `test_tools_unit.py` and `test_integration_live.py`
are not modified; the new tools live in new modules and `strands_agent.py` only
appends to the tool/hook lists. Run `python -m pytest agent/tests` → **all
existing unit tests remain green** (the Task 1 read-tool suite is unchanged) and
the live integration test still skips gracefully when the tunnel/creds are
absent. We assert "existing unit tests remain green" rather than gating on a
hard-coded count, since this step adds a new test file (resolves review
finding 8).

**Live end-to-end (manual, tunnel + `lava` SSO up).** Not a committed test (same
policy as Task 1's single skippable integration test). Verify once in-session:
"create a feature branch for PAY-109" → prints a PROPOSAL and writes nothing
(confirm via `github_list` showing the branch absent); approve → branch appears;
then "commit the code" → propose → approve → commit; then "open a PR" → propose →
approve → PR appears. Confirm the `[SYSTEM]` signal prevents a re-proposed branch.

### Testability notes

- The hook is a plain object with one method taking an event; unit-testable with a
  tiny fake event exposing `tool_use`, `interrupt()`, and a settable
  `cancel_tool`. No agent or network needed → fast and deterministic.
- The write tool bodies are pure "resolve → make_request → format," identical
  seam to Task 1, so they unit-test the same way (monkeypatch `make_request`).
- The only genuinely integration-level behavior (real interrupt stop/resume
  through the event loop) is covered by the manual live check; the driver-level
  resume logic is unit-tested with a fake agent so we don't need Bedrock to prove
  the loop shape. This split keeps the suite offline-green while still exercising
  every branch.

---

## Responses to design review (`task2-design-review.json`, verdict CHANGES_REQUESTED)

All eight findings addressed; none backlogged or ignored. Each fix was verified
against real source before writing.

- **Finding 1 (MEDIUM — `_resolve_assignee`/`_fetch_developers` reuse
  unspecified).** ADDRESSED. Confirmed in `agent/tools/jira_tools.py` that both
  are module-private. Chose the explicit cross-module import
  `from agent.tools.jira_tools import _resolve_assignee, _fetch_developers` over
  hoisting to a new `jira_common.py`, because hoisting would edit the frozen read
  module. Documented the new one-way `jira_write_tools.py → jira_tools.py`
  dependency and why it is low-risk. See "Module layout and wiring →
  Assignee-resolution reuse."

- **Finding 2 (MEDIUM — approval-driver source of truth ambiguous).** ADDRESSED.
  Dropped the "read from resumed `AgentResult`" option; the driver now captures
  `itr.reason` (the `{action, system, params, description}` proposal) BEFORE
  resuming, remembers approvals, and emits the `[SYSTEM]` message keyed on
  `proposal["action"]`/`proposal["params"]` only on approve. Pasted the three
  exact f-string templates (transcribed verbatim from mahalo-dock
  `routers/chat.py` lines 205–225, which I opened and read this iteration) plus
  the generic fallback. Updated the `_ask` pseudocode to match. See "Chaining"
  and "REPL / approval driver."

- **Finding 3 (MEDIUM — resume re-fire stated as verified but only inferred).**
  ADDRESSED in `task2-hitl-decision.md`. Read `strands/interrupt.py` in full and
  cited the concrete replay path: `_InterruptState.resume()` writes the response
  onto the stored `Interrupt` by `interruptId`; `PendingToolExecution` replays
  the stored assistant message instead of re-calling the model; and the
  per-`toolUseId` id (`v1:before_tool_call:…`) is NOT invocation-scoped, so it
  survives `end_tool_cycle()` filtering and the same `BeforeToolCallEvent`
  recomputes the identical id and returns the response. Now evidence-backed, not
  inferred; the live check remains as a secondary confirmation.

- **Finding 4 (NIT — interrupt name form).** ADDRESSED. Switched to a stable
  literal name `"write_approval"` (positional, matching the SDK example);
  per-call uniqueness comes from `_interrupt_id` hashing `toolUseId`. See
  "Propose path" step 2.

- **Finding 5 (NIT — "rule 2" label imprecise).** ADDRESSED. Verified in
  `agent/prompts.py` that the `[SYSTEM]`-honoring instruction lives in the
  CHECK-IN-CODE FLOW sub-bullets under IMPORTANT RULE 2; updated every reference
  ("Chaining", invariants, edge cases) to use that precise wording.

- **Finding 6 (NIT — pre-GET seam not named).** ADDRESSED. Stated that the
  existence check reuses `make_request(settings.jira_url, settings.jira_token,
  endpoint=f"/stories/{story_id}")` (default GET — the same call `jira_get_story`
  makes), no new helper. See the Jira contract note.

- **Finding 7 (NIT — update success string depends on 200 body carrying
  id/title).** ADDRESSED. Added a parenthetical in the Jira contract table that
  the success string reads `data["id"]`/`data["title"]` from the PUT 200 body
  (matching the mahalo-dock executor), so test fixtures shape the mocked return
  accordingly.

- **Finding 8 (NIT — "13 unit tests" hard-coded).** ADDRESSED. Changed the gate
  to "all existing unit tests remain green" rather than a hard-coded count, since
  this step adds a new test file.
