# Phased Plan

The rewrite proceeds in incremental tasks. Each task leaves the project in a working,
demonstrable state before the next begins.

## Task 0 - Verification and skeleton (DONE)

Verify the toolchain and AWS/AgentCore capabilities, then scaffold the repository: directory
structure, `.gitignore`, `README.md`, architecture and plan docs, and a read-only AgentCore
capability-check script. Initialize git and push the skeleton to the remote.

## Task 1 - Strands agent (local) vs existing mocks (CODE-COMPLETE)

Build the first version of the Strands agent running locally, wired to the existing mock
systems so we can exercise end-to-end reasoning before any AWS hosting is introduced.

Progress: implemented under `agent/` — env-driven config, a Bedrock-backed Strands agent
(Claude Sonnet 4.5, 300s read timeout, `lava` profile), ported prompts, 19 read-only tools
over Jira/Confluence/GitHub/ServiceNow, a `python -m agent.chat` CLI/REPL (dev-6 identity),
and unit + live-integration tests. Zero LangChain. Offline verification recorded in
`docs/.agents/tasks/task1-verification.md` (unit 13/13 pass; full suite passes with the live
integration test skipping while the tunnel is down; agent builds without creds). The live
REPL/Bedrock/tunnel run remains for the user. Write/propose/approve is deferred to Task 2.

## Task 2 - Propose/approve in Strands

Implement the propose/approve interaction pattern inside the Strands agent so changes are
surfaced for approval before any action is taken.

## Task 3 - Mocks as Lambdas

Reimplement the four mock systems (Jira, Confluence, GitHub, ServiceNow) as AWS Lambdas,
keeping their behavior equivalent to the local mocks.

## Task 4 - Gateway MCP (OFFLINE-COMPLETE; live deploy deferred)

Place the Lambdas behind AgentCore Gateway and expose them as MCP tools the agent can call.

Progress: implemented as `infra-cdk/mahalo_infra/gateway_stack.py`
(`MahaloGatewayStack`: one `CfnGateway` MCP + four `CfnGatewayTarget`s with inline
toolSchema + a least-privilege Gateway IAM role + per-Lambda invoke permission;
`authorizerType` CfnParameter default `AWS_IAM`). Scope refinement during the
task: a single `tools-lambdas/common/tool_schemas.py` (25-tool source of truth)
feeds BOTH the CDK toolSchema and a new in-Lambda `gateway_adapter.py` (synthetic
Function-URL request through the frozen router), so the model's schema and the
wire call cannot drift; three server-side composites reproduce the agent-only
orchestration; the agent gets a dual-mode toggle (`MAHALO_TOOL_MODE`, default
`direct` — DIRECT HTTP stays the baseline) with a `build_agent(tool_mode=...)`
branch returning `(agent, mcp_client)`; and HITL is preserved under Gateway's
`target___tool` rename so the six writes stay gated. Zero LangChain. Offline gate
GREEN (`docs/.agents/tasks/task4-verification.md`): `cdk synth --all` exit 0
(gateway = 1 Gateway + 4 Targets), infra-cdk 26 pass, tools-lambdas 94 pass,
agent 52 pass / 1 skip (DIRECT 42/1 preserved), gateway-mode `build_agent`
constructs offline. Code reviewed and APPROVED
(`docs/.agents/tasks/task4-code-review.json`). The live deploy (four Lambdas +
Gateway + targets + inbound auth) and the end-to-end READ / HITL-WRITE through
the Gateway are DEFERRED operator steps.

## Task 5 - Memory and Identity (OFFLINE-COMPLETE; live deploy deferred)

Add AgentCore Memory for session state and AgentCore Identity for tool credentials.

Progress: implemented as two **opt-in / additive** capabilities — with the
toggles off, DIRECT and GATEWAY behave byte-for-byte as before. Scope
refinement during the task: Memory is wired through the native Strands
`session_manager=` seam (`AgentCoreMemorySessionManager`) and scoped to
**short-term conversation memory only** (bare `CfnMemory`, no long-term
strategies; a `with_long_term` seam is left off by default), replacing
mahalo-dock's in-memory `_sessions` with a durable session-id-keyed store. Since
the installed `bedrock-agentcore 1.24.1` manager `__init__` performs a live
`ListEvents` read, the offline-safe construction was relocated: `build_agent`
builds only a plain-data `MemorySessionSpec`, and the live manager is constructed
inside a new `attach_memory` helper (the single AWS touch) — the
"construct-not-started" pattern from Task 4. Identity is scoped to the **smallest
real slice**: provision a `CfnWorkloadIdentity` + one `CfnApiKeyCredentialProvider`
and wire **one** representative outbound path (`jira_create_story`, DIRECT mode)
to fetch its key at call time behind `MAHALO_IDENTITY_ENABLED` (per-service
brokering and the Runtime Workload-Access-Token path deferred to Task 6; Task-4
inbound auth untouched). `build_agent` now returns a `BuildResult(agent,
mcp_client, session_manager)` dataclass instead of a variable-arity tuple; six
new off-by-default settings; `agent/chat.py` gains argparse `--session-id`. New
`infra-cdk/mahalo_infra/memory_identity_stack.py` (`MahaloMemoryIdentityStack`,
wired in `app.py`). Zero LangChain. Offline gate GREEN
(`docs/.agents/tasks/task5-verification.md`): `pytest agent -q` = 69 pass / 1 skip
(55 baseline + 14 new; DIRECT path 49/1 preserving the Task-2 42/1, Task-4
GATEWAY/HITL 6/6), `build_agent(memory=True, identity=True)` and
`build_agent(tool_mode='gateway', memory=True)` construct offline with no creds,
`cdk synth --all` exit 0 (six templates), infra-cdk 31 pass, tools-lambdas 94
pass. Code reviewed and APPROVED
(`docs/.agents/tasks/task5-code-review.json`). The live deploy of
`MahaloMemoryIdentityStack`, the two-invocation persist/reload-history check via
AgentCore Memory, and the Identity-brokered credential exercise are DEFERRED
operator steps.

## Task 6 - Runtime hosting (OFFLINE-COMPLETE; live deploy deferred)

Host the Strands agent on AgentCore Runtime and route traffic to it through the thin API.

Progress: implemented and offline-verified. The agent `build_agent` seam is
hosted UNCHANGED on **Amazon Bedrock AgentCore Runtime** via a thin harness
(`agent/runtime_app.py`: `BedrockAgentCoreApp` + a single `@app.entrypoint invoke`
that reuses `build_agent -> attach_gateway_tools -> attach_memory` through
`agent/runtime_session.build_and_attach` — no second agent, no duplication).
Traffic flows through a thin, stateless FastAPI forwarder (`api/`, Mangum on a
Function-URL Lambda) that speaks a small `{action, prompt/decision, interrupt_id,
...}` request / `{response, proposal?, session_id, status, error?}` response
contract and imports **zero `agent`/LangChain** code. IaC adds two stacks
(`infra-cdk/mahalo_infra/runtime_stack.py` `MahaloRuntimeStack`,
`api_stack.py` `MahaloApiStack`, wired in `app.py`).

Scope refinements during the task:
- **Provisioning via the CDK L2 `aws_bedrockagentcore.Runtime`** construct suite
  (`Runtime` + `AgentRuntimeArtifact` + `add_endpoint`), not boto3/starter-toolkit
  — the L2 was discovered in the installed CDK during design review and auto-
  creates the execution role (app-level Bedrock/Memory/Gateway grants added on
  top). Docker branches (image build + Lambda dep bundling) are flag-gated
  (`-c buildImage=1` / `MAHALO_BUILD_IMAGE=1`) so `cdk synth` stays Docker-free.
- **Per-request sessions** arrive on the runtime session-id header (surfaced as
  `context.session_id`, never in the body) and are wired straight into Task-5
  Memory via `build_agent(memory=True, session_id=...)`.
- **HITL** is a two-call propose->approve protocol at the Runtime boundary; the
  `[SYSTEM]` chain breadcrumb is derived from the Runtime's own restored interrupt
  state, so chain correctness does NOT depend on the client echoing the proposal.
- **Identity Runtime path landed but descoped from the AWS_IAM MVP live gate**:
  the Workload-Access-Token plumbing (`MAHALO_IDENTITY_ENABLED` env, per-user
  `grant_invoke_runtime_for_user`, `runtimeUserId` forwarding) is in place and
  flip-enabled; off by default under SigV4 inbound auth.
- Inbound auth is **AWS_IAM/SigV4** (the L2 default); a Cognito branch stub is left
  for the dev-mode upgrade.

Zero LangChain. Offline gate GREEN (`docs/.agents/tasks/task6-verification.md`):
`pytest agent -q` = 99 pass / 1 skip (69/1 baseline + 30 Task-6; DIRECT 42/1 and
Task-4 GATEWAY / Task-5 Memory-Identity preserved), thin-API `pytest api -q` = 15
pass, `pytest tools-lambdas/tests -q` = 94 pass, infra-cdk `pytest tests -q` = 42
pass / 1 skip (the Docker from_asset branch is operator-only), `cdk synth --all`
exit 0 (EIGHT templates incl. `MahaloRuntimeStack` + `MahaloApiStack`), Runtime
entrypoint + thin API import/construct offline with no creds. Code reviewed and
APPROVED (`docs/.agents/tasks/task6-code-review.json`, 0 blocking). The live
deploy (container build/push + `cdk deploy --all`), the end-to-end READ, the HITL
WRITE via the two-call approve protocol, and the cross-invocation Memory
persistence check are DEFERRED operator steps documented in
`docs/.agents/tasks/task6-verification.md` and `task6-deploy-runbook.md`.

## Task 7 - Gitea and frontend hosting

Stand up self-hosted Gitea on an always-on host and deploy the Next.js frontend.

## Task 8 - Re-deployable CDK and teardown

Harden the AWS CDK (Python) stacks so the environment can be deployed and torn down cleanly
and repeatably.

## Task 9 - Docs

Finalize documentation covering architecture, operations, and demo walkthrough.
