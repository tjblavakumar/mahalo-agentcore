# Task 4 — Design Review (AgentCore Gateway + MCP exposure layer)

**Reviewer:** design-review subagent (fresh read, no authoring context)
**Design under review:** `docs/.agents/tasks/task4-design.md` (REVISION 3)
**Investigation:** `docs/.agents/tasks/task4-investigation.md`
**Verdict:** CHANGES_REQUESTED (1 MEDIUM, 2 NIT)

The verdict is mechanical: any HIGH or MEDIUM blocks. This revision resolves the
two prior review rounds well; the one remaining MEDIUM is a concrete
data-equivalence gap for a single write tool (`jira_update_story`) that the
design names but does not wire into any execution path. Everything else I
spot-checked against source holds.

Scope note: I only read/wrote files under
`D:/<USER>/LavaCode/AI/mahalo-agentcore`. No `mahalo-dock` access, no
git actions.

---

## Method

I re-read the design end to end, then verified its load-bearing claims against
the actual source rather than against the investigation's summaries:

- `agent/tools/http.py` (`make_request` success predicate + error string)
- `agent/approval.py` (`WRITE_TOOL_NAMES`, `build_proposal`, `_before_tool_call`)
- `agent/chat.py` (`_ask` interrupt loop, `_emit_system_signal` param keys)
- `agent/tools/{jira,github,servicenow,confluence}_tools.py` and the three
  `*_write_tools.py` (tool names, signatures, client-side orchestration)
- `tools-lambdas/{jira,github,servicenow,confluence}/routes.py` (verb/path/arg
  keys, auth, error shapes)
- `tools-lambdas/common/{router,auth,responses}.py` and one `handler.py`
- `infra-cdk/app.py` and `infra-cdk/mahalo_infra/mock_service_stack.py`
- Installed SDK: `strands/tools/executors/_executor.py` and
  `strands/tools/mcp/mcp_agent_tool.py`

---

## Findings

### 1. MEDIUM — `jira_update_story` server-side assignee resolution has no execution home (behavior-equivalence gap + internal §3.4/§5.3 conflict)

**Where:** §3.4 (last bullet), §5.3 (the `jira_update_story` row), Decision A
equivalence (§1, §11).

**Problem.** DIRECT-mode `jira_update_story` (verified in
`agent/tools/jira_write_tools.py`) performs three agent-side steps before the
PUT: (a) a pre-GET existence check, (b) `assignee` name→dev-id resolution via
`_resolve_assignee` (so `assignee="Raj"` is stored as `dev-3`), and (c) a
changed-fields-only body assembly. The Jira `update_story` route (verified in
`tools-lambdas/jira/routes.py`) stores `body["assignee"]` **verbatim with no
resolution**. The design §3.4 states "`jira_update_story`'s assignee name→dev-id
resolution also uses `common.assignee.resolve_assignee` server-side," but §5.3
classifies `jira_update_story` as a **plain (non-composite) `PUT`** whose adapter
path (per §5.2 step 4) only maps args→body and dispatches — it never calls a
resolver. The two sections conflict, and as written the GATEWAY path would store
the raw assignee name instead of the dev-id, breaking the data equivalence that
Decision A promises. (`jira_create_story` does NOT need this — its `@tool` passes
`assignee` unresolved, verified — so the gap is specific to update.)

**Concrete fix (pick one and state it):**

- Preferred: add `jira_update_story` to the composite set and give it a home,
  e.g. `tools-lambdas/jira/composites.py::update_story(store, args)` that (1)
  GETs the story (404 → error object), (2) calls
  `common.assignee.resolve_assignee` when `assignee` is present, (3) assembles
  the changed-fields-only body, (4) dispatches the `PUT`. Change the §5.3 row for
  `jira_update_story` from a plain `PUT` to `*composite* jira.composites.update_story`.
- Then extend the §8 composite-parity test to assert that for
  `assignee="Raj"` the GATEWAY path stores the same resolved `dev-id` the DIRECT
  `@tool` would send (the §8 parity test currently covers only
  `stories_by_assignee`/`search_stories` resolution and the ServiceNow
  aggregation, not update).

### 2. NIT — `jira_search_stories` keyword filter is not called out as ported logic or parity-tested

**Where:** §3.4 (Jira composites bullet), §8 (parity test).

**Problem.** DIRECT `jira_search_stories` (verified in
`agent/tools/jira_tools.py`) applies an agent-side keyword filter
(`_matches_keyword`: case-insensitive match against story title/description)
*after* fetching, in addition to assignee resolution and multi-project fan-out.
§3.4 enumerates "same name-resolution + multi-project fan-out + keyword filter"
in the problem statement but the porting bullet only pins the resolver and the
fan-out; the keyword-match semantics are left implicit, and §8's parity test
asserts dev-id resolution + the ServiceNow aggregation but not keyword matching.

**Concrete fix:** state in §3.4 that `jira.composites.search_stories` reproduces
the `query` keyword filter (case-insensitive substring over `title` and
`description`, empty/None query = match-all), and add one parity assertion in §8
that a keyword fixture returns the same story-id set from the agent helper and
the Lambda composite.

### 3. NIT — `_resolve_assignee` has a seventh branch (`if not assignee: return None`) the parity test does not enumerate

**Where:** §3.4 and §8 ("all six branches").

**Problem.** The design enumerates six branches (exact-name, first-name, email,
no-match, dev-id passthrough, ambiguous). The source `_resolve_assignee`
(verified in `agent/tools/jira_tools.py`) also has a leading
`if not assignee: return None` guard — a seventh path. It is low-risk, but the
design's own framing is "assert identical resolution across all branches," and a
`common/assignee.py::resolve_assignee(assignee, developers)` that takes the
developer list as an argument must still define what it returns for an
empty/`None` `assignee` to stay equivalent.

**Concrete fix:** add the empty/`None` assignee case to the §8 parity test
(`resolve_assignee("", devs) is None` and `resolve_assignee(None, devs) is None`),
and have `common/assignee.py` short-circuit the falsy input before touching the
developer list.

---

## Verified Assumptions

These design claims were checked against source and hold:

1. **Adapter success predicate / error string (§5.2, §5.4).**
   `agent/tools/http.py::make_request` returns the decoded JSON only on
   `response.status_code in (200, 201)`, else
   `{"error": f"Request failed with status {code}: {response.text}"}`. Verified.
2. **Error-body equivalence (§5.4).** `common/responses.py::error` returns body =
   `json.dumps({"detail": detail})`; `json_response` JSON-encodes the body. So
   `result["body"]` is exactly what `httpx` `response.text` would be for the same
   route, making the adapter's `f"...: {result['body']}"` byte-identical to
   DIRECT. Verified.
3. **GitHub arg quirks (§5.3).** `create_branch` route reads `body.get("name")`
   (tool param is `branch_name`); `list_commits` reads query `author`;
   `list_pulls`/`list_all_pulls` read query `author_id`. All three match the
   §5.3 table. Verified in `tools-lambdas/github/routes.py` +
   `agent/tools/github_tools.py` / `github_write_tools.py`.
4. **ServiceNow list-filter rows (§5.3, revision-3 Finding 1).**
   `list_deployments` reads `service`/`environment`/`status`; `list_incidents`
   reads `severity`/`status`/`service` (plus an `assignee` filter the `@tool`
   does NOT expose). The design's corrected rows and the "do not surface
   assignee" decision match source. Verified in
   `tools-lambdas/servicenow/routes.py` + `agent/tools/servicenow_tools.py`.
5. **HITL interrupt fires for MCP tools, pre-write (§4.1, inv §1.3).**
   `strands/tools/executors/_executor.py::ToolExecutor._stream` fires
   `BeforeToolCallEvent` and, if it yields interrupts, emits `ToolInterruptEvent`
   and returns **before** the `ExecuteToolStage` terminal calls
   `ctx.tool.stream(...)`. For an MCP tool, `ctx.tool.stream()` is the only place
   the server call happens (`MCPAgentTool.stream` →
   `mcp_client.call_tool_async`). So no MCP write occurs pre-approval. Verified
   in installed SDK source.
6. **Hook sees `tool_name`, server sees the original name (§4.2).**
   `MCPAgentTool.tool_name = name_override or mcp_tool.name` is what the
   model/hook see; `stream()` calls the server with `self.mcp_tool.name`.
   Verified. The `rsplit("___", 1)[-1]` strip is a no-op on a bare name, so it is
   safe whether the Gateway advertises `target___tool` or a bare name — the fix
   degrades gracefully even if the AWS-side prefix assumption is imperfect.
7. **`build_proposal` / `_before_tool_call` current shape (§4.2).**
   `agent/approval.py` does `name.partition("_")` and exact-match
   `name in WRITE_TOOL_NAMES`; `WRITE_TOOL_NAMES` is the six bare names. The
   described edits are minimal and correct. Verified.
8. **`_emit_system_signal` param dependency (§4.2 interplay).**
   `agent/chat.py::_emit_system_signal` reads `proposal["params"]` keys
   `branch_name`, `repo_id`, `branch`, `head`, `base`. Because the design keeps
   Gateway `inputSchema` property names identical to the `@tool` signatures
   (`branch_name`, not the route's `name`) and the §8 schema-parity test enforces
   exact arg-set equality, these breadcrumb keys survive in GATEWAY mode.
   Verified consistent.
9. **CfnOutputs are not CloudFormation Exports → construct reference is correct
   (§7.1, Finding 2).** `mock_service_stack.py` emits `CfnOutput`s with **no**
   `export_name`, so `Fn.import_value` could not resolve them by name; passing
   the `MockServiceStack` instances (each exposing `self.function`) into
   `MahaloGatewayStack` is the right wiring. Verified.
10. **`app.py` already builds per-service stacks (§7.1, §10).** `infra-cdk/app.py`
    instantiates a `MockServiceStack` per service in a loop; capturing the
    instances and passing them on is a local, feasible change. Verified.
11. **Handler dispatch revision (§5.1).** `tools-lambdas/github/handler.py` uses
    `store, router = _get_router(); store.ensure_seeded()` inside a
    `try/except ClientError→503 / Exception→500`. The revised Gateway branch
    (inside the try, after seeding, passing the live `store, router`) matches the
    live handler. Verified.
12. **Tool inventory (25 tools / 6 writes) and names (§3.2).** Jira 7+2, GitHub
    4+3, Confluence 3, ServiceNow 5+1 = 25; the six write names equal
    `WRITE_TOOL_NAMES`. Verified across the tool modules.
13. **Composite route availability (§3.4, §5.3).** `/developers`, `/projects`,
    `/projects/{id}/stories`, `/services`, `/deployments` all exist for the three
    composites to call in-Lambda. Verified.

---

## Unverified / Wrong Assumptions

1. **Gateway advertises tools as `target___tool` (inv §1.3/§3; design §3.2, §4,
   §5.2).** This is grounded in AWS documentation only; no gateway was created,
   so the wire-level tool name and the `bedrockAgentCoreToolName` `___` delimiter
   are **not** verified live. Impact is contained: both the HITL strip and the
   adapter strip use `rsplit("___", 1)[-1]`, which is correct for a bare name
   too, so a wrong prefix assumption does not silently bypass approval. The
   design correctly treats this as doc-sourced and does not overclaim. Not a
   blocking finding; noted for the LIVE step.

2. **SigV4-over-MCP inbound auth (design §2, §6.4, §9).** The design explicitly
   does NOT lock this: `MCPClient` is confirmed only to *accept* `auth=` /
   `auth_provider=` kwargs; that a botocore SigV4 `httpx.Auth` is accepted by an
   `AWS_IAM` Gateway authorizer for the SSO admin role, and the exact signing
   service name, are deferred to a LIVE step with a documented `CUSTOM_JWT`+
   Cognito fallback. This is the correct handling of an unverified AWS/SDK
   assumption (it resolves the prior HIGH/MEDIUM on this point) and does not
   block the offline gate. Not a finding.

3. **`CfnGateway`/`CfnGatewayTarget` L1 construct property names (inv §4; design
   §7.1).** The module's presence in `aws-cdk-lib 2.273.0` and the nested
   property-class names are asserted from the investigation's import listing; I
   did not independently re-synth the stack. The design's offline gate (`cdk
   synth` + `assertions.Template`) is the right place this gets proven; flagged
   only so the implementer confirms exact kwarg spelling
   (`protocol_type`/`authorizer_type` casing, `inline_payload` nesting) at build
   time. Not a blocking finding.

---

## Verdict rationale

HIGH = 0, MEDIUM = 1 (Finding 1), NIT = 2 (Findings 2, 3). MEDIUM count > 0, so
**CHANGES_REQUESTED**. Resolving Finding 1 (give `jira_update_story`'s
server-side assignee resolution a concrete composite home and a parity
assertion) clears the block; the two NITs are quick completeness tightenings in
the same composite/parity area.
