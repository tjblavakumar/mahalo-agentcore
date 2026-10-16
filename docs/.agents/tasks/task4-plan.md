# Task 4 — Implementation Plan (AgentCore Gateway + MCP exposure layer)

Derived from the APPROVED design `docs/.agents/tasks/task4-design.md` (revision 3)
and the investigation `docs/.agents/tasks/task4-investigation.md`. This plan
sequences that design faithfully; it does not re-decide the architecture. Every
decision below is the design's resolution of questions A–D (and the mandatory E).

**Hard rules (carried from the task brief + `docs/CONTINUATION.md`):**
- Only create/modify files UNDER `D:/lavakumar.baskaran/LavaCode/AI/mahalo-agentcore`.
  Never touch `mahalo-dock` (read-only). No git commit/push. No worktree — work
  directly in the workspace.
- Invariants: zero LangChain; `import agent.*` and `build_agent()` stay
  offline-safe (no AWS call / no network at import or construct time); DIRECT-HTTP
  mode stays the default and the test baseline; the existing agent suite stays
  green (**42 passed, 1 skipped** — the one live integration test skips when the
  tunnel is down).

**Project build/test commands (discovered during exploration):**
- Lambda/adapter tests: from `tools-lambdas/`, `python -m pytest tests -q`
  (offline; moto fakes DynamoDB via `tests/conftest.py`; asset root is on
  `sys.path` so `common` and each service import as top-level packages).
- Agent tests: from the repo root, `python -m pytest agent -q` (DIRECT mode;
  baseline 42 passed, 1 skipped).
- CDK synth: from `infra-cdk/`, `cdk synth --all` (offline, no creds).
- CDK assertion tests: from `infra-cdk/`, `python -m pytest tests -q` (uses
  `aws_cdk.assertions.Template`, pattern in `infra-cdk/tests/test_synth.py`).

All six write-tool names (the HITL set): `jira_create_story`,
`jira_update_story`, `github_create_branch`, `github_commit_files`,
`github_open_pull_request`, `servicenow_create_incident`.

The 25 operations = 19 read + 6 write, names identical to the current `@tool`
function names. Three are composites (server-side orchestration, not a 1:1 HTTP
call): `jira_search_stories`, `jira_get_stories_by_assignee`,
`servicenow_deployment_status_by_project`.

---

## Ordered implementation steps

- [ ] 1. Create the single source of truth for assignee resolution:
      `tools-lambdas/common/assignee.py` with a pure
      `resolve_assignee(assignee: str, developers: list[dict]) -> str | None`
      that reproduces ALL SIX branches of `agent/tools/jira_tools.py::_resolve_assignee`
      exactly: empty→None; `dev-` prefix passthrough (returns the lowercased value
      WITHOUT consulting `developers`); exact full-name or email match; first-name /
      partial / email-local-part match returning the single match; ambiguous
      (len(matches) != 1)→None. Stdlib only, no HTTP (takes `developers` as an arg).
      Files: `tools-lambdas/common/assignee.py`
      Verify: `cd tools-lambdas && python -m pytest tests -q` — existing suite still
      passes (no behavior added yet; the parity test arrives in step 9).

- [ ] 2. Refactor `agent/tools/jira_tools.py::_resolve_assignee` to a thin wrapper
      that fetches developers (via the existing `_fetch_developers()`) and delegates
      to `common.assignee.resolve_assignee`, keeping the SAME module-private names
      `_resolve_assignee` and `_fetch_developers` so the existing one-way import in
      `agent/tools/jira_write_tools.py` (`from agent.tools.jira_tools import
      _fetch_developers, _resolve_assignee`) keeps working. Make `tools-lambdas`
      importable from the agent via a minimal path shim inside `jira_tools.py` (add
      the repo-root `tools-lambdas` dir to `sys.path` at import time, guarded and
      offline-safe); if a clean import proves awkward, vendor the one pure function
      body and enforce equivalence via the step-9 parity test instead. No other edit
      to `agent/tools/*`.
      Files: `agent/tools/jira_tools.py`
      Verify: `python -m pytest agent -q` — still 42 passed, 1 skipped (DIRECT-mode
      behavior unchanged).

- [ ] 3. Create `tools-lambdas/common/tool_schemas.py` — the authoritative registry
      of all 25 tools. For each tool a descriptor dict `{name, description,
      inputSchema, method, path_template, arg_mapping, composite}` where `inputSchema`
      is a JSON-Schema-subset object (top-level `type: "object"`, `properties`,
      `required`) whose property names/types/required-ness EXACTLY match the current
      `@tool` signatures, and `method`/`path_template`/`arg_mapping`/`composite` feed
      the adapter (step 4). Encode the known arg quirks verbatim from design §5.3:
      `github_get_commits` → query `author` (not `author_id`); `github_get_pull_requests`
      → query `status, author_id`; `github_create_branch` body `{name: <branch_name>,
      from_branch}` (route reads `body["name"]`); `jira_update_story` PUT with
      changed-fields-only + assignee name→dev-id; `servicenow_list_deployments` →
      query `service, environment, status`; `servicenow_list_incidents` → query
      `severity, status, service` (do NOT expose `assignee`); the three composites
      flagged `composite=True` with their handler ref. Stdlib + pure data; importable
      by both `infra-cdk` and the Lambdas.
      Files: `tools-lambdas/common/tool_schemas.py`
      Verify: `cd tools-lambdas && python -c "from common.tool_schemas import TOOLS;
      assert len(TOOLS) == 25"` and `python -m pytest tests -q` stays green
      (the strict parity assertions arrive in step 8).

- [ ] 4. Create the composite handlers that reproduce the agent-only orchestration
      server-side:
      `tools-lambdas/jira/composites.py` with `search_stories(store, router, args)`
      and `stories_by_assignee(store, router, args)` — each resolves the assignee via
      `common.assignee.resolve_assignee` (using `/developers`), fans out over
      `/projects` → `/projects/{id}/stories` through the in-Lambda router, applies the
      keyword filter (search only), and returns the same JSON records DIRECT mode
      aggregates; and `tools-lambdas/servicenow/composites.py` with
      `deployment_status(store, router, args)` that joins `/services` and
      `/deployments` and produces the grouped-by-service aggregation matching
      `agent/tools/servicenow_tools.py::servicenow_deployment_status_by_project`.
      Return plain JSON dicts (not formatted strings), per design §1/§3.4.
      Files: `tools-lambdas/jira/composites.py`,
      `tools-lambdas/servicenow/composites.py`
      Verify: `cd tools-lambdas && python -m pytest tests -q` (covered end-to-end by
      the adapter + parity tests in steps 8–9; suite must stay green here).

- [ ] 5. Create `tools-lambdas/common/gateway_adapter.py` with
      `handle(tool_name, store, router, event) -> dict`: strip the Gateway `___`
      prefix (`tool_name.rsplit("___", 1)[-1]`); look up the descriptor in
      `tool_schemas.py`; if `composite` dispatch to the service composite (step 4)
      and return its JSON; else build a synthetic Function-URL-v2 event (fill
      `path_template` with path args, map remaining args to query for GET or JSON
      body for POST/PUT per `arg_mapping`, and INJECT the expected `X-API-Token`
      header value — read from the Lambda's own `MOCK_<SVC>_TOKEN` env var — so the
      frozen `require_token` check passes), call `router.dispatch`, and unwrap:
      on `statusCode in (200, 201)` return `json.loads(result["body"])`, otherwise
      return `{"error": f"Request failed with status {status}: {result['body']}"}`
      (byte-identical to `agent/tools/http.py::make_request`). Error table per design
      §5.4 (unknown tool, missing required arg, 4xx/5xx, composite raise). Never raise
      for an expected failure.
      Files: `tools-lambdas/common/gateway_adapter.py`
      Verify: `cd tools-lambdas && python -m pytest tests -q` (full coverage in step 8;
      suite stays green).

- [ ] 6. Add the Gateway-source dispatch branch to each of the four service handlers,
      INSIDE the existing `try/except ClientError→503 / Exception→500` and AFTER
      `store.ensure_seeded()`: read the tool name via
      `getattr(getattr(context, "client_context", None), "custom", None)` →
      `custom.get("bedrockAgentCoreToolName")`; if present, return
      `gateway_adapter.handle(tool_name, store, router, event)`; else fall through to
      the unchanged `router.dispatch(event)`. Pass the freshly constructed
      `store, router` (never the stale `_store` global). Same pattern across all four
      files.
      Files: `tools-lambdas/jira/handler.py`, `tools-lambdas/confluence/handler.py`,
      `tools-lambdas/github/handler.py`, `tools-lambdas/servicenow/handler.py`
      Verify: `cd tools-lambdas && python -m pytest tests -q` — existing handler tests
      (HTTP path) stay green AND the new adapter tests (step 8) pass.

- [ ] 7. Create `infra-cdk/mahalo_infra/gateway_stack.py` — `MahaloGatewayStack`
      taking the four `MockServiceStack` instances as constructor args (direct
      construct reference; no `Fn.import_value`; `mock_service_stack.py` stays frozen).
      Using `aws_cdk.aws_bedrockagentcore` L1 constructs: a Gateway IAM service role
      (trust `bedrock-agentcore.amazonaws.com`, inline `lambda:InvokeFunction` on the
      four `stack.function.function_arn`s only); one `CfnGateway`
      (`protocolType="MCP"`, `roleArn`, `authorizerType` as a CfnParameter defaulting
      to `"AWS_IAM"`, `protocolConfiguration.mcp.supportedVersions`); four
      `CfnGatewayTarget`s (`name="mock-<svc>"`, `targetConfiguration.mcp.lambda` with
      `lambdaArn` + inline `toolSchema` built from `tool_schemas.py`,
      `credentialProviderConfigurations=[{credentialProviderType:
      "GATEWAY_IAM_ROLE"}]`); a `fn.add_permission(...)` invoke grant per function;
      and CfnOutputs `GatewayId`, `GatewayArn`, `GatewayMcpUrl`. Then wire it in
      `infra-cdk/app.py`: capture the four `MockServiceStack` instances and pass them
      into `MahaloGatewayStack`. Bump `infra-cdk/requirements.txt` floor to
      `aws-cdk-lib>=2.251,<3`.
      Files: `infra-cdk/mahalo_infra/gateway_stack.py`, `infra-cdk/app.py`,
      `infra-cdk/requirements.txt`
      Verify: `cd infra-cdk && cdk synth --all` succeeds (gateway stack + four mock
      stacks synthesize with no AWS/net).

- [ ] 8. Add the Lambda-side unit tests: `tools-lambdas/tests/test_gateway_adapter.py`
      (synthetic Gateway events — flat args map + a fake
      `context.client_context.custom['bedrockAgentCoreToolName']` — for a
      representative read, write, error 404/409, and composite per service; assert the
      dispatched route, the unwrapped JSON payload equals the route body data, and the
      error string equals `make_request`'s for the same raw body) and
      `tools-lambdas/tests/test_tool_schemas.py` (all 25 names present; the six write
      names equal `WRITE_TOOL_NAMES`; every schema top-level `type == "object"`;
      EXACT bidirectional arg-set equality between each DIRECT `@tool` signature —
      read via `inspect.signature` — and its schema `properties` keys; NO name in
      `tool_schemas.py` or `WRITE_TOOL_NAMES` contains the substring `___`). Follow
      the moto/`make_event` fixtures in `tools-lambdas/tests/conftest.py`.
      Files: `tools-lambdas/tests/test_gateway_adapter.py`,
      `tools-lambdas/tests/test_tool_schemas.py`
      Verify: `cd tools-lambdas && python -m pytest tests -q` — all tests pass.

- [ ] 9. Add the composite parity test
      `tools-lambdas/tests/test_composites_parity.py`: feed one shared developer
      fixture to `common.assignee.resolve_assignee` and assert identical dev-id
      resolution across all six branches (exact-name, first-name, email-local-part,
      no-match, `dev-3` passthrough against an empty fixture, ambiguous→None); and
      assert the ServiceNow composite's grouped JSON matches the data the agent
      aggregation (`servicenow_tools.py`) produces for the same services/deployments
      fixture.
      Files: `tools-lambdas/tests/test_composites_parity.py`
      Verify: `cd tools-lambdas && python -m pytest tests -q` — all tests pass.

- [ ] 10. Wire the agent's Gateway-MCP mode (dual-mode toggle; DIRECT stays default).
      Add three `_getenv`-backed fields to `agent/config.py`: `tool_mode`
      (`MAHALO_TOOL_MODE`, default `"direct"`), `gateway_mcp_url`
      (`MAHALO_GATEWAY_MCP_URL`, default `""`), `gateway_region`
      (`MAHALO_GATEWAY_REGION`, default = `aws_region`). Create
      `agent/gateway_client.py` with `_build_gateway_mcp_client()` that constructs a
      `strands.tools.mcp.MCPClient(url=settings.gateway_mcp_url, ...)` with a pluggable
      auth-provider factory but does NOT call `start()` (construction is offline-safe).
      In `agent/strands_agent.py::build_agent`, add a `tool_mode` parameter/branch: in
      `gateway` mode build the MCP client, construct `Agent(model=..., tools=[mcp_client],
      system_prompt=..., hooks=[WriteApprovalHook()])` and return `(agent, mcp_client)`;
      DIRECT mode is unchanged (returns the bare `Agent` with the 25 local tools).
      Files: `agent/config.py`, `agent/gateway_client.py`, `agent/strands_agent.py`
      Verify: `python -c "from agent.strands_agent import build_agent;
      a, c = build_agent(tool_mode='gateway'); print(type(a), type(c))"` with NO AWS
      creds/network — imports and constructs cleanly; and `python -m pytest agent -q`
      stays 42 passed, 1 skipped.

- [ ] 11. Preserve HITL for the six writes over MCP. In `agent/approval.py` add
      `_bare_name(name) = name.rsplit("___", 1)[-1]`; use it in
      `WriteApprovalHook._before_tool_call` (`if _bare_name(event.tool_use["name"])
      not in WRITE_TOOL_NAMES: return`) and in `build_proposal` (compute
      `bare = _bare_name(tool_use["name"])` then `prefix, _, action =
      bare.partition("_")`). A bare local name has no `___`, so the strip is a no-op
      for DIRECT mode. In `agent/chat.py` wrap the GATEWAY-mode invocation in
      `with mcp_client:` (unpacking the `(agent, mcp_client)` tuple from
      `build_agent`); DIRECT mode path unchanged.
      Files: `agent/approval.py`, `agent/chat.py`
      Verify: `python -m pytest agent -q` — existing HITL tests stay green.

- [ ] 12. Add the agent-side unit tests: new prefix cases in
      `agent/tests/test_write_tools_unit.py` (`_bare_name` strips `___`; a
      `mock-github___github_create_branch` tool_use triggers `event.interrupt`; a
      non-APPROVE resume sets `event.cancel_tool`; a read tool passes through) and
      `agent/tests/test_gateway_mode.py` (`build_agent(tool_mode="gateway")` imports
      and constructs cleanly offline with no AWS/network and returns the
      `(agent, mcp_client)` tuple; the MCP client is constructed, not started).
      Files: `agent/tests/test_write_tools_unit.py`, `agent/tests/test_gateway_mode.py`
      Verify: `python -m pytest agent -q` — new tests pass; prior 42 passed / 1
      skipped baseline preserved (count grows by the new tests, still 1 skipped).

- [ ] 13. Add the CDK assertion test `infra-cdk/tests/test_gateway_stack.py`
      (pattern from `infra-cdk/tests/test_synth.py`): synth `MahaloGatewayStack`
      given the four mock stacks; assert exactly one `CfnGateway`
      (`authorizerType` default `AWS_IAM`), four targets whose `toolSchema` tool-name
      sets match the per-service expected names, the Gateway role with
      `lambda:InvokeFunction` on the four function ARNs, four invoke permissions, and
      no `Fn::ImportValue` in the template.
      Files: `infra-cdk/tests/test_gateway_stack.py`
      Verify: `cd infra-cdk && python -m pytest tests -q` — all CDK assertion tests
      pass.

- [ ] 14. Run the full OFFLINE verification gate and fix any cross-cutting seams:
      (1) `cd infra-cdk && cdk synth --all` succeeds; (2) `cd infra-cdk &&
      python -m pytest tests -q` passes; (3) `cd tools-lambdas && python -m pytest
      tests -q` passes (adapter, schema, composite-parity, plus the unchanged handler
      tests); (4) from the repo root `python -m pytest agent -q` = 42 passed, 1
      skipped (DIRECT baseline preserved) plus the new gateway/HITL tests;
      (5) `build_agent(tool_mode="gateway")` imports/constructs cleanly offline;
      (6) confirm zero LangChain anywhere (`grep -ri langchain agent tools-lambdas
      infra-cdk` returns nothing). Record the outcomes in
      `docs/.agents/tasks/task4-verification.md`.
      Files: `docs/.agents/tasks/task4-verification.md`
      Verify: all six gate conditions above hold and are recorded.

---

## DEFERRED — LIVE operator steps (NOT part of the offline gate)

These are documented for a human to run with `aws sso login --profile lava`
active; they are NOT executed by this plan and no live results are fabricated.

1. From `infra-cdk/`: `cdk deploy --all --profile lava` (CDK deploys the four mock
   stacks first, then `MahaloGatewayStack` via the construct-reference dependency).
2. Copy the `GatewayMcpUrl` CfnOutput → set `MAHALO_GATEWAY_MCP_URL` and
   `MAHALO_TOOL_MODE=gateway` in the agent environment.
3. Confirm the caller IAM principal has `bedrock-agentcore:InvokeGateway` on the
   gateway ARN.
4. Validate inbound auth (design §6.4 open item): run one GATEWAY-mode tool call
   and confirm the SigV4 `httpx.Auth` (correct signing service name) is accepted
   by the `AWS_IAM` authorizer for the SSO admin role. If not, switch
   `authorizerType` to `CUSTOM_JWT`, stand up a Cognito app-client, and use the
   bearer-token path. Record which mechanism worked.
5. Run the LIVE integration check (GATEWAY-mode end-to-end: "list my repositories"
   → payment-service; "show my stories" (dev-6) → PAY-; a `github_create_branch`
   write → interrupt fires → approve → branch created) and record outcomes in
   `docs/.agents/tasks/task4-verification.md`.

---

## Notes / assumptions

- The build loop's reviewer writes its verdict to
  `docs/.agents/tasks/task4-code-review.json` (`{"verdict": "APPROVED" |
  "CHANGES_REQUESTED", ...}`); the loop stops when `verdict == "APPROVED"`.
- `tool_schemas.py` is the ONE source of truth consumed by BOTH the CDK stack
  (for `toolSchema`) and the Lambda adapter (for `arg_mapping`), so the two can
  never drift; the step-8 schema-parity test enforces this against the live
  `@tool` signatures.
- Step order is dependency-driven: the shared modules (assignee, tool_schemas,
  composites, adapter) come before the handlers that call them (step 6), the CDK
  stack that reads `tool_schemas.py` (step 7), and the tests (steps 8–9, 12–13).
  The agent-side changes (10–11) are independent of the Lambda side and could run
  in parallel, but are sequenced after for a single coherent review.
```
