# Task 6 — Runtime hosting: deferred operator deploy runbook

This runbook is **operator-run and billable**. The automated gate is OFFLINE
(`cdk synth` + unit tests, no network, no AWS creds); nothing here auto-deploys.
It captures design §E.5, the §C.5 HITL live gate, the two-invocation Memory
persist/reload check, the Identity descope + enablement flip, the invocation-budget
open item, and teardown. Run it manually when a live Runtime demo is needed.

> HARD RULE: this stays under `mahalo-agentcore`; never touch `mahalo-dock`.

## Prerequisites

- Docker must be available (the Runtime image build + the thin-API Lambda
  dependency bundling both run Docker on the deploy branch).
- `aws sso login --profile lava`; confirm with
  `aws sts get-caller-identity --profile lava`.
- The build flag turns ON the Docker branches:
  `$env:MAHALO_BUILD_IMAGE = "1"` (PowerShell), or `-c buildImage=1`.

## Deploy order (direct construct refs — CDK auto-orders)

1. Memory/Identity + Gateway + mocks first so their outputs exist:
   ```powershell
   cd infra-cdk
   $env:MAHALO_BUILD_IMAGE = "1"
   cdk deploy MahaloMemoryIdentityStack MahaloGatewayStack `
     MahaloMockJiraStack MahaloMockConfluenceStack `
     MahaloMockGithubStack MahaloMockServicenowStack --profile lava
   ```
   Note `MemoryId` and `GatewayMcpUrl`.
2. Runtime — builds + pushes the ARM64 image (`agent/Dockerfile`), the L2
   auto-creates the execution role (with the app-level Bedrock/Memory/Gateway
   grants added on top), and `Runtime` + `add_endpoint("default")` create the
   runtime + endpoint:
   ```powershell
   cdk deploy MahaloRuntimeStack --profile lava
   ```
   Note the `RuntimeArn` output.
3. Thin API — Function-URL Lambda wired to the Runtime ARN, deps bundled into the
   asset via `BundlingOptions`:
   ```powershell
   cdk deploy MahaloApiStack --profile lava
   ```
   Note the `RuntimeApiUrl` output.

The Function URL uses `AuthType=AWS_IAM`, so hit it with SigV4-signed requests
(the demo/frontend signs; matches the Task-4 inbound decision and the user's
"keep AWS_IAM for now").

## §C.5 HITL live gate (billable, operator-run)

Through the deployed thin API (SigV4-signed):

1. `POST /chat {message:"create a feature branch for PAY-109"}` → expect
   `status=pending_approval` with a `proposal` and **no** write performed.
2. `POST /chat/approve {session_id:S, interrupt_id:<id>, approved:true}` → expect
   exactly one write and **no `ValidationException`**. This is the test that the
   `filter_restored_tool_context=False` pending-write build composes cleanly
   across a cold rebuild. If it raises a `ValidationException`
   (toolResult/toolUse mismatch), that is the trigger to apply the design §C.4
   fallback (Option C — explicit `pending_action` proposal), NOT a surprise.
3. On a fresh proposal, `POST /chat/approve approved=false` → expect nothing
   written.
4. Branch → commit → PR chain across three approves → expect no step re-proposed
   (the `[SYSTEM]` breadcrumb is persisted to Memory and seen on the next turn).

## Two-invocation Memory persist/reload check

Same session id across two `POST /chat` calls:
1. `POST /chat {message:"remember my favorite repo is payment-service", session_id:S}`.
2. `POST /chat {message:"what's my favorite repo?", session_id:S}` → the answer
   should reflect the reloaded history (AgentCore Memory STM, `batch_size=1`).

## Identity — DESCOPED from the AWS_IAM MVP

The Identity-brokered `jira_create_story` write is **NOT** part of this gate. Under
SigV4 inbound auth the installed SDK raises `ValueError` in the container unless
the caller supplies a `runtimeUserId`, so the MVP runs with
`MAHALO_IDENTITY_ENABLED=false`. `jira_create_story` still works in the demo via
its static env-configured key (Task-1/2 behavior); it just is not *brokered*.

Enablement (a later config flip, not a redesign):
- Flip `MAHALO_IDENTITY_ENABLED=true` on the Runtime env.
- The thin API then forwards `runtimeUserId=ident.developer_id` to
  `invoke_agent_runtime`.
- Grant the Runtime execution role the AgentCore Identity data-plane actions
  (grounded to installed source): `bedrock-agentcore:GetResourceApiKey` and
  `bedrock-agentcore:GetWorkloadAccessTokenForUserId`, scoped to the
  `mahalo-jira-apikey` provider and the `mahalo-agent` workload identity.
- Grant the thin-API Lambda role **both** `bedrock-agentcore:InvokeAgentRuntime`
  and `bedrock-agentcore:InvokeAgentRuntimeForUser` on the Runtime ARN
  (`MahaloApiStack(identity_enabled=True)` wires the per-user grant via
  `runtime.grant_invoke_runtime_for_user`). There is no separate
  `InvokeAgentRuntimeForUser` *API operation* — the per-user invoke is the same
  `InvokeAgentRuntime` call with the `runtimeUserId` header set — but
  `InvokeAgentRuntimeForUser` is a distinct IAM *action* the caller must hold.

Proven only once this path is enabled (either `runtimeUserId` end-to-end under
SigV4, or Cognito/OAuth inbound auth lands).

## OPEN VERIFICATION ITEM — synchronous invocation budget (measure, do not assume)

The installed source documents only the session *idle* timeout
(`idle_runtime_session_timeout`, default 900s) and instance *lifetime*
(`max_lifetime`, default 28800s) — NOT a per-invocation request budget. No number
for a synchronous `InvokeAgentRuntime` timeout is asserted. On first deploy:
**measure** the observed end-to-end time of a representative code-gen
`github_commit_files` invocation and whether the platform severs a long
synchronous call; cross-check the published synchronous invocation timeout in the
AgentCore Runtime limits/quotas doc. If a representative commit is at risk, switch
the entrypoint to the SSE/streaming path (design §A.2, Out of Scope for the MVP)
before the demo. The 300s Bedrock `read_timeout` from `settings.bedrock_read_timeout`
is preserved; `idle_runtime_session_timeout` is set to 15 min so a warm session
survives the approve round-trip.

## Teardown (stop spend)

```powershell
cd infra-cdk
cdk destroy MahaloApiStack MahaloRuntimeStack `
  MahaloMemoryIdentityStack MahaloGatewayStack `
  MahaloMockJiraStack MahaloMockConfluenceStack `
  MahaloMockGithubStack MahaloMockServicenowStack --profile lava
```
