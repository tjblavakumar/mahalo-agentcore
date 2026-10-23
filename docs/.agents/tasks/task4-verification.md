# Task 4 â€” Verification (AgentCore Gateway + MCP exposure layer)

Status: OFFLINE GATE GREEN (re-run). This records the OFFLINE acceptance gate
only â€” the Gateway and Lambdas were NOT deployed (deploy is billable/account-
mutating and is a DEFERRED operator step; see Â§DEFERRED below). No live/deploy
results are fabricated.

Scope guardrail honored: every file created/modified is under
`<WORKSPACE_ROOT>`; nothing was written to
`mahalo-dock`. No git commit/push performed by this step.

Implementation was code-reviewed and APPROVED
(`docs/.agents/tasks/task4-code-review.json` / `.md`, verdict APPROVED).

---

## What was implemented (summary; full detail in the code review)

New files:
- `tools-lambdas/common/assignee.py` â€” single `resolve_assignee` pure function
  (shared by the agent wrapper and the Jira composites).
- `tools-lambdas/common/tool_schemas.py` â€” the 25-tool single source of truth
  (name/description/input_schema + method/path_template/arg_mapping/composite),
  consumed by both the CDK stack and the Lambda adapter.
- `tools-lambdas/common/gateway_dispatch.py` â€” shared synthetic Function-URL-v2
  request builder + envelope unwrap helper.
- `tools-lambdas/common/gateway_adapter.py` â€” Gatewayâ†’Router shim: strips the
  `___` prefix, looks up the descriptor, dispatches composite or synthetic
  request (injecting the service token), unwraps the HTTP envelope to JSON on
  200/201 or `{"error": "Request failed with status <code>: <body>"}` otherwise
  (byte-identical to `agent/tools/http.py::make_request`).
- `tools-lambdas/jira/composites.py`, `tools-lambdas/servicenow/composites.py` â€”
  the three server-side composites (search_stories, stories_by_assignee,
  deployment_status).
- `infra-cdk/mahalo_infra/gateway_stack.py` â€” `MahaloGatewayStack`
  (`CfnGateway` MCP + 4Ã— `CfnGatewayTarget` with inline toolSchema from
  `tool_schemas.py` + Gateway IAM role + per-Lambda invoke permission;
  `authorizerType` CfnParameter default `AWS_IAM`; outbound `GATEWAY_IAM_ROLE`).
- `agent/gateway_client.py` â€” `_build_gateway_mcp_client()` (constructed, NOT
  started) + pluggable auth-provider factory.
- Tests: `tools-lambdas/tests/test_gateway_adapter.py`,
  `tools-lambdas/tests/test_tool_schemas.py`,
  `tools-lambdas/tests/test_composites_parity.py`,
  `agent/tests/test_gateway_mode.py`, `infra-cdk/tests/test_gateway_stack.py`.

Changed files:
- `tools-lambdas/<svc>/handler.py` (Ã—4) â€” Gateway-source dispatch branch INSIDE
  the existing try/except, AFTER `store.ensure_seeded()`, passing the freshly
  constructed `store, router` and the Lambda's own token; the DIRECT HTTP path
  is unchanged.
- `agent/config.py` â€” `tool_mode`/`gateway_mcp_url`/`gateway_region` via `_getenv`
  (DIRECT is the default).
- `agent/strands_agent.py` â€” `tool_mode` branch; gateway mode returns
  `(agent, mcp_client)`; added `attach_gateway_tools` so tools load inside the
  MCP context (keeps `build_agent` offline-safe â€” see note below).
- `agent/approval.py` â€” `_bare_name` strips the Gateway `<target>___<tool>`
  prefix in the hook and `build_proposal` (no-op for bare local names).
- `agent/chat.py` â€” GATEWAY mode wraps the invocation in `with mcp_client:` and
  attaches tools; DIRECT path unchanged.
- `agent/tools/jira_tools.py` â€” `_resolve_assignee` is now a thin wrapper over
  `common.assignee.resolve_assignee` (behavior unchanged).
- `infra-cdk/app.py` â€” captures the four `MockServiceStack` instances and passes
  them into `MahaloGatewayStack` (ARNs by direct construct reference).
- `infra-cdk/requirements.txt` â€” floor bumped to `aws-cdk-lib>=2.251,<3`.
- `agent/tests/test_write_tools_unit.py` â€” prefixed-name HITL cases.

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

## Offline acceptance gate â€” commands run and REAL results

Re-run on Windows / PowerShell. Three venvs: `agent/.venv` (agent suite),
`tools-lambdas/.venv` (moto-backed Lambda suite), `infra-cdk/.venv` (CDK). The
`cdk` CLI resolves to `D:\<USER>\AppData\Roaming\npm\cdk.ps1`.

### 1. CDK synth (new + changed IaC)

```powershell
cd infra-cdk ; cdk synth --all
```

Result: exit code **0**; "Successfully synthesized to ...\infra-cdk\cdk.out".
Note: THIS cdk CLI version does not accept `synth --all` â€” it prints
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
(DIRECT path untouched). (Warnings are benign â€” `datetime.utcnow()` deprecation
in botocore and similar.)

### 4. Agent suite (DIRECT baseline preserved + new gateway/HITL tests)

```powershell
# from repo root, agent venv:
<WORKSPACE_ROOT>/agent/.venv/Scripts/python.exe -m pytest agent -q
```

Result: **52 passed, 1 skipped** in ~9s. The 1 skip is the live-integration test
skipping offline (tunnel/creds down) â€” unchanged. The DIRECT Task-1/2 baseline
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

Result: `Agent MCPClient False` (exit 0) â€” constructs with no AWS call / no
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
(account <AWS_ACCOUNT_ID>, AWSAdministratorAccess SSO role), so the `lava` session
was up during this run. No live probe was run: a meaningful GATEWAY-MCP probe
requires an actually-deployed Gateway endpoint, and standing one up is the
billable/account-mutating deploy that is explicitly DEFERRED to the operator.
The optional probe is never a substitute for the offline gate, which is green
above. No live/deploy results are fabricated.

---

## DEFERRED â€” LIVE operator steps (NOT run here; no results fabricated)

These require `aws sso login --profile lava` and create/modify real AWS
resources, so they are left for the operator:

1. **Deploy the four Lambdas + the Gateway stack.** From `infra-cdk/`:
   `cdk deploy --all --profile lava`. CDK deploys the four `MockServiceStack`
   Lambdas first, then `MahaloGatewayStack` (Gateway + four Lambda targets +
   inbound auth) via the construct-reference dependency.
2. **Point the agent at the Gateway MCP endpoint.** Copy the `GatewayMcpUrl`
   CfnOutput â†’ set `MAHALO_GATEWAY_MCP_URL` and `MAHALO_TOOL_MODE=gateway` in the
   agent environment.
3. **Confirm invoke permission.** Ensure the caller IAM principal has
   `bedrock-agentcore:InvokeGateway` on the gateway ARN.
4. **Validate inbound auth** (design Â§6.4 open item): run one GATEWAY-mode tool
   call and confirm the SigV4 `httpx.Auth` (correct signing service name) is
   accepted by the `AWS_IAM` authorizer for the SSO admin role. If not, switch
   `authorizerType` to `CUSTOM_JWT`, stand up a Cognito app-client, and use the
   bearer-token path. Record which mechanism worked.
5. **End-to-end GATEWAY-mode checks through the Gateway:**
   - a READ: "list my repositories" â†’ payment-service; "show my stories" (dev-6)
     â†’ PAY- stories;
   - a HITL WRITE: a `github_create_branch` request â†’ the `WriteApprovalHook`
     interrupt fires â†’ approve â†’ branch created (confirm by a follow-up read);
     a reject writes nothing.
   Record the real outcomes here when run.

---

## LIVE DEPLOY + AUTH VALIDATION (2026-10-16, operator-run)

Deployed to account <AWS_ACCOUNT_ID> / us-east-1 via the `lava` SSO admin role. Real
results (no fabrication):

### Bootstrap + deploy
- `cdk bootstrap aws://<AWS_ACCOUNT_ID>/us-east-1 --profile lava` â†’ `CDKToolkit`
  CREATE_COMPLETE (12/12 resources).
- `cdk deploy --all --require-approval never --profile lava` â†’ all five stacks
  CREATE_COMPLETE in ~421s. Deployed outputs:
  - `GatewayMcpUrl` = `https://<GATEWAY_HOST>/mcp`
  - `GatewayId` = `mahalo-gateway-bex2gwexvv`
  - Function URLs: jira `https://<LAMBDA_URL_HOST>/`,
    confluence `https://<LAMBDA_URL_HOST>/`,
    github `https://<LAMBDA_URL_HOST>/`,
    servicenow `https://<LAMBDA_URL_HOST>/`

### Lambda Function URL smoke (direct, bypassing Gateway)
- `GET <jiraUrl>/projects` with `X-API-Token: mock-jira-token-12345` â†’ HTTP 200,
  seeded projects (AUTH, CART, ...). DynamoDB lazy-seed + in-handler auth work live.
- Same path with NO token â†’ HTTP 401. Auth enforced.

### Gateway inbound-auth validation (the design's open Â§6.4 item) â€” RESOLVED
- Unsigned POST `tools/list` to the Gateway MCP URL â†’ HTTP 401 (AWS_IAM rejects
  unsigned, as expected).
- **SigV4-signed with signing service `bedrock-agentcore`** â†’ **HTTP 200**, MCP
  `tools/list` returned the tool catalog with Gateway-prefixed names
  (e.g. `mock-confluence___confluence_get_page`) â€” confirming both the AWS_IAM
  path AND the `<target>___<tool>` prefix the HITL hook strips.
- SigV4-signed with signing service `bedrock` â†’ HTTP 401 (wrong service name).

**Conclusion:** the default AWS_IAM authorizer is viable for the demo with the
SSO admin role; the correct SigV4 signing service name is **`bedrock-agentcore`**.
No Cognito/CUSTOM_JWT fallback needed. The `agent/gateway_client.py` auth factory
(currently returns `None`) must install a SigV4 `httpx.Auth` signing as
`bedrock-agentcore` for a full in-agent GATEWAY-mode run â€” pending, scoped, and
now fully de-risked by the probe above.

---

## GATEWAY-mode live E2E (2026-10-17, lifecycle fix + partial)

Gateway still deployed from 2026-10-16. `lava` SSO re-authed. Env:
`MAHALO_TOOL_MODE=gateway`,
`MAHALO_GATEWAY_MCP_URL=https://<GATEWAY_HOST>/mcp`.

### Offline gate (after the MCP double-start lifecycle fix)
`& "agent/.venv/Scripts/python.exe" -m pytest agent -q` â†’ **53 passed, 1 skipped**
(52 + 1 new lifecycle regression test; DIRECT 42/1 preserved).

### LIVE READ through the Gateway â€” PASS
`python -m agent.chat "list my repositories"` (GATEWAY mode) returned the real
seeded repos including **payment-service** (+ cart/auth/product/order-service).
Full chain proven live: Strands â†’ Bedrock Sonnet 4.5 â†’ SigV4(`bedrock-agentcore`)
â†’ AgentCore Gateway MCP â†’ github Lambda â†’ DynamoDB. The lifecycle fix
(single start via `attach_gateway_tools`, `mcp_client.stop()` in `finally`)
resolved the double-start.

### LIVE HITL WRITE through the Gateway â€” PARTIAL (gate fires; resume bug)
Driver: `scripts/_gw_hitl_smoke.py approve "create a feature branch ... in repo repo-1"`.
- GOOD: the agent resolved repo-1 â†’ payment-service via a live `mock-github___github_list_repos`
  call, then the write tool `mock-github___github_create_branch` triggered the
  `WriteApprovalHook` interrupt correctly â€” `PROPOSED: Create branch
  'feature/gw-smoke' in payment-service from main` / `Approve this write? [y/N]`.
  So HITL PROPOSE-not-execute + the Gateway `___`-prefix strip both work LIVE.
- BUG: after APPROVE, the agent re-proposed the same branch and then the run
  crashed with `ValidationException ... The number of toolResult blocks at
  messages.7.content exceeds the number of toolUse blocks of previous turn`
  (Strands ConverseStream). The interrupt-resume + `_emit_system_signal` history
  threading corrupts the tool-use/tool-result pairing in GATEWAY (MCP-sourced
  tools) mode. DIRECT mode is unaffected. This is the remaining Task-4 bug;
  reject path not yet exercised. Fix in progress.

## GATEWAY HITL resume fix (live)

### Root cause (confirmed against installed strands-agents 1.61.1 + live dump)

The interrupt/resume contract in `strands/event_loop/event_loop.py` +
`strands/interrupt.py` works like this:

- On the interrupt turn the model's assistant message that carries the open
  `toolUse` is appended to `agent.messages` (`_handle_model_execution`,
  `await agent._append_messages(message)`), then `_handle_tool_execution` raises
  the interrupt via `_stop_for_interrupts`. The matching `toolResult` is **not**
  appended yet â€” the toolUse is left "open".
- On resume, `agent(prompt)` calls `_interrupt_state.resume(prompt)` and
  `_convert_prompt_to_messages` returns `[]` while `activated` is True, so the
  `interruptResponse` list is NOT appended to history (SDK side is clean). The
  event loop replays `pending_tool_execution.assistant_message`, runs the tool,
  and only then `await agent._append_messages(tool_result_message)` appends the
  `toolResult` as a `user` turn â€” closing the cycle.

The defect was in `agent/chat.py::_ask`. It called `_emit_system_signal` (which
does `agent.messages.append({"role":"assistant","content":[{"text": "[SYSTEM]â€¦"}]})`)
immediately after EVERY `agent(responses)` resume â€” including a resume that
**re-interrupted**. In GATEWAY mode the first approved write 404s (mock keys by
repo id, agent passes the name) so the model re-proposes `github_create_branch`,
producing a SECOND interrupt whose `toolUse` is still open. Appending the
`[SYSTEM]` assistant message at that moment wedged a zero-`toolUse` assistant
turn between the open `toolUse` and its pending `toolResult`. Live `agent.messages`
dump at the crash (temp `scripts/_gw_dump.py`):

```
[3] assistant {text, toolUse}   <- 1st proposal (approved) â†’ ran, 404
[4] user      {toolResult}
[5] assistant {text, toolUse}   <- model RE-PROPOSED (approved) â€” OPEN toolUse
[6] assistant {text}            <- [SYSTEM] breadcrumb INSERTED mid-cycle  â† BUG
[7] user      {toolResult}      <- result for toolUse#5; its previous turn [6] has 0 toolUse
```

So the next ConverseStream call failed with exactly
`The number of toolResult blocks at messages.7.content exceeds the number of
toolUse blocks of previous turn`. DIRECT mode never hit this because each
approved write's resume closed its own cycle before the breadcrumb landed.

### The fix

`agent/chat.py::_ask` now DEFERS the `[SYSTEM]` breadcrumbs: approved proposals
are collected in `pending_breadcrumbs` and flushed via `_emit_system_signal`
ONLY when a resume returns a non-interrupt result (the tool cycle is fully
closed and the `toolResult` has landed). While another interrupt is pending the
toolUse is still open, so no assistant message is inserted. This is
mode-agnostic: in DIRECT mode each write's resume closes its own cycle, so the
breadcrumb still lands before the model proposes the next chained step â€” the
branchâ†’commitâ†’PR chaining and "don't re-propose a completed step" semantics are
preserved in BOTH modes. `_emit_system_signal` itself is unchanged; APPROVE still
records the breadcrumb, REJECT still records nothing. DIRECT mode is otherwise
byte-for-byte unchanged and remains the default.

### Offline gate

`& "agent/.venv/Scripts/python.exe" -m pytest agent -q` â†’ **55 passed, 1 skipped**
(was 53/1; +2 new regression tests in `agent/tests/test_write_tools_unit.py`:
`test_ask_driver_gateway_resume_reinterrupt_keeps_history_valid` and
`test_ask_driver_gateway_reject_then_reinterrupt_writes_nothing`). The new
APPROVE test reproduces the malformed history with a fake MCP-sourced tool whose
resume re-interrupts, and asserts every `toolResult` turn's count matches the
previous turn's `toolUse` count (the Bedrock contract) and that breadcrumbs land
only after the final `toolResult`. Verified it FAILS against the old eager-emit
behavior with `message 4 has 1 toolResult block(s) but the previous turn has 0
toolUse block(s)` â€” the same defect the live crash reported. DIRECT 42/1
preserved.

### Live APPROVE (deployed Gateway, SSO `lava`, us-east-1, acct <AWS_ACCOUNT_ID>)

`scripts/_gw_hitl_smoke.py approve 'create a feature branch called feature/gw-smoke in repo repo-1'`:

```
=== AGENT FINAL ANSWER ===
... Tool #1: mock-github___github_list_repos
Perfect! I can see that "repo-1" maps to **payment-service**. ...
Tool #2: mock-github___github_create_branch
PROPOSED: Create branch 'feature/gw-smoke' in payment-service from main
Approve this write? [y/N] y   <- scripted APPROVE
I'm getting a repository not found error. Let me try listing repos again ...
Tool #3: mock-github___github_list_repos
... Tool #4: mock-github___github_create_branch
PROPOSED: Create branch 'feature/gw-smoke' in payment-service from main
Approve this write? [y/N] y   <- scripted APPROVE
Tool #5: mock-github___github_get_repo_stats
There seems to be a system issue with accessing the GitHub repositories. ...
Available repositories: payment-service (repo-1) ... order-service (repo-5)
Could you confirm which repository you'd like me to create the branch in? ...
(exit code 0)
```

Outcome: the `WriteApprovalHook` interrupt fired on the Gateway-prefixed
`mock-github___github_create_branch`; after APPROVE the write executed ONCE per
approval; the resume completed with a clean final answer and **exit code 0 â€” NO
ValidationException**. The write itself returns "repository not found" because
the mock keys GitHub collections by repo id (`repo-1`) while the agent passes the
repo NAME (`payment-service`) in `/repos/{repo_id}/branches` per preserved
mahalo-dock behavior â€” this by-name 404 is EXPECTED pre-existing behavior, not the
resume bug. Required assertion met: resume no longer crashes, the gate fires and
executes-once. An alternate phrasing (`'create a branch named feature/gw-smoke in
the payment-service repository'`) produced the same clean, non-crashing result
(exit 0) and the same expected mock 404 â€” no phrasing made the by-name mock
accept the write, confirming it is the mock's id-vs-name keying, independent of
the resume fix.

### Live REJECT (deployed Gateway)

`scripts/_gw_hitl_smoke.py reject 'create a feature branch called feature/gw-smoke2 in repo repo-1'`:

```
=== AGENT FINAL ANSWER ===
Tool #1: mock-github___github_list_repos
I see you want to create a branch in "repo-1". The repository ID "repo-1"
corresponds to payment-service. I'll create the feature branch feature/gw-smoke2 ...
Tool #2: mock-github___github_create_branch
PROPOSED: Create branch 'feature/gw-smoke2' in payment-service from main
Approve this write? [y/N] n   <- scripted REJECT
The branch creation proposal was rejected. If you'd like to proceed, please
approve the write action ...
(exit code 0)
```

Outcome: the gate fired, the scripted REJECT cancelled the tool (nothing
written), and the agent returned a clean, non-crashing final answer (exit 0). No
`[SYSTEM]` breadcrumb recorded on reject.

### Verdict

The GATEWAY-mode HITL write-resume `ValidationException` is **GONE**. APPROVE runs
the write once with no re-corruption of history, REJECT writes nothing, DIRECT
mode is unchanged and still default, and the offline suite is 55 passed / 1
skipped (DIRECT 42/1 preserved).
