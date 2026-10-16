# Task 4 — Design (AgentCore Gateway + MCP exposure layer)

**Status:** Design — **REVISION 3** in response to the second
`docs/.agents/tasks/task4-design-review.json` (verdict `CHANGES_REQUESTED`;
1 MEDIUM, 2 NIT — all resolved in this revision; see §13). Revision 2 resolved
the prior review's 2 HIGH / 4 MEDIUM / 3 NIT (see §12). Every finding is resolved
in-line. Still grounded entirely in
`docs/.agents/tasks/task4-investigation.md` (cited inline as *(inv §N)*) and the
Task 1–3 source re-read for this revision. No AWS resources are created here; no
git commit/push; nothing is written outside the `mahalo-agentcore` workspace.

**Scope guardrail:** `mahalo-dock` is READ-ONLY and is not touched by anything in
this design. All new code lands under `mahalo-agentcore/` (`agent/`,
`tools-lambdas/`, `infra-cdk/`).

---

## 1. Overview

Task 4 places the four mock-service Lambdas (Jira, Confluence, GitHub,
ServiceNow — already provisioned by Task 3's `MockServiceStack`) behind one
Amazon Bedrock AgentCore **Gateway** and exposes their operations as **MCP
tools** the Strands agent can call, while preserving **semantic / data
equivalence** with Tasks 1–2.

> **Equivalence, precisely defined (revised per review Finding 1).** The two
> modes are *data-equivalent*, not *byte-for-byte text-equivalent*. In DIRECT
> mode each `@tool` returns a **human-formatted string** (e.g.
> `jira_tools._format_stories` → `"Found N stories ...\n- [PAY-1] ..."`;
> `github_tools.github_list_repos` → `"Available repositories:\n- **name** ..."`).
> In GATEWAY mode the MCP tool result is the **structured JSON** the route
> produces (the adapter returns `json.loads(result["body"])`, §5.2), and the
> model re-formats it for the user. Therefore the agent's *final rendered text*
> can differ in wording between modes; what is guaranteed identical is the
> underlying data (same records, same ids, same error semantics) and the same
> behavioral rules (repo-NAME discipline, dev-id resolution, UPDATE-vs-CREATE,
> github "already exists"=success, propose/approve on writes). Tests assert the
> JSON payload, not the formatted sentence (§8).

The design makes four load-bearing choices, each resolving an open question:

- **(A) Granularity** — expose **one MCP tool per operation** (25 tools total,
  names identical to today's `@tool` function names), grouped into **four
  Gateway targets** (one per service Lambda). The behavioral docstrings/rules
  move into each operation's Gateway `ToolDefinition.description`, so the model
  sees the same guidance regardless of tool source. Client-side orchestration
  that is NOT a single HTTP call (Jira name→dev-id resolution, multi-call
  aggregation) is reproduced server-side via ported helpers (§3.4) so a
  Gateway-mode call yields the same data as DIRECT mode.
- **(B) HITL** — keep Task 2's native `BeforeToolCallEvent` interrupt. The
  investigation confirms the before-hook fires uniformly for MCP tools *(inv
  §1.3)*. We normalize Gateway's `target___tool` name back to the bare tool name
  **inside the hook and `build_proposal`** via `rsplit("___", 1)[-1]` — a no-op
  for local names — rather than relying on `MCPClient(prefix=...)` (which only
  *adds* a prefix, it cannot strip Gateway's `___`). One hook serves both modes.
- **(C) Dual-mode** — a single env flag `MAHALO_TOOL_MODE` (`direct` |
  `gateway`, default `direct`) selects the tool source in `build_agent()`.
  DIRECT mode is unchanged (the 25 local `@tool`s), so the existing agent suite
  stays green; GATEWAY mode swaps in an `MCPClient`. The direct-HTTP tools are
  NOT removed.
- **(D) IaC + auth** — a new native CDK stack `MahaloGatewayStack` under
  `infra-cdk/` creates the Gateway (`CfnGateway`, `protocolType=MCP`), four
  `CfnGatewayTarget`s (one per Lambda, inline `toolSchema`), the Gateway IAM
  role, and the four Lambda invoke permissions — all re-deployable to survive a
  monthly account reset *(inv §4)*. The four Lambda ARNs reach the gateway stack
  by **direct CDK construct reference** (not `Fn.import_value`), so Task 3's
  `mock_service_stack.py` stays frozen (revised per review Finding 2, §7.1).
  **Inbound auth is deferred as a LIVE-validated choice** (revised per review
  Finding 6): the offline deliverable fixes `authorizerType` as a stack
  parameter defaulting to `AWS_IAM`, but the working SigV4-over-MCP mechanism is
  an explicitly to-be-validated LIVE step with a documented `CUSTOM_JWT`+Cognito
  fallback (§6.4, §9). Outbound to the Lambdas is `GATEWAY_IAM_ROLE` *(inv §2.4)*.

A **mandatory** fifth piece falls out of the investigation's critical gap *(inv
§3, §E)*: a Gateway Lambda-target invocation is not an HTTP event, so each
Lambda needs a `common/gateway_adapter.py` shim that maps `(toolName, args)` →
the existing `Router` and unwraps the HTTP envelope to plain JSON. This is a
first-class deliverable, not an afterthought.

---

## 2. Technology stack (LOCKED on approval)

- **Gateway provisioning:** AWS CDK (Python) using the native, stable L1
  constructs `aws_cdk.aws_bedrockagentcore.CfnGateway` and `CfnGatewayTarget`
  shipped in the already-installed `aws-cdk-lib 2.273.0` *(inv §4)*. No boto3
  custom resource. (Fallback, not used:
  `bedrock_agentcore.gateway.GatewayClient` — *(inv §2.5)*.)
- **MCP client in the agent:** `strands.tools.mcp.MCPClient` from the installed
  `strands-agents 1.61.1`, passed directly into `Agent(tools=[...])` *(inv
  §1.1, §1.4)*.
- **Inbound auth to Gateway:** `authorizerType` is a stack parameter defaulting
  to **`AWS_IAM`**. The agent-side SigV4 signing mechanism is **NOT locked** —
  it is a LIVE-validated step with a `CUSTOM_JWT`+Cognito fallback (§6.4, §9).
  No Cognito user pool is provisioned in the offline deliverable.
- **Outbound Gateway→Lambda creds:** `GATEWAY_IAM_ROLE` *(inv §2.4)*.
- **Lambda runtime / adapter:** existing `python3.13` Lambdas; new pure-Python
  `common/gateway_adapter.py` (stdlib only) *(inv §3)*.
- **Tests:** `pytest` (already the project runner); CDK `assertions.Template`
  for synth checks. No new third-party dependency is introduced. `aws-cdk-lib`
  floor is bumped to `>=2.251,<3` (the version that first ships the constructs)
  to make the requirement explicit; `2.273.0` already satisfies it *(inv §4)*.

Non-negotiable invariants carried from Tasks 1–3: **zero LangChain**;
`import agent.*` and `build_agent()` stay offline-safe (no AWS call, no network
at import/construct time); **data equivalence** with the local mocks (§1).

---

## 3. Decision A — Tool granularity + behavior preservation

### 3.1 One MCP tool per operation (not per Lambda)

Today the agent has **25** fine-grained `@tool`s hitting HTTP endpoints. Two
options for Gateway exposure:

- **Coarse** — one MCP tool per Lambda (4 tools), each taking an `operation`
  discriminator + a free-form payload.
- **Fine** — one MCP tool per operation (25 tools), each with a typed
  `inputSchema`.

**Chosen: fine (25 tools).** Reasoning: the agent's correctness depends on the
model picking the right narrow tool with the right typed args and reading the
per-operation behavioral docstring (repo-NAME discipline, dev-id resolution,
UPDATE-vs-CREATE, "already exists"=success, propose/approve). A coarse tool
would collapse all that guidance into one blob, forcing the model to synthesize
the operation + payload shape itself — a regression in both accuracy and the
HITL story (the hook keys on tool *name*). Fine-grained tools keep the model's
decision identical to today. The investigation confirms the Gateway Lambda
target's `toolSchema` is a flat list of `ToolDefinition`s, so N operations on
one Lambda is natively supported *(inv §2.1, §2.2)*.

**Targets:** four `CfnGatewayTarget`s, one per service Lambda, each carrying its
service's operations in `toolSchema.inlinePayload`:

| Target name (`name`) | Lambda (construct ref) | Operations in `toolSchema` |
|---|---|---|
| `mock-jira` | `jira_stack.function` | 9 (7 read + 2 write) |
| `mock-github` | `github_stack.function` | 7 (4 read + 3 write) |
| `mock-confluence` | `confluence_stack.function` | 3 (3 read) |
| `mock-servicenow` | `servicenow_stack.function` | 6 (5 read + 1 write) |

The Lambda functions reach this stack by **direct construct reference** —
`app.py` passes each `MockServiceStack` instance (which already exposes
`self.function`, confirmed in `mock_service_stack.py`) into `MahaloGatewayStack`.
CDK auto-wires the cross-stack reference (export/`Fn::ImportValue`) and an
implicit stack dependency; `mock_service_stack.py` does **not** change
(revised per review Finding 2 — see §7.1).

### 3.2 Tool names are IDENTICAL to today's `@tool` names

Each `ToolDefinition.name` equals the current Strands function name so prompts,
docstrings and the HITL name-set carry over unchanged:

- Jira: `jira_list_projects`, `jira_list_developers`, `jira_search_stories`,
  `jira_get_stories_by_assignee`, `jira_get_story`, `jira_get_sprint_info`,
  `jira_get_board`, **`jira_create_story`**, **`jira_update_story`**.
- GitHub: `github_list_repos`, `github_get_pull_requests`, `github_get_commits`,
  `github_get_repo_stats`, **`github_create_branch`**, **`github_commit_files`**,
  **`github_open_pull_request`**.
- Confluence: `confluence_search`, `confluence_get_page`,
  `confluence_list_spaces`.
- ServiceNow: `servicenow_list_deployments`,
  `servicenow_deployment_status_by_project`, `servicenow_list_incidents`,
  `servicenow_get_incident`, `servicenow_get_stats`,
  **`servicenow_create_incident`** (6 bold = the six writes).

The model-facing tool name becomes `"<targetName>___<toolName>"` on the wire
*(inv §1.3, §3)*; §4 and §5 handle the strip.

### 3.3 Where the docstrings/behavioral rules live

The current docstrings are the behavioral spec (repo-NAME discipline; "do not
invent repo-1"; UPDATE-vs-CREATE; "already exists"=success; incident-status
nuance). Because `MCPAgentTool.tool_spec.description` is the MCP tool's
`description` verbatim and `inputSchema.json` is the published schema verbatim
*(inv §1.2)*, we move each docstring into the matching
`ToolDefinition.description`, and each parameter into `inputSchema.properties`
with the same names/types/required-ness as the `@tool` signature. The source of
truth is a single Python module (see §3.5) consumed by BOTH the CDK stack (to
emit `toolSchema`) and the agent/tests (for parity), so the two never drift.

> **Note on output presentation (Finding 1).** The docstring guidance that
> governs the model's *decisions* (which tool, which args, how to treat a 409)
> carries over verbatim. The docstring text that describes *output formatting*
> is advisory only in GATEWAY mode — the tool returns JSON and the model renders
> it. Equivalence is on the data, not the sentence (§1).

### 3.4 Behaviors that are NOT a single HTTP call → ported server-side helpers

Three of the 25 operations are not a 1:1 HTTP passthrough; they orchestrate
multiple calls and/or transform input in the **agent process** today:

1. `jira_get_stories_by_assignee` — resolves a name→dev-id via `GET
   /developers` (`jira_tools.py::_resolve_assignee`), then fans out across
   projects/stories.
2. `jira_search_stories` — same name-resolution + multi-project fan-out +
   keyword filter.
3. `servicenow_deployment_status_by_project` — joins `GET /services` with `GET
   /deployments` and produces a specific grouped aggregation
   (`servicenow_tools.py`).

**Decision (revised per review Finding 3): expose these three as MCP tools whose
target Lambda implements the composite server-side, and this requires porting
net-new logic — explicitly sized and pinned to ONE source of truth.** The review
correctly notes these composites do *not* merely "reuse existing route
functions": `_resolve_assignee` (name/first-name/email matching against `GET
/developers`) and the ServiceNow services⋈deployments aggregation live only in
the agent today, not in any Lambda route. Pushing the composites server-side
therefore means porting that agent-only logic into the Lambda packages.

To avoid two drifting copies of the resolver:

- **Pin `_resolve_assignee` to a single source.** Move the resolver body to a
  **new `tools-lambdas/common/assignee.py`** (pure function:
  `resolve_assignee(assignee: str, developers: list[dict]) -> str | None`,
  stdlib only — it takes the developer list as an argument, so it has no HTTP
  dependency and runs in both the agent and the Lambda). The agent's
  `jira_tools.py::_resolve_assignee` is refactored to a thin wrapper that fetches
  developers and delegates to `common.assignee.resolve_assignee`. Because
  `tools-lambdas/common/` is already bundled into every Lambda asset
  (`mock_service_stack.py` includes `common/`), the Lambda composite imports the
  exact same function.
  - *Note on the import path:* `tools-lambdas/common/` is packaged at the Lambda
    root as `common`, while the agent imports from the repo root. The agent
    wrapper imports it via a small shim (add `tools-lambdas` to the resolver's
    import path, or vendor the single pure function) — chosen so there is
    literally one function body. If a clean cross-package import proves awkward
    at implementation time, the fallback is: keep the body in
    `common/assignee.py` and enforce equivalence with a **parity test** (below)
    rather than a shared import. Either way there is exactly one *behavioral*
    source of truth.
- **Port the ServiceNow aggregation** into
  **`tools-lambdas/servicenow/composites.py::deployment_status(store, args)`**,
  reproducing the `servicenow_tools.py` grouping. It calls the service's own
  route handlers (`GET /services`, `GET /deployments`) through the in-Lambda
  router/store and composes the same records.
- **Jira composites** land in
  **`tools-lambdas/jira/composites.py`** (`search_stories`,
  `stories_by_assignee`), each calling `common.assignee.resolve_assignee` + the
  project/story routes.
- `jira_update_story`'s `assignee` name→dev-id resolution also uses
  `common.assignee.resolve_assignee` server-side so the Gateway path resolves
  identically.

**Parity test (mandatory deliverable, §8):** feed one shared developer fixture
to BOTH the agent helper and the Lambda composite path and assert identical
dev-id resolution across **all six branches** of
`jira_tools.py::_resolve_assignee` (verified in source): exact-name, first-name,
email, no-match, **already-a-dev-id passthrough** (`val.startswith("dev-")`
returns `val` without consulting the developer list — so it must resolve
identically even against an empty/irrelevant fixture), and **ambiguous match**
(more than one partial match → `None`, from the `len(matches) == 1` branch).
Also assert the ServiceNow composite's grouped JSON equals the data the agent
aggregation produces for the same fixture. This is what actually guarantees the
two implementations stay equivalent (revision-3 Finding 3).

> Rationale for server-side composites over leaving them in the agent: in
> GATEWAY mode the agent must not also hold HTTP clients to the Lambdas (that
> would reintroduce the direct path and the `X-API-Token` requirement). Putting
> composites behind the tool keeps GATEWAY mode purely MCP. DIRECT mode is
> untouched and keeps its existing agent-side orchestration. Each composite
> returns JSON (not the `_format_stories` string), consistent with §1.

### 3.5 New/changed files for Decision A

- **New** `tools-lambdas/common/tool_schemas.py` — the single source of truth:
  for each of the 25 tools, a dict `{name, description, inputSchema,
  method, path_template, arg_mapping, composite?}`. `description`/`inputSchema`
  feed the Gateway `toolSchema`; `method`/`path_template`/`arg_mapping` feed the
  adapter (§5). Pure data + stdlib; importable by both `infra-cdk` and the
  Lambdas. **This module is the authoritative arg-mapping source** — the §5.3
  table documents it, but the module (with all 25 rows) is canonical
  (Finding 8).
- **New** `tools-lambdas/common/assignee.py` — the single `resolve_assignee`
  pure function (§3.4), imported by the Jira composites and the agent wrapper.
- **New** `tools-lambdas/jira/composites.py`,
  `tools-lambdas/servicenow/composites.py` — the three composite handlers
  (§3.4), reusing the service routes + `common.assignee`.
- **Changed** `agent/tools/jira_tools.py` — `_resolve_assignee` becomes a thin
  wrapper over `common.assignee.resolve_assignee` (behavior unchanged; this is
  the only edit to `agent/tools/*`, made solely to collapse the duplicate
  resolver to one source). All other `agent/tools/*.py` stay frozen.

---

## 4. Decision B — HITL preservation under Gateway MCP

### 4.1 The interrupt still fires (confirmed)

The native `BeforeToolCallEvent` is dispatched for **every** tool, MCP included,
*before* `MCPAgentTool.stream()` runs, so no MCP/HTTP write happens
pre-approval *(inv §1.3)*. Task 2's `WriteApprovalHook` mechanism therefore
carries over unchanged **except for name matching**.

### 4.2 The name-prefix problem and the fix

Gateway renames every tool to `"<targetName>___<toolName>"` (triple
underscore) *(inv §1.3, §3)*. Today `WriteApprovalHook._before_tool_call` does
an exact-match `event.tool_use["name"] in WRITE_TOOL_NAMES`, and
`build_proposal` does `name.partition("_")` to derive the service prefix (both
verified in `agent/approval.py`). Both would break on
`mock-github___github_create_branch`.

**Chosen fix (lowest-churn, dual-mode safe): strip the `___` prefix in the hook
and proposal builder.** A bare local name (`github_create_branch`) has no `___`,
so `rsplit("___", 1)[-1]` is a no-op for DIRECT mode and a correct strip for
GATEWAY mode — one code path serves both. Implementation:

```python
# agent/approval.py
def _bare_name(name: str) -> str:
    """Gateway sends '<target>___<tool>'; local tools send '<tool>'."""
    return name.rsplit("___", 1)[-1]
```

- `_before_tool_call`: `if _bare_name(event.tool_use["name"]) not in
  WRITE_TOOL_NAMES: return`.
- `build_proposal`: compute `bare = _bare_name(tool_use["name"])` first, then
  `prefix, _, action = bare.partition("_")` (unchanged logic on the bare name).

`WRITE_TOOL_NAMES` stays the six bare names; the proposal `description`,
`_SYSTEM_BY_PREFIX` lookup (`jira`/`github`/`servicenow`) and the `params` all
remain identical because they are derived from the *bare* name and the
model-supplied `input`. Rejected over the §1.3 alternative of
`MCPClient(prefix=...)`/`name_override` renaming because that construct only
*adds* a prefix (it cannot delete the Gateway `___` segment) and would require a
custom `MCPAgentTool.name_override`, which is more surface area for the same
outcome.

### 4.3 Resume path unchanged

`agent/chat.py::_ask` drives the interrupt loop on `result.stop_reason ==
"interrupt"` and resumes with `interruptResponse` blocks. Nothing there keys on
the prefix (it reads the proposal dict), so the only edit needed for the
resume/`[SYSTEM]`-breadcrumb chain is that `proposal["action"]` already comes
from the bare name via §4.2 — no change to `_ask` or `_emit_system_signal`.

### 4.4 Edge cases (HITL)

- **Read tool with a coincidental `___`** — none of the 25 names contains `___`;
  the delimiter is Gateway-injected only, so the strip is unambiguous. This
  invariant is **asserted mechanically** by a test (§8, Finding 9), not merely
  assumed.
- **Unknown/new write tool** — if a future write tool is added, it must be added
  to `WRITE_TOOL_NAMES` (bare name). A test (§8) asserts the six write names are
  present and that each resolves through a representative `target___tool` form.
- **Interrupt bypass risk** — the single biggest correctness risk *(inv §1.3)*
  is a write executing without approval because the name missed the set. §8
  adds a direct test that feeds a `BeforeToolCallEvent`-shaped `tool_use` with
  a `mock-github___github_create_branch` name and asserts `event.interrupt`
  is invoked (first pass) and `cancel_tool` is set on a non-APPROVE resume.

---

## 5. Decision E (mandatory) — the Gateway→Router adapter

This is not optional: a Gateway Lambda-target event is a flat args map with the
tool name on `context.client_context.custom['bedrockAgentCoreToolName']`, no
HTTP fields, no headers, no `X-API-Token` *(inv §3)*. Task 3's router would 404
every such call. The adapter is the bridge.

### 5.1 Handler dispatch (per service `handler.py`) — revised per review Finding 5

The live handler (verified in `tools-lambdas/github/handler.py`) seeds the store
and wraps everything in `ClientError → error(503)` / `Exception → error(500)`.
The Gateway branch must live **inside** that same try/except and **after**
seeding, and must not reference the stale `_store` module global. The revised
branch:

```python
def lambda_handler(event, context):
    try:
        store, router = _get_router()
        store.ensure_seeded()
        tool_name = _gateway_tool_name(context)   # None if not a Gateway call
        if tool_name is not None:
            return gateway_adapter.handle(tool_name, store, router, event)
        return router.dispatch(event)             # existing HTTP path, unchanged
    except ClientError:
        logger.exception("DynamoDB error")
        return error(503, "Backend store unavailable")
    except Exception:
        logger.exception("Unhandled error")
        return error(500, "Internal error")
```

`_gateway_tool_name(context)` reads
`getattr(getattr(context, "client_context", None), "custom", None)` and returns
`custom.get("bedrockAgentCoreToolName")` or `None`. A Function-URL invocation has
no such custom context, so DIRECT behavior is untouched. The adapter receives the
already-constructed `store` and `router` (not the `None` global), the store is
seeded before any Gateway dispatch, and a DynamoDB `ClientError` in the Gateway
path is caught by the existing `except ClientError → error(503)` guard so it
still becomes the §5.4 JSON error contract (the adapter unwraps that envelope).

### 5.2 `common/gateway_adapter.py` (new) — `handle(tool_name, store, router, event)`

Responsibilities:

1. Strip the `___` prefix: `bare = tool_name.rsplit("___", 1)[-1]`.
2. Look up the operation descriptor from `tool_schemas.py` (§3.5):
   `(method, path_template, arg_mapping, composite?)`.
3. If `composite` → call the service composite handler (§3.4) with `(store,
   args)` and return its JSON dict.
4. Else build a **synthetic normalized request** and dispatch:
   - fill `path_template` with the path args from `event`,
   - put remaining args into query (for GET) or JSON body (for POST/PUT) per
     `arg_mapping`,
   - construct a synthetic Function-URL-v2 event (or the router's internal
     normalized request) and call `router.dispatch`.
5. **Auth:** the Gateway call carries no `X-API-Token`. The adapter injects the
   expected token header into the synthetic request so the existing
   `require_token` check in `routes.py` passes **unchanged** — the Lambda reads
   its own `MOCK_<SVC>_TOKEN` env var (set by `MockServiceStack`, default
   verified in `mock_service_stack.py::_DEFAULT_TOKENS`) and the adapter sets
   that same value. This keeps `routes.py` and `auth.py` frozen; the real auth
   boundary for Gateway calls is IAM (the Gateway role), per *(inv §2.4)*. Chosen
   over "make `require_token` conditional on event source" because it touches
   zero existing route/auth code.
6. **Unwrap the HTTP envelope and return JSON (Finding 1):** `routes.py` returns
   `{statusCode, headers, body}` where `body` is a JSON string. Gateway expects
   the tool result as plain JSON, so **on `statusCode in (200, 201)`** (the exact
   success predicate `make_request` uses — verified in `agent/tools/http.py`:
   `if response.status_code in (200, 201)`; revision-3 Finding 2, NOT a loose
   "2xx") the adapter returns **`json.loads(result["body"])`** — the structured
   data, which is exactly the JSON the DIRECT tool's `make_request` parses and
   then *formats into a string*. The GATEWAY tool result is therefore this JSON
   payload; the model re-formats it. On any other `statusCode` (including a
   hypothetical 202/204), it returns the §5.4 error object rather than raising —
   same as `make_request`, which treats anything outside `{200, 201}` as the
   error string.

The GATEWAY tool-result payload is thus **the route's JSON body on success** and
**an `{"error": ...}` object on failure** — specified exactly so an implementer
and the tests agree (§8).

### 5.3 The operation→HTTP mapping table (authoritative: `tool_schemas.py`)

`tool_schemas.py` is the **authoritative** arg-mapping source (Finding 8); the
table below documents the full 25 rows it must contain. Every arg-name quirk is
listed so none is left to inference.

| Tool name | method | path_template | arg_mapping |
|---|---|---|---|
| `jira_list_projects` | GET | `/projects` | — |
| `jira_list_developers` | GET | `/developers` | — |
| `jira_get_story` | GET | `/stories/{story_id}` | path: story_id |
| `jira_get_sprint_info` | GET | `/sprints/{project_id}` | path: project_id |
| `jira_get_board` | GET | `/projects/{project_id}/board` | path: project_id |
| `jira_search_stories` | — | *composite* | `jira.composites.search_stories` (resolves assignee via `common.assignee`, fans out) |
| `jira_get_stories_by_assignee` | — | *composite* | `jira.composites.stories_by_assignee` (resolves assignee via `common.assignee`) |
| `jira_create_story` | POST | `/stories` | body: {project_id, title, description, priority, story_points, assignee} |
| `jira_update_story` | PUT | `/stories/{story_id}` | path: story_id; body: **changed fields only**; `assignee` resolved name→dev-id via `common.assignee` first |
| `github_list_repos` | GET | `/repos` | — |
| `github_get_pull_requests` | GET | `/repos/{repo_id}/pulls` | path: repo_id; query: status, **author_id** |
| `github_get_commits` | GET | `/repos/{repo_id}/commits` | path: repo_id; query: **author** (NOT `author_id` — verified in `github_tools.py`), since |
| `github_get_repo_stats` | GET | `/repos/{repo_id}/stats` | path: repo_id |
| `github_create_branch` | POST | `/repos/{repo_id}/branches` | path: repo_id; body: {**name**: branch_name, from_branch} (route reads `body["name"]`) |
| `github_commit_files` | POST | `/repos/{repo_id}/commits` | path: repo_id; body: {branch, message, files} |
| `github_open_pull_request` | POST | `/repos/{repo_id}/pulls` | path: repo_id; body: {head, base, title, body} |
| `confluence_search` | GET | `/search` | query: q=query, space_id |
| `confluence_get_page` | GET | `/pages/{page_id}` | path: page_id |
| `confluence_list_spaces` | GET | `/spaces` | — |
| `servicenow_list_deployments` | GET | `/deployments` | query: **service** (NOT `service_id`), **environment**, status — verified in `servicenow_tools.py::servicenow_list_deployments(service, environment, status)` + `routes.py::list_deployments` |
| `servicenow_deployment_status_by_project` | — | *composite* | `servicenow.composites.deployment_status` (joins /services + /deployments, aggregates) |
| `servicenow_list_incidents` | GET | `/incidents` | query: severity, status, **service** — verified in `servicenow_tools.py::servicenow_list_incidents(severity, status, service)` + `routes.py::list_incidents`. The route also accepts `assignee`, but the current `@tool` does NOT expose it, so the schema does **not** expose `assignee` either (stay equivalent with DIRECT) |
| `servicenow_get_incident` | GET | `/incidents/{incident_id}` | path: incident_id |
| `servicenow_get_stats` | GET | `/stats` | — |
| `servicenow_create_incident` | POST | `/incidents` | body: {title, affected_service, severity, description, assignee, linked_deployment} |

> The exact verb/path/query key for each row is taken from
> `tools-lambdas/<svc>/routes.py` and the current `agent/tools/*.py` endpoint
> strings; the implementer confirms each row against those two sources when
> authoring `tool_schemas.py`. The highlighted quirks (`author` vs `author_id`,
> `branch_name`→`name`, update-changed-fields-only, the ServiceNow
> `service`/`environment` filters) are the known traps.
>
> **ServiceNow list-filter note (review Finding 1, revision 3).** The two
> ServiceNow *list* rows expose exactly the `@tool` args, no more and no less, so
> GATEWAY mode keeps every filter DIRECT mode has and adds none DIRECT lacks:
> `servicenow_list_deployments` exposes `service`, `environment`, `status` (the
> prior draft wrongly said `status, service_id` — mis-naming `service` and
> dropping `environment`); `servicenow_list_incidents` exposes `severity`,
> `status`, `service` (the prior draft dropped `service`). The route's extra
> `assignee` filter on `/incidents` is deliberately **not** surfaced because the
> current `@tool` does not, and §8's schema-parity test now asserts **exact**
> arg-set equality to prevent exactly this class of drift.

### 5.4 Error handling (adapter, concrete per failure mode) — revised per Finding 4

The success predicate is `statusCode in (200, 201)` (revision-3 Finding 2),
matching `make_request` exactly; **every** other status — 4xx, 5xx, and any
2xx that is not 200/201 (e.g. 202/204) — is treated as the error string below.
The DIRECT error string is **the full raw response body text**, not an extracted
field: `agent/tools/http.py::make_request` returns
`{"error": f"Request failed with status {response.status_code}:
{response.text}"}` (verified). To stay data-equivalent, the adapter builds the
error string from the **unparsed route body string** `result["body"]` (which is
exactly what `httpx` `response.text` would be for the same route), NOT from a
parsed `detail`:

```python
err = {"error": f"Request failed with status {status}: {result['body']}"}
```

| Failure | Recoverable? | What the caller (agent/model) receives | Logged? |
|---|---|---|---|
| Unknown tool name (not in table) | fatal for that call | `{"error": "Unknown tool: <bare>"}` | WARNING (unexpected schema drift) |
| Missing required path arg | fatal for call | `{"error": "Missing required argument '<arg>'"}` | INFO |
| Route returns 4xx (404/409/422/401) | recoverable | `{"error": "Request failed with status <code>: <raw body string>"}` — byte-identical to DIRECT `make_request` for the same body | INFO |
| Route returns 5xx (handler route returned `error(500/503)`) | recoverable | `{"error": "Request failed with status <code>: <raw body string>"}` | ERROR (route already logged) |
| Composite handler raises | fatal for call | `{"error": "Internal error"}` (no stack to model) | ERROR |
| DynamoDB `ClientError` | recoverable | caught by the handler's `except ClientError → error(503)`; adapter already returned, or the guard produces the 503 envelope which the model sees as `{"error": ...}` | ERROR (via `handler.py` `logger.exception`) |

The adapter never raises out of `lambda_handler` for an *expected* failure; it
returns a JSON error object so the Gateway returns a well-formed tool result and
the model handles it like today's `{"error": ...}` dicts (e.g. GitHub 409
"already exists" still surfaces and is treated as success by the model via the
tool description). Only truly unexpected exceptions propagate to the handler's
`except Exception → error(500)` guard (§5.1).

A test (§8) asserts the adapter's 404/409 error string equals what
`make_request` yields for the same route body.

### 5.5 Input validation (adapter + Gateway schema split)

- **Shape/type/required** — enforced first by the Gateway via each
  `ToolDefinition.inputSchema` (JSON-Schema subset, top-level `object`) *(inv
  §2.2)*; the model's args are validated before the Lambda is invoked.
- **Business/semantic validation** — stays in `routes.py` (e.g. story field
  required → 422, repo not found → 404, branch exists → 409). The adapter does
  not duplicate it; it forwards to the route and relays the status. One owner
  per invariant (§7.4).

---

## 6. Decision C — dual-mode selection and rollout

### 6.1 The toggle + config (revised per review Finding 7)

Three new `Settings` fields in `agent/config.py`, **each** read from an explicit
env var via the existing `_getenv(..., default)` helper so import stays
offline-safe:

| `Settings` field | Env var | Default |
|---|---|---|
| `tool_mode` | `MAHALO_TOOL_MODE` | `"direct"` |
| `gateway_mcp_url` | `MAHALO_GATEWAY_MCP_URL` | `""` |
| `gateway_region` | `MAHALO_GATEWAY_REGION` | value of `aws_region` (i.e. `AWS_REGION`) |

- `direct` (default) — today's behavior: 25 local `@tool`s hitting HTTP
  endpoints (localhost tunnel or deployed Function URLs). The existing agent
  suite runs in this mode, so **42 passed / 1 skipped stays green** unchanged.
- `gateway` — build an `MCPClient` against `gateway_mcp_url` and pass it into
  `Agent(tools=[...])` *(inv §1.1, §1.4)*.

No value triggers AWS at import time.

### 6.2 `build_agent()` changes

```python
def build_agent(..., tool_mode: str | None = None):
    mode = (tool_mode or settings.tool_mode).lower()
    model = _build_bedrock_model()
    system_prompt = ...  # unchanged
    hooks = [WriteApprovalHook()]  # unchanged (now prefix-aware, §4)
    if mode == "gateway":
        mcp_client = _build_gateway_mcp_client()  # constructed, NOT started
        agent = Agent(model=model, tools=[mcp_client],
                      system_prompt=system_prompt, hooks=hooks)
        return agent, mcp_client            # tuple in gateway mode (see §6.3)
    return Agent(model=model, tools=[*READ_TOOLS, *WRITE_TOOLS],
                 system_prompt=system_prompt, hooks=hooks)
```

`_build_gateway_mcp_client()` constructs `MCPClient(url=settings.gateway_mcp_url,
...)` but does **not** call `start()` — construction is offline-safe *(inv §1.1,
§1.4)*. This preserves the import/construct invariant: `build_agent(
tool_mode="gateway")` must import and construct cleanly offline (part of the
offline gate); only a live invocation touches AWS.

### 6.3 Driver change for the MCP context manager

MCP tools are only usable inside the client's `with` context *(inv §1.1)*. In
GATEWAY mode `build_agent` returns `(agent, mcp_client)` and `agent/chat.py`
wraps the invocation in `with mcp_client:`; DIRECT mode is unchanged:

```python
if settings.tool_mode == "gateway":
    agent, mcp_client = build_agent(tool_mode="gateway", **_IDENTITY)
    with mcp_client:
        print(_ask(agent, message))
else:
    agent = build_agent(**_IDENTITY)
    print(_ask(agent, message))
```

**Decision:** the explicit `with mcp_client:` form (return the client alongside
the agent in gateway mode) is chosen because *(inv §1.1)* documents exactly that
lifecycle; it does not depend on any un-verified `Agent` provider-context helper.

### 6.4 Inbound auth from the agent (Decision D, agent side) — revised per Finding 6

The gateway's `authorizerType` defaults to `AWS_IAM`. **How the agent actually
signs its MCP requests is a LIVE-validated step, not a locked offline claim.**
The investigation confirms only that `MCPClient.__init__` *accepts*
`auth=`/`auth_provider=` kwargs and documents the bearer-token/OAuth path *(inv
§1.1)*; it does **not** verify that a `botocore` `SigV4Auth` wrapped as an
`httpx.Auth` works end-to-end against an AgentCore Gateway MCP endpoint, nor the
exact SigV4 service name, nor that the agent's SSO admin role is accepted by the
`AWS_IAM` authorizer *(inv §2.3)*.

Therefore:

- **Offline (locked now):** `_build_gateway_mcp_client()` constructs an
  `MCPClient` with a pluggable auth provider; the **offline gate only requires
  that the client constructs** (no network, no signing). The specific
  `auth_provider` implementation is behind a small factory so it can be swapped
  without touching `build_agent`.
- **LIVE (to be validated, §9):** the first candidate mechanism is a `botocore`
  SigV4 `httpx.Auth` for the Gateway's signing service in `gateway_region`,
  carrying the caller's IAM identity (which needs `bedrock-agentcore:
  InvokeGateway` on the gateway ARN *(inv §2.3)*). The exact signing service
  name and SSO-role acceptance are confirmed during the LIVE step, not asserted
  here.
- **Documented fallback (if SigV4-over-MCP does not work):** switch the stack
  parameter `authorizerType` to `CUSTOM_JWT` and stand up a minimal Cognito
  app-client, having the agent fetch a client-credentials bearer token and pass
  it via the `MCPClient` `auth`/`headers` bearer path *(inv §2.3 documents this
  path)*. This is the production-shaped option and is the escape hatch if IAM
  inbound proves impractical for the SSO role.

Rationale for defaulting `AWS_IAM`: lowest setup for an in-account,
operator-deployed demo (no user pool). `NONE` is rejected *(inv §2.3)*.

### 6.5 Rollout / fallback

DIRECT stays the default and the test baseline. GATEWAY is opt-in via env, so
the two modes coexist; if the Gateway is down or not yet deployed, unset
`MAHALO_TOOL_MODE` (or set `direct`) and the agent runs exactly as in Task 2.
The direct-HTTP tools are never removed.

---

## 7. Decision D — IaC + auth (the `MahaloGatewayStack`)

### 7.1 Stack contents (native CDK, `infra-cdk/mahalo_infra/gateway_stack.py`) — revised per Finding 2

`MahaloGatewayStack.__init__` takes the four `MockServiceStack` instances (or
their `lambda_.Function` objects) as **constructor arguments** — passed from
`app.py` — so the Lambda ARNs arrive by **direct construct reference**. CDK then
auto-creates the cross-stack reference and an implicit dependency; there is **no
`Fn.import_value`** and **no change to `mock_service_stack.py`** (its
`CfnOutput`s have no `export_name`, so they are not CloudFormation Exports and
could not be imported by name — the review's Finding 2, verified).

Using `aws_cdk.aws_bedrockagentcore` L1 constructs *(inv §4)*:

1. **Gateway IAM service role** (`aws_iam.Role`) — trust principal
   `bedrock-agentcore.amazonaws.com`; inline policy granting
   `lambda:InvokeFunction` on the four referenced function ARNs only
   (least-privilege). ARNs come from `stack.function.function_arn`.
2. **`CfnGateway`** — `name="mahalo-gateway"`, `protocolType="MCP"`,
   `roleArn=<role>`, `authorizerType=<stack param, default "AWS_IAM">`,
   `protocolConfiguration.mcp.supportedVersions=[...]` as required by the model
   *(inv §2.1)*.
3. **Four `CfnGatewayTarget`s** — each `gatewayIdentifier=<gateway ref>`,
   `name="mock-<svc>"`, `targetConfiguration.mcp.lambda = { lambdaArn:
   <stack.function.function_arn>, toolSchema: { inlinePayload:
   [<ToolDefinition...>] } }`, `credentialProviderConfigurations=[{
   credentialProviderType: "GATEWAY_IAM_ROLE"}]` *(inv §2.1, §2.4)*. The
   `inlinePayload` is generated from `tool_schemas.py` (§3.5) so schema and
   adapter never drift.
4. **Lambda invoke permission** — grant each referenced function a
   resource-based permission allowing the Gateway service/role to invoke it. Use
   `fn.add_permission(...)` on the passed-in construct (the function is now a
   real cross-stack construct reference, so this works without `CfnPermission`
   gymnastics) *(inv §2.4)*.
5. **CfnOutputs** — `GatewayId`, `GatewayArn`, `GatewayMcpUrl` so the operator
   can set `MAHALO_GATEWAY_MCP_URL` for the agent, and so Task 5/6 can consume
   them.

### 7.2 Monthly-reset survivability

Everything is CDK, re-deployable from scratch: `cdk deploy --all` recreates the
four mock stacks and then `MahaloGatewayStack` (CDK orders them via the implicit
dependency from the construct references) with stable logical ids. No manual
console step, no stored gateway id in code (the agent reads the MCP URL from env,
set from the CfnOutput). Satisfies the "CDK for everything / survives a monthly
account reset" constraint *(inv §4; docs/PLAN.md, docs/CONTINUATION.md)*.

### 7.3 Non-blocking for Task 5/6

- **Task 5 (Memory/Identity):** the `authorizerType` is a stack parameter, so
  later adding AgentCore Identity/Workload-identity or switching to `CUSTOM_JWT`
  is a parameter change, not a redesign. The IAM role is isolated and extendable.
- **Task 6 (Runtime):** the agent reads Gateway config purely from env, so
  moving the agent into AgentCore Runtime only changes *where* the signing
  identity comes from (the Runtime execution role instead of the `lava` profile),
  not the design. No lock-in.

### 7.4 Invariant ownership

| Invariant | Owner | Why there |
|---|---|---|
| Model args shape/type/required | Gateway (`inputSchema`) | validated before Lambda invoke *(inv §2.2)* |
| Business rules (404/409/422, required fields) | `routes.py` (frozen) | single existing owner; adapter forwards |
| Assignee name→dev-id resolution | `common/assignee.py` (single source) | one body, used by agent + Lambda composite (§3.4) |
| Write approval (6 tools) | agent `WriteApprovalHook` | pre-invocation interrupt *(inv §1.3)* |
| Inbound caller authn/authz | Gateway `authorizerType` (default `AWS_IAM`) | real auth boundary; mechanism LIVE-validated (§6.4) |
| Gateway→Lambda authn | `GATEWAY_IAM_ROLE` + Lambda resource permission | *(inv §2.4)* |
| Tool schema ↔ adapter parity | `tool_schemas.py` (single source) | prevents drift between CDK and Lambda |

---

## 8. Testability

**Unit-testable offline (new tests, must pass in the gate):**

- `common/gateway_adapter.py` — feed synthetic Gateway events (flat args map +
  a fake `context.client_context.custom['bedrockAgentCoreToolName']`) for a
  representative read, write, error (404/409), and composite tool per service;
  assert (a) the dispatched route, (b) the unwrapped **JSON payload** equals the
  route body data (Finding 1 — assert JSON, not a formatted string), and (c) the
  §5.4 error string equals `make_request`'s for the same raw body (Finding 4).
  Uses the existing in-memory store pattern from `tools-lambdas/tests`.
- **Composite parity (Finding 3)** — one shared developer fixture fed to the
  agent helper and to `common.assignee.resolve_assignee` + the Lambda composite;
  assert identical dev-id resolution across **all six branches** of
  `_resolve_assignee` (verified in `jira_tools.py`):
  exact-name, first-name, email-local-part, no-match, **dev-id passthrough**
  (`assignee="dev-3"` → `"dev-3"` regardless of / even with an empty developer
  fixture, since the branch short-circuits before `_fetch_developers`), and
  **ambiguous match** (an input that partially matches two developers → `None`
  in both implementations, from the `len(matches) == 1` branch) — revision-3
  Finding 3. Also assert the ServiceNow composite's grouped JSON matches the
  agent aggregation's data for the same fixture.
- `tool_schemas.py` parity — assert all 25 names present; the six write names
  match `WRITE_TOOL_NAMES`; each schema `type` is `object`; **exact bidirectional
  arg-set equality** between each DIRECT `@tool` signature's parameter names and
  its schema `properties` keys — i.e. the two sets are equal, so a *missing* arg
  (e.g. dropping ServiceNow `environment`/`service`) AND a *spurious* arg (e.g. a
  non-existent `service_id`) both fail the gate (revision-3 Finding 1; the prior
  one-way "covered by" assertion would have let a spurious arg pass silently);
  and **no name in `tool_schemas.py` or `WRITE_TOOL_NAMES` contains the substring
  `___`** (Finding 9). The `@tool` parameter set is derived from the live
  function signatures (e.g. via `inspect.signature`) so the test reads the real
  args, not a hand-copied list.
- `agent/approval.py` prefix handling — assert `_bare_name` strips `___`, a
  `mock-github___github_create_branch` tool_use triggers `interrupt`, a
  non-APPROVE resume sets `cancel_tool`, and a read tool passes through (§4.4).
- `build_agent(tool_mode="gateway")` offline — imports/constructs cleanly with
  no AWS call/network (MCP client constructed, not started); returns the
  `(agent, mcp_client)` tuple.
- CDK `assertions.Template` over `MahaloGatewayStack` — one `CfnGateway`
  (`authorizerType` default `AWS_IAM`), four targets with the expected
  `toolSchema` tool-name sets, the Gateway role with `lambda:InvokeFunction` on
  the four function ARNs, four invoke permissions; and that the stack accepts the
  mock-stack constructs (no `Fn.import_value` in the template).

**Integration-testable (LIVE only, operator-run, NOT in the offline gate):**

- End-to-end agent in GATEWAY mode against the deployed Gateway: "list my
  repositories" → `payment-service`; "show my stories" (dev-6) → `PAY-`;
  a write (`github_create_branch`) → interrupt fires → approve → branch created.
  Mirrors the existing `test_integration_live.py` skip-when-offline pattern so
  the suite still exits 0 offline.
- The §6.4 inbound-auth mechanism (SigV4-over-MCP, or the Cognito fallback) is
  validated here — it is explicitly NOT part of the offline gate.

**Offline acceptance gate (per the task brief) — all must hold:**

1. `cdk synth` succeeds for `MahaloGatewayStack` (+ existing stacks).
2. `build_agent(tool_mode="gateway")` imports/constructs cleanly (no AWS/net).
3. New unit tests (adapter, composite parity, schema parity, prefix HITL, CDK
   assertions) pass.
4. Existing agent suite stays green: **42 passed, 1 skipped** (tunnel-down live
   test), in DIRECT mode (unchanged).
5. **Zero LangChain** anywhere.

No auto-deploy of the Gateway or Lambdas is planned here; live steps are §9.

---

## 9. LIVE operator steps (run by a human, separate from the offline gate)

1. `aws sso login --profile lava` (already done this session).
2. From `infra-cdk/`: `cdk deploy --all --profile lava` (CDK deploys the four
   mock stacks first, then `MahaloGatewayStack`, via the construct-reference
   dependency).
3. Copy the `GatewayMcpUrl` CfnOutput → set `MAHALO_GATEWAY_MCP_URL` and
   `MAHALO_TOOL_MODE=gateway` in the agent environment.
4. Confirm the caller IAM principal has `bedrock-agentcore:InvokeGateway` on the
   gateway ARN.
5. **Validate inbound auth (the §6.4 open item):** run a single GATEWAY-mode
   tool call and confirm the SigV4 `httpx.Auth` (correct signing service name)
   is accepted by the `AWS_IAM` authorizer for the SSO admin role. If it is not,
   switch `authorizerType` to `CUSTOM_JWT`, stand up the Cognito app-client, and
   use the bearer-token path (§6.4 fallback). Record which mechanism worked.
6. Run the LIVE integration check (§8) and record outcomes in
   `docs/.agents/tasks/task4-verification.md`.

These are documented, not executed; no live/deploy results are fabricated here.

---

## 10. File change summary

**New**

- `infra-cdk/mahalo_infra/gateway_stack.py` — `MahaloGatewayStack` (§7).
- `tools-lambdas/common/gateway_adapter.py` — Gateway→Router shim (§5).
- `tools-lambdas/common/tool_schemas.py` — 25-tool single source of truth (§3.5).
- `tools-lambdas/common/assignee.py` — single `resolve_assignee` pure function
  (§3.4, Finding 3).
- `tools-lambdas/jira/composites.py`, `tools-lambdas/servicenow/composites.py` —
  composite handlers (§3.4).
- `agent/gateway_client.py` — `_build_gateway_mcp_client()` + pluggable auth
  provider factory (§6.2, §6.4).
- Tests: `tools-lambdas/tests/test_gateway_adapter.py`,
  `tools-lambdas/tests/test_tool_schemas.py`,
  `tools-lambdas/tests/test_composites_parity.py`,
  `agent/tests/test_gateway_mode.py`, `infra-cdk/tests/test_gateway_stack.py`,
  and new HITL-prefix cases in `agent/tests/test_write_tools_unit.py`.

**Changed**

- `infra-cdk/app.py` — capture the four `MockServiceStack` instances and pass
  them into `MahaloGatewayStack` (§7.1).
- `tools-lambdas/<svc>/handler.py` (×4) — source-branch dispatch inside the
  existing try/except, after seeding (§5.1).
- `tools-lambdas/jira/*` + `tools-lambdas/servicenow/*` — add the composite
  modules (§3.4) (no change to existing `routes.py`).
- `agent/config.py` — `tool_mode`, `gateway_mcp_url`, `gateway_region` via
  `_getenv` (§6.1).
- `agent/strands_agent.py` — `tool_mode` branch; returns `(agent, mcp_client)`
  in gateway mode (§6.2).
- `agent/approval.py` — `_bare_name` prefix strip in the hook and
  `build_proposal` (§4.2).
- `agent/chat.py` — MCP context-manager wrap in gateway mode (§6.3).
- `agent/tools/jira_tools.py` — `_resolve_assignee` becomes a thin wrapper over
  `common.assignee.resolve_assignee` (only to collapse the duplicate resolver to
  one source; behavior unchanged) (§3.4).
- `infra-cdk/requirements.txt` — pin floor `aws-cdk-lib>=2.251,<3` (§2).

**Frozen (NOT changed):** the rest of `agent/tools/*.py`,
`tools-lambdas/<svc>/routes.py`, `tools-lambdas/common/router.py`,
`tools-lambdas/common/auth.py`, **`infra-cdk/mahalo_infra/mock_service_stack.py`**
(Finding 2 — stays frozen because ARNs now flow by construct reference), and all
of `mahalo-dock`.

---

## 11. Decisions recap

- **A. Granularity** — 25 fine-grained MCP tools across 4 per-service Lambda
  targets, names identical to today's `@tool`s, docstrings→`ToolDefinition`
  descriptions, three composites pushed server-side (porting `_resolve_assignee`
  to `common/assignee.py` and the ServiceNow aggregation, pinned to one source
  with a parity test). Single source of truth in `tool_schemas.py`. Equivalence
  is **data-level** (GATEWAY tools return JSON; the model re-formats), not
  byte-for-byte text.
- **B. HITL** — native `BeforeToolCallEvent` interrupt preserved; the hook and
  proposal builder strip the Gateway `target___tool` prefix via
  `rsplit("___", 1)[-1]`, a no-op for local names — one hook, both modes; a test
  asserts no tool name contains `___`.
- **C. Dual-mode** — `MAHALO_TOOL_MODE` env flag (`direct` default | `gateway`),
  plus `MAHALO_GATEWAY_MCP_URL` and `MAHALO_GATEWAY_REGION`, all `_getenv`-backed;
  DIRECT is unchanged so the existing suite stays green; GATEWAY adds an
  `MCPClient` (constructed offline-safe, used inside its context manager, agent
  returned as a `(agent, mcp_client)` tuple). Direct-HTTP tools are not removed.
- **D. IaC + auth** — native CDK `MahaloGatewayStack` (`CfnGateway` +
  4×`CfnGatewayTarget` + Gateway IAM role + Lambda invoke permissions); the four
  Lambda ARNs flow by **direct construct reference** (Task 3 stays frozen, no
  `Fn.import_value`); `authorizerType` defaults to `AWS_IAM` but the agent-side
  SigV4-over-MCP mechanism is a **LIVE-validated** step with a `CUSTOM_JWT`+
  Cognito fallback; outbound `GATEWAY_IAM_ROLE`; fully re-deployable
  (monthly-reset-safe) and non-blocking for Tasks 5–6.
- **E (mandatory).** A `common/gateway_adapter.py` shim is required because a
  Gateway Lambda-target event is not HTTP-shaped; it maps `(toolName, args)` →
  the existing `Router` (inside the handler's seeded try/except), injects the
  expected token, and unwraps the HTTP envelope to the route's **JSON** on
  success / an `{"error": "...status <code>: <raw body>"}` object on failure,
  with concrete per-failure error handling.

---

## 12. Responses to the design review (`task4-design-review.json`)

**Finding 1 (HIGH — behavior equivalence) — ADDRESSED.** The goal is redefined
to **semantic/data equivalence**. "Byte-for-byte" is removed from §1, §3, §5,
§8, §11. The GATEWAY tool-result payload is now specified exactly: the route's
JSON body on success (`json.loads(result["body"])`), an `{"error": ...}` object
on failure (§5.2, §5.4). Tests assert the JSON payload, not the formatted
sentence (§8). I accepted the review's recommended option (a) and explicitly
rejected moving formatting server-side (it would un-freeze `agent/tools/*` and
balloon scope).

**Finding 2 (HIGH — `Fn.import_value`) — ADDRESSED.** Adopted the review's
option (b): the four Lambda ARNs reach `MahaloGatewayStack` by **direct CDK
construct reference** (`app.py` passes the `MockServiceStack` instances in), so
CDK auto-wires the cross-stack reference and `mock_service_stack.py` stays frozen
(§3.1, §7.1, §10). All `Fn.import_value("JiraArn")` text is removed. Chosen over
option (a) because it keeps the frozen-Task-3 intent the design repeatedly
promises.

**Finding 3 (MEDIUM — composites) — ADDRESSED.** §3.4 now states explicitly that
the composites require **porting** `_resolve_assignee` and the ServiceNow
aggregation (net-new in the Lambdas), pins the resolver to a single source
(`tools-lambdas/common/assignee.py`, imported by both the agent wrapper and the
Lambda composite), lists it as a new deliverable (§10), and adds a composite
**parity test** (§8).

**Finding 4 (MEDIUM — error string) — ADDRESSED.** §5.4 now specifies
`err = f"Request failed with status {status}: {result['body']}"` using the
unparsed route body string (matching `httpx` `response.text`, verified in
`agent/tools/http.py`), not an extracted `detail`, with a test asserting
equality to `make_request` for the same body.

**Finding 5 (MEDIUM — handler dispatch) — ADDRESSED.** §5.1 now mirrors the live
`handler.py`: the Gateway branch runs **inside** the existing
`try/except ClientError→503 / Exception→500`, **after** `store.ensure_seeded()`,
and passes the freshly constructed `store, router` to `gateway_adapter.handle`
(the stale `_store` global argument is dropped).

**Finding 6 (MEDIUM — unverified SigV4) — ADDRESSED.** §2, §6.4, §7.3 no longer
present SigV4-over-MCP as settled. `authorizerType` defaults to `AWS_IAM` (a
stack parameter), the offline gate only requires the MCP client to *construct*,
and the working signing mechanism is an explicit **LIVE-validated** step (§9
step 5) with a documented `CUSTOM_JWT`+Cognito fallback.

**Finding 7 (NIT — config env vars) — ADDRESSED.** §6.1 gives an explicit
`_getenv`-backed env var for all three fields: `MAHALO_TOOL_MODE`,
`MAHALO_GATEWAY_MCP_URL`, `MAHALO_GATEWAY_REGION` (defaulting to `aws_region`).

**Finding 8 (NIT — arg-mapping quirks) — ADDRESSED.** §5.3 declares
`tool_schemas.py` the authoritative arg-mapping source and enumerates the full
25-row table, including `github_get_commits → query: author` (vs
`github_get_pull_requests → author_id`) and the other known quirks.

**Finding 9 (NIT — `___` strip invariant) — ADDRESSED.** §4.4 and §8 add a test
asserting that no name in `tool_schemas.py` or `WRITE_TOOL_NAMES` contains the
substring `___`, enforcing the strip invariant mechanically.

---

## 13. Responses to the SECOND design review (`task4-design-review.json`, revision 3)

The second review returned `CHANGES_REQUESTED` with 1 MEDIUM and 2 NIT (0 HIGH).
All three are resolved in this revision; each was independently re-verified
against source before editing.

**Finding 1 (MEDIUM — §5.3 ServiceNow list rows wrong) — ADDRESSED.** Verified
against `agent/tools/servicenow_tools.py` and `tools-lambdas/servicenow/routes.py`:

- `servicenow_list_deployments` — the real `@tool` signature is
  `(service, environment, status)` and `list_deployments` reads query params
  `service`, `environment`, `status`. The §5.3 row is corrected to
  `query: service, environment, status` (the prior `status, service_id`
  mis-named `service` as `service_id` and dropped `environment`).
- `servicenow_list_incidents` — the real `@tool` signature is
  `(severity, status, service)` and `list_incidents` reads `severity`, `status`,
  `service` (plus an `assignee` filter the `@tool` does NOT expose). The §5.3
  row is corrected to `query: severity, status, service`; the design now states
  **explicitly** that `assignee` is deliberately NOT surfaced, to stay equivalent
  with the current `@tool`.

Because `tool_schemas.py` is declared the authoritative source feeding both the
Gateway `inputSchema` and the adapter `arg_mapping`, the §8 schema-parity test is
also strengthened (per the review's concrete fix) from one-way "args covered by
properties" to **exact bidirectional arg-set equality**, so a missing arg
(`environment`/`service`) AND a spurious arg (`service_id`) both fail the offline
gate rather than passing silently.

**Finding 2 (NIT — adapter success predicate) — ADDRESSED.** Verified
`agent/tools/http.py::make_request` treats **only** 200 and 201 as success
(`if response.status_code in (200, 201)`). §5.2 step 6 and §5.4 now specify the
adapter's success predicate as `statusCode in (200, 201)` (not a loose "2xx"),
so a hypothetical 202/204 route is routed to the error-string path in both modes,
keeping the adapter behavior-equivalent to `make_request`.

**Finding 3 (NIT — composite parity test coverage) — ADDRESSED.** Verified
`jira_tools.py::_resolve_assignee` has two branches the prior test list omitted:
a dev-id passthrough (`val.startswith("dev-")` returns `val` **before**
`_fetch_developers`, so it is independent of the developer list) and an
ambiguous-match case (`len(matches) == 1` else `None`). §3.4 and §8 now specify
the parity test covers **all six** branches, adding (a) `assignee="dev-3"` →
`"dev-3"` regardless of the developer fixture and (b) an input partially matching
two developers → `None` in both implementations.
