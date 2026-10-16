# Task 4 — Verification (AgentCore Gateway + MCP exposure layer)

Status: OFFLINE GATE GREEN (re-run). This records the OFFLINE acceptance gate
only — the Gateway and Lambdas were NOT deployed (deploy is billable/account-
mutating and is a DEFERRED operator step; see §DEFERRED below). No live/deploy
results are fabricated.

Scope guardrail honored: every file created/modified is under
`D:/lavakumar.baskaran/LavaCode/AI/mahalo-agentcore`; nothing was written to
`mahalo-dock`. No git commit/push performed by this step.

Implementation was code-reviewed and APPROVED
(`docs/.agents/tasks/task4-code-review.json` / `.md`, verdict APPROVED).

---

## What was implemented (summary; full detail in the code review)

New files:
- `tools-lambdas/common/assignee.py` — single `resolve_assignee` pure function
  (shared by the agent wrapper and the Jira composites).
- `tools-lambdas/common/tool_schemas.py` — the 25-tool single source of truth
  (name/description/input_schema + method/path_template/arg_mapping/composite),
  consumed by both the CDK stack and the Lambda adapter.
- `tools-lambdas/common/gateway_dispatch.py` — shared synthetic Function-URL-v2
  request builder + envelope unwrap helper.
- `tools-lambdas/common/gateway_adapter.py` — Gateway→Router shim: strips the
  `___` prefix, looks up the descriptor, dispatches composite or synthetic
  request (injecting the service token), unwraps the HTTP envelope to JSON on
  200/201 or `{"error": "Request failed with status <code>: <body>"}` otherwise
  (byte-identical to `agent/tools/http.py::make_request`).
- `tools-lambdas/jira/composites.py`, `tools-lambdas/servicenow/composites.py` —
  the three server-side composites (search_stories, stories_by_assignee,
  deployment_status).
- `infra-cdk/mahalo_infra/gateway_stack.py` — `MahaloGatewayStack`
  (`CfnGateway` MCP + 4× `CfnGatewayTarget` with inline toolSchema from
  `tool_schemas.py` + Gateway IAM role + per-Lambda invoke permission;
  `authorizerType` CfnParameter default `AWS_IAM`; outbound `GATEWAY_IAM_ROLE`).
- `agent/gateway_client.py` — `_build_gateway_mcp_client()` (constructed, NOT
  started) + pluggable auth-provider factory.
- Tests: `tools-lambdas/tests/test_gateway_adapter.py`,
  `tools-lambdas/tests/test_tool_schemas.py`,
  `tools-lambdas/tests/test_composites_parity.py`,
  `agent/tests/test_gateway_mode.py`, `infra-cdk/tests/test_gateway_stack.py`.

Changed files:
- `tools-lambdas/<svc>/handler.py` (×4) — Gateway-source dispatch branch INSIDE
  the existing try/except, AFTER `store.ensure_seeded()`, passing the freshly
  constructed `store, router` and the Lambda's own token; the DIRECT HTTP path
  is unchanged.
- `agent/config.py` — `tool_mode`/`gateway_mcp_url`/`gateway_region` via `_getenv`
  (DIRECT is the default).
- `agent/strands_agent.py` — `tool_mode` branch; gateway mode returns
  `(agent, mcp_client)`; added `attach_gateway_tools` so tools load inside the
  MCP context (keeps `build_agent` offline-safe — see note below).
- `agent/approval.py` — `_bare_name` strips the Gateway `<target>___<tool>`
  prefix in the hook and `build_proposal` (no-op for bare local names).
- `agent/chat.py` — GATEWAY mode wraps the invocation in `with mcp_client:` and
  attaches tools; DIRECT path unchanged.
- `agent/tools/jira_tools.py` — `_resolve_assignee` is now a thin wrapper over
  `common.assignee.resolve_assignee` (behavior unchanged).
- `infra-cdk/app.py` — captures the four `MockServiceStack` instances and passes
  them into `MahaloGatewayStack` (ARNs by direct construct reference).
- `infra-cdk/requirements.txt` — floor bumped to `aws-cdk-lib>=2.251,<3`.
- `agent/tests/test_write_tools_unit.py` — prefixed-name HITL cases.

**Frozen as designed:** `tools-lambdas/<svc>/routes.py`, `common/router.py`,
`common/auth.py`, `infra-cdk/mahalo_infra/mock_service_stack.py`, the rest of
`agent/tools/*.py`, and all of `mahalo-dock`.

### Implementation note (deviation from the design's offline-safety claim)

The design asserted that passing an `MCPClient` into `Agent(tools=[...])` is
offline-safe at construction. Against the INSTALLED `strands-agents 1.61.1`,
`ToolRegistry.process_tools` eagerly calls `ToolProvider.load_tools()` during
`Agent.__init__`, which STARTS the MCP client (network). To keep the required
invariant "`build_agent(tool_mode='gateway')` imports/constructs cleanly
offline", the gateway-mode agent is built with `tools=[]` and the MCP provider is
attached via `attach_gateway_tools(agent, mcp_client)` INSIDE `with mcp_client:`
(the documented idiomatic lifecycle). The DIRECT default and the HITL contract
are unchanged; the six writes remain gated.

---

## Offline acceptance gate — commands run and REAL results

Re-run on Windows / PowerShell. Three venvs: `agent/.venv` (agent suite),
`tools-lambdas/.venv` (moto-backed Lambda suite), `infra-cdk/.venv` (CDK). The
`cdk` CLI resolves to `D:\lavakumar.baskaran\AppData\Roaming\npm\cdk.ps1`.

### 1. CDK synth (new + changed IaC)

```powershell
cd infra-cdk ; cdk synth --all
```

Result: exit code **0**; "Successfully synthesized to ...\infra-cdk\cdk.out".
Note: THIS cdk CLI version does not accept `synth --all` — it prints
`Unknown option(s): --all. These will be ignored.` and still synthesizes ALL
stacks (it lists `MahaloMockJiraStack, MahaloMockConfluenceStack,
MahaloMockGithubStack, MahaloMockServicenowStack, MahaloGatewayStack`). All five
templates are produced under `cdk.out/`:

```
MahaloGatewayStack.template.json
MahaloMockConfluenceStack.template.json
MahaloMockGithubStack.template.json
MahaloMockJiraStack.template.json
MahaloMockServicenowStack.template.json
```

`MahaloGatewayStack.template.json` contains exactly **1** `AWS::BedrockAgentCore::Gateway`
and **4** `AWS::BedrockAgentCore::GatewayTarget` resources (one per mock service),
each with an inline `ToolSchema.InlinePayload` and `CredentialProviderConfigurations`
= `GATEWAY_IAM_ROLE`. Benign deprecation warnings
(`CfnResource#addDependency is deprecated`) and a cross-stack-reference-strength
advisory print to stderr; they do NOT affect the exit code.

### 2. CDK assertion suite

```powershell
cd infra-cdk ; .\.venv\Scripts\python.exe -m pytest tests -q
```

Result: **26 passed** (was 20 before Task 4; +6 `test_gateway_stack.py`). Asserts:
one MCP Gateway with `AuthorizerType` default `AWS_IAM`; four targets whose inline
toolSchema name-sets exactly match the per-service `tool_schemas` names; all 25
tool names present across the four targets; the Gateway role grants
`lambda:InvokeFunction` on exactly four Lambda ARNs; each mock stack gains exactly
one gateway invoke permission (principal `bedrock-agentcore.amazonaws.com`); and
no hand-written named import of the Task-3 `*Arn` outputs.

### 3. Lambda / adapter suite (moto, offline)

```powershell
cd tools-lambdas ; .\.venv\Scripts\python.exe -m pytest tests -q
```

Result: **94 passed, 634 warnings** in ~90s (was 68 before Task 4; +26). New
coverage: the adapter (read/write/404/409/unknown-tool/composite per service;
unwrapped JSON payload equals the route body; error string byte-identical to
`make_request`); schema structure (25 tools, write-name set, object schemas,
exactly one of method/composite, no `___` in any name); composite parity (all six
`resolve_assignee` branches; ServiceNow aggregation data equals the agent
aggregation for the same fixture). The existing HTTP handler tests stay green
(DIRECT path untouched). (Warnings are benign — `datetime.utcnow()` deprecation
in botocore and similar.)

### 4. Agent suite (DIRECT baseline preserved + new gateway/HITL tests)

```powershell
# from repo root, agent venv:
D:/lavakumar.baskaran/LavaCode/AI/mahalo-agentcore/agent/.venv/Scripts/python.exe -m pytest agent -q
```

Result: **52 passed, 1 skipped** in ~9s. The 1 skip is the live-integration test
skipping offline (tunnel/creds down) — unchanged. The DIRECT Task-1/2 baseline
(**42 passed, 1 skipped**) is fully preserved; the +10 are the new HITL-prefix
cases in `test_write_tools_unit.py` and `test_gateway_mode.py` (offline gateway
build returns `(agent, mcp_client)` with the client NOT started; `MAHALO_TOOL_MODE`
default is `direct`; EXACT bidirectional arg-set parity between every live `@tool`
signature and its `tool_schemas` descriptor).

### 5. build_agent gateway-mode imports/constructs cleanly offline

```powershell
$env:MAHALO_GATEWAY_MCP_URL="https://example.invalid/mcp"
D:/.../agent/.venv/Scripts/python.exe -c "from agent.strands_agent import build_agent; a, c = build_agent(tool_mode='gateway'); print(type(a).__name__, type(c).__name__, c._is_session_active())"
```

Result: `Agent MCPClient False` (exit 0) — constructs with no AWS call / no
network; the MCP client is constructed but NOT started
(`_is_session_active() == False`).

### 6. Zero LangChain

```powershell
# ripgrep over agent / tools-lambdas / infra-cdk python sources (excluding .venv)
```

Result: **no matches** for `langchain` in any `.py` under `agent`,
`tools-lambdas`, or `infra-cdk`. Confirmed zero LangChain.

---

## Gate summary

| # | Gate | Command | Result |
|---|------|---------|--------|
| 1 | CDK synth | `cdk synth --all` (infra-cdk) | exit 0; 5 templates; Gateway has 1 Gateway + 4 Targets |
| 2 | CDK assertion suite | `pytest tests -q` (infra-cdk) | 26 passed |
| 3 | Lambda/adapter suite | `pytest tests -q` (tools-lambdas) | 94 passed |
| 4 | Agent suite | `pytest agent -q` (agent venv) | 52 passed, 1 skipped (DIRECT 42/1 preserved) |
| 5 | Gateway-mode build | `build_agent(tool_mode='gateway')` | `Agent MCPClient False` (constructed, not started) |
| 6 | Zero LangChain | grep `langchain` | no matches |

All six offline-gate conditions hold.

---

## Live SSO session note (no live probe run)

`aws sts get-caller-identity --profile lava` returned a valid identity
(account 051570254217, AWSAdministratorAccess SSO role), so the `lava` session
was up during this run. No live probe was run: a meaningful GATEWAY-MCP probe
requires an actually-deployed Gateway endpoint, and standing one up is the
billable/account-mutating deploy that is explicitly DEFERRED to the operator.
The optional probe is never a substitute for the offline gate, which is green
above. No live/deploy results are fabricated.

---

## DEFERRED — LIVE operator steps (NOT run here; no results fabricated)

These require `aws sso login --profile lava` and create/modify real AWS
resources, so they are left for the operator:

1. **Deploy the four Lambdas + the Gateway stack.** From `infra-cdk/`:
   `cdk deploy --all --profile lava`. CDK deploys the four `MockServiceStack`
   Lambdas first, then `MahaloGatewayStack` (Gateway + four Lambda targets +
   inbound auth) via the construct-reference dependency.
2. **Point the agent at the Gateway MCP endpoint.** Copy the `GatewayMcpUrl`
   CfnOutput → set `MAHALO_GATEWAY_MCP_URL` and `MAHALO_TOOL_MODE=gateway` in the
   agent environment.
3. **Confirm invoke permission.** Ensure the caller IAM principal has
   `bedrock-agentcore:InvokeGateway` on the gateway ARN.
4. **Validate inbound auth** (design §6.4 open item): run one GATEWAY-mode tool
   call and confirm the SigV4 `httpx.Auth` (correct signing service name) is
   accepted by the `AWS_IAM` authorizer for the SSO admin role. If not, switch
   `authorizerType` to `CUSTOM_JWT`, stand up a Cognito app-client, and use the
   bearer-token path. Record which mechanism worked.
5. **End-to-end GATEWAY-mode checks through the Gateway:**
   - a READ: "list my repositories" → payment-service; "show my stories" (dev-6)
     → PAY- stories;
   - a HITL WRITE: a `github_create_branch` request → the `WriteApprovalHook`
     interrupt fires → approve → branch created (confirm by a follow-up read);
     a reject writes nothing.
   Record the real outcomes here when run.
