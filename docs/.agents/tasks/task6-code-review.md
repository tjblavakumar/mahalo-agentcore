# Task 6 — Runtime hosting + thin stateless API

Hosts the existing Strands agent on Bedrock AgentCore Runtime behind a thin, stateless FastAPI forwarder. A new `agent/runtime_app.py` wraps the unchanged `build_agent` seam in a `BedrockAgentCoreApp` entrypoint; a new `api/` package forwards `POST /chat` + `POST /chat/approve` to the Runtime over `InvokeAgentRuntime`; and two new CDK stacks (`MahaloRuntimeStack`, `MahaloApiStack`) provision the L2 `agentcore.Runtime` + a Function-URL Lambda, both offline-synth-able. The HITL gate becomes a two-call propose→approve protocol with no stdin, the six writes stay gated by the unchanged `WriteApprovalHook`, and every new path is additive/opt-in so the DIRECT/GATEWAY CLI and the clean-env baseline are untouched.

Watch for: nothing blocking. The implementation is faithful to the approved design across all six dimensions, the L2 CDK surface it relies on is confirmed in installed source, and the coder's recorded offline evidence (agent 99/1, api 15, infra 42/1 + synth exit 0, tools-lambdas 94) is internally consistent with the diff. Two **possible** low-severity observations are noted below for the operator's live gate, neither blocking.

**Verdict**: APPROVED

## High-level view

The Runtime entrypoint hosts `build_agent` through the single `build_and_attach` composition helper that mirrors `agent/chat.py` exactly (build → attach gateway tools in GATEWAY mode → attach memory). Import-time is offline-safe: constructing `BedrockAgentCoreApp` is a Starlette subclass construction and the agent is not built until an invocation arrives. The request/response contract matches design §A.3 field-for-field.

The thin API is genuinely thin. It imports no `agent/` code, carries no second agent, no LangChain, no business logic — it serializes the JSON contract, forwards the session id as `runtimeSessionId`, and projects the reply onto the mahalo-dock `ChatResponse`/`ActionResult` shape. The boto3 client is lazy so the module imports with no creds.

HITL works without stdin: the chat leg returns `pending_approval` with the `build_proposal` dict (carried as `itr.reason`) plus `interrupt_id`; the approve leg rebuilds the agent with `pending_write=True`, derives the breadcrumb from restored interrupt state, resumes via the `interruptResponse` block, and emits the `[SYSTEM]` branch→commit→PR breadcrumb on a closed APPROVE cycle. The six writes remain gated by the unchanged `WriteApprovalHook`.

Per-request session ids wire to Task-5 Memory through `build_agent(memory=True, session_id=...)`; the new `pending_write` flag flips `filter_restored_tool_context` to `False` only for approve-leg builds, leaving Task-5 STM behavior byte-for-byte unchanged everywhere else. The Identity Workload-Access-Token path is landed as designed but descoped-OFF for the AWS_IAM MVP (`MAHALO_IDENTITY_ENABLED=false`), with the `runtimeUserId` plumbing present and opt-in.

The IaC is offline-synth-able: the Runtime artifact is flag-gated between `from_image_uri(CfnParameter)` (default, Docker-free) and `from_asset` (operator deploy), the L2 auto-creates the execution role with AWS_IAM default authorizer, and app-level Bedrock/Memory grants (plus explicit ECR-pull on the parameter branch) are added onto `runtime.role`. No git commit was made by the coder; no live/deploy results are fabricated — deploy stays a deferred operator runbook.

<details>
<summary>Issues (2)</summary>

1. **Runtime-side session-id fallback length (possible)** — `_resolve_session_id` generates `uuid.uuid4().hex` (32 chars) when the header is absent; AgentCore's `runtimeSessionId` minimum is 33 chars. This only fires on a direct Runtime call bypassing the thin API (which sends a 36-char `uuid4()`), and the value is only echoed, not re-sent by the Runtime, so it cannot break the thin-API path. Operator should confirm the direct-invoke fallback during the live gate or widen the generated id.
2. **Cross-VM HITL restore under live conditions (possible)** — the `filter_restored_tool_context=False` contract for pending-write sessions is designed to keep the open toolUse in the restored message list, but the design itself flags that the cross-process interrupt-state restore is the designated live verification gate. Not verifiable offline; the deploy runbook §C.5 already schedules it.

</details>

<details>
<summary>Details</summary>

### Runtime entrypoint hosts build_agent with the §A.3 contract, offline-safe

`agent/runtime_app.py` constructs `BedrockAgentCoreApp()` at import and registers a single two-parameter `@app.entrypoint def invoke(payload, context)` — the second parameter is named `context`, which the harness requires (it introspects the name). The agent is not built until `build_and_attach` runs inside `_handle_chat`/`_handle_approve`, so `import agent.runtime_app` touches no AWS, matching the offline gate's import assertion.

The request contract is exactly design §A.3: `action` ∈ {chat, approve}, `prompt` required non-empty for chat, `decision` ∈ {APPROVE, REJECT} + `interrupt_id` required for approve, `developer_id` default `dev-6`, `role` default `developer` and omitted on approve. `developer_id` is validated against `^dev-\d+$` and `role` against `ROLE_PROMPTS` keys, both falling back to defaults with a warning rather than erroring — a reasonable hardening beyond the plan. The response dict carries `status` ∈ {complete, pending_approval, error}, and semantic failures return an in-band HTTP-200 error envelope so the thin API forwards them rather than the platform 400'ing. The `build_and_attach` call is wrapped in `try/finally` that stops the GATEWAY MCP client, mirroring the CLI.

`build_and_attach` composes `build_agent(memory=True, session_id, developer_id, role, pending_write)` → `attach_gateway_tools` (GATEWAY only) → `attach_memory`, reusing the Task-5 seams verbatim with no second agent. `tool_mode` is read from `settings.tool_mode` (the Runtime env constant), never a per-request field, so both HITL legs rebuild an identical tool registry — the design §B.3 invariant.

### Thin FastAPI forwarder is genuinely thin

`api/app/routers/chat.py` forwards `{action, prompt, developer_id, role}` on chat and `{action, decision, interrupt_id, developer_id, proposal?}` on approve, then projects the reply onto `ChatResponse`/`ActionResult`. It holds no DB, no `openai`/`demo` branch, no `execute_proposed_action`, no second agent. A source scan confirms `api/` imports neither `agent` nor `langchain`. Auth is a fixed `dev-6`/`developer` identity with a single documented swap point for Cognito; SigV4 is enforced at the Function-URL edge via `AuthType=AWS_IAM`.

`runtime_client.invoke_runtime` builds the boto3 `bedrock-agentcore` client lazily and sets `agentRuntimeArn`, `runtimeSessionId`, `contentType`/`accept`, `payload`, and `runtimeUserId` only when Identity is enabled — all members confirmed against the installed `bedrock-agentcore/2024-02-28` model. Error mapping is correct and matches the design: a `BotoCoreError`/`ClientError` from the invoke raises HTTP 502, a Runtime `{"status":"error"}` becomes HTTP 200 with `success=false`, and the approve leg is never auto-retried (it could double-apply a write).

Approve omits `role` because the resume replays `pending_tool_execution` without a model call, so the role-selected system prompt is never re-consumed. If a future change re-invokes the model on the post-approve turn, `role` must be forwarded then — the code comments make this invariant explicit.

### HITL propose→approve without stdin; six writes gated; chain preserved

The chat leg returns `{status:"pending_approval", proposal:{**itr.reason, "interrupt_id": itr.id}}` when `result.stop_reason == "interrupt"`. This is confirmed against the strands interrupt model: `event.interrupt("write_approval", reason=build_proposal(...))` stores `Interrupt(id, name, reason, response)`, `result.interrupts[0].reason` is exactly the `build_proposal` dict, and `.id` is the resumable id — so the proposal is carried, not re-derived.

The approve leg rebuilds with `pending_write=True`, reads `agent._interrupt_state.interrupts[interrupt_id].reason` via `_restored_proposal` to recover the proposal from restored state, then resumes through `hitl.resume_once`, which builds `[{"interruptResponse": {"interruptId": interrupt_id, "response": decision}}]` — the exact shape the strands docstring documents. On an unknown/stale id, `_InterruptState.resume` raises `KeyError` (confirmed at `strands/interrupt.py` line 150); the handler catches it and returns `no_pending_interrupt` fail-safe, with nothing executed.

The `[SYSTEM]` breadcrumb now derives from restored interrupt state rather than a client echo (the prior-iteration finding 2 fix), so a faithful mahalo-dock frontend sending only `{session_id, interrupt_id, approved}` still gets the branch→commit→PR chain; the client `proposal` echo is a belt-and-braces fallback used only when restored state has no matching interrupt. `emit_system_signal` fires only on a closed APPROVE cycle (`stop_reason != "interrupt"`), and a chained write that re-interrupts on the same turn is re-proposed correctly. The six `WRITE_TOOL_NAMES` remain gated by the unchanged `WriteApprovalHook`, prefix-aware (`rsplit("___", 1)`) for both DIRECT and GATEWAY.

The `agent/chat.py` extraction is behavior-preserving: `_emit_system_signal` moved verbatim into `agent/hitl.py` (same three templates + generic fallback) and the CLI now calls the shared `emit_system_signal`/`resume_once`, preserving the deferred-flush timing (flush only when a resume returns a non-interrupt result).

### Session ids wire to Memory; pending_write flag is tightly scoped

Per-request session ids flow `context.session_id` → `build_and_attach(session_id)` → `build_agent(memory=True, session_id=...)` → `build_memory_session_spec` → the live `AgentCoreMemorySessionManager`, so invocation N+1 with the same id rehydrates the prior turn. The new `pending_write` flag threads `build_agent → build_memory_session_spec` and sets `filter_restored_tool_context=(not pending_write)`; the `MemorySessionSpec` field defaults to `True` and `build_memory_session_manager` now reads it from the spec instead of a hardcoded `True`. Defaults preserve Task-5 STM behavior for every non-approve build, which is why the Task-5 Memory tests stay green.

The `_build_bedrock_model` profile fix is the one with real failure consequences: it reads `botocore.session.Session().available_profiles` (config-file read, offline-safe, no creds) and passes `profile_name` only when `lava` is actually present, else builds a profile-less Session so boto3 resolves the execution-role chain in-container. This replaces the prior reliance on a construction-time `ProfileNotFound` that is in fact raised lazily inside the first model call — the earlier bug the design §A.6/Finding 1 identified. The container Dockerfile deliberately sets no `AWS_PROFILE`, so the absent-profile branch is what executes in-container.

### Identity WAT path landed, descoped-OFF per Decision D

The Runtime env sets `MAHALO_IDENTITY_ENABLED=false` and `MAHALO_IDENTITY_JIRA_PROVIDER=mahalo-jira-apikey`; the runtime stack adds no Identity policy to the exec role, so the MVP role claims nothing ungrounded. The enablement path is present and opt-in: the thin API forwards `runtimeUserId` only when `settings.identity_enabled`, and `MahaloApiStack` adds `grant_invoke_runtime_for_user` only under `identity_enabled`. This matches the design's AWS_IAM-phase descope with Cognito/`runtimeUserId` as the documented later flip — consistent with the user's "keep AWS_IAM for now, Cognito when I move to development mode."

### IaC is offline-synth-able; new code imports/constructs offline

`MahaloRuntimeStack` uses the L2 `agentcore.Runtime`; every method/attribute it relies on — `grant_invoke_runtime`, `grant_invoke_runtime_for_user`, `add_to_role_policy`, `agent_runtime_arn`, `LifecycleConfiguration`, `tracing_enabled`, `add_endpoint`, `AgentRuntimeArtifact.from_image_uri`/`from_asset` — is confirmed in the installed `aws_bedrockagentcore/__init__.py`. The artifact branch is flag-gated on `buildImage`/`MAHALO_BUILD_IMAGE`: the default branch builds a `CfnParameter` image URI (no `DockerImageAsset`, Docker-free synth), the deploy branch uses `from_asset(..., platform=LINUX_ARM64)`. `authorizer_configuration=None` yields the L2 AWS_IAM default; a Cognito branch raises `NotImplementedError` as an explicit stub. The `from_image_uri` branch adds explicit ECR-pull because that factory grants no IAM — closing the gap the design §E.1/Finding 2 flagged.

Cross-stack wiring in `app.py` passes `memory_stack=memory_identity` (which exposes `.memory` with `attr_memory_id`/`attr_memory_arn`) and no gateway stack, so the default is DIRECT tool mode with no gateway grant — matching the plan. `MahaloApiStack` packages `api/` as a plain asset offline (Docker-free) and bundles deps only on the deploy branch, wires `MAHALO_RUNTIME_ARN` from the Runtime construct, grants `InvokeAgentRuntime`, and exposes a Function URL with `AuthType=AWS_IAM`. The thin-API modules use `app.*` imports matching the Lambda asset root (the prior-iteration finding 1 fix), with a cold-start import guard test.

### Verification evidence and scope discipline

The coder's recorded evidence (plan "Verification record" + iteration-2 record) is internally consistent with the diff: agent 99/1, thin-API 15, infra-cdk 42/1, `cdk synth --all` exit 0 producing 8 templates Docker-free, tools-lambdas 94 unchanged, zero-LangChain confirmed. Per the judge-don't-verify instruction these were read, not re-run; the one narrow spot-check performed (the strands interrupt model and `KeyError` resume behavior, and the L2 CDK method surface) confirmed the specific claims the entrypoint and stacks depend on. `git status` shows the work is uncommitted with no coder commit, and the deploy runbook keeps the live HITL/Memory gates and container build as deferred operator steps — no fabricated live/deploy results.

</details>

<details>
<summary>File map</summary>

- `agent/runtime_app.py` (new) — `BedrockAgentCoreApp` entrypoint; chat/approve dispatch, validation, error envelope, breadcrumb-from-restored-state.
- `agent/runtime_session.py` (new) — `build_and_attach` per-invocation composition helper (build → gateway → memory).
- `agent/hitl.py` (new) — shared `resume_once` + `emit_system_signal`, extracted verbatim from the CLI.
- `agent/chat.py` (modified) — rewired to the shared HITL helpers; `_emit_system_signal` body removed.
- `agent/memory_client.py` (modified) — `pending_write`-driven `filter_restored_tool_context` on the Memory spec.
- `agent/strands_agent.py` (modified) — `_build_bedrock_model` profile-resolution fix; `build_agent` accepts/forwards `pending_write`.
- `agent/Dockerfile` (new) — ARM64 python:3.13-slim image; no `AWS_PROFILE`.
- `api/app/{main,config,models,auth,runtime_client}.py`, `api/app/routers/chat.py` (new) — thin FastAPI forwarder; no `agent`/LangChain import.
- `api/conftest.py`, `api/requirements.txt` (new) — asset-root import path; fastapi/mangum/boto3 pins.
- `infra-cdk/mahalo_infra/runtime_stack.py` (new) — L2 `agentcore.Runtime` + endpoint + exec-role grants, offline/deploy artifact branch.
- `infra-cdk/mahalo_infra/api_stack.py` (new) — Function-URL Lambda, `InvokeAgentRuntime` grant.
- `infra-cdk/app.py` (modified) — wires the two new stacks (DIRECT mode, no gateway ref).
- `infra-cdk/tests/test_runtime_stack.py`, `test_api_stack.py`, `agent/tests/test_hitl.py`, `test_runtime_app.py`, `api/tests/*` (new) — offline suites.
- `docs/.agents/tasks/task6-deploy-runbook.md` (new) — deferred operator deploy/live-gate runbook.

Full diff: `git diff` (tracked) + the untracked files above; working tree uncommitted.

</details>
