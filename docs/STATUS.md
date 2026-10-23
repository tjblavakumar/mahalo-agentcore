# mahalo-agentcore — Project Status

**Snapshot date:** 2026-10-18 (updated)
**Branch:** `main` @ `d4f386f` — **Tasks 0-7 all committed + pushed, in sync with
origin.** Every task is offline-complete + code-review APPROVED. Nothing of ours
is deployed to AWS (only the free CDKToolkit bootstrap stack remains).
**NEXT ACTION:** execute the **EC2 Docker-builder runbook**
(`docs/.agents/tasks/task7b-ec2-builder-runbook.md`) for the full live end-to-end
deploy + browser validation of Tasks 3-7 together, done WITH the user, then code
review of Task 7b. The operator workstation is an AWS WorkSpaces VDI with **no
local Docker** (no nested virtualization), so the deploy path is NOT "run
`cdk deploy --all` locally with Docker Desktop" — it is **"provision
`MahaloBuilderStack` from the VDI (Docker-free synth) → SSM into the arm64 EC2
builder → run `scripts/builder-deploy.sh --phase all`"** (the builder has Docker
and runs the two Docker-dependent deploys natively on Graviton). The app now has
**11 CDK stacks** (the 10 app stacks + `MahaloBuilderStack`). See
`docs/.agents/tasks/task7b-design.md` for the design. Then Task 8 (re-deployable
CDK + teardown) and Task 9 (docs).
**Repo:** https://github.com/tjblavakumar/mahalo-agentcore

This is the one-page "where are we" view. For per-task depth see `docs/PLAN.md`
(design/scope per task) and `docs/CONTINUATION.md` (operational handoff +
runbooks). Per-task investigation/design/review/verification artifacts live under
`docs/.agents/tasks/`.

---

## What this project is

A ground-up rewrite of **mahalo-dock** (a multi-persona SDLC chat assistant over
four mock enterprise systems: Jira, Confluence, GitHub/Gitea, ServiceNow) onto the
**Amazon Bedrock AgentCore** stack + **Strands Agents SDK**, replacing the old
hand-rolled LangChain/LangGraph loop. The original mahalo-dock is kept untouched
as a fallback and is only ever read from, never edited.

Target end-state (see `docs/ARCHITECTURE.md`): Next.js frontend → thin API →
AgentCore **Runtime** (hosts the Strands agent) → Bedrock Claude Sonnet 4.5, with
AgentCore **Memory** (sessions), **Gateway** (the four Lambdas as MCP tools), and
**Identity** (tool credentials); the GitHub mock backed by self-hosted Gitea; all
provisioned by AWS CDK (Python) that survives a monthly account reset.

---

## Done (committed + pushed)

| Task | What | Verification | Live? |
|------|------|--------------|-------|
| 0 | Repo skeleton, docs, `scripts/verify-agentcore.ps1` | — | — |
| 1 | Local Strands agent, 19 read tools over the mocks, Bedrock Sonnet 4.5, env-driven config, `python -m agent.chat` CLI | offline 13/13; live-verified | ✅ (EC2 mocks via tunnel) |
| 2 | 6 HITL write tools + `WriteApprovalHook` (native Strands interrupt), propose/approve/reject, branch→commit→PR chaining | offline 42/1; live-verified | ✅ |
| 3 | Four mocks reimplemented as **AWS Lambdas** (DynamoDB-backed) + CDK `MockServiceStack`×4; seed data byte-identical to mahalo-dock | offline: 94 lambda tests, cdk synth, 20→ infra tests | deploy deferred→done in Task 4 |
| 4 | **AgentCore Gateway** + 4 targets expose the 25 tools as MCP; agent dual-mode (`MAHALO_TOOL_MODE`, DIRECT default / GATEWAY opt-in); SigV4/AWS_IAM inbound auth; HITL preserved over MCP | offline gate green; **live E2E passed** (read + HITL approve/reject through the deployed Gateway) | ✅ deployed, validated, then **torn down** |
| 5 | **AgentCore Memory** (short-term conversation, session-id keyed) + **Identity** (one API-key-brokered outbound path); both opt-in/additive; CDK `MahaloMemoryIdentityStack` | offline: agent 69/1, infra-cdk 31, lambdas 94, zero LangChain | deploy + persist/reload check deferred |
| 6 | **AgentCore Runtime** hosts the agent (`agent/runtime_app.py`, L2 `agentcore.Runtime`) behind a **thin stateless FastAPI forwarder** (`api/`, Function-URL Lambda); per-request sessions → Task-5 Memory; two-call HITL approve/reject at the Runtime boundary; Identity Runtime path plumbed (off for the AWS_IAM MVP); CDK `MahaloRuntimeStack` + `MahaloApiStack` | offline gate green: agent 99/1, api 15, infra-cdk 42/1, lambdas 94, `cdk synth --all` exit 0 (8 templates), entrypoint + thin API import offline, zero LangChain | deploy + E2E read / HITL write / Memory-persist check deferred |

**Current test baseline (clean env):** agent `99 passed, 1 skipped`; thin-API
`15 passed`; infra-cdk `42 passed, 1 skipped` (the 1 skip is the operator-only
Docker from_asset branch) + `cdk synth --all` exit 0 (8 templates);
tools-lambdas `94 passed`; zero LangChain anywhere.

**DIRECT mode is always the default** and stays byte-for-byte unchanged across
Tasks 4–6; GATEWAY / Memory / Identity are all opt-in via `MAHALO_*` env toggles.
The Runtime harness and thin API reuse the same `build_agent` seam the CLI uses.

---

## AWS deployed state

**Nothing of ours is currently deployed.** Task 4's stacks (Gateway + 4 Lambdas +
DynamoDB) were deployed, live-validated, then destroyed (`cdk destroy --all`) to
stop spend — confirmed zero `Mahalo*` CloudFormation stacks remain. Only the free
`CDKToolkit` bootstrap stack is left (account `<AWS_ACCOUNT_ID>`, `us-east-1`, SSO
profile `lava`).

**Deploy path (VDI — no local Docker):** because the operator workstation is an
AWS WorkSpaces VDI with no nested virtualization, the two Docker-dependent deploys
(the `MahaloRuntimeStack` ARM64 agent image and the `MahaloApiStack` Lambda
dependency bundle) cannot run locally. The supported path is the **EC2
Docker-builder** (Task 7b): deploy the Docker-free `MahaloBuilderStack` from the
VDI, SSM into the arm64 EC2 builder, and run `scripts/builder-deploy.sh --phase
all` there for the full staged deploy; validate in the browser at the CloudFront
`FrontendUrl`; then tear down the app stacks **from the builder** and the builder
**from the VDI last**. Full steps in
`docs/.agents/tasks/task7b-ec2-builder-runbook.md` (design in
`docs/.agents/tasks/task7b-design.md`). The app now has **11 CDK stacks** (the 10
app stacks + `MahaloBuilderStack`). The old "run `cdk deploy --all --profile lava`
locally with Docker Desktop" path is superseded for the VDI by the builder (it
still works from any workstation that actually has local Docker). Each deploy's
Gateway gets a fresh id/MCP-URL — re-read the CfnOutputs.

---

## Still to be developed

### Deferred LIVE operator steps for already-built tasks
These are implemented and offline-verified; they need a real AWS deploy to
exercise end-to-end (billable; run under `lava` SSO). Commands are in each task's
`docs/.agents/tasks/taskN-verification.md`.
- **Task 3/4 redeploy** — `cdk deploy --all` to stand the Lambdas + Gateway back up.
- **Task 5 Memory live check** — deploy `MahaloMemoryIdentityStack`, then run the
  CLI twice with the same `--session-id` and confirm conversation history
  persists/reloads via AgentCore Memory; exercise the Identity-brokered
  `jira_create_story` API-key path.
- **Task 6 Runtime live gate** — build/push the agent image + deploy
  `MahaloRuntimeStack` + `MahaloApiStack` (`MAHALO_BUILD_IMAGE=1`, `cdk deploy
  --all --profile lava`), then through the deployed thin API: a **READ**, a
  **HITL WRITE** via the two-call approve protocol (propose → approve/reject,
  branch→commit→PR chain), and a **cross-invocation Memory persistence** check
  (same `session_id` across two `/chat` calls). Also measure the synchronous
  `InvokeAgentRuntime` budget on a code-gen commit. Exact commands in
  `docs/.agents/tasks/task6-verification.md` + `task6-deploy-runbook.md`.

### Remaining tasks (not started) — see `docs/PLAN.md`
- **Task 7 — Gitea + frontend hosting.** Stand up self-hosted Gitea on an
  always-on host (the GitHub-mock Lambda targets it) and deploy the reused
  Next.js frontend (portable from mahalo-dock).
- **Task 8 — Re-deployable CDK + teardown.** Harden all CDK stacks so the whole
  environment deploys and tears down cleanly and repeatably (survives the monthly
  account reset).
- **Task 9 — Docs.** Finalize architecture, operations, and a demo walkthrough.

### Known smaller follow-ups / tech debt
- **Test env-isolation (Task 5):** a few `test_memory_mode.py` / `test_gateway_mode.py`
  tests read ambient `MAHALO_*` env vars instead of fully isolating them via
  monkeypatch, so they can fail if the shell already has those set (e.g. after a
  live GATEWAY run). Low severity — the suite is green in a clean env (69/1); tidy
  for robustness.
- **Pre-existing GitHub repo keying quirk (carried from mahalo-dock):** the agent
  passes the repo *name* in GitHub tool paths, but the mocks key collections by
  repo *id* (`repo-1..repo-5`), so a name-based GitHub write can 404 against the
  mock. This is faithfully preserved (not a bug to "fix" in the port); revisit if
  a demo needs name-based GitHub writes to succeed end-to-end.
- **Memory long-term strategies:** only short-term conversation memory is wired;
  a `with_long_term` seam exists but is off. Enable if the demo wants
  summaries/semantic recall.
- **Identity breadth:** only one representative outbound path is brokered; broaden
  per-service once Task 6 Runtime identity is in place.

---

## How to resume

1. Open a session with `mahalo-agentcore` as the workspace root.
2. Read `docs/CONTINUATION.md` top-to-bottom (handoff + the hard operational
   rule: only ever write under `mahalo-agentcore`, never edit `mahalo-dock`).
3. Re-auth if needed: `aws sso login --profile lava`, verify with
   `aws sts get-caller-identity --profile lava`.
4. Next planned work: **Task 7 — Gitea + frontend hosting** (per `docs/PLAN.md`).
   Task 6 (Runtime hosting) is offline-complete + code-review APPROVED; its live
   deploy/E2E gate is a deferred operator step (see
   `docs/.agents/tasks/task6-verification.md`).
