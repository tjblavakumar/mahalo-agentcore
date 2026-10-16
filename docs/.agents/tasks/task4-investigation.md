# Task 4 — Investigation (AgentCore Gateway + MCP exposure layer)

**Status:** MANDATORY STEP 0 complete. This is a citation-backed investigation,
not a design. It grounds every claim in (a) the INSTALLED SDK source under
`agent/.venv` and `infra-cdk/.venv`, (b) the live botocore service model for
`bedrock-agentcore-control`, and (c) official AWS docs. No AWS resources were
created; no git commit/push; nothing written outside the
`mahalo-agentcore` workspace.

**Environment confirmed:** `aws sts get-caller-identity --profile lava` →
account `051570254217`, SSO admin role, us-east-1. Installed:
`strands-agents 1.61.1`, `bedrock-agentcore 1.24.1`, `boto3 1.43.114` /
`botocore 1.43.114` (agent venv), `aws-cdk-lib 2.273.0` (infra-cdk venv).

> Content was rephrased for compliance with licensing restrictions; AWS doc text
> is paraphrased and linked inline.

---

## TL;DR of the four implications (design questions A–D)

- **A. Tool granularity** — Expose each agent operation as ONE MCP tool via a
  per-service Gateway *target* backed by that service's Lambda. The Lambda target
  `toolSchema` is a flat list of `ToolDefinition` objects (`name`,
  `description`, `inputSchema` JSON-Schema, optional `outputSchema`). Keep the
  tool names identical to the current Strands `@tool` function names so behavior
  and prompts carry over. (Evidence: §1, §2.)
- **B. HITL preservation** — The native `BeforeToolCallEvent` interrupt DOES
  fire for MCP-sourced tools: the tool executor raises the before-hook for every
  tool uniformly before `MCPAgentTool.stream()` runs, so no HTTP/MCP write
  happens pre-approval. BUT the hook matches on `event.tool_use["name"]`, and
  Gateway renames every tool to `"<targetName>___<toolName>"` (triple
  underscore). The current `WRITE_TOOL_NAMES` exact-match set will NOT fire
  against the prefixed names. This is the single biggest correctness risk for
  Task 4 and must be designed around (strip the `___` prefix, or rename the MCP
  tools back via a client-side prefix/override). (Evidence: §1.)
- **C. Dual-mode / rollout** — The agent can keep today's local `@tool` HTTP
  tools AND add Gateway MCP tools behind a flag, because Strands accepts an
  `MCPClient` directly in `Agent(tools=[...])` alongside decorated tools. The
  MCP tools only exist inside the client's context manager, which shapes the
  rollout. (Evidence: §1.)
- **D. IaC + auth** — The whole Gateway + Lambda-target layer can be built in
  native CDK CloudFormation: `aws-cdk-lib 2.273.0` already ships the STABLE L1
  constructs `CfnGateway` and `CfnGatewayTarget` (with
  `McpLambdaTargetConfigurationProperty`, `ToolSchemaProperty`,
  `ToolDefinitionProperty`). No boto3 custom resource is required (the
  `bedrock_agentcore.gateway.GatewayClient` boto3 path exists as a fallback).
  Inbound auth is one of `CUSTOM_JWT` (Cognito/OIDC), `AWS_IAM`,
  `AUTHENTICATE_ONLY` (SigV4), or `NONE`; outbound tool creds for a Lambda target
  default to `GATEWAY_IAM_ROLE` (the gateway's own IAM role invokes the Lambda).
  (Evidence: §2, §4.)
- **CRITICAL GAP (E)** — A Gateway Lambda-target invocation is **NOT** an HTTP
  event. It delivers a flat `event` = `{property: value}` map (the tool's input
  args) and puts the tool name in `context.client_context.custom`. Task 3's
  `common/router.py` normalizes only Function-URL-v2 / API-Gateway HTTP events
  (method/path/headers/body); given a Gateway event it falls through to
  `GET /` and returns 404 for every call. The design's "Task 4 note" claim that
  the router already tolerates a non-Function-URL event is **false for Gateway
  targets**. An adapter is mandatory. (Evidence: §3.)

---

## 1. Strands Agents SDK 1.61.1 — how MCP tools are consumed

All paths below are under
`agent/.venv/Lib/site-packages/strands/`.

### 1.1 The MCP client / tool-provider class

- `strands.tools.mcp.MCPClient` (`tools/mcp/mcp_client.py`) is the MCP
  server connection. It subclasses `ToolProvider` and implements
  `async load_tools(...)`, so it is passed **directly** into
  `Agent(tools=[...])` — the Agent treats it as a provider that yields tools.
  Exported from `strands.tools.mcp.__init__` as `MCPClient` (also
  `MCPServerConfig`, `ToolFilters`, `MCPAgentTool`).
- Construction accepts either a `transport_callable` OR a `url=` (for
  streamable-HTTP / SSE), plus `headers=`, `auth=` (OAuth client-credentials),
  `auth_provider=` (custom `httpx.Auth`), `prefix=`, `tool_filters=`,
  `startup_timeout=`, `continue_on_error=`. For an AgentCore Gateway (an MCP
  server over HTTPS) the relevant path is `MCPClient(url=<gateway MCP url>,
  headers={"Authorization": "Bearer <jwt>"})` or an `auth`/`auth_provider` that
  supplies the bearer token. (Source: `MCPClient.__init__` docstring and the
  `ValueError` guards requiring exactly one of transport/url.)
- The connection runs on a background thread and is **only live inside the
  context manager** (`with MCPClient(...) as c:` / `start()`/`stop()`).
  `load_tools` auto-starts if needed. The class docstring and
  `CLIENT_SESSION_NOT_RUNNING_ERROR_MESSAGE` both stress that the agent must be
  used within the client's context manager. This directly constrains rollout
  (design D): the agent invocation that uses MCP tools must run inside
  `with mcp_client:`.
- `MCPClient.load_servers(config, ...)` builds clients from an `mcpServers`
  JSON mapping (stdio `command` or HTTP `url`), with `${VAR}` interpolation,
  `disabled`, `continue_on_error`, per-server `prefix`, and
  `prefix_with_server_name`. This is an alternative to hand-constructing clients.

### 1.2 How an MCP tool becomes an agent tool (schema mapping)

- `strands.tools.mcp.mcp_agent_tool.MCPAgentTool` (`tools/mcp/mcp_agent_tool.py`)
  is an `AgentTool` adapter wrapping one `mcp.types.Tool`.
  - `tool_name` → `name_override or mcp_tool.name` (the MCP server's tool name).
  - `tool_spec` → `{"name": tool_name, "description": mcp_tool.description,
    "inputSchema": {"json": input_schema(mcp_tool)}}`, plus optional
    `outputSchema` and opaque `annotations`. So the MCP tool's JSON input schema
    becomes the agent tool's `inputSchema.json` verbatim — the model sees exactly
    the Gateway-published schema.
  - `tool_type` → always `"python"`.
  - `stream(tool_use, ...)` delegates to
    `mcp_client.call_tool_async(tool_use_id=..., name=self.mcp_tool.name,
    arguments=tool_use["input"], ...)` and yields a single `ToolResultEvent`.
    Note it calls the server with the **original** `mcp_tool.name`, while the
    agent/model/hook see `self.tool_name` (which may be overridden).
- `MCPClient._list_all_tools_sync()` pages through `list_tools_sync(...)` applying
  the constructor `prefix` and `tool_filters`, returning `list[MCPAgentTool]`.

### 1.3 Does the native HITL interrupt (Task 2) still fire for MCP tools?

**Yes — the before-tool hook is dispatched uniformly for ALL tools, MCP
included, and before the tool body/stream runs.**

- The gating path is `strands/tools/executors/_executor.py :: ToolExecutor._stream`.
  It resolves `tool_func = _lookup_tool(agent, tool_name)` then, in a loop,
  fires `BeforeToolCallEvent[...](agent=..., selected_tool=tool_func,
  tool_use=tool_use, ...)` via `agent.hooks.invoke_callbacks_async(...)`
  **before** dispatching to `ctx.tool.stream(...)`. For an MCP tool,
  `ctx.tool` is the `MCPAgentTool`, whose `stream()` is the only place the MCP
  server call happens — so a before-hook interrupt stops the call before any
  MCP/HTTP write. (Source: grep + context read of `_executor.py`;
  `BeforeToolCallEvent` imported from `...hooks`.)
- Task 2's gate is `agent/approval.py :: WriteApprovalHook`, which registers on
  `BeforeToolCallEvent` and keys on `event.tool_use["name"] in WRITE_TOOL_NAMES`,
  calling `event.interrupt(...)` (first pass raises `InterruptException`,
  resume returns the stored response; non-`APPROVE` sets
  `event.cancel_tool`). The mechanism is tool-source-agnostic.

**The catch (HITL risk for design B):** the local `@tool` name is the function
name — confirmed in `tools/decorator.py` (`func_name = self.func.__name__`;
`tool_spec = {"name": func_name, ...}`), e.g. `github_create_branch`. When the
same operation is served through Gateway, the MCP tool name the agent sees is
`"<targetName>___<toolName>"` (see §2.4 and §3 — Gateway prefixes every tool
with its target name using the `___` delimiter). So:
- `event.tool_use["name"]` becomes e.g. `mock-github___github_create_branch`.
- The current exact-match `WRITE_TOOL_NAMES` set (`{"github_create_branch", ...}`)
  will **miss**, and the write would execute WITHOUT approval.

Mitigations the design must pick ONE of:
1. In `WriteApprovalHook`, match on the segment after the last `___`
   (`name.rsplit("___", 1)[-1] in WRITE_TOOL_NAMES`). Lowest-churn; also keeps
   working for local tools (no `___`).
2. Give each Gateway target a name such that `target___tool` is still
   recognizable, and/or use `MCPClient(prefix=...)` / `MCPAgentTool` name_override
   to normalize names back to the bare tool name before they reach the hook.
Either way, `build_proposal()` in `approval.py` (which does
`name.partition("_")` to derive the system prefix) will also need to parse the
`target___tool` shape, or receive the already-stripped name.

### 1.4 Dual-mode feasibility (design C)

`strands_agent.build_agent()` currently passes
`tools=[*READ_TOOLS, *WRITE_TOOLS]` (25 decorated tools) and
`hooks=[WriteApprovalHook()]`. Because `Agent(tools=[...])` accepts an
`MCPClient` (a `ToolProvider`) in the same list as decorated tools, a
Gateway-backed build can add one or more `MCPClient`s to `tools=[...]` while
keeping (or replacing) the local tools behind a config flag. Constraint: MCP
tools are only usable inside the `MCPClient` context manager, so the CLI/driver
(`agent/chat.py`) must wrap the invocation in `with mcp_client: ...` for the
Gateway path. Offline import-safety (a Task-1/2 invariant) is preserved as long
as the client is constructed but not `start()`ed at import time.

---

## 2. AgentCore Gateway — create, targets, tool schema, auth, invocation

Two surfaces exist in the installed stack: the **boto3 control-plane**
(`bedrock-agentcore-control`, authoritative API shape) and a thin SDK wrapper
`bedrock_agentcore.gateway.GatewayClient`. Both were read directly.

### 2.1 The boto3 control-plane API (authoritative, from the installed model)

`boto3.Session().client("bedrock-agentcore-control")` exists in boto3 1.43.114.
Introspecting the service model:

- **`CreateGateway`** input:
  `name`, `description`, `roleArn`, `protocolType` (**enum: `MCP` only**),
  `protocolConfiguration.mcp` (supportedVersions, instructions, searchType,
  sessionConfiguration, streamingConfiguration, `disableMcpListToolsPagination`),
  `authorizerType` (**enum: `CUSTOM_JWT` | `AWS_IAM` | `NONE` |
  `AUTHENTICATE_ONLY`**), `authorizerConfiguration.customJWTAuthorizer`
  (`discoveryUrl`, `allowedAudience[]`, `allowedClients[]`, `allowedScopes[]`,
  `customClaims`, optional `privateEndpoint` for VPC IdPs), `kmsKeyArn`,
  `interceptorConfigurations`, `policyEngineConfiguration`, `tags`.
- **`CreateGatewayTarget`** input: `gatewayIdentifier`, `name`, `description`,
  `targetConfiguration`, `credentialProviderConfigurations[]`,
  `metadataConfiguration`, `privateEndpoint`, `certificateConfigurations`.
  - `targetConfiguration.mcp` supports one of: `openApiSchema`, `smithyModel`,
    **`lambda`**, `mcpServer`, `apiGateway`, `connector`.
  - **`targetConfiguration.mcp.lambda = { lambdaArn, toolSchema: { s3 |
    inlinePayload: [ToolDefinition] } }`** — this is the Lambda-target path we
    need.
  - `credentialProviderConfigurations[].credentialProviderType` (**enum:
    `GATEWAY_IAM_ROLE` | `OAUTH` | `API_KEY` | `CALLER_IAM_CREDENTIALS` |
    `JWT_PASSTHROUGH`**) + nested `credentialProvider` (oauth / apiKey / iam).

### 2.2 ToolDefinition contract (how each operation is described as an MCP tool)

From the model AND the official doc
([AWS Lambda function targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html)):

```
ToolDefinition = {
  "name": string,              # required; the tool name (gets target-prefixed)
  "description": string,       # required
  "inputSchema": SchemaDefinition,   # required; top-level type MUST be "object"
  "outputSchema": SchemaDefinition   # optional
}
SchemaDefinition(object) = {
  "type": "object",
  "description": string?,
  "properties": { name: SchemaDefinition },
  "required": [string]
}
```
`SchemaDefinition.type` enum = `string | number | object | array | boolean |
integer` (nested `properties`, `items`, `required`, `description`). This is a
JSON-Schema subset. The agent-facing tool's `inputSchema.json` is this schema
verbatim (§1.2), so the model sees exactly what we declare here — meaning the
19 read + 6 write operations must each get a hand-authored `inputSchema` that
matches the args the current `@tool` functions accept (e.g.
`github_create_branch(repo_id, branch_name, from_branch="main")`).

### 2.3 Inbound auth (AgentCore Identity's role on the inbound side)

From [Set up inbound authorization](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html):
- **JWT (`CUSTOM_JWT`)** — any OIDC provider (Amazon Cognito is the documented
  default when you create via console/CLI). You supply `discoveryUrl`,
  `allowedClients`/`allowedAudience`, optional `allowedScopes`. The caller obtains
  an access token from the IdP and sends it as a bearer token to the Gateway MCP
  endpoint. Unauthorized calls get a 401/403 with an RFC-6750 `WWW-Authenticate`
  challenge advertising scopes.
- **`AWS_IAM`** — the caller's IAM credentials authorize via SigV4; the caller
  needs `bedrock-agentcore:InvokeGateway` on the gateway ARN.
- **`AUTHENTICATE_ONLY`** (SigV4, authenticate but don't authorize) and
  **`NONE`** (no inbound auth) are "offloaded" modes — authorization is delegated
  to a policy engine, an interceptor Lambda, or the downstream target. The doc
  warns strongly against `NONE` for anything non-public.
- **Implication for this demo (design D):** the agent runs under the `lava`
  admin role in-account. `AWS_IAM` inbound is the lowest-setup secure option (no
  Cognito user pool to stand up) and the agent's existing boto3/SigV4 identity
  authorizes it. `CUSTOM_JWT` + Cognito is the "production-shaped" option but
  adds a user-pool/app-client dependency. The design should choose ONE and state
  why; `AWS_IAM` is the pragmatic pick for an offline-gated, operator-deployed
  demo. `NONE` should be rejected for anything beyond a throwaway local probe.

### 2.4 How Gateway invokes a Lambda target + outbound creds

- For a **Lambda** target, the gateway invokes the function with its **own IAM
  service role** (`credentialProviderType: GATEWAY_IAM_ROLE` is the natural
  choice — this is what the SDK's built-in target helpers default to; see
  `bedrock_agentcore/gateway/client.py` `create_knowledge_base_target` /
  `create_web_search_target`, which hard-code
  `[{"credentialProviderType": "GATEWAY_IAM_ROLE"}]`). The gateway role needs
  `lambda:InvokeFunction` on the target ARN; the Lambda's resource policy must
  allow the gateway/service principal to invoke it.
- **This matters for the Lambda's in-handler `X-API-Token` check.** Today each
  Task 3 Lambda enforces a static `X-API-Token` header (`common/auth.py
  :: require_token`). A Gateway invocation carries **no HTTP headers at all**
  (§3), so there is no `X-API-Token`. The design must decide: (i) make the
  token check conditional on event source (skip it for Gateway invocations, rely
  on IAM for auth), or (ii) have the adapter synthesize the expected token. IAM
  (the gateway role) is the real auth boundary for Gateway calls, so option (i)
  is the clean path.

### 2.5 The `bedrock_agentcore.gateway.GatewayClient` convenience wrapper

`agent/.venv/.../bedrock_agentcore/gateway/client.py` wraps the control-plane
client. Allow-listed methods: `create_gateway`, `get_gateway`, `list_gateways`,
`update_gateway`, `delete_gateway`, and the `*_gateway_target` equivalents, plus
`*_and_wait` pollers and `get_gateway_by_name` / `get_gateway_target_by_name`.
It ships typed helpers only for `knowledge_base`, `agentic_retrieve`, and
`web_search` targets — **there is no `create_lambda_target` helper**, so a Lambda
target via this client means calling `create_gateway_target(...)` with a
hand-built `targetConfiguration.mcp.lambda`. (It accepts both camelCase and
snake_case kwargs.) This client is the boto3 **fallback** if CDK is not used.

---

## 3. CRITICAL — the Lambda payload gap (correctness risk, confirmed)

**Finding:** A Gateway Lambda-target invocation does NOT resemble any HTTP event
the Task 3 router understands.

From [AWS Lambda function targets › Lambda function input format](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html):
- **`event`** is a flat map of the tool's `inputSchema` properties to their
  values, e.g. `{"keywords": "wireless headphones", "category": "electronics"}`.
  There is **no** `requestContext`, no `requestContext.http.method`, no
  `rawPath`, no `httpMethod`, no `path`, no `headers`, no `body`, no
  `isBase64Encoded`.
- **Tool identity** arrives on the **context**, not the event:
  `context.client_context.custom['bedrockAgentCoreToolName']`, formatted
  `"<targetName>___<toolName>"` (the doc's boilerplate strips the prefix using a
  `"___"` delimiter). Other context fields:
  `bedrockAgentCoreMessageVersion`, `bedrockAgentCoreAwsRequestId`,
  `bedrockAgentCoreMcpMessageId`, `bedrockAgentCoreGatewayId`,
  `bedrockAgentCoreTargetId`. The doc also notes imported Lambdas "will need to
  change the function code to account for a schema change for event and context
  objects" — i.e. an HTTP-shaped handler is explicitly expected NOT to work
  as-is.

**What Task 3's router does with that event** (read from
`tools-lambdas/common/router.py :: _normalize`): it looks for
`event["requestContext"]["http"]`, else falls back to
`event.get("httpMethod","GET")` / `event.get("path") or "/"`. A Gateway event has
neither, so it resolves to **method=`GET`, path=`/`, headers=`{}`, body=`None`**.
`Router.dispatch` then finds no route matching `GET /` and returns
`error(404, "Not found")`. Auth (`require_token`) would also fail — there is no
`x-api-token` header. **Every Gateway tool call would 404.**

**Conclusion:** The Task 3 design's "Event-source tolerance (Task 4 note)" — that
the existing fallback branch keeps the handler usable under a non-Function-URL
event — is **accurate for API-Gateway/direct-invoke HTTP events but FALSE for
AgentCore Gateway Lambda-target events**, which are not HTTP-shaped at all.

**A Gateway→HTTP adapter is mandatory.** The design must add a mapping layer
that, per tool name, turns `(toolName, event-as-args)` into the router's
`(METHOD, path, path_params, query, json_body)` and bypasses/satisfies the
`X-API-Token` check. Concretely, for each of the 25 operations the adapter needs
to know the verb + path template + which args are path params vs query vs body
(this information already exists in `tools-lambdas/<svc>/routes.py` route
registrations and in the agent `@tool` endpoint strings, e.g.
`github_create_branch` → `POST /repos/{repo_id}/branches` with body
`{name, from_branch}`). Recommended shape: a small
`common/gateway_adapter.py` that reads
`context.client_context.custom['bedrockAgentCoreToolName']`, strips the `___`
prefix, looks up a per-service `{tool_name: (method, path_template, arg_mapping)}`
table, builds a synthetic normalized request (or a synthetic Function-URL-v2
event), dispatches through the existing `Router`, and returns the handler's JSON
body (unwrapped from the `{statusCode, body}` HTTP envelope, since Gateway expects
plain JSON). Each Lambda `handler.py` then branches: Gateway event (has
`context.client_context.custom['bedrockAgentCoreToolName']`) → adapter; else →
existing HTTP router path. This preserves the Function-URL demo AND adds Gateway
support without touching `routes.py` behavior.

---

## 4. IaC — native CDK L1 constructs exist (no custom resource needed)

**Decisive finding:** the installed `aws-cdk-lib 2.273.0` (infra-cdk venv) ships
STABLE L1 constructs in `aws_cdk.aws_bedrockagentcore`. Confirmed by importing
the module from `infra-cdk/.venv` and listing `Cfn*` exports, which include:
`CfnGateway`, `CfnGatewayProps`, `CfnGatewayTarget`, `CfnGatewayTargetProps`,
plus credential-provider and runtime constructs
(`CfnApiKeyCredentialProvider`, `CfnOAuth2CredentialProvider`,
`CfnWorkloadIdentity`, `CfnRuntime`, `CfnMemory`, `CfnPolicy`, …).

`CfnGatewayTarget` nested property classes confirm the Lambda-target path is
expressible in CloudFormation:
`TargetConfigurationProperty`, `McpTargetConfigurationProperty`,
**`McpLambdaTargetConfigurationProperty`**, **`ToolSchemaProperty`**,
**`ToolDefinitionProperty`**, **`SchemaDefinitionProperty`**,
`CredentialProviderConfigurationProperty`, `CredentialProviderProperty`,
`IamCredentialProviderProperty`, `S3ConfigurationProperty`.
`CfnGateway` confirms inbound-auth config:
`AuthorizerConfigurationProperty`, **`CustomJWTAuthorizerConfigurationProperty`**,
`MCPGatewayConfigurationProperty`, interceptor/policy/WAF/VPC property classes.

AWS docs corroborate stability:
[the alpha module README](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-bedrock-agentcore-alpha-readme.html)
states the constructs graduated to stable in `aws-cdk-lib/aws-bedrockagentcore`
(only the Policy submodule remains alpha), and L1 `Cfn*` constructs are always
stable. There is also an L2 alpha
(`@aws-cdk/aws-bedrock-agentcore-alpha`) with higher-level helpers if a future
task wants them, but it is NOT needed and NOT installed.

**Implication for design D (IaC approach):**
- **Primary path:** build Task 4 entirely in the existing Python CDK app under
  `infra-cdk/`, adding a new stack (e.g. `MahaloGatewayStack`) that:
  1. Creates the gateway IAM service role (trust `bedrock-agentcore`, grant
     `lambda:InvokeFunction` on the four target ARNs).
  2. `CfnGateway` with `protocolType="MCP"` and the chosen `authorizerType`
     (`AWS_IAM` recommended, §2.3).
  3. Four `CfnGatewayTarget`s, each `targetConfiguration.mcp.lambda` pointing at
     one mock Lambda ARN (imported from the existing `*Arn` CfnOutputs —
     `JiraArn` / `ConfluenceArn` / `GithubArn` / `ServiceNowArn`, confirmed in
     `mock_service_stack.py :: _OUTPUT_IDS` and `task3-verification.md`) with an
     inline `toolSchema` listing that service's operations, and
     `credentialProviderConfigurations=[{credentialProviderType:
     GATEWAY_IAM_ROLE}]`.
  4. Grant each mock Lambda's resource policy to allow the gateway role to invoke
     it.
- This keeps the "CDK for everything / survives a monthly account reset"
  constraint (docs/PLAN.md, docs/CONTINUATION.md) intact. The current
  `requirements.txt` pins `aws-cdk-lib>=2.0,<3`, which already resolves to
  2.273.0 — no new dependency needed, though pinning a floor at the version that
  has the constructs (≥2.251) is prudent.
- **Fallback path:** if a CFN property proves unsupported for our exact
  toolSchema, `bedrock_agentcore.gateway.GatewayClient` (or raw
  `bedrock-agentcore-control` boto3) can create the gateway/targets from a
  script, invoked as a CDK custom resource or a standalone
  `scripts/*.ps1`. Not expected to be necessary.
- **The offline gate** (synth/tests/import, per the task brief) is satisfiable:
  `cdk synth` over the new stack + CDK assertions that the gateway, four targets,
  the toolSchema tool names, and the IAM grants exist; `pytest` over the adapter
  (§3) with synthetic Gateway events; and `import`/`build_agent()` staying
  offline-safe with the MCP client constructed-but-not-started.

---

## Appendix — exact sources read

INSTALLED SDK source (agent/.venv):
- `strands/tools/mcp/mcp_client.py` — `MCPClient(ToolProvider)`, `load_servers`,
  `__init__` url/headers/auth, context-manager lifecycle.
- `strands/tools/mcp/mcp_agent_tool.py` — `MCPAgentTool(AgentTool)`, `tool_name`,
  `tool_spec` (inputSchema/outputSchema mapping), `stream()` → `call_tool_async`.
- `strands/tools/mcp/__init__.py` — public exports.
- `strands/tools/executors/_executor.py` — `ToolExecutor._stream` fires
  `BeforeToolCallEvent` before `tool.stream()` for all tools.
- `strands/tools/decorator.py` — local `@tool` name = `func.__name__`.
- `agent/approval.py`, `agent/strands_agent.py`, `agent/tools/github_write_tools.py`
  — current HITL hook + tool wiring + a representative write tool.
- `bedrock_agentcore/gateway/client.py` + `__init__.py` — `GatewayClient`
  control-plane wrapper and built-in target helpers (no lambda helper).

Live botocore model (agent/.venv, boto3 1.43.114):
- `bedrock-agentcore-control` `CreateGateway` / `CreateGatewayTarget` input shapes
  and enums (`protocolType`, `authorizerType`, `credentialProviderType`,
  `SchemaDefinition.type`).

Installed CDK (infra-cdk/.venv, aws-cdk-lib 2.273.0):
- `aws_cdk.aws_bedrockagentcore` module — `CfnGateway`/`CfnGatewayTarget` present;
  nested `McpLambdaTargetConfigurationProperty` / `ToolSchemaProperty` /
  `ToolDefinitionProperty` / `CustomJWTAuthorizerConfigurationProperty`.

Task 3 source read for the payload-gap analysis:
- `tools-lambdas/common/router.py` (`_normalize`, `dispatch`),
  `tools-lambdas/common/auth.py` (`require_token`),
  `infra-cdk/mahalo_infra/mock_service_stack.py` (ARN/URL outputs),
  `docs/.agents/tasks/task3-design.md`, `docs/.agents/tasks/task3-verification.md`.

Official AWS docs (paraphrased, linked inline):
- [AWS Lambda function targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html)
  — ToolDefinition schema; Lambda event = flat args map; tool name on
  `context.client_context.custom['bedrockAgentCoreToolName']`, `___` prefix.
- [Set up inbound authorization for your gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html)
  — JWT / IAM / AUTHENTICATE_ONLY / NONE inbound modes.
- [aws-bedrock-agentcore-alpha module README](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-bedrock-agentcore-alpha-readme.html)
  — constructs graduated to stable `aws-cdk-lib/aws-bedrockagentcore`.
- [CfnGatewayTarget (CDK Python)](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_bedrockagentcore/CfnGatewayTarget.html)
  — L1 target construct reference.
