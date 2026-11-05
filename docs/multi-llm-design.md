# Multi-LLM per SDLC activity — Technical Design (First Slice)

## Overview

This design adds a credible, **independent** code-review stage to the mahalo
agent and the plumbing to select the model that runs it. Today one
`BedrockModel` (Claude Sonnet 4.5) is built once in
`agent/strands_agent.py::_build_bedrock_model` and drives every activity; the
agent has no separate reviewer, so any "I reviewed it" claim is the generator
grading itself. We introduce a **second Strands `Agent` bound to its own
`BedrockModel`** that reviews generated code read-only before any write is
proposed, a **per-persona model configuration** reusing the existing dashboard
DynamoDB pattern, a **structured `stages` array** on the chat response so the UI
can show per-stage progress and a "who-did-what" trust line, and a scoped IAM
grant for the new review model. The HITL write gate (`WriteApprovalHook` over the
six write tools) is untouched: the reviewer has no write tools and never reaches
the interrupt path.

The technology stack is **locked** by the existing system and unchanged by this
design: Python 3.13 + `strands-agents` 1.61.1 (`Agent`, `BedrockModel`) on
Amazon Bedrock AgentCore Runtime (`bedrock_agentcore.runtime.BedrockAgentCoreApp`),
a FastAPI thin API on a Lambda Function URL (`AuthType=NONE`), a Next.js
static-export frontend behind CloudFront, DynamoDB for per-persona persistence,
and AWS CDK (`infra-cdk/`) for infrastructure. No new frameworks are introduced.

The slice is intentionally minimal: Settings model config + **one** code-review
stage + visible progress + the trust line. The security stage and chat
suggest-and-confirm are future work.

> **Revision note.** This is a revision addressing the review at
> `.agents/tasks/multi-llm/design-review.md` (verdict CHANGES_REQUESTED, 1 HIGH /
> 4 MEDIUM / 2 NIT). Every finding is resolved below and summarised in
> **"Responses to the design review"** at the end. Invoke-access and
> base-model evidence for §A and the IAM grant is captured in
> `.agents/tasks/multi-llm/bedrock-ping-evidence.md`.

---

## A. Bedrock model allow-list (verified, not assumed)

**Evidence (corroborated — finding 4).** Against profile `lava` / region
`us-east-1` I ran, read-only: `bedrock list-inference-profiles --type-equals
SYSTEM_DEFINED` (all candidates show `ACTIVE`), `bedrock get-inference-profile`
(to enumerate the base foundation-model fan-out for the IAM grant, §Infra), and —
crucially — a real `bedrock-runtime converse` "ping" (5 max tokens) against each
candidate to prove true *invoke* access rather than mere listing. The full
captured output (command shape, `stopReason` per model, and the
`get-inference-profile` base-model ARNs) lives in
`.agents/tasks/multi-llm/bedrock-ping-evidence.md`, the committed artifact the
review asked for. Summary:

| Model (system inference profile id) | list status | converse result | role in this slice |
| --- | --- | --- | --- |
| `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | ACTIVE | success (`end_turn`) | Code-gen default (unchanged; current `BEDROCK_MODEL_ID`) |
| `us.amazon.nova-lite-v1:0` | ACTIVE | success (`max_tokens`) | **Review default** — cheap, cross-vendor |
| `us.amazon.nova-micro-v1:0` | ACTIVE | success (`max_tokens`) | Review alt — cheapest, cross-vendor |
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | ACTIVE | success (`max_tokens`) | Review alt — cheap, same-vendor |
| `us.anthropic.claude-opus-4-5-20251101-v1:0` | ACTIVE | success (`max_tokens`) | **Dropped from the slice allow-list** (costly, never the default) |

A successful `converse` (a non-`AccessDeniedException` reply carrying a
`stopReason`) is the proof of invoke access; listing alone would not be. All four
slice candidates returned a successful converse.

**Opus decision (resolves finding 4).** Opus 4.5 *was* pinged and is invocable,
but it is **removed from the slice allow-list**: it is expensive, the design never
defaults to it, and a selectable-but-costly option adds an IAM grant and a
spend-risk this first slice does not need. Keeping every offered model both
invoke-verified *and* IAM-granted means there is no selectable model that can
AccessDenied at runtime. Opus can be added later by the same two-ARN grant pattern
if a demand arises.

**Decision — the allow-list (server-side constant):**

- **Code generation:** `us.anthropic.claude-sonnet-4-5-20250929-v1:0` only
  (default, current behaviour). Code-gen is **not** configurable this slice
  (FR-12; see finding 7 / §B.2), so this entry is fixed and shown read-only in
  the UI.
- **Code review:** `us.amazon.nova-lite-v1:0` (**default**),
  `us.amazon.nova-micro-v1:0`, `us.anthropic.claude-haiku-4-5-20251001-v1:0`.
- **Security:** the same three review options are presented, but the control is
  **inert** this slice (FR-5) — persisted, never executed.

**Why Nova Lite is the review default.** It is (a) *confirmed invocable*, (b)
low-cost (satisfies NFR-2 and the demo's "cheaper is fine"), and (c)
**cross-vendor** relative to the Anthropic generator, which is the strongest
independence story — a different lab's model reviewing Anthropic-generated code
is the most credible "it is not grading its own work" claim. Claude Haiku 4.5 is
offered for users who want a same-vendor but still-distinct reviewer.

The allow-list lives as a single constant shared conceptually by three layers:
`agent/model_config.py` (the Runtime's canonical enum + id↔label map and the
server-side validator), mirrored as a small static TypeScript array in the
frontend for the dropdowns, and enforced on the server (thin-API `PUT` validator)
so a hand-crafted request to the `AuthType=NONE` thin API can never make the
Runtime invoke an off-list model (NFR-6). We do **not** enumerate Bedrock from the
browser or the Lambda at request time; the curated constant is the contract.

---

## B. Per-persona vs global configuration — **per-persona, reusing the dashboard store**

**Decision.** Model configuration is **per-persona**, persisted in a **new tiny
DynamoDB store** that reuses the exact pattern already proven by
`api/app/routers/dashboard.py` + `mahalo-dashboards`.

**Why per-persona and not global.** The product already treats the three personas
(`pm`/`dev`/`exec`) as the unit of identity end-to-end: `api/app/auth.py` maps
`X-Mahalo-Persona` → `{developer_id, role}`, and the dashboard store keys on the
canonical `personaId` derived from role (`_ROLE_TO_PERSONA`:
`product_manager→pm`, `developer→dev`, `executive→exec`, default `dev`).
Per-persona config fits that grain, lets the demo show different personas with
different review models, and costs nothing extra over global. A global singleton
would be simpler but breaks the established persona-scoped mental model and the
dashboard precedent.

**Why reuse the dashboard pattern (new table, same shape) rather than a brand-new
mechanism or cramming into the dashboards table.** The dashboard router is the
template: a thin FastAPI forwarder, a **lazily-constructed** boto3 DynamoDB
*resource* client (`_get_table`, import stays offline-safe, NFR-4), partition key
`personaId`, read-returns-default-on-absent, overwrite-save on PUT, 502 on
DynamoDB error, 422 on structural validation. We add a sibling router
`api/app/routers/model_config.py` and a new table `mahalo-model-config`
(partition key `personaId`) provisioned by a new `MahaloModelConfigStack` wired
like `MahaloDashboardStack` in `infra-cdk/app.py`. A separate table (not a new
attribute on `mahalo-dashboards`) keeps the two concerns independent, avoids
read-modify-write contention with widget saves, and mirrors the existing
one-table-per-concern layout. The "simpler mechanism" alternative (baking config
into an env var) is rejected because it cannot be changed from the Settings UI
without a redeploy, violating FR-10.

### B.1 Config schema and endpoints

New endpoints on the thin API (sibling router, registered like the dashboard
router):

- `GET /model-config` → `{ "codeGeneration": <id>, "codeReview": <id>,
  "security": <id> }` for the caller's persona; returns documented defaults when
  no item exists (FR-7), without materialising them (mirrors the dashboard
  default-on-absent read). A malformed stored item falls back to defaults with a
  `warning` log.
- `PUT /model-config` with the same body; **validated against the server
  allow-list** before `put_item`. Invalid id → **422** (reuse the dashboard 422
  validation precedent). DynamoDB error → **502**. Server stamps `updatedAt`.

Pydantic model `ModelConfig` (new, in `api/app/models.py`): `codeReview` and
`security` are strings constrained to the **review** allow-list; `codeGeneration`
is constrained to the single code-gen id (fixed this slice). Each validator
imports the shared allow-list constant. The persona id is derived server-side
from `current_identity` exactly as the dashboard router does — via a shared
`_ROLE_TO_PERSONA` rule (the header is never re-read for the key).

### B.2 How the config reaches the Runtime

The thin API is the single place that knows the persona and reads the config. On
`POST /chat`, `api/app/routers/chat.py` performs a `GetItem` on
`mahalo-model-config` (defaults on absent) and **forwards the resolved review
model id** in the Runtime invoke body as a new field `review_model_id`, alongside
the existing `{action, prompt, developer_id, role}`.

**No `codegen_model_id` is forwarded (resolves finding 7).** FR-12 keeps code-gen
on the Runtime's `BEDROCK_MODEL_ID` env (Sonnet 4.5) unchanged this slice, so a
forwarded code-gen id would be consumed by nothing. The `stages[generate]` entry
is populated from the *known* code-gen default id/label (a constant in
`agent/model_config.py`), not from a request field. Configurable code-gen is
future work; when it lands it adds `codegen_model_id` to the body and wires the
main agent to honour it.

The approve leg does **not** forward any model id; the resume replays the pending
tool with no model call (§C.4), confirmed against
`api/app/routers/chat.py::approve_action` (forwards `developer_id`,
`interrupt_id`, `decision`, `proposal` only).

---

## C. How the review stage runs on a different model — **a read-only Strands sub-agent**

**Decision.** The review stage is a **second `strands.Agent`** bound to its own
`BedrockModel(model_id=<review id>)`, built per invocation with **no tools** (so
no write tools, nothing the `WriteApprovalHook` could ever see) and a dedicated
reviewer system prompt. The main agent generates as today; a new orchestration
seam invokes the reviewer read-only on the generated code and attaches the result
to the response. The reviewer is **not** given the gateway/write tools and
**never** participates in the HITL interrupt flow.

**Why a sub-agent and not alternatives.** Swapping the single model's `model_id`
mid-turn (rebuild the one agent) cannot give *independent* review — the same
conversation and the same model would review itself, defeating the trust goal. A
Strands "agent-as-tool" where the reviewer is registered as a `@tool` on the main
agent is viable but adds a tool the `WriteApprovalHook` and the gateway registry
must reason about, and makes the review implicit/model-triggered rather than a
deterministic pipeline stage. A **separate `Agent` the orchestrator calls
directly** is the smallest change that gives a genuinely different model, keeps
the reviewer provably tool-less and read-only, and makes the stage deterministic
(so progress/stages reporting in §D/§E is exact). This matches the codebase's
existing "offline-safe lazy `BedrockModel`" idiom.

### C.1 Where it lives

- `agent/model_config.py` — the shared allow-list enum, id↔label map, the fixed
  code-gen id/label and the default review id, and
  `resolve_review_model(requested_id) -> (resolved_id, did_fallback)` (FR-11).
  Pure data + validation; offline-safe (no boto3 at import).
- **Factored `BedrockModel` helper (resolves finding 6).** Refactor
  `agent/strands_agent.py::_build_bedrock_model` to take the model id as a
  parameter: `_build_bedrock_model(model_id: str) -> BedrockModel`. All of the
  existing session/`Config`/profile-resolution logic (the `available_profiles`
  check, the "omit `profile_name` in the container" branch, the 300s read
  timeout) is factored and unchanged; only the id becomes a parameter. The main
  build calls `_build_bedrock_model(settings.bedrock_model_id)` (identical
  behaviour to today); the reviewer calls `_build_bedrock_model(review_model_id)`.
  This is the one change that stops the reviewer from accidentally binding to
  `BEDROCK_MODEL_ID` (the code-gen default).
- `agent/review.py` — `build_reviewer(model_id) -> Agent` and
  `review_code(reviewer, generated_code, context) -> ReviewResult`. The reviewer
  `Agent` is built like the main one but `tools=[]` and **no `WriteApprovalHook`**
  (there is nothing to gate), using `_build_bedrock_model(model_id)` and the
  reviewer system prompt (C.5). A `ReviewResult` dataclass carries
  `{model_id, findings_text, status}`.
- `agent/runtime_app.py::_handle_chat` — the orchestration seam (C.2).

### C.2 Pipeline within a chat turn (resolves findings 1 and 2)

`_handle_chat` has two return branches today (verified against
`agent/runtime_app.py`): the **interrupt** branch (`stop_reason == "interrupt"`,
returns `status="pending_approval"`, `response == ""`, with the proposal) and the
**complete** branch (`stop_reason != "interrupt"`, returns the assistant text).
The review stage is a seam that wraps **both** branches; critically, on the
interrupt branch `response` is empty, so the review input cannot come from
assistant text there.

1. `_handle_chat` resolves `review_model_id` via
   `agent/model_config.resolve_review_model(payload.get("review_model_id"))`
   (valid → passthrough; off-list/absent → default + `fallback=True`). Code-gen
   stays on `BEDROCK_MODEL_ID` (no resolve step — finding 7).
2. The main agent runs as today (`build_and_attach(...).agent(prompt)`).
3. **Review trigger — two disjoint, verified cases (resolves finding 1):**
   - **Complete branch** (`stop_reason != "interrupt"`, `response` non-empty):
     scan `response` for fenced code blocks. If one or more are present, the
     review input is their concatenation. No fenced block ⇒ no review (FR-17).
   - **Interrupt branch** (`stop_reason == "interrupt"`): inspect
     `result.interrupts[0].reason` (the `build_proposal` dict). Review **only
     when** `reason["system"] == "github"` **and** `reason["action"] ==
     "commit_files"`, extracting code from `reason["params"]["files"]` (a list of
     `{path, content}`). **A `create_branch` or `open_pull_request` proposal
     carries no file bodies** (verified in `agent/tools/github_write_tools.py`:
     `create_branch` params are `{repo_id, branch_name, from_branch}`;
     `open_pull_request` params are `{repo_id, head, base, title, body}`), so **no
     review stage runs on those steps** — the code was/will be reviewed on the
     `commit_files` turn, which is the step that actually carries the generated
     files. This is the documented reason AC-10's branch→commit→PR chain emits a
     review stage only on the commit step.
4. If triggered, build the reviewer (`build_reviewer(review_model_id)`) and call
   `review_code(...)` with the extracted code and a short context (the user's
   ask). This is a **single, read-only** Bedrock Converse on the review model; it
   writes nothing and touches no tool.
5. **Attach to the correct return dict (resolves finding 2).** The seam adds the
   `stages` and `review` keys (§E) to **whichever** dict `_handle_chat` is about
   to return:
   - on the **interrupt** branch, after the proposal dict is built, run the
     reviewer on the proposal `files` and add `stages`/`review` to the
     `pending_approval` dict **without changing `status` or `proposal`**;
   - on the **complete** branch, run the reviewer on the fenced blocks and add
     `stages`/`review` to the completed dict.
   Review runs *before* the proposal is surfaced but does **not** gate it; the
   human still approves the write exactly as today (FR-9, FR-18). Attaching the
   keys is purely additive — an old client ignoring them still sees an unchanged
   `pending_approval`/`complete` envelope (FR-19).

### C.3 Flow of the review model id

Settings UI → `PUT /model-config` (DynamoDB) → on `/chat`, thin API `GetItem` →
`review_model_id` in the Runtime invoke body → `_handle_chat` reads it →
`resolve_review_model` validates/falls back → `build_reviewer(model_id)` →
`_build_bedrock_model(model_id)`. No env var edit, no redeploy (FR-10). The
Runtime env `BEDROCK_MODEL_ID` continues to pin only the **code-gen** default; the
review id is strictly per-request.

### C.4 HITL stays untouched

The reviewer has `tools=[]`, so `WriteApprovalHook` (which fires only on the six
write tool names via `BeforeToolCallEvent`, verified in `agent/approval.py`) can
never trigger inside the reviewer. The main agent keeps its hook and its write
tools unchanged. The `/chat/approve` leg (`_handle_approve`) is **not modified**
and does **not** run a review stage (the resume replays a pending tool execution
with no model call); model ids are not forwarded on approve. The
branch→commit→PR breadcrumb chain in `agent/hitl.py` and the restored-interrupt
proposal derivation (`_restored_proposal`) are unchanged.

### C.5 Reviewer prompt + output contract

`build_reviewer` uses a compact system prompt instructing the model to act as an
independent senior reviewer of the supplied code, to **not** rewrite the code,
and to return a short structured verdict: an overall assessment line plus a
bulleted list of concrete concerns (security, correctness, style) or an explicit
"no blocking issues found." The reviewer output is captured verbatim into
`ReviewResult.findings_text`; the stage `status` is `ok` when the call succeeds,
`error` on the recoverable failure path (§Error handling).

---

## D. How per-stage progress reaches the UI — **structured `stages` array + optimistic client progress**

This is the hard transport question. Current reality (verified): the thin API
(`api/app/routers/chat.py::send_message`) performs a **single blocking**
`invoke_runtime(...)` and returns one `ChatResponse`; the Runtime emits only a
final dict. The frontend is a **static export behind CloudFront (no server)**,
calling a **Lambda Function URL (`AuthType=NONE`)**, and the chat page shows a
frozen three-dot spinner while `isLoading`.

**Options considered:**

- **(i) True streaming (SSE/chunked) from the thin API.** Lambda Function URLs
  *can* stream responses, but it means moving the thin API off the buffered
  request/response model, teaching the static frontend to consume a streamed
  body, and handling partial-failure/HITL interleaving over a stream. High effort
  and new failure modes for a demo.
- **(ii) Staged/polling protocol.** The Runtime would persist intermediate stage
  state and the client would poll a second endpoint. This needs new state storage
  and a polling loop, and AgentCore invocations are request-scoped — more moving
  parts than the requirement warrants.
- **(iii) Pragmatic middle-ground (CHOSEN).** Keep the single blocking invoke.
  The response carries a **structured `stages` array** (`generate`, `review`)
  with model + status, and the **client renders optimistic per-stage progress**:
  the moment the user sends a prompt, the chat UI replaces the frozen spinner with
  a staged indicator that advances through the *known* pipeline
  ("Generating with &lt;codegen label&gt;…" → "Reviewing with &lt;review label&gt;…")
  on a short timer, then reconciles against the authoritative `stages` array when
  the response lands.

**Decision & justification.** Choose **(iii)**. The requirement (NFR-3, FR-14) is
explicitly *"not a frozen spinner,"* not *"true token streaming."* Option (iii) is
the **smallest change** that satisfies it: no change to the blocking transport, no
SSE on the Function URL, no new polling endpoint or state store, and it works
within a static-export frontend with zero server. The client already knows the
fixed code-gen label and the configured review label (it just saved it in
Settings / can read it from `/model-config`), so it can show meaningful stage
labels optimistically, and the final `stages` array makes the displayed result
truthful (e.g. if review was skipped because no code was generated, the array
reflects that and the UI drops the review step).

**Tradeoff called out explicitly.** This is *optimistic* progress, not
*live-streamed* progress — between send and response the stage text is
client-driven, so on an unusually slow turn the client could show "Reviewing…"
slightly before the server truly reached that stage. This is acceptable for the
demo and is the documented cost of avoiding Function-URL streaming. If true live
progress is needed later, option (i) is the upgrade path and the `stages` array
contract in §E is forward-compatible with it (the same objects would simply
arrive incrementally).

### D.1 Edge cases for progress

- **No code generated:** server returns `stages = [generate]` only; client, on
  reconciliation, removes any optimistic review step.
- **Write-proposal (interrupt) turn:** on a `commit_files` proposal the server
  returns `stages = [generate, review]` plus the `pending_approval` proposal; on a
  `create_branch`/`open_pull_request` proposal the server returns
  `stages = [generate]` (no review step — finding 1) and the client shows no
  review line for that step.
- **Review model fallback (FR-11):** the `review` stage reports the *resolved*
  (fallback) model id/label and a `fallback: true` flag; the UI shows the model
  actually used.
- **Review call fails:** the `review` stage `status = "error"` with a short
  message; the turn still returns the generated answer (review failure is
  **recoverable** — see Error handling). The trust line degrades to "Generated by
  X; review unavailable."

---

## E. The "who did what" response contract (additive, non-breaking)

**Decision.** Extend both the Runtime response dict **and** the thin-API
`ChatResponse` with **new optional fields**, and update the chat router to forward
them; change nothing existing.

**Correcting the prior evidence (resolves finding 3).** The earlier draft claimed
the backend `ChatResponse` "tolerates extra optional fields (it carries an unused
optional `systems_queried`)." That is **wrong**: `api/app/models.py::ChatResponse`
has exactly four fields (`response`, `proposal`, `session_id`, `status`) and
**no** `systems_queried` (that optional lives only in
`frontend/src/types/index.ts`, whose own comment notes the backend "strips
extras"). More importantly, `api/app/routers/chat.py::send_message` constructs
`ChatResponse(response=…, proposal=…, session_id=…, status=…)` with a **fixed
field list** and forwards nothing else — so even a `stages`/`review` returned by
the Runtime would be dropped. Two concrete, **required** changes:

1. Add optional fields to `api/app/models.py::ChatResponse`:
   `stages: Optional[list[StageInfo]] = None` and
   `review: Optional[ReviewInfo] = None` (typed Pydantic sub-models `StageInfo`
   and `ReviewInfo`, both all-optional-with-defaults so old payloads still
   validate).
2. Update `api/app/routers/chat.py::send_message` to read `out.get("stages")` and
   `out.get("review")` and pass them into the `ChatResponse(...)` constructor.
   Without this router change the fields never reach the browser.

New Runtime/thin-API response shape (the four existing fields unchanged):

```jsonc
{
  "response": "…",                 // unchanged
  "proposal": { … } | null,          // unchanged (HITL)
  "session_id": "…",               // unchanged
  "status": "complete" | "pending_approval" | "error",  // unchanged
  // --- NEW, all optional ---
  "stages": [
    { "stage": "generate", "model_id": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "model_label": "Claude Sonnet 4.5", "status": "ok" },
    { "stage": "review",   "model_id": "us.amazon.nova-lite-v1:0",
      "model_label": "Nova Lite", "status": "ok", "fallback": false }
  ],
  "review": {
    "model_id": "us.amazon.nova-lite-v1:0",
    "model_label": "Nova Lite",
    "findings": "No blocking issues found. Minor: validate `page` param …",
    "status": "ok"
  }
}
```

- `stages` (optional list): ordered stages actually executed; drives both the
  progress reconciliation (§D) and the trust line.
- `review` (optional object): present only when the review stage ran; carries the
  reviewer model and findings for FR-16.
- The **trust line** (FR-15) is derived client-side from `stages` (generate label
  + review label) so there is one source of truth; the server need not send a
  pre-formatted sentence.

**Why additive-optional keeps HITL/old clients working.** Every new field is
optional with a `None`/empty default, and the four existing fields are untouched,
so (a) a `pending_approval` response still carries `proposal` exactly as today and
may *also* carry `stages`/`review` describing the generate+review that preceded
the proposal (§C.2 step 5), (b) `ActionResult` for `/chat/approve` is
**unchanged** (no review on approve, §C.4), and (c) an older client that ignores
the new keys behaves exactly as before (FR-18/FR-19). Pydantic validation of old
payloads is unaffected.

### E.1 Frontend changes (static-export aware)

- **Read the static-export constraint first.** Per `frontend/AGENTS.md` this is a
  **non-standard Next.js static export**; before any frontend build/config work,
  consult the vendored docs under `frontend/node_modules/next/dist/...` and do not
  introduce server-only Next features. All changes here are client components
  (`"use client"`), consistent with the existing chat/settings pages.
- `frontend/src/types/index.ts`: add optional `stages?: Stage[]` and
  `review?: ReviewSummary` to `ChatResponse` (purely additive to the existing
  shape; leaves the existing `systems_queried?` untouched).
- `frontend/src/services/api.ts`: add `getModelConfig()` / `putModelConfig()`
  helpers (GET/PUT `/model-config`) using the existing `api` client and the
  persona header — no new client infra.
- `frontend/src/app/(protected)/settings/page.tsx`: add the three dropdowns
  (Code generation / Code review / Security) above the existing "Refresh demo
  data" card, wired to the config endpoints. **Code generation** is shown
  read-only / disabled (fixed to Sonnet 4.5 this slice); **Security** is visibly
  marked "not yet active" (FR-5). Options come from a static allow-list array
  mirroring `agent/model_config.py`.
- `frontend/src/app/(protected)/chat/page.tsx`: replace the frozen spinner block
  with a staged-progress indicator while `isLoading` (optimistic, §D), and render
  the trust line + review findings from `stages`/`review` on the assistant
  message. A small new `components/chat/StageProgress.tsx` and a trust-line render
  in `ChatMessage.tsx` (reusing its existing footer-pill styling).

---

## Error handling (per operation that can fail)

- **Settings read (`GET /model-config`).** DynamoDB error → **502** (thin API),
  logged `error`; recoverable (Settings shows an inline error, as the dashboard
  GET does). Absent item → return defaults (not an error). Malformed stored item →
  fall back to defaults with a `warning` log (mirrors the dashboard GET).
- **Settings write (`PUT /model-config`).** Body fails allow-list validation →
  **422** (fatal for that request; the UI keeps the prior saved value and shows
  the message). DynamoDB error → **502**, logged `error`, recoverable.
- **Runtime invoke (thin API `/chat`).** `BotoCoreError`/`ClientError` → **502**
  (unchanged existing behaviour); recoverable at the edge.
- **Review model id invalid / off allow-list (Runtime).** Not fatal:
  `resolve_review_model` substitutes the default and sets `fallback=true`; the
  turn succeeds; the `review` stage reports the resolved model. Logged `warning`.
- **Review Converse call fails (Runtime).** Recoverable: catch the exception, set
  the `review` stage `status="error"` with a short message, and **still return the
  generated answer** (`status` stays `complete`/`pending_approval`). The
  generator's result must not be lost because the second opinion failed. Logged
  `warning` with the model id (no code/secret contents logged).
- **Main agent invoke fails (Runtime).** Unchanged: the existing entrypoint
  `try/except` returns the in-band `{status:"error", error:{…}}` envelope (HTTP
  200), which the thin API maps as today.
- **HITL legs.** Unchanged, including the stale/unknown `interrupt_id` →
  `no_pending_interrupt` safe failure in `_handle_approve`.

No operation logs model-generated code bodies or any token/secret; errors
reference model **ids/labels** only.

## Input validation (per external input)

- **`X-Mahalo-Persona` header** — optional; mapped by the existing
  `current_identity` to one of three fixed identities or the safe default. Never
  injects an arbitrary persona. Unchanged.
- **`PUT /model-config` body** — required object; `codeReview`/`security` must be
  members of the server **review** allow-list, `codeGeneration` must be the fixed
  code-gen id (type: string; limit: allow-list membership; failure → 422). This
  is the invariant that stops a hand-crafted request to the `AuthType=NONE` URL
  from selecting an arbitrary model.
- **`review_model_id` in the Runtime invoke body** — optional string; validated
  again at the Runtime via `resolve_review_model` (defence in depth; failure →
  silent fallback to default, not an error). Absent ⇒ default.
- **`prompt`** — unchanged existing caps (non-empty, ≤ 32 KB) in
  `agent/runtime_app.py::_handle_chat`.
- **Generated code passed to the reviewer** — internal; size-bounded to the same
  32 KB ceiling before the review Converse to avoid an oversized second call;
  truncation (if ever needed) is noted in the review context.

## Invariant ownership (which layer enforces what, and why)

- **Allow-list membership** — owned by the **server** (`agent/model_config.py`
  for the Runtime, the `PUT /model-config` validator for the thin API). The
  browser array is a *convenience* for the dropdown, never the trust boundary,
  because the Function URL is `AuthType=NONE` and the client is untrusted (NFR-6).
- **Reviewer is read-only / tool-less** — owned by `agent/review.py`
  (`build_reviewer` constructs the `Agent` with `tools=[]` and no write hook). The
  write gate itself (`WriteApprovalHook`) is owned by the **main** agent and is
  unchanged; making the reviewer tool-less is the mechanism that keeps it out of
  the gate entirely.
- **Per-persona key derivation** — owned by the thin-API routers (derive
  `personaId` from `current_identity`, never from a raw header), reusing the
  dashboard router's `_ROLE_TO_PERSONA` precedent so there is one identity rule.
- **Offline-safe import** — owned by `agent/model_config.py`, `agent/review.py`,
  and the new router: no boto3/client construction at import; `BedrockModel` and
  the DynamoDB resource are built lazily (NFR-4), matching
  `_build_bedrock_model` and the dashboard router.

## Infrastructure — IAM implication (flagged) and deploy surface

### IAM — new review model grant (required)

`infra-cdk/mahalo_infra/runtime_stack.py::_grant_app_permissions` currently grants
`bedrock:InvokeModel`/`…WithResponseStream` on **only** the Sonnet 4.5
inference-profile ARN plus `arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0`
(a two-ARN pattern: the regional inference-profile ARN + a `*`-region
foundation-model ARN). The reviewer invokes a **different** model, so the Runtime
execution role must gain an `InvokeModel` grant for each allow-listed review
model, mirroring that exact two-ARN pattern (scoped, per NFR-5 / AC-12).

**Base foundation-model ids each review profile fans out to (verified via
`get-inference-profile`; resolves finding 5).** Each cross-region profile routes
to the same base id in `us-east-1`/`us-east-2`/`us-west-2`, which is why the
foundation-model ARN uses the `*` region wildcard:

| Review inference-profile ARN (regional) | paired foundation-model ARN (`*` region) |
| --- | --- |
| `…:inference-profile/us.amazon.nova-lite-v1:0` | `arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0` |
| `…:inference-profile/us.amazon.nova-micro-v1:0` | `arn:aws:bedrock:*::foundation-model/amazon.nova-micro-v1:0` |
| `…:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0` | `arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0` |

The inference-profile ARNs are templated from `self.region`/`self.account` (no
literal account id committed). **Opus is NOT granted** — it is off the slice
allow-list (§A), so there is no selectable-but-ungranted model. **Without these
grants the review Converse fails with AccessDenied** and the review stage degrades
to its recoverable error path. AC-12 stays satisfied: a per-model scoped grant, no
broader Bedrock grant.

A new table **`mahalo-model-config`** (partition key `personaId`) is provisioned
by a new `MahaloModelConfigStack` (modelled on `MahaloDashboardStack`), wired in
`infra-cdk/app.py`, and its name injected into the thin-API Lambda env
(`MAHALO_MODEL_CONFIG_TABLE`); the thin-API role gains `grant_read_write_data` on
it, exactly like the dashboard table.

### Deploy surface (operator approves deploy separately)

This change touches three deployables; note the surface, do not deploy here:

- **Runtime** (`MahaloRuntimeStack`) — new agent code (`model_config.py`,
  `review.py`, the `_build_bedrock_model(model_id)` refactor, `runtime_app.py`
  changes) means a **new container image**: deploy with `MAHALO_BUILD_IMAGE=1`
  (the `from_asset` ARM64 build branch), plus the new IAM grant above.
- **Thin API** (`MahaloApiStack`) — new `/model-config` router, `ChatResponse`
  fields + the chat-router forward change, chat-router config read: redeploy the
  Lambda with `MAHALO_BUILD_IMAGE=1`, plus the new table + grant and
  `MAHALO_MODEL_CONFIG_TABLE` env.
- **Frontend** (`MahaloFrontendStack`) — Settings dropdowns, chat stage progress +
  trust line, new api helpers: a **static re-export and deploy** with
  `NEXT_PUBLIC_API_URL` set. Per `frontend/AGENTS.md`, treat this as a
  non-standard static export and consult the vendored Next docs before any
  build/config change.
- **New** `MahaloModelConfigStack` (DynamoDB table) — deploy before/with the API
  stack (direct construct reference, like the dashboard stack).

## Testability

- **Unit (no AWS):**
  - `agent/model_config.py`: allow-list membership, `resolve_review_model` (valid
    → passthrough; invalid/absent → default + `fallback=true`). Pure data.
  - `agent/strands_agent.py`: `_build_bedrock_model(model_id)` returns a
    `BedrockModel` for an arbitrary id offline (lazy construction, NFR-4/AC-11),
    and the main build still uses `settings.bedrock_model_id`.
  - `agent/review.py`: `build_reviewer` constructs an `Agent` with `tools == []`
    and no write hook (offline — `BedrockModel` is lazy). `review_code` with a
    monkeypatched reviewer agent (stubbed `__call__`) → `ReviewResult` shape,
    including the error path.
  - `agent/runtime_app.py`: extend `test_runtime_app.py` fakes — (a) a
    **complete-branch** turn whose `response` contains a fenced block yields a
    `stages` array with distinct generate/review ids and a `review` object; (b) a
    **complete-branch** turn with no fenced block yields no `review` stage
    (FR-17); (c) an **interrupt-branch** `commit_files` proposal yields a `review`
    stage built from `params.files` with `status` still `pending_approval` and the
    `proposal` byte-for-byte unchanged; (d) an **interrupt-branch**
    `create_branch` proposal yields `stages == [generate]` and **no** review
    (finding 1); (e) the approve leg is byte-for-byte unchanged.
  - Thin API: `/model-config` GET default-on-absent, PUT 422 on off-list id, 502
    on DynamoDB error — reuse the dashboard router test pattern with a stubbed
    table. `/chat` forwards `review_model_id` from the resolved config **and**
    projects `out["stages"]`/`out["review"]` onto `ChatResponse` (guards finding 3
    — the router actually forwards the new fields).
  - Frontend: the stages→trust-line derivation and the "drop review step when no
    review stage" reconciliation as a small pure function with unit tests.
- **Integration (live AWS, run manually in the account):** one chat turn with
  review set to Nova Lite and code-gen Sonnet 4.5, asserting two **distinct**
  invoked model ids surface in `stages`, the reviewer performs no write, and the
  subsequent commit still pauses at the HITL card. This is the acceptance-level
  check that cannot be unit-tested because it needs real Bedrock + Runtime.
- **Hard-to-test smell check:** because the review stage is a *deterministic
  pipeline step* (not a model-chosen tool), its execution and reporting are
  directly assertable from the entrypoint return value — the design is
  test-friendly. The only genuinely live-only concern is actual model
  independence, covered by the integration test above.

## Future work (explicitly deferred — not designed here)

- **Security-review stage** — a second read-only sub-agent on the configured
  security model, wired like the review stage; the Settings dropdown and store
  field already exist this slice, so enabling it is additive.
- **Configurable code generation** — add `codegen_model_id` to the invoke body and
  wire the main agent to honour it; the `stages[generate]` entry and the allow-list
  are already shaped for it (finding 7).
- **Chat suggest-and-confirm** model selection — out of scope; Settings remains the
  single source of truth.
- **True streamed progress** (option D-i) — upgrade path; the `stages` contract is
  forward-compatible.
- **Opus (or other costly models)** on the allow-list — add via the same two-ARN
  grant pattern if demand arises (pinged OK, intentionally excluded this slice).
- Per-user config, cost metering, real static-analysis tooling.

---

## Responses to the design review

Review: `.agents/tasks/multi-llm/design-review.md` — verdict CHANGES_REQUESTED
(1 HIGH / 4 MEDIUM / 2 NIT). Evidence artifact:
`.agents/tasks/multi-llm/bedrock-ping-evidence.md`.

1. **HIGH — review trigger reads assistant text, empty on a write-proposal turn.**
   **Addressed** (§C.2 step 3). Trigger split into two disjoint verified cases:
   complete branch scans `response` fenced blocks; interrupt branch inspects
   `result.interrupts[0].reason` and reviews **only** `commit_files` via
   `params.files`, explicitly skipping `create_branch`/`open_pull_request` (which
   carry no file bodies — verified in `github_write_tools.py`). §D.1 and the
   Testability cases (c)/(d) and AC-10's clarified expectation follow from this.

2. **MEDIUM — review-before-proposal ordering not tied to the interrupt branch.**
   **Addressed** (§C.2 step 5). The seam wraps both return branches; on interrupt
   it adds `stages`/`review` to the `pending_approval` dict **without** changing
   `status` or `proposal`.

3. **MEDIUM — additive-non-breaking rests on a false `systems_queried` claim and
   omits the router change.** **Addressed** (§E). Corrected the claim (backend
   `ChatResponse` has four fields and strips extras; `systems_queried` is
   frontend-only). Added the two required changes: optional `stages`/`review` on
   `api/app/models.py::ChatResponse` **and** the `chat.py::send_message` forward of
   `out.get("stages")`/`out.get("review")`. A thin-API test now guards the
   forward.

4. **MEDIUM — allow-list invoke access asserted without evidence; Opus
   unpinged.** **Addressed** (§A + evidence artifact). Ran `converse` pings for
   Sonnet 4.5, Nova Lite, Nova Micro, Claude Haiku 4.5 (all succeeded) and
   captured them in `bedrock-ping-evidence.md`. Opus was pinged too (invocable)
   but is **dropped from the slice allow-list** so no offered model is
   unverified/ungranted.

5. **MEDIUM — IAM grant under-specifies base foundation-model ARNs (and Opus).**
   **Addressed** (§Infra IAM table). Enumerated each review inference-profile ARN
   paired with its `arn:aws:bedrock:*::foundation-model/<base-id>`
   (`amazon.nova-lite-v1:0`, `amazon.nova-micro-v1:0`,
   `anthropic.claude-haiku-4-5-20251001-v1:0`), verified via `get-inference-profile`
   (fan-out across us-east-1/2, us-west-2 → `*` wildcard). Opus omitted because it
   is off the allow-list (consistent with finding 4).

6. **NIT — factored `BedrockModel` helper must take `model_id`.** **Addressed**
   (§C.1). Helper signature is `_build_bedrock_model(model_id: str)`; session/
   `Config`/profile logic factored, id passed by both the main build and
   `build_reviewer`.

7. **NIT — `codegen_model_id` forwarded but unused.** **Addressed** (§B.2 / §C.2
   step 1). Dropped `codegen_model_id` from the invoke body and the resolve step;
   `stages[generate]` is populated from the known code-gen default id/label.
   Configurable code-gen noted as future work.
