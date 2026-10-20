# Task 6 — Runtime hosting: implementation plan

Host the existing Strands agent on **Amazon Bedrock AgentCore Runtime** behind a
thin, stateless FastAPI forwarder. This plan sequences the APPROVED design
(`docs/.agents/tasks/task6-design.md`, grounded in
`docs/.agents/tasks/task6-investigation.md`) into small, dependency-ordered,
independently verifiable items. It does **not** re-decide architecture — the
design settled the L2 `agentcore.Runtime` IaC, the container packaging, the
`filter_restored_tool_context=False` HITL contract, the Identity descope under
AWS_IAM, and the FastAPI/Function-URL thin API; this plan only orders the work.

**Hard rules honored throughout.** Every file is **under
`D:/<USER>/LavaCode/AI/mahalo-agentcore`** (paths below are
workspace-relative, forward-slash). `mahalo-dock` is **READ ONLY** — used only as
a shape reference. **No `git commit`/`push`**. No worktree — work directly in the
workspace. **Everything is additive/opt-in**: the DIRECT/GATEWAY CLI and the
Task-5 Memory/Identity seams stay byte-for-byte unchanged except the one
behavior-preserving `agent/hitl.py` extraction (item 1). **Zero LangChain.** The
baseline must stay green: `agent 69 passed / 1 skipped`, `infra-cdk 31 passed` +
`cdk synth` exit 0, `tools-lambdas 94 passed`.

**Deploy policy.** The automated gate is **OFFLINE** — `cdk synth` and all
imports pass with no network and no AWS creds. Deploy (container build/push, live
HITL/Memory gates) is a **deferred operator step** (item 13); nothing here
auto-deploys.

## Verification commands (discovered during exploration)

- **Agent unit suite (offline):** from `agent/` venv —
  `python -m pytest agent/tests -q` (run from repo root with the `agent/.venv`
  active, as the existing suite does). Baseline: 69 passed, 1 skipped; this task
  adds new Runtime/HITL/thin-API-shared tests.
- **infra-cdk suite + synth (offline):** `cd infra-cdk; python -m pytest tests -q`
  then `cdk synth --all` (exit 0). Baseline infra-cdk: 31 passed.
- **tools-lambdas suite (offline, must stay untouched):**
  `python -m pytest tools-lambdas/tests -q` → 94 passed.
- **thin-API suite (new, offline):** `python -m pytest api/tests -q`.
- **LangChain guard:** grep for `langchain` across `agent/`, `api/`, `infra-cdk/`
  returns nothing.

Grep is never the verification of a behavior — it is only used for the explicit
"zero LangChain" guard. Every functional item below verifies via pytest / `cdk
synth`.

---

# Implementation Plan

- [ ] 1. Extract the HITL breadcrumb + resume logic into a shared `agent/hitl.py` (behavior-preserving) and rewire the CLI to it.
      Create `agent/hitl.py` exporting `emit_system_signal(agent, proposal)` (moved verbatim from `agent/chat.py::_emit_system_signal`, same three `[SYSTEM]` templates + generic fallback) and `resume_once(agent, interrupt_id: str, decision: str) -> AgentResult` (one `agent([{ "interruptResponse": {"interruptId": interrupt_id, "response": decision}}])` call returning the result; the single canonical resume helper). Rewire `agent/chat.py::_ask` to call `agent.hitl.resume_once` for the resume and `agent.hitl.emit_system_signal` for the deferred breadcrumb flush, preserving the exact deferred-flush timing (flush only when a resume returns a non-interrupt result). Delete the now-moved `_emit_system_signal` body from `chat.py` (or make it a thin re-export) so there is one implementation. This is a pure extraction — no behavior change.
      Files: `agent/hitl.py` (new), `agent/chat.py` (modify), `agent/tests/test_hitl.py` (new).
      Verify: `python -m pytest agent/tests -q` — existing HITL/`_ask` tests still pass (69/1 baseline held) and the new `test_hitl.py` asserts `emit_system_signal` emits the three chain breadcrumbs verbatim and `resume_once` builds the correct `interruptResponse` block.

- [ ] 2. Thread a per-session `pending_write` flag through the Memory spec so pending-write builds use `filter_restored_tool_context=False`.
      Make the three additive edits from design §C.4 in `agent/memory_client.py`: (a) add field `filter_restored_tool_context: bool = True` to the `MemorySessionSpec` dataclass (default `True` preserves Task-5 behavior); (b) change `build_memory_session_spec(session_id, actor_id, *, region, pending_write: bool = False)` to set `filter_restored_tool_context=(not pending_write)` on the returned spec; (c) in `build_memory_session_manager`, pass `filter_restored_tool_context=spec.filter_restored_tool_context` into `AgentCoreMemoryConfig(...)` instead of the hardcoded `True`. Then thread `pending_write` through the `build_agent(..., pending_write: bool = False)` signature in `agent/strands_agent.py` so it is forwarded into `build_memory_session_spec`. Default `False`/`True` everywhere keeps DIRECT/GATEWAY/CLI and Task-5 tests unchanged.
      Files: `agent/memory_client.py` (modify), `agent/strands_agent.py` (modify `build_agent` to accept + forward `pending_write`).
      Verify: `python -m pytest agent/tests/test_memory_mode.py -q` — existing Memory tests pass unchanged (default spec still `filter_restored_tool_context=True`); add an assertion that `build_memory_session_spec(..., pending_write=True)` yields a spec with `filter_restored_tool_context == False`.

- [ ] 3. Patch `_build_bedrock_model` to decide the AWS profile via `available_profiles` before constructing the boto3 Session (design §A.6 / Finding 1).
      In `agent/strands_agent.py::_build_bedrock_model`, replace the current `try/except boto3.Session(profile_name=...)` with an explicit resolution: read `botocore.session.Session().available_profiles` (offline-safe — reads the config file, no creds/network) and pass `profile_name=settings.aws_profile` only when that profile is actually present; otherwise build `boto3.Session(region_name=settings.aws_region)` with no profile so boto3 uses the default credential chain (= the Runtime execution role in-container). Keep the `botocore.config.Config` read/connect timeouts. This fixes the lazy-`ProfileNotFound` bug: the container (no `lava` profile) now resolves the default chain instead of raising inside the first model call.
      Files: `agent/strands_agent.py` (modify `_build_bedrock_model`).
      Verify: `python -m pytest agent/tests -q` plus a new test in `agent/tests/test_runtime_app.py` (added in item 5) that patches `botocore.session.Session.available_profiles` to a list WITHOUT `"lava"` and asserts (via a `boto3.Session` spy) `profile_name` is NOT passed, and WITH `"lava"` asserts it IS passed. The test must NOT mock `Session()` to raise — it exercises the real resolution path.

- [ ] 4. Create the Runtime entrypoint helper module `agent/runtime_session.py`.
      Add `build_and_attach(session_id, developer_id="dev-6", role="developer", *, pending_write=False)` that composes the Task-5 seams exactly as `agent/chat.py` does: `build_agent(memory=True, session_id=session_id, developer_id=developer_id, role=role, pending_write=pending_write)` → in GATEWAY mode call `attach_gateway_tools(result.agent, result.mcp_client)` → `attach_memory(result.agent, result.session_manager)`. Return the agent plus the GATEWAY teardown handle (the `mcp_client` or `None`) so the entrypoint can `stop(...)` it in `finally`. Export ONLY `build_and_attach` from this module (the resume/breadcrumb helpers live in `agent/hitl.py`, item 1). `tool_mode` is resolved from `settings.tool_mode` (the Runtime env constant), never a per-request field.
      Files: `agent/runtime_session.py` (new).
      Verify: `python -m pytest agent/tests/test_runtime_app.py -q` (item 5) — a test with `attach_memory`/`attach_gateway_tools`/`build_agent` mocked asserts `build_and_attach` calls them in order and returns the teardown handle; offline, no AWS.

- [ ] 5. Create the Runtime harness module `agent/runtime_app.py` with the `@app.entrypoint` request/response contract.
      Implement `BedrockAgentCoreApp()` + a two-parameter `@app.entrypoint def invoke(payload, context)` (2nd param MUST be named `context`), a plain sync function returning a JSON-able dict, and `if __name__ == "__main__": app.run()`. Implement the full §A.3–§A.5 contract: validate `payload` (`action` required; `prompt` required non-empty for `chat`; `decision`∈{APPROVE,REJECT} + `interrupt_id` required for `approve`; `developer_id` default `dev-6`; `role` default `developer`, omitted on approve); resolve `session_id = context.session_id or uuid4` and ECHO the resolved id back; on the `chat` leg call `build_and_attach(..., pending_write=False)`, `agent(prompt)` inside `try/finally` that stops the GATEWAY MCP client, and on `stop_reason=="interrupt"` return `{"status":"pending_approval","proposal": {**itr.reason, "interrupt_id": itr.id}, "response":"", "session_id":...}` (proposal is exactly `build_proposal`'s dict carried as `itr.reason`, plus the one `interrupt_id` key — no re-derivation); else return `{"status":"complete","response":str(result).strip(),"session_id":...}`; on the `approve` leg call `build_and_attach(..., pending_write=True)`, `resume_once(agent, interrupt_id, decision)`, and on a closed non-interrupt result emit the `[SYSTEM]` breadcrumb via `emit_system_signal` before returning `{"status":"complete",...}`. All semantic errors return `{"status":"error","error":{type,message}}` (HTTP 200 envelope). Import-time must be offline-safe (no AWS touch until the agent call). Reuse the edge-case handling of §"Edge cases" (unknown `interrupt_id` → `no_pending_interrupt`; missing header → generated+echoed uuid + warning; GATEWAY single-start discipline, no `with mcp_client:`).
      Files: `agent/runtime_app.py` (new), `agent/tests/test_runtime_app.py` (new).
      Verify: `python -m pytest agent/tests/test_runtime_app.py -q` — tests assert (with `build_and_attach` stubbed, no AWS): `import agent.runtime_app` + `BedrockAgentCoreApp()` + entrypoint registration succeed offline; chat-leg complete/pending_approval shaping; approve-leg resume + breadcrumb; every validation-failure path returns the error envelope; missing-header echoes a generated id. Also run `python -m pytest agent/tests -q` to confirm the 69/1 baseline + new tests all pass.

- [ ] 6. Add the container `agent/Dockerfile` (ARM64) and assert the harness-dep pins.
      Create `agent/Dockerfile`: `FROM --platform=linux/arm64 python:3.13-slim`, `WORKDIR /app`, copy+`pip install -r agent/requirements.txt`, copy `agent/`, `EXPOSE 8080`, `CMD ["python","-m","agent.runtime_app"]`. Do NOT set `AWS_PROFILE` (item 3 handles profile resolution). Confirm `agent/requirements.txt` already pins `bedrock-agentcore==1.24.1` and `strands-agents==1.61.1` (verified present — no edit needed unless a pin is missing); `uvicorn`/`starlette` come transitively from `bedrock-agentcore`'s base deps, so the image ships the ASGI harness even though the dev venv lacks `uvicorn`.
      Files: `agent/Dockerfile` (new); `agent/requirements.txt` (modify only if a required pin is absent).
      Verify: `python -m pytest agent/tests/test_runtime_app.py -q` — a regex test asserts `agent/requirements.txt` pins both `bedrock-agentcore==1.24.1` and `strands-agents==1.61.1` (stays green offline regardless of dev-venv state). Dockerfile is not built in the offline gate (deferred to item 13).

- [ ] 7. Scaffold the thin-API package skeleton under `api/` (config, models, auth) with no `agent/` import.
      Under `api/app/`: `config.py` (env `MAHALO_RUNTIME_ARN`, `AWS_REGION`, `MAHALO_IDENTITY_ENABLED`), `models.py` (pydantic `ChatRequest {message, session_id?, project_id?}`, `ChatResponse {response, proposal?, session_id, status}`, `ApprovalRequest {session_id, interrupt_id, approved}`, `ActionResult {success, message, session_id}` — mirror design §A.3), and `auth.py` (`current_identity` dependency returning fixed dev identity `developer_id="dev-6"`, `role="developer"` — the single swap point for Cognito later). The thin API must NOT import `agent/` or any Strands/tool code. Add `api/app/__init__.py` and `api/tests/__init__.py`. Remove the `api/.gitkeep` placeholder once real files exist.
      Files: `api/app/__init__.py`, `api/app/config.py`, `api/app/models.py`, `api/app/auth.py` (all new); delete `api/.gitkeep`.
      Verify: `python -m pytest api/tests -q` (with the import test from item 9) — `import api.app.models`/`config`/`auth` succeed offline with no creds; a grep confirms no `import agent` / `langchain` under `api/`.

- [ ] 8. Implement `api/app/runtime_client.py` — the `bedrock-agentcore` data-plane forwarder with lazy client construction.
      Implement `invoke_runtime(*, session_id, body, runtime_user_id=None) -> dict` wrapping `boto3.client("bedrock-agentcore").invoke_agent_runtime(agentRuntimeArn=cfg.runtime_arn, runtimeSessionId=session_id, contentType="application/json", accept="application/json", payload=json.dumps(body).encode()[, runtimeUserId=...])` and returning `json.loads(resp["response"].read())`. Build the boto3 client LAZILY (module-level accessor, not at import) so the module imports with no creds. `runtime_user_id` is only passed when Identity is enabled (off for the MVP).
      Files: `api/app/runtime_client.py` (new).
      Verify: `python -m pytest api/tests -q` — a test monkeypatches the lazy client so `invoke_runtime` round-trips a fake `{"response": <stream>}` and asserts the kwargs (session id, contentType/accept, payload JSON, no `runtimeUserId` when Identity off); `import api.app.runtime_client` succeeds offline without constructing a boto3 client.

- [ ] 9. Implement the thin-API routers (`POST /chat`, `POST /chat/approve`) and the FastAPI app + Mangum handler.
      `api/app/routers/chat.py`: `POST /chat` forwards `{action:"chat", prompt, developer_id, role}` with `session_id = req.session_id or uuid4` and maps the Runtime reply to `ChatResponse`; `POST /chat/approve` forwards `{action:"approve", decision: APPROVE|REJECT, interrupt_id, developer_id}` and maps to `ActionResult`. Neither endpoint forwards `role` on approve nor any `tool_mode` (design §B.3 invariant). `api/app/main.py`: build `FastAPI()`, include the router, expose `handler = Mangum(app)`. Apply the §B.6 error mapping (502 on invoke throw; 200 `success=false` on `{"status":"error"}`; 422 on pydantic validation; approve is never auto-retried). Pure forwarder — no DB, no business logic, no second agent.
      Files: `api/app/routers/__init__.py`, `api/app/routers/chat.py`, `api/app/main.py` (all new).
      Verify: `python -m pytest api/tests -q` — router tests with `invoke_runtime` mocked assert: `/chat` returns a proposal passthrough and a complete passthrough; `/chat/approve` maps success/error to `ActionResult`; validation errors yield 422; a Runtime-invoke exception yields 502. `import api.app.main` succeeds offline (lazy boto3).

- [ ] 10. Add `api/requirements.txt` and an offline import-safety test for the thin API.
      `api/requirements.txt` pins `fastapi`, `mangum`, `pydantic`, and `boto3`/`botocore` new enough for the `bedrock-agentcore` 2024-02-28 data-plane model (NO langchain, NO agent). Add `api/tests/test_api.py` consolidating the import-safety + mocked round-trip assertions referenced by items 7–9 (if not already split across those items' test files).
      Files: `api/requirements.txt` (new), `api/tests/test_api.py` (new if needed).
      Verify: `python -m pytest api/tests -q` passes; grep confirms `langchain` absent under `api/`.

- [ ] 11. Add the L2 `MahaloRuntimeStack` in `infra-cdk/mahalo_infra/runtime_stack.py` with the offline/`from_image_uri` vs deploy/`from_asset` artifact branch.
      Create `MahaloRuntimeStack(Stack)` using `from aws_cdk import aws_bedrockagentcore as agentcore` (same alias as `gateway_stack.py`). Artifact branch gated by `self.node.try_get_context("buildImage") or os.environ.get("MAHALO_BUILD_IMAGE")=="1"`: deploy branch → `agentcore.AgentRuntimeArtifact.from_asset("..", file="agent/Dockerfile", platform=ecr_assets.Platform.LINUX_ARM64)`; offline/default branch → `agentcore.AgentRuntimeArtifact.from_image_uri(CfnParameter(self,"AgentImageUri",default="000000000000.dkr.ecr.us-east-1.amazonaws.com/placeholder:latest").value_as_string)` (constructs NO `DockerImageAsset` so synth is Docker-free). Create `agentcore.Runtime(self,"MahaloRuntime", runtime_name="mahalo_agent_runtime", agent_runtime_artifact=<branch>, environment_variables=<item 12 env>, tracing_enabled=True, lifecycle_configuration=...(idle_runtime_session_timeout=Duration.minutes(15), max_lifetime=Duration.hours(8)))` with `authorizer_configuration` OMITTED (L2 default `.iam()` = AWS_IAM) and `execution_role` OMITTED (L2 auto-creates). Add app-level grants onto `runtime.role`: Bedrock `InvokeModel`/`InvokeModelWithResponseStream` on the Sonnet 4.5 inference-profile + regional model ARNs; Memory `CreateEvent`/`ListEvents`/`GetEvent`/`RetrieveMemoryRecords` scoped to the `CfnMemory` ARN; Gateway invoke (GATEWAY mode). On the `from_image_uri` branch ONLY, add an explicit ECR-pull statement (`ecr:GetAuthorizationToken` on `*`, `ecr:BatchGetImage`/`ecr:GetDownloadUrlForLayer` on the repo ARN) since `from_image_uri` grants no IAM; on `from_asset` the artifact wires ECR pull. NO Identity policy in the MVP role (Identity off). Add a Cognito branch stub (`inbound = try_get_context("inboundAuth") or "AWS_IAM"`; only when `"COGNITO"` build `RuntimeAuthorizerConfiguration.using_cognito(...)`). Then `endpoint = runtime.add_endpoint("default")` and `CfnOutput(self,"RuntimeArn", value=runtime.agent_runtime_arn)`. Cross-stack: accept the `MahaloMemoryIdentityStack` (for `MAHALO_MEMORY_ID` + Memory ARN) and the Gateway MCP URL by direct construct reference via `app.py`.
      Files: `infra-cdk/mahalo_infra/runtime_stack.py` (new).
      Verify: `cd infra-cdk; python -m pytest tests/test_runtime_stack.py -q` (item 14) and `cdk synth --all` exit 0 with no Docker invocation on the default branch.

- [ ] 12. Define the Runtime env-var map and wire `MahaloRuntimeStack` (+ the thin-API Lambda stack) into `infra-cdk/app.py`.
      Build the `environment_variables` dict for the L2 `Runtime`: `MAHALO_TOOL_MODE`, `MAHALO_GATEWAY_MCP_URL` (GATEWAY), `MAHALO_MEMORY_ENABLED="true"`, `MAHALO_MEMORY_ID` (from the Memory CfnOutput/construct), `MAHALO_IDENTITY_ENABLED="false"` (MVP), `MAHALO_IDENTITY_JIRA_PROVIDER="mahalo-jira-apikey"`, `BEDROCK_MODEL_ID`, `AWS_REGION`, and the four mock `*_URL`s. Deliberately DO NOT set `AWS_PROFILE`. Add `MahaloApiStack` (`infra-cdk/mahalo_infra/api_stack.py`): a Function-URL Lambda (`python3.13`, handler `app.main.handler`) for `api/`, with the deploy-branch `BundlingOptions` (`pip install -r requirements.txt -t /asset-output && cp -r app /asset-output` in the `PYTHON_3_13.bundling_image`) and an offline-branch pre-built-deps-layer / `CfnParameter`-layer path so synth is Docker-free; `fn.add_function_url(auth_type=FunctionUrlAuthType.AWS_IAM)`; grant the Lambda role `bedrock-agentcore:InvokeAgentRuntime` on the Runtime ARN; env `MAHALO_RUNTIME_ARN` from the `RuntimeArn` output; `CfnOutput RuntimeApiUrl`. Wire both new stacks into `infra-cdk/app.py` alongside the existing six (direct construct references, no `Fn.import_value`, mirroring how `MahaloMemoryIdentityStack` was added).
      Files: `infra-cdk/mahalo_infra/api_stack.py` (new), `infra-cdk/app.py` (modify).
      Verify: `cd infra-cdk; cdk synth --all` exit 0 producing the two new templates with no Docker call on the default branch; `python -m pytest tests -q` (existing 31 + new stay green).

- [ ] 13. Add the infra-cdk synth/assertion tests for the new stacks (offline gate).
      Add `infra-cdk/tests/test_runtime_stack.py` (and API assertions, co-located or in `test_api_stack.py`) asserting, with the flag UNSET (offline branch): (1) `app.synth()` exit 0 and NO `DockerImageAsset` / image asset staged, and the `AWS::BedrockAgentCore::Runtime` references the `AgentImageUri` parameter; (2) one `AWS::BedrockAgentCore::Runtime` with NO JWT authorizer block (AWS_IAM default), an auto-created exec role carrying the Bedrock/Memory/Gateway statements (plus the explicit ECR-pull statement on the `from_image_uri` branch), the expected `EnvironmentVariables`, and one `AWS::BedrockAgentCore::RuntimeEndpoint` from `add_endpoint("default")`; (3) the API Lambda synthesizes Docker-free on the offline branch with a Function URL `AuthType=AWS_IAM` and the `InvokeAgentRuntime` grant. Mark the `from_asset`/`BundlingOptions` deploy-branch tests `skip`/`xfail` when Docker is unavailable so the offline gate never breaks.
      Files: `infra-cdk/tests/test_runtime_stack.py` (new), `infra-cdk/tests/test_api_stack.py` (new or folded into the former).
      Verify: `cd infra-cdk; python -m pytest tests -q` — all pass (31 baseline + new); `cdk synth --all` exit 0.

- [ ] 14. Full offline-gate sweep + zero-LangChain confirmation.
      Run the complete baseline to confirm everything composes and nothing regressed: the agent suite (69/1 + new Runtime/HITL tests), the thin-API suite, the infra-cdk suite + `cdk synth --all`, the tools-lambdas suite (must be exactly 94, untouched), and the LangChain grep guard. Clean up any temporary files created during verification.
      Files: none (verification only).
      Verify: `python -m pytest agent/tests -q` (69/1 + new all pass); `python -m pytest api/tests -q` (all pass); `cd infra-cdk; python -m pytest tests -q` (31 + new) and `cdk synth --all` (exit 0); `python -m pytest tools-lambdas/tests -q` (94 passed); grep for `langchain` across `agent/`, `api/`, `infra-cdk/` returns nothing.

- [ ] 15. Write the deferred operator deploy runbook into `docs/.agents/tasks/task6-deploy-runbook.md`.
      Capture design §E.5 verbatim-in-intent as an operator-run, billable, NOT-auto-run checklist: `aws sso login --profile lava`; `$env:MAHALO_BUILD_IMAGE="1"`; `cdk deploy MahaloMemoryIdentityStack MahaloGatewayStack MahaloMock*Stack --profile lava` (outputs first); `cdk deploy MahaloRuntimeStack --profile lava` (builds+pushes the ARM64 image, auto-role, `Runtime`+`add_endpoint`; note `RuntimeArn`); `cdk deploy MahaloApiStack --profile lava` (note `RuntimeApiUrl`); then the §C.5 HITL live gate (chat→proposal with no write; approve→exactly one write, no `ValidationException`; reject→nothing written; branch→commit→PR chain across three approves with no re-proposal) and the two-invocation Memory persist/reload check (same session id across two `POST /chat`). Document that the Identity-brokered `jira_create_story` write is DESCOPED from the AWS_IAM MVP (`MAHALO_IDENTITY_ENABLED=false`; static-key write still works), and the enablement path (`runtimeUserId` + `InvokeAgentRuntimeForUser` + the grounded `GetResourceApiKey`/`GetWorkloadAccessTokenForUserId` role grants) is a documented config flip. Record the OPEN VERIFICATION ITEM: measure a representative `github_commit_files` invocation end-to-end against the synchronous `InvokeAgentRuntime` budget and switch to the SSE entrypoint if at risk. End with `cdk destroy MahaloApiStack MahaloRuntimeStack ...` to stop spend.
      Files: `docs/.agents/tasks/task6-deploy-runbook.md` (new).
      Verify: this is a docs deliverable — confirm it exists and covers deploy order, the §C.5 HITL gate, the Memory persist/reload check, the Identity descope + enablement flip, the invocation-budget measurement item, and teardown. No build command applies.

---

## Dependency notes

- Item 1 (`agent/hitl.py`) is a prerequisite for item 5 (the entrypoint imports
  `emit_system_signal`/`resume_once`).
- Item 2 (`pending_write` through the Memory spec) and item 3 (profile fix) are
  prerequisites for item 4/5 (the entrypoint builds with `pending_write` and runs
  Bedrock in-container).
- Item 4 (`build_and_attach`) is a prerequisite for item 5 (entrypoint).
- Items 7→8→9→10 are the thin-API chain (skeleton → forwarder → routers →
  requirements), independent of the agent-side items 1–6 (the thin API never
  imports `agent/`).
- Items 11→12→13 are the IaC chain; item 11 references the Dockerfile from item 6
  (deploy branch only) and the `api/` package from items 7–10 (Lambda asset); the
  offline branch needs neither to synth.
- Items 14 (full sweep) and 15 (runbook) come last.

Each item leaves the codebase in a buildable, test-green state: the additive new
modules do not alter existing behavior until wired, and the one existing-file
change that could regress (item 1's extraction, item 2/3's `strands_agent.py`
edits) is guarded by the unchanged Task-1/2/5 agent suite.

## Assumptions / gaps noted (not blockers)

- The design leaves the warm-VM session cache (`MAHALO_RUNTIME_SESSION_CACHE`) and
  the SSE streaming entrypoint OUT of the MVP. This plan follows that: neither is
  implemented; both remain documented opt-in follow-ups. If the operator deploy
  (item 15) measures a commit at risk of the synchronous invocation budget, the
  SSE entrypoint becomes a fast-follow — not part of this task.
- Identity is OFF for the AWS_IAM MVP; the enablement wiring (thin-API
  `runtimeUserId`, the `InvokeAgentRuntimeForUser` + `GetResourceApiKey` +
  `GetWorkloadAccessTokenForUserId` grants) is designed and documented (item 15)
  but NOT provisioned in the MVP role, so the offline gate claims nothing
  ungrounded. Turning it on is a later config flip, not a redesign.
- Exact Sonnet 4.5 inference-profile ARN construction for the Bedrock grant (item
  11) follows the account/region already pinned in `infra-cdk/app.py`
  (`<AWS_ACCOUNT_ID>` / `us-east-1`) and the `BEDROCK_MODEL_ID` default; the regional
  foundation-model ARNs the cross-region profile fans out to are included as the
  design's §5.4 least-privilege set specifies.

---

## Verification record (offline gate — what was run and the results)

Recorded so the reviewer need not re-run the suites. All runs were in a CLEAN env
with **no `MAHALO_*` env vars set** (PowerShell: the `MAHALO_*` vars were removed
before each run, because a few Task-5 tests read ambient env and would otherwise
misreport). NO deploy was run; NO live/deploy results are fabricated — the live
HITL/Memory gates remain the deferred operator step in `task6-deploy-runbook.md`.

- **Agent suite (offline, clean env):**
  `& "agent/.venv/Scripts/python.exe" -m pytest agent -q`
  → **98 passed, 1 skipped**. This holds the clean-env baseline (69 passed /
  1 skipped) PLUS 29 new Task-6 agent tests: `agent/tests/test_hitl.py` (6 — the
  three chain breadcrumbs + resume block), `agent/tests/test_runtime_app.py` (23 —
  entrypoint chat/approve shaping, all validation envelopes, missing-header echo,
  `build_and_attach` order DIRECT+GATEWAY, the REAL `_build_bedrock_model`
  profile-resolution path (profile absent ⇒ no `profile_name`; present ⇒ passed —
  never a forced `Session` raise), and the `requirements.txt` harness-dep pins).
  The 1 skip is the pre-existing live integration test (tunnel down).

- **Thin-API suite (offline):**
  `& "api/.venv/Scripts/python.exe" -m pytest api/tests -q`
  → **13 passed**. Covers: offline imports (lazy boto3 client not constructed at
  import), no `agent`/`langchain` imports pulled into the edge,
  `invoke_runtime` round-trip kwargs (session id, contentType/accept, payload,
  no `runtimeUserId` when Identity off; set when provided), `/chat` proposal +
  complete passthrough, `/chat/approve` success→`ActionResult`, Runtime-error→
  `success=false` (HTTP 200), invoke-exception→HTTP 502, pydantic validation→422,
  and a source-tree guard that no import line references `langchain`/`agent`.
  (`api/.venv` was created from the agent venv's Python and
  `pip install -r api/requirements.txt pytest httpx`; both `api/.venv` and
  `infra-cdk/cdk.out` are gitignored.)

- **infra-cdk suite (offline):**
  `cd infra-cdk; & ".venv/Scripts/python.exe" -m pytest tests -q`
  → **42 passed, 1 skipped** (31 baseline + 11 new, minus the 1 Docker-only
  `from_asset` test which `skip`s when Docker is unavailable). New:
  `tests/test_runtime_stack.py` (one L2 `AWS::BedrockAgentCore::Runtime` + one
  `RuntimeEndpoint`, no JWT authorizer = AWS_IAM default, Runtime references the
  `AgentImageUri` parameter, NO container-image asset staged on the offline
  branch, env vars incl. `MAHALO_IDENTITY_ENABLED=false` and NO `AWS_PROFILE`,
  exec-role Bedrock/Memory + explicit ECR-pull statements, `RuntimeArn` output);
  `tests/test_api_stack.py` (one python3.13 Lambda `app.main.handler`, Function
  URL `AuthType=AWS_IAM`, `MAHALO_RUNTIME_ARN` env + `RuntimeApiUrl` output,
  Lambda role has `bedrock-agentcore:InvokeAgentRuntime` and NOT
  `InvokeAgentRuntimeForUser` in the MVP).

- **cdk synth --all (offline, Docker-free):**
  `cd infra-cdk; cdk synth --all` → **exit 0**, producing **8** templates
  (the six prior + `MahaloRuntimeStack` + `MahaloApiStack`). CDK emitted an INFO
  annotation that the container URI is an unresolved token validated at deploy
  time (the `from_image_uri` parameter branch) — expected, not an error. No Docker
  was invoked (default/offline branch).

- **tools-lambdas suite (offline, untouched):**
  `python -m pytest tools-lambdas/tests -q` → **94 passed** (unchanged).

- **Zero LangChain:** a grep for `langchain` across `agent/`, `api/`, `infra-cdk/`
  (excluding `.venv`) returns only prose/guard references in the thin-API
  docstrings and the `test_api.py` guard itself (and the gitignored `cdk.out`
  staged asset copy of `api/`) — **no actual LangChain import anywhere**.

Note on IaC runtime: the L2 `agentcore.Runtime` jsii synth is slow on this host
(the runtime-stack suite ~161s, api-stack ~230s, full infra suite ~228s); all
green. The ARM64 Runtime image build and the thin-API Lambda dependency bundling
are Docker steps deferred to the operator (`task6-deploy-runbook.md`); the offline
gate never builds them.

---

## Verification record — iteration 2 (code-review fixes)

This iteration addressed the three findings in
`docs/.agents/tasks/task6-code-review.json` (verdict CHANGES_REQUESTED):

- **Finding 1 (blocking) — thin-API Lambda import path.** The `api/app/*` modules
  used absolute `from api.app.*` imports while the Lambda ships with asset root
  `api/` and handler `app.main.handler` — no `api` package exists at runtime, so
  the deployed function would `ModuleNotFoundError: api` on cold start. **Fix:**
  rebased every intra-package import to `app.*` (`main.py`, `runtime_client.py`,
  `routers/chat.py`); deleted `api/__init__.py` so `app` is the top-level package
  (matching the asset root); added `api/conftest.py` to put `api/` on `sys.path`
  so the unit suite imports `app.*` via the SAME path the Lambda uses; added
  `test_imports_from_asset_root_only` that imports `app.main` with only the asset
  root on `sys.path` (reproducing cold-start resolution the synth gate cannot
  exercise). The CDK handler stays `app.main.handler` (unchanged, already correct).

- **Finding 2 (non-blocking) — breadcrumb depended on client echo.** The approve
  leg emitted the `[SYSTEM]` chain breadcrumb only when the client echoed
  `payload["proposal"]` back — a coupling the design/mahalo-dock frontend shape
  did not carry, so a faithful client dropped the breadcrumb and branch→commit→PR
  re-proposed. **Fix (behavior-robust, design-intent-preserving):**
  `agent/runtime_app.py::_restored_proposal` now derives the proposal from the
  RESTORED interrupt state (`agent._interrupt_state.interrupts[interrupt_id].reason`,
  which is exactly the chat-leg `build_proposal` dict), so the breadcrumb fires
  regardless of client cooperation. The optional `payload["proposal"]` echo is
  retained only as a belt-and-braces fallback (used iff restored state has no
  matching pending interrupt). New tests:
  `test_approve_emits_breadcrumb_from_restored_state` (no client echo) and
  `test_approve_emits_breadcrumb_from_client_echo_fallback`.

- **Finding 3 (nit) — approve surface widened beyond design §B.3.** Folded into
  finding 2: `ApprovalRequest.proposal` is documented as an OPTIONAL belt-and-
  braces echo (not required for correctness) in `api/app/models.py`,
  `api/app/routers/chat.py`, and design §B.3 (updated to
  `ApprovalRequest {session_id, interrupt_id, approved, proposal?}` with the
  restored-state derivation note). `api/tests/test_api.py::test_approve_forwards_proposal_echo`
  asserts the forward is verbatim and the omit-path is supported.

All runs again in a CLEAN env with no `MAHALO_*` env vars set; NO deploy, NO
fabricated live results.

- **Agent suite:** `& "agent/.venv/Scripts/python.exe" -m pytest agent -q`
  → **99 passed, 1 skipped** (clean-env baseline 69/1 held + Task-6 agent tests;
  net +1 vs iteration 1's 98/1 from the two new restored/fallback breadcrumb
  tests replacing one). The 1 skip is the pre-existing live integration test.
- **Thin-API suite:** `& "api/.venv/Scripts/python.exe" -m pytest api/tests -q`
  → **15 passed** (iteration-1 13 + the asset-root cold-start import guard + the
  proposal-echo forward test).
- **infra-cdk suite:** `cd infra-cdk; & ".venv/Scripts/python.exe" -m pytest tests -q`
  → **42 passed, 1 skipped** (unchanged; the Docker-only `from_asset` test skips).
- **cdk synth --all:** `cd infra-cdk; cdk synth --all` → **exit 0**, 8 templates,
  Docker-free (only the expected INFO annotation about the unresolved container
  URI token on the `from_image_uri` offline branch).
- **tools-lambdas suite:** `& "tools-lambdas/.venv/Scripts/python.exe" -m pytest
  tools-lambdas/tests -q` → **94 passed** (untouched).
- **Zero LangChain:** grep for `langchain` across `agent/`, `api/`, `infra-cdk/`
  (excluding `.venv` and the gitignored `cdk.out` staged copies) returns only
  prose/guard references — no actual import.
