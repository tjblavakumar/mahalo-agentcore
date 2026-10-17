# Task 5 Implementation Plan — AgentCore Memory & Identity

Ordered, dependency-sequenced steps to implement the APPROVED design
(`docs/.agents/tasks/task5-design.md`), grounded in the cited investigation
(`docs/.agents/tasks/task5-investigation.md`) and the current code under `agent/`
and `infra-cdk/`. Both capabilities are **opt-in / additive**: default behavior
(all toggles off) is byte-for-byte unchanged. The automated gate is **OFFLINE**
(synth / unit tests / import). Deploy and the live persistence/brokering checks
are documented for the operator, not executed here. No git commit, no auto-deploy.
Only files under `mahalo-agentcore` are modified; `mahalo-dock` is read-only.

## Conventions discovered during exploration (apply throughout)

- Agent tests run with `agent/.venv/Scripts/python.exe -m pytest agent -q`;
  green baseline is **55 passed, 1 skipped** (the 1 skip is the live tunnel test
  `agent/tests/test_integration_live.py`). Preserve that baseline plus new tests.
- `agent/config.py` `Settings` is a frozen dataclass read at import; tests flip
  env vars by `importlib.reload(config)` (see `agent/tests/test_gateway_mode.py::_fresh_gateway_client`).
  New settings use the existing `_getenv(name, default)` pattern.
- The offline-safe seam pattern is established by GATEWAY mode: `build_agent`
  **constructs but does not start** the client; a separate `attach_*` helper does
  the single live wiring; boto3 is imported lazily inside function bodies
  (`agent/gateway_client.py::SigV4Auth.auth_flow`). Mirror this exactly for Memory.
- CDK stacks are per-feature `Stack` subclasses under `infra-cdk/mahalo_infra/`,
  wired in `infra-cdk/app.py` with `env=cdk.Environment(account="<AWS_ACCOUNT_ID>", region="us-east-1")`.
  Offline synth assertions live in `infra-cdk/tests/` using `aws_cdk.assertions.Template.from_stack`
  (see `infra-cdk/tests/test_gateway_stack.py`). Confirmed installed CDK props:
  `CfnMemory(... event_expiry_duration=<int>, memory_strategies=[...])`,
  `CfnWorkloadIdentity(... allowed_resource_oauth2_return_urls=...)`,
  `CfnApiKeyCredentialProvider(...)` — read the exact required-prop signatures from
  `infra-cdk/.venv/Lib/site-packages/aws_cdk/aws_bedrockagentcore/__init__.py` at
  implementation time (classes per investigation §3), but the constructs and the
  STM-only shape are locked by the design.
- CDK offline gate: run in `infra-cdk/` — `cdk synth --all` (exit 0) and
  `python -m pytest tests -q`.
- Secrets rule: never log the fetched API key value; error messages are type-name only.

---

# Implementation Plan

- [ ] 1. Add the six new opt-in settings to `agent/config.py`.
      Extend the `Settings` dataclass with (defaults preserve today's behavior, all off/empty):
      `memory_enabled: bool` (`MAHALO_MEMORY_ENABLED`, default `False`),
      `memory_id: str` (`MAHALO_MEMORY_ID`, default `""`),
      `memory_region: str` (`MAHALO_MEMORY_REGION`, default verbatim
      `_getenv("MAHALO_MEMORY_REGION", _getenv("AWS_REGION", "us-east-1"))` mirroring `gateway_region`),
      `session_id: str` (`MAHALO_SESSION_ID`, default `""`),
      `identity_enabled: bool` (`MAHALO_IDENTITY_ENABLED`, default `False`),
      `identity_jira_provider: str` (`MAHALO_IDENTITY_JIRA_PROVIDER`, default `"mahalo-jira-apikey"`).
      Parse booleans with a tolerant helper (`_getenv(name, "false").strip().lower() in {"1","true","yes"}`).
      Do NOT add `MAHALO_MEMORY_EVENT_EXPIRY_DAYS` (retention lives only in the CDK stack).
      Files: `agent/config.py`
      Verify: `agent/.venv/Scripts/python.exe -m pytest agent -q` — still 55 passed, 1 skipped
      (no behavior change yet; this only adds fields). Leaves the repo buildable.

- [ ] 2. Create the offline-safe Memory session-manager builder `agent/memory_client.py`.
      Add `build_memory_session_manager(session_id: str, actor_id: str, *, region: str) -> AgentCoreMemorySessionManager`
      that assembles `AgentCoreMemoryConfig(memory_id=settings.memory_id, session_id=..., actor_id=...,
      filter_restored_tool_context=True, batch_size=1)` (STM-only; no `retrieval_config`) and constructs the
      `AgentCoreMemorySessionManager(cfg, region_name=region)` — mirroring `gateway_client._build_gateway_mcp_client`:
      construct only, perform NO network call, import `bedrock_agentcore...` / boto3 lazily inside the function body so
      importing the module needs no creds. Imports: `from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig`
      and `...session_manager import AgentCoreMemorySessionManager` (both present in `agent/.venv` per investigation §1.1).
      Files: `agent/memory_client.py`
      Verify: `agent/.venv/Scripts/python.exe -c "import agent.memory_client"` runs with no AWS creds and no network
      (no error). Covered more fully by step 6's unit tests.

- [ ] 3. Refactor `build_agent` to return a `BuildResult` and add Memory params + `attach_memory`, in `agent/strands_agent.py`.
      Add `@dataclass class BuildResult: agent; mcp_client=None; session_manager=None`. Change `build_agent` to
      keyword-only params `*, memory: bool | None = None, session_id: str | None = None, identity: bool | None = None`
      (resolve `memory`→`settings.memory_enabled`, `identity`→`settings.identity_enabled` when `None`); make it ALWAYS
      return `BuildResult(...)` — DIRECT: `BuildResult(agent=<Agent>)`; GATEWAY: `BuildResult(agent, mcp_client=<constructed,not started>)`;
      when `memory` resolves true: also set `session_manager=build_memory_session_manager(session_id, actor_id=developer_id, region=settings.memory_region)`
      (do NOT pass `session_manager=` into `Agent(...)` and do NOT register it as a hook — keeps construction offline).
      Add a fail-fast `ValueError("MEMORY mode requires MAHALO_MEMORY_ID ...")` when `memory` is true and `settings.memory_id` is empty
      (mirrors the GATEWAY URL guard). Add `attach_memory(agent, session_manager)` that does, in order:
      `agent.hooks.add_hook(session_manager)` (the `HookRegistry.add_hook(provider)` method — NOT `Agent.add_hook`),
      then `session_manager.initialize(agent)` exactly once, then `agent._session_id = session_manager.session_id`.
      Leave `attach_gateway_tools` unchanged.
      Files: `agent/strands_agent.py`
      Verify: step 5 updates the callers/tests that unpack the old tuple shapes; run the full suite there. This step alone
      breaks `agent/chat.py` + 3 gateway tests (expected — fixed in step 5), so verify compile only:
      `agent/.venv/Scripts/python.exe -c "import agent.strands_agent"` succeeds.

- [ ] 4. Wire the one representative Identity outbound path in `agent/tools/jira_write_tools.py`.
      Add module-level `from bedrock_agentcore.identity.auth import requires_api_key` (plain import, no client built).
      Add a body-local helper `_fetch_jira_token() -> str` whose nested `@requires_api_key(provider_name=settings.identity_jira_provider, into="api_key")`
      decorated `_inner(*, api_key)` is defined-and-invoked only when the helper runs (so no `IdentityClient`/boto3 at import).
      In `jira_create_story` only, replace the token source with
      `token = _fetch_jira_token() if settings.identity_enabled else settings.jira_token`, wrapped in
      `try/except Exception` returning `❌ Failed to create story: credential fetch failed (<ExcTypeName>)` (type-name only,
      never the key value). `jira_create_story`'s `@tool` signature/docstring and `jira_update_story` stay byte-for-byte unchanged.
      Files: `agent/tools/jira_write_tools.py`
      Verify: `agent/.venv/Scripts/python.exe -m pytest agent/tests/test_write_tools_unit.py -q` — existing write-tool tests
      pass (identity off by default ⇒ static token path unchanged). Covered further by step 7.

- [ ] 5. Update `agent/chat.py` and the 3 existing DIRECT/GATEWAY tests to the `BuildResult` API, and add argparse session-id parsing.
      In `agent/chat.py`: read `result.agent` / `result.mcp_client` / `result.session_manager` instead of tuple-unpacking in
      `_run_single`/`_run_repl`; thread `session_id` into `_run_single(message, session_id=...)` and `_run_repl(session_id=...)`;
      after construction, when `result.session_manager is not None`, call `attach_memory(result.agent, result.session_manager)`
      and print a one-line "resuming session <id>" / "new session <id>" notice ONLY when memory is enabled. Keep the deferred
      `[SYSTEM]` breadcrumb flush in `_ask` verbatim. Rewrite `main` to use `argparse` with `--session-id` (dest `session_id`,
      default `None`) and `message nargs="*"`; add `_resolve_session_id(flag) -> str | None` (precedence: `--session-id` > `MAHALO_SESSION_ID`
      env > `uuid4().hex` only when `settings.memory_enabled`, else `None`). Message words still join with a single space so
      `python -m agent.chat "show my stories"` and bare-REPL `python -m agent.chat` behave identically. Update the three tests in
      `agent/tests/test_gateway_mode.py` that unpack `build_agent()`/`build_agent(tool_mode="gateway")` to read `BuildResult` attributes.
      Files: `agent/chat.py`, `agent/tests/test_gateway_mode.py`
      Verify: `agent/.venv/Scripts/python.exe -m pytest agent -q` — back to 55 passed, 1 skipped (baseline restored with the new API).

- [ ] 6. Add offline Memory unit tests `agent/tests/test_memory_mode.py` (mirror `test_gateway_mode.py` reload style).
      Cover: (a) `build_agent(memory=True, session_id="s1")` with `MAHALO_MEMORY_ID` set constructs with no creds/network, and
      `AgentCoreMemorySessionManager.initialize` (monkeypatched sentinel) is NOT called during construction, and the manager is
      not attached as a hook / `result.agent._session_manager is None`; (b) `attach_memory` invokes `session_manager.register_hooks`
      (i.e. `agent.hooks.add_hook` path — assert per-turn `MessageAddedEvent`/`AfterInvocationEvent` callbacks are present on the
      registry afterward, NOT `agent.add_hook`), calls the `initialize` sentinel exactly once, and sets `agent._session_id`;
      (c) `build_agent(memory=True)` with empty `MAHALO_MEMORY_ID` raises `ValueError`; (d) `build_agent()` (memory off) returns
      `BuildResult(agent=<Agent>, mcp_client=None, session_manager=None)` with no manager constructed; (e) the four `BuildResult`
      rows (DIRECT/GATEWAY × memory off/on) set the right attrs; (f) `build_memory_session_manager` builds a config with
      `filter_restored_tool_context=True`, `batch_size=1`, correct `actor_id`/`session_id`, STM shape; (g) `_resolve_session_id`
      precedence + that argv `"show my stories"` joins to the same message and bare argv takes the REPL path.
      Files: `agent/tests/test_memory_mode.py`
      Verify: `agent/.venv/Scripts/python.exe -m pytest agent/tests/test_memory_mode.py -q` — all new tests pass.

- [ ] 7. Add offline Identity unit tests `agent/tests/test_identity_mode.py`.
      Cover: (a) importing `agent.tools.jira_write_tools` and calling `build_agent(identity=True)` constructs NO `IdentityClient`/boto3
      client (monkeypatch `IdentityClient.__init__` / boto3 `client` sentinel, assert not called); (b) identity off ⇒ `jira_create_story`
      uses the static token (existing behavior, `@tool` signature unchanged); (c) identity on ⇒ `_fetch_jira_token` runs and the injected
      `api_key` flows into `make_request` (monkeypatch `requires_api_key`/`_inner` to inject a fake value, no AWS), and the key value is
      never logged; (d) a credential-fetch exception is caught and returned as `❌ Failed to create story: credential fetch failed (<Type>)`
      with no key in the message. Do NOT assert the CDK `CfnWorkloadIdentity` is used locally (the SDK self-provisions a local identity).
      Files: `agent/tests/test_identity_mode.py`
      Verify: `agent/.venv/Scripts/python.exe -m pytest agent -q` — full agent suite is green: 55 + new Memory + new Identity tests pass
      (1 skipped unchanged). Record the new total in the test output.

- [ ] 8. Create the CDK stack `infra-cdk/mahalo_infra/memory_identity_stack.py` (`MahaloMemoryIdentityStack`).
      Follow `MahaloGatewayStack` conventions (`Stack` subclass, `RemovalPolicy.DESTROY`, `CfnOutput`s). Resources from
      `aws_cdk.aws_bedrockagentcore`: `CfnMemory(name="mahalo-memory", event_expiry_duration=30)` STM-only (no `memory_strategies`
      unless an optional `with_long_term: bool = False` ctor prop is passed — default off); `CfnWorkloadIdentity(name="mahalo-agent")`;
      `CfnApiKeyCredentialProvider(name="mahalo-jira-apikey", ...)` whose API-key value comes from a `CfnParameter(..., no_echo=True)`
      defaulting to the mock token `"mock-jira-token-12345"` so synth has a value. Read the exact required-prop names for these three
      constructs from `infra-cdk/.venv/Lib/site-packages/aws_cdk/aws_bedrockagentcore/__init__.py` before finalizing. Add `CfnOutput`s:
      `MemoryId` (→ `MAHALO_MEMORY_ID`), `WorkloadIdentityArn`, `JiraApiKeyProviderName` (→ `MAHALO_IDENTITY_JIRA_PROVIDER`). The stack is
      independent of the mock/gateway stacks (no cross-references). Do NOT edit `gateway_stack.py`.
      Files: `infra-cdk/mahalo_infra/memory_identity_stack.py`
      Verify: step 10 wires it into `app.py`; standalone check now:
      `python -c "from mahalo_infra.memory_identity_stack import MahaloMemoryIdentityStack"` in `infra-cdk/` imports without error.

- [ ] 9. Add offline CDK synth assertions `infra-cdk/tests/test_memory_identity_stack.py` (mirror `test_gateway_stack.py`).
      Synth the stack alone via `assertions.Template.from_stack(MahaloMemoryIdentityStack(app, "MahaloMemoryIdentityStack", env=_ENV))`
      and assert: exactly one `AWS::BedrockAgentCore::Memory` with `EventExpiryDuration == 30` and NO `MemoryStrategies` (STM default);
      exactly one `AWS::BedrockAgentCore::WorkloadIdentity`; exactly one `AWS::BedrockAgentCore::ApiKeyCredentialProvider`;
      the `MemoryId` and provider-name `CfnOutput`s exist; the API-key `CfnParameter` is `NoEcho: true`.
      Files: `infra-cdk/tests/test_memory_identity_stack.py`
      Verify: in `infra-cdk/` run `python -m pytest tests/test_memory_identity_stack.py -q` — all assertions pass.

- [ ] 10. Wire `MahaloMemoryIdentityStack` into `infra-cdk/app.py`.
      Add one construction line `MahaloMemoryIdentityStack(app, "MahaloMemoryIdentityStack", env=_ENV)` alongside the existing stacks
      (it has no cross-references, so `cdk synth --all` ordering is unaffected). Import the class at the top.
      Files: `infra-cdk/app.py`
      Verify: in `infra-cdk/` run `cdk synth --all` (exit 0) and `python -m pytest tests -q` — the whole infra suite (gateway +
      new memory/identity) passes and all templates synthesize, confirming Task-4 synth is unregressed.

- [ ] 11. Update docs: `docs/ARCHITECTURE.md` and `docs/CONTINUATION.md`.
      In `ARCHITECTURE.md`, note Memory is now session-id-keyed STM via the Strands session-manager and Identity brokers the one demo
      outbound path (`jira_create_story`); keep the existing diagram. In `CONTINUATION.md`, append the operator runbook from the design:
      `aws sso login --profile lava`; `cd infra-cdk && cdk deploy MahaloMemoryIdentityStack --profile lava`; export
      `MAHALO_MEMORY_ENABLED=true` + `MAHALO_MEMORY_ID=<MemoryId output>` (optionally `MAHALO_IDENTITY_ENABLED=true`); the two-invocation
      persistence check (`--session-id demo-1` write then re-read) and the Identity write; note that the first Identity-enabled local run
      self-provisions a local workload identity and writes `.agentcore.json` (dev-auth cache, deletable); teardown via
      `cdk destroy MahaloMemoryIdentityStack`. These are documented, NOT executed here.
      Files: `docs/ARCHITECTURE.md`, `docs/CONTINUATION.md`
      Verify: docs-only; re-run the full offline gate once more as the final integration check (see step 12).

- [ ] 12. Final whole-repo offline gate (integration verification across all FEAT seams).
      Run, in order: `agent/.venv/Scripts/python.exe -m pytest agent -q` (55 passed + new Memory/Identity tests, 1 skipped);
      in `infra-cdk/` `cdk synth --all` (exit 0) and `python -m pytest tests -q`; `pytest tools-lambdas/tests -q` (must stay
      unaffected). Confirm zero LangChain imported and that with all toggles OFF `build_agent()` behavior is byte-for-byte the prior
      baseline. Clean up any stray `.agentcore.json`/`cdk.out` artifacts produced during verification. Do NOT deploy and do NOT commit.
      Files: none (verification only)
      Verify: all three suites green and `cdk synth --all` exits 0 — Task 5 OFFLINE gate satisfied.
