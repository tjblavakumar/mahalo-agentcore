# Task 3 — Implementation Plan: Mocks as AWS Lambdas

Derived faithfully from the APPROVED `docs/.agents/tasks/task3-design.md` and the
readiness note `docs/.agents/tasks/task3-setup.md`. The architecture is already
decided (Function URL per function, DynamoDB one-table-per-service lazily seeded,
plain `(event, context)` handlers + thin shared router, CDK Python per-service
stacks). This plan sequences the work without re-deciding it; where the design
left a small mechanical choice open, the choice is made inline and labeled.

## Ground rules (apply to every step)

- **Workspace only.** Read/modify files ONLY under
  `D:/<USER>/LavaCode/AI/mahalo-agentcore`. All Task 3 artifacts live
  under `docs/.agents/tasks/` (workspace-relative, forward-slash).
- **mahalo-dock is READ-ONLY.** Copy route logic and seed data **into**
  `tools-lambdas/`; never edit anything under
  `D:/<USER>/LavaCode/AI/mahalo-dock`. The four `seed_data.py` are
  copied **byte-for-byte** from
  `D:/<USER>/LavaCode/AI/mahalo-dock/mock-services/<svc>/seed_data.py`.
- **No git.** Do NOT `git commit` or `git push` as part of these steps. No
  worktree; work directly in the workspace.
- **Zero LangChain** anywhere (handlers, router, tests, CDK).
- **No agent changes.** Do NOT modify any file under `agent/`. The Lambdas are
  reached purely by overriding the four `*_URL` env vars post-deploy; the agent
  stays green against the original localhost mocks.
- **Scope is Task 3 only** — the Lambda reimplementation. Do NOT build the
  AgentCore Gateway/MCP wiring (that is Task 4), but preserve the design's
  Task-4-friendly choices (function ARN + URL Cfn outputs, event-source-tolerant
  handler, DynamoDB invisible to the Gateway layer).
- **Python runtime deps:** `boto3`/`botocore` are provided by the Lambda runtime,
  so Lambda assets carry **no** third-party runtime deps and **no** per-service
  `requirements.txt`. Test-only deps (`pytest`, `moto`) live in
  `tools-lambdas/requirements-dev.txt`, never packaged into any function asset.
- **Account / region / profile:** `<AWS_ACCOUNT_ID>` / `us-east-1` / profile `lava`.
- **Shell is Windows PowerShell:** chain with `;` (NOT `&&`); env vars are
  `$env:VAR`; invoke a venv exe with the call operator `&`. Toolchain confirmed:
  python 3.13.9, node v24.13.0, cdk 2.1145.0.

## Environments created by this plan

- `tools-lambdas/.venv` — venv for running the Lambda unit tests (pytest + moto).
  `.venv/` is gitignored.
- `infra-cdk/.venv` — venv for the CDK app (aws-cdk-lib 2.x + constructs) and the
  synth tests. `.venv/` and `cdk.out/` are gitignored.

Both venvs are created with `py -3.13 -m venv` / `python -m venv`. Verification
commands below name the venv python explicitly; adjust the `.venv/Scripts/`
path only if a step reports it missing.

---

# Implementation Plan

- [ ] 1. **Scaffold `tools-lambdas/` package + dev venv.**
      Create the package skeleton with empty `__init__.py` files
      (`tools-lambdas/common/__init__.py`, and one per service dir) so the four
      functions and the `common/` package import cleanly; add
      `tools-lambdas/requirements-dev.txt` pinning `pytest` and `moto` (moto with
      the `dynamodb`/`all` extra). Create `tools-lambdas/.venv` and install the
      dev deps. The lone `tools-lambdas/.gitkeep` may remain.
      Files: `tools-lambdas/common/__init__.py`, `tools-lambdas/jira/__init__.py`,
      `tools-lambdas/confluence/__init__.py`, `tools-lambdas/github/__init__.py`,
      `tools-lambdas/servicenow/__init__.py`, `tools-lambdas/tests/__init__.py`,
      `tools-lambdas/requirements-dev.txt`.
      Verify: `& tools-lambdas/.venv/Scripts/python.exe -m pip install -r tools-lambdas/requirements-dev.txt`
      succeeds; `& tools-lambdas/.venv/Scripts/python.exe -c "import pytest, moto; print('deps OK')"`
      prints `deps OK`.

- [ ] 2. **Copy the four seed files VERBATIM.**
      Copy each `seed_data.py` byte-for-byte from
      `D:/<USER>/LavaCode/AI/mahalo-dock/mock-services/<svc>/seed_data.py`
      to `tools-lambdas/<svc>/seed_data.py` for jira, confluence, github,
      servicenow. Do not reformat, re-indent, or edit — including github's
      `BRANCHES`/`CONTRIBUTOR_STATS` dicts and servicenow's `_SERVICE_CONTEXT`.
      Files: `tools-lambdas/jira/seed_data.py`,
      `tools-lambdas/confluence/seed_data.py`,
      `tools-lambdas/github/seed_data.py`,
      `tools-lambdas/servicenow/seed_data.py`.
      Verify: for each service, a byte-compare against the source is identical,
      e.g. `(Get-FileHash tools-lambdas/jira/seed_data.py).Hash -eq (Get-FileHash D:/<USER>/LavaCode/AI/mahalo-dock/mock-services/jira/seed_data.py).Hash`
      returns `True` for all four; and
      `& tools-lambdas/.venv/Scripts/python.exe -c "import importlib,sys; sys.path.insert(0,'tools-lambdas/jira'); m=importlib.import_module('seed_data'); print(len(m.DEVELOPERS),len(m.PROJECTS),len(m.SPRINTS),len(m.STORIES))"`
      imports without error.

- [ ] 3. **Build the shared `common/` runtime (router, auth, responses, store).**
      Implement the four modules as one coherent unit:
      `common/responses.py` — `json_response(status, body)` returning the Function
      URL shape `{"statusCode", "headers":{"content-type":"application/json"}, "body": json.dumps(body)}`,
      plus `error(status, detail)` → body `{"detail": detail}`.
      `common/auth.py` — `require_token(request, expected)` doing a
      case-insensitive header-KEY lookup for `x-api-token` and an EXACT value
      compare (`header_value != expected` → 401 `{"detail":"Invalid API token"}`,
      including `None`/absence; no trimming/case-folding of the value).
      `common/router.py` — a `Request` dataclass (`method, path, path_params,
      query, json_body, headers`) and a `Router` that registers
      `(METHOD, path_template)` routes with `{param}` segments and declared int
      coercion (e.g. `pr_number`; non-int → 422). It normalizes BOTH the Function
      URL v2 event (`requestContext.http.method`, `rawPath`,
      `rawQueryString`/`queryStringParameters`, base64-aware JSON `body`) AND, when
      `requestContext.http` is absent, the top-level
      `httpMethod`/`path`/`queryStringParameters` shape (API Gateway/direct-invoke
      fallback — the Task 4 event-source-tolerance hook). Unmatched route → 404
      `{"detail":"Not found"}`; malformed JSON body on POST/PUT → 400
      `{"detail":"Invalid JSON body"}`.
      `common/dynamo_store.py` — a `Store(table_name)` over boto3 DynamoDB
      (`pk`/`sk` keys) exposing: `get(pk, sk)`, `put(pk, sk, record, attr="data")`,
      `query(pk)` (all items for a collection), `count(pk)` (a `Query` with
      `Select="COUNT"`, equal to the mock's `len(...)`), `delete(pk, sk)`, and
      `batch_write(items)`. It seeds lazily: on first access check sentinel
      `pk="_meta", sk="seeded"`; if absent, deep-copy every seed collection into
      the table via batched writes, then set the sentinel with a conditional put
      (`attribute_not_exists(pk)`) so concurrent cold starts cannot double-seed.
      Store the enclosing record under a `data` attribute; github's dict-keyed
      `BRANCHSET`/`STATS` store their per-repo list under a `value` attribute.
      A `ClientError` from DynamoDB surfaces as 503 `{"detail":"Backend store
      unavailable"}` at the handler layer (step 4), so the store should let
      `ClientError` propagate rather than swallow it.
      Files: `tools-lambdas/common/responses.py`, `tools-lambdas/common/auth.py`,
      `tools-lambdas/common/router.py`, `tools-lambdas/common/dynamo_store.py`.
      Verify: step 4's router + store unit tests (written next) pass under moto:
      `& tools-lambdas/.venv/Scripts/python.exe -m pytest tools-lambdas/tests/test_common_router.py -q`
      — depends on step 4's test file, so run after step 4.

- [ ] 4. **Author the test harness + router/store unit tests.**
      Create `tools-lambdas/tests/conftest.py` with a moto `@mock_aws`
      DynamoDB-table fixture (creates a `mahalo-mock-*` table with `pk`/`sk` on
      PAY_PER_REQUEST) and a synthetic Function-URL event builder
      (`make_event(method, path, *, query=None, headers=None, body=None,
      token=...)`) plus an API-Gateway-shaped builder for the fallback branch.
      Create `tools-lambdas/tests/test_common_router.py` covering: path-param
      extraction, int coercion of `pr_number` (bad value → 422), unmatched-route
      404, malformed-body 400, the Function-URL-v2 path, and the top-level
      `httpMethod` fallback path; and lazy-seed behavior (seed-once sentinel, no
      double-seed on a second call).
      Files: `tools-lambdas/tests/conftest.py`,
      `tools-lambdas/tests/test_common_router.py`.
      Verify: `& tools-lambdas/.venv/Scripts/python.exe -m pytest tools-lambdas/tests/test_common_router.py -q`
      — all tests pass (this is also the verification for step 3).

- [ ] 5. **Port the Jira service (`handler.py` + `routes.py`) + unit tests.**
      Implement `routes.py` reproducing `mahalo-dock jira/main.py` against the
      `Store`: `/health` (200, no token); `/projects` GET/POST (POST id
      `(id|project_id|"PROJ").upper()`, 409 duplicate, defaults
      status="active"/lead="dev-1"); `/projects/{id}` GET (404 "Project not
      found"); `/projects/{id}/board` (active-sprint stories bucketed into
      todo/in_progress/in_review/done; no active sprint →
      `{"sprint":null,"columns":{}}`); `/stories` GET (filters
      status/assignee/project_id → `{"stories":[...],"total":n}`);
      `/projects/{id}/stories` GET (filters status/assignee/sprint_id);
      `/stories/{id}` GET (enrich with `assignee_details` from DEVELOPERS; 404
      "Story not found"); `POST /stories` (validate project_id+title FIRST →
      422 `{"detail":"Field '<name>' is required"}`, THEN unknown project → 404;
      new id `{project_id}-{max_existing_num+1}`, status="todo", empty
      acceptance_criteria/comments); `PUT /stories/{id}` (apply only non-null
      fields; 404); `/sprints/{project_id}` GET (project key, returns ALL its
      sprints; active sprint gets computed `completed_points`/`total_points`);
      `/developers` GET. `handler.py` exposes `lambda_handler(event, context)`
      wiring the router + `require_token` (token from `MOCK_JIRA_TOKEN`, default
      `mock-jira-token-12345`) + a top-level try/except that maps `ClientError`
      → 503 and any other exception → 500 `{"detail":"Internal error"}` (never
      leak a trace). Add `tools-lambdas/tests/test_jira_handler.py` driving
      `lambda_handler` with synthetic events: health, auth 401, every read route
      (seed-derived expectations), create-story→get-story read-after-write, the
      422-before-404 order, and PUT update.
      Files: `tools-lambdas/jira/routes.py`, `tools-lambdas/jira/handler.py`,
      `tools-lambdas/tests/test_jira_handler.py`.
      Verify: `& tools-lambdas/.venv/Scripts/python.exe -m pytest tools-lambdas/tests/test_jira_handler.py -q`
      — all tests pass.

- [ ] 6. **Port the Confluence service (`handler.py` + `routes.py`) + unit tests.**
      Reproduce `confluence/main.py`: `/health`; `POST /spaces` (id
      `(id|"SPACE").upper()`, 409, name defaults to id); `GET /spaces`;
      `GET /spaces/{id}` (404 "Space not found"); `GET /pages` (optional
      `space_id`; SUMMARY objects `id,title,author,last_updated,space_id` — no
      `content`); `GET /spaces/{id}/pages` (summary); `POST /spaces/{id}/pages`
      (404 unknown space; new id `(id or f"{space_id}-{count(PAGES)+1:03d}").upper()`
      where count is the `Query COUNT` over `pk="PAGE"`; defaults title="New
      page"/author="System"/last_updated="2026-08-29"/content=""); `GET
      /pages/{id}` (full page incl. content; 404 "Page not found"); `GET /search`
      (required `q` min-length-1 → else 422 `{"detail":"Field 'q' is required"}`,
      optional `space_id`; case-insensitive substring over title+content; ±100-char
      excerpt; relevance 1.0 title / 0.7 content; sort by relevance desc →
      `{"results":[...],"total":n,"query":q}`). `handler.py` as in step 5 with
      `MOCK_CONFLUENCE_TOKEN`. Add `test_confluence_handler.py` covering health,
      auth, list/get/search reads, summary-vs-full trimming, search
      excerpt/relevance, create-page read-after-write, and missing-`q` 422.
      Files: `tools-lambdas/confluence/routes.py`,
      `tools-lambdas/confluence/handler.py`,
      `tools-lambdas/tests/test_confluence_handler.py`.
      Verify: `& tools-lambdas/.venv/Scripts/python.exe -m pytest tools-lambdas/tests/test_confluence_handler.py -q`
      — all tests pass.

- [ ] 7. **Port the GitHub service (mock-mode only) (`handler.py` + `routes.py`)
      + unit tests.**
      Port `github/main.py` + `github/mock_backend.py` (mock mode ONLY; do NOT
      port `gitea_backend.py`/`backend_base.py` pluggability). Keep three separate
      collections and the three distinct existence checks: `pk="REPO"` (repo
      record under `data`), `pk="BRANCHSET", sk=repo_id` (branch list under
      `value`) for branch/commit/pull existence (mirrors `repo_id not in
      BRANCHES`), `pk="STATS", sk=repo_id` (contributor list under `value`) for
      `get_stats` existence (mirrors `repo_id not in CONTRIBUTOR_STATS`). All
      `sk`/`repo_id` values are the seed id `repo-N`; NO name→id resolution (the
      agent passes the name, the mock 404s — replicate verbatim). `/health`
      returns `mode = os.environ.get("GITHUB_MODE","mock")`. `POST /repos`: new id
      `str(name or "repo").lower().strip()`, 409 "Repository already exists";
      writes a `REPO` item AND a `BRANCHSET` item seeded with default
      `main` branch (`{"name":"main","protected":true,"last_commit":"2026-08-29"}`),
      and NO `STATS` item. Branches: `GET /repos/{id}/branches` (404 off
      BRANCHSET), `POST /repos/{id}/branches` (pydantic-style: missing `name` →
      422 `{"detail":"Field 'name' is required"}`; 404 repo off BRANCHSET; 409
      "Branch already exists"). Pulls: `GET /pulls`, `GET /repos/{id}/pulls`,
      `GET /repos/{id}/pulls/{pr_number}` (int coercion; 404 "Pull request not
      found"), `POST /repos/{id}/pulls` (404 repo off BRANCHSET; missing head →
      422 `{"detail":"head branch is required"}` VERBATIM; id `pr-{count(PULL)+1}`,
      number `max(existing,0)+1`). Commits: `GET /repos/{id}/commits` (sorted desc
      by date), `POST /repos/{id}/commits` (`has_files = isinstance(body.get("files"),
      list) or bool(body.get("path"))`; required `branch,message` always +
      `author_id` only when NOT has_files, else default `mahalo-bot`; missing →
      422 `{"detail":"Field '<field>' is required"}` VERBATIM; 404 repo off
      BRANCHSET then 404 "Branch not found"; author name resolved from STATS; id
      `c{count(COMMITS)+1:03d}`; date "2026-08-25"). `POST /repos/{id}/readme`
      (404 repo off BRANCHSET). `GET /repos/{id}/stats` (404 off STATS; computed
      aggregates incl. `active_branches` from BRANCHSET and `open_prs`). Add
      `test_github_handler.py` covering the Task-2 chain
      create_branch→commit→open_pull, the 409/422 "already exists" codes+`detail`
      asserted exactly, the three-collection 404 split (branch/commit/pull 404
      vs stats 404 for a freshly created repo), count-vs-max id rules, and
      health `{"mode":"mock"}`.
      Files: `tools-lambdas/github/routes.py`, `tools-lambdas/github/handler.py`,
      `tools-lambdas/tests/test_github_handler.py`.
      Verify: `& tools-lambdas/.venv/Scripts/python.exe -m pytest tools-lambdas/tests/test_github_handler.py -q`
      — all tests pass.

- [ ] 8. **Port the ServiceNow service (`handler.py` + `routes.py`) + unit tests.**
      Reproduce `servicenow/main.py`: `/health`; `GET /services`; `GET
      /deployments` (filters service/environment/status; sort desc by
      `deployed_at`); `GET /deployments/{id}` (404 "Deployment not found"); `GET
      /incidents` (filters severity/status/service(=affected_service)/assignee;
      sort desc by `opened_at`); `GET /incidents/{id}` (404 "Incident not found");
      `POST /incidents` (validate title+affected_service FIRST → 422
      `{"detail":"Field '<name>' is required"}`, THEN unknown service → 404
      `{"detail":"Unknown affected_service"}` VERBATIM; id
      `INC-{max(2000, existing max)+1}`; defaults status="open",
      `opened_at=now UTC %Y-%m-%dT%H:%M:%SZ`, resolved_at=None); `PUT
      /incidents/{id}` (apply only provided fields; set `resolved_at` on
      transition to "resolved"; 404); `GET /stats` (deployments-by-status, open
      incidents, open-by-severity computed on the fly). `handler.py` as before
      with `MOCK_SERVICENOW_TOKEN`. Add `test_servicenow_handler.py` covering
      health, auth, deployment/incident reads + sort order, create-incident→list
      read-after-write, unknown-service 404, missing-field 422-before-404 order,
      PUT resolve transition, and `/stats`.
      Files: `tools-lambdas/servicenow/routes.py`,
      `tools-lambdas/servicenow/handler.py`,
      `tools-lambdas/tests/test_servicenow_handler.py`.
      Verify: `& tools-lambdas/.venv/Scripts/python.exe -m pytest tools-lambdas/tests/test_servicenow_handler.py -q`
      — all tests pass.

- [ ] 9. **Full Lambda test-suite green.**
      Run the entire `tools-lambdas/tests/` suite together to confirm the four
      services + common runtime pass as a unit under moto, offline, with no AWS
      creds.
      Files: (none — verification only)
      Verify: `& tools-lambdas/.venv/Scripts/python.exe -m pytest tools-lambdas/tests -q`
      — all tests pass, no network calls.

- [ ] 10. **Scaffold the CDK app (`infra-cdk/`) + venv.**
      Replace `infra-cdk/.gitkeep` with a CDK v2 Python app: `cdk.json`
      (`"app": "python app.py"`), `requirements.txt` (`aws-cdk-lib>=2.0,<3`,
      `constructs>=10,<11`), `requirements-dev.txt` (`pytest`), `app.py`
      (`cdk.App()` targeting env account `<AWS_ACCOUNT_ID>`/region `us-east-1`),
      `mahalo_infra/__init__.py`, and a `README.md` with bootstrap/deploy/teardown
      + env-output notes. Create `infra-cdk/.venv` and install `requirements.txt`
      + `requirements-dev.txt`.
      Files: `infra-cdk/cdk.json`, `infra-cdk/requirements.txt`,
      `infra-cdk/requirements-dev.txt`, `infra-cdk/app.py`,
      `infra-cdk/mahalo_infra/__init__.py`, `infra-cdk/README.md`.
      Verify: `cd infra-cdk; & .venv/Scripts/python.exe -m pip install -r requirements.txt -r requirements-dev.txt`
      succeeds; `& .venv/Scripts/python.exe -c "import aws_cdk, constructs; print('cdk OK')"`
      prints `cdk OK`.

- [ ] 11. **Implement the reusable `MockServiceStack` + wire the four stacks.**
      In `infra-cdk/mahalo_infra/mock_service_stack.py` implement a `Stack` (or
      construct) parameterized by service name/token-default that creates, per
      service: (1) a DynamoDB table `mahalo-mock-<svc>` with `pk` (S) partition +
      `sk` (S) sort, `BillingMode.PAY_PER_REQUEST`, `RemovalPolicy.DESTROY`; (2) a
      `lambda.Function` `runtime=PYTHON_3_13`,
      `handler="<svc>.handler.lambda_handler"`, `code=Code.from_asset("../tools-lambdas",
      exclude=[the other three service dirs, "tests", ".venv", "**/__pycache__",
      "requirements-dev.txt"])`, `memory=256`, `timeout=30s`, env `TABLE_NAME` +
      `MOCK_<SVC>_TOKEN` (default matching the agent); (3)
      `table.grant_read_write_data(fn)`; (4) `fn.add_function_url(auth_type=NONE)`.
      Emit CfnOutputs for each service's Function URL (`JiraUrl`, …) AND function
      ARN (`JiraArn`, …) for Task 4. `app.py` instantiates all four stacks.
      Files: `infra-cdk/mahalo_infra/mock_service_stack.py`, `infra-cdk/app.py`.
      Verify: `cd infra-cdk; & .venv/Scripts/python.exe -m aws_cdk ...` is not
      used — run `cdk synth --all` with the venv on PATH:
      `cd infra-cdk; .\.venv\Scripts\Activate.ps1; cdk synth --all` produces four
      templates with no error (synth needs no AWS creds).

- [ ] 12. **CDK synth assertion tests.**
      Add `infra-cdk/tests/__init__.py` and `infra-cdk/tests/test_synth.py` using
      `aws_cdk.assertions.Template` to assert, per stack: one
      `AWS::DynamoDB::Table` (PAY_PER_REQUEST, pk/sk), one `AWS::Lambda::Function`
      (`Runtime: python3.13`, handler `<svc>.handler.lambda_handler`, `TABLE_NAME`
      env present), one `AWS::Lambda::Url` (`AuthType: NONE`), and an IAM policy
      scoped to that one table (least privilege — the policy resource references
      only this stack's table).
      Files: `infra-cdk/tests/__init__.py`, `infra-cdk/tests/test_synth.py`.
      Verify: `cd infra-cdk; & .venv/Scripts/python.exe -m pytest tests -q`
      — all synth assertion tests pass.

- [ ] 13. **Reset maintenance script.**
      Add `scripts/reset-mock-tables.ps1` (uses `--profile lava`) that, for each
      of the four `mahalo-mock-*` tables by EXACT name, deletes the `_meta/seeded`
      sentinel and the collection items so the next call re-seeds. It targets
      ONLY the four named tables (no wildcard scans / no table drops) — a
      high-blast-radius operation guarded to exact names, never reachable by the
      agent.
      Files: `scripts/reset-mock-tables.ps1`.
      Verify: `powershell -NoProfile -Command "Get-Command -Syntax ./scripts/reset-mock-tables.ps1"`
      parses with no syntax error (the script is NOT executed against live AWS in
      this step; execution is an operator action documented in the CDK README).

- [ ] 14. **Full-suite + synth regression gate (integration seams).**
      Run both test suites and a fresh synth together to confirm nothing broke
      across the Lambda + CDK boundary; confirm no file under `agent/` or
      `mahalo-dock/` was modified and no LangChain import was introduced anywhere
      under `tools-lambdas/`/`infra-cdk/`.
      Files: (none — verification only)
      Verify: `& tools-lambdas/.venv/Scripts/python.exe -m pytest tools-lambdas/tests -q`
      passes; `cd infra-cdk; & .venv/Scripts/python.exe -m pytest tests -q`
      passes and `cdk synth --all` (venv active) succeeds; `git status` shows no
      changes under `agent/`; a grep for `langchain`/`langgraph` under
      `tools-lambdas` and `infra-cdk` returns nothing.

---

## Verification summary (project's real commands)

- Lambda unit tests (offline, moto):
  `& tools-lambdas/.venv/Scripts/python.exe -m pytest tools-lambdas/tests -q`
- CDK synth: `cd infra-cdk; .\.venv\Scripts\Activate.ps1; cdk synth --all`
- CDK assertion tests:
  `cd infra-cdk; & .venv/Scripts/python.exe -m pytest tests -q`
- Live integration (opt-in, operator-run after `cdk deploy --all --profile lava`):
  hit each Function URL with the real `X-API-Token` and assert read-after-write;
  skips if the `*_URL` env vars are unset. Not run as part of these steps.

## Assumptions / gaps noted

- The step prompt did not pin a `tools-lambdas` venv path; this plan creates
  `tools-lambdas/.venv` (mirroring the existing `agent/.venv` convention) and
  `infra-cdk/.venv`. Both are gitignored.
- moto's DynamoDB fake is the unit-test backend; the live Function-URL/DynamoDB
  path is validated only by the opt-in integration check after a real deploy,
  exactly as the design specifies.
- `cdk bootstrap --profile lava` is a one-time per-account/region step (re-run
  after a monthly account reset); it is an operator action documented in the CDK
  README, not a step executed here.
