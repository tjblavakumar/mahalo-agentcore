# CONTINUATION — read this first (fresh-session handoff)

This file lets a new chat session (opened with `mahalo-agentcore` as the workspace
root) continue the AgentCore rewrite with zero prior context. Read it top to
bottom before doing anything.

> For a one-page "where are we / what's left" snapshot, read `docs/STATUS.md`
> first. As of 2026-10-18: Tasks 0-6 DONE (6 is OFFLINE-COMPLETE + code-review
> APPROVED, committed+pushed as `172890c`); live deploy is a deferred operator
> step; nothing of ours is deployed; **Task 7 (Gitea + frontend hosting) is
> IN PROGRESS — design phase, not yet implemented.** This CONTINUATION file has
> the full operational detail.

> ⏸️ RESUME TOMORROW — Task 7 in-flight (workflow `wf_15b843019e9d877e`, PAUSED):
> Task 7 (port the mahalo-dock Next.js frontend to the Task-6 thin API + stand up
> self-hosted Gitea) is mid-DESIGN. The design went 5 iterations and is one PROSE
> fix from APPROVED — the last confirming review hadn't run when we paused. Git is
> clean at `172890c` (Task 6); Task 7 has produced ONLY doc artifacts so far
> (`docs/.agents/tasks/task7-investigation.md`, `task7-design.md`,
> `task7-design-review.{md,json}`) and NO code — nothing to commit yet.
>
> The design is SOUND and verified against source; the hard problems are resolved:
> (A) chat-surface-only frontend port with the two-call `/chat` + `/chat/approve`
> HITL (interrupt_id already on the wire — no backend change); (B) browser auth via
> a Cognito UNAUTHENTICATED Identity Pool -> temp IAM creds -> in-browser SigV4
> (aws4fetch) direct to the Function URL at the AWS_IAM edge; (C) Gitea on EC2+EBS
> (SQLite), additive behind `GITHUB_MODE=real` (mock path stays default, 94
> lambda tests green); (D) frontend as S3+CloudFront static export (dropped
> `next/font/google` so the offline `npm build` needs no network), `NEXT_PUBLIC_API_URL`
> from the `RuntimeApiUrl` CfnOutput via a two-phase operator build; (E) two new
> offline-synthing CDK stacks (`MahaloGiteaStack` + `MahaloFrontendStack`, 8->10
> templates, asset builds flag-gated). The ONLY open item is review Finding 1
> (MEDIUM, prose-only): §D.2/§E.1 mis-state WHY `frontend_stack` takes `api_stack`
> — fix the sentence to say it reads `api_stack.function.function_arn` for the
> unauthenticated Cognito role's `lambda:InvokeFunctionUrl` policy, and that
> `NEXT_PUBLIC_API_URL`/CORS are operator steps, not done by the stack.
>
> TO RESUME: inspect `wf_15b843019e9d877e`. If it settled paused mid-design, either
> resume it (it should finish the fix -> confirming review -> APPROVED -> plan ->
> build-loop -> verify), or if it's in a bad state, relaunch Task 7 from a
> `run_workflow` prompt noting the design is already near-APPROVED (reuse the
> existing `task7-design.md`, apply only Finding 1, then proceed to build). After
> implementation: offline gate = frontend `npm ci && npm run build` + lint +
> vitest `--run`, plus Python gates green (agent 99/1 clean-env with NO `MAHALO_*`
> env vars, api 15, tools-lambdas 94, infra-cdk synth+tests), zero LangChain.
> Then COMMIT+PUSH Task 7, and the PLAN is: do the full end-to-end LIVE deploy +
> validation (frontend -> thin API -> Runtime -> Gateway -> Lambdas, incl. the
> two-call HITL in the browser) WITH the user, since the frontend is now in place.

> HARD RULE: Only create or modify files UNDER
> `D:\<USER>\LavaCode\AI\mahalo-agentcore`. NEVER write to
> `D:\<USER>\LavaCode\AI\mahalo-dock` — that is the original, working
> project kept as a fallback demo. You MAY read from mahalo-dock to copy reusable
> assets, but never edit it. (If your workspace root is mahalo-agentcore, that
> protection is mostly automatic.)

---

## What this project is

A ground-up rewrite of "mahalo-dock" (a multi-persona SDLC chat assistant over
four mock enterprise systems: Jira, Confluence, GitHub/Gitea, ServiceNow) to use
the **Amazon Bedrock AgentCore** stack + **Strands Agents SDK** instead of the
old hand-rolled LangChain/LangGraph agent loop.

Target architecture (see docs/ARCHITECTURE.md):
- Strands Agents SDK = the reasoning/tool loop (replaces LangChain).
- AgentCore Runtime = hosts the agent (managed, in AWS).
- AgentCore Gateway = exposes the 4 mock systems (as Lambdas) as MCP tools.
- AgentCore Memory = sessions + conversation history (replaces in-memory session.py).
- AgentCore Identity = brokers tool credentials.
- Self-hosted Gitea = real branch/commit/PR backend (kept, always-on host).
- Next.js frontend = reused from mahalo-dock.
- AWS CDK (Python) = IaC for everything (must survive a monthly account reset).

Full phased plan: docs/PLAN.md. This file covers operational details that plan
doesn't.

## Status

- Task 0 DONE: skeleton, docs, scripts/verify-agentcore.ps1, git repo. First
  commit pushed to https://github.com/tjblavakumar/mahalo-agentcore (branch main).
- Task 1 DONE (local Strands agent, read-only): package under `agent/`
  with env-driven config, a Bedrock-backed Strands agent (Claude Sonnet 4.5,
  read_timeout=300s, creds from the `lava` profile), ported system prompts, 19
  read tools over the four mocks (7 Jira / 4 GitHub / 3 Confluence / 5
  ServiceNow), a `python -m agent.chat` CLI/REPL (dev-6 "Lava Dev" identity), and
  tests. Zero LangChain imports. Offline verification recorded in
  `docs/.agents/tasks/task1-verification.md`: unit suite 13/13 pass, full suite
  13 pass + 1 integration test SKIPS (tunnel down), import/`build_agent()` succeed
  without creds. Strands 1.61.1 API confirmed against the installed source.
  Code reviewed and APPROVED (docs/.agents/tasks/task1-review.md).
  Committed AND PUSHED to origin/main (commit 727ba7b).
  - LIVE VERIFICATION PASSED (2026-10-15, with tunnel + `lava` SSO up): routed
    through Strands -> Bedrock Sonnet 4.5 -> live EC2 mocks with zero LangChain.
    `python -m agent.chat "list my repositories"` -> payment-service (via
    github_list_repos); `python -m agent.chat "show PAY-109"` -> full story with
    assignee resolved to "Lava Dev (you)" = dev-6. End-to-end path confirmed.
- Task 2 DONE (write tools + HITL approval gate): added six WRITE `@tool`
  functions (jira_create_story, jira_update_story, github_create_branch,
  github_commit_files, github_open_pull_request, servicenow_create_incident)
  plus a `WriteApprovalHook` (Strands `BeforeToolCallEvent` interrupt) and the
  `chat.py` propose/approve/reject driver, wired in `strands_agent.build_agent()`
  (`tools=[*READ_TOOLS(19), *WRITE_TOOLS(6)]`, `hooks=[WriteApprovalHook()]`).
  Preserves propose-don't-execute (no HTTP on propose), "branch already exists =
  success" resilience, and branch->commit->PR chaining via `[SYSTEM]` breadcrumbs.
  `agent/prompts.py` and the Task 1 read modules are untouched; zero LangChain.
  Offline-verified (`docs/.agents/tasks/task2-verification.md`): full suite
  `pytest agent -q` = 42 passed, 1 skipped (the ONE live integration test SKIPS
  because the tunnel/mocks on ports 5001-5004 are down — not fabricated),
  `build_agent()` constructs 25 tools with no network/creds, no LangChain.
  Code reviewed and APPROVED (`docs/.agents/tasks/task2-code-review.json`,
  verdict APPROVED). Committed AND PUSHED to origin/main (commit cce2158).
  LIVE VERIFICATION PASSED (2026-10-16, tunnel 5001-5004 + `lava` SSO up) via
  `pwsh ./scripts/verify-task2-live.ps1`: live integration test ran green,
  create-story propose->approve wrote (reject wrote nothing), and the
  branch->commit->PR chain approved step-by-step with `[SYSTEM]` breadcrumbs
  preventing re-proposals. Recorded in `docs/.agents/tasks/task2-verification.md`.
- Task 3 DONE (four mocks reimplemented as AWS Lambdas): the Jira, Confluence,
  GitHub, and ServiceNow mocks are re-implemented under `tools-lambdas/` as four
  Function-URL Lambdas (Python 3.13) backed by DynamoDB, behavior-equivalent to
  the mahalo-dock mocks (seed data copied verbatim; mahalo-dock untouched). A
  shared `common/` provides the router, auth (`X-API-Token`), and store. IaC
  added under `infra-cdk/` as four `MockServiceStack`s. Offline-verified
  (`docs/.agents/tasks/task3-verification.md`): `pytest tools-lambdas/tests -q`
  = 68 passed (moto-backed, offline); `cdk synth` produced all four stack
  templates; `infra-cdk` assertion suite = 20 passed. Code reviewed and APPROVED
  (`docs/.agents/tasks/task3-code-review.json`). Live AWS deploy + Function-URL
  integration check are DEFERRED operator actions.
- Task 4 DONE (AgentCore Gateway + MCP exposure, OFFLINE GATE GREEN): the four
  Task-3 Lambdas are placed behind one `MahaloGatewayStack` (`CfnGateway` MCP +
  four `CfnGatewayTarget`s with inline toolSchema + Gateway IAM role + per-Lambda
  invoke permission; `authorizerType` CfnParameter default `AWS_IAM`). A single
  `tools-lambdas/common/tool_schemas.py` (25-tool source of truth) feeds BOTH the
  CDK toolSchema and a new in-Lambda `gateway_adapter.py` that turns a flat
  Gateway invocation into a synthetic Function-URL request through the frozen
  router (DIRECT HTTP path untouched). Three server-side composites
  (`jira_search_stories`, `jira_get_stories_by_assignee`,
  `servicenow_deployment_status_by_project`) reproduce the agent-only
  orchestration. The agent gains a dual-mode toggle (`MAHALO_TOOL_MODE`, default
  `direct`); gateway mode builds an `MCPClient` (constructed, NOT started — stays
  offline-safe) and `build_agent` returns `(agent, mcp_client)`. HITL is
  preserved under Gateway's `target___tool` rename via `_bare_name` in
  `WriteApprovalHook`/`build_proposal`, so the six writes stay gated. Zero
  LangChain. Code reviewed and APPROVED
  (`docs/.agents/tasks/task4-code-review.json`, verdict APPROVED).
  Offline gate re-run and recorded in `docs/.agents/tasks/task4-verification.md`:
  `cdk synth --all` exit 0 (5 templates; gateway = 1 Gateway + 4 Targets);
  infra-cdk assertion suite **26 passed**; tools-lambdas suite **94 passed**;
  agent suite **52 passed, 1 skipped** (DIRECT Task-1/2 baseline 42/1 preserved);
  `build_agent(tool_mode='gateway')` constructs offline → `Agent MCPClient False`;
  zero LangChain. The `lava` SSO session was up but NO live probe was run (a
  meaningful probe needs a deployed Gateway endpoint = the deferred deploy); no
  live/deploy results fabricated. DEFERRED LIVE operator steps (deploy the four
  Lambdas; create the Gateway + four Lambda targets + inbound auth; point the
  agent at the Gateway MCP endpoint via `MAHALO_GATEWAY_MCP_URL`/
  `MAHALO_TOOL_MODE=gateway`; run an end-to-end READ and a HITL WRITE through the
  Gateway) are documented in `docs/.agents/tasks/task4-verification.md`.
  - LIVE DEPLOY DONE (2026-10-16, `lava` SSO up): `cdk bootstrap` +
    `cdk deploy --all --require-approval never --profile lava` → all five stacks
    CREATE_COMPLETE in account <AWS_ACCOUNT_ID> / us-east-1. **These resources are
    STILL DEPLOYED and incurring (small) cost.** Deployed outputs:
    - Gateway MCP URL: `https://mahalo-gateway-bex2gwexvv.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp`
      (GatewayId `mahalo-gateway-bex2gwexvv`).
    - Lambda Function URLs: jira `https://6jysjgpotsbtmps4reiphgm4y40qxfph.lambda-url.us-east-1.on.aws/`,
      confluence `https://xs4ceoejtdhjn255utn4uxhysy0mkgou.lambda-url.us-east-1.on.aws/`,
      github `https://hgfughfqvq5omyacdydghzrzom0zcmft.lambda-url.us-east-1.on.aws/`,
      servicenow `https://joz5k452zdqp6zpehiapftyc5m0mkwqu.lambda-url.us-east-1.on.aws/`.
    - Lambda smoke (direct, bypassing Gateway): `GET <jira>/projects` with the
      `X-API-Token` → HTTP 200 seeded data; no token → HTTP 401. Lambdas healthy.
    - INBOUND-AUTH RESOLVED: the default AWS_IAM authorizer ACCEPTS a SigV4-signed
      MCP request when the signing SERVICE NAME is **`bedrock-agentcore`** (HTTP
      200, returns the tool catalog with Gateway-prefixed names like
      `mock-confluence___confluence_get_page`); `bedrock` is rejected (401);
      unsigned is rejected (401). So AWS_IAM is viable for the demo — NO Cognito
      needed now (CUSTOM_JWT/Cognito still the documented dev-mode path).
    Recorded in `docs/.agents/tasks/task4-verification.md` ("LIVE DEPLOY + AUTH
    VALIDATION").

  - LIVE E2E FULLY PASSED (2026-10-17): the Task-4 live-finish is complete.
    Two live bugs were found by deploying and fixed in-session:
    1. MCP client DOUBLE-START — `with mcp_client:` + `attach_gateway_tools`
       (which calls `load_tools()` → starts again) raised
       `ToolProviderException: the client session is currently running`. Fixed:
       `attach_gateway_tools` is the SINGLE start; `chat.py` uses
       `try: attach...; finally: mcp_client.stop(None,None,None)` (no outer
       `with`). The offline test only asserted construct-not-started, so it
       missed this — deploying first surfaced it.
    2. HITL RESUME history corruption — `chat.py::_ask` emitted the `[SYSTEM]`
       breadcrumb via `agent.messages.append` after EVERY resume, including a
       resume that re-interrupted, wedging a zero-toolUse assistant message
       between an open toolUse and its pending toolResult → Bedrock
       `ValidationException: toolResult blocks ... exceeds toolUse blocks of
       previous turn`. Fixed: defer approved breadcrumbs, flush only when a
       resume returns a NON-interrupt result (tool cycle fully closed).
       Mode-agnostic; DIRECT unchanged & still default; branch→commit→PR
       chaining preserved both modes.
    Also implemented the SigV4 `httpx.Auth` provider (`agent/gateway_client.py`
    `SigV4Auth`, signing service `bedrock-agentcore`) as the default auth factory.
    Verified LIVE against the deployed Gateway: READ (`list my repositories` →
    payment-service et al.) routed Strands→Bedrock→SigV4→Gateway MCP→github
    Lambda→DynamoDB; HITL APPROVE (gate fires on `mock-github___github_create_branch`,
    write runs once, no ValidationException) and REJECT (nothing written, clean)
    both pass. The write's "repository not found" is the EXPECTED pre-existing
    mock repo-id-vs-name keying, NOT a bug. Offline gate: `pytest agent -q` =
    **55 passed, 1 skipped** (+2 resume regression tests; DIRECT 42/1 preserved).
    Full detail in `docs/.agents/tasks/task4-verification.md`
    ("GATEWAY-mode live E2E" + "GATEWAY HITL resume fix (live)").
    Live driver kept as `scripts/gw_hitl_smoke.py`. Committed + pushed to
    origin/main.
- Task 5 DONE (AgentCore Memory + Identity, OFFLINE GATE GREEN; code-review
  APPROVED): added two **opt-in / additive** capabilities that leave DIRECT and
  GATEWAY modes (and the full existing baseline) byte-for-byte unchanged when the
  toggles are off.
  - **Memory** plugs AgentCore Memory into Strands via the native
    `session_manager=` seam (`AgentCoreMemorySessionManager`), replacing
    mahalo-dock's in-memory `_sessions` dict with a durable session-id-keyed STM
    store. New module `agent/memory_client.py` assembles the config offline;
    `build_agent` only builds a plain-data `MemorySessionSpec` (the installed
    `bedrock-agentcore 1.24.1` manager `__init__` does a live `ListEvents`, so the
    live manager is constructed inside `attach_memory` — the single AWS touch,
    recorded as **Option 1**). `agent/chat.py` gains argparse `--session-id`
    (precedence `--session-id` > `MAHALO_SESSION_ID` > uuid4 when memory on).
  - **Identity** wires ONE representative outbound path (`jira_create_story`,
    DIRECT mode) to fetch its API key via AgentCore Identity at call time behind
    `MAHALO_IDENTITY_ENABLED`; `@requires_api_key` decorates a body-local `_inner`
    so no `IdentityClient`/boto3 is built at import. Task-4 inbound auth untouched.
  - `build_agent` now always returns a `BuildResult(agent, mcp_client,
    session_manager)` dataclass (no more variable-arity tuple); callers/tests
    migrated to read attributes. Six new off-by-default settings in
    `agent/config.py`. New CDK `MahaloMemoryIdentityStack`
    (`infra-cdk/mahalo_infra/memory_identity_stack.py`, wired in `app.py`):
    `CfnMemory` (STM, name `mahalo_memory` — underscore, the construct rejects
    hyphens), `CfnWorkloadIdentity` (`mahalo-agent`), `CfnApiKeyCredentialProvider`
    (`mahalo-jira-apikey`, no-echo `CfnParameter`), with `MemoryId` /
    `WorkloadIdentityArn` / `JiraApiKeyProviderName` outputs.
  - Code reviewed and APPROVED (`docs/.agents/tasks/task5-code-review.json`,
    verdict APPROVED). Offline gate re-run with REAL output and recorded in
    `docs/.agents/tasks/task5-verification.md`: `pytest agent -q` = **69 passed,
    1 skipped** (55 baseline + 14 new; DIRECT path 49/1 preserving the Task-2 42/1,
    Task-4 GATEWAY/HITL 6/6); `build_agent(memory=True, identity=True)` and
    `build_agent(tool_mode='gateway', memory=True)` both CONSTRUCT OFFLINE with no
    AWS creds (session manager constructed-but-not-attached ⇒ no rehydrate at
    build); `cdk synth --all` exit 0 (SIX templates incl.
    `MahaloMemoryIdentityStack`); infra-cdk assertions **31 passed**;
    tools-lambdas **94 passed**; zero LangChain. NO deploy was run and NO
    live/Memory/Identity results were fabricated. DEFERRED LIVE operator steps
    (deploy `MahaloMemoryIdentityStack`; run a two-invocation session that
    persists + reloads history across invocations via AgentCore Memory; exercise
    the Identity-brokered `jira_create_story` credential; `cdk deploy --all
    --profile lava`; teardown) are documented in
    `docs/.agents/tasks/task5-verification.md` and in the operator runbook below.
- Task 6 DONE (AgentCore Runtime hosting behind a thin stateless API, OFFLINE
  GATE GREEN; code-review APPROVED): the existing `agent/` package is hosted
  UNCHANGED on **Amazon Bedrock AgentCore Runtime** via a thin harness
  (`agent/runtime_app.py`: `BedrockAgentCoreApp` + a single `@app.entrypoint
  invoke`) that reuses the `build_agent -> attach_gateway_tools -> attach_memory`
  seam through `agent/runtime_session.build_and_attach` — no second agent. A thin,
  stateless **FastAPI forwarder** (`api/`, Mangum on a Function-URL Lambda) speaks
  a small `{action, prompt/decision, interrupt_id, ...}` request /
  `{response, proposal?, session_id, status, error?}` response contract and imports
  **zero `agent`/LangChain** code. Per-request **sessions** arrive on the runtime
  session-id header (surfaced as `context.session_id`, never in the body) and wire
  straight into Task-5 **Memory** via `build_agent(memory=True, session_id=...)`.
  **HITL** is a two-call propose->approve protocol at the Runtime boundary; the
  `[SYSTEM]` chain breadcrumb is derived from the Runtime's OWN restored interrupt
  state, so chain correctness does NOT depend on the client echoing the proposal
  (approve/reject + branch->commit->PR chaining preserved). The deferred
  **Identity** Runtime path LANDED but is descoped from the AWS_IAM MVP live gate:
  the Workload-Access-Token plumbing (`MAHALO_IDENTITY_ENABLED` env, per-user
  `grant_invoke_runtime_for_user`, `runtimeUserId` forwarding) is in place and
  flip-enabled, off by default under SigV4 inbound. IaC adds two stacks
  (`infra-cdk/mahalo_infra/runtime_stack.py` `MahaloRuntimeStack` — the **CDK L2
  `aws_bedrockagentcore.Runtime`** suite, auto-created exec role + app-level
  Bedrock/Memory/Gateway grants; `api_stack.py` `MahaloApiStack`), both wired in
  `app.py`; the Docker branches (image build + Lambda dep bundling) are flag-gated
  (`-c buildImage=1` / `MAHALO_BUILD_IMAGE=1`) so `cdk synth` stays Docker-free.
  DIRECT stays the default and unchanged; GATEWAY/Memory/Identity remain opt-in.
  Zero LangChain. Code reviewed and APPROVED
  (`docs/.agents/tasks/task6-code-review.json`, 0 blocking; 2 non-blocking
  "possible" items scheduled for the live gate). Offline gate re-run with REAL
  output and recorded in `docs/.agents/tasks/task6-verification.md`:
  `pytest agent -q` = **99 passed, 1 skipped** (69/1 baseline + 30 Task-6; DIRECT
  42/1 and Task-4 GATEWAY / Task-5 Memory-Identity preserved); thin-API
  `pytest api -q` = **15 passed**; `pytest tools-lambdas/tests -q` = **94 passed**;
  infra-cdk `pytest tests -q` = **42 passed, 1 skipped** (the 1 skip is the
  operator-only Docker from_asset deploy branch); `cdk synth --all` exit 0 (**EIGHT
  templates** incl. `MahaloRuntimeStack` + `MahaloApiStack`); the Runtime
  entrypoint and thin API both import/construct OFFLINE with no creds (thin API
  loads zero `agent.*`/`langchain*`); zero LangChain anywhere. NO deploy was run
  and NO live/Memory/Identity results were fabricated. DEFERRED LIVE operator
  steps (pre-deploy `aws sts get-caller-identity --profile lava`; build/push the
  ARM64 agent image + bundle the Lambda deps via `MAHALO_BUILD_IMAGE=1`;
  `cdk deploy --all --profile lava`; then through the deployed thin API a READ, a
  HITL WRITE via the two-call approve protocol, and a cross-invocation Memory
  persistence check; measure the synchronous invoke budget; teardown) are
  documented in `docs/.agents/tasks/task6-verification.md` and
  `docs/.agents/tasks/task6-deploy-runbook.md`.
- NEXT: Task 7 — Gitea + frontend hosting (stand up self-hosted Gitea on an
  always-on host — the GitHub-mock Lambda targets it — and deploy the reused
  Next.js frontend from mahalo-dock). See docs/PLAN.md. Task 6's live Runtime
  deploy/E2E remains a deferred operator step (not a Task-7 blocker).
  - AWS COST / DEPLOYED STATE: the five app stacks (Gateway + 4 Lambdas + 4
    DynamoDB tables) were TORN DOWN 2026-10-17 via
    `cdk destroy --all --force --profile lava` (confirmed: no `Mahalo*` stacks
    remain). Only `CDKToolkit` (the free bootstrap stack) is left, so NO ongoing
    Task-4 spend. Redeploy cleanly any time via `cdk deploy --all --profile lava`
    (~7 min; Gateway gets a NEW id/MCP URL each deploy — re-read the CfnOutputs).

## Task 2 — concrete definition (do this next)

Goal: add the WRITE tools to the Strands agent with a human-in-the-loop
propose/approve gate, so no write executes until the user approves it. Build on
Task 1's agent package; keep everything read-only still working. Tunnel + SSO
were live at end of Task 1, so Task 2 can be verified end-to-end (real
propose -> approve -> write against the mocks) in-session, not just offline.

The 7 write actions to add (contracts match the mahalo-dock tool modules under
`mahalo-dock/backend/app/agent/tools/*_tools.py` — read them for exact params):
- jira_create_story, jira_update_story
- github_create_branch, github_commit_files, github_open_pull_request
- servicenow_create_incident

Required behaviors to preserve (from the 7-write-actions section below and the
mahalo-dock originals):
- Propose, don't execute: a write-tool call returns a PROPOSAL for the user to
  approve; only after approval does the agent perform the real HTTP write
  (POST/PUT) against the mock. Decide HOW to model this in Strands 1.61.1 FIRST
  (investigate the installed SDK for a native human-in-the-loop / tool-interrupt
  / approval mechanism) rather than blindly porting mahalo-dock's
  `__PROPOSAL__...__END_PROPOSAL__` string sentinel. Pick the idiomatic Strands
  approach and document the decision.
- Resilience: "branch already exists" = success (not an error).
- Chaining: branch -> commit -> PR, each a separate approved step; a `[SYSTEM]`
  signal records which steps are already done so the agent never re-proposes a
  completed step.
- github_commit_files must carry the COMPLETE file contents (never a diff),
  re-emitting the full generated code.
- Keep the write-tool docstrings/behavioral rules (repo-NAME discipline, resolve
  people to dev-ids, UPDATE vs CREATE for existing story keys).
- Write HTTP verbs: jira create=POST /..., update=PUT; github create branch /
  commit / open PR = POST; servicenow create incident = POST. Confirm exact
  endpoints against the live mocks (tunnel) or mahalo-dock source.

Verification for Task 2 (tunnel + `lava` SSO up): a write request (e.g. "create
a story in PAY titled X" or "create a feature branch for PAY-109") produces a
PROPOSAL (nothing written yet), and only after an explicit approve does the mock
actually change (confirm by a follow-up read). Unit-test the propose path
(no HTTP on proposal) and the approve path (mocked HTTP write). Keep the Task 1
integration test green.

## AWS environment (verified)

- Account: <AWS_ACCOUNT_ID>, Region: us-east-1, SSO profile: `lava`.
- Re-auth when the session expires: `aws sso login --profile lava`, verify with
  `aws sts get-caller-identity --profile lava`.
- Bedrock model (tool-calling, verified ACTIVE):
  `us.anthropic.claude-sonnet-4-5-20250929-v1:0`.
- AgentCore capability check PASSED (11/11). Re-run anytime:
  `pwsh ./scripts/verify-agentcore.ps1`.
- Toolchain: Python 3.13, Node 24, npm 11, AWS CLI v2, AWS CDK 2.1145.0.
- SDKs install cleanly: `strands-agents` (1.61.1), `bedrock-agentcore` (1.24.1).

## The running mock backend (Task 1 uses option "a" = reuse what's deployed)

The mahalo-dock stack is already deployed on an EC2 instance and is the backend
Task 1 talks to. Do NOT redeploy it; just reach it over an SSH tunnel.

- EC2 instance: `i-0234d7d98744d60b9`, public IP **13.223.68.203** (the IP can
  change if the instance is stopped/started — re-check with:
  `aws ec2 describe-instances --filters "Name=tag:project,Values=mahalo-dock" "Name=instance-state-name,Values=running" --query "Reservations[0].Instances[0].PublicIpAddress" --output text --profile lava --region us-east-1`).
- SSH key: `%USERPROFILE%\.ssh\mahalo-dock-key.pem`.
- Mock services are published on the EC2 host on these ports (verified):
  - mock-jira 5001, mock-confluence 5002, mock-github 5003, mock-servicenow 5004
  - backend 8008, frontend 3000, gitea 3001
- Static auth header for every mock: `X-API-Token: mock-<svc>-token-12345`
  (e.g. `mock-jira-token-12345`, `mock-github-token-12345`).

### Open the tunnel for Task 1 (INCLUDES the mock ports 5001-5004)

The old tunnel only forwarded 3000/3001/8008. For Task 1 the agent calls the
mocks directly, so ALSO forward 5001-5004. Run in a separate terminal, leave open:

```powershell
ssh -i "$env:USERPROFILE\.ssh\mahalo-dock-key.pem" -N `
  -L 5001:localhost:5001 -L 5002:localhost:5002 `
  -L 5003:localhost:5003 -L 5004:localhost:5004 `
  -L 8008:localhost:8008 -L 3001:localhost:3001 `
  ubuntu@13.223.68.203
```

Then the agent's mock base URLs are: http://localhost:5001 (jira),
http://localhost:5002 (confluence), http://localhost:5003 (github),
http://localhost:5004 (servicenow). Make these ENV-CONFIGURABLE in the agent so
the same code works against localhost-tunnel now and other hosts later.

Quick reachability check once the tunnel is up:
```powershell
curl.exe -s -H "X-API-Token: mock-jira-token-12345" http://localhost:5001/projects
```

## Reuse map (copy FROM mahalo-dock, never edit it there)

Framework-agnostic assets to copy into mahalo-agentcore as Task 1+ needs them:
- Seed data: `mahalo-dock/mock-services/*/seed_data.py` (verbatim) — only needed
  when mocks become Lambdas (Task 3); Task 1 just calls the live mocks.
- Prompts: `mahalo-dock/backend/app/agent/prompts.py` (base + 3 role prompts,
  behavioral rules) -> port into the Strands system prompt.
- Tool CONTRACTS/semantics (names, params, read vs write) — see the tool list in
  docs/PLAN.md and the mahalo-dock tool modules under
  `backend/app/agent/tools/{jira,github,confluence,servicenow}_tools.py`.
- DB models + JWT auth + persona/project seeding (for the Task 6 thin API):
  `backend/app/models/`, `services/auth_service.py`, `services/identity.py`,
  `services/user_seed.py`, `services/project_seed.py`.
- Frontend: the whole `mahalo-dock/frontend/` (Task 7).
- Hard-won behaviors to carry forward: Bedrock read_timeout=300s; real repo NAME
  discipline (never invent repo-1 etc.; use github list -> real names like
  payment-service); persona identity mapping (lava@dev/exe/pm.com -> dev-6);
  github author->dev-6 mapping; proxy error propagation; dashboard array guards;
  propose/approve human-in-the-loop on all writes.

## The 7 write actions (preserve the human-approval gate)

create_story, update_story, create_branch, commit_files, open_pull_request,
create_incident. In mahalo-dock these were proposed (not executed) and approved
in a second step. Reproduce this human-in-the-loop in Strands (Task 2). Also keep
the "branch already exists = success" resilience and the branch->commit->PR
chaining.

## Task 1 — concrete definition (do this next)

Goal: a Strands agent, run LOCALLY, that answers read questions by calling the
live EC2 mocks over the tunnel. No LangChain anywhere.

1. In `agent/`, create a Python package with a venv and
   `requirements.txt` pinning `strands-agents`, `bedrock-agentcore`, `boto3`,
   `httpx`. (Keep .venv out of git — already in .gitignore.)
2. Configure the Strands agent to use Bedrock model
   `us.anthropic.claude-sonnet-4-5-20250929-v1:0` in us-east-1, with a botocore
   read timeout of 300s (large code-gen responses exceed the 60s default).
   Creds come from the `lava` profile locally (AWS_PROFILE=lava) — do NOT bake
   keys.
3. Port the base + developer role system prompt from
   mahalo-dock/backend/app/agent/prompts.py.
4. Implement the READ tools as Strands tools (HTTP + X-API-Token), base URLs
   from env (defaults to the localhost tunnel ports above):
   - jira: list_projects, list_developers, search_stories,
     get_stories_by_assignee, get_story, get_sprint_info, get_board
   - github: list_repos, get_pull_requests, get_commits, get_repo_stats
   - confluence: search, get_page, list_spaces
   - servicenow: list_deployments, deployment_status_by_project,
     list_incidents, get_incident, get_stats
   Keep the behavioral rules in tool descriptions (real repo names; resolve
   people to dev-ids; current user = dev-6 for "me/my").
5. Provide a small CLI/REPL (e.g. `python -m agent.chat "show my stories"`) for
   manual testing.
6. Tests: unit-test the tool HTTP wrappers (mocked), and ONE integration test
   that hits the live mocks via the tunnel ("show my stories" -> dev-6 -> PAY
   stories; "list my repositories" -> payment-service). Integration test should
   skip gracefully if the tunnel/mocks are unreachable.

Verification for Task 1: with the tunnel up and AWS session valid, the REPL
answers "list my repositories" (returns payment-service) and "show PAY-109"
correctly, routing through Strands + Bedrock, with zero LangChain imports.
Defer the write/propose/approve flow to Task 2.

## Working agreement for every session

- Only write under mahalo-agentcore. Never edit mahalo-dock.
- Commit to the mahalo-agentcore repo (origin/main) at the end of each task with
  a clear message; keep mahalo-dock's git history separate.
- Update this file's "Status" section and docs/PLAN.md as tasks complete.
- Each task should produce something runnable (phased build).

## Task 5 — Memory & Identity operator runbook (live, NOT run in the offline gate)

Memory and Identity are opt-in and additive; with the toggles off, DIRECT and
GATEWAY behave exactly as before. The automated gate is offline (synth / unit
tests / import). The steps below are for exercising the live capabilities.

1. `aws sso login --profile lava`.
2. `cd infra-cdk && cdk deploy MahaloMemoryIdentityStack --profile lava` (supply
   the `JiraApiKey` parameter or accept the mock default). Note the stack
   outputs: `MemoryId`, `WorkloadIdentityArn`, `JiraApiKeyProviderName`.
3. Export the Memory toggles:
   - `$env:MAHALO_MEMORY_ENABLED = "true"`
   - `$env:MAHALO_MEMORY_ID = "<MemoryId output>"`
   - optionally `$env:MAHALO_IDENTITY_ENABLED = "true"`.
4. Two-invocation persistence check (STM across invocations):
   - `python -m agent.chat --session-id demo-1 "remember my favorite repo is payment-service"`
   - then `python -m agent.chat --session-id demo-1 "what's my favorite repo?"`
   - the second answer should reflect the reloaded history.
   With Identity on, run a `jira_create_story` write and confirm it succeeds
   using the brokered API key (fetched at call time, not from the static env).

   **Local workload-identity note:** the first Identity-enabled run from the
   local CLI uses the SDK's local dev-auth path, which self-provisions a *local*
   workload identity and writes a `.agentcore.json` file into the run directory.
   It does NOT use the CDK `CfnWorkloadIdentity` (`mahalo-agent`), which is for
   the Task-6 Runtime path. Expect that file to appear; it is a dev-auth cache
   and can be deleted to force re-provisioning. The brokered key itself comes
   from the CDK `CfnApiKeyCredentialProvider` (`mahalo-jira-apikey`).
5. When done for the day, `cdk destroy MahaloMemoryIdentityStack` to stop Memory
   charges (and optionally delete `.agentcore.json`).

**Construction-boundary note:** the installed `bedrock-agentcore 1.24.1`
`AgentCoreMemorySessionManager.__init__` is NOT offline-safe — it performs a live
`ListEvents` read at construction. So `build_agent(memory=True)` only assembles an
offline `MemorySessionSpec`; the live manager is built inside `attach_memory`
(the single AWS touch). See `docs/.agents/tasks/task5-verification.md`.
