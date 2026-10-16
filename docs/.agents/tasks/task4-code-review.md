# AgentCore Gateway + MCP exposure layer for the mock services (Task 4)

Task 4 puts the four Task-3 mock-service Lambdas (Jira, Confluence, GitHub,
ServiceNow) behind one Amazon Bedrock AgentCore Gateway and exposes their 25
operations as MCP tools the Strands agent can call, while keeping the existing
direct-HTTP tools as the default. The change adds a dual-mode toggle
(`MAHALO_TOOL_MODE`, default `direct`), a Gateway→Router adapter inside each
Lambda so a non-HTTP Gateway invocation still reaches the frozen routes, three
server-side composites that reproduce agent-only orchestration, a single
`tool_schemas.py` source of truth consumed by both the CDK stack and the Lambda
adapter, and a prefix-aware HITL hook so the six writes stay gated when Gateway
renames tools to `target___tool`. A new `MahaloGatewayStack` provisions the
Gateway, four Lambda targets, the IAM role, and the invoke permissions in native
CDK.

Watch for: (1) the documented, legitimate deviation from the design's
offline-safety claim — a bare `MCPClient` passed to `Agent(tools=[...])` would
start the client at construction, so gateway-mode builds with `tools=[]` and a
separate `attach_gateway_tools` call inside `with mcp_client:` (confirmed; sound
and tested). (2) The inbound-auth mechanism (SigV4-over-MCP vs Cognito JWT) is
deferred to a LIVE operator step and is NOT exercised offline (confirmed, matches
the design's explicit deferral). (3) Everything here is offline-gated only; the
Gateway and Lambdas were not deployed (confirmed, correct per the plan).

**Verdict**: APPROVED

## High-level view

Tool granularity and behavior equivalence are handled by `tool_schemas.py`, a
25-row registry where each tool's name equals the current `@tool` function name
and each `input_schema` is checked for exact bidirectional arg parity against the
live function signatures. Reads flow through a synthetic Function-URL request
into the frozen router; the three composites (`jira_search_stories`,
`jira_get_stories_by_assignee`, `servicenow_deployment_status_by_project`) run
server-side and return structured JSON rather than DIRECT mode's formatted
string — the documented data-level (not text-level) equivalence.

HITL is preserved correctly. Gateway renames every tool to `target___tool`;
`_bare_name` strips that via `rsplit("___", 1)` before the write-name match and
before `build_proposal`'s prefix parse, a no-op for bare DIRECT names. The
prefixed-name interrupt, reject, and read-passthrough paths are all tested. This
was the investigation's single biggest correctness risk and it is closed.

Dual-mode keeps DIRECT as the default and untouched; gateway mode is opt-in via
env and returns `(agent, mcp_client)` so the caller can wrap the invocation in
the client's context manager. The direct-HTTP tools are not removed.

The Gateway→Router adapter is the load-bearing new piece: it turns a flat Gateway
args map into a synthetic HTTP request, injects the Lambda's own token so the
frozen `require_token` passes, and unwraps the envelope to JSON on 200/201 or an
`{"error": "...status <code>: <body>"}` object otherwise — byte-identical to the
DIRECT `make_request`. The handler branch sits inside the existing
try/except, after seeding, and leaves the DIRECT dispatch untouched.

IaC is native CDK: `MahaloGatewayStack` takes the four `MockServiceStack`
instances by direct construct reference (no `Fn.import_value`, Task 3 stays
frozen), builds one `CfnGateway` (MCP, `authorizerType` parameter default
`AWS_IAM`), four `CfnGatewayTarget`s with inline toolSchema from the single
source, a least-privilege Gateway role, and a per-Lambda invoke permission.

The single source of truth is the strongest part of the design and it holds: the
schema-parity test fails on either a missing or a spurious arg, so the CDK
toolSchema and the adapter arg-mapping cannot silently drift from the real `@tool`
signatures.

<details>
<summary>Issues (3)</summary>

1. **Offline-safety deviation (informational, resolved)** — the design claimed a
   bare `MCPClient` in `Agent(tools=[...])` constructs offline; against installed
   strands 1.61.1 it eagerly starts the client. The coder correctly builds with
   `tools=[]` + `attach_gateway_tools` inside `with mcp_client:`, documented it,
   and the offline gate confirms `_is_session_active() is False`. No action.
2. **Inbound-auth mechanism unverified (deferred, by design)** — SigV4-over-MCP
   vs the Cognito JWT fallback is a LIVE operator step; the offline gate only
   proves the MCP client constructs. Accept as deferred; the operator must record
   which mechanism the `AWS_IAM` authorizer accepts (plan §9 step 4).
3. **No live deployment yet (deferred, by design)** — the Gateway and Lambdas
   were not deployed and the end-to-end GATEWAY-mode run is unexecuted. Accept as
   deferred; this is the operator's §9 step 5. Nothing in the offline gate is
   fabricated.

</details>

<details>
<summary>Details</summary>

### The single source of truth actually prevents drift

`tools-lambdas/common/tool_schemas.py` holds one descriptor per operation:
`name`, `description`, `input_schema` feed the CDK target's
`toolSchema.inlinePayload`; `method`/`path_template`/`arg_mapping`/`composite`
feed the Lambda adapter. Both the stack and the adapter import this one module,
so a schema the model sees and the wire call the adapter makes are generated from
the same row.

What makes this more than a convention is `test_exact_arg_set_parity_with_at_tool_signatures`
in the agent suite: it reads every live `@tool` signature via `inspect.signature`
and asserts `sig_args == schema_args` for all 25 tools, plus
`set(funcs) == set(BY_NAME)`. Because the assertion is set equality, a dropped arg
(the kind of regression the design's revision-3 Finding 1 was about — ServiceNow
`environment`/`service`) and a spurious arg (a non-existent `service_id`) both
fail the gate. The documented arg quirks are encoded and correct: `github_get_commits`
maps tool arg `author` to query `author` (the route reads `author`, verified in
`github/routes.py`), distinct from `github_get_pull_requests` using `author_id`;
`github_create_branch` maps tool arg `branch_name` to body `name` (the route reads
`body["name"]`); `confluence_search` maps `query` to query `q`.

### Gateway→Router adapter: the behavioral bridge

A Gateway Lambda-target event is a flat args map with the tool name on
`context.client_context.custom['bedrockAgentCoreToolName']` and no HTTP envelope,
so the frozen router would 404 every call. `common/gateway_adapter.py::handle`
bridges it:

```
Gateway event (flat args) + context tool name
        │  _gateway_tool_name(context)  -> "mock-github___github_create_branch"
        ▼
handle(tool_name, store, router, event, token)
        │  bare_name -> descriptor lookup in tool_schemas.BY_NAME
        ├─ composite? ─> jira/servicenow composites.<fn>(store, router, token, args)
        └─ else: build path/query/body from arg_mapping
                 -> gateway_dispatch.build_event (synthetic FU-v2 + x-api-token)
                 -> router.dispatch
                 -> 200/201: json.loads(body) | else: {"error": "...status <c>: <body>"}
```

The error string is built from the raw route body (`result["body"]`), matching
`agent/tools/http.py::make_request` verbatim, and the success predicate is
`status in (200, 201)` — not a loose 2xx — so a hypothetical 202/204 is routed to
the error path exactly as DIRECT mode would. The GitHub 409 "already exists" path
therefore surfaces as the same `{"error": ...}` dict the model already treats as
success. The adapter returns an error object rather than raising for every
expected failure (unknown tool, missing path arg, non-2xx), so only an unexpected
exception reaches the handler's `except Exception → 500`.

One deviation from the design worth noting and accepting: the design said the
adapter would read the Lambda's `MOCK_<SVC>_TOKEN` env var itself; the
implementation passes the handler's existing `_TOKEN` into `handle(...)`. This is
the same value `build_router` already uses and is cleaner (one owner of the token
per handler), not a behavior change.

### Handler dispatch leaves DIRECT untouched

Each of the four `handler.py` files gained an identical branch inside the existing
`try/except ClientError→503 / Exception→500`, after `store.ensure_seeded()`:
resolve the Gateway tool name, and if present dispatch through the adapter with the
freshly constructed `store, router`; otherwise fall through to the unchanged
`router.dispatch(event)`. `_gateway_tool_name` guards on
`isinstance(custom, dict)`, so a Function-URL invocation (no client-context custom
map) takes the DIRECT path. A DynamoDB error in the Gateway path is still caught by
the existing 503 guard. The stale `_store` global is not referenced.

### HITL under the `target___tool` rename

`_bare_name(name) = name.rsplit("___", 1)[-1]` is applied in both
`WriteApprovalHook._before_tool_call` (before the `WRITE_TOOL_NAMES` membership
test) and `build_proposal` (before `partition("_")` derives system/action). A bare
local name has no `___`, so the strip is a no-op for DIRECT mode — one hook serves
both. `WRITE_TOOL_NAMES` stays the six bare names and equals the
`tool_schemas.WRITE_TOOL_NAMES` set (asserted). The tests exercise the real risk:
`mock-github___github_create_branch` raises the interrupt on the first pass and
builds a proposal with `action == "create_branch"` / `system == "github"` from the
bare name; a `REJECT` resume sets `cancel_tool`; `mock-jira___jira_get_story`
passes straight through. A separate test asserts no tool name or write name
contains `___`, so the delimiter is unambiguous.

### Dual-mode and the offline-safety deviation

`build_agent(tool_mode=...)` defaults to `settings.tool_mode` (`direct`). DIRECT
returns the bare `Agent` with the 25 local tools — unchanged, which is why the
existing suite stays at the 42/1 baseline. The documented deviation: passing an
`MCPClient` into `Agent(tools=[...])` triggers `ToolProvider.load_tools()` during
`__init__` against strands 1.61.1, which starts the client (network). To keep
`build_agent(tool_mode="gateway")` offline-safe, gateway mode constructs the agent
with `tools=[]` and the caller attaches tools via `attach_gateway_tools(agent,
mcp_client)` inside `with mcp_client:`. `chat.py` does exactly this in both
`_run_single` and `_run_repl`, mode-gated, with the DIRECT fallback unchanged. The
offline gate confirms the resulting client reports `_is_session_active() is False`.
This is a legitimate correction of the investigation's assumption, not a shortcut,
and the HITL contract and the six gated writes are unaffected.

`gateway_client._build_gateway_mcp_client()` raises `ValueError` if
`MAHALO_GATEWAY_MCP_URL` is unset — a fail-fast on misconfiguration rather than an
opaque failure at first invocation — and the auth provider is pluggable behind a
factory defaulting to `None` so offline construction stays dependency-free.

### Composites reproduce agent-only orchestration server-side

The three non-1:1 operations are pushed behind the tool so GATEWAY mode stays
purely MCP. `jira/composites.py` resolves the assignee via the shared
`common.assignee.resolve_assignee`, fans out over projects/stories through the
in-Lambda router, and applies the keyword filter client-side for
`search_stories` — mirroring the DIRECT `jira_tools` logic, including the "Could
not resolve assignee ... Available developers: ..." error shape.
`servicenow/composites.py::deployment_status` reproduces the group-by-service,
count-by-status, latest-by-`deployed_at` aggregation from
`servicenow_tools.py`. Both return structured JSON, consistent with the design's
data-level equivalence: the DIRECT tool returns a formatted string and the model
renders the GATEWAY JSON, so wording can differ but the records, ids, and filter
behavior match.

Assignee resolution is pinned to one body in `common/assignee.py`, and the agent
wrapper (`jira_tools._resolve_assignee`) delegates to it — keeping the `dev-`
short-circuit (returns the lowercased value without fetching developers) and all
six branches intact. The agent reaches `common` via an import-time, offline-safe
`sys.path` shim to the `tools-lambdas` dir. The composite-parity test feeds one
shared fixture through both paths across all six branches (exact-name, first-name,
email-local-part, no-match, `dev-` passthrough against an empty fixture, ambiguous
→ None) and asserts the ServiceNow aggregation JSON matches.

### MahaloGatewayStack: native CDK, Task 3 frozen

`gateway_stack.py` takes the four `MockServiceStack` instances as a dict and reads
`stack.function.function_arn` by direct construct reference, so CDK auto-wires the
cross-stack reference and implicit dependency and `mock_service_stack.py` is not
touched — the design's Finding 2 resolution, verified. The Gateway role trusts
`bedrock-agentcore.amazonaws.com` and grants `lambda:InvokeFunction` on exactly the
four function ARNs (least privilege). One `CfnGateway` (`protocol_type="MCP"`,
`authorizer_type` a `CfnParameter` defaulting to `AWS_IAM` with the four allowed
values, MCP `supported_versions`), four `CfnGatewayTarget`s each with inline
toolSchema generated from `tool_schemas.tools_for_service(svc)` and
`credential_provider_type="GATEWAY_IAM_ROLE"`, and a per-Lambda `add_permission`
for the Gateway principal. `_schema_to_cfn` recurses through nested object/array
schemas (used by `github_commit_files`'s `files` array). Outputs expose
`GatewayId`/`GatewayArn`/`GatewayMcpUrl`. The `requirements.txt` floor bump to
`>=2.251,<3` makes the construct availability explicit.

### Test coverage

Covered: exact bidirectional arg parity against live `@tool` signatures (25
tools); write-name-set equality; `___`-free names; method-XOR-composite per tool;
adapter read/write/404/409/unknown-tool/composite per service with the unwrapped
JSON payload and the byte-identical error string; composite parity across all six
resolver branches and the ServiceNow aggregation; the prefixed-name HITL interrupt,
reject, and read-passthrough; `build_agent(tool_mode="gateway")` offline
construction with the client not started; default mode `direct`; and the CDK
assertions (one gateway, four targets with matching tool-name sets, the role grant,
four invoke permissions, no `Fn::ImportValue`).

Not tested (by design, LIVE only): the inbound-auth signing mechanism against a
real `AWS_IAM` authorizer; the end-to-end GATEWAY-mode agent run (list repos →
payment-service; dev-6 stories → PAY-; a write → interrupt → approve → branch
created); and that a deployed Gateway actually renames tools to `target___tool` on
the wire (the strip is unit-tested, the live format is assumed from the AWS doc).
These are the operator's §9 steps and are honestly marked deferred, not fabricated.

### Success criteria check

(1) Documented, working path for the agent to call the four mocks through Gateway
as MCP tools, behavior-equivalent to direct-HTTP: yes, via the adapter +
composites, with data-level equivalence precisely defined and the six writes still
going through propose/approve. (2) HITL gates writes in Gateway-MCP mode: yes, via
the prefix-aware hook, tested on the prefixed name. (3) DIRECT remains the default
and the existing suite stays green (42/1 preserved inside 52 passed/1 skipped),
Gateway opt-in via env: yes. (4) New IaC synthesizes offline, zero LangChain,
existing agent behavior additive-only: yes per the recorded gate. (5) The three
docs are present and not fabricated: design (rev 3), plan, and investigation are
all present, internally consistent, and the verification honestly separates the
offline gate from the deferred LIVE steps. The direct-HTTP tools were not removed
and the default mode was not changed.

</details>

<details>
<summary>File map</summary>

New:
- `tools-lambdas/common/tool_schemas.py` — 25-tool single source of truth (schema + adapter mapping).
- `tools-lambdas/common/gateway_adapter.py` — Gateway→Router shim, envelope unwrap.
- `tools-lambdas/common/gateway_dispatch.py` — synthetic FU-v2 request builder + JSON helper.
- `tools-lambdas/common/assignee.py` — single `resolve_assignee` body.
- `tools-lambdas/jira/composites.py`, `tools-lambdas/servicenow/composites.py` — server-side composites.
- `agent/gateway_client.py` — offline-safe `MCPClient` builder + pluggable auth factory.
- `infra-cdk/mahalo_infra/gateway_stack.py` — `MahaloGatewayStack`.
- Tests: `tools-lambdas/tests/test_gateway_adapter.py`, `test_tool_schemas.py`, `test_composites_parity.py`; `agent/tests/test_gateway_mode.py`; `infra-cdk/tests/test_gateway_stack.py`.

Changed:
- `tools-lambdas/{jira,confluence,github,servicenow}/handler.py` — Gateway dispatch branch, DIRECT path unchanged.
- `agent/config.py` — `tool_mode`/`gateway_mcp_url`/`gateway_region` via `_getenv` (DIRECT default).
- `agent/strands_agent.py` — gateway-mode branch, `attach_gateway_tools`.
- `agent/approval.py` — `_bare_name` prefix strip in hook and `build_proposal`.
- `agent/chat.py` — gateway-mode MCP context wrap; DIRECT unchanged.
- `agent/tools/jira_tools.py` — `_resolve_assignee` thin wrapper over shared body.
- `infra-cdk/app.py` — capture mock stacks, instantiate `MahaloGatewayStack`.
- `infra-cdk/requirements.txt` — floor bump `aws-cdk-lib>=2.251,<3`.
- `agent/tests/test_write_tools_unit.py` — prefixed-name HITL cases.

Full diff: `git diff` against the working tree (changes are unstaged on `main`).

</details>
