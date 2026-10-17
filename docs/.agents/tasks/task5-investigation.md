# Task 5 Investigation — AgentCore Memory & Identity

Mandatory pre-design investigation for Task 5 (add AgentCore **Memory** for
session/conversation state and AgentCore **Identity** for tool credentials). Every
claim is cited to installed SDK source (exact file + symbol) and/or an AWS doc URL.
Content from AWS docs was rephrased for compliance with licensing restrictions.

Investigated against the INSTALLED SDKs in `agent/.venv`
(`strands-agents 1.61.1`, `bedrock-agentcore 1.24.1`) and the CDK libs in
`infra-cdk/.venv` (`aws-cdk-lib 2.273.0`). Paths below are workspace-relative
forward-slash where they reference project artifacts; venv/third-party paths are
given in full so later steps can re-open the exact source.

---

## 0. Baseline confirmed by reading the code

- The agent today is effectively a **stateless CLI**. `agent/chat.py` builds a
  fresh agent per single-shot invocation (`_run_single` → `build_agent(**_IDENTITY)`
  → one `agent(message)` call) and, in the REPL, keeps history only in-process via
  Strands' own `agent.messages` list (`_repl_loop`). There is **no cross-invocation
  persistence**: nothing writes session/conversation state anywhere durable.
  (`agent/chat.py`, `agent/strands_agent.py::build_agent`.)
- The HITL breadcrumb mechanism writes directly to `agent.messages`
  (`agent/chat.py::_emit_system_signal` → `agent.messages.append(...)`), so whatever
  Memory integration we add must not corrupt that list mid-tool-cycle (see §1.4).
- What Memory must **replace**: the mahalo-dock in-memory session store
  (`D:/<USER>/LavaCode/AI/mahalo-dock/backend/app/agent/session.py` —
  `_sessions: dict[str, ChatSession]`, `get_or_create_session`, `clear_session`,
  plus `ChatSession.pending_action` for propose/confirm). That store was explicitly
  "no persistence needed for PoC" (its own docstring). Task 5 upgrades this to a
  durable, managed store keyed by session/actor.
- Green baseline for Task 5 to preserve: `agent/.venv/Scripts/python.exe -m pytest agent -q`
  → **55 passed, 1 skipped** (ran during this investigation; the 1 skip is the live
  tunnel integration test).

---

## 1. AgentCore MEMORY

### 1.1 The integration exists and is first-class (Strands ⇄ AgentCore Memory)

`bedrock-agentcore 1.24.1` ships a **native Strands session-manager** that bridges
Strands' session abstraction to AgentCore Memory. It is installed in the agent venv:

- `bedrock_agentcore/memory/integrations/strands/session_manager.py`
  → `class AgentCoreMemorySessionManager(RepositorySessionManager, SessionRepository)`
  (line 83). Its `__init__` (line 126) takes `agentcore_memory_config: AgentCoreMemoryConfig`,
  `region_name`, optional `boto_session` / `boto_client_config`, and an optional `converter`.
- `bedrock_agentcore/memory/integrations/strands/config.py`
  → `class AgentCoreMemoryConfig(BaseModel)` with required `memory_id`, `session_id`,
  `actor_id`, and optional `retrieval_config: Dict[str, RetrievalConfig]`, `batch_size`
  (1–100, default 1), `flush_interval_seconds`, `context_tag`,
  `filter_restored_tool_context`, `default_metadata`, `metadata_provider`,
  `persistence_mode` (`FULL`/`NONE`), `async_mode`. Also `class RetrievalConfig`
  (`top_k` default 10, `relevance_score` default 0.2, `strategy_id`, `initialization_query`).
- `bedrock_agentcore/memory/integrations/strands/README.md` is the usage reference and
  shows the exact wiring (quoted structurally below).

**Crucially, `AgentCoreMemorySessionManager` subclasses `RepositorySessionManager`,
which is Strands' own base** (`strands/session/repository_session_manager.py`;
`strands/session/session_manager.py::SessionManager`). The Strands `Agent` constructor
accepts `session_manager: SessionManager | None = None`
(`strands/agent/agent.py` line 225; stored at line 546). So Memory plugs in through the
**documented, native Strands `session_manager=` seam** — no monkey-patching, no fork.

Doc confirmation: AWS publishes a Strands-specific Memory page,
[Using AgentCore Memory with the Strands SDK](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/strands-sdk-memory.html),
and the general [Add memory to your AgentCore agent](https://docs.aws.amazon.com/id_id/bedrock-agentcore/latest/devguide/memory.html).

### 1.2 How a Strands agent READS/WRITES session + conversation history

Wiring (from the integration README and the class source):

```python
from strands import Agent
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

cfg = AgentCoreMemoryConfig(memory_id=MEM_ID, session_id=SESSION_ID, actor_id=ACTOR_ID)
session_manager = AgentCoreMemorySessionManager(cfg, region_name="us-east-1")
agent = Agent(system_prompt="...", session_manager=session_manager)
```

Mechanics, grounded in `session_manager.py`:

- **WRITE (per turn):** `append_message(self, message, agent, **kwargs)` (line 834) is
  the Strands hook that fires as messages are added; it converts each Strands message to
  AgentCore Memory event payloads and ultimately calls the data-plane `create_event`.
  With `batch_size > 1`, messages buffer (`_message_buffer`, `BufferedMessage`) and flush
  as one `create_event` call; with the default `batch_size=1` each message sends
  immediately.
- **READ (on construction):** `initialize(self, agent, **kwargs)` (line 1002) runs during
  `Agent(...)` construction — it rehydrates prior session messages / agent state from
  Memory (short-term event history) and, when `retrieval_config` is set, injects retrieved
  long-term records into the agent's context wrapped in a `<user_context>` tag
  (`context_tag`, config default `"user_context"`). It warns and continues if a second
  agent attaches to the same session ("one agent per session").
- **Flush / teardown:** `close()` (line 1231) flushes buffered messages. The README is
  explicit: with `batch_size > 1` you **must** use the manager as a context manager
  (`with AgentCoreMemorySessionManager(...) as sm:`) or call `close()`, or buffered
  messages are lost. With the default `batch_size=1` there is nothing to flush.
- **Underlying event shape:** the low-level `MemoryClient.create_event(memory_id, actor_id,
  session_id, messages=[(text, role), ...], ...)` (`bedrock_agentcore/memory/client.py`
  line 436) is the short-term write primitive; its docstring states this is "the basis of
  short-term memory," and if the memory resource has strategies, these events feed long-term
  extraction. `extraction_mode="SKIP"` stores short-term only. `get_last_k_turns`
  (line 1159) and `list_events` (line 818) are the read primitives. The session-manager
  wraps all of this — Task 5 agent code should use the session-manager, not raw client calls.

### 1.3 Short-term (STM) vs long-term (LTM); session id; retention

- **STM = raw turns in a session.** Each user/assistant turn is stored as an event; the
  agent reloads the conversation on the next construction with the same `session_id`
  (AWS [memory types](https://docs.aws.amazon.com/id_id/bedrock-agentcore/latest/devguide/memory-types.html)).
  STM needs **no strategies** — a bare `create_memory(name=...)` is enough.
- **LTM = extracted summaries / semantic facts / user preferences,** enabled by adding
  **memory strategies** to the resource. The three built-ins (README + AWS
  [long-term memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/long-term-memory-long-term.html)):
  `summaryMemoryStrategy`, `userPreferenceMemoryStrategy`, `semanticMemoryStrategy`, each
  with `namespaceTemplates` (e.g. `/summaries/{actorId}/{sessionId}/`,
  `/preferences/{actorId}/`, `/facts/{actorId}/`). LTM records are scoped to their
  namespace (AWS [memory organization](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-organization.html)).
  Retrieval into context is controlled per-namespace by `RetrievalConfig(top_k, relevance_score)`.
- **Session id / actor id:** both are **supplied by the caller** via `AgentCoreMemoryConfig`
  (`session_id`, `actor_id`, each `min_length=1`). `session_id` groups a conversation;
  `actor_id` identifies the user/agent (reuse the same `actor_id` across a user's sessions
  so LTM accumulates per user). For mahalo this maps cleanly to the existing identity model:
  `actor_id = dev-6` (the demo "Lava Dev" identity used throughout — see
  `agent/strands_agent.py` `developer_id="dev-6"` and the mahalo-dock
  `services/identity.py` which maps all demo logins to `dev-6`), and `session_id` =
  a per-conversation id (new uuid per REPL session / provided by the API in Task 6).
- **Retention:** `event_expiry_days` on create (default **90** in
  `MemoryClient.create_memory`; **30** in the CDK `CfnMemory` prop default — see §3).
  This governs how long raw short-term events live. Set it explicitly so the two paths
  don't silently differ.

### 1.4 Usable BEFORE Task 6 Runtime? — YES, confirmed (not coupled to Runtime)

- The session-manager talks to Memory purely over boto3 data/control clients it builds
  itself: in `__init__` it sets `self.memory_client.gmcp_client = session.client("bedrock-agentcore-control", ...)`
  and `self.memory_client.gmdp_client = session.client("bedrock-agentcore", ...)`
  (`session_manager.py` ~lines 190–200). Nothing requires the agent to be hosted on
  AgentCore Runtime; it only needs AWS credentials (the `lava` profile) and the two
  AgentCore endpoints. So Memory works from the **local CLI today**, exactly like the
  Gateway client did in Task 4.
- Contrast with Identity's Workload Access Token path, which *is* Runtime-coupled
  (see §2.3) — Memory is not.
- **Construction caveat (must respect in design):** `initialize()` runs **synchronously
  inside `Agent(...)` construction** and performs network reads
  (`read_session`/`read_agent`/`list_messages`). This means in GATEWAY mode, where
  `build_agent` is deliberately **offline-safe** (it constructs the MCP client without
  starting it), adding a `session_manager` would make `build_agent` hit AWS at construction
  time. Design must therefore make the session-manager **opt-in** (a new flag/param), keep
  the default DIRECT/offline construction behavior intact, and preserve the 55/1 offline test
  baseline (the existing tests call `build_agent()` with no creds).
- **HITL interaction (must respect):** the session-manager drives Strands' message lifecycle.
  The Task-4 `[SYSTEM]` breadcrumb logic in `agent/chat.py::_emit_system_signal` appends
  directly to `agent.messages`; combined with a session-manager those appended messages also
  get persisted as events. The existing deferred-breadcrumb-flush fix (only append once a
  tool cycle closes) must stay — otherwise a persisted half-open toolUse/toolResult pair can
  both corrupt history and be replayed on rehydrate. `filter_restored_tool_context=True` on
  the config strips historical toolUse/toolResult blocks on restore and is a candidate
  safeguard; the design must decide whether to enable it.

### 1.5 Low-level alternative (not recommended for the agent path)

`bedrock_agentcore/memory/__init__.py` also exports `MemoryClient`,
`MemoryControlPlaneClient`, and `MemorySession`/`MemorySessionManager`
(`bedrock_agentcore/memory/session.py`). These are the raw data/control clients. The agent
should use the **Strands session-manager** (§1.1–1.2), not these, because the session-manager
is what hooks Strands' message lifecycle. The raw clients are only relevant if a later step
needs out-of-band event inspection or admin.

---

## 2. AgentCore IDENTITY

### 2.1 What it actually brokers

AgentCore Identity brokers **outbound tool/service credentials** so the agent fetches them
at call time instead of embedding secrets. The installed SDK
(`bedrock_agentcore/identity/__init__.py` → `bedrock_agentcore/identity/auth.py`) exposes
four decorators:

- `requires_access_token(provider_name, scopes, auth_flow=..., ...)` — fetches an **OAuth2
  access token** from an AgentCore Identity credential provider and injects it into the
  decorated function (`into="access_token"`). `auth_flow` ∈ `{"M2M", "USER_FEDERATION",
  "ON_BEHALF_OF_TOKEN_EXCHANGE"}`. Backed by `IdentityClient.get_token(...)`.
  Docs: [Obtain OAuth 2.0 access token](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-authentication.html),
  [Add OAuth client (included provider)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-add-oauth-client-included.html).
- `requires_api_key(provider_name, into="api_key")` — fetches a stored **API key** from an
  AgentCore Identity API-key credential provider via `IdentityClient.get_api_key(...)`.
  Docs: [Add an API key](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-add-api-key.html).
- `requires_wat(into="identity_wat")` — reads the **Workload Access Token (WAT)** that the
  **Runtime platform mints** before the agent runs, via
  `BedrockAgentCoreContext.get_workload_access_token()`, for identity propagation across
  hops (header `X-Amz-Bedrock-AgentCore-Identity-WAT`). Docs:
  [Get workload access token](https://docs.aws.amazon.com/zh_cn/bedrock-agentcore/latest/devguide/get-workload-access-token.html).
- `requires_iam_access_token(audience, ...)` — gets an **AWS-signed JWT** from STS
  `GetWebIdentityToken` (no client secret) for M2M auth to services that validate OIDC;
  requires account-level "AWS IAM Outbound Web Identity Federation" to be enabled and
  `sts:GetWebIdentityToken` on the execution role (per the decorator's own docstring).

Provisioning: credential providers are created in AgentCore Identity (console "Outbound
Auth", CLI, or API) and referenced by `provider_name`/ARN from agent code
([OAuthCredentialProvider API](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_OAuthCredentialProvider.html)).
Workload identities are the identity under which a workload retrieves those credentials,
and access can be scoped per workload identity
([scope credential-provider access](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/scope-credential-provider-access.html)).

### 2.2 How the agent/Gateway would obtain tool credentials through it

Two seams, both already partly visible in this repo:

1. **In the agent tool (outbound):** decorate a tool with `@requires_api_key` /
   `@requires_access_token`; the decorator injects the fetched secret as a kwarg
   (`api_key=` / `access_token=`) so the tool code never holds a static secret. For a
   local (non-Runtime) run, `auth.py::_set_up_local_auth` auto-creates a local workload
   identity + user id in a `.agentcore.json` file and fetches a workload access token so
   the decorators work off-Runtime too (dev path). On Runtime the WAT arrives in the
   request context automatically.
2. **At the Gateway target (outbound, config-side):** the Gateway target's
   `credentialProviderConfigurations` selects how the Gateway authenticates to the backend.
   Today Task 4 uses `GATEWAY_IAM_ROLE` (`infra-cdk/mahalo_infra/gateway_stack.py`,
   `CredentialProviderConfigurationProperty(credential_provider_type="GATEWAY_IAM_ROLE")`).
   AgentCore Identity's OAuth2/API-key credential providers are the alternative values here
   (the CDK exposes `CfnApiKeyCredentialProvider` / `CfnOAuth2CredentialProvider` — see §3),
   letting the Gateway attach a brokered OAuth token / API key to the backend call instead
   of a static header.

### 2.3 How Identity relates to Task-4 Gateway auth — what it ADDS vs. what already works

This is the critical delineation (do NOT duplicate or break Task 4):

- **Two different directions.** Task 4 solved **inbound** auth to the Gateway: the agent
  SigV4-signs its MCP request as service `bedrock-agentcore` for the Gateway's default
  `AWS_IAM` authorizer (`agent/gateway_client.py::SigV4Auth`,
  `_GATEWAY_SIGNING_SERVICE = "bedrock-agentcore"`; validated live per
  `docs/.agents/tasks/task4-verification.md`). AgentCore Identity is about **outbound**
  credentials — what the agent/Gateway presents to the **backend tool** (Jira/Confluence/
  GitHub/ServiceNow). These do not overlap; Identity does **not** replace the Gateway
  inbound authorizer.
- **The Lambdas' static `X-API-Token`.** The mock Lambdas authenticate inbound requests with
  a static header (`common/` auth; tokens like `mock-jira-token-12345`, see
  `docs/CONTINUATION.md`). In the deployed Gateway path the Gateway→Lambda call is authorized
  by `GATEWAY_IAM_ROLE` (IAM invoke), and the `X-API-Token` is the Lambda's own app-level
  check. **Identity's role, if adopted, is to REPLACE those static per-service tokens** with
  OAuth2 tokens / brokered API keys fetched at call time (via a credential provider on the
  Gateway target or `@requires_*` in a tool), removing the hard-coded secret. It does **not**
  replace the Gateway's IAM invoke permission and it does **not** replace the agent's inbound
  SigV4 to the Gateway.
- **Net for Task 5 (given the user's standing decision):** the user explicitly chose to
  **keep `AWS_IAM` now and defer Cognito/dev-mode** (original request messages #3). Since the
  four backends are *mocks* with a static token that already works end-to-end over the
  Gateway, full Identity credential-provider brokering is **additive and largely
  demonstrative** here — the design should scope Identity to the **minimum that shows the
  capability without breaking Task 4**: e.g. provision a workload identity (and optionally one
  API-key credential provider) and wire ONE representative outbound path, while leaving the
  working SigV4-inbound + `GATEWAY_IAM_ROLE` + `X-API-Token` chain intact. The design must
  call this scope decision out explicitly rather than rip out working auth.

---

## 3. CDK vs boto3 provisioning (IaC approach)

`aws-cdk-lib 2.273.0` **does ship stable L1 constructs** for both Memory and Identity in
`aws_cdk.aws_bedrockagentcore` (same module Task 4 used for `CfnGateway`/`CfnGatewayTarget`).
Confirmed by reading `infra-cdk/.venv/Lib/site-packages/aws_cdk/aws_bedrockagentcore/__init__.py`:

- **`CfnMemory`** (class at line 32551; CloudFormation `AWS::BedrockAgentCore::Memory`).
  Required props: `name` and `event_expiry_duration: int` (prop docstring: "Event retention
  in days. Defaults to 30"). Optional: `description`, `encryption_key_arn`, `indexed_keys`,
  `memory_execution_role_arn`, and **`memory_strategies`** (a list of
  `CfnMemory.MemoryStrategyProperty` with `summary_override` / `semantic_override` /
  `user_preference_override` / `custom_memory_strategy` etc.) — i.e. STM is just
  `CfnMemory(name=..., event_expiry_duration=...)`, LTM adds `memory_strategies`.
- **`CfnWorkloadIdentity`** (class at line 51726; `AWS::BedrockAgentCore::WorkloadIdentity`).
  `__init__(scope, id, *, name, allowed_resource_oauth2_return_urls=None, tags=None)`.
- **`CfnApiKeyCredentialProvider`** (line 6890) and **`CfnOAuth2CredentialProvider`**
  (line 38617) — the outbound credential providers Identity brokers.

**Decision input:** prefer the **CDK L1 path** (consistent with Task 4's
`MahaloGatewayStack`, survives the monthly account reset per `docs/CONTINUATION.md`, and the
constructs exist). A `boto3`/custom-resource path is **not** required for Memory or Identity
in this CDK version. One nuance to decide in design: the agent needs the **memory_id at
runtime**. With CDK, surface it as a `CfnOutput` (like `GatewayMcpUrl` today) and feed it to
the agent via env (`MAHALO_MEMORY_ID`, mirroring the `MAHALO_GATEWAY_MCP_URL` pattern in
`agent/config.py`). Alternatively the agent could `create_or_get_memory(name=...)` at startup
(`MemoryClient.create_or_get_memory`, idempotent by name), but that mixes provisioning into
the agent and is less clean than the CDK+output+env pattern already established — the design
should pick CDK-provisioned + env-fed and say so.

Existing IaC conventions to follow (so Task 5 matches the repo): per-feature `Stack`
subclass under `infra-cdk/mahalo_infra/` wired in `infra-cdk/app.py` with
`env=cdk.Environment(account="<AWS_ACCOUNT_ID>", region="us-east-1")`; offline assertion tests
under `infra-cdk/tests/` using `aws_cdk.assertions.Template.from_stack(...)` (see
`infra-cdk/tests/test_gateway_stack.py`); `cdk synth --all` as the offline gate. `requirements.txt`
already allows this CDK version (`aws-cdk-lib>=2.251,<3`).

---

## 4. Build / test / verification commands (discovered, for the planner)

- Agent unit+integration suite (offline-safe; 1 live skip):
  `agent/.venv/Scripts/python.exe -m pytest agent -q` — baseline **55 passed, 1 skipped**.
- Agent deps: `agent/requirements.txt` (`strands-agents==1.61.1`, `bedrock-agentcore==1.24.1`,
  `boto3`, `httpx`, `pytest`). The Strands Memory integration is already importable in the
  venv (the `bedrock-agentcore[strands-agents]` extra is satisfied — the
  `memory/integrations/strands/` package is present).
- CDK offline gate (run in `infra-cdk/` with its own `.venv`): `cdk synth --all` (exit 0),
  and `python -m pytest tests -q` for the assertion suite.
- Tools-lambdas suite (unaffected by Task 5 but part of the repo's green gate):
  `tools-lambdas/.venv` + `pytest tools-lambdas/tests -q`.
- AWS: profile `lava`, region `us-east-1`, account `<AWS_ACCOUNT_ID>`; re-auth via
  `aws sso login --profile lava` (per `docs/CONTINUATION.md`). Memory needs only creds +
  the AgentCore endpoints (no Runtime) to run live from the CLI.

---

## 5. Design-decision inputs / open questions (for the design/plan step)

1. **Opt-in session-manager** so DIRECT/GATEWAY offline construction stays offline (preserve
   the 55/1 baseline). New knobs mirroring existing config: `MAHALO_MEMORY_ID`,
   `MAHALO_MEMORY_ENABLED` (or a `memory` flag on `build_agent`), plus `session_id`/`actor_id`
   plumbing (actor_id defaults to the `developer_id` already threaded through, i.e. `dev-6`).
2. **STM-only vs STM+LTM for the demo.** STM (bare `CfnMemory`, no strategies) fully replaces
   the old in-memory `session.py` and is the lowest-risk, lowest-cost first cut; LTM strategies
   (summary/preference/semantic) are an additive enhancement with extra cost and model calls.
   Recommend STM first, LTM behind a toggle — but the design makes the call.
3. **HITL safety:** keep the deferred-breadcrumb flush; decide on
   `filter_restored_tool_context=True` to avoid replaying half-open tool cycles from Memory.
4. **Identity scope (see §2.3):** given AWS_IAM is being kept and backends are mocks with a
   working static token, decide how much Identity to actually provision (minimum: a
   `CfnWorkloadIdentity`; optional: one `CfnApiKeyCredentialProvider` wired to one tool path
   as a demonstration) WITHOUT removing the Task-4 SigV4-inbound / `GATEWAY_IAM_ROLE` /
   `X-API-Token` chain that already works.
5. **IaC:** CDK L1 (`CfnMemory`, `CfnWorkloadIdentity`, credential-provider constructs) with
   `CfnOutput` → env, consistent with `MahaloGatewayStack`; no boto3 custom resource needed.
6. **Cost/teardown:** Memory incurs charges for STM events, stored LTM records, and retrieval
   (AWS [harness-memory pricing note](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-memory.html));
   keep it in a destroyable stack per the Task-8 re-deployable/teardown requirement.

---

## 6. Deliverable

This investigation: `docs/.agents/tasks/task5-investigation.md`.

### Sources

- Installed SDK (agent venv): `bedrock_agentcore/memory/integrations/strands/session_manager.py`,
  `.../strands/config.py`, `.../strands/README.md`, `bedrock_agentcore/memory/__init__.py`,
  `bedrock_agentcore/memory/client.py`, `bedrock_agentcore/memory/controlplane.py`,
  `bedrock_agentcore/identity/__init__.py`, `bedrock_agentcore/identity/auth.py`,
  `strands/agent/agent.py`, `strands/session/*`.
- Installed CDK (infra-cdk venv): `aws_cdk/aws_bedrockagentcore/__init__.py`
  (`CfnMemory` line 32551, `CfnWorkloadIdentity` line 51726, `CfnApiKeyCredentialProvider`
  line 6890, `CfnOAuth2CredentialProvider` line 38617).
- Project: `agent/chat.py`, `agent/strands_agent.py`, `agent/config.py`, `agent/gateway_client.py`,
  `infra-cdk/mahalo_infra/gateway_stack.py`, `infra-cdk/app.py`, `infra-cdk/tests/test_gateway_stack.py`,
  `docs/ARCHITECTURE.md`, `docs/PLAN.md`, `docs/CONTINUATION.md`; read-only reference
  `mahalo-dock/backend/app/agent/session.py`, `mahalo-dock/backend/app/services/identity.py`.
- AWS docs (rephrased for compliance): memory get-started / types / organization / long-term /
  strands-sdk-memory / harness-memory, and identity authentication / OAuth-client / API-key /
  workload-access-token / scope-credential-provider / runtime-oauth (URLs inline above).
