# Task 6 — Runtime hosting: investigation (READ installed source; no code changes)

Goal of this doc: nail down the REAL AgentCore Runtime packaging / entrypoint /
deploy contract, and how the Task-5 modes (DIRECT/GATEWAY tools, Memory,
Identity) and the Task-2/4 HITL interrupt behave INSIDE the Runtime execution
model — all cited against installed source, not guessed.

Everything below is verified against:

- `bedrock-agentcore 1.24.1` — `agent/.venv/Lib/site-packages/bedrock_agentcore/`
- `strands-agents 1.61.1` — `agent/.venv/Lib/site-packages/strands/`
- `aws-cdk-lib 2.273.0` — `infra-cdk/.venv/Lib/site-packages/aws_cdk/aws_bedrockagentcore/`
- mahalo-dock thin-API reference (READ ONLY): `mahalo-dock/backend/app/routers/chat.py`,
  `.../agent/session.py`

File:line citations use the installed-package paths above (relative to the venv
`site-packages`).

---

## TL;DR / key decisions this unblocks

1. **Runtime contract is a Starlette ASGI app** you build with
   `BedrockAgentCoreApp` and decorate one function with `@app.entrypoint`. The
   platform POSTs to `/invocations`; health is `GET /ping`. Entry signature is
   `fn(payload)` or `fn(payload, context)` where `payload` is the raw request
   JSON and `context` is a `RequestContext` carrying `session_id`. Streaming is
   automatic when the entrypoint returns a (sync or async) generator → SSE.
   (`runtime/app.py`, `runtime/context.py`, `runtime/models.py`.)

2. **Session id arrives as an HTTP header** `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`
   and is surfaced on `context.session_id`. The **platform does NOT manage
   per-session agent lifecycle inside your process** — it routes same-session
   requests to the same microVM, but your entrypoint must map the session id
   onto the Strands/Memory `session_id`/`actor_id`. This is exactly the
   `build_agent(..., memory=True, session_id=...)` + `attach_memory` seam from
   Task 5. (`runtime/app.py::_build_request_context`.)

3. **HITL CAN round-trip across Runtime invocations** — the Strands interrupt
   state (including the pending open tool-use) is serialized into the session
   store by the session manager and restored on the next invocation. So the
   propose/approve gate becomes a **two-call protocol over the request/response
   boundary** (call 1 returns the proposal, call 2 sends the decision), which
   maps 1:1 onto mahalo-dock's existing `POST /chat` → `POST /chat/approve`
   shape. There is one real sharp edge (interrupt-state vs
   `filter_restored_tool_context`) documented in §3 that is an open design
   decision. It is NOT a blocker.

4. **Identity on Runtime is simpler than local** — the platform mints a Workload
   Access Token and delivers it in request context; `@requires_api_key` /
   `@requires_access_token` read it automatically (no `.agentcore.json`
   local-dev dance). (`identity/auth.py`, `runtime/app.py`,
   `runtime/context.py`.)

5. **IaC: `aws-cdk-lib 2.273.0` DOES ship a Runtime L1** — `CfnRuntime` +
   `CfnRuntimeEndpoint` under `aws_cdk.aws_bedrockagentcore`. It accepts EITHER a
   container image (ECR `container_uri`) OR managed code (`CodeConfiguration` =
   S3 zip + entry_point + runtime). The **starter-toolkit is NOT installed**, so
   our deploy path is CDK `CfnRuntime` — and because our agent needs arbitrary
   deps + a non-trivial process, the **container path is the right choice**,
   which means a **Dockerfile + ECR image build** is required in Task 6.

---

## 1. AgentCore Runtime contract — packaging, entrypoint, payload, streaming

### 1.1 The runtime harness object

`bedrock_agentcore.runtime.BedrockAgentCoreApp` is the harness
(`runtime/__init__.py` exports it; defined in `runtime/app.py`). It **subclasses
`starlette.applications.Starlette`** and in `__init__` registers exactly three
routes (`runtime/app.py`, `BedrockAgentCoreApp.__init__`):

```python
routes = [
    Route("/invocations", self._handle_invocation, methods=["POST"]),
    Route("/ping", self._handle_ping, methods=["GET"]),
    WebSocketRoute("/ws", self._handle_websocket),
]
```

So the container contract the managed Runtime expects is: an HTTP server that
answers **`POST /invocations`** (the agent call) and **`GET /ping`** (health),
plus an optional **`/ws`** WebSocket. `app.run()` serves it with uvicorn on port
**8080**, binding `0.0.0.0` when it detects a container (`/.dockerenv` or
`DOCKER_CONTAINER` env). (`runtime/app.py::run`.)

### 1.2 The entrypoint decorator and its EXACT signature

`@app.entrypoint` registers the one handler under `handlers["main"]`
(`runtime/app.py::entrypoint`). The platform's POST body is passed to it
**unchanged** (the decorator docstring: "Invocation payloads are passed to the
registered function unchanged. Applications should validate input before
forwarding it to an agent framework").

The harness decides whether to pass the context by **introspecting the
handler's 2nd parameter name** (`runtime/app.py::_takes_context`):

```python
def _takes_context(self, handler):
    params = list(inspect.signature(handler).parameters.keys())
    return len(params) >= 2 and params[1] == "context"
```

So the two valid entrypoint signatures are:

```python
@app.entrypoint
def invoke(payload):                      # payload only
    ...

@app.entrypoint
def invoke(payload, context):             # the 2nd param MUST be named "context"
    ...
```

- `payload` = `await request.json()` — the raw parsed JSON body. The harness does
  **no schema shaping**; whatever the caller POSTed is what you get
  (`runtime/app.py::_handle_invocation`). A malformed body yields HTTP 400 before
  your handler runs; our handler owns all other validation.
- `context` = a `RequestContext` pydantic model (`runtime/context.py`):
  `session_id: Optional[str]`, `request_headers: Optional[Dict[str,str]]`,
  `request` (the raw Starlette request).

**How the user prompt + session id arrive:** there is no fixed prompt schema —
by convention agents read `payload["prompt"]` (or similar) for the user text.
The **session id is NOT in the payload**; it is an HTTP header lifted into
`context.session_id` (see §2). So our entrypoint reads the prompt from the JSON
body and the session id from the context.

### 1.3 Sync vs async vs streaming

`_invoke_handler` (`runtime/app.py`) dispatches on handler type:

- **async generator** → bridged to a sync generator over a dedicated worker loop
  and returned as a Starlette `StreamingResponse` with `media_type=
  "text/event-stream"`; each yielded value is serialized to an SSE frame
  `data: <json>\n\n` (`_convert_to_sse`, `_stream_with_error_handling`).
- **sync generator** → same SSE streaming path (`_sync_stream_with_error_handling`).
- **plain async fn** → run on the worker event loop.
- **plain sync fn** → run in a threadpool (`run_in_threadpool`).

The worker-loop design exists so a blocking handler never starves `GET /ping`
(`runtime/app.py::_run_worker_loop` comments). If the handler returns a plain
value (not a generator), the harness serializes it to a single
`application/json` response via `_safe_serialize_to_json_string` (progressive
fallback: `json.dumps` → `convert_complex_objects` → `str`).

**Implication for us:** our agent call (`agent(message)`) is a blocking sync
call, so the simplest correct entrypoint is a **plain sync function returning a
JSON-able dict** (Runtime runs it in the threadpool; `/ping` stays healthy).
Streaming (SSE token-by-token) is available later by switching the entrypoint to
an async generator over `agent.stream_async(...)`, but it is NOT required for the
thin-API MVP and is explicitly out of scope unless we want it.

### 1.4 Health / ping

`GET /ping` returns `{"status": "Healthy"|"HealthyBusy", ...}`
(`runtime/app.py::_handle_ping`, `PingStatus` in `runtime/models.py`). Status is
automatic (HealthyBusy while `@async_task`s run) or can be forced. For a
synchronous agent we can rely on the default Healthy; no custom `@app.ping`
handler is needed for the MVP.

### 1.5 Observability / env the platform injects

The harness reads `OTEL_RESOURCE_ATTRIBUTES` (`cloud.resource_id` → the runtime
ARN) for tracing/config-bundle selection (`runtime/app.py::_parse_runtime_arn`).
That env is injected by the managed platform; we don't set it. Logs are emitted
as Lambda-style JSON with `requestId`/`sessionId`
(`runtime/app.py::RequestContextFormatter`).

---

## 2. Sessions on Runtime — how a session id propagates and wires to Memory

### 2.1 Where the session id comes from

`_build_request_context` (`runtime/app.py`) reads it from a header:

```python
session_id = headers.get(SESSION_HEADER)   # SESSION_HEADER in runtime/models.py
BedrockAgentCoreContext.set_request_context(request_id, session_id)
...
return RequestContext(session_id=session_id, request_headers=..., request=request)
```

`runtime/models.py`:

```python
SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
REQUEST_ID_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Request-Id"
```

So the **caller of the Runtime** (our thin API, via
`bedrock-agentcore:InvokeAgentRuntime`) supplies the session id, and it surfaces
as `context.session_id`. The id is also stashed on a `ContextVar`
(`BedrockAgentCoreContext.get_session_id()`), so code deep in the call tree can
read it without threading it through.

### 2.2 Does the Runtime manage session lifecycle? (confirmed: NO, not inside your process)

The managed Runtime uses the session id for **routing/affinity** (same session →
same warm microVM) and session TTL at the platform level, but inside the process
the harness does exactly ONE thing with it: puts it on the context/ContextVar.
It never constructs an agent, never maps it to Memory, never persists anything.
**The entrypoint owns** turning `context.session_id` into a Strands `session_id`
+ Memory `actor_id` and (re)building/attaching the agent. Verified: the only
session-id touches in `runtime/app.py` are the two `BedrockAgentCoreContext`
setters and the `RequestContext` field — there is no agent/memory wiring in the
harness.

### 2.3 The convergence with Task-5 Memory

Task 5 already built the exact seam:
`build_agent(memory=True, session_id=..., developer_id=...)` →
`BuildResult.session_manager` (an offline `MemorySessionSpec`), then
`attach_memory(agent, spec)` constructs the live
`AgentCoreMemorySessionManager` (`agent/strands_agent.py`, `agent/memory_client.py`).
The mapping on Runtime is:

| Runtime concept | Strands/Memory concept | Source of truth |
|---|---|---|
| `context.session_id` (header) | `AgentCoreMemoryConfig.session_id` (groups one conversation) | header → entrypoint → `build_agent(session_id=...)` |
| the logged-in user | `AgentCoreMemoryConfig.actor_id` | from the thin-API JWT / payload → `build_agent(developer_id=...)` |
| `MAHALO_MEMORY_ID` | `AgentCoreMemoryConfig.memory_id` | Runtime env var (CfnMemory output) |

How history persists across invocations (confirmed in installed source): the
memory manager subclasses `RepositorySessionManager` and implements
`create_message`/`list_messages`/`create_agent`/`read_agent` against AgentCore
Memory events (`bedrock_agentcore/memory/integrations/strands/session_manager.py`).
`AgentCoreMemorySessionManager.register_hooks` wires
`MessageAddedEvent → append_message` (each turn is written immediately because
Task-5 uses `batch_size=1`) and `AgentInitializedEvent → initialize` (restores
on construction). So invocation N+1, built with the SAME `session_id`+`actor_id`,
rehydrates the prior conversation from Memory. This is exactly what the Task-5
operator runbook's two-invocation persist/reload check exercises — Task 6 is
where real per-request session ids flow in.

**Entrypoint shape for Memory (recommended):** build + attach the agent **per
invocation** from `context.session_id`. The managed Runtime keeps the microVM
warm, but we must NOT assume a cached in-process agent is the right one for an
arbitrary incoming session id (routing affinity is best-effort and a warm VM may
serve a new session after TTL). Rebuilding per request is cheap (model
construction is lazy/offline per Task-1 notes) and the only live cost is the
`attach_memory` rehydrate (one `ListEvents`), which is inherent to resuming a
session anyway. A per-session in-process cache is a possible optimization but
should be keyed on `context.session_id` and is NOT required for correctness.

### 2.4 Memory ListEvents at construction — still the single AWS touch

Unchanged from Task 5: `AgentCoreMemorySessionManager.__init__` →
`RepositorySessionManager.__init__` → `read_session` → `list_events` is a live
read (`memory/integrations/strands/session_manager.py::read_session`,
`strands/session/repository_session_manager.py::__init__`). On Runtime that is
fine (we are online and have creds via the execution role), so Task 6 can call
`attach_memory` straight from the entrypoint; the offline-safety gymnastics only
mattered for the local offline gate.

---

## 3. HITL under Runtime — does the interrupt round-trip over request/response?

This is the single highest-risk question. Answer from installed source:
**Yes, the native Strands interrupt is designed to round-trip through a session
store, so it survives the Runtime request/response boundary — becoming a
two-call propose→approve protocol. There is one real caveat (below) that is an
open design decision, not a blocker.**

### 3.1 How the interrupt is modeled (recap, verified)

`agent/approval.py::WriteApprovalHook` calls `event.interrupt("write_approval",
reason=proposal)` in `BeforeToolCallEvent`. In `strands/types/interrupt.py` the
first `interrupt()` raises `InterruptException` (loop stops; `agent(...)` returns
`AgentResult` with `stop_reason == "interrupt"` and `result.interrupts`); on
resume the SAME call returns the stored response. The caller resumes by invoking
the agent with a list of `{"interruptResponse": {"interruptId", "response"}}`
blocks. Today `agent/chat.py::_ask` drives this in a single process over stdin.

### 3.2 Why it can cross invocations: interrupt state is session-serialized

The crucial finding — `strands/types/session.py::SessionAgent.from_agent`
captures the interrupt state into the serialized agent blob:

```python
internal_state = {
    "interrupt_state": agent._interrupt_state.to_dict(),
    "model_state": agent._model_state,
}
```

and `SessionAgent.initialize_internal_state` restores it:

```python
if "interrupt_state" in self._internal_state:
    agent._interrupt_state = _InterruptState.from_dict(self._internal_state["interrupt_state"])
```

`_InterruptState.to_dict()`/`from_dict()` (`strands/interrupt.py`) persist the
raised interrupts AND the `pending_tool_execution` (the open assistant
`toolUse` message + any completed tool results needed to resume **without
re-calling the model**). `RepositorySessionManager.sync_agent` writes this on
every turn where internal state changed, and `initialize` restores it
(`strands/session/repository_session_manager.py`).

The AgentCore Memory manager persists that same `SessionAgent` blob as a
dedicated event with `metadata.stateType = "AGENT"` and reads it back in
`read_agent` (`memory/integrations/strands/session_manager.py::create_agent`/
`read_agent`). So:

- **Invocation A** (thin API `POST /chat`): build+attach agent for session S,
  call `agent(prompt)`. A write tool fires → `stop_reason == "interrupt"`. The
  per-turn `sync_agent` hook has already persisted the interrupt state (open
  toolUse + the pending interrupt) into Memory under session S. The entrypoint
  returns the proposal JSON to the caller (NO stdin needed).
- **Invocation B** (thin API `POST /chat/approve`): a FRESH process/agent is
  built+attached for the SAME session S; `attach_memory`→`initialize` restores
  `_interrupt_state` (and history) from Memory. The entrypoint calls
  `agent([{ "interruptResponse": { "interruptId": <id>, "response":
  "APPROVE"|"REJECT" }}])`; `agent.__call__` does `self._interrupt_state.resume(
  prompt)` (`strands/agent/agent.py`), the gate's `event.interrupt(...)` now
  RETURNS the decision, and the tool body runs (or cancels) — all without
  re-invoking the model, because `pending_tool_execution` was restored.

This is the SDK's documented interrupt flow (`strands/types/interrupt.py`
module docstring: "Interrupts are session managed in-between return and user
response"), just split across two Runtime calls instead of one stdin loop.

### 3.3 The caveat (OPEN DESIGN DECISION): interrupt state vs `filter_restored_tool_context=True`

Task-5's STM config sets `filter_restored_tool_context=True`
(`agent/memory_client.py`), and `AgentCoreMemorySessionManager.list_messages`
strips every `toolUse`/`toolResult` block from the RESTORED MESSAGE LIST
(`memory/integrations/strands/session_manager.py::_filter_restored_tool_context`).
But the pending open `toolUse` lives in a DIFFERENT restore channel — the
`interrupt_state.pending_tool_execution` blob on the `SessionAgent`, restored by
`initialize_internal_state`, NOT by `list_messages`. These two channels can
disagree: the message list (filtered) will not contain the open toolUse, while
the interrupt state will. On resume, Strands replays the pending tool execution
from `pending_tool_execution`; the filtered message history is what the model
sees on the NEXT model call. Whether these compose cleanly across a
process boundary with `filter_restored_tool_context=True` is the one thing we
could NOT fully prove from source alone (the Task-4/5 HITL resume was validated
only WITHIN a single process, where interrupt state lives in memory and is never
round-tripped through `list_messages`).

Options for Task 6 (pick during design, then verify live):

- **Option A (recommended): keep HITL propose→approve inside ONE Runtime
  invocation, driven by the session-affinity warm VM.** The thin API's two calls
  still map to two agent turns, but the agent object is cached in-process keyed
  by `context.session_id` for the brief approve window, so the interrupt state
  never has to survive a cold rebuild. Memory still persists conversation
  history; the interrupt just doesn't rely on the cross-invocation
  `interrupt_state` restore. Lowest risk; relies on Runtime same-session
  affinity, which the platform provides, with a bounded in-process session cache
  + idle eviction. Falls back to Option B semantics if the VM was recycled.
- **Option B: rely on the cross-invocation interrupt-state restore** (fully
  stateless thin API). Cleanest architecture, but we must verify the
  `filter_restored_tool_context` interaction live; if it corrupts the toolUse/
  toolResult pairing on the post-approve model turn, either set
  `filter_restored_tool_context=False` for sessions with a pending write, or
  carry the pending proposal out-of-band (see Option C).
- **Option C: don't round-trip the native interrupt at all — port
  mahalo-dock's explicit `pending_action` protocol.** mahalo-dock stored the
  proposal on the session (`agent/session.py::ChatSession.pending_action`) and
  executed it on `POST /chat/approve` (`routers/chat.py::approve_action`),
  appending the `[SYSTEM]` breadcrumb afterwards — never relying on an in-flight
  interrupt. We already reproduce those breadcrumbs in
  `agent/chat.py::_emit_system_signal`. This trades the native Strands interrupt
  for an explicit app-level proposal object but is the most transport-robust and
  the closest to the proven mahalo-dock demo behavior.

**Recommendation:** design for **Option A** (native interrupt, in-process
session-keyed agent cache across the approve window) as the primary, with
**Option C** documented as the robust fallback if live testing shows the
cross-VM restore is flaky. Either way the thin API surface is the same two calls
(`send` → returns `proposal`; `approve` → returns result), matching
mahalo-dock's `POST /chat` + `POST /chat/approve` so the frontend port is
unchanged. This must be PROVEN with a live Runtime deploy in Task 6 — it is the
designated verification gate.

### 3.4 Thin-API HITL shape to port (mahalo-dock, READ ONLY)

`mahalo-dock/backend/app/routers/chat.py`:
`POST /chat {message, session_id?, project_id?}` → `ChatResponse {response,
proposal?, systems_queried, session_id}`; then `POST /chat/approve {session_id,
approved}` → `ActionResult {success, message}`. Session objects were in-memory
(`agent/session.py::_sessions` dict) with a `pending_action`. In Task 6 the thin
API stays stateless and forwards to the Runtime; the session/`pending_action`
role is taken over by AgentCore Memory + the interrupt state (Option A/B) or an
explicit proposal object (Option C).

---

## 4. Identity on Runtime — Workload Access Token vs local `@requires_api_key`

### 4.1 What the Runtime provides

The platform mints a **Workload Access Token (WAT)** and delivers it to the agent
process as a request header, which the harness lifts into context
(`runtime/app.py::_build_request_context`):

```python
agent_identity_token = headers.get(IDENTITY_WAT_HEADER) or headers.get(ACCESS_TOKEN_HEADER)
if agent_identity_token:
    BedrockAgentCoreContext.set_workload_access_token(agent_identity_token)
```

`runtime/models.py`:
`IDENTITY_WAT_HEADER = "X-Amz-Bedrock-AgentCore-Identity-WAT"`,
`ACCESS_TOKEN_HEADER = "WorkloadAccessToken"`.

### 4.2 How the Task-5 decorators consume it (no code change needed)

`identity/auth.py::_get_workload_access_token`:

```python
token = BedrockAgentCoreContext.get_workload_access_token()
if token is not None:
    return token            # RUNNING ON RUNTIME: use the platform-minted WAT
# else: LOCAL DEV → _set_up_local_auth() self-provisions a workload identity
#       and writes .agentcore.json
```

So the **same** `@requires_api_key(provider_name="mahalo-jira-apikey")` that
Task 5 applied to `jira_create_story` works unchanged on Runtime — it just reads
the platform WAT from context instead of doing the local-dev
`.agentcore.json` provisioning. The ugly local dev-auth path (and the
`.agentcore.json` file) simply does not execute on Runtime. This is the "Runtime
Workload-Access-Token path for Identity" that Task 5 explicitly deferred to
Task 6.

Also available (not currently used): `@requires_access_token` (OAuth2 flows,
M2M/USER_FEDERATION/ON_BEHALF_OF), `@requires_wat` (read the WAT and propagate it
on outbound Runtime/Gateway hops via the `X-Amz-Bedrock-AgentCore-Identity-WAT`
header), and `@requires_iam_access_token` (AWS-signed JWT via STS
`GetWebIdentityToken`). (`identity/auth.py`.)

### 4.3 What Task 6 must wire for Identity

- Point the agent's Identity provider name at the CDK
  `CfnApiKeyCredentialProvider` (`mahalo-jira-apikey`) — already the default in
  `agent/config.py::identity_jira_provider`.
- Give the Runtime **execution role** permission to call AgentCore Identity /
  credential-provider APIs so the WAT→API-key exchange works server-side (the
  IdentityClient call inside `@requires_api_key`).
- The Runtime's `CfnWorkloadIdentity` (`mahalo-agent`, already provisioned in
  `MahaloMemoryIdentityStack`) is the workload identity for the hosted agent —
  the one the local CLI dev-auth path does NOT use (the Task-5 runbook note). On
  Runtime, the platform associates the agent with a workload identity and mints
  the WAT; we wire it via the runtime's auth/role config (see §5).
- Broadening beyond the one `jira_create_story` path (per-service brokering) is
  the other Task-5→6 deferral; it is additive decorator application, no new
  mechanism.

---

## 5. IaC — how Runtime is deployed; model access + execution role

### 5.1 `aws-cdk-lib 2.273.0` ships a Runtime L1 (confirmed)

`aws_cdk.aws_bedrockagentcore` exposes `CfnRuntime`, `CfnRuntimeProps`,
`CfnRuntimeEndpoint`, `CfnRuntimeEndpointProps` (verified by scanning the
installed `aws_bedrockagentcore/__init__.py`, alongside the already-used
`CfnGateway`/`CfnMemory`/`CfnWorkloadIdentity`/`CfnApiKeyCredentialProvider`). So
Runtime is deployable the same CDK way as Tasks 4-5 — **the starter-toolkit is
NOT required and is NOT installed** (`bedrock_agentcore_starter_toolkit` absent
from `agent/.venv`).

### 5.2 `CfnRuntime` contract (from installed `CfnRuntimeProps`)

Required:
- `agent_runtime_artifact` — the code/image. Two mutually-relevant shapes:
  - `ContainerConfigurationProperty(container_uri=<ECR image URI>)` — a container
    image in ECR.
  - `CodeConfigurationProperty(code=CodeProperty(s3=S3LocationProperty(...)),
    entry_point=[...], runtime=<managed runtime>)` — a zip in S3 + entry point.
- `agent_runtime_name` — the runtime name.
- `role_arn` — the **execution role** the Runtime assumes.

Optional (the ones that matter for us):
- `environment_variables` — map of env for the agent process. This is how we
  inject `MAHALO_TOOL_MODE`, `MAHALO_GATEWAY_MCP_URL`, `MAHALO_MEMORY_ENABLED`,
  `MAHALO_MEMORY_ID`, `MAHALO_IDENTITY_ENABLED`, `MAHALO_IDENTITY_JIRA_PROVIDER`,
  `BEDROCK_MODEL_ID`, `AWS_REGION`, mock URLs, etc.
- `authorizer_configuration` — inbound auth for `InvokeAgentRuntime`
  (`CustomJWTAuthorizerConfigurationProperty` for Cognito/JWT, or default SigV4/
  IAM). Mirrors the Task-4 decision: **keep AWS_IAM for now, Cognito later**
  (matches the user's "keep the AWS_IAM for now ... Cognito when I move to
  development mode").
- `network_configuration` (`network_mode` + optional VPC `network_mode_config`),
  `protocol_configuration`, `request_header_configuration`,
  `lifecycle_configuration`, `capacity_provider_configuration`,
  `filesystem_configurations`.

`CfnRuntimeEndpoint` creates an addressable endpoint for the runtime (the ARN the
thin API invokes).

### 5.3 Container vs managed-code — DECISION

**Choose the container (ECR `container_uri`) path.** Reasons: our agent process
has non-trivial dependencies (strands-agents, bedrock-agentcore, boto3, httpx,
our `agent/` package and its 25 tools) and we want full control of the server
(the `BedrockAgentCoreApp` + `@app.entrypoint` process listening on 8080 with
`/invocations` + `/ping`). A container is the well-trodden AgentCore Runtime
packaging and avoids managed-runtime entry-point/zip constraints. **This means
Task 6 adds a `Dockerfile`** (base Python 3.13 image, `pip install` our
`agent/requirements.txt`, copy `agent/`, `CMD` runs the app which calls
`app.run()` → uvicorn on 8080) **and an ECR image build/push step** wired into
CDK (e.g. `aws_ecr_assets.DockerImageAsset` → feed its image URI into
`CfnRuntime.ContainerConfigurationProperty`). Note the agent must be `linux/arm64`
or `linux/amd64` per the Runtime's `platform_version`/architecture requirement —
confirm the required arch at build time (AgentCore Runtime documents ARM64;
build the image for that arch).

### 5.4 Execution role — permissions the Runtime needs

The `role_arn` principal is `bedrock-agentcore` (the Runtime service assuming the
role on the agent's behalf). It must allow at least:

- **Bedrock model invoke** for Claude Sonnet 4.5:
  `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream` on the
  inference-profile/model ARNs for
  `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (cross-region inference profile
  ⇒ include the regional foundation-model ARNs it fans out to). Model access
  itself is already confirmed ACTIVE in the account (STATUS/CONTINUATION, Task-0
  capability check).
- **AgentCore Memory** (STM read/write): `bedrock-agentcore:CreateEvent`,
  `ListEvents`, `GetEvent`, `RetrieveMemoryRecords` (as used by
  `MemoryClient`/`AgentCoreMemorySessionManager`) scoped to the `CfnMemory` ARN.
- **AgentCore Identity**: the credential-provider / workload-identity APIs the
  `IdentityClient` calls to exchange the WAT for the Jira API key
  (`GetResourceApiKey`/token APIs) scoped to the `mahalo-jira-apikey` provider
  and the `mahalo-agent` workload identity.
- **AgentCore Gateway** (GATEWAY mode): invoke the Gateway MCP endpoint. Task-4
  established the inbound-auth answer — a SigV4-signed MCP request with signing
  service `bedrock-agentcore` is accepted by the default AWS_IAM authorizer
  (CONTINUATION Task-4 "INBOUND-AUTH RESOLVED"). So the execution role needs the
  matching invoke permission for the Gateway; the agent's
  `agent/gateway_client.py::SigV4Auth` already signs with service
  `bedrock-agentcore`. On Runtime, creds come from the execution role (not the
  `lava` profile), so `_build_bedrock_model`/the SigV4 signer must resolve the
  ambient role credentials — confirm `AWS_PROFILE` is unset in the container so
  boto3 uses the container role, not a missing `lava` profile
  (`agent/strands_agent.py::_build_bedrock_model` already falls back to the
  default chain when the profile is absent).
- Standard CloudWatch Logs write for the Runtime's log group.

### 5.5 Where this lands in CDK

Add a new stack (e.g. `MahaloRuntimeStack`) under `infra-cdk/mahalo_infra/`,
wired in `app.py` alongside the existing six stacks. It builds the Docker image
asset, creates the execution role (policies above), and defines `CfnRuntime`
(container artifact + env vars + `authorizer_configuration` AWS_IAM) and
`CfnRuntimeEndpoint`, exporting the runtime/endpoint ARN as a CfnOutput for the
thin API to invoke. The thin API itself (FastAPI, ported from
mahalo-dock's shape) calls `bedrock-agentcore:InvokeAgentRuntime` with the
session-id header; whether it's a Lambda+Function-URL or a small container is a
Task-6 design choice (Function-URL Lambda is consistent with Task-3's pattern
and keeps it stateless/cheap).

---

## Open questions to resolve in Task 6 DESIGN (not blockers)

1. **HITL transport (§3.3):** Option A (in-process session-keyed agent cache
   across the approve window, recommended) vs Option B (stateless cross-
   invocation interrupt-state restore) vs Option C (explicit `pending_action`
   proposal object à la mahalo-dock). Must be PROVEN with a live Runtime deploy —
   specifically the interaction of the restored `interrupt_state`
   `pending_tool_execution` with `filter_restored_tool_context=True`.
2. **Agent build cadence per invocation (§2.3):** rebuild-per-request (simple,
   correct) vs session-keyed in-process cache (faster, needed anyway for Option
   A). Decide the cache key (`context.session_id`) and eviction.
3. **Streaming (§1.3):** MVP returns a single JSON response (sync entrypoint);
   SSE via `agent.stream_async` is a later enhancement, out of MVP scope.
4. **Container arch (§5.3):** confirm the required image architecture for
   AgentCore Runtime (ARM64) and build the Docker image for it.
5. **Thin-API host (§5.5):** Function-URL Lambda (consistent with Task 3) vs a
   small always-on container. Must stay stateless and forward the session id.
6. **Inbound auth (§5.2):** stay on AWS_IAM for now (per the user's direction);
   Cognito/CUSTOM_JWT is the documented dev-mode upgrade.

## Citations index (installed source)

- Runtime harness / routes / entrypoint / payload / streaming / ping:
  `bedrock_agentcore/runtime/app.py` (`BedrockAgentCoreApp`, `entrypoint`,
  `_takes_context`, `_handle_invocation`, `_invoke_handler`, `run`,
  `_build_request_context`, `_convert_to_sse`).
- Request context + session/WAT context vars:
  `bedrock_agentcore/runtime/context.py` (`RequestContext`,
  `BedrockAgentCoreContext`).
- Header constants (session id, WAT, request id):
  `bedrock_agentcore/runtime/models.py` (`SESSION_HEADER`, `IDENTITY_WAT_HEADER`,
  `ACCESS_TOKEN_HEADER`, `PingStatus`).
- Identity decorators + WAT resolution:
  `bedrock_agentcore/identity/auth.py` (`requires_api_key`,
  `requires_access_token`, `requires_wat`, `requires_iam_access_token`,
  `_get_workload_access_token`, `_set_up_local_auth`).
- Memory session manager (persist/restore messages + agent/interrupt blob):
  `bedrock_agentcore/memory/integrations/strands/session_manager.py`
  (`AgentCoreMemorySessionManager`, `create_agent`/`read_agent`,
  `create_message`/`list_messages`, `_filter_restored_tool_context`,
  `register_hooks`, `initialize`).
- Memory config (STM toggles):
  `bedrock_agentcore/memory/integrations/strands/config.py`
  (`AgentCoreMemoryConfig`, `filter_restored_tool_context`, `batch_size`,
  `persistence_mode`).
- Strands interrupt model + session serialization:
  `strands/types/interrupt.py`, `strands/interrupt.py` (`_InterruptState`,
  `PendingToolExecution`, `to_dict`/`from_dict`),
  `strands/types/session.py` (`SessionAgent.from_agent` /
  `initialize_internal_state`),
  `strands/session/repository_session_manager.py`
  (`sync_agent`, `initialize`, `_fix_broken_tool_use`),
  `strands/agent/agent.py` (`self._interrupt_state.resume(prompt)`,
  `session_manager` wiring).
- CDK Runtime L1:
  `aws_cdk/aws_bedrockagentcore/__init__.py` (`CfnRuntime`, `CfnRuntimeProps`,
  `CfnRuntime.AgentRuntimeArtifactProperty`, `ContainerConfigurationProperty`,
  `CodeConfigurationProperty`, `NetworkConfigurationProperty`,
  `AuthorizerConfigurationProperty`, `CfnRuntimeEndpoint`).
- Existing agent seams (unchanged, to reuse): `agent/strands_agent.py`
  (`build_agent`, `attach_gateway_tools`, `attach_memory`, `BuildResult`),
  `agent/memory_client.py`, `agent/approval.py` (`WriteApprovalHook`),
  `agent/chat.py` (`_ask`, `_emit_system_signal`), `agent/config.py`.
- Thin-API/session shape to port (READ ONLY):
  `mahalo-dock/backend/app/routers/chat.py` (`POST /chat`, `POST /chat/approve`),
  `mahalo-dock/backend/app/agent/session.py` (`ChatSession.pending_action`).
