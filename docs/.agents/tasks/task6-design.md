# Task 6 â€” Runtime hosting: technical DESIGN

Host the existing Strands agent on **Amazon Bedrock AgentCore Runtime** and route
all traffic through a thin, stateless API. This design is grounded in
`docs/.agents/tasks/task6-investigation.md` (the verified Runtime/SDK surface);
it does not re-derive those facts, it builds on them and resolves the five open
questions (Aâ€“E). Every file path is workspace-relative with forward slashes.

**Deploy policy:** the automated gate stays **OFFLINE** â€” `cdk synth` and all
import/construct paths must pass with no network and no AWS creds. Deploy
(including the container build/push) is a **deferred operator step** with a
documented live runbook; nothing here auto-deploys.

**Hard rule honored:** all artifacts land under
`<WORKSPACE_ROOT>`. `mahalo-dock` is READ ONLY
and is only used as a shape reference; no LangChain and no old agent loop are
dragged in.

**Technology stack (locked once approved):**
- Runtime harness: `bedrock-agentcore==1.24.1` `BedrockAgentCoreApp` (Starlette ASGI, uvicorn on :8080).
- Agent: the existing `agent/` package â€” `strands-agents==1.61.1`, Bedrock Claude Sonnet 4.5.
- Packaging: a **container image** (Docker) pushed to **ECR**, referenced by the Runtime artifact.
- Thin API: **FastAPI** (mahalo-dock precedent) on a **Function-URL Lambda** (`python3.13`, consistent with Task 3), invoking the Runtime via `boto3` `bedrock-agentcore` data-plane `InvokeAgentRuntime`.
- IaC: AWS CDK (Python), `aws-cdk-lib==2.273.0` â€” the **L2 `aws_bedrockagentcore.Runtime`** construct suite (`Runtime`, `AgentRuntimeArtifact`, `RuntimeAuthorizerConfiguration`, `RuntimeEndpoint` via `runtime.add_endpoint`), plus `aws_lambda`, `aws_iam`, `aws_ecr`. (Â§E.0 records the L1-vs-L2 decision and why the L2 is chosen over the raw `CfnRuntime`.)
- Inbound auth: **AWS_IAM / SigV4** for now (per the user); Cognito/CUSTOM_JWT is the documented dev-mode upgrade.

> **Revision note (fifth design-review iteration).** The first iteration resolved
> an earlier review's seven findings; the second a 5-finding review; the third a
> 1-HIGH/1-MEDIUM/2-NIT review; the fourth a 2-MEDIUM/2-NIT review (all recorded
> in "Review responses â€” earlier iterations" at the end). This iteration resolves
> the **fifth** review (`docs/.agents/tasks/task6-design-review.json` /
> `task6-design-review.md`, verdict CHANGES_REQUESTED, **1 HIGH + 4 MEDIUM + 2
> NIT**). Each fix is recorded inline where the change lands and summarized in
> "Review responses â€” current iteration" at the end. The one HIGH finding forced a
> re-grounding of the **entire Â§E IaC approach** against installed source, which
> changed the construct choice:
>
> 1. **(Finding 1, HIGH) The installed CDK ships a full L2 `agentcore.Runtime`
>    construct suite that the investigation never discovered; Â§E is re-based onto
>    it.** Re-verified against
>    `infra-cdk/.venv/Lib/site-packages/aws_cdk/aws_bedrockagentcore/__init__.py`:
>    the module exports an L2 `Runtime` construct (jsii type
>    `aws-cdk-lib.aws_bedrockagentcore.Runtime`, class body at line ~85818) with
>    `execution_role` **optional** ("If not provided, a role will be created
>    automatically", `__init__` docstring) and `authorizer_configuration`
>    defaulting to `RuntimeAuthorizerConfiguration.iam()` ("IAM authentication"); an
>    `AgentRuntimeArtifact` abstract base (line ~4586) with
>    `from_image_uri(container_uri)` (line ~283 docstring: "Use this when
>    referencing ECR images from **CloudFormation parameters** or cross-stack
>    references â€¦ **No IAM permissions are automatically granted** â€” you must ensure
>    the runtime has ECR pull permissions"), `from_asset(directory, file=,
>    platform=)`, `from_ecr_repository`, `from_code_asset`, `from_s3`; a
>    `RuntimeAuthorizerConfiguration` abstract base (line ~74748) with
>    `using_iam()` / `using_cognito(user_pool, clients, â€¦)` / `using_jwt(discovery_url,
>    â€¦)` / `using_o_auth(â€¦)`; `Runtime.add_endpoint(name, â€¦)` â†’ `RuntimeEndpoint`
>    (line ~85988); and a `.role` property exposing the (auto-created or supplied)
>    role for grants. **Decision: adopt the L2** (Â§E.0). This deletes the
>    hand-rolled execution role, the `CfnCondition` authorizer dance, and the manual
>    `CfnRuntimeEndpoint` from the prior Â§E; the offline gate keeps its
>    `CfnParameter` mechanism via `from_image_uri(CfnParameter.value_as_string)`,
>    which the docstring blesses for exactly that use.
>
> 2. **(Finding 2, MEDIUM) ECR pull permission.** `from_image_uri` grants no IAM
>    (docstring, line ~283), and the L2 auto-role covers ECR only on the
>    `from_asset`/`from_ecr_repository` paths (the artifact `bind` wires it). So on
>    the offline/`from_image_uri` branch the design grants ECR pull on
>    `runtime.role` explicitly (Â§E.1); on the deploy/`from_asset` branch the artifact
>    grants it. Either way ECR pull is present â€” the gap the prior hand-rolled role
>    had is closed.
>
> 3. **(Finding 3, MEDIUM) Thin-API Lambda dependency bundling** is now specified
>    (Â§E.2): `BundlingOptions` running `pip install -r requirements.txt -t
>    /asset-output` in the `python3.13` bundling image, gated like the image build
>    so `cdk synth` stays Docker-free offline (a pre-built deps layer is the
>    offline-branch fallback).
>
> 4. **(Finding 4, MEDIUM) `tool_mode` identity across HITL legs** is stated
>    explicitly (Â§B.3/Â§C.2/Â§D.2): `MAHALO_TOOL_MODE` is a Runtime-process env
>    constant, identical on both legs by construction, and the approve leg re-runs
>    `attach_gateway_tools` in GATEWAY mode so the restored `pending_tool_execution`
>    resolves against the same `target___tool` registry.
>
> 5. **(Finding 5, MEDIUM) The `interrupt_id` round-trip** is now grounded to the
>    `strands` interrupt model (Â§C.2) with file:line citations for the id field and
>    the resume-matching, or marked a live-gate item where source cannot confirm it.
>
> The two NITs: Finding 6 (proposal payload identity with `build_proposal`) and
> Finding 7 (session-cache correctness across the approve window) are resolved by
> one-sentence precision fixes in Â§A.4/Â§C.2 and Â§D.2. The prior-iteration facts
> (ARM64 grounding, the withdrawn per-invocation budget, the `boto3` lazy
> `ProfileNotFound` + `available_profiles` fix, the grounded Identity IAM actions,
> `InvokeAgentRuntimeForUser`, `contentType`/`accept`, the `requirements.txt` pins)
> remain as verified then.

---

## Overview

The agent moves from a local `python -m agent.chat` process into a managed
Runtime microVM. The Runtime process is a thin ASGI harness
(`BedrockAgentCoreApp`) whose single `@app.entrypoint` wraps the **unchanged**
`build_agent(...)` / `attach_gateway_tools` / `attach_memory` seams. The platform
POSTs `/invocations` and probes `GET /ping`; it supplies the session id as an
HTTP header and (for Identity) a Workload Access Token in request context. The
entrypoint reads the prompt from the JSON body, maps the header session id onto
the Strands/Memory session, builds + attaches the agent **per invocation**,
drives one agent turn, and returns a JSON-able dict.

In front of the Runtime sits a **stateless FastAPI thin API** on a Function-URL
Lambda. It exposes `POST /chat` and `POST /chat/approve` (the exact mahalo-dock
shape), forwards the session id, carries no business logic and no second agent,
and calls `bedrock-agentcore:InvokeAgentRuntime`. The frontend port from
mahalo-dock is therefore unchanged.

HITL (the six gated writes) becomes a **two-call proposeâ†’approve protocol** over
the request/response boundary, replacing the stdin loop in `agent/chat.py::_ask`.
The **contract** (Finding 4) is the lowest-risk path: for any session carrying a
pending write, the agent's Memory session manager is constructed with
`filter_restored_tool_context=False`, so the restored message list and the
restored `interrupt_state` cannot disagree on the open tool-use across a cold
process boundary. The fully stateless cross-invocation restore with the default
`filter_restored_tool_context=True` (Option B) is demoted to an **opt-in
optimization** that is only enabled after the live gate (Â§C.5) proves it clean;
the explicit `pending_action` proposal (Option C) remains the documented robust
fallback. The thin-API surface is identical under all three.

Identity (the WAT-brokered Jira write) is **descoped from the AWS_IAM MVP**:
under SigV4 inbound auth the installed SDK raises `ValueError` in the container
unless the caller supplies a `runtimeUserId`, so for the AWS_IAM phase
`MAHALO_IDENTITY_ENABLED=false` and the live gate omits the brokered write. The
`runtimeUserId` plumbing â€” and the now-grounded execution-role Identity policy
(`bedrock-agentcore:GetResourceApiKey` + `GetWorkloadAccessTokenForUserId`,
cited to installed source in Â§D.4) â€” is designed and wired as the opt-in
enablement path (Â§D.4), provisioned only when Identity is turned on so the MVP
role claims nothing ungrounded, and proven once either `runtimeUserId`
end-to-end or Cognito inbound auth lands.

The hosted agent's Bedrock credentials come from the Runtime **execution role**.
The container sets no `AWS_PROFILE`, so `agent/config.py` resolves the `"lava"`
default; `_build_bedrock_model` must therefore choose the profile *before*
constructing the boto3 Session â€” checking `botocore` `available_profiles` and
only passing `profile_name` when `"lava"` is actually present â€” because a
`boto3.Session(profile_name="lava")` does **not** raise at construction (the
`ProfileNotFound` is lazy, Â§A.6/Finding 1). When `"lava"` is absent (the
container) the Session is built with no profile, so boto3 uses the default chain
= the execution role.

Everything new is **additive and opt-in**: the DIRECT/GATEWAY CLI, the Task-5
Memory/Identity seams, and the current offline test baseline (`agent 69/1`,
`infra-cdk 31` + synth, `tools-lambdas 94`, zero LangChain) stay intact. The
Runtime is a new consumer of `build_agent`, not a change to it.

---

## A. Runtime entrypoint + packaging

### A.1 New module: `agent/runtime_app.py`

A new module `agent/runtime_app.py` hosts the Runtime harness. It lives inside
the `agent/` package so it reuses `build_agent`, `attach_gateway_tools`,
`attach_memory`, `settings`, and `build_proposal` directly (no duplication, no
second agent). `agent/chat.py` stays as the local CLI and is untouched.

Skeleton (grounded in investigation Â§1.2â€“Â§1.3, Â§2.1â€“Â§2.3):

```python
# agent/runtime_app.py
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent.config import settings
from agent.strands_agent import attach_gateway_tools, attach_memory, build_agent
from agent.runtime_session import build_and_attach         # Â§D helper
from agent.hitl import emit_system_signal, resume_once     # Â§C helpers

app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload, context):           # 2nd param MUST be named "context"
    ...

if __name__ == "__main__":
    app.run()                            # uvicorn on 0.0.0.0:8080 in-container
```

Import-time offline-safety: `BedrockAgentCoreApp()` is a Starlette subclass
construction (no network); `build_agent` is already offline-safe. So `import
agent.runtime_app` succeeds with no creds â€” this is what the offline gate asserts
(Â§E.4). The single AWS touch stays inside `attach_memory` / `attach_gateway_tools`
/ the live agent call, exactly as today.

### A.2 Entrypoint signature and dispatch

Use the **two-parameter** form `invoke(payload, context)` so `context.session_id`
and the WAT are available (the harness detects the `context` name by
introspection â€” investigation Â§1.2). Use a **plain sync function returning a
dict** for the MVP: the agent call is blocking, the harness runs sync handlers in
a threadpool so `GET /ping` stays healthy, and a returned dict is serialized to a
single `application/json` response (investigation Â§1.3). Streaming via
`agent.stream_async` is explicitly **out of MVP scope** (Â§A.6).

### A.3 Request/response contract

There is no platform-fixed prompt schema (investigation Â§1.2), so the entrypoint
owns validation. The contract the thin API and Runtime agree on:

**Request body (`payload`, JSON):**

| field | type | required | meaning |
|---|---|---|---|
| `action` | string enum `"chat"` \| `"approve"` | required | which leg of the protocol |
| `prompt` | string | required when `action="chat"` | the user message |
| `decision` | string enum `"APPROVE"` \| `"REJECT"` | required when `action="approve"` | HITL verdict |
| `interrupt_id` | string | required when `action="approve"` | the pending interrupt to resume |
| `developer_id` | string | optional (default `"dev-6"`) | maps to Memory `actor_id` |
| `role` | string | optional (default `"developer"`) | role prompt selection; sent on the `chat` leg, **omitted on the `approve` leg** because resume replays `pending_tool_execution` without a model call so the system prompt is not re-consumed (Finding 4, Â§B.3) |

Session id is **not** in the body â€” it is the header
`X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`, surfaced as `context.session_id`
(investigation Â§2.1). The thin API sets it on the invoke call.

**Response body (dict â†’ JSON):**

| field | type | meaning |
|---|---|---|
| `response` | string | the agent's assistant text (empty string when a proposal is pending) |
| `proposal` | object \| null | present iff a write gate fired: `{action, system, params, description, interrupt_id}` (the `build_proposal` dict plus the interrupt id) |
| `session_id` | string | the **resolved** id (`context.session_id or <generated>`), echoed so the client threads the next call â€” including the generated id when the header was absent (Â§A.4 step 2, Finding 3) |
| `status` | string enum `"complete"` \| `"pending_approval"` \| `"error"` | drives the client |
| `error` | object \| null | `{type, message}` on handled failure |

This maps 1:1 onto mahalo-dock's `ChatResponse {response, proposal?, session_id}`
and `ActionResult`, so the thin API is a near-pure projection.

### A.4 Entrypoint behavior (chat leg)

1. Validate `payload`: require `action`; for `chat`, require non-empty `prompt`.
   On validation failure return `{"status":"error","error":{...}}` (HTTP 200 with
   an error envelope â€” the platform only 400s on malformed JSON before our
   handler; our semantic errors are in-band so the thin API can forward them).
2. Resolve `session_id = context.session_id or <generated uuid>` (the fallback
   should not happen when invoked via the thin API, which always sets the header
   â€” Â§B.4; log a warning if it does). **This resolved id is the one echoed back
   in the response `session_id` (Â§A.3)** â€” including the generated uuid when the
   header was absent â€” so a client that omitted the header still receives a
   threadable id and its follow-up call continues the SAME Memory conversation
   instead of silently starting a fresh one (Finding 3). The thin API is the
   primary id source; the Runtime-side generation is a belt-and-braces path.
3. `build_and_attach(session_id, developer_id, role)` (Â§D.2) â†’ a ready agent with
   Memory attached (history rehydrated) and, in GATEWAY mode, the MCP client
   started.
4. Call `result = agent(prompt)` inside a `try/finally` that stops the MCP client
   in GATEWAY mode (mirrors `agent/chat.py`).
5. If `result.stop_reason == "interrupt"`: build the proposal from the interrupt
   and return
   `{"status":"pending_approval","proposal":{...,"interrupt_id":itr.id},
   "response":"", "session_id":...}`. **The proposal returned to the client is
   exactly `build_proposal(tool_use)` carried as `itr.reason`
   (`agent/approval.py::WriteApprovalHook` passes the `build_proposal` dict as the
   `reason=` of `event.interrupt("write_approval", reason=...)`), with
   `interrupt_id` (= `itr.id`, Â§C.2) added as the only new key â€” no re-derivation
   (Finding 6).** Because the payload is literally the `build_proposal` output,
   the gated set maps 1:1 to the six `WRITE_TOOL_NAMES`
   (`agent/approval.py`): the client sees a proposal iff one of exactly those six
   write tools was about to fire. The per-turn Memory `sync_agent` hook has
   already persisted the open toolUse + interrupt state under the session
   (investigation Â§3.2), so no HTTP write happened and nothing is lost.
6. Else return `{"status":"complete","response":str(result).strip(),
   "session_id":...}`.

### A.5 Entrypoint behavior (approve leg)

Covered in detail in Â§C; summary: rebuild+attach the agent for the same session
(restoring the interrupt state from Memory), resume with the
`interruptResponse` block, and on a closed non-interrupt cycle emit the `[SYSTEM]`
breadcrumb (reusing `agent/chat.py::_emit_system_signal`, refactored to a shared
helper) before returning the result.

### A.6 Packaging decision â€” container (ECR), not managed-code

The Runtime artifact can be a container image or managed code: the L2
`AgentRuntimeArtifact` exposes `from_image_uri`/`from_asset`/`from_ecr_repository`
(container) and `from_code_asset`/`from_s3` (managed zip + entry point) â€”
investigation Â§5.2â€“Â§5.3, and verified in installed source (Â§E.0). **Choose the
container path.** Reasoning: our process has non-trivial deps (`strands-agents`,
`bedrock-agentcore`, `boto3`, `httpx`, the whole `agent/` package with 25 tools)
and we want full control of the ASGI server listening on :8080 with
`/invocations` + `/ping`. The container is the well-trodden AgentCore Runtime
packaging and avoids managed-runtime zip/entry-point constraints. The cost is a
`Dockerfile` + an ECR image build/push wired into CDK via
`AgentRuntimeArtifact.from_asset(...)` on the deploy branch and
`from_image_uri(CfnParameter)` on the offline branch (Â§E.1/Â§E.2).

**New file: `agent/Dockerfile`** (co-located with the package it ships):

```dockerfile
# linux/arm64 â€” REQUIRED by AgentCore Runtime. Grounded in the installed CDK L1
# docstring (infra-cdk/.venv/.../aws_bedrockagentcore/__init__.py): the
# container-deployment section states "developers create a Dockerfile, build
# ARM-compatible containers, manage ECR repositories" (line ~238), and the
# code-deploy section states "A ZIP archive containing Linux arm64 dependencies
# needs to be uploaded to S3 as a pre-requisite to Create Agent Runtime"
# (line ~242). AWS doc: runtime-get-started-code-deploy.html (see Assumptions).
FROM --platform=linux/arm64 python:3.13-slim
WORKDIR /app
COPY agent/requirements.txt ./agent/requirements.txt
RUN pip install --no-cache-dir -r agent/requirements.txt
COPY agent/ ./agent/
# NOTE (Finding 1): do NOT set AWS_PROFILE at all. agent/config.py then resolves
# the "lava" default; _build_bedrock_model (patched, Â§A.6) checks botocore
# available_profiles and, because "lava" is absent in the container, builds the
# boto3 Session with NO profile so boto3 uses the default (exec-role) credential
# chain. (Setting AWS_PROFILE="" would pass an empty profile name; the fix branches
# on profile resolution rather than relying on any Session construction-time raise.)
EXPOSE 8080
CMD ["python", "-m", "agent.runtime_app"]
```

**Credential resolution â€” the correct mechanism (Finding 1, HIGH; verified
against installed source).** The prior iteration assumed
`boto3.Session(profile_name="lava")` *raises `ProfileNotFound` at construction*
and that `_build_bedrock_model`'s `try/except` around the Session constructor
would then fall back to the default chain. **That is wrong and this iteration
fixes it.** Verified:

- `boto3/session.py::Session.__init__` does nothing with the profile but
  `self._session.set_config_variable('profile', profile_name)` â€” no config read,
  no existence check, **no raise**.
- `ProfileNotFound` is raised **lazily** by
  `botocore/session.py::get_scoped_config` (line 424:
  `raise ProfileNotFound(profile=profile_name)`), which runs only at
  credential/region resolution â€” i.e. **inside** `BedrockModel`/the first model
  call, **after** `_build_bedrock_model` has returned and **outside** its
  `try/except` (which wraps only the `boto3.Session(...)` constructor).
- Corroborated by the existing offline tests
  (`agent/tests/test_gateway_mode.py`, `test_memory_mode.py`,
  `test_identity_mode.py`): they `build_agent(...)` with no creds and no `lava`
  profile and pass â€” only possible because `Session("lava")` does not raise at
  construction.

So, as written, the container's `_build_bedrock_model` would return a Session
still pinned to `profile='lava'`, the `except` branch would never fire, and the
**first `agent(prompt)` would raise `ProfileNotFound` unhandled** â€” breaking
every Bedrock call the hosted agent makes.

**Fix â€” decide the profile before constructing the Session.** Patch
`agent/strands_agent.py::_build_bedrock_model` to resolve the profile explicitly
using `botocore`'s `available_profiles` (verified
`botocore/session.py::available_profiles` line 302 returns
`list(self._build_profile_map().keys())`, reading the config file via
`full_config['profiles']` â€” **no credentials, no network**, so it is
offline-safe):

```python
# agent/strands_agent.py::_build_bedrock_model (patched)
import botocore.session
prof = settings.aws_profile                      # "lava" by default
avail = botocore.session.Session().available_profiles   # reads config, no creds/network
if prof and prof in avail:
    session = boto3.Session(profile_name=prof, region_name=settings.aws_region)
else:
    # profile absent (the container) or empty -> default credential chain = exec role
    session = boto3.Session(region_name=settings.aws_region)
```

This removes the reliance on a construction-time raise entirely: locally, `lava`
is in `available_profiles` so the profile Session is used (CLI behavior
unchanged); in the container `lava` is absent so the profile-less Session is
built and boto3 resolves the Runtime execution role via the default chain. The
`try/except` can remain as a belt-and-braces guard but is no longer the
mechanism. `AWS_PROFILE` is still **omitted** from the Dockerfile and the L2
`Runtime(environment_variables=...)` map (so `settings.aws_profile == "lava"` and the
`prof in avail` check is what decides). The Â§E.4 offline test exercises this
**real** path (profile absent from `available_profiles` â‡’ profile-less branch),
not a mock that forces `Session()` to raise.

Note on `DOCKER_CONTAINER`: the harness binds `0.0.0.0` when it detects a
container (`/.dockerenv` or `DOCKER_CONTAINER`), and the installed Identity
resolver treats `DOCKER_CONTAINER=="1"` as "running on Runtime" â€” the exact flag
that makes `@requires_api_key` raise rather than fall back to local dev-auth when
no WAT is present (Â§D.4, Finding 1). Because Identity is OFF for the AWS_IAM MVP,
that path is not exercised; the flag's only MVP effect is the harness host
binding. When Identity is later enabled, this is precisely why the thin API must
send `runtimeUserId`.

`agent/requirements.txt` gains no new hard runtime dep (`pytest` is dev-only but
harmless; optionally split a `requirements-dev.txt` later â€” not required for Task
6). The image is built for **ARM64** (open question 4 resolved, Finding 2):
**ARM64 is the AgentCore Runtime container contract, grounded in installed
source** â€” the CDK L1 docstring (`infra-cdk/.venv/Lib/site-packages/aws_cdk/
aws_bedrockagentcore/__init__.py`) says, verbatim, that for container deployment
"developers create a Dockerfile, build **ARM-compatible** containers, manage ECR
repositories" (line ~238) and, for the code-deploy alternative, "A ZIP archive
containing **Linux arm64** dependencies needs to be uploaded to S3 as a
pre-requisite to Create Agent Runtime" (line ~242), citing the AWS doc
`https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy.html`.
So `--platform=linux/arm64` rests on a citation, not a guess. The "confirm at
build time" step is retained only as a belt-and-braces check; it is not the basis
for the choice. (Note the L2 `Runtime` also accepts a `platform_version`
(`PlatformVersion.V1`/`V2`) â€” this is the *runtime platform generation*, not
the CPU architecture, and defaults to the service default; it is orthogonal to the
ARM64 image requirement.)

### A.7 Health / ping and observability

Rely on the default `GET /ping` â†’ `Healthy` (investigation Â§1.4); no custom
`@app.ping` for the MVP. The platform injects `OTEL_RESOURCE_ATTRIBUTES` and
request/session-tagged JSON logging automatically (Â§1.5); we set nothing.

---

## B. Thin API (`api/`)

### B.1 Framework and host decision

**FastAPI on a Function-URL Lambda** (`python3.13`). FastAPI is the mahalo-dock
precedent and keeps the ported router shape familiar; the Function-URL Lambda is
the Task-3 pattern, stays stateless, scales to zero, and is cheap. It runs FastAPI
under an ASGI-to-Lambda adapter (`mangum`) behind the Function URL. The
alternative â€” an always-on container (Fargate/App Runner) â€” is rejected for the
MVP: it adds standing cost and ops for no benefit, since the thin API holds no
state and does no long-running work. (Open question 5 resolved: Function-URL
Lambda.)

### B.2 Layout (under `api/`, which today holds only `.gitkeep`)

```
api/
  app/
    main.py            # FastAPI() app + Mangum handler
    routers/chat.py    # POST /chat, POST /chat/approve  (ported SHAPE from mahalo-dock)
    runtime_client.py  # boto3 bedrock-agentcore InvokeAgentRuntime wrapper
    auth.py            # request-identity extraction (dev-id); SigV4 is inbound at the edge
    models.py          # pydantic request/response models (mirror Â§A.3)
    config.py          # env: MAHALO_RUNTIME_ARN / endpoint, region
  requirements.txt     # fastapi, mangum, boto3, pydantic  (NO langchain, NO agent import)
  Dockerfile           # optional; only if B.1 is later revisited for a container
```

The thin API **does not import `agent/`** â€” it must not pull the Strands agent or
any tool code into the edge. It only speaks the JSON contract of Â§A.3.

### B.3 Endpoints (ported shape, thinned)

Ported from `mahalo-dock/backend/app/routers/chat.py` but reduced to a pure
forwarder â€” no DB, no `openai_api_key` branch, no `demo_agent`, no
`execute_proposed_action` (that logic now lives in the agent on the Runtime):

```python
# api/app/routers/chat.py  (SHAPE ported; LangChain / old loop NOT ported)
@router.post("", response_model=ChatResponse)
async def send_message(req: ChatRequest, ident = Depends(current_identity)):
    session_id = req.session_id or str(uuid.uuid4())
    out = invoke_runtime(
        session_id=session_id,
        body={"action": "chat", "prompt": req.message,
              "developer_id": ident.developer_id, "role": ident.role},
    )
    return ChatResponse(response=out["response"], proposal=out.get("proposal"),
                        session_id=session_id, status=out["status"])

@router.post("/approve", response_model=ActionResult)
async def approve_action(req: ApprovalRequest, ident = Depends(current_identity)):
    out = invoke_runtime(
        session_id=req.session_id,
        body={"action": "approve", "decision": "APPROVE" if req.approved else "REJECT",
              "interrupt_id": req.interrupt_id, "developer_id": ident.developer_id},
    )
    return ActionResult(success=(out["status"] != "error"),
                        message=out["response"], session_id=req.session_id)
```

`ChatRequest {message, session_id?, project_id?}` and
`ApprovalRequest {session_id, interrupt_id, approved, proposal?}` mirror mahalo-dock
plus the one new `interrupt_id` field the two-call protocol needs (Â§C) and an
**optional** `proposal` echo (see the breadcrumb note below). `project_id` is
accepted for frontend compatibility but currently unused (noted in Out of Scope).

**`[SYSTEM]` breadcrumb is derived from restored state, not the client (code-review
Findings 2 & 3).** On a cold approve process the entrypoint has no in-memory
proposal, so the chain breadcrumb (branchâ†’commitâ†’PR) must not depend on the client
round-tripping it. The approve leg therefore **derives the proposal from the
RESTORED session state**: after `attach_memory` rehydrates the agent,
`agent._interrupt_state.interrupts[interrupt_id].reason` is exactly the
`build_proposal` dict the chat leg returned (`agent/approval.py` passes it as
`event.interrupt(reason=...)`), so `agent/runtime_app.py::_restored_proposal` reads
it and `emit_system_signal` fires regardless of what the client sent. The
`ApprovalRequest.proposal` field is retained only as a **belt-and-braces fallback**
(used iff the restored state has no matching pending interrupt, e.g. a recycled VM);
it is NOT required for chain correctness, so a faithful mahalo-dock frontend sending
only `{session_id, interrupt_id, approved}` still gets the breadcrumb. This closes
the earlier coupling where the chain re-proposed when the client omitted the echo.

**Why the approve leg does not forward `role` (Finding 4).** The `/chat/approve`
body carries `developer_id` but **not** `role`, so the approve-leg
`build_and_attach` rebuilds with the default `role="developer"`. This is **safe
regardless of the chat-leg role** because the approve leg resumes via
`agent([{interruptResponse:...}])`, which replays the restored
`pending_tool_execution` and runs the gated tool body **without a model call**
(investigation Â§3.2: `_interrupt_state.resume(prompt)` returns the stored
response; the model is not re-invoked). The `role` only selects the system
prompt, and the system prompt is only consumed on a model call â€” so a rebuilt
approve-leg agent with a different `role` than the chat-leg agent produces an
identical resume. (For the demo `role` is always `developer` anyway.) The design
therefore does **not** forward `role` on approve; if a future change makes the
post-approve turn re-invoke the model, `role` must be forwarded then â€” called out
here so the invariant is explicit.

**Why the approve leg CAN omit `role` but MUST NOT vary `tool_mode` (Finding 4).**
The `role`-is-safe argument above covers the *system prompt*, but the approve-leg
rebuild also reconstructs the agent's **tool registry**, and the restored
`pending_tool_execution` references the gated tool **by name**. In GATEWAY mode
those names carry the Gateway `target___tool` prefix â€” this is exactly why
`agent/approval.py::_bare_name` exists (it strips that prefix so
`WRITE_TOOL_NAMES` matches in both DIRECT and GATEWAY). If the chat leg ran
GATEWAY (prefixed names, MCP started) and the approve leg were rebuilt in a
different mode, the restored tool-use name would not resolve against the rebuilt
registry and the resume could fail to dispatch the gated tool body. **Invariant:
`tool_mode` is a Runtime-process-level env constant (`MAHALO_TOOL_MODE`, the L2
`Runtime(environment_variables=...)`, Â§E.3), identical on both legs by
construction** â€” it is NOT a per-request field and is forwarded by neither
`/chat` nor `/chat/approve`. `build_and_attach` (Â§D.2) therefore resolves the
same `settings.tool_mode` on both legs, so the rebuilt approve-leg agent has the
same tool registry (and, in GATEWAY mode, the same `target___tool` names) as the
chat-leg agent, and the restored `pending_tool_execution` resolves. In GATEWAY
mode the approve leg re-runs `attach_gateway_tools` (MCP start, with stop in
`finally`, Â§A.4 step 4 / Â§A.5) before the resume so those prefixed tools are live
when the body dispatches. If a future change ever allows per-request `tool_mode`,
it must be forwarded on the approve leg exactly like `developer_id` â€” called out
so the invariant is explicit.

### B.4 Forwarding and session id

`api/app/runtime_client.py` wraps the **data-plane** call:

```python
import boto3
_client = boto3.client("bedrock-agentcore", region_name=cfg.region)

def invoke_runtime(*, session_id: str, body: dict, runtime_user_id: str | None = None) -> dict:
    kwargs = dict(
        agentRuntimeArn=cfg.runtime_arn,          # from CfnOutput via env
        runtimeSessionId=session_id,              # becomes the X-Amzn-...-Session-Id header
        contentType="application/json",           # Content-Type header (Â§B.4 note)
        accept="application/json",                # Accept header; unary JSON MVP
        payload=json.dumps(body).encode(),
    )
    if runtime_user_id:                           # only set when Identity is enabled (Â§D.4)
        kwargs["runtimeUserId"] = runtime_user_id # â†’ X-Amzn-Bedrock-AgentCore-Runtime-User-Id
    resp = _client.invoke_agent_runtime(**kwargs)
    return json.loads(resp["response"].read())    # single-JSON (unary) response
```

**Confirmed against installed source (Finding 5).** The boto3 contract is not an
open question: `botocore/data/bedrock-agentcore/2024-02-28/service-2.json.gz`
defines `InvokeAgentRuntime` with request members `agentRuntimeArn` (uri),
`runtimeSessionId` (header `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`),
`payload` (body), the optional `contentType` (header `Content-Type`) and `accept`
(header `Accept`) MIME members, and â€” relevant to Â§D.4 â€” `runtimeUserId` (header
`X-Amzn-Bedrock-AgentCore-Runtime-User-Id`); the response payload member is
`response` of shape `ResponseStream`, so `resp["response"].read()` is correct.
`invoke_runtime` sets `contentType`/`accept` to `application/json` explicitly
rather than relying on server defaults (Finding 3); the post-MVP SSE/streaming
path (Â§A.2) is the only place that flips `accept` to `text/event-stream`.
There is **no** separate `InvokeAgentRuntimeForUser` data-plane operation â€” the
per-user invoke is the same `InvokeAgentRuntime` call with the `runtimeUserId`
header set. The SigV4-signed `httpx` fallback (reusing
`agent/gateway_client.py::SigV4Auth`, signing service `bedrock-agentcore`) is kept
**only** as a botocore version-pin contingency; `api/requirements.txt` therefore
pins a botocore version new enough to include the 2024-02-28 model (so the Lambda
bundle ships the data-plane client).

### B.5 Auth (AWS_IAM now; Cognito deferred)

Two layers:
- **Edge â†’ thin API:** the Function URL uses `AuthType=AWS_IAM` so callers sign
  with SigV4 (the frontend/dev hits it with signed requests, mirroring the
  Task-4 inbound decision and the user's "keep AWS_IAM for now"). The
  `project_id`/user identity for the demo is carried in the request body /
  a dev header for now; Cognito JWT is the dev-mode upgrade that would populate
  a real principal (see Â§D.3 and Out of Scope).
- **Thin API â†’ Runtime:** the Lambda's execution role is granted
  `bedrock-agentcore:InvokeAgentRuntime` on the Runtime ARN; the data-plane call
  is SigV4-signed by boto3 automatically. The Runtime is deployed with **no
  `authorizer_configuration`**, which is how the L1 expresses AWS_IAM/SigV4 (the
  property has no AWS_IAM value â€” Â§E.3, Finding 2), so the signed invoke is
  accepted â€” no Cognito needed now.
  - **When Identity is later enabled** (Â§D.4, opt-in), the thin API also sends
    `runtimeUserId=ident.developer_id`; that per-user invoke requires an
    additional IAM action beyond `InvokeAgentRuntime`. The action name is
    **knowable now from installed source** (Finding 2): the botocore model
    `bedrock-agentcore/2024-02-28/service-2.json.gz` documents on
    `InvokeAgentRuntime` â€” "If you are making a call to `InvokeAgentRuntime` on
    behalf of a user ID with the `X-Amzn-Bedrock-AgentCore-Runtime-User-Id`
    header, You require permissions to **both** actions
    (`bedrock-agentcore:InvokeAgentRuntime` and
    `bedrock-agentcore:InvokeAgentRuntimeForUser`)." So when
    `MAHALO_IDENTITY_ENABLED=true` the Lambda role is granted **both**
    `bedrock-agentcore:InvokeAgentRuntime` and
    `bedrock-agentcore:InvokeAgentRuntimeForUser` on the Runtime ARN. Note there
    is no separate `InvokeAgentRuntimeForUser` *API operation* â€” the per-user
    invoke is still the same `InvokeAgentRuntime` call with the `runtimeUserId`
    header set â€” but `InvokeAgentRuntimeForUser` is a distinct IAM *action* that
    the caller must be authorized for. For the AWS_IAM MVP, Identity is off and
    `runtimeUserId` is not sent, so only `InvokeAgentRuntime` is required.

`api/app/auth.py` exposes a `current_identity` dependency that, for the MVP,
returns a fixed dev identity (`developer_id="dev-6"`, `role="developer"`) unless
overridden by a request field/header â€” faithfully matching the Task-1/2 demo
identity. When Cognito lands, this dependency is the single place to swap in JWT
claim extraction; nothing else changes.

### B.6 Thin-API error handling

| failure | recoverable? | caller receives | logged |
|---|---|---|---|
| Runtime invoke throws (`ThrottlingException`, `ServiceException`) | yes (retryable) | HTTP 502 `{detail}` | `logger.exception` at API |
| Runtime returns `{"status":"error",...}` | depends | HTTP 200 with `success=false` + message (mirrors mahalo-dock `ActionResult`) | warning |
| validation (empty message) | yes | HTTP 422 (FastAPI/pydantic) | â€” |
| missing `interrupt_id` on approve | yes | HTTP 422 | â€” |
| credentials/role missing | no (fatal config) | HTTP 500 | error |

The thin API never retries writes blindly â€” an `approve` is **not** auto-retried
on a 5xx (it could double-apply a write); it surfaces the error for the user to
re-approve explicitly.

---

## C. HITL over the API boundary

The stdin loop in `agent/chat.py::_ask` cannot run on Runtime. The native Strands
interrupt is session-serialized (investigation Â§3.2: `SessionAgent.from_agent`
captures `interrupt_state`, the AgentCore Memory manager persists it as the
`stateType="AGENT"` event and restores it in `read_agent`), so the gate becomes a
**two-call protocol** that maps onto `POST /chat` â†’ `POST /chat/approve`.

### C.1 The contract: lowest-risk restore (Finding 4 â€” contract flipped)

The investigation offers three options. The prior revision made the *unproven*
Option B (cross-invocation restore under the default
`filter_restored_tool_context=True`) the contract; the review correctly flagged
that the headline HITL path was load-bearing on a behavior the author could not
prove offline, while the robust path was relegated to an escape hatch. **Decision
(revised): make the lowest-risk path the contract and demote Option B to an opt-in
optimization.** Concretely:

- **Contract (primary): cross-invocation interrupt-state restore with
  `filter_restored_tool_context=False` for any session that carries a pending
  write.** The thin API stays fully stateless (session id is the only key; Memory
  is the only state). With the tool-context filter off, `list_messages` does NOT
  strip the open `toolUse`/`toolResult` from the restored message list, so **the
  one filter-driven collision is removed**: the filtered-message-list channel no
  longer disagrees with the separate `interrupt_state` channel by construction.
  The **residual** interrupt-state â†” message-list agreement across a cold process
  boundary (whether `_fix_broken_tool_use` in `RepositorySessionManager.initialize`
  and the restored `pending_tool_execution` compose cleanly â€” the item
  investigation Â§3.3 flags as not provable offline) is thereby **reduced to the
  single Â§C.5 live gate**, with Option C as the fallback if the gate fails. This
  is a small,
  additive change threaded through `build_memory_session_spec` via a
  `pending_write` flag and surfaced as a new `MemorySessionSpec` field (the three
  concrete edits are enumerated in Â§C.4); the explicit resulting flag value for
  pending-write sessions is **`filter_restored_tool_context=False`**.
  Non-pending-write sessions keep the Task-5 default (`True`) unchanged.
- **Opt-in optimization (Option A): warm-VM in-process agent cache.** When the
  same microVM serves both legs, reuse the in-process agent keyed by
  `context.session_id` so the approve leg never cold-rebuilds and the interrupt
  state never round-trips at all. This is a latency layer *under* the contract; a
  cache miss falls through to the stateless restore above, which is always
  correct. Off by default (`MAHALO_RUNTIME_SESSION_CACHE`, Â§D.2).
- **Opt-in optimization (Option B): the default `filter_restored_tool_context=True`
  cross-invocation restore**, enabled only after the live gate (Â§C.5) proves the
  three-channel interaction composes cleanly. Until then it is NOT the contract.
- **Documented fallback (Option C): explicit `pending_action` proposal** ported
  from mahalo-dock â€” executed on approve by a small dispatcher in the entrypoint,
  never relying on an in-flight interrupt. It changes the *agent-internal*
  mechanism, not the thin-API surface, so it is invisible to the frontend.

Rationale for picking the `filter=False` restore over Option A as the *contract*:
it does not depend on Runtime same-session VM affinity (a best-effort platform
behavior) for correctness, keeps the thin API genuinely stateless, and removes the
only proven collision deterministically rather than hoping it does not fire. The
live gate (Â§C.5) still runs end-to-end, but it now *confirms* a path designed to
be safe rather than *deciding* whether an unproven path is usable.

### C.2 The two calls, concretely

**Call 1 â€” `POST /chat {message:"create a feature branch for PAY-109"}`:**
thin API â†’ Runtime `invoke({action:"chat", prompt:...})` with session header S.
Entrypoint builds+attaches agent for S, calls `agent(prompt)`. The
`github_create_branch` gate fires `event.interrupt("write_approval",
reason=build_proposal(...))` â†’ `stop_reason=="interrupt"`. The per-turn Memory
hook persists the open toolUse + interrupt state under S. Entrypoint returns
`{"status":"pending_approval","proposal":{action:"create_branch", system:"github",
params:{...}, description:"Create branch 'feature/PAY-109' in payment-service...",
interrupt_id:"<id>"}, "session_id":S}`. **Nothing written** (the tool body never
ran). The thin API relays the proposal verbatim.

**Call 2 â€” `POST /chat/approve {session_id:S, interrupt_id:"<id>", approved:true}`:**
thin API â†’ Runtime `invoke({action:"approve", decision:"APPROVE",
interrupt_id:"<id>"})` with session header S. A fresh build+attach for S restores
`_interrupt_state` (and history) from Memory. Entrypoint calls
`agent([{ "interruptResponse": { "interruptId": interrupt_id, "response":
"APPROVE" }}])`. `agent.__call__` does `self._interrupt_state.resume(prompt)`
(investigation Â§3.2), the gate's `event.interrupt(...)` now **returns** `"APPROVE"`,
and the tool body runs (the real POST) without re-invoking the model because
`pending_tool_execution` was restored. On a closed non-interrupt result the
entrypoint emits the `[SYSTEM]` breadcrumb (Â§C.3) and returns
`{"status":"complete","response":...}`. On `REJECT`, the hook sets
`event.cancel_tool` (already in `agent/approval.py`), nothing is written, and no
breadcrumb is emitted.

**The `interrupt_id` contract â€” grounded in the `strands` interrupt model
(Finding 5).** The two-call protocol hinges on three facts, each now cited to
installed source in `agent/.venv/Lib/site-packages/strands/`:

1. **The id the chat leg reads.** `strands/types/interrupt.py` defines
   `@dataclass class Interrupt` with a field **`id: str`** documented "Unique
   identifier. Treat as opaque: pass it back to resume the agent, do not parse"
   (lines ~17-28). `AgentResult.interrupts` is the list of these `Interrupt`
   objects (the module docstring's worked example iterates
   `for interrupt in result.interrupts:` and builds
   `{"interruptResponse": {"interruptId": interrupt.id, "response": "A"}}`, lines
   ~50-56). So the chat leg's `itr.id` (Â§A.4 step 5) is exactly this field â€” no
   re-derivation.
2. **The resume matches by id, not positionally.**
   `strands/interrupt.py::_InterruptState.resume` (lines 121-152) reads
   `interrupt_id = content["interruptResponse"]["interruptId"]`, then does a
   **dict-key match**: `if interrupt_id not in self.interrupts: raise KeyError(...)`
   and `self.interrupts[interrupt_id].response = interrupt_response`
   (`self.interrupts` is `dict[str, Interrupt]` keyed by id). So the approve leg
   must echo the *same* id string; an unknown id raises `KeyError` (mapped to the
   `no_pending_interrupt` error envelope â€” Edge cases).
3. **The id survives serialize â†’ Memory â†’ restore.**
   `_InterruptState.to_dict`/`from_dict` (lines ~187-189, 233-236) serialize and
   rebuild `self.interrupts` **keyed by the same `interrupt_id`** string
   (`{interrupt_id: Interrupt(**interrupt_data) for interrupt_id, interrupt_data
   in data["interrupts"].items()}`), and investigation Â§3.2 shows
   `SessionAgent.from_agent`/`initialize_internal_state` route that blob through
   the AgentCore Memory `stateType="AGENT"` event. So the id the chat leg returned
   is stable across the cold-process round-trip and still keys the restored
   pending interrupt on the approve leg.

The one thing source alone cannot prove is whether the restored
`pending_tool_execution` composes cleanly with the restored message list across a
cold boundary â€” that remains the single Â§C.5 live gate (the `filter=False`
contract of Â§C.1/Â§C.4 removes the one filter-driven collision; the residual is
measured live). The id matching above is NOT part of that uncertainty: it is
grounded.

### C.3 Preserving the `[SYSTEM]` breadcrumb + branchâ†’commitâ†’PR chaining

The breadcrumb logic and its hard-won timing fix (defer the breadcrumb until a
resume returns a **non-interrupt** result, so an open toolUse/toolResult pair is
never split â€” see `agent/chat.py::_ask` docstring and the Task-4 live fix) must
be preserved verbatim. **Refactor** the two private helpers out of
`agent/chat.py` into a shared module so both the CLI and the Runtime entrypoint
use one implementation:

- New `agent/hitl.py` holding `emit_system_signal(agent, proposal)` (moved from
  `_emit_system_signal`, unchanged templates) and a small
  `resume_once(agent, interrupt_id, decision)` helper that performs one resume
  and reports whether the cycle closed. **This is the single canonical resume
  helper and the single canonical module** (Finding 4): there is no
  `resume_decision` and no resume helper in `agent/runtime_session.py`. Its one
  signature â€” `resume_once(agent, interrupt_id: str, decision: "APPROVE" |
  "REJECT") -> AgentResult` â€” is stated here once; the Â§A.1 entrypoint skeleton
  imports it as `from agent.hitl import emit_system_signal, resume_once`, and
  `agent/runtime_session.py` exports only `build_and_attach` (Â§D.2).
- `agent/chat.py::_ask` and `agent/chat.py::_emit_system_signal` are rewired to
  call `agent/hitl.py` (behavior-preserving refactor; the DIRECT CLI baseline
  tests must stay green â€” this is a pure extraction).

On Runtime the chain is driven across *client* calls: each approved write is one
`POST /chat/approve`; after the branch approve closes its cycle, the breadcrumb is
appended to history (persisted to Memory), so when the user asks to commit, the
next `POST /chat` turn sees the breadcrumb and proposes `github_commit_files`
instead of re-proposing the branch â€” identical semantics to the CLI, just split
across HTTP calls. The six writes stay gated because `WriteApprovalHook` is
attached unchanged by `build_agent` (both DIRECT and GATEWAY).

### C.4 The sharp edge, reduced to one live gate (Finding 4)

Investigation Â§3.3 and the review both confirm the collision: with
`filter_restored_tool_context=True` (the Task-5 default in `agent/memory_client.py`),
`AgentCoreMemorySessionManager.list_messages` strips `toolUse`/`toolResult` from
the **restored message list**, while the pending open toolUse comes back through
the **separate** `interrupt_state` restore channel, and
`RepositorySessionManager.initialize` runs `_fix_broken_tool_use` as a third path
that rewrites mismatched pairings. Across a cold process boundary these three can
disagree on the post-approve model turn.

**Design position (revised, non-optional and pre-decided):** the contract removes
the *filter-driven* collision deterministically rather than reacting to it. When
the entrypoint (re)builds the agent for a session that is **in a pending-write
state** (an approve leg, or any build where the restored `interrupt_state` carries
a `pending_tool_execution`), the Memory manager is assembled with
**`filter_restored_tool_context=False`** so the restored message list keeps the
open `toolUse`/`toolResult` intact and no longer disagrees with the interrupt-state
channel. For all other sessions the flag stays `True` (Task-5 behavior,
byte-for-byte).

**The three concrete edits this requires (Finding 3 â€” verified against
`agent/memory_client.py`).** Today `MemorySessionSpec` carries only
`session_id`/`actor_id`/`region`/`memory_id` and the flag is hardcoded
`filter_restored_tool_context=True` inside `build_memory_session_manager` (line 94
of `agent/memory_client.py`), so the spec cannot carry a per-session value yet.
Make it carriable with exactly these three additive edits (default preserves
Task-5 behavior byte-for-byte):

1. **`MemorySessionSpec` gains a field** `filter_restored_tool_context: bool = True`
   (default `True`).
2. **`build_memory_session_spec(session_id, actor_id, *, region, pending_write:
   bool = False)`** sets the new field to `filter_restored_tool_context=(not
   pending_write)` on the returned spec. (`pending_write` is itself threaded in
   from `build_agent`/`build_and_attach` per Â§D.2.)
3. **`build_memory_session_manager`** passes
   `filter_restored_tool_context=spec.filter_restored_tool_context` into the
   `AgentCoreMemoryConfig(...)` constructor **instead of the hardcoded `True`**.

Net effect, stated explicitly per the review: pending-write sessions â‡’
`filter_restored_tool_context=False`; every other session â‡’ `True` (the exact
Task-5 default, so DIRECT/GATEWAY/CLI and the Task-5 Memory tests are unchanged).

What this does and does not guarantee (Finding 4): `filter=False` eliminates the
*one* collision the review confirmed â€” `list_messages` stripping the open
tool-use. It does **not** by itself prove the full three-channel interaction,
because `_fix_broken_tool_use` still runs unconditionally in `initialize` and the
open tool-use also arrives through the separate
`interrupt_state.pending_tool_execution` channel; whether those agree across a
cold boundary is exactly the item investigation Â§3.3 could not prove offline. So
the honest framing is: the filter-driven collision is removed; the residual
agreement is reduced to the single Â§C.5 live gate (which **confirms** a path
designed to be safe), with Option C as the fallback if the gate fails.

How "pending-write state" is known at build time: on the `chat` leg the agent is
built with `pending_write=False` (there is no pending write yet); if that turn
interrupts, the next (`approve`) leg is explicitly a pending-write build, so it is
built with `pending_write=True`. The entrypoint knows which leg it is from
`payload["action"]` (`chat` vs `approve`), so the flag is set deterministically
from the request, not guessed.

Option C remains the documented fallback if the live gate still shows a
`ValidationException` (toolResult/toolUse mismatch) despite `filter=False`: carry
the proposal out-of-band as an explicit `pending_action` object (ported from
mahalo-dock's `ChatSession.pending_action`), executed on approve via a small
`execute_proposed_action`-style dispatcher inside the entrypoint, never relying on
the in-flight interrupt. The thin-API surface is unchanged either way.

### C.5 HITL live verification gate

Deploy the Runtime, then via the thin API: (1) `POST /chat` a write â†’ confirm a
`pending_approval` proposal and **no** write; (2) `POST /chat/approve approved=true`
â†’ confirm exactly one write and no `ValidationException` (this is the test that the
`filter_restored_tool_context=False` pending-write build composes cleanly across a
cold rebuild); (3) `POST /chat/approve approved=false` on a fresh proposal â†’
confirm nothing written; (4) run the branchâ†’commitâ†’PR chain across three approves
and confirm no step is re-proposed. This is billable and operator-run (DEPLOY
POLICY: deferred). The gate now **confirms** the contract path (designed to be
safe); if step (2) still raises a `ValidationException`, that is the trigger to
fall back to Option C (Â§C.4), not a surprise that invalidates the headline design.

---

## D. Sessions + Memory + Identity convergence

### D.1 Session id wiring (header â†’ Strands/Memory)

Real per-request session ids finally flow in. The thin API sets `runtimeSessionId
= req.session_id or uuid4` (Â§B.4); the platform delivers it as the session header;
the entrypoint reads `context.session_id` (investigation Â§2.1) and threads it into
`build_agent(session_id=context.session_id, memory=True, developer_id=...)`. The
mapping (investigation Â§2.3) is unchanged from Task 5:

| Runtime concept | Strands/Memory concept | source |
|---|---|---|
| `context.session_id` (header) | `AgentCoreMemoryConfig.session_id` | thin API â†’ header â†’ entrypoint |
| logged-in user (`developer_id`) | `AgentCoreMemoryConfig.actor_id` | request body / dev identity |
| `MAHALO_MEMORY_ID` | `AgentCoreMemoryConfig.memory_id` | Runtime env var (CfnMemory output) |

### D.2 Build cadence â€” rebuild-per-invocation, with an optional warm-VM cache

**Decision: build + `attach_memory` the agent per invocation** (investigation Â§2.3,
open question 2). Rebuild is cheap (model construction is lazy/offline) and the
only live cost is the one `ListEvents` rehydrate in `attach_memory`, which is
inherent to resuming a session. A new helper `agent/runtime_session.py::build_and_attach(session_id,
developer_id, role="developer", *, pending_write=False)` encapsulates:
`build_agent(memory=True, session_id=..., developer_id=..., role=...)` â†’ if
GATEWAY, `attach_gateway_tools` â†’ `attach_memory` (with the `pending_write` flag
threaded into the Memory spec per Â§C.4). It returns the agent plus the GATEWAY
teardown handle. The `chat` leg passes the request `role`; the `approve` leg
lets `role` default (Finding 4) because the resume replays
`pending_tool_execution` without a model call, so the system prompt the `role`
selects is never re-consumed â€” a different approve-leg `role` yields an identical
resume.

An **optional** in-process cache keyed on `context.session_id` (Option A
fast-path, Â§C.1) with idle eviction (a small dict + a monotonic-clock LRU, bounded
size, evict on TTL) may skip the rebuild+rehydrate when the same warm VM serves a
same-session follow-up. It is a performance layer only: a cache miss (cold VM, new
session, or evicted entry) falls through to the per-invocation build, which is
always correct. The cache is **off by default** behind a flag
(`MAHALO_RUNTIME_SESSION_CACHE`, default false) so the MVP and the offline gate
never depend on it.

**Cache correctness across the approve window (Finding 7).** When the cache is
enabled, the two HITL legs for one session must never hold two divergent agent
objects for the same session id. The rule is **exactly one of these two paths per
approve leg, never both in flight:**
- **(a) hit:** the approve leg finds the *same* cached chat-leg agent (which still
  carries the in-memory `interrupt_state`) and resumes it directly â€” the interrupt
  state never round-trips through Memory, which is the whole point of Option A.
- **(b) miss:** the approve leg does a cold `build_and_attach(pending_write=True)`
  (`filter_restored_tool_context=False`, Â§C.4) restoring the interrupt state from
  Memory, and on a cache miss **no cached entry for S is consulted or created for
  the approve resume**; after the cycle closes (approve returns), any pre-existing
  cache entry for S is **invalidated** so a subsequent `/chat` turn rebuilds
  cleanly from Memory.
This forbids the race the review flagged (a cached chat-leg agent with in-memory
interrupt state coexisting with a Memory-restored approve-leg agent for the same
S). It stays a documented constraint of the opt-in path; with the cache off
(the MVP), every leg is a cold build through Memory and the question does not
arise.

### D.3 Memory stays additive/opt-in

Memory is enabled on the Runtime purely by env (`MAHALO_MEMORY_ENABLED=true`,
`MAHALO_MEMORY_ID=<CfnMemory output>`) injected via the L2
`Runtime(environment_variables=...)` map (Â§E.3). The DIRECT/GATEWAY CLI and all Task-5 tests are untouched: `build_agent`
already resolves `memory` from the arg or `settings.memory_enabled`, so with the
env unset locally nothing changes. The Task-5 construction boundary holds â€”
`build_agent` assembles only the offline `MemorySessionSpec`; `attach_memory` is
the single AWS touch, called from the entrypoint (online, exec-role creds), which
is exactly the posture the investigation Â§2.4 blesses for Runtime.

### D.4 Identity â€” WAT path designed, but descoped from the AWS_IAM MVP (Finding 1)

The prior revision asserted the platform mints and delivers a Workload Access
Token to the agent so `@requires_api_key` brokers the Jira key. The review
flagged â€” and re-verification against installed source **confirms** â€” that this
does not hold under the AWS_IAM/SigV4 inbound auth this task selected:

```python
# bedrock_agentcore/identity/auth.py::_get_workload_access_token  (lines 350-363)
token = BedrockAgentCoreContext.get_workload_access_token()
if token is not None:
    return token
else:
    if os.getenv("DOCKER_CONTAINER") == "1":          # i.e. running in the Runtime container
        raise ValueError(
            "Workload access token has not been set. If invoking agent runtime via "
            "SIGV4 inbound auth, please specify the X-Amzn-Bedrock-AgentCore-Runtime-User-Id "
            "header and retry. ...runtime-oauth.html")
    return await _set_up_local_auth(client)
```

So under SigV4, the WAT is tied to the caller supplying
`runtimeUserId` (header `X-Amzn-Bedrock-AgentCore-Runtime-User-Id`); absent that,
the `@requires_api_key`-decorated `jira_create_story` raises `ValueError` inside
the container. Two honest consequences and the chosen resolution:

**Decision (MVP): Identity is OFF for the AWS_IAM phase.** The Runtime is deployed
with `MAHALO_IDENTITY_ENABLED=false`, the thin API does not send `runtimeUserId`,
and the Â§E.5 live gate **does not** include the Identity-brokered
`jira_create_story` write. This keeps the task honest about what the AWS_IAM mode
can actually demonstrate â€” Memory and HITL round-tripping â€” and matches the user's
"keep AWS_IAM for now; Cognito when I move to development mode." `jira_create_story`
runs with its static env-configured key (the Task-1/2 behavior) when Identity is
off, so the write still works in the demo; it just is not *brokered*.

**Enablement path (opt-in, designed now so it is a config flip later):** the WAT
brokering is wired end-to-end but gated, so it can be turned on without redesign
once `runtimeUserId` is threaded or Cognito lands:

- **Thin API:** when `MAHALO_IDENTITY_ENABLED=true` on the Runtime, the thin API
  passes `runtimeUserId=ident.developer_id` to `invoke_agent_runtime` (Â§B.4). This
  is the header the SDK error names; supplying it is what lets the platform mint +
  deliver the WAT under SigV4.
- **Env:** `MAHALO_IDENTITY_ENABLED=true` +
  `MAHALO_IDENTITY_JIRA_PROVIDER=mahalo-jira-apikey` (provider already provisioned
  in `MahaloMemoryIdentityStack`).
- **Execution role (grounded now, provisioned only on enablement â€” Finding 2):**
  grant the Runtime role the AgentCore Identity data-plane actions so the
  server-side WATâ†’API-key exchange works. The action names are **grounded to
  installed source**, not deferred: the `@requires_api_key` path uses
  `bedrock_agentcore/services/identity.py::IdentityClient`, whose `get_api_key`
  calls the data-plane op `get_resource_api_key` (line 300) and whose
  user-scoped WAT mint calls `get_workload_access_token_for_user_id` (line 151);
  the installed botocore `bedrock-agentcore/2024-02-28` model names these
  operations `GetResourceApiKey` and `GetWorkloadAccessTokenForUserId`. So the
  IAM actions are **`bedrock-agentcore:GetResourceApiKey`** and
  **`bedrock-agentcore:GetWorkloadAccessTokenForUserId`**, scoped to the
  `mahalo-jira-apikey` provider and the `mahalo-agent` workload identity
  (investigation Â§4.3, Â§5.4). **This policy is provisioned only in the
  enablement path â€” it is NOT in the MVP execution role (Â§E.1)** â€” so the AWS_IAM
  MVP role claims nothing it does not need. (Non-user WAT variants
  `GetWorkloadAccessToken`/`GetWorkloadAccessTokenForJWT` exist too but are not
  used by the `runtimeUserId`/SigV4 brokering path, so they are not granted.)
- **Thin-API Lambda role:** grant **both**
  `bedrock-agentcore:InvokeAgentRuntime` and
  `bedrock-agentcore:InvokeAgentRuntimeForUser` on the Runtime ARN (Â§B.5). The
  user-scoped action `bedrock-agentcore:InvokeAgentRuntimeForUser` is named
  directly from the installed botocore `bedrock-agentcore/2024-02-28`
  `InvokeAgentRuntime` documentation (Finding 2) â€” it is grantable now, not a
  deferred unknown; it is simply not needed until Identity is enabled.
- **Workload identity:** `CfnWorkloadIdentity` (`mahalo-agent`) from
  `MahaloMemoryIdentityStack` is the hosted agent's workload identity, associated
  with the Runtime via the role/auth wiring (Â§E.3).
- **Verification:** the Identity-brokered write is proven only once this path is
  enabled (either `runtimeUserId` end-to-end under SigV4, or Cognito/OAuth inbound
  auth) â€” explicitly deferred past the AWS_IAM MVP.

**`AWS_PROFILE` is omitted (not set to empty) in the container** (Â§A.6
Dockerfile, Finding 1). `agent/config.py::aws_profile` then resolves to its
`"lava"` default; the patched `_build_bedrock_model` checks `botocore`
`available_profiles` and, because no `lava` profile exists in the container,
builds a **profile-less** `boto3.Session(region_name=...)` so boto3 resolves the
default credential chain = the execution role (investigation Â§5.4). This does
**not** rely on any `boto3.Session` construction-time raise (the review confirmed
`ProfileNotFound` is lazy, fired inside the model call outside the Session
constructor's `try/except` â€” Â§A.6); the profile decision is made explicitly
*before* the Session is constructed. It applies regardless of Identity being on
or off, and the real resolution path is covered by an offline unit test (Â§E.4).

Broadening Identity beyond the one `jira_create_story` path is additive decorator
application (investigation Â§4.3) and is left for a follow-up, not Task 6.

### D.5 Baseline preservation

Nothing in Aâ€“E edits the DIRECT/GATEWAY code paths or the Task-5 Memory/Identity
seams except the behavior-preserving `agent/hitl.py` extraction (Â§C.3), which is
covered by the existing `_ask` tests plus a new unit test asserting the extracted
helper matches. The offline gate (agent 69/1 + new Runtime tests, infra-cdk synth,
tools-lambdas 94, zero LangChain) must stay green (Â§E.4).

---

## E. IaC + offline-safety

### E.0 L1 vs L2 construct decision (Finding 1, HIGH) â€” adopt the L2 `agentcore.Runtime`

The investigation and all prior design iterations asserted the only Runtime
deploy surface in `aws-cdk-lib 2.273.0` was the L1 `CfnRuntime`/`CfnRuntimeEndpoint`.
**That reading was incomplete.** Re-verified this iteration against the installed
`infra-cdk/.venv/Lib/site-packages/aws_cdk/aws_bedrockagentcore/__init__.py`, the
module **also** ships a full L2 construct suite (jsii type names confirmed by
scanning the file's `jsii_type="aws-cdk-lib.aws_bedrockagentcore.*"` declarations):

- **`Runtime`** (L2 construct, `__init__` at line ~85818, `:resource:
  AWS::BedrockAgentCore::Runtime`). Keyword args: `agent_runtime_artifact`
  (required), `authorizer_configuration` (optional, **default
  `RuntimeAuthorizerConfiguration.iam()` â€” "IAM authentication"** per the arg
  docstring), `execution_role` (**optional** â€” "If not provided, a role will be
  created automatically"), `environment_variables`, `platform_version`
  (`PlatformVersion.V1|V2`), `network_configuration` (default
  `RuntimeNetworkConfiguration.usingPublicNetwork()`), `lifecycle_configuration`,
  `logging_configs`, `tracing_enabled`, `runtime_name`. It exposes
  `agent_runtime_arn`/`agent_runtime_id`/`agent_runtime_name` attributes, a `.role`
  property (the auto-created or supplied `IRole`), a `grant_principal`, and a
  `runtime.add_endpoint(name, description?, version?) -> RuntimeEndpoint`
  convenience (method at line ~85988).
- **`AgentRuntimeArtifact`** (abstract base, line ~4586) with classmethod
  factories: **`from_image_uri(container_uri)`** (line ~283 docstring: "Use this
  when referencing ECR images from **CloudFormation parameters** or cross-stack
  references â€¦ **No IAM permissions are automatically granted** â€” you must ensure
  the runtime has ECR pull permissions"), **`from_asset(directory, *, file=,
  platform=, exclude=, â€¦)`** (local Dockerfile dir â†’ CDK builds + pushes to ECR;
  wraps `DockerImageAssetOptions`), `from_ecr_repository(repository, tag?)`,
  `from_code_asset(â€¦)`, `from_s3(location, runtime, entrypoint)`.
- **`RuntimeAuthorizerConfiguration`** (abstract base, line ~74748) with
  `using_iam()`, `using_cognito(user_pool, user_pool_clients, â€¦)`,
  `using_jwt(discovery_url, â€¦)`, `using_o_auth(discovery_url, client_id, â€¦)`.
- **`RuntimeEndpoint`** (line ~86099) and `IamAuthorizer`/`CustomJwtAuthorizer`
  helpers.

**Decision: adopt the L2 `agentcore.Runtime`** (`infra-cdk` imports it as
`from aws_cdk import aws_bedrockagentcore as agentcore`, the same alias
`gateway_stack.py` already uses). Rationale:

- The L2 **auto-creates the execution role** with baseline permissions (ECR pull
  on the `from_asset`/`from_ecr_repository` paths, CloudWatch logging, X-Ray),
  deleting the hand-rolled role of the prior Â§E.1 â€” which, the review correctly
  noted, had omitted ECR pull entirely (Finding 2). We still grant the *app-level*
  permissions (Bedrock model, Memory, Gateway) onto `runtime.role` explicitly.
- IAM inbound auth is the L2 **default** (`authorizer_configuration` omitted â‡’
  `RuntimeAuthorizerConfiguration.iam()`), so the prior Â§E.3 `CfnParameter` +
  `CfnCondition` authorizer dance collapses to "pass nothing for AWS_IAM; pass
  `RuntimeAuthorizerConfiguration.using_cognito(...)` in the Cognito branch."
- The offline gate keeps its `CfnParameter` mechanism first-class via
  `AgentRuntimeArtifact.from_image_uri(CfnParameter.value_as_string)` â€” the
  docstring blesses exactly this (CloudFormation-parameter / cross-stack image
  URIs), so no `DockerImageAsset` is constructed on the offline branch and `cdk
  synth` stays Docker-free.
- `runtime.add_endpoint(...)` manages the endpoint + versioning, deleting the
  manual `CfnRuntimeEndpoint` + `apply_removal_policy` plumbing.

(The repo's *Gateway* stack stays on the L1 `CfnGateway` â€” it predates this and is
proven; there is no L2 `Gateway` benefit that justifies churning it. The L2 choice
here is scoped to the new Runtime stack, where it removes the most hand-rolled
L1 surface.)

### E.1 New stack: `infra-cdk/mahalo_infra/runtime_stack.py` (L2 `Runtime`)

A new `MahaloRuntimeStack`, wired in `infra-cdk/app.py` alongside the existing six
stacks (mirroring how `MahaloMemoryIdentityStack` was added). It provisions, in
order:

1. **Runtime artifact â€” flag-gated so synth is Docker-free (Finding 3 of the prior
   review; preserved).** Only in the operator-deploy branch (`MAHALO_BUILD_IMAGE=1`
   / `-c buildImage=1`) is a build-from-source artifact constructed â€”
   `agentcore.AgentRuntimeArtifact.from_asset("..", file="agent/Dockerfile",
   platform=ecr_assets.Platform.LINUX_ARM64)` (directory is the repo root so
   `agent/` is in Docker context; this is the path that invokes Docker at synth
   and lets the L2 auto-role grant ECR pull on the built repo). In the
   **offline/default branch no asset is constructed at all** â€” the artifact is
   `agentcore.AgentRuntimeArtifact.from_image_uri(CfnParameter(self, "AgentImageUri",
   default="000000000000.dkr.ecr.us-east-1.amazonaws.com/placeholder:latest")
   .value_as_string)` â€” so `cdk synth` never touches Docker (grounded: the
   `from_image_uri` docstring is explicitly the "CloudFormation parameters /
   cross-stack" path). Exact branch + tests in Â§E.4.
2. **The L2 `Runtime`** â€” `agentcore.Runtime(self, "MahaloRuntime",
   runtime_name="mahalo_agent_runtime", agent_runtime_artifact=<from step 1>,
   environment_variables={...} (Â§E.3), tracing_enabled=True,
   lifecycle_configuration=LifecycleConfiguration(idle_runtime_session_timeout=
   Duration.minutes(15), max_lifetime=Duration.hours(8)))`. For AWS_IAM/SigV4
   inbound auth, **`authorizer_configuration` is omitted** â†’ the L2 default
   `RuntimeAuthorizerConfiguration.iam()` applies (grounded: the `__init__`
   docstring). `execution_role` is **also omitted** so the L2 auto-creates the
   role with baseline ECR/logging/X-Ray permissions.
3. **App-level grants onto `runtime.role`** (the auto-created role, exposed by the
   L2 `.role` property). The L2 baseline covers ECR pull (on `from_asset`),
   CloudWatch Logs, and X-Ray; we add the application permissions the baseline does
   NOT include, mirroring the Â§5.4 least-privilege set:
   - `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream` on the
     Sonnet 4.5 inference-profile and the regional foundation-model ARNs it fans
     out to.
   - AgentCore Memory: `bedrock-agentcore:CreateEvent`, `ListEvents`, `GetEvent`,
     `RetrieveMemoryRecords` scoped to the `CfnMemory` ARN.
   - AgentCore Gateway invoke (GATEWAY mode) for the Gateway endpoint.
   - **ECR pull on the offline/`from_image_uri` branch only (Finding 2):** because
     `from_image_uri` grants **no** IAM (docstring), when that branch is taken the
     stack adds an explicit ECR-pull statement to `runtime.role` â€”
     `ecr:GetAuthorizationToken` on `*` plus `ecr:BatchGetImage` +
     `ecr:GetDownloadUrlForLayer` on the image repo ARN â€” so a container Runtime
     pulling a parameter-supplied image can still start. On the `from_asset`
     branch the artifact's `bind` wires ECR pull into the auto-role, so this
     explicit statement is not added (avoid double-grant). This closes the ECR gap
     the prior hand-rolled role had.
   - **No AgentCore Identity policy in the MVP role (Finding 2 of the prior
     review; preserved):** Identity is descoped from the AWS_IAM MVP (Â§D.4), so the
     MVP role does **not** carry the credential-provider actions. They are grounded
     to installed source (`bedrock-agentcore:GetResourceApiKey` +
     `bedrock-agentcore:GetWorkloadAccessTokenForUserId`, Â§D.4) and added to
     `runtime.role` only by the opt-in enablement path when
     `MAHALO_IDENTITY_ENABLED=true`.
   - CloudWatch Logs write is already in the L2 baseline; no extra statement
     needed for the MVP.
4. **Endpoint + output** â€” `endpoint = runtime.add_endpoint("default")` (the L2
   manages the `RuntimeEndpoint` + versioning), then
   `CfnOutput(self, "RuntimeArn", value=runtime.agent_runtime_arn)` for the thin
   API. (`endpoint` ARN is also exported if the thin API ever targets a specific
   endpoint; the data-plane `InvokeAgentRuntime` takes the runtime ARN.)

Cross-stack wiring: the stack reads `MahaloMemoryIdentityStack`'s `memory`
construct (for `MAHALO_MEMORY_ID` and the Memory ARN in the policy) and the
Gateway's MCP URL by direct construct reference passed through `app.py` â€” the same
no-`Fn.import_value` pattern `gateway_stack.py` uses.

**Teardown (Finding 6 of the prior review).** The L2 `Runtime` and its
`add_endpoint` `RuntimeEndpoint` are CDK constructs over
`AWS::BedrockAgentCore::Runtime`/`::RuntimeEndpoint`; the stack is destroyed as a
unit by `cdk destroy MahaloRuntimeStack` (Â§E.5), and the on-disk resources are the
CloudFormation resources plus the CDK-managed ECR asset (cleaned up with the
toolkit, not this stack). Where the L2 exposes the underlying `CfnResource`, apply
`RemovalPolicy.DESTROY` to match the Task-8 teardown posture; otherwise rely on the
stack-level destroy, which deletes the runtime and endpoint.

### E.2 Thin-API stack (with explicit dependency bundling â€” Finding 3)

Either a second stack `MahaloApiStack` or an added construct in the runtime stack
provisions the Function-URL Lambda for `api/`. **The Lambda MUST ship its
dependencies** (`fastapi`, `mangum`, `pydantic`, and a `boto3`/`botocore` new
enough for the `bedrock-agentcore` 2024-02-28 data-plane model, Â§B.4) â€” a plain
`Code.from_asset("../api")` would `ImportError` at cold start and could fall back
to the Lambda runtime's older bundled botocore. The bundling mechanism is
specified, gated the same way as the image build so `cdk synth` stays offline:

- **Deploy branch (`MAHALO_BUILD_IMAGE=1`, Docker available):**
  `aws_lambda.Function(self, "ApiFn", runtime=Runtime.PYTHON_3_13,
  handler="app.main.handler", code=Code.from_asset("../api",
  bundling=BundlingOptions(image=Runtime.PYTHON_3_13.bundling_image,
  command=["bash","-c","pip install -r requirements.txt -t /asset-output && cp -r
  app /asset-output"])))`. This installs `api/requirements.txt` into the asset so
  `fastapi`/`mangum`/`boto3` are present; `app/` is copied alongside.
  (Equivalent: `aws_lambda_python_alpha.PythonFunction`, which bundles from
  `requirements.txt` automatically â€” either is acceptable; the `BundlingOptions`
  form is chosen to avoid an extra alpha-module dependency.)
- **Offline/default branch (no Docker):** Docker-based bundling is **not** invoked
  during the offline gate. The Lambda is synthesized against a **pre-built
  dependencies layer** asset checked in under `api/` (or, for the pure-synth gate,
  `Code.from_asset("../api")` with the deps layer referenced by a
  `CfnParameter` layer ARN) so `cdk synth` produces the template with no Docker
  call. The Â§E.4 test asserts the offline branch neither runs Docker nor errors.

Then `fn.add_function_url(auth_type=FunctionUrlAuthType.AWS_IAM)`, the
execution-role grant `bedrock-agentcore:InvokeAgentRuntime` on the Runtime ARN
(plus `InvokeAgentRuntimeForUser` on the Identity-enablement path, Â§D.4), and env
`MAHALO_RUNTIME_ARN` from the `RuntimeArn` output. A `RuntimeApiUrl` `CfnOutput`
gives the frontend its endpoint. Keep it a separate stack for teardown
granularity; it depends on the runtime stack (direct reference).

### E.3 Env vars injected into the Runtime

The L2 `Runtime(environment_variables=...)` is how the agent process is configured
(investigation Â§5.2): `MAHALO_TOOL_MODE` (direct|gateway),
`MAHALO_GATEWAY_MCP_URL` (gateway mode), `MAHALO_MEMORY_ENABLED=true`,
`MAHALO_MEMORY_ID`, **`MAHALO_IDENTITY_ENABLED=false`** (Finding 1 â€” Identity is
off for the AWS_IAM MVP; flip to `true` only on the enablement path of Â§D.4),
`MAHALO_IDENTITY_JIRA_PROVIDER=mahalo-jira-apikey` (harmless when Identity is
off), `BEDROCK_MODEL_ID`, `AWS_REGION`, and the four mock `*_URL`s.
**`AWS_PROFILE` is deliberately NOT set** (Finding 1): it is omitted from
`environment_variables` (and the Dockerfile) so `agent/config.py` resolves the
`"lava"` default. The patched `_build_bedrock_model` (Â§A.6) then checks `botocore`
`available_profiles`; `"lava"` is absent in the container, so it builds a
profile-less `boto3.Session(region_name=...)` and boto3 resolves the default
credential chain = the execution role. This does **not** rely on any
`boto3.Session` construction-time raise (`ProfileNotFound` is lazy, fired inside
the model call â€” Â§A.6); the profile decision is made explicitly before the
Session is constructed. Setting `AWS_PROFILE=""` is still avoided â€” the fix
branches on `available_profiles`, not on an empty-string special case.

**Inbound auth mechanism on the L2 (grounded).** The L2 `Runtime` arg
`authorizer_configuration` **defaults to `RuntimeAuthorizerConfiguration.iam()`
("IAM authentication")** when omitted (verified: `Runtime.__init__` docstring,
line ~85818, and `RuntimeAuthorizerConfiguration.using_iam()` docstring "Use IAM
authentication (default). Requires AWS credentials to sign requests using SigV4",
line ~74748). So the AWS_IAM MVP simply **omits `authorizer_configuration`** â€” no
`CfnParameter`/`CfnCondition` dance is needed. A plain Python branch on a stack
flag picks the authorizer, which is cleaner and still synth-offline:

```python
inbound = self.node.try_get_context("inboundAuth") or "AWS_IAM"   # default AWS_IAM
authorizer = None                                                  # AWS_IAM -> L2 default iam()
if inbound == "COGNITO":                                            # dev-mode upgrade (opt-in)
    authorizer = agentcore.RuntimeAuthorizerConfiguration.using_cognito(
        user_pool, [user_pool_client])                             # or .using_jwt(discovery_url, ...)
runtime = agentcore.Runtime(self, "MahaloRuntime",
    runtime_name="mahalo_agent_runtime",
    agent_runtime_artifact=artifact,
    environment_variables=env,
    authorizer_configuration=authorizer)                           # None -> iam() default
```

This replaces the prior L1 `CfnRuntime.AuthorizerConfigurationProperty` wording
(which was correct for the L1 but moot now): on the L2, `using_cognito`/`using_jwt`
are the typed dev-mode upgrade, constructed only in that branch. (Open question 6
resolved: AWS_IAM now via the L2 default; Cognito/JWT is the dev-mode upgrade.)

### E.4 Offline-safety (the automated gate)

The gate must pass with **no network and no AWS creds**, mirroring Tasks 4/5:

- `cd infra-cdk && cdk synth --all` exit 0 producing a **seventh** template
  (`MahaloRuntimeStack`, plus the thin-API stack). The `from_asset` artifact (and
  Docker-based Lambda bundling) resolves/stages during `cdk synth` and can invoke
  the Docker CLI, which would violate the hard offline gate. The guard is
  therefore **precise about which artifact factory is called** (Finding 3): in the
  offline (default) branch the Runtime artifact is
  `AgentRuntimeArtifact.from_image_uri(CfnParameter.value_as_string)` â€” the L2
  factory the docstring designates for CloudFormation-parameter image URIs â€” which
  constructs **no `DockerImageAsset`**, so synth never touches Docker:

  ```python
  build_image = (self.node.try_get_context("buildImage")
                 or os.environ.get("MAHALO_BUILD_IMAGE") == "1")
  if build_image:                                   # operator deploy only
      artifact = agentcore.AgentRuntimeArtifact.from_asset(
          "..", file="agent/Dockerfile",
          platform=ecr_assets.Platform.LINUX_ARM64)  # builds + pushes to ECR
  else:                                             # offline gate: NO asset constructed
      image_uri = CfnParameter(self, "AgentImageUri",
          default="000000000000.dkr.ecr.us-east-1.amazonaws.com/placeholder:latest"
      ).value_as_string
      artifact = agentcore.AgentRuntimeArtifact.from_image_uri(image_uri)
  ```

  Tests asserting this (all in the infra-cdk suite):
  1. **offline branch:** run `app.synth()` with the flag unset â†’ assert (a) exit 0,
     (b) no Docker invocation (no `DockerImageAsset` in the construct tree / no
     image asset staged), and (c) the synthesized `AWS::BedrockAgentCore::Runtime`
     template references the `AgentImageUri` parameter for its container URI.
  2. **asset branch:** with the flag set â†’ assert the `from_asset` path is taken;
     this test is `skip`/`xfail` when Docker is unavailable so it never breaks the
     offline gate.
  3. **L2 shape:** assert the synthesized template has one
     `AWS::BedrockAgentCore::Runtime` with **no** JWT authorizer block (AWS_IAM
     default), an auto-created execution role carrying the Bedrock/Memory/Gateway
     statements (and, on the `from_image_uri` branch, the explicit ECR-pull
     statement), the expected `EnvironmentVariables`, and a
     `AWS::BedrockAgentCore::RuntimeEndpoint` from `add_endpoint("default")`.
  4. **thin-API bundling:** assert the offline branch synthesizes the API Lambda
     without invoking Docker (deps layer / `CfnParameter` path), and that the
     deploy branch would use `BundlingOptions` (skip/xfail without Docker).
- `import agent.runtime_app` and `BedrockAgentCoreApp()` + `@app.entrypoint`
  registration succeed offline (no creds) â€” a new agent unit test.
- **Credential-resolution check (Finding 1) â€” exercises the REAL path, not a
  forced raise.** An offline unit test asserts the patched `_build_bedrock_model`
  (Â§A.6) picks the profile from `available_profiles` rather than relying on a
  `Session` construction-time raise (which does not happen â€” the review verified
  `boto3.Session.__init__` does not raise and `ProfileNotFound` is lazy). Two
  cases:
  1. **container case:** patch `botocore.session.Session.available_profiles` to a
     list **without** `"lava"` (and `settings.aws_profile == "lava"`) â†’ assert
     `_build_bedrock_model` constructs `boto3.Session(region_name=...)` with **no**
     `profile_name` (default-chain = exec role). Assert via a `boto3.Session` spy
     that `profile_name` was not passed.
  2. **local case:** patch `available_profiles` to include `"lava"` â†’ assert the
     Session is built **with** `profile_name="lava"` (CLI behavior unchanged).
  The test must NOT mock `Session()` to raise `ProfileNotFound` â€” that would
  assert a behavior the installed `boto3` does not have and would mask the real
  bug. It guards against anyone re-introducing the construction-time-raise
  assumption or an `AWS_PROFILE=""` shortcut.
- `python -m agent.chat` DIRECT baseline unchanged (the `agent/hitl.py` extraction
  is behavior-preserving); `agent` suite stays green (69/1 + new Runtime/HITL
  unit tests).
- The thin API `api/app/main.py` imports offline (FastAPI + Mangum + boto3
  client construction is lazy; **do not** create the boto3 client at import â€”
  build it in a module-level lazy accessor so `import` needs no creds). A new
  `api/tests` unit test asserts import + a mocked `invoke_runtime` round-trip.
- **Container reproducibility check (Finding 5).** An offline test asserts
  `agent/requirements.txt` pins both `bedrock-agentcore==1.24.1` and
  `strands-agents==1.61.1` (verified present â€” the file already pins exactly these
  two, plus `boto3`, `httpx`, `pytest`). The ASGI harness deps `uvicorn` and
  `starlette` are **declared hard dependencies of `bedrock-agentcore==1.24.1`**
  (verified: its metadata requires `uvicorn>=0.34.2` and `starlette>=0.46.2` as
  base deps, not extras), so `pip install -r agent/requirements.txt` in the image
  pulls them transitively â€” the container ships the harness even though the local
  dev venv happens not to have `uvicorn` installed. The test asserts the two pins
  are present (regex over `requirements.txt`) rather than importing uvicorn, so it
  stays green offline regardless of the dev venv state. `langchain` is pulled by
  `bedrock-agentcore` only under its `langgraph`/`ragas` extras (never the base
  install), so the "zero LangChain" grep stays empty.
- `grep` for LangChain stays empty across `agent/`, `api/`, `infra-cdk/`.

### E.5 Deferred operator deploy runbook (not auto-run)

1. `aws sso login --profile lava`.
2. `cd infra-cdk && $env:MAHALO_BUILD_IMAGE="1"` then `cdk deploy
   MahaloMemoryIdentityStack MahaloGatewayStack MahaloMock*Stack --profile lava`
   (Memory/Gateway first so their outputs exist).
3. `cdk deploy MahaloRuntimeStack --profile lava` â€” the L2 `from_asset` artifact
   builds the ARM64 image and pushes to ECR, the L2 auto-creates the execution
   role (with the app-level grants added), and `Runtime` + `add_endpoint("default")`
   create the runtime and endpoint. Note `RuntimeArn`.
4. `cdk deploy MahaloApiStack --profile lava` â€” Function-URL Lambda wired to the
   Runtime ARN. Note `RuntimeApiUrl`.
5. Run the Â§C.5 HITL live gate and the two-invocation Memory persist/reload check
   (same session id across two `POST /chat` calls). **The Identity-brokered
   `jira_create_story` write is NOT part of this gate** (Finding 1, iter-1): it is
   descoped from the AWS_IAM MVP. `jira_create_story` still works in the demo via
   its static env key (Identity off). Brokering is exercised only after the Â§D.4
   enablement path is turned on (`runtimeUserId` end-to-end under SigV4, or
   Cognito inbound auth).
   - **MEASURE the invocation-budget open item (Edge cases / Finding 1 this
     iteration):** time a representative code-gen `github_commit_files` invocation
     end-to-end and note whether the platform severs the synchronous call;
     cross-check the published synchronous `InvokeAgentRuntime` timeout in the
     AgentCore Runtime limits/quotas doc. If at risk, switch to the SSE entrypoint
     (Â§A.2) before the demo. No invocation-budget number is assumed before this
     measurement.
6. `cdk destroy MahaloApiStack MahaloRuntimeStack ...` to stop spend (Task-8
   teardown posture â€” the explicit `RemovalPolicy.DESTROY` on the Runtime L1s
   ensures clean deletion, Â§E.1).

---

## Edge cases

- **Missing session header** (direct Runtime call bypassing the thin API): the
  entrypoint generates a uuid, logs a warning, and **returns that generated uuid
  as `session_id`** (Â§A.3/Â§A.4 step 2) so the caller can thread the follow-up on
  the same Memory conversation. Memory keys a fresh conversation only on the
  first such call. Not a failure. (Via the thin API this never fires â€” Â§B.4
  always sets the header.)
- **Approve with a stale/unknown `interrupt_id`** (VM recycled, interrupt already
  resolved, or wrong id): `_interrupt_state.resume` finds no matching pending
  interrupt â†’ return `{"status":"error","error":{type:"no_pending_interrupt"}}`;
  the thin API surfaces `success=false` so the user re-issues the request. No
  write occurs.
- **Approve when Memory restored no interrupt state** (cold VM + Option-B restore
  failed): same `no_pending_interrupt` error; this is the trigger to apply the
  Â§C.4 fallback. Fail safe (nothing written), never silently execute.
- **GATEWAY mode MCP double-start**: avoided by reusing the Task-4 single-start
  discipline (`attach_gateway_tools` owns the start; stop in `finally`) inside the
  entrypoint â€” do **not** wrap in `with mcp_client:`.
- **Model timeout on a huge code-gen commit** (Finding 7 + Finding 1 this
  iteration): the 300s `read_timeout` from `settings.bedrock_read_timeout` is
  preserved; if exceeded, the agent call raises â†’ caught â†’ `{"status":"error"}`.
  Re-verification against installed source shows the lifecycle config exposes
  **only** `idle_runtime_session_timeout` (default **900s / 15 min**) and
  `max_lifetime` (default **28800s / 8 hr**) â€” grounded in the installed CDK L1
  docstring (`infra-cdk/.venv/Lib/site-packages/aws_cdk/aws_bedrockagentcore/
  __init__.py`, lines ~183 and ~750-751). These are the session *idle* timeout and
  instance *lifetime*, **not** a per-invocation request timeout, so there is **no
  L1 knob** to raise a single invocation's limit (this part IS verified). **What
  is NOT grounded (Finding 1): the existence and magnitude of a synchronous
  `InvokeAgentRuntime` per-invocation budget.** The installed source does not
  document it, and neither this design nor the investigation can cite a number for
  it. **The prior "on the order of minutes" assertion is therefore WITHDRAWN** and
  demoted to a measured open-verification item (below), not stated as fact.
  Consequence that IS grounded and acted on: set `idle_runtime_session_timeout`
  generously (e.g. 15 min â€” at/above the default) so a warm session survives the
  approve round-trip, and `max_lifetime` to a few hours. The streaming/SSE
  entrypoint (Â§A.2, Out of Scope for the MVP) remains the escape hatch for any
  single invocation that risks a long-running budget, because it keeps the
  connection alive with incremental output.
  - **OPEN VERIFICATION ITEM (measured on first deploy, not asserted):** on the
    Â§E.5 operator deploy, MEASURE the observed end-to-end time of a representative
    code-gen `github_commit_files` invocation and whether the platform severs a
    long synchronous `InvokeAgentRuntime` call. Cross-check against the AgentCore
    Runtime **limits/quotas** doc
    (`https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/` runtime
    quotas page) for the published synchronous invocation timeout. If a
    representative commit is at risk of exceeding it, switch the entrypoint to the
    SSE path (Â§A.2) before the demo. Until measured, no invocation-budget
    magnitude is treated as known.
- **Concurrent same-session calls** (double-click approve): the warm-VM cache (if
  on) could race; the MVP (cache off, rebuild-per-invocation) serializes through
  Memory's event log. Document that the frontend should disable the approve
  button after the first click; idempotency beyond that is out of scope.

## Input validation (entrypoint)

| input | rule | on failure |
|---|---|---|
| `action` | required; one of `chat`/`approve` | `{"status":"error","error":{type:"bad_action"}}` |
| `prompt` | required non-empty string when `action=chat`; length cap (e.g. 32 KB) | error envelope |
| `decision` | required `APPROVE`/`REJECT` when `action=approve` | error envelope |
| `interrupt_id` | required non-empty when `action=approve` | error envelope |
| `developer_id` | optional; default `dev-6`; must match `^dev-\d+$` if supplied | ignore malformed, fall back to default + warn |
| `role` | optional; must be a key in `ROLE_PROMPTS`; default `developer` | fall back to default |

The entrypoint owns ALL semantic validation (the harness only 400s malformed
JSON). Invariant: **no write tool body executes without a prior approved
interrupt** â€” owned by `WriteApprovalHook` (agent layer), unchanged; the entrypoint
cannot bypass it because it only ever calls `agent(...)`.

## Testability

- **Unit (offline, in the gate):** entrypoint request/response shaping and
  validation with a stubbed `build_and_attach` (no AWS); `build_and_attach`
  composition with mocked `attach_memory`/`attach_gateway_tools`; `agent/hitl.py`
  breadcrumb/timing logic (ported from the existing `_ask` resume-regression
  tests); thin-API router with a mocked `invoke_runtime`; CDK assertions that
  `MahaloRuntimeStack` synthesizes one `AWS::BedrockAgentCore::Runtime` (L2
  `Runtime`) + `AWS::BedrockAgentCore::RuntimeEndpoint` + the auto-created exec
  role with the expected app-level policies and env, in both `MAHALO_BUILD_IMAGE`
  on/off (`from_asset` vs `from_image_uri`) branches.
- **Integration (live, deferred/operator):** the Â§C.5 HITL gate, the
  two-invocation Memory persist/reload, and the Identity-brokered write â€” all
  through the deployed thin API. These are billable and NOT in the offline gate.
- A design note on testability: the one thing not fully unit-testable is the
  cross-invocation `interrupt_state` â†” `filter_restored_tool_context` interaction
  (Â§C.4) â€” it requires a real Runtime + Memory. That is why it is the explicit
  live gate, and why Option C is pre-designed as the fallback.

## Out of Scope (Task 6)

- SSE/token streaming (`agent.stream_async`) â€” MVP is unary JSON (Â§A.2).
- Cognito / CUSTOM_JWT inbound auth â€” AWS_IAM now; Cognito is the dev-mode upgrade.
- **Identity-brokered writes under AWS_IAM** (Finding 1): the WAT-brokered
  `jira_create_story` is descoped from this MVP (`MAHALO_IDENTITY_ENABLED=false`).
  The enablement path (`runtimeUserId` end-to-end, or Cognito) is designed (Â§D.4)
  but its live verification is deferred. `jira_create_story` still runs via its
  static env key in the demo.
- Broadening Identity brokering beyond `jira_create_story`.
- Long-term Memory strategies (STM only, unchanged from Task 5).
- `project_id` semantics in the thin API (accepted for frontend compat, unused).
- Frontend hosting and Gitea (Task 7); CDK re-deploy/teardown hardening (Task 8).
- Any change to the DIRECT/GATEWAY tool code or the Task-5 seams beyond the
  behavior-preserving `agent/hitl.py` extraction.

## Assumptions

- **CONFIRMED (was an assumption; Finding 2):** AgentCore Runtime requires
  **ARM64** container images. Grounded in the installed CDK L1 docstring
  (`infra-cdk/.venv/Lib/site-packages/aws_cdk/aws_bedrockagentcore/__init__.py`):
  container deployment = "build **ARM-compatible** containers" (line ~238);
  code-deploy = "A ZIP archive containing **Linux arm64** dependencies" (line
  ~242); AWS doc `runtime-get-started-code-deploy.html`. The Dockerfile pins
  `--platform=linux/arm64` on that basis; "confirm at build time" is only a
  belt-and-braces check, not the basis for the choice. (The L2
  `Runtime(platform_version=PlatformVersion.V1|V2)` is the runtime platform
  generation, not the CPU architecture.)
- **CONFIRMED (was an assumption; Finding 5):** the installed botocore ships a
  `bedrock-agentcore` **data-plane** client with `invoke_agent_runtime(
  agentRuntimeArn, runtimeSessionId, payload[, runtimeUserId])` and response
  member `response` (`ResponseStream`). The SigV4-signed `httpx` fallback is kept
  only as a botocore version-pin contingency; `api/requirements.txt` pins a
  botocore new enough to include the 2024-02-28 model.
- **RESOLVED by adopting the L2 (Finding 1 this iteration):** the execution-role
  **trust principal is no longer hand-rolled** â€” the L2 `Runtime` auto-creates the
  role (with the correct Runtime service trust and baseline ECR/logging/X-Ray) when
  `execution_role` is omitted (`Runtime.__init__` docstring). The design only
  *adds* app-level grants onto `runtime.role`, so the "confirm the principal string"
  risk the prior hand-rolled role carried is gone. (If a hand-rolled role is ever
  needed, `bedrock-agentcore.amazonaws.com` â€” the Gateway role's
  `gateway_stack.py::_GATEWAY_PRINCIPAL` â€” is the expected trust.)
- **CONFIRMED (was an assumption; Finding 1 this iteration):** `aws-cdk-lib
  2.273.0` ships the **L2 `agentcore.Runtime`** suite (`Runtime`,
  `AgentRuntimeArtifact.from_image_uri`/`from_asset`/â€¦,
  `RuntimeAuthorizerConfiguration.using_iam`/`using_cognito`/`using_jwt`,
  `runtime.add_endpoint`), with `execution_role` optional (auto-created) and
  `authorizer_configuration` defaulting to IAM â€” all verified in installed source
  `infra-cdk/.venv/Lib/site-packages/aws_cdk/aws_bedrockagentcore/__init__.py`
  (Â§E.0 line citations). The L1 `CfnRuntime` remains available but is not used for
  the new Runtime stack.
- **CORRECTED (Finding 7, then Finding 1 of the prior iteration):** the Runtime
  does **not** expose a per-invocation timeout knob â€” the lifecycle config carries only
  `idle_runtime_session_timeout` (default 900s/15min) + `max_lifetime` (default
  28800s/8hr), grounded in the installed CDK L1 docstring (lines ~183, ~750-751).
  That part is verified. **The existence/magnitude of a synchronous
  `InvokeAgentRuntime` per-invocation budget is NOT grounded** and is no longer
  asserted ("on the order of minutes" withdrawn): it is a **measured
  open-verification item** on first deploy (Edge cases + Â§E.5), cross-checked
  against the AgentCore Runtime limits/quotas doc, with the streaming/SSE
  entrypoint (Â§A.2) as the escape hatch if a representative commit is at risk.
- **CONFIRMED (was deferred; Finding 2):** the user-scoped invoke action required
  when `runtimeUserId` is sent (Â§B.5, Â§D.4 enablement path) is
  `bedrock-agentcore:InvokeAgentRuntimeForUser`, named directly in the installed
  botocore `bedrock-agentcore/2024-02-28` `InvokeAgentRuntime` docs (calling with
  the `X-Amzn-Bedrock-AgentCore-Runtime-User-Id` header requires permissions to
  **both** `InvokeAgentRuntime` and `InvokeAgentRuntimeForUser`). It is grantable
  now; for the AWS_IAM MVP only `bedrock-agentcore:InvokeAgentRuntime` is needed
  (Identity off).

---

## Review responses â€” current iteration (vs `task6-design-review.json`, 1 HIGH + 4 MEDIUM + 2 NIT)

All seven findings grounded against installed source during this revision. The
HIGH finding required re-opening the installed CDK module and re-basing Â§E onto
the L2 construct; the MEDIUMs required new citations to the L2 artifact/role/auth
API and the `strands` interrupt model; the NITs are precision fixes.

- **Finding 1 â€” HIGH â€” IaC built on L1 `CfnRuntime` while a full L2
  `agentcore.Runtime` ships in the installed CDK and was never considered
  (ADDRESSED).** Confirmed the review is correct. Re-opened
  `infra-cdk/.venv/Lib/site-packages/aws_cdk/aws_bedrockagentcore/__init__.py` and
  verified the L2 suite exists: `Runtime` (line ~85818; `execution_role` optional
  "a role will be created automatically", `authorizer_configuration` default
  `RuntimeAuthorizerConfiguration.iam()`, `environment_variables`,
  `platform_version`, `add_endpoint`, `.role`), `AgentRuntimeArtifact` (line ~4586)
  with `from_image_uri` (line ~283, the "CloudFormation parameters / cross-stack â€¦
  no IAM auto-granted" path), `from_asset`/`from_ecr_repository`/`from_code_asset`/
  `from_s3`, and `RuntimeAuthorizerConfiguration` (line ~74748) with
  `using_iam`/`using_cognito`/`using_jwt`/`using_o_auth`. **Resolution: added Â§E.0
  "L1 vs L2 decision" with the file:line citations and explicitly adopted the L2.**
  Â§E.1 is rewritten to use `agentcore.Runtime` (auto-role + app-level grants on
  `runtime.role`, `from_asset`/`from_image_uri` flag branch, `add_endpoint`); Â§E.3
  authorizer section replaced the L1 `CfnCondition` dance with "omit
  `authorizer_configuration` for the IAM default; `using_cognito`/`using_jwt` in the
  dev-mode branch"; Â§E.4 synth tests re-expressed in L2 terms; the stack
  tech-stack line, runbook, testability, and Assumptions updated. Offline synth is
  preserved by `from_image_uri(CfnParameter)` (no `DockerImageAsset` on the default
  branch).

- **Finding 2 â€” MEDIUM â€” hand-rolled execution role omits ECR image-pull
  permission (ADDRESSED).** Grounded that `from_image_uri` grants **no** IAM (its
  docstring, line ~283) and that the L2 auto-role includes ECR access on the
  `from_asset`/`from_ecr_repository` paths. **Resolution:** adopting the L2
  (Finding 1) makes the auto-role cover ECR pull on the `from_asset` deploy branch;
  and Â§E.1 step 3 adds an **explicit ECR-pull statement** (`ecr:GetAuthorizationToken`
  on `*` + `ecr:BatchGetImage`/`ecr:GetDownloadUrlForLayer` on the repo ARN) to
  `runtime.role` **only on the `from_image_uri` branch**, where no IAM is
  auto-granted. The ECR gap the prior hand-rolled role had is closed on both
  branches.

- **Finding 3 â€” MEDIUM â€” thin-API Lambda packaging will not include its
  dependencies (ADDRESSED).** Confirmed the prior Â§E.2 `Code.from_asset("../api")`
  shipped no deps. **Resolution: Â§E.2 now specifies the bundling mechanism** â€”
  `Code.from_asset("../api", bundling=BundlingOptions(image=
  Runtime.PYTHON_3_13.bundling_image, command=[pip install -r requirements.txt -t
  /asset-output && cp -r app /asset-output]))` on the deploy branch (installs
  `fastapi`/`mangum`/`boto3`), and a pre-built deps layer / `CfnParameter` layer on
  the offline branch so Docker-based bundling never runs during `cdk synth`. A Â§E.4
  test asserts the offline branch is Docker-free, and `api/requirements.txt` keeps
  the botocore pin new enough for the 2024-02-28 data-plane model.

- **Finding 4 â€” MEDIUM â€” approve-leg tool-set reconstruction (GATEWAY prefixing)
  not pinned; the `role`-is-safe argument ignores the tool registry (ADDRESSED).**
  **Resolution: Â§B.3 gains a paragraph** stating `tool_mode` is a
  Runtime-process-level env constant (`MAHALO_TOOL_MODE`), identical on both legs by
  construction (not a per-request field, forwarded by neither `/chat` nor
  `/chat/approve`), so the approve-leg rebuild has the same tool registry (and
  GATEWAY `target___tool` names, via `agent/approval.py::_bare_name`) as the chat
  leg; and that in GATEWAY mode the approve leg re-runs `attach_gateway_tools`
  (start, stop in `finally`) before the resume so the restored
  `pending_tool_execution` resolves. Â§C.2/Â§D.2 cross-reference this. Called out
  that a future per-request `tool_mode` would have to be forwarded on approve.

- **Finding 5 â€” MEDIUM â€” `interrupt_id` round-trip asserted but not grounded in the
  strands interrupt API (ADDRESSED).** Grounded to installed `strands` source:
  **Â§C.2 now cites** (a) `strands/types/interrupt.py` `@dataclass Interrupt` field
  `id: str` ("Unique identifier â€¦ pass it back to resume", lines ~17-28) and
  `result.interrupts` as the list of `Interrupt`s the chat leg reads; (b)
  `strands/interrupt.py::_InterruptState.resume` (lines 121-152) matching
  **by dict key** (`interrupt_id = content["interruptResponse"]["interruptId"]`,
  `if interrupt_id not in self.interrupts: raise KeyError`,
  `self.interrupts[interrupt_id].response = â€¦`), not positionally; and (c)
  `to_dict`/`from_dict` (lines ~187-189, 233-236) preserving the `interrupt_id`
  keys so the id survives the serializeâ†’Memoryâ†’restore round-trip. The unknown-id
  path raises `KeyError` â†’ the `no_pending_interrupt` envelope (Edge cases). The id
  contract is therefore grounded; only the `pending_tool_execution` â†” message-list
  composition remains the single Â§C.5 live gate.

- **Finding 6 â€” NIT â€” proposal-to-client payload identity with `build_proposal`
  not stated (ADDRESSED).** **Resolution: Â§A.4 step 5 now states** the proposal
  returned to the client is exactly `build_proposal(tool_use)` carried as
  `itr.reason` (`agent/approval.py::WriteApprovalHook`'s `event.interrupt(â€¦,
  reason=â€¦)`), with `interrupt_id` (= `itr.id`) the only added key â€” no
  re-derivation â€” so the gated set maps 1:1 to the six `WRITE_TOOL_NAMES`.

- **Finding 7 â€” NIT â€” session-cache correctness across the approve window
  under-specified (ADDRESSED).** **Resolution: Â§D.2 now states** that with
  `MAHALO_RUNTIME_SESSION_CACHE` on, the approve leg takes exactly one of two paths
  and never both in flight: (a) a cache **hit** reuses the same cached chat-leg
  agent (interrupt state never round-trips), or (b) a **miss** does the cold
  `pending_write=True` restore and invalidates any pre-existing cache entry for S
  after the cycle closes. With the cache off (the MVP) every leg is a cold build
  and the race cannot arise.

---

## Review responses â€” fourth iteration (vs the 2-MEDIUM/2-NIT review)

All four findings grounded against installed source during this revision (the two
MEDIUMs required a new citation to installed CDK L1 docstrings; the two NITs are
wording/precision fixes verified against `agent/memory_client.py` and the Â§A.1/Â§C.3
cross-reference).

- **Finding 1 â€” MEDIUM â€” platform per-invocation timeout budget asserted without a
  citation (ADDRESSED).** Confirmed the review is correct: the installed source
  grounds the *lifecycle* config (only `idle_runtime_session_timeout`, default
  900s/15min, and `max_lifetime`, default 28800s/8hr â€” CDK L1 docstring lines ~183
  and ~750-751, re-read this iteration) and confirms there is **no** per-invocation
  request-timeout knob, but the *existence and magnitude* of a synchronous
  `InvokeAgentRuntime` budget is **not** in installed source and no AWS-doc number
  could be cited pre-implementation. **Resolution: withdraw "on the order of
  minutes."** The Edge-cases bullet now (a) states the grounded lifecycle facts,
  (b) explicitly marks the invocation-budget existence/magnitude as NOT grounded,
  and (c) adds an **OPEN VERIFICATION ITEM** â€” measure the observed time of a
  representative code-gen `github_commit_files` invocation on first deploy,
  cross-check the AgentCore Runtime limits/quotas doc, and switch to the SSE
  entrypoint (Â§A.2) if at risk. The Â§E.5 runbook gains the matching measure step,
  and the Assumptions "CORRECTED (Finding 7)" entry is updated to say the magnitude
  is withdrawn/measured rather than asserted. The streaming escape hatch (Â§A.2)
  remains the documented mitigation.

- **Finding 2 â€” MEDIUM â€” container architecture (ARM64) asserted as the Runtime
  contract without a citation (ADDRESSED).** Grounded ARM64 in installed source
  this iteration: the CDK L1 docstring
  (`infra-cdk/.venv/Lib/site-packages/aws_cdk/aws_bedrockagentcore/__init__.py`)
  states, verbatim, "developers create a Dockerfile, build **ARM-compatible**
  containers, manage ECR repositories" for container deployment (line ~238) and "A
  ZIP archive containing **Linux arm64** dependencies needs to be uploaded to S3 as
  a pre-requisite to Create Agent Runtime" for code-deploy (line ~242), citing AWS
  doc `runtime-get-started-code-deploy.html`. **Resolution:** the Â§A.6 Dockerfile
  comment, the Â§A.6 ARM64 paragraph, and the Assumptions entry now carry these
  file+line citations and the doc URL; "confirm at build time / flip `--platform`
  only if the deploy rejects it" is demoted to a belt-and-braces check, not the
  basis for the choice. Also noted that the separate `CfnRuntime.platform_version`
  (`V1`/`V2`) is the runtime platform generation, NOT the CPU architecture, so it
  does not conflict with the ARM64 image requirement.

- **Finding 3 â€” NIT â€” `filter_restored_tool_context` described as living on the
  spec, but it is set in the manager builder (ADDRESSED).** Verified against
  `agent/memory_client.py`: `MemorySessionSpec` has only
  `session_id`/`actor_id`/`region`/`memory_id`, and `filter_restored_tool_context`
  is hardcoded `True` in `build_memory_session_manager` (line 94). **Resolution:
  Â§C.4 now names the three concrete edits** â€” (1) add
  `filter_restored_tool_context: bool = True` to `MemorySessionSpec`; (2)
  `build_memory_session_spec(..., *, pending_write: bool = False)` sets it to
  `(not pending_write)`; (3) `build_memory_session_manager` passes
  `spec.filter_restored_tool_context` into `AgentCoreMemoryConfig` instead of the
  hardcoded `True`. Default `True` preserves Task-5 behavior byte-for-byte; the
  Â§C.1 summary wording is aligned to reference these edits.

- **Finding 4 â€” NIT â€” entrypoint imports `resume_decision` from
  `agent/runtime_session.py`, but that helper is undefined and Â§C.3 defines
  `resume_once` in `agent/hitl.py` (ADDRESSED).** **Resolution:** the Â§A.1 skeleton
  import is corrected to `from agent.runtime_session import build_and_attach` +
  `from agent.hitl import emit_system_signal, resume_once`; the `resume_decision`
  name is dropped entirely. Â§C.3 now states the single canonical signature once â€”
  `resume_once(agent, interrupt_id: str, decision) -> AgentResult` in
  `agent/hitl.py` â€” and that `agent/runtime_session.py` exports only
  `build_and_attach`.

---

## Review responses â€” third iteration (vs the 1-HIGH/1-MEDIUM/2-NIT review)

All four findings re-verified against installed source in `agent/.venv` during
that revision, not taken on the review's word.

- **Finding 1 â€” HIGH â€” the `AWS_PROFILE`-omission credential fallback does not
  fire where the design said; the hosted agent's Bedrock calls would raise
  `ProfileNotFound` unhandled (ADDRESSED).** Confirmed the review is correct:
  `boto3/session.py::Session.__init__` only calls
  `set_config_variable('profile', profile_name)` and does **not** raise;
  `botocore/session.py::get_scoped_config` (line 424) raises `ProfileNotFound`
  **lazily** at credential/region resolution (inside the model call), **outside**
  `_build_bedrock_model`'s `try/except` which wraps only the Session constructor;
  and the existing offline `test_gateway_mode`/`test_memory_mode`/
  `test_identity_mode` build agents with no `lava` profile and pass â€” proving the
  construction-time raise the design relied on never happens. **Resolution:**
  patch `_build_bedrock_model` to decide the profile **before** constructing the
  Session using `botocore.session.Session().available_profiles` (verified at
  `botocore/session.py` line 302 to read the config file via
  `full_config['profiles']` â€” no creds, no network, offline-safe): pass
  `profile_name` only when `settings.aws_profile` is in `available_profiles`
  (local `lava` present), else build a profile-less Session so boto3 uses the
  default chain = the execution role (container, `lava` absent). Â§A.6 (Dockerfile
  note + new "Credential resolution â€” the correct mechanism" subsection with the
  patched code), the Overview, Â§D.4, Â§E.3, and Â§E.4 updated. **Â§E.4 test
  rewritten** to exercise the real resolution path (patch `available_profiles` to
  omit/include `"lava"` and assert the profile-less vs profiled Session branch) â€”
  explicitly **not** a mock that forces `Session()` to raise, which would assert a
  non-existent boto3 behavior and mask the bug.

- **Finding 2 â€” MEDIUM â€” AgentCore Identity credential-provider IAM actions were
  hand-waved yet provisioned now (ADDRESSED, both fixes applied).** Grounded the
  actions to installed source: `bedrock_agentcore/services/identity.py` shows the
  `@requires_api_key` path's `IdentityClient.get_api_key` calls the data-plane op
  `get_resource_api_key` (line 300) and the user-scoped WAT mint calls
  `get_workload_access_token_for_user_id` (line 151); the installed botocore
  `bedrock-agentcore/2024-02-28` model names the operations `GetResourceApiKey`
  and `GetWorkloadAccessTokenForUserId`, so the IAM actions are
  **`bedrock-agentcore:GetResourceApiKey`** and
  **`bedrock-agentcore:GetWorkloadAccessTokenForUserId`** (SDK method names like
  `get_api_key` are not IAM actions â€” fixed). **Resolution (both review options
  applied):** (a) Â§D.4 now names the grounded actions with their file:line
  citations; and (b) the Identity policy is **removed from the Â§E.1 MVP execution
  role ("provision now")** and attached only in the Â§D.4 opt-in enablement path,
  so the AWS_IAM MVP role claims nothing ungrounded. Â§E.1 step 2 now states
  explicitly there is no Identity policy in the MVP role.

- **Finding 3 â€” NIT â€” generated session id must be echoed (ADDRESSED).**
  **Resolution: Â§A.4 step 2 and the Â§A.3 `session_id` row now state the echoed id
  is the resolved id (`context.session_id or <generated>`)**, so a header-less
  caller still threads the same Memory conversation; the Edge-cases "Missing
  session header" bullet is updated to match. Noted the thin API is always the
  primary id source so this is belt-and-braces.

- **Finding 4 â€” NIT â€” approve-leg `role` source unspecified (ADDRESSED, with the
  safety reason stated).** **Resolution: the design does NOT forward `role` on the
  approve leg and Â§B.3 (new paragraph), the Â§A.3 `role` row, and Â§D.2
  `build_and_attach` now state why it is safe** â€” the approve leg resumes via
  `pending_tool_execution` which runs the tool body **without a model call**
  (investigation Â§3.2), and `role` only selects the system prompt which is
  consumed only on a model call, so a different approve-leg `role` yields an
  identical resume. Called out that `role` must be forwarded if a future change
  makes the post-approve turn re-invoke the model.

---

## Review responses â€” earlier iterations (the 7-finding review, then the 5-finding review)

The entries below record the resolutions to the two earlier reviews (a 7-finding
review and a 5-finding review) that preceded the current (third) review. They are
retained for traceability.

### Second iteration (vs the 5-finding review, 2 MEDIUM + 3 NIT)

- **Finding 1 â€” MEDIUM â€” `AWS_PROFILE=""` does not guarantee the default-chain
  fallback (SUPERSEDED by the current HIGH Finding 1).** This iteration chose "omit
  `AWS_PROFILE` â†’ rely on a `ProfileNotFound` raise â†’ except-branch fallback",
  which the **third** review proved unsound (the raise is lazy, outside the
  `try/except`). The correct fix now lives in the current-iteration Finding 1
  above (decide the profile via `available_profiles` before constructing the
  Session). Retained here only to record the supersession.

- **Finding 2 â€” MEDIUM â€” user-scoped IAM action is knowable now (ADDRESSED).**
  Confirmed against `botocore/data/bedrock-agentcore/2024-02-28/service-2.json.gz`:
  calling `InvokeAgentRuntime` with the
  `X-Amzn-Bedrock-AgentCore-Runtime-User-Id` header requires permissions to
  **both** `bedrock-agentcore:InvokeAgentRuntime` and
  `bedrock-agentcore:InvokeAgentRuntimeForUser`. Â§B.5, Â§D.4, and Assumptions name
  `bedrock-agentcore:InvokeAgentRuntimeForUser` directly and grant both actions on
  the Runtime ARN when `MAHALO_IDENTITY_ENABLED=true`.

- **Finding 3 â€” NIT â€” set `contentType`/`accept` on the invoke (ADDRESSED).**
  Both are optional MIME header members of `InvokeAgentRuntimeRequest`; Â§B.4
  `invoke_runtime` passes `contentType="application/json"` and
  `accept="application/json"` explicitly (SSE path flips `accept` to
  `text/event-stream`).

- **Finding 4 â€” NIT â€” soften "removed by construction" (ADDRESSED).** Â§C.1/Â§C.4
  reworded â€” `filter=False` removes the one filter-driven collision; the residual
  interrupt-state â†” message-list agreement across a cold boundary is reduced to
  the single Â§C.5 live gate, with Option C as the fallback.

- **Finding 5 â€” NIT â€” assert the container installs the harness deps
  (ADDRESSED).** Â§E.4 asserts `agent/requirements.txt` pins
  `bedrock-agentcore==1.24.1` + `strands-agents==1.61.1`, documents that
  `bedrock-agentcore` declares `uvicorn>=0.34.2` + `starlette>=0.46.2` as base
  deps (transitively installed in the image), and that `langchain` is only under
  `bedrock-agentcore`'s `langgraph`/`ragas` extras (never the base install).

### First iteration (vs the 7-finding review)

All findings re-verified against installed source in `agent/.venv` /
`infra-cdk/.venv` during that revision, not taken on the review's word.

- **Finding 1 â€” HIGH â€” Identity WAT under SigV4 (ADDRESSED).** Confirmed the
  claim: `bedrock_agentcore/identity/auth.py::_get_workload_access_token`
  (lines 350-363) raises `ValueError` in container mode when no WAT is in context,
  naming `X-Amzn-Bedrock-AgentCore-Runtime-User-Id`. **Resolution: descope the
  Identity-brokered write from the AWS_IAM MVP** â€” `MAHALO_IDENTITY_ENABLED=false`
  (Â§E.3), the Â§E.5 live gate no longer includes the brokered `jira_create_story`
  write, and Â§D.4 now states the SDK behavior explicitly and designs the
  `runtimeUserId` enablement path (thin API sends `runtimeUserId`, Â§B.4/Â§B.5; env
  flip; role grant) proven only once `runtimeUserId` end-to-end or Cognito lands.
  Overview and Out of Scope aligned.

- **Finding 2 â€” MEDIUM â€” CfnRuntime authorizer (ADDRESSED).** Confirmed:
  `CfnRuntime.AuthorizerConfigurationProperty` (aws-cdk-lib 2.273.0) has only
  `custom_jwt_authorizer`; no AWS_IAM value. **Resolution: Â§E.3 (and Â§A.6/Â§E.1
  references) now state AWS_IAM = omit `authorizer_configuration`**, with a
  `CfnParameter`-gated `CfnCondition` that constructs
  `custom_jwt_authorizer` only in the `CUSTOM_JWT` branch. Removed the inaccurate
  "AWS_IAM default value / mirror the Gateway `AuthorizerType`" wording.

- **Finding 3 â€” MEDIUM â€” synth offline-safety for DockerImageAsset (ADDRESSED).**
  **Resolution: Â§E.1 step 1 and Â§E.4 now specify that no `DockerImageAsset` is
  instantiated in the off branch** (container URI is an `AgentImageUri`
  `CfnParameter`), with the exact branch code and two infra-cdk tests â€” one
  asserting flag-unset synth is exit 0, Docker-free, and uses the parameter ref;
  one (skippable) asserting the asset path when the flag is set.

- **Finding 4 â€” MEDIUM â€” HITL contract load-bearing on unproven behavior
  (ADDRESSED).** **Resolution: flipped the contract.** Â§C.1/Â§C.4 make the
  lowest-risk path primary â€” for any pending-write session the Memory manager is
  built with **`filter_restored_tool_context=False`** (stated explicitly), which
  removes the restore collision by construction; Option B (default `True`
  cross-invocation restore) is demoted to an opt-in optimization enabled only
  after the Â§C.5 live proof, and Option C remains the documented fallback. The
  Â§C.4 remediation is now non-optional and pre-decided, keyed off `payload.action`
  (chat vs approve), not a reactive "if the gate fails" branch.

- **Finding 5 â€” NIT â€” boto3 contract (ADDRESSED).** Confirmed present/correct in
  `botocore/data/bedrock-agentcore/2024-02-28/service-2.json.gz`
  (`agentRuntimeArn`/`runtimeSessionId`/`payload`/`runtimeUserId`, response
  `response`=`ResponseStream`). **Resolution: Â§B.4 and Assumptions downgraded the
  caveat to a confirmed note; httpx fallback kept only as a version-pin
  contingency with a pinned botocore in `api/requirements.txt`.**

- **Finding 6 â€” NIT â€” removal policy (ADDRESSED).** **Resolution: Â§E.1 now calls
  `apply_removal_policy(RemovalPolicy.DESTROY)` explicitly** on `CfnRuntime` and
  `CfnRuntimeEndpoint` rather than calling DESTROY "implicit."

- **Finding 7 â€” NIT â€” invocation timeout (ADDRESSED).** Confirmed
  `LifecycleConfigurationProperty` exposes only `idle_runtime_session_timeout` +
  `max_lifetime` â€” **no per-invocation request timeout knob**. **Resolution: the
  Edge-cases and Assumptions entries now document that there is no L1 knob**, rely
  on the platform default invocation budget, set idle/lifetime generously for the
  approve round-trip, and name streaming (Â§A.2) as the escape hatch for commits
  that would exceed the platform budget; confirm the exact budget at deploy time.
