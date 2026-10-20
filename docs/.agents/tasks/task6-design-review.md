# Task 6 Design Review — Runtime hosting (fresh, context-free)

Scope: `docs/.agents/tasks/task6-design.md`, judged against its investigation
(`docs/.agents/tasks/task6-investigation.md`), `docs/ARCHITECTURE.md`, and the
central risk brief: guessing the AgentCore Runtime packaging/entrypoint/deploy
contract and the HITL-interrupt-over-HTTP behavior. Every SDK/AWS assertion was
checked against installed source or the botocore model; none was taken on the
design's word.

Verdict is mechanical: **0 HIGH + 0 MEDIUM** below ⇒ **APPROVED**. The three NITs
do not gate.

This is the sixth review iteration. The prior review's one HIGH (IaC built on L1
while an L2 `agentcore.Runtime` ships) was the single biggest risk; it is now
**resolved and independently verified** — the L2 suite exists exactly where the
design cites it, and the design re-based §E onto it correctly.

---

## Findings

### 1. NIT — Stale "L1" wording survives the L2 re-base in two places

**Where:** §E.5 step 6 ("the explicit `RemovalPolicy.DESTROY` on the Runtime
**L1s** ensures clean deletion") and the Edge-cases / Assumptions "lifecycle
config … grounded in the installed CDK **L1** docstring (lines ~183, ~750-751)".

**Problem:** §E.0 adopted the L2 `agentcore.Runtime`, and §E.1's teardown note
already correctly says the L2 constructs are destroyed as a unit with
`RemovalPolicy.DESTROY` applied *where the L2 exposes the underlying
`CfnResource`*. The two residual "L1" references are leftover wording from the
prior iteration. They are not wrong facts (the lifecycle-config docstring text is
real and the Duration-based `LifecycleConfiguration` L2 wrapper carries the same
`idle_runtime_session_timeout`/`max_lifetime` semantics — verified below), but the
"L1" label is now internally inconsistent with the adopted construct and could
mislead the implementer into reaching for `CfnRuntime`.

**Fix:** replace "the Runtime L1s" in §E.5 step 6 with "the Runtime L2 constructs
(and the underlying `CfnResource`s where exposed)", and change "the installed CDK
L1 docstring" in the lifecycle citations to "the installed CDK
`LifecycleConfiguration` docstring" (the L2 `LifecycleConfiguration` at
`__init__.py` line ~65795 carries the same 900s/28800s defaults — the citation is
valid, only the "L1" label is stale).

### 2. NIT — `add_endpoint` first argument is positional `endpoint_name`, not a keyword

**Where:** §E.1 step 4 / §A/§E snippets: `runtime.add_endpoint("default")` and the
prose "`runtime.add_endpoint(name, description?, version?)`".

**Problem:** the installed L2 signature is
`add_endpoint(endpoint_name: str, *, description=None, version=None)`
(`__init__.py` line ~85970). `runtime.add_endpoint("default")` is correct, but the
prose paraphrase "`add_endpoint(name, …)`" names the first param `name` while the
SDK calls it `endpoint_name`. Harmless for the positional call, but a keyword call
`add_endpoint(name="default")` would `TypeError`.

**Fix:** paraphrase as `add_endpoint(endpoint_name, *, description=None,
version=None)` so nobody tries the wrong keyword.

### 3. NIT — Investigation §5 still describes only the L1; design and investigation now disagree on the IaC surface

**Where:** investigation §5.1–§5.3 and its Citations index state the Runtime
deploy surface is `CfnRuntime`/`CfnRuntimeEndpoint` (L1) and that "our deploy path
is CDK `CfnRuntime`"; the design §E.0 supersedes this with the L2.

**Problem:** the design is the authoritative artifact and it is correct (L2
verified below), but the investigation it claims to be "grounded in" now contains
a materially superseded IaC conclusion. A future reader cross-checking the design
against the investigation will hit a direct contradiction on the single most
load-bearing deploy decision. The design acknowledges this inline (§E.0 "that
reading was incomplete"), which keeps it from being a MEDIUM, but the source doc
is left stale.

**Fix:** add a one-line note at investigation §5.1 pointing to design §E.0 ("L2
`agentcore.Runtime` suite also ships and is the chosen surface — see design
§E.0"), so the two docs do not contradict each other on the deploy contract.

---

## Verified Assumptions (checked against installed source)

Area A — Runtime entrypoint + packaging:
- `BedrockAgentCoreApp` is a Starlette subclass registering `POST /invocations`,
  `GET /ping`, `/ws`; `app.run()` serves uvicorn on :8080 — consistent with the
  investigation's citations (`bedrock_agentcore/runtime/app.py`). Entrypoint
  two-param form keyed on the 2nd param being named `context` (`_takes_context`) —
  consistent; design's `invoke(payload, context)` is correct.
- Container ARM64 requirement: **verified verbatim** in
  `infra-cdk/.venv/.../aws_bedrockagentcore/__init__.py` line 238 ("build
  ARM-compatible containers") and line 242 ("A ZIP archive containing Linux arm64
  dependencies"), with the AWS doc URL at line 244. `--platform=linux/arm64` rests
  on a real citation.
- Container ships the ASGI harness: `bedrock-agentcore==1.24.1` METADATA declares
  `Requires-Dist: starlette>=0.46.2` and `Requires-Dist: uvicorn>=0.34.2` as
  **base** deps (not extras) — §E.4's claim is correct; `pip install -r
  agent/requirements.txt` pulls them transitively.
- Credential fix (the prior HIGH, now §A.6): **verified**. Current
  `agent/strands_agent.py::_build_bedrock_model` does
  `try: boto3.Session(profile_name=settings.aws_profile, …) except: Session(...)`.
  `botocore/session.py` raises `ProfileNotFound` in `get_scoped_config` (line 424),
  **not** in `Session.__init__`, so the lazy-raise reasoning is correct and the
  existing `try/except` would not catch it. `botocore.session.Session.available_profiles`
  exists (line 302). The design's "decide the profile before constructing the
  Session" fix is sound and offline-safe.

Area B — Thin API:
- `api/` currently holds only `.gitkeep` (matches §B.2).
- botocore `bedrock-agentcore/2024-02-28` model: `InvokeAgentRuntime` request
  members verified — `contentType`(hdr Content-Type), `accept`(hdr Accept),
  `runtimeSessionId`(hdr X-Amzn-Bedrock-AgentCore-Runtime-Session-Id),
  `runtimeUserId`(hdr X-Amzn-Bedrock-AgentCore-Runtime-User-Id),
  `agentRuntimeArn`(uri), `payload`(body). Response member `response` of shape
  `ResponseStream` (streaming blob). `resp["response"].read()` is correct.
- `InvokeAgentRuntimeForUser` is **not** a separate operation (operations are
  `InvokeAgentRuntime`, `InvokeAgentRuntimeCommand`, `InvokeBrowser`,
  `InvokeCodeInterpreter`, `InvokeHarness`); it appears only in the IAM-permission
  doc string "You require permissions to both actions
  (`bedrock-agentcore:InvokeAgentRuntime` and
  `bedrock-agentcore:InvokeAgentRuntimeForUser`)". §B.5/§D.4's precise
  "IAM-action-not-API-op" distinction is grounded.

Area C — HITL over the API boundary:
- `agent/approval.py::WriteApprovalHook` calls `event.interrupt("write_approval",
  reason=build_proposal(event.tool_use))`; `build_proposal` returns
  `{action, system, params, description}` (no `interrupt_id`) — so §A.4 step 5 /
  Finding 6 "add `interrupt_id` as the only new key" is exact. The six
  `WRITE_TOOL_NAMES` match the gated set. `_bare_name` strips the `___` Gateway
  prefix (grounds §B.3's `tool_mode` invariant argument).
- Strands interrupt model: `strands/interrupt.py::Interrupt` is a dataclass with
  field `id: str` docstring "Unique identifier. Treat as opaque: pass it back to
  resume the agent, do not parse or construct it." — §C.2 Finding-5 citation
  exact. `_InterruptState.resume` reads
  `content["interruptResponse"]["interruptId"]`, does a dict-key match
  (`if interrupt_id not in self.interrupts: raise KeyError`), and assigns
  `self.interrupts[interrupt_id].response` — the id round-trip grounding is
  correct. `interrupt(name, reason)` sets `interrupts.setdefault(id, Interrupt(id,
  name, reason, response))` and returns the stored response on resume — matches the
  two-pass gate design.
- `agent/chat.py` has `_ask` (line 33) and `_emit_system_signal` (line 82) — the
  §C.3 shared-`agent/hitl.py` extraction targets exist.
- `agent/memory_client.py`: `MemorySessionSpec` currently carries only
  `session_id`/`actor_id`/`region`/`memory_id`; `build_memory_session_spec` is
  `(session_id, actor_id, *, region)`; `build_memory_session_manager` hardcodes
  `filter_restored_tool_context=True`. The §C.4 "three concrete edits"
  (add field default True; add `pending_write` param setting `not pending_write`;
  pass `spec.filter_restored_tool_context` instead of the literal) match the real
  code exactly, and the default preserves Task-5 behavior.

Area D — Sessions + Memory + Identity:
- Identity descope (the prior HIGH, §D.4): **verified**.
  `bedrock_agentcore/identity/auth.py::_get_workload_access_token` (line 350) does,
  when the WAT is absent and `os.getenv("DOCKER_CONTAINER") == "1"`, raise
  `ValueError("Workload access token has not been set. If invoking agent runtime
  via SIGV4 inbound auth, please specify the X-Amzn-Bedrock-AgentCore-Runtime-User-Id
  header …")`. So under AWS_IAM/SigV4 the brokered path requires `runtimeUserId`;
  descoping Identity for the MVP is the correct, honest call.
- Identity IAM actions: botocore model contains operations `GetResourceApiKey` and
  `GetWorkloadAccessTokenForUserId` → IAM actions
  `bedrock-agentcore:GetResourceApiKey` /
  `bedrock-agentcore:GetWorkloadAccessTokenForUserId` are grounded (§D.4).
- Memory/opt-in posture matches ARCHITECTURE.md ("opt-in and additive"); no scope
  creep against the documented end-state.

Area E — IaC + offline-safety (the prior HIGH; the crux):
- **The L2 `agentcore.Runtime` suite exists in `aws-cdk-lib 2.273.0`** at the exact
  jsii types / lines the design cites:
  `aws-cdk-lib.aws_bedrockagentcore.AgentRuntimeArtifact` (line 4586),
  `RuntimeAuthorizerConfiguration` (74748), `Runtime` (85818), `RuntimeEndpoint`
  (86099); L1 `CfnRuntime` (48035) also present.
- `Runtime.__init__`: `execution_role` **optional** ("If not provided, a role will
  be created automatically"); `authorizer_configuration` optional, **default
  `RuntimeAuthorizerConfiguration.iam()` (IAM authentication)**; also
  `environment_variables`, `platform_version` (`PlatformVersion`),
  `lifecycle_configuration`, `tracing_enabled`, `runtime_name`. `.role` property
  returns the (auto-created or supplied) `IRole`. `add_endpoint(endpoint_name, *,
  description?, version?) -> RuntimeEndpoint`. `agent_runtime_arn` attribute +
  `grant_principal`. All match §E.0/§E.1/§E.3.
- `AgentRuntimeArtifact.from_image_uri(container_uri)` docstring: "Use this when
  referencing ECR images from CloudFormation parameters or cross-stack references.
  **Note: No IAM permissions are automatically granted. You must ensure the runtime
  has ECR pull permissions**" — grounds both the offline-synth `CfnParameter` path
  and the §E.1/Finding-2 explicit-ECR-grant-on-`from_image_uri`-branch decision.
  `from_asset(directory, *, file=, platform=, exclude=, …)`,
  `from_ecr_repository(repository, tag?)`, `from_code_asset(...)`,
  `from_s3(location, runtime, entrypoint)` all present with the cited signatures.
  `bind(scope, runtime)` wires permissions on the asset paths.
- `RuntimeAuthorizerConfiguration`: `using_iam` (jsii `usingIAM`), `using_cognito`,
  `using_jwt` (jsii `usingJWT`), `using_o_auth` (jsii `usingOAuth`) all present.
  Python snake_case names used by the design resolve correctly.
- `LifecycleConfiguration` (L2, line ~65795) takes `idle_runtime_session_timeout` /
  `max_lifetime` as `Duration` with service defaults 900s (15 min) / 28800s (8 hr)
  — grounds the Edge-cases timeout discussion and the §E.1 `Duration.minutes(15)` /
  `Duration.hours(8)` usage. The withdrawal of the per-invocation-budget magnitude
  (demoted to a measured open item) is the correct call; no such knob exists.

---

## Unverified / Wrong Assumptions

None blocking. The design is scrupulous about separating grounded facts from
open items. The two genuinely-unverifiable items are correctly flagged by the
design itself (not errors):

1. **Cross-boundary HITL composition** — whether the restored
   `interrupt_state.pending_tool_execution` composes cleanly with the restored
   message list across a cold process rebuild, even with
   `filter_restored_tool_context=False`. The design does **not** assert this works;
   it makes it the single §C.5 live gate, removes the one filter-driven collision
   deterministically (the three `memory_client.py` edits, verified above), and
   pre-designs Option C (`pending_action`) as the fallback. This is the correct
   posture for a behavior that provably cannot be confirmed from source alone — it
   is flagged, bounded, and has a fallback, so it is not a blocking gap.
2. **Synchronous `InvokeAgentRuntime` per-invocation timeout magnitude** — the
   design explicitly **withdrew** the earlier "on the order of minutes" assertion
   and demoted it to a measured open-verification item with the SSE entrypoint as
   the escape hatch. Correct; no source documents a number.

The grep/code-search tooling initially returned no matches against the 5.2 MB
single-file CDK module (a tool limitation on that file), which could have looked
like "the L2 does not exist". Direct source reads and `Select-String` confirmed
every cited line, so the design's §E.0 line citations are accurate, not
fabricated.

---

## Verdict

0 HIGH, 0 MEDIUM, 3 NIT ⇒ **APPROVED**.

The central risk — guessing the Runtime packaging/entrypoint/deploy contract and
the HITL-over-HTTP behavior — is retired: every external AWS/SDK surface the design
leans on (L2 `agentcore.Runtime` suite, `from_image_uri`/`from_asset`, IAM-default
authorizer, `InvokeAgentRuntime` member/header shape, `InvokeAgentRuntimeForUser`
as an IAM action, the SigV4 WAT `ValueError`, the `strands` `Interrupt.id` +
`resume` key-match, the lazy `ProfileNotFound`, the `bedrock-agentcore` base
uvicorn/starlette deps, and the ARM64 docstring) was independently confirmed in
installed source at the cited locations. The three NITs are wording/consistency
cleanups (stale "L1" labels, an `add_endpoint` keyword-name paraphrase, and the
investigation doc left contradicting the design on the IaC surface) and do not
gate implementation.
