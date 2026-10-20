# Task 6 — Runtime hosting: OFFLINE verification

Host the Strands agent on **Amazon Bedrock AgentCore Runtime** behind a thin,
stateless API (`api/`). This document records the **offline gate** re-run with
**real output** in a clean environment (no `MAHALO_*` env vars set), confirms the
Task-6 success criteria that are provable offline, and lists the **deferred live
operator steps** (which were NOT run — no live/deploy results are fabricated).

- Code review: **APPROVED** (`docs/.agents/tasks/task6-code-review.json`, 0
  blocking findings; 2 non-blocking "possible" items scheduled for the live gate).
- Deploy policy: the automated gate is **OFFLINE** — `cdk synth` + unit tests +
  import/construct, no network, no AWS creds. Nothing here auto-deploys.
- Hard rule honored: every artifact is under
  `D:/<USER>/LavaCode/AI/mahalo-agentcore`; `mahalo-dock` untouched.

Environment for the run: a PowerShell session with **no `MAHALO_*` env vars**
(the Task-5 `test_memory_mode.py` / `test_gateway_mode.py` cases read ambient env
and would misreport otherwise). Each command below was prefixed with a clean-env
guard that removes any ambient `MAHALO_*` vars for the child process.

---

## Commands run and REAL output (offline only)

### 1. Agent suite — Runtime entrypoint + all prior baselines

Clean env, then:

```powershell
& "agent/.venv/Scripts/python.exe" -m pytest agent -q
```

Real output (tail):

```
................s................................ [ 49%]
................................................. [ 98%]
..                                                [100%]
99 passed, 1 skipped, 3 warnings in 18.42s
```

**Result: 99 passed, 1 skipped.** The 1 skip is the single live-integration test
(`test_integration_live.py`) that skips gracefully with the tunnel/mocks down —
not fabricated, same skip carried since Task 1.

Per-file collection (clean env, `--collect-only`):

| test file | tests |
|-----------|------:|
| `test_tools_unit.py` | 13 |
| `test_write_tools_unit.py` | 36 |
| `test_hitl.py` | 6 |
| `test_gateway_mode.py` | 6 |
| `test_identity_mode.py` | 4 |
| `test_memory_mode.py` | 10 |
| `test_runtime_app.py` | **24 (Task 6)** |
| `test_integration_live.py` | 1 (skipped) |
| **total** | **100 collected → 99 passed / 1 skipped** |

This is the clean-env **69 passed / 1 skipped** baseline from Task 5 **plus 30
Task-6 additions**, all green:
- **DIRECT** core preserved — the Task-1/2 read+write+HITL baseline (42 passed /
  1 skipped) lives in `test_tools_unit.py` (13) + `test_write_tools_unit.py` (36)
  + `test_hitl.py` (6) + the integration skip; untouched.
- **Task-4 GATEWAY** (`test_gateway_mode.py`, 6) and **Task-5 Memory/Identity**
  (`test_memory_mode.py` 10 + `test_identity_mode.py` 4) preserved.
- **Task-6** adds `test_runtime_app.py` (24): entrypoint chat/approve legs, HITL
  propose→approve→reject, chain-breadcrumb-from-restored-state, session-id
  contract, input validation, `build_and_attach` composition order (DIRECT and
  GATEWAY), import-time offline-safety, and the Bedrock profile-resolution path.

### 2. Thin API suite (`api/`) — the stateless forwarder

```powershell
& "api/.venv/Scripts/python.exe" -m pytest api -q
```

Real output (tail):

```
...............                                   [100%]
15 passed, 1 warning in 2.88s
```

**Result: 15 passed.** Covers: offline import of the FastAPI app + Mangum handler,
the §A.3 request/response contract forwarding (chat + approve/reject), error
mapping (502 on invoke failure, in-band error passthrough), and the **zero-agent /
zero-LangChain** guards over the `api/` source tree and over `sys.modules` after
importing `app.main`.

### 3. tools-lambdas suite

```powershell
& "tools-lambdas/.venv/Scripts/python.exe" -m pytest tools-lambdas/tests -q
```

Real output (tail):

```
................................................. [ 52%]
.............................................     [100%]
94 passed, 634 warnings in 58.91s
```

**Result: 94 passed** — the Task-3/4 baseline (94) preserved; Task 6 did not
touch the Lambdas. (Warnings are upstream botocore `utcnow()` deprecations.)

### 4. infra-cdk suite (in `infra-cdk/.venv`)

```powershell
cd infra-cdk
& .\.venv\Scripts\Activate.ps1
python -m pytest tests -q
```

Real output (tail):

```
......................s....................       [100%]
42 passed, 1 skipped in 286.46s (0:04:46)
```

**Result: 42 passed, 1 skipped.** This is the Task-5 baseline (31) plus the Task-6
stack-assertion additions (`test_runtime_stack.py`, `test_api_stack.py`,
synth-count update in `test_synth.py`). The **1 skip** is deliberate and offline-
correct:

```
SKIPPED [1] tests\test_runtime_stack.py:108: Docker unavailable; the from_asset
deploy branch is operator-only.
```

The `from_asset` (image-build) branch invokes Docker, which the offline gate
forbids; it is exercised only on the operator deploy. The default/offline branch
(`from_image_uri(CfnParameter.value_as_string)`) is fully asserted.

### 5. cdk synth --all (offline, no creds)

```powershell
cd infra-cdk
& .\.venv\Scripts\Activate.ps1
cdk synth --all
```

Real output (tail):

```
Successfully synthesized to ...\infra-cdk\cdk.out
...
EXITCODE=0
```

**Exit 0.** Eight templates produced — the six from Task 5 plus the two new
Task-6 stacks:

```
MahaloApiStack.template.json            (Task 6)
MahaloGatewayStack.template.json
MahaloMemoryIdentityStack.template.json
MahaloMockConfluenceStack.template.json
MahaloMockGithubStack.template.json
MahaloMockJiraStack.template.json
MahaloMockServicenowStack.template.json
MahaloRuntimeStack.template.json        (Task 6)
```

Key resource types synthesized (confirms the Runtime construct suite + thin-API
Lambda, no Docker on this branch):
- `MahaloRuntimeStack`: `AWS::BedrockAgentCore::Runtime` +
  `AWS::BedrockAgentCore::RuntimeEndpoint` + the auto-created execution
  `AWS::IAM::Role`/`Policy` + CloudWatch Logs delivery + X-Ray resource policy.
- `MahaloApiStack`: `AWS::Lambda::Function` + `AWS::Lambda::Url` (AuthType
  `AWS_IAM`) + the invoke `AWS::IAM::Role`/`Policy`.

> Note on provisioning: the Runtime is provisioned via the **CDK L2
> `aws_bedrockagentcore.Runtime`** construct (not boto3/starter-toolkit), so the
> standard `cdk synth` / `cdk deploy` path applies and the provisioning plan is
> validated offline by the synth above.

### 6. Runtime entrypoint + thin API import/construct offline (no network, no creds)

Clean env (also cleared `AWS_*`), then:

```powershell
& "agent/.venv/Scripts/python.exe" -c "import agent.runtime_app as r; ..."
```

Real output:

```
runtime_app import OK; app= BedrockAgentCoreApp
entrypoint= invoke
build_and_attach import OK
```

```powershell
# in api/, with a placeholder MAHALO_RUNTIME_ARN
& ".venv/Scripts/python.exe" -c "import app.main as m; ..."
```

Real output:

```
thin API import OK; handler= Mangum
app routes= ['/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc', '/chat', '/chat/approve', '/healthz']
forbidden imports: []
```

Confirms:
- The Runtime entrypoint `agent/runtime_app.py` imports offline; `app` is a
  `BedrockAgentCoreApp` (Starlette subclass construction, no network) and the
  `@app.entrypoint` `invoke` is registered. `build_and_attach` is not called until
  an invocation arrives (the single AWS touch stays inside the agent call).
- The thin API `api/app/main.py` imports offline; the Mangum handler is built and
  the `/chat` + `/chat/approve` + `/healthz` routes are present. The boto3
  `bedrock-agentcore` client is lazy, so import touches no AWS.
- **Zero forbidden imports:** importing the thin API pulls in **no `agent.*` and
  no `langchain*`** modules — the edge is a pure forwarder.

### 7. Zero LangChain anywhere

A tree-wide search for `langchain`/`langgraph` import statements across
`**/*.{py,txt,toml,cfg}` (excluding `.venv`) returns only **negative assertions**:
the `api/tests/test_api.py` guards that fail if any `langchain`/`agent` import
appears, and comments in `api/requirements.txt` / `api/app/__init__.py` stating
the forwarder must not import LangChain. There are **no LangChain or LangGraph
imports** in any source or requirements file. The runtime import check in §6 also
confirms zero `langchain*` modules load at import.

---

## Success criteria — confirmation (offline-provable)

| Criterion | Status | Evidence (offline) |
|-----------|--------|--------------------|
| Runtime entrypoint hosts the agent | ✅ | `agent/runtime_app.py` — `BedrockAgentCoreApp` + single `@app.entrypoint invoke`, reusing the unchanged `build_agent` seam via `agent/runtime_session.build_and_attach`; imports offline (§6); synthed as `AWS::BedrockAgentCore::Runtime` + endpoint (§5). |
| Thin stateless API with request/response contract | ✅ | `api/app` FastAPI + Mangum Function-URL Lambda; `/chat` + `/chat/approve` forward the §A.3 `{action, prompt/decision, interrupt_id, ...}` request and map `{response, proposal?, session_id, status, error?}` back; 15/15 tests (§2); synthed as Lambda + Function URL `AWS_IAM` (§5). |
| HITL approve/reject over the two-call protocol | ✅ | `_handle_chat` returns `pending_approval` + proposal on interrupt; `_handle_approve` resumes the restored interrupt, emits the `[SYSTEM]` breadcrumb only on a closed APPROVE cycle, nothing on REJECT; the six writes stay gated by `WriteApprovalHook`. Covered by `test_runtime_app.py` (pending/approve/reject/chained-repropose/stale-id). |
| Session contract | ✅ | Session id arrives on the `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` header (surfaced as `context.session_id`), never in the body; a missing header is generated + echoed back. `test_missing_session_header_generates_and_echoes_id` + the thin-API `session_id` passthrough. |
| Offline-constructible + unit-tested with stubs | ✅ | Entrypoint and thin API import/construct with no network/creds (§6); `build_and_attach` and the entrypoint legs are unit-tested with `build_and_attach` / agent / Memory-manager stubbed (§1, §2). |
| Per-request sessions wired to Task-5 Memory, cross-invocation persistence demonstrated offline via a mocked Memory client | ✅ | `build_and_attach(session_id, ...)` calls `build_agent(memory=True, session_id=...)` → `attach_memory` (the single AWS touch: `ListEvents` rehydrate + per-turn persistence hooks). Offline proof with a **stubbed/mocked Memory manager**: `test_memory_mode.py` asserts the STM config (`filter_restored_tool_context=True`, `batch_size=1`, session_id/actor_id binding) and that the per-turn persistence callbacks register; `test_runtime_app.py::test_approve_emits_breadcrumb_from_restored_state` demonstrates the approve leg deriving the chain breadcrumb from **restored** interrupt state (i.e. state carried across an invocation boundary) with the Memory layer stubbed. |
| Deferred Identity Runtime path landed | ✅ | The Runtime Workload-Access-Token plumbing is in place and config-flippable: `runtime_stack` injects `MAHALO_IDENTITY_ENABLED` (off for the AWS_IAM MVP) + `MAHALO_IDENTITY_JIRA_PROVIDER`; `MahaloApiStack(identity_enabled=True)` wires the per-user `grant_invoke_runtime_for_user`; `runtime_client.invoke_runtime` forwards `runtimeUserId`; the chat router sends `runtimeUserId` only when Identity is enabled. Descoped from the live MVP gate per the design (SigV4 inbound) — the enablement flip (not a redesign) is in the deploy runbook. |
| DIRECT / GATEWAY CLI intact | ✅ | `agent/chat.py` unchanged for DIRECT (default) and GATEWAY; `test_gateway_mode.py` (6) + the DIRECT read/write/HITL suite all green (§1). `build_and_attach` reuses the same `attach_gateway_tools`→`attach_memory` seams as the CLI (single MCP start, no double-start). |
| Zero LangChain | ✅ | §7 — no LangChain/LangGraph imports anywhere; thin-API import loads zero `langchain*` / `agent.*` modules (§6). |

**Not provable offline (scheduled for the live gate):** the two non-blocking
code-review "possible" items — (1) the direct-Runtime-call session-id fallback
length (32-char hex vs AgentCore's 33-char minimum; cannot fire via the thin API,
which sends a 36-char uuid4), and (2) the cross-VM HITL restore under live
conditions (`filter_restored_tool_context=False` pending-write rebuild across a
cold process boundary). Both are addressed in the live runbook §C.5.

---

## DEFERRED LIVE OPERATOR STEPS (NOT run here — documented only)

These are **billable, operator-run** steps for a live Runtime demo. The full
runbook is `docs/.agents/tasks/task6-deploy-runbook.md`; the exact commands are
reproduced here. **None of these were executed; no live/deploy results exist.**

### Pre-deploy auth check (AWS SSO, profile `lava`, account <AWS_ACCOUNT_ID>, us-east-1)

```powershell
aws sts get-caller-identity --profile lava
```

(If the SSO session is expired: `aws sso login --profile lava` first.)

### Container build + ECR push (the Runtime needs an ARM64 image)

The image build is folded into the CDK deploy via the `MAHALO_BUILD_IMAGE=1`
flag: `MahaloRuntimeStack` then uses `AgentRuntimeArtifact.from_asset(repo_root,
file="agent/Dockerfile", platform=LINUX_ARM64)`, which builds and pushes the
image to the CDK ECR asset repository as part of synth/deploy (Docker required).
The thin-API Lambda deps are bundled the same way (`MahaloApiStack`
`BundlingOptions`). So there is no separate `docker build`/`ecr push`; enable the
flag before the deploy:

```powershell
$env:MAHALO_BUILD_IMAGE = "1"   # turns on the Docker build/bundle branches
```

### CDK deploy (CDK L2 Runtime path — not starter-toolkit/boto3)

Deploy the dependency stacks first, then the Runtime, then the thin API
(direct construct refs let CDK auto-order; listed explicitly for clarity):

```powershell
cd infra-cdk
$env:MAHALO_BUILD_IMAGE = "1"
cdk deploy MahaloMemoryIdentityStack MahaloGatewayStack `
  MahaloMockJiraStack MahaloMockConfluenceStack `
  MahaloMockGithubStack MahaloMockServicenowStack --profile lava
cdk deploy MahaloRuntimeStack --profile lava   # note the RuntimeArn output
cdk deploy MahaloApiStack --profile lava        # note the RuntimeApiUrl output
```

(Or the whole set in one shot: `cdk deploy --all --profile lava` with
`$env:MAHALO_BUILD_IMAGE = "1"` set.)

### End-to-end live invocation checks (through the deployed thin API, SigV4-signed)

1. **READ** — a read routes Strands → Bedrock → tools → reply:
   ```
   POST <RuntimeApiUrl>/chat   {"message":"list my repositories"}
   ```
   Expect a `complete` reply naming the real mock repos (e.g. `payment-service`).

2. **HITL WRITE via the two-call approve protocol** — propose, then approve:
   ```
   POST <RuntimeApiUrl>/chat          {"message":"create a feature branch for PAY-109"}
      -> expect status=pending_approval + a proposal, NOTHING written yet
   POST <RuntimeApiUrl>/chat/approve  {"session_id":S,"interrupt_id":<id>,"approved":true}
      -> expect exactly one write and NO ValidationException
   ```
   On a fresh proposal, `approved:false` must write nothing. A branch → commit →
   PR chain across three approves must re-propose no completed step (the
   `[SYSTEM]` breadcrumb is persisted to Memory and seen on the next turn).
   > If the approve raises a `ValidationException` (toolResult/toolUse mismatch),
   > apply the design §C.4 fallback (explicit `pending_action` proposal) — this is
   > the designated live gate for the `filter_restored_tool_context=False`
   > pending-write rebuild, not a surprise.

3. **Cross-invocation Memory persistence** — same `session_id` across two calls:
   ```
   POST <RuntimeApiUrl>/chat  {"message":"remember my favorite repo is payment-service","session_id":S}
   POST <RuntimeApiUrl>/chat  {"message":"what's my favorite repo?","session_id":S}
      -> the second answer should reflect the reloaded history (AgentCore Memory STM)
   ```

### Open live item + teardown

- **Measure (do not assume)** the synchronous `InvokeAgentRuntime` budget on a
  representative code-gen `github_commit_files` call; if a long commit is at risk,
  switch the entrypoint to the SSE/streaming path before the demo.
- **Teardown to stop spend:**
  ```powershell
  cd infra-cdk
  cdk destroy MahaloApiStack MahaloRuntimeStack `
    MahaloMemoryIdentityStack MahaloGatewayStack `
    MahaloMockJiraStack MahaloMockConfluenceStack `
    MahaloMockGithubStack MahaloMockServicenowStack --profile lava
  ```

---

## Offline gate summary

| Gate | Result |
|------|--------|
| Agent suite (`pytest agent -q`) | **99 passed, 1 skipped** (69/1 baseline + 30 Task-6; DIRECT 42/1 preserved) |
| Thin API suite (`pytest api -q`) | **15 passed** |
| tools-lambdas (`pytest tools-lambdas/tests -q`) | **94 passed** |
| infra-cdk (`pytest tests -q`) | **42 passed, 1 skipped** (Docker deploy-branch test, operator-only) |
| `cdk synth --all` | **exit 0** — 8 templates (incl. `MahaloRuntimeStack`, `MahaloApiStack`) |
| Runtime entrypoint import offline | **OK** — `BedrockAgentCoreApp`, no network |
| Thin API import offline | **OK** — zero `agent.*` / `langchain*` imports |
| Zero LangChain | **confirmed** — no LangChain/LangGraph imports anywhere |

No deploy was run; no live/Memory/Identity results were fabricated.
