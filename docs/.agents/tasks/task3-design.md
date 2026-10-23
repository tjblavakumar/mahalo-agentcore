# Task 3 â€” Technical Design: Mocks as AWS Lambdas

## Overview

Task 3 reimplements the four mahalo-dock mock systems (Jira, Confluence, GitHub,
ServiceNow) as AWS Lambda functions that are **behavior-equivalent** to the local
mocks the agent already talks to over the SSH tunnel (ports 5001â€“5004). The
agent's `agent/tools/*` modules call these services with a fixed HTTP contract
â€” specific verbs, paths, bodies, status codes, and a static `X-API-Token` header
â€” that must be preserved exactly so the existing agent package stays green with
nothing more than four environment-variable changes (`JIRA_URL`, `CONFLUENCE_URL`,
`GITHUB_URL`, `SERVICENOW_URL`).

Scope is strictly the Lambda reimplementation: four deployable, testable
functions plus the CDK (Python) that provisions them and their HTTP exposure and
state store. The AgentCore Gateway/MCP wiring is **Task 4** and is explicitly out
of scope here, but every decision below is made so it will not block Task 4
(noted inline as "Task 4 note").

This design assumes the reader has `docs/CONTINUATION.md`, `docs/ARCHITECTURE.md`,
and `docs/PLAN.md` context. All paths are workspace-relative forward-slash paths
under the `mahalo-agentcore` workspace root.

## Technology stack (locked once approved)

- **Runtime:** AWS Lambda, Python 3.13 (matches the confirmed toolchain in
  `docs/.agents/tasks/task3-setup.md` and the agent package; Lambda supports the
  `python3.13` managed runtime).
- **Handler framework:** plain Python `dict`-in/`dict`-out Lambda handlers with a
  small shared router â€” **no FastAPI, no Mangum** (justification in Decision 3).
- **HTTP exposure:** one **Lambda Function URL per function**, `AuthType=NONE`,
  with the mock's own `X-API-Token` check enforced inside the handler
  (justification in Decision 1).
- **State:** one **Amazon DynamoDB table per service**, on-demand billing, each
  lazily seeded from verbatim-copied seed data on first use
  (justification in Decision 2).
- **IaC:** AWS CDK v2 in **Python** under `infra-cdk/`, its own venv, one app with
  per-service stacks (justification in Decision 4).
- **Account / region / auth:** account `<AWS_ACCOUNT_ID>`, region `us-east-1`, SSO
  profile `lava`.
- **Zero LangChain** anywhere (project-wide constraint; nothing here introduces it).

## Code layout

Reuse the existing `tools-lambdas/` skeleton (currently just `tools-lambdas/.gitkeep`)
rather than inventing a new `mock-lambdas/`. The name already matches
`docs/ARCHITECTURE.md` ("Tool Lambdas") and the setup note, and these functions
are exactly the tool backends the Gateway will expose in Task 4, so a rename
would only churn docs. Layout:

```
tools-lambdas/
  common/
    __init__.py
    router.py          # tiny path/verb router + Function URL event (de)serialization
    auth.py            # X-API-Token enforcement
    responses.py       # JSON response + error helpers (status, body)
    dynamo_store.py    # DynamoDB-backed collection store (load/save/seed)
  jira/
    handler.py         # lambda_handler(event, context) -> Function URL response
    routes.py          # ported route logic from mahalo-dock jira/main.py
    seed_data.py       # VERBATIM copy of mahalo-dock mock-services/jira/seed_data.py
                       # (no per-service requirements.txt: no runtime deps, asset zipped as-is)
  confluence/
    handler.py
    routes.py
    seed_data.py       # VERBATIM copy of mahalo-dock confluence/seed_data.py
  github/
    handler.py
    routes.py          # ported from github main.py + mock_backend.py (mock mode only)
    seed_data.py       # VERBATIM copy of mahalo-dock github/seed_data.py
  servicenow/
    handler.py
    routes.py
    seed_data.py       # VERBATIM copy of mahalo-dock servicenow/seed_data.py
  tests/
    test_jira_handler.py
    test_confluence_handler.py
    test_github_handler.py
    test_servicenow_handler.py
    test_common_router.py
    conftest.py        # moto-based DynamoDB fixture + synthetic-event builders
```

The `common/` package is shared by all four functions; CDK bundles `common/` plus
the per-service directory into each function's asset (see Decision 4 for bundling).

### Verbatim seed data

The four `seed_data.py` files are copied **byte-for-byte** from
`<FALLBACK_ROOT>/mock-services/<svc>/seed_data.py`
into `tools-lambdas/<svc>/seed_data.py` (read-only source; never edited in
mahalo-dock). They define the module-level collections:

- jira: `DEVELOPERS`, `PROJECTS`, `SPRINTS`, `STORIES`
- confluence: `SPACES`, `PAGES`
- github: `REPOS`, `BRANCHES`, `PULL_REQUESTS`, `COMMITS`, `CONTRIBUTOR_STATS`
- servicenow: `SERVICES`, `DEPLOYMENTS`, `INCIDENTS`

These are the canonical fixtures; the DynamoDB seeding path (Decision 2) deep-copies
them into the table on first use, exactly as mahalo-dock's `store.load()` seeds
`data.json` from `seed_data.py` on first run.

## Decision 1 â€” Lambda HTTP shape: **Lambda Function URL per function**

**Options considered.** (a) Lambda Function URL, (b) API Gateway (HTTP or REST
API), (c) Application Load Balancer.

**Decision: a Function URL per function, `AuthType=NONE`.**

**Why.** The agent tools call simple, fixed REST-ish paths (`/projects`,
`/stories/{id}`, `/repos/{id}/pulls`, `/search?q=...`, etc.) against a base URL
read from env. A Function URL gives each function a stable HTTPS base URL
(`https://<url-id>.lambda-url.us-east-1.on.aws/`) and forwards the **entire path
and query string** to the handler untouched, so the router can match the exact
paths/verbs the mocks use without per-route gateway configuration. API Gateway
would force us to declare every route (or a `{proxy+}` catch-all) and adds a
second auth/throttle layer and cost for no behavioral gain in a demo; ALB needs a
VPC, target groups, and a listener, which is far heavier than four demo mocks
warrant. `AuthType=NONE` is deliberate: the mocks' real auth is the static
`X-API-Token` header, which the agent already sends and which we enforce in the
handler (Decision: auth below), so layering IAM auth on the Function URL would
break the agent's existing header-only contract.

**Base-URL shape and env wiring.** Each function gets its own Function URL. The
CDK stack **outputs** the four URLs (CloudFormation outputs `JiraUrl`,
`ConfluenceUrl`, `GithubUrl`, `ServiceNowUrl`). To point the agent at the
Lambdas, set:

```
JIRA_URL=https://<jira-url-id>.lambda-url.us-east-1.on.aws
CONFLUENCE_URL=https://<conf-url-id>.lambda-url.us-east-1.on.aws
GITHUB_URL=https://<gh-url-id>.lambda-url.us-east-1.on.aws
SERVICENOW_URL=https://<snow-url-id>.lambda-url.us-east-1.on.aws
```

`agent/config.py` already reads each of these from the environment with a
localhost default, and `agent/tools/http.py` builds requests as
`f"{base_url}{endpoint}"` with `endpoint` like `/stories` â€” so the Lambda base
URL must carry **no trailing slash** (the Function URL base has none by default;
document this in the deploy note). No agent code changes are required; this is
purely an env swap, which keeps the "agent stays green against the original
localhost mocks" constraint intact (the defaults are unchanged).

**Trailing-slash / path edge case.** A Function URL request to the bare origin
arrives with `rawPath = "/"`. The agent never calls the bare root (its lowest
path is `/projects`, `/repos`, etc.), but the router still maps unknown paths to a
404 JSON body, matching how an unmatched FastAPI route would behave for the
agent's error contract (any non-200/201 becomes an `{"error": ...}` dict in
`make_request`).

**Create routes return 201, not 200.** `make_request` treats both 200 and 201 as
success, so a create that returned 200 would still satisfy the agent â€” but it would
break the handler unit tests, which assert the mock's exact status. Every create
route in the inventory lists 201 (the mock sets `status_code=201` on each POST
create), and the inventory's success column is authoritative: creates emit 201,
reads/updates emit 200.

**Task 4 note.** AgentCore Gateway can target a Lambda **directly by ARN**
(Gateway invokes the function, it does not need an HTTP endpoint). The Function
URL is therefore purely for Task 3 testing and the env-swap demo; it does not
constrain Task 4. Because the handler is a normal `(event, context)` Lambda, Task
4 can either (i) keep the Function URL and register it, or (ii) register the
function ARN and have Gateway synthesize the invocation event. To keep option (ii)
open, the handler must **not** assume Function-URL-only event fields (see the
router's event-normalization note in Decision 3).

## Decision 2 â€” State model: **DynamoDB, one table per service, lazily seeded**

**The demand.** The Task 2 HITL write flow must still visibly work: create a story
in Jira, then read it back and see it; create a branch then commit then open a PR
on GitHub; create an incident in ServiceNow and list it. Lambdas are ephemeral and
concurrent, so in-process mutation of module globals (what mahalo-dock does) is not
durable â€” a write served by one execution environment is invisible to the next
cold start or a concurrent environment. Re-seed-per-invocation would make every
write silently vanish on the following request, breaking the demo's core
read-after-write.

**Decision: Amazon DynamoDB, one on-demand table per service, seeded lazily on
first use.** This preserves read-after-write across cold starts and concurrency
with minimal operational weight, and it survives the monthly account reset because
the table is defined in CDK (re-created empty, then re-seeded on first call) â€” the
`docs/PLAN.md` durability requirement. Options rejected: **re-seed-per-invocation**
(breaks the demo's read-after-write, as above); **a single shared table** (mixes
heterogeneous schemas and complicates seeding/teardown per service); **S3-as-JSON**
(no conditional writes, racy under concurrency, clumsy for per-item reads);
**EFS-mounted `data.json`** (needs a VPC and file-locking, heavier than warranted);
**provisioned-capacity DynamoDB** (unnecessary cost for demo traffic).

**Table shape (identical pattern for all four).** Single-table-per-service with a
simple partition key `pk` and sort key `sk`:

- `pk` = collection name (e.g. `STORY`, `PROJECT`, `SPRINT`, `DEVELOPER` for jira;
  `REPO`, `BRANCHSET`, `PULL`, `COMMIT`, `STATS` for github; etc.).
- `sk` = the item's natural id (e.g. story id `PAY-105`, project id `PAY`,
  developer id `dev-1`; github repo id `repo-1`; a fixed sentinel like
  `#` for singletons). For github's `BRANCHES` and `CONTRIBUTOR_STATS` (which are
  dicts keyed by repo id in mahalo-dock), `sk` = repo id and the item stores the
  per-repo list/record under a `value` attribute, reproducing the dict exactly.

  **GitHub `sk` is the seed repo *id* (`repo-N`), never the `name`.** The seed
  `REPOS` carry `id="repo-1".."repo-5"` with a **separate** `name` field
  (`payment-service`, `cart-service`, â€¦); `BRANCHES`/`CONTRIBUTOR_STATS` are dicts
  keyed by `repo-N` and `PULL_REQUESTS`/`COMMITS` carry `repo_id="repo-N"`. The
  mock does **strict identity matches** (`get_repo` â†’ `r["id"]==repo_id`;
  branch/commit/pull â†’ `repo_id not in BRANCHES`; `get_stats` â†’ `repo_id not in
  CONTRIBUTOR_STATS`) with **no nameâ†’id resolution anywhere**. So every GitHub
  `REPO`/`BRANCHSET`/`STATS` `sk` and every stored `repo_id` is the seed value
  `repo-N`, and the port MUST NOT add nameâ†’id resolution â€” the mock's
  identity-match behavior (including the 404 a name-based lookup produces, since
  the agent passes the repo *name* as `repo_id`) is replicated VERBATIM. This
  pre-existing agent-passes-name vs mock-keys-by-id mismatch is a mahalo-dock
  behavior that Task 3 reproduces as-is; it is never "fixed". (A freshly
  `create_repo`'d repo is keyed by `str(name).lower().strip()` â€” see the
  id-normalization block â€” so new and seed repos use different id conventions
  exactly as the mock does.)
- A `data` attribute holds the full stored record dict (the same JSON the mock
  persists). For **plain reads** the handler reads the item and returns `data`
  directly. For the routes the mock **enriches or trims at request time** (listed
  per service in the inventory â€” jira `/stories/{id}` adds `assignee_details`; jira
  `/sprints/{id}` adds `completed_points`/`total_points` for the active sprint; jira
  `/projects/{id}/board` buckets stories into columns; confluence `/pages` and
  `/spaces/{id}/pages` return summary objects without `content`; confluence
  `/search` builds excerpt + relevance; github `/repos/{id}/stats` and servicenow
  `/stats` compute aggregates), the handler applies that **same transform on top of
  the stored record** before returning. Either way the response shape is identical
  to mahalo-dock because the port runs the mock's own compute/trim logic against the
  stored `data`.

**GitHub dict-keyed collections and per-collection existence checks (preserve the
split).** In the mock, `BRANCHES` and `CONTRIBUTOR_STATS` are **dicts keyed by
repo_id**, and three different 404 checks read three different collections:

- branch/commit/pull routes 404 with `"Repository not found"` when
  `repo_id not in BRANCHES` â€” i.e. keyed off the branch collection, **not** the
  `REPO` list.
- `get_stats` 404s with `"Repository not found"` when
  `repo_id not in CONTRIBUTOR_STATS` â€” keyed off the stats collection.
- `get_repo` / `list_repos` read the `REPO` list directly.

The port must keep these as **three separate collections** and preserve which one
each existence check reads:

- `pk="BRANCHSET", sk=repo_id`, `value` = the repo's branch list â€” presence of this
  item is the "repo exists for branch/commit/pull purposes" check (mirrors
  `repo_id not in BRANCHES`).
- `pk="STATS", sk=repo_id`, `value` = the repo's contributor-stats list â€” presence
  is the `get_stats` existence check (mirrors `repo_id not in CONTRIBUTOR_STATS`).
- `pk="REPO", sk=repo_id`, `data` = the repo record.

**`create_repo` must write two items**, mirroring the mock's
`REPOS.append(...)` **and** `BRANCHES.setdefault(repo_id, [{main...}])`: a
`pk="REPO"` item **and** a `pk="BRANCHSET", sk=repo_id` item seeded with the default
`main` branch (`{"name":"main","protected":true,"last_commit":"2026-08-29"}`). It
does **not** create a `STATS` item (the mock's `setdefault` only seeds branches), so
a freshly created repo correctly 404s on `get_stats` (no seeded contributor stats)
while succeeding on branch/commit/pull â€” exactly as the mock behaves. Do not collapse
these three checks into a single "does the REPO item exist" lookup; that would 404
the github createâ†’commitâ†’PR chain (the Task 2 demo) differently from the mock.

Table naming: `mahalo-mock-jira`, `mahalo-mock-confluence`, `mahalo-mock-github`,
`mahalo-mock-servicenow`. Table name is passed to the handler via a
`TABLE_NAME` environment variable set by CDK.

**Lazy seeding.** `common/dynamo_store.py` exposes a `Store` that, on first access
for a given table, checks a sentinel item (`pk="_meta", sk="seeded"`). If absent,
it writes every record from the service's `seed_data.py` collections (deep-copied)
in a batched write, then sets the sentinel using a **conditional put**
(`attribute_not_exists(pk)`) so concurrent cold starts cannot double-seed. This
mirrors mahalo-dock's "seed on first run" semantics. A `MOCK_RESET_ON_START`-style
reset is **not** auto-run per invocation (that would be destructive under traffic);
instead reset is an explicit operation â€” see "Reset" below.

**Concurrency semantics the user should expect.** DynamoDB is the single source of
truth, so a created story/branch/PR/incident is visible to the very next read
regardless of which execution environment serves it. There is no "warm container
only" caveat (that caveat only applies if warm-state were chosen, which it is not).
ID generation that in mahalo-dock relied on scanning the in-memory collection (next
story number, next incident number, next PR number, next commit/PR id) is reproduced
by reading the relevant collection from DynamoDB and applying **the same per-field
rule the mock uses** â€” max-based for jira story / servicenow incident / PR `number`,
and count-based (`Query` `Count`) for github commit id / PR id / confluence page
fallback id (see the ID-generation invariant for the exact per-field list). This is
correct for demo-scale single-user traffic. Documented limitation: two **truly
simultaneous** creates of the same collection could in theory compute the same next
id; for the single-user demo this is acceptable and matches mahalo-dock's own
non-atomic numbering. (If Task 4+ ever needs atomicity, a DynamoDB atomic counter
item can replace the max-scan without changing the response shape â€” noted, not
built here.)

**Reset.** A small maintenance path re-seeds a table to pristine state: delete the
`_meta/seeded` sentinel and the collection items, then re-run lazy seeding on next
call. Exposed as a CDK-independent script `scripts/reset-mock-tables.ps1` (uses the
`lava` profile) rather than an HTTP route, so it is never reachable by the agent and
cannot be triggered accidentally. (High-blast-radius operation; the script targets
only the four `mahalo-mock-*` tables by exact name.)

**Task 4 note.** DynamoDB is invisible to the Gateway/MCP layer; it only changes
what the handler reads/writes. Each function needs an IAM policy granting
`dynamodb:GetItem/PutItem/Query/BatchWriteItem/DeleteItem` on its own table only
(least privilege), which CDK grants via `table.grant_read_write_data(fn)`.

## Decision 3 â€” Packaging: **one Lambda per service (4 functions), plain handler**

**Options considered.** (a) four functions, one per service; (b) one multiplexed
function routing on a `service` field or host.

**Decision: four functions, one per service.** Each service already has its own
auth token, its own state collections, and will be exposed as a distinct MCP tool
group in Task 4; four functions give independent deploy/rollback, independent IAM
(each touches only its own DynamoDB table), independent Function URLs that map
cleanly to the four `*_URL` env vars, and simpler per-service tests. A single
multiplexed function would blur least-privilege (one role touching all four tables),
complicate the env-to-URL mapping the agent expects, and couple unrelated deploys â€”
with no upside at demo scale.

**Framework: plain `(event, context)` handlers with a tiny shared router â€” not
FastAPI/Mangum.** The mock route logic is small and mechanical (match verb+path,
check token, read/write a collection, return JSON). Porting it to a ~60-line router
removes the FastAPI + Starlette + Mangum + pydantic dependency chain from every
Lambda package, which shrinks cold starts and the deployment asset and eliminates
ASGI-adapter edge cases. FastAPI's value (validation, OpenAPI, DI) is unused by this
contract â€” the agent sends known bodies and only cares about status code and JSON
shape. The port is low-risk because the behavior to preserve is explicit and fully
enumerated in the endpoint inventory below.

**Router design (`common/router.py`).** Parses a Lambda Function URL v2 event
(`event["requestContext"]["http"]["method"]`, `event["rawPath"]`,
`event["rawQueryString"]` / `event["queryStringParameters"]`, and a
base64-aware JSON `event["body"]`). It normalizes these into a small `Request`
object (`method`, `path`, `path_params`, `query`, `json_body`, `headers`) **before**
any route runs, so the route functions are framework-agnostic and directly unit
testable with synthetic dicts. Routes are registered as `(METHOD, path_template)`
where `path_template` supports `{param}` segments (e.g. `/repos/{repo_id}/pulls/{pr_number}`);
the router extracts path params and coerces declared int params (e.g. `pr_number`).
Response helpers in `common/responses.py` return the Function-URL response shape
`{"statusCode": int, "headers": {"content-type": "application/json"}, "body": json.dumps(...)}`.

**Event-source tolerance (Task 4 note).** The router first looks for the Function
URL v2 shape; if `requestContext.http` is absent it falls back to top-level
`httpMethod`/`path`/`queryStringParameters` (API Gateway/direct-invoke style). This
one branch keeps the handler usable if Task 4 registers the function by ARN and
Gateway synthesizes a non-Function-URL event, so the packaging choice does not
block Task 4.

**Per-service `requirements.txt` â€” not needed.** `boto3`/`botocore` are provided by
the Lambda Python runtime, so the functions need **no third-party runtime
dependencies**. The CDK packaging uses plain `lambda.Function` + `Code.from_asset`,
which zips the asset **as-is with no pip step** (it is not the
`aws-lambda-python-alpha` `PythonFunction` bundler, which would pip-install from a
`requirements.txt`). Therefore **no per-service `requirements.txt` is created** â€” its
presence or absence is irrelevant to the bundler. Test-only deps (`pytest`, `moto`)
live in `tools-lambdas/requirements-dev.txt`, which is never packaged into any
function asset. This is the lightest option that preserves behavior.

## Decision 4 â€” IaC: **AWS CDK (Python), one app, per-service stacks, own venv**

**Decision.** A single CDK app under `infra-cdk/` (replacing the lone
`infra-cdk/.gitkeep`) with its own Python virtualenv (`infra-cdk/.venv`, kept out of
git) and `infra-cdk/requirements.txt` pinning `aws-cdk-lib` (2.x) and `constructs`.
The app is parameterized to account `<AWS_ACCOUNT_ID>` / region `us-east-1`; deploys run
with `--profile lava`.

**Layout.**

```
infra-cdk/
  app.py                     # cdk.App(); instantiates the four stacks
  cdk.json                   # "app": "python app.py"
  requirements.txt           # aws-cdk-lib==2.x, constructs
  requirements-dev.txt       # pytest, optional cdk assertions
  README.md                  # bootstrap + deploy + teardown + env-output notes
  mahalo_infra/
    __init__.py
    mock_service_stack.py    # reusable construct/stack: 1 DynamoDB table + 1 Lambda + 1 Function URL
  tests/
    test_synth.py            # cdk assertions: table, function, url, least-priv policy exist
```

**Stack design.** One reusable `MockServiceStack` (or a construct instantiated four
times) each creating, for a service:

1. A DynamoDB table `mahalo-mock-<svc>` â€” `pk` (S) partition, `sk` (S) sort,
   `BillingMode.PAY_PER_REQUEST`, `RemovalPolicy.DESTROY` (demo; clean teardown for
   the monthly reset).
2. A `lambda.Function` â€” `runtime=PYTHON_3_13`, `handler="<svc>.handler.lambda_handler"`,
   code bundled from `tools-lambdas/` including `common/` and the one service dir
   (exclude the other services and tests via the asset `exclude` list so each
   package stays minimal), `memory=256MB`, `timeout=30s`, env `TABLE_NAME` +
   `MOCK_<SVC>_TOKEN` (default token value matching the agent, overridable).
3. `table.grant_read_write_data(fn)` â€” least-privilege IAM, this table only.
4. A Function URL (`fn.add_function_url(auth_type=NONE)`), exported as a
   Cfn output so the four `*_URL` env values are discoverable post-deploy.

Deploying four separate stacks (one per service) lets a single service be updated or
rolled back independently and keeps each stack's teardown isolated. `app.py` wires all
four; `cdk deploy --all --profile lava` provisions everything and prints the four URLs.

**Bootstrap / reset survival.** CDK bootstrap (`cdk bootstrap --profile lava`) is a
one-time per-account/region step re-run after a monthly account reset; the stacks then
`cdk deploy` cleanly from scratch, tables start empty and self-seed on first call. This
satisfies `docs/PLAN.md`'s "must survive a monthly account reset" and feeds Task 8's
re-deployable/teardown hardening.

**Task 4 note.** The stack outputs both the Function URL and the function ARN (add a
`fn.function_arn` output) so Task 4's Gateway stack can import the ARNs without this
stack changing.

## Per-service endpoint inventory

Every route below is derived from the mahalo-dock `main.py` (and github
`mock_backend.py`) and cross-checked against the agent tool modules in
`agent/tools/`. Verb, path, body, success status, and error statuses must match
exactly. The agent's `make_request` treats **only 200/201** as success; any other
status becomes `{"error": "Request failed with status {code}: {text}"}`, so error
status codes and the presence of a JSON `detail` matter for the agent's error
strings. Unless noted, the response body is the same JSON object/shape the mock
returns.

Legend: **Auth** = all non-health routes require `X-API-Token` (401 on mismatch).

### Jira (`tools-lambdas/jira`), token `mock-jira-token-12345`

| Verb | Path | Body / query | Success | Errors | Agent tool(s) |
|---|---|---|---|---|---|
| GET | `/health` | â€” | 200 | â€” | (none) |
| GET | `/projects` | â€” | 200 `{"projects":[...]}` | 401 | `jira_list_projects`, `jira_search_stories` |
| POST | `/projects` | dict `{id/name/description/status/lead}` | 201 (new project) | 401, 409 already exists | (not used by agent; preserve) |
| GET | `/projects/{project_id}` | â€” | 200 | 401, 404 | (preserve) |
| GET | `/projects/{project_id}/board` | â€” | 200 `{"sprint":...,"columns":{...}}` | 401 | `jira_get_board` |
| GET | `/stories` | query `status,assignee,project_id` | 200 `{"stories":[...],"total":n}` | 401 | (preserve) |
| GET | `/projects/{project_id}/stories` | query `status,assignee,sprint_id` | 200 `{"stories":[...],"total":n}` | 401 | `jira_get_stories_by_assignee`, `jira_search_stories` |
| GET | `/stories/{story_id}` | â€” | 200 (story + `assignee_details`) | 401, 404 | `jira_get_story`, `jira_update_story` (pre-GET) |
| POST | `/stories` | `{project_id*,title*,description,priority,story_points,assignee,sprint_id}` | 201 (new story, id `PROJ-N`, status `todo`) | 401, **422 missing `project_id`/`title`**, 404 project | `jira_create_story` |
| PUT | `/stories/{story_id}` | `{status?,assignee?,priority?,sprint_id?,story_points?}` | 200 (updated story) | 401, 404 | `jira_update_story` |
| GET | `/sprints/{project_id}` | â€” | 200 `{"sprints":[...]}` (active sprint gets `completed_points`/`total_points`); **`{project_id}` is a project key (e.g. `PAY`), not a sprint id â€” returns all sprints for that project** | 401 | `jira_get_sprint_info` |
| GET | `/developers` | â€” | 200 `{"developers":[...]}` | 401 | `jira_list_developers`, assignee resolution |

Behavioral details to preserve: new story id = `{project_id}-{max_existing_num+1}`
(**max-based** across that project's stories, matching the mock â€” contrast with
github's count-based commit/PR ids);
new story defaults `status="todo"`, empty `acceptance_criteria`/`comments`; PUT only
applies provided (non-null) fields; `/stories/{id}` enriches with `assignee_details`
from `DEVELOPERS`; sprint velocity fields computed on the fly for active sprints.

### Confluence (`tools-lambdas/confluence`), token `mock-confluence-token-12345`

Read-only from the agent's side (no `confluence_write_tools.py` exists), but the
mock also exposes space/page creation, which we preserve for completeness.

| Verb | Path | Body / query | Success | Errors | Agent tool(s) |
|---|---|---|---|---|---|
| GET | `/health` | â€” | 200 | â€” | (none) |
| POST | `/spaces` | dict `{id,name,description}` | 201 | 401, 409 already exists | (preserve) |
| GET | `/spaces` | â€” | 200 `{"spaces":[...]}` | 401 | `confluence_list_spaces` |
| GET | `/spaces/{space_id}` | â€” | 200 | 401, 404 | (preserve) |
| GET | `/pages` | query `space_id` | 200 `{"pages":[...],"total":n}` (summary fields only) | 401 | (preserve) |
| GET | `/spaces/{space_id}/pages` | â€” | 200 `{"pages":[...],"total":n}` (summary) | 401 | (preserve) |
| POST | `/spaces/{space_id}/pages` | dict `{id?,title,author,last_updated,content}` | 201 (new page) | 401, 404 space | (preserve) |
| GET | `/pages/{page_id}` | â€” | 200 (full page incl. `content`) | 401, 404 | `confluence_get_page` |
| GET | `/search` | query `q*` (min len 1), `space_id?` | 200 `{"results":[...],"total":n,"query":q}` | 401, 422 missing `q` | `confluence_search` |

Behavioral details: `/pages` and `/spaces/{id}/pages` return **summary** objects
(`id,title,author,last_updated,space_id`) without `content`; `/search` does a
case-insensitive substring match over title+content, builds a Â±100-char excerpt,
assigns `relevance` 1.0 (title hit) or 0.7 (content hit), and sorts by relevance.
The `q` min-length-1 requirement maps to a 422 when absent/empty (matches FastAPI's
query validation; the agent always sends a non-empty `q`).

**ID derivation and uppercasing on creates (preserve exactly).** The mock
normalizes created-entity ids, which the port must reproduce byte-for-byte:

- confluence `create_page`: new page id =
  `(supplied id or f"{space_id}-{count(PAGES)+1:03d}").upper()` â€” note both the
  **count-based** fallback (`len(PAGES)` in the mock, a `Query` `Count` over
  `pk="PAGE"` items in the port) **and** the `.upper()` applied to the final id
  (supplied or generated). Defaults: `title="New page"`, `author="System"`,
  `last_updated="2026-08-29"`, `content=""`.
- confluence `create_space`: new space id = `(supplied id or "SPACE").upper()`;
  `name` defaults to the id, `description` to `""`.
- jira `create_project` (listed under Jira): new project id =
  `(supplied id or supplied project_id or "PROJ").upper()`; `name` defaults to the
  id, `status="active"`, `lead="dev-1"`.
- github `create_repo`: new repo id =
  `str(body.get("name") or "repo").lower().strip()` â€” **lower-cased and stripped**,
  the deliberate contrast with jira/confluence's `.upper()`. The 409 duplicate
  check (`any(r["id"]==repo_id)` â†’ `{"detail":"Repository already exists"}`)
  compares this normalized id against existing `REPO` sks, and both the `REPO` sk
  and the `BRANCHSET` sk use this same normalized id. The `BRANCHSET` item is
  seeded with the default `main` branch
  (`[{"name":"main","protected":true,"last_commit":"2026-08-29"}]`); no `STATS`
  item is created (mirrors `setdefault` seeding only branches).

These id-normalization rules (count-based fallback + `.upper()`, github's
`.lower().strip()`) are collected here
in one place so the port does not silently store a differently-cased or
differently-numbered id and break created-entity response-shape equivalence and the
handler tests.

### GitHub (`tools-lambdas/github`), token `mock-github-token-12345`

Port the **mock backend** behavior only (`GITHUB_MODE=mock` path from
`mock_backend.py`). The Gitea-backed real mode and the `backend_base`/`gitea_backend`
pluggability are **not** ported in Task 3 (see "GitHub real-mode" below).

| Verb | Path | Body / query | Success | Errors | Agent tool(s) |
|---|---|---|---|---|---|
| GET | `/health` | â€” | 200 (`mode` = `GITHUB_MODE` env, default `"mock"`) | â€” | (none) |
| POST | `/repos` | dict `{name,description,language,default_branch}` | 201 | 401, 409 already exists | (preserve) |
| GET | `/repos` | â€” | 200 `{"repos":[...]}` | 401 | `github_list_repos` |
| GET | `/repos/{repo_id}` | â€” | 200 | 401, 404 | (preserve) |
| GET | `/repos/{repo_id}/branches` | â€” | 200 `{"branches":[...]}` | 401, 404 | (preserve) |
| POST | `/repos/{repo_id}/branches` | `{name*,from_branch="main"}` | 201 (new branch) | 401, 404 repo, **409 already exists**, **422 missing name** | `github_create_branch` |
| GET | `/pulls` | query `status,author_id,repo_id` | 200 `{"pull_requests":[...],"total":n}` | 401 | (preserve) |
| GET | `/repos/{repo_id}/pulls` | query `status,author_id` | 200 `{"pull_requests":[...],"total":n}` | 401 | `github_get_pull_requests` |
| GET | `/repos/{repo_id}/pulls/{pr_number}` | `pr_number` int | 200 | 401, 404 | (preserve) |
| POST | `/repos/{repo_id}/pulls` | dict `{head/branch*,base/target_branch,title,body,author_id,...}` | 201 (new PR) | 401, 404 repo, **422 missing head** | `github_open_pull_request` |
| GET | `/repos/{repo_id}/commits` | query `branch,author` | 200 `{"commits":[...],"total":n}` (sorted desc by date) | 401 | `github_get_commits` |
| POST | `/repos/{repo_id}/commits` | `{branch*,message*,author_id?,files?/additions/deletions}` | 201 (new commit) | 401, 404 repo/branch, **422 missing required field** | `github_commit_files` |
| POST | `/repos/{repo_id}/readme` | dict `{title,content}` | 201 | 401, 404 repo | (preserve) |
| GET | `/repos/{repo_id}/stats` | â€” | 200 (contributors + totals) | 401, 404 | `github_get_repo_stats` |

**Critical behavior â€” "already exists" = success at the agent layer.** The mock
returns **409** for a duplicate branch and **422** for a missing head / missing
commit field. The Lambda must return those exact codes. The agent's
`github_create_branch` write tool inspects the resulting error string for
`"status 409"`, `"status 422"`, or `"already exists"` and treats it as **success**
(re-using the branch so the branchâ†’commitâ†’PR chain proceeds). So the handler keeps
the native 409/422 + `detail` message; the "success" interpretation lives in the
agent and must not be changed. The `detail` strings must stay equal to the mock's
("Branch already exists", "head branch is required", "Field '{x}' is required",
"Repository not found", "Branch not found") because the agent substring-matches
on them.

Commit behavior to preserve from `mock_backend.create_commit`: two accepted body
shapes selected by the **exact mock predicate**
`has_files = isinstance(body.get("files"), list) or bool(body.get("path"))`. When
`has_files` is **true** the required fields are `branch,message` and `author_id` is
optional (defaulting to `mahalo-bot`); when **false** (legacy metadata shape)
`author_id` is also required (422 if missing/empty). Note an **empty** `files: []`
list still counts as the file-contents shape (`isinstance([], list)` is `True`, so
the agent's normalized empty-files commit does not suddenly require `author_id`), and
the `or bool(body.get("path"))` fallback also selects the file-contents shape even
with no `files` key â€” the agent never sends a bare `path`, but the port must honor it
for behavior-equivalence and the handler tests. Then: validate required fields â†’ 422;
verify branch exists â†’ 404;
resolve `author` name from `CONTRIBUTOR_STATS`; date fixed `2026-08-25`. Defaults for
new PRs mirror `mock_backend.create_pull`. `create_repo` seeds a default `main`
branch set for new repos (see Decision 2 for how this maps to the `BRANCHSET` item).

**ID generation â€” count-based vs max-based (preserve each field's exact rule).**
The mock mixes two rules within a single create; follow them per field:

- **New commit id** = `f"c{count(COMMITS)+1:03d}"` â€” derived from the **collection
  count** (`len(COMMITS)` in the mock), not a max. In the DynamoDB port,
  `count(COMMITS)` is a `Query` `Count` over the `pk="COMMIT"` items (equal to the
  mock's `len(COMMITS)`).
- **New PR id** = `f"pr-{count(PULL)+1}"` â€” also **count-based** (`len(PULL_REQUESTS)`
  in the mock); use the `Query` `Count` over `pk="PULL"` items.
- **New PR `number`** = `max(existing pr['number'], default 0) + 1` â€” this field is
  **max-based**, unlike the PR id.

This split matters: for a seed collection whose ids are not contiguous
`c001..cNNN`, a max-based id would diverge from the mock's count-based id string and
break response-shape equivalence (and the handler tests). The inventory is
authoritative; do not "simplify" either count-based id into a max. (See the
corrected ID-generation invariant below.)

### ServiceNow (`tools-lambdas/servicenow`), token `mock-servicenow-token-12345`

| Verb | Path | Body / query | Success | Errors | Agent tool(s) |
|---|---|---|---|---|---|
| GET | `/health` | â€” | 200 | â€” | (none) |
| GET | `/services` | â€” | 200 `{"services":[...]}` | 401 | `servicenow_deployment_status_by_project` |
| GET | `/deployments` | query `service,environment,status` | 200 `{"deployments":[...],"total":n}` (sorted desc by `deployed_at`) | 401 | `servicenow_list_deployments`, `..._status_by_project` |
| GET | `/deployments/{deployment_id}` | â€” | 200 | 401, 404 | (preserve) |
| GET | `/incidents` | query `severity,status,service,assignee` | 200 `{"incidents":[...],"total":n}` (sorted desc by `opened_at`) | 401 | `servicenow_list_incidents` |
| GET | `/incidents/{incident_id}` | â€” | 200 | 401, 404 | `servicenow_get_incident` |
| POST | `/incidents` | `{title*,affected_service*,severity="P3",description,assignee,linked_deployment}` | 201 (new incident) | 401, **422 missing `title`/`affected_service`**, 404 unknown service | `servicenow_create_incident` |
| PUT | `/incidents/{incident_id}` | `{status?,severity?,assignee?}` | 200 (updated) | 401, 404 | (preserve) |
| GET | `/stats` | â€” | 200 (portfolio summary) | 401 | `servicenow_get_stats` |

Behavioral details: create validates `affected_service` against `SERVICES`
(unknown `affected_service` â†’ 404 `{"detail":"Unknown affected_service"}`
(verbatim) â€” note this is not a "... not found" form); new id
`INC-{max(2000, existing max)+1}`; defaults `status="open"`,
`opened_at=now UTC` (`%Y-%m-%dT%H:%M:%SZ`), `resolved_at=None`; PUT sets
`resolved_at` when status transitions to `resolved`. `/stats` computes
deployments-by-status, open incidents, and open-by-severity on the fly.

### GitHub real-mode (Task 4+ note, not built here)

mahalo-dock's github service ships a pluggable backend (`GITHUB_MODE=mock|real`)
where `real` targets self-hosted Gitea (`gitea_backend.py`). Task 3 ports **mock
mode only** â€” it is the offline-friendly, behavior-equivalent default the agent has
always used, and it needs no network egress or Gitea. The ported `routes.py` keeps
the same request/response contract, so a later task can add a `real` backend
(reading `GITHUB_MODE`/`GITEA_URL` env) without changing the handler's HTTP surface.
This is recorded so Task 4/7 (Gitea hosting) is not blocked. The `/health` body
keeps a `"mode"` field computed as `os.environ.get("GITHUB_MODE", "mock")`, exactly
as the mock does. CDK deliberately **does not set** `GITHUB_MODE` on the github
function, so it defaults to `"mock"` and the health body reads `{"mode":"mock"}` in
Task 3 â€” while the env var remains the live switch the Task 4/7 `real`-mode hook
needs, so there is no contradiction between the hardcoded output and the hook.

## Auth enforcement (per handler)

Every non-`/health` route enforces the static token, exactly as the mocks do.
`common/auth.py` exposes `require_token(request, expected)` that reads the
`X-API-Token` header (case-insensitive key lookup â€” Function URL event headers are
lower-cased) and, on mismatch or absence, returns a 401 with body
`{"detail": "Invalid API token"}`. The value comparison is **exact** â€” the handler
401s when `header_value != expected`, matching the mock's `x_api_token !=
API_TOKEN` (no trimming or case-folding of the value, and `None`/absence mismatches
too); **only the header *key* lookup is case-insensitive** (Function URL event
headers are lower-cased). Each service's `routes.py` calls it at the top of
every protected route; `expected` comes from the `MOCK_<SVC>_TOKEN` env var (default
`mock-<svc>-token-12345`, matching the agent's defaults and
`agent/config.py`). `/health` skips the check (matches the mocks). This preserves the
agent's existing header contract unchanged.

## Error handling (concrete, per failure mode)

The handler's contract is deliberately simple because the agent only distinguishes
200/201 from "everything else", and for a few cases substring-matches the `detail`.

- **Invalid/missing token** â†’ 401, body `{"detail":"Invalid API token"}`. Recoverable
  (caller sends the right token). Logged at WARN (no token value logged).
- **Not found** (unknown story/page/repo/branch/incident/deployment/project/space)
  â†’ 404, body `{"detail":"<mock's exact message>"}`. Recoverable. Logged at INFO.
- **Already exists** (duplicate project/space/repo/branch) â†’ 409, exact mock
  `detail`. Recoverable; for github branches the agent treats it as success. Logged
  at INFO.
- **Validation failure** â†’ 422, with a **per-route `detail`** (pinned below in
  "Input validation â†’ 422 `detail` shape"; the github routes keep the mock's exact
  wording, the pydantic-generated ones use the simplified shape). Recoverable.
  Logged at INFO. Bad `pr_number` (not int) â†’ 422.
- **Route not matched** â†’ 404 `{"detail":"Not found"}`. Recoverable. Logged at INFO.
- **Malformed JSON body** on a POST/PUT â†’ 400 `{"detail":"Invalid JSON body"}`.
  Recoverable. Logged at WARN. (The agent always sends valid JSON, so this is
  defensive; it must not 500.)
- **DynamoDB failure** (throttle, transient AWS error, `ClientError`) â†’ the handler
  catches it, logs at ERROR with the exception type (not secrets), and returns 503
  `{"detail":"Backend store unavailable"}`. Fatal for that request but recoverable on
  retry; the agent surfaces it as a generic error string. This is the only
  server-side (5xx) condition.
- **Unexpected handler exception** â†’ top-level `try/except` in `lambda_handler`
  returns 500 `{"detail":"Internal error"}` and logs the traceback at ERROR. Must
  never leak a stack trace in the response body.

All logging uses the Lambda runtime logger (CloudWatch Logs). No request body
containing a token is logged verbatim; the token header is redacted to a boolean
"present/absent" in logs.

## Input validation (per external input)

External input is the HTTP request (path, query, body). Rules:

- **`X-API-Token` header** â€” required on all non-health routes; type string; must
  equal the service token; else 401. (Decision: auth above.)
- **Path params** â€” `{project_id}`, `{story_id}`, `{repo_id}`, `{space_id}`,
  `{page_id}`, `{incident_id}`, `{deployment_id}`: required by route matching, type
  string, used as lookup keys; a miss yields 404 (not 500). `{pr_number}`: required,
  coerced to int; non-int â†’ 422.
- **Query params** â€” all optional filters (`status`, `assignee`, `project_id`,
  `sprint_id`, `service`, `environment`, `severity`, `author_id`, `branch`,
  `author`, `space_id`); type string; unknown values simply match nothing (empty
  list), matching the mocks. Confluence `/search` `q`: required, min length 1, else
  422.
- **JSON bodies** â€” POST/PUT bodies validated field-by-field in `routes.py`
  reproducing the mock/pydantic behavior:
  - jira `POST /stories`: `project_id`, `title` required (missing/empty â†’ **422**);
    `description/priority/story_points/assignee/sprint_id` optional with the mock's
    defaults; unknown project â†’ **404**.
  - jira `PUT /stories/{id}`: all fields optional; only non-null fields applied.
  - github `POST /repos/{id}/branches`: `name` required; `from_branch` default
    `main`. Missing/empty `name` â†’ **422**. This route binds the pydantic model
    `CreateBranchRequest(name, from_branch="main")` in the mock, so the 422 is
    **pydantic-sourced** (raised before the backend runs, like the jira/servicenow
    pydantic 422s); the port therefore uses the same simplified body
    `{"detail":"Field 'name' is required"}` as the other pydantic-generated 422s.
  - github `POST /repos/{id}/commits`: shape chosen by
    `has_files = isinstance(body.get("files"), list) or bool(body.get("path"))`.
    `branch`,`message` required always; `author_id` required **only** when
    `has_files` is false (legacy shape) and defaults to `mahalo-bot` when true;
    missing/empty required field â†’ 422 `{"detail":"Field '<field>' is required"}`.
    An empty `files: []` is still the file-contents shape.
  - github `POST /repos/{id}/pulls`: `head` (or `branch`) required â†’ 422 if absent.
  - servicenow `POST /incidents`: `title`,`affected_service` required
    (missing/empty â†’ **422**); `severity` default `P3`; unknown service â†’ **404**.
  - servicenow `PUT /incidents/{id}`: all optional.

  **Validation order (the mock's pydantic layer runs before the handler body).**
  In the mock, pydantic rejects a missing required field with **422 before** the
  route body executes, so the 422 always precedes the handler's existence checks.
  The port must preserve that order: for `POST /stories` and `POST /incidents`,
  **validate required body fields first** (missing/empty â†’ 422), **then** run the
  existence check (jira unknown project â†’ 404; servicenow unknown
  `affected_service` â†’ 404). Getting the order wrong would surface a 404 where the
  mock surfaces a 422.

  **422 `detail` shape â€” pinned per route (the handler unit tests assert each
  exactly).** The 422 `detail` is **not** uniform across routes: the github routes
  preserve the mock's verbatim wording (because the review's own cross-check shows
  those are the literal strings `mock_backend.py` raises), while the routes whose
  422 was generated by FastAPI/pydantic in the mock (jira/servicenow/confluence) get
  a port-owned simplified string (safe because the agent never parses a 422 body â€”
  it only sees `"status 422"` in the error text, which for github branch creation it
  treats as success). We deliberately do **not** reproduce FastAPI's nested
  `{"detail":[{"loc":...,"msg":...}]}` list. Per route:

  - github `POST /repos/{repo_id}/pulls` missing head â†’ **`{"detail":"head branch
    is required"}`** (verbatim from `mock_backend.create_pull`).
  - github `POST /repos/{repo_id}/commits` missing required field â†’ **`{"detail":
    "Field '<field>' is required"}`** naming the offending field (verbatim from
    `mock_backend.create_commit`, which raises `f"Field '{field}' is required"`).
  - jira `POST /stories` missing `project_id`/`title`, servicenow `POST /incidents`
    missing `title`/`affected_service`, confluence `/search` missing `q`, github
    `POST /repos/{id}/branches` missing `name` â†’
    port-owned simplified **`{"detail":"Field '<name>' is required"}`** naming the
    first missing field (no mock-exact string to preserve â€” these were
    pydantic-generated 422s the port deliberately replaces). Note github branch
    create is pydantic-sourced (model `CreateBranchRequest`), unlike github
    commit/pull create, whose 422s are raised inside `mock_backend` and keep the
    verbatim strings above.

  These are the authoritative per-route 422 bodies; the handler unit tests assert
  the exact `detail` string for each. Note the github missing-head case is
  `"head branch is required"`, **not** `"Field 'head' is required"` â€” do not
  normalize it into the generic shape.

  Field ownership: because there is no pydantic layer, `routes.py` **owns** body
  validation and must produce the same status (and, for the cases above, the
  documented `detail`) the mock produced, since the agent's error strings and the
  409/422-as-success logic depend on the status codes.

## Invariants and ownership

- **Response-shape equivalence** (the core invariant): the JSON the agent receives
  must match mahalo-dock field-for-field. **Owned by** the ported `routes.py` plus
  the `data`-attribute storage in DynamoDB. For plain reads the handler returns the
  stored record directly; for the enriched/trimmed routes listed in Decision 2 and
  the per-service inventory (e.g. jira `assignee_details`/sprint velocity/board
  columns, confluence page-summary trimming and search excerpt/relevance, github and
  servicenow `/stats` aggregates) `routes.py` applies the mock's own compute/trim
  transform on top of the stored record â€” so response-shape equivalence covers both
  the raw-record reads and the computed-field routes. Enforced by the handler unit
  tests that assert full response bodies against expectations derived from
  `seed_data.py`. Chosen here because the agent's
  human-readable output formatting reads specific keys (e.g. `story['story_points']`,
  `pr['number']`, `data['assignee_details']`) â€” a missing/renamed key breaks the
  agent silently.
- **Auth invariant** (no protected route serves data without a valid token).
  **Owned by** `common/auth.require_token`, called at the top of every protected
  route; tested per service. Centralized so one implementation can't drift per
  service.
- **ID generation** (per-field rules, **not** a single "compute the max"). **Owned
  by** `routes.py` create paths, computed from a DynamoDB read of the relevant
  collection. The mock uses **two different rules**, and the port must match each
  field exactly:
  - **max-based:** jira story id `{project_id}-{max(existing project nums)+1}`;
    servicenow incident id `INC-{max(2000, existing max)+1}`; github PR `number`
    `max(existing number, default 0)+1`.
  - **count-based (collection length, not max):** github commit id
    `c{count(COMMITS)+1:03d}`; github PR id `pr-{count(PULL)+1}`; confluence page
    fallback id `{space_id}-{count(PAGES)+1:03d}` (before `.upper()`). In the
    DynamoDB port, `count(...)` is a `Query` `Count` over the collection's `pk`
    (equal to the mock's `len(...)`), read as the full count â€” **not** a max of
    numeric suffixes.

  Kept at the route layer because the numbering rules are service-specific. The
  count-vs-max distinction is intentional parity with mahalo-dock: the two rules
  coincide only for a contiguously-numbered append-only store, so following a
  blanket "max" rule would diverge the id strings the agent formats and the handler
  tests assert.
- **Seed-once** (a table is seeded exactly once until an explicit reset). **Owned by**
  `common/dynamo_store` via the conditional-put sentinel, so concurrent cold starts
  can't double-seed.

## Testability

- **Unit tests (primary), per `tools-lambdas/tests/`.** Invoke each
  `lambda_handler(event, context)` with **synthetic Function URL events** built by a
  `conftest.py` helper (method, path, query, headers, JSON body) and assert the
  returned `statusCode` and the decoded `body` against expectations computed from the
  copied `seed_data.py`. DynamoDB is faked with **moto** (`@mock_aws`), so tests run
  offline with no AWS creds â€” matching how the agent suite mocks its HTTP seam and
  keeping CI hermetic. Coverage per service: health (200, no token), auth (401 on
  missing/wrong token), every read route (seed-derived expectations), every write
  route (create â†’ read-back shows the new record; the Task 2 flows: jira create
  storyâ†’get story; github create branchâ†’commitâ†’open PR with the 409/422 "already
  exists" path asserted to return those exact codes+`detail`; servicenow create
  incidentâ†’list). Router unit tests cover path-param extraction, int coercion,
  unmatched-route 404, malformed-body 400, and the event-source fallback branch.
- **Integration tests (secondary, opt-in).** After `cdk deploy`, a script hits each
  live Function URL with the real token and asserts the same read-after-write
  behavior end-to-end (gated like the agent's live test â€” skips if the URLs/env are
  unset). This validates the Function URL event shape and DynamoDB wiring that moto
  can only approximate.
- **CDK synth tests.** `infra-cdk/tests/test_synth.py` uses CDK assertions to verify
  each stack synthesizes a DynamoDB table, a `python3.13` function with the right
  handler and `TABLE_NAME` env, a Function URL, and an IAM policy scoped to that one
  table (least privilege).

The design is unit-testable without AWS because the route logic is pure-ish
(request in, store calls out) and the store is swappable for moto; this is the main
reason the plain-handler + thin-router + per-service-table shape was chosen over
FastAPI/Mangum and a shared table.

## Constraints honored

- **Zero LangChain** â€” none introduced anywhere (handlers, router, CDK).
- **Agent stays green against the ORIGINAL localhost mocks** â€” no file under
  `agent/` is modified; the Lambdas are reached purely by overriding the `*_URL` env
  vars, whose defaults remain the localhost tunnel ports. The HTTP contract
  (verbs/paths/bodies/status/`detail`) is preserved so `agent/tools/http.py`'s
  200/201 success rule and the github 409/422-as-success logic keep working.
- **mahalo-dock is read-only** â€” seed data and route logic are copied **into**
  `tools-lambdas/`; nothing in mahalo-dock is edited.
- **Monthly account reset survivable** â€” everything is CDK-defined; tables re-create
  empty and self-seed.
- **Does not block Task 4** â€” four discrete functions with stable ARNs + Function
  URLs, event-source-tolerant handlers, DynamoDB invisible to the Gateway layer, and
  ARN/URL Cfn outputs for the Gateway stack to import.

## Open items deferred (not blocking Task 3)

- GitHub `real`/Gitea backend mode (Task 4/7 concern) â€” contract-compatible hook left
  in place; not implemented.
- Atomic ID counters (only if future concurrent multi-user load appears) â€” current
  max-scan matches mahalo-dock and suffices for the single-user demo.
- Gateway/MCP registration of the functions â€” **Task 4**.

## Responses to iteration-4 review

Review: `docs/.agents/tasks/task3-design-review.md` /
`docs/.agents/tasks/task3-design-review.json` (verdict `CHANGES_REQUESTED`: one
HIGH, two MEDIUM, three NITs). Each finding was re-verified against the mahalo-dock
mock sources (`github/seed_data.py`, `github/mock_backend.py`, `github/main.py`,
`servicenow/main.py`, `jira/main.py`) before editing. All six are **addressed**.

1. **[HIGH] GitHub collections keyed by repo *id* (`repo-N`), not the repo *name*.**
   Addressed. The one literal `payment-service` GitHub `sk` example in Decision 2's
   "Table shape" bullet is replaced with `repo-1` (the real seed id), and a new
   paragraph states that GitHub `sk` is the seed repo id (`repo-N`) â€” not the
   `name` â€” that the mock's `REPOS`/`BRANCHES`/`CONTRIBUTOR_STATS`/`repo_id` all key
   off, that lookups are strict identity matches with no nameâ†’id resolution, and
   that the port MUST NOT add nameâ†’id resolution so the mock's behavior (including
   the 404 produced by the agent's name-based lookups) is replicated VERBATIM. The
   pre-existing agent-passes-name vs mock-keys-by-id mismatch is called out as
   replicated as-is, never "fixed". Verified: seed `REPOS` carry
   `id="repo-1".."repo-5"` with a separate `name`; `BRANCHES`/`CONTRIBUTOR_STATS`
   keyed `repo-N`; `get_repo`/`list_branches`/`create_commit`/`create_pull`/
   `get_stats` all identity-match on `repo_id`.

2. **[MEDIUM] GitHub `create_repo` id normalization unspecified.** Addressed. The
   id-normalization block now includes github `create_repo` new id =
   `str(body.get("name") or "repo").lower().strip()` (lower+strip, contrasted with
   jira/confluence `.upper()`), states the 409 duplicate check and the
   `REPO`/`BRANCHSET` sk use this normalized id, and that the `BRANCHSET` item is
   seeded with the default `main` branch (no `STATS` item). Verified against
   `mock_backend.create_repo`.

3. **[MEDIUM] GitHub `POST /repos/{id}/branches` missing-name 422 uncovered.**
   Addressed. The branch-create inventory row now lists `422 missing name`; the
   input-validation bullet states missing/empty `name` â†’ 422 (pydantic-sourced via
   `CreateBranchRequest`) using the same simplified body
   `{"detail":"Field 'name' is required"}` as the other pydantic 422s; and the
   pinned per-route 422 `detail` list now includes this route among the
   pydantic-sourced simplified-shape routes. Verified: `github/main.py` binds
   `CreateBranchRequest(name, from_branch="main")`.

4. **[NIT] ServiceNow unknown-service 404 detail not pinned.** Addressed. The
   ServiceNow behavioral-details line now pins unknown `affected_service` â†’ 404
   `{"detail":"Unknown affected_service"}` (verbatim), noting it is not a
   "... not found" form. Verified against `servicenow/main.py` `create_incident`.

5. **[NIT] Auth value-comparison exactness.** Addressed. The Auth section now
   states the value comparison is exact (`header_value != expected` â†’ 401, matching
   `x_api_token != API_TOKEN`, including `None`/absence) and that only the header
   *key* lookup is case-insensitive. Verified: all four mocks use
   `x_api_token != API_TOKEN`.

6. **[NIT] Jira `/sprints/{project_id}` param is a project key.** Addressed. The
   Jira inventory row now annotates that `{project_id}` is a project key (e.g.
   `PAY`), not a sprint id, and returns all sprints for that project. Verified:
   `@app.get("/sprints/{project_id}")` â†’ `list_sprints` filters
   `s["project_id"]==project_id` and returns `{"sprints":[...]}`.

## Responses to design review (iteration 3)

Review: `docs/.agents/tasks/task3-design-review.md` /
`docs/.agents/tasks/task3-design-review.json` (verdict `CHANGES_REQUESTED`: one
MEDIUM + two NITs). Each finding was re-verified against `mock_backend.py` before
editing. All three are **addressed**.

1. **[MEDIUM] GitHub PR missing-`head` 422 `detail` specified two conflicting ways.**
   Addressed. The "Input validation â†’ 422 `detail` shape" subsection is rewritten to
   pin the `detail` **per route** instead of declaring one uniform shape: github
   `POST .../pulls` missing head â†’ `{"detail":"head branch is required"}` (verbatim);
   github `POST .../commits` missing field â†’ `{"detail":"Field '<field>' is
   required"}` (verbatim); jira/servicenow/confluence missing field â†’ the port-owned
   simplified `{"detail":"Field '<name>' is required"}`. The Error-handling bullet now
   points at this per-route list rather than restating a single shape, so the two
   sections no longer disagree. Verified: `create_pull` raises
   `BackendError(422, "head branch is required")`; `create_commit` raises
   `f"Field '{field}' is required"`.

2. **[NIT] GitHub commit `has_files` predicate under-specified.** Addressed. The
   "Commit behavior to preserve" block and the github-commit input-validation line
   now state the exact predicate
   `has_files = isinstance(body.get("files"), list) or bool(body.get("path"))`, that
   `author_id` is optional (default `mahalo-bot`) when true and required when false,
   and that an empty `files: []` is still the file-contents shape. Verified against
   `mock_backend.create_commit`.

3. **[NIT] "returns `data` unchanged" undersells computed-field routes.** Addressed.
   Decision 2's "Table shape" bullet and the "Invariants â†’ Response-shape
   equivalence" line are reworded: the handler returns the stored record directly for
   plain reads, and for the routes the mock enriches/trims (jira
   `assignee_details`/sprint velocity/board columns; confluence page-summary trimming
   and search excerpt/relevance; github and servicenow `/stats`) it applies the same
   transform on top of the stored record. No behavioral change; removes the internal
   tension.

## Responses to design review (iteration 2)

Review: `docs/.agents/tasks/task3-design-review.md` /
`docs/.agents/tasks/task3-design-review.json` (verdict `CHANGES_REQUESTED`). Every
finding was re-verified against the mahalo-dock sources
(`github/mock_backend.py`, `github/main.py`, `confluence/main.py`,
`servicenow/main.py`, `jira/main.py`) before editing. All seven are **addressed**.

1. **[HIGH] Commit/PR id generation (count vs max).** Addressed. The GitHub
   behavioral details now spell out per-field rules â€” commit id
   `c{count(COMMITS)+1:03d}` (count-based), PR id `pr-{count(PULL)+1}` (count-based),
   PR `number` `max+1` (max-based) â€” and the "Invariants â†’ ID generation" section is
   rewritten from a single "compute the max" into an explicit max-based vs
   count-based split covering jira/servicenow/github/confluence, with the DynamoDB
   `Query` `Count` mapping stated. Decision 2's prose was corrected to match.
   Verified: `mock_backend.py` uses `len(COMMITS)`/`len(PULL_REQUESTS)` for the id
   strings and `max(...)+1` only for PR `number`.

2. **[MEDIUM] github `/health` `mode` field.** Addressed. `/health` now specifies
   `mode = os.environ.get("GITHUB_MODE", "mock")` (matching the mock), and the
   real-mode note states CDK does not set `GITHUB_MODE`, so the body is
   `{"mode":"mock"}` in Task 3 while the env switch stays live for the Task 4/7
   hook â€” removing the constant-vs-hook contradiction. The inventory `/health` row
   was updated to match.

3. **[MEDIUM] Confluence `create_page` id + uppercasing.** Addressed. A new
   "ID derivation and uppercasing on creates" block documents page id =
   `(supplied id or f"{space_id}-{count(PAGES)+1:03d}").upper()` and collects the
   other id-normalization rules in one place: `create_space` â†’
   `(id or "SPACE").upper()`, jira `create_project` â†’
   `(id or project_id or "PROJ").upper()`. Verified against the three mocks.

4. **[MEDIUM] jira/servicenow 422 source and validation order.** Addressed. The
   inventory error columns for `POST /stories` and `POST /incidents` now include
   422; the validation section states the order (required-field 422 **before**
   existence 404, mirroring pydantic running before the route body) and pins the
   422 body to a simplified `{"detail":"Field '<name>' is required"}` that the
   handler tests assert (the agent never parses the 422 body). Verified: both mocks
   use pydantic request models, so missing fields 422 ahead of the 404 checks.

5. **[MEDIUM] DynamoDB existence checks for github dict-keyed collections.**
   Addressed. Decision 2 now defines three separate collections (`BRANCHSET`,
   `STATS`, `REPO`), states that `create_repo` writes **both** a `REPO` item and a
   `BRANCHSET` item seeded with default `main` (and intentionally no `STATS` item),
   and that branch/commit/pull 404s key off `BRANCHSET` while `get_stats` 404s off
   `STATS` â€” mirroring `repo_id not in BRANCHES` vs `repo_id not in
   CONTRIBUTOR_STATS`, with an explicit "do not collapse into one lookup" warning.
   Verified against `create_repo`/`list_branches`/`create_commit`/`create_pull`/
   `get_stats` in `mock_backend.py`.

6. **[NIT] Affirm creates return 201.** Addressed. Decision 1 now states creates
   emit 201 (not 200), that the agent accepts both but the handler tests assert the
   exact status, and that the inventory success column is authoritative.

7. **[NIT] `requirements.txt` ambiguity.** Addressed. Decision 3 now states no
   per-service `requirements.txt` is created because the asset is zipped as-is with
   no pip step (`lambda.Function` + `Code.from_asset`, not the `PythonFunction`
   bundler), and test-only deps live in `tools-lambdas/requirements-dev.txt`. The
   code-layout block was updated to drop the stray `requirements.txt` entry.
