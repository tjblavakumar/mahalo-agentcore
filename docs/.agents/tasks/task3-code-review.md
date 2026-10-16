# Task 3 Code Review — Mocks reimplemented as AWS Lambdas

Four mahalo-dock mock services ported to AWS Lambda (Function URL + DynamoDB) with a Python CDK app, reviewed against the authoritative `task3-design.md` / `task3-plan.md` and the two FEAT artifacts. The port is behavior-equivalent to the mocks, the verification evidence in both FEAT files reproduces, and the only open items are two low-impact findings.

**Watch for:** nothing blocking. A pydantic-ordering edge (auth-vs-422) that the agent never triggers [confirmed], and one untested branch of the github commit predicate [confirmed].

**Verdict**: APPROVED

## High-level view

The four `seed_data.py` are byte-for-byte copies of their mahalo-dock sources (Get-FileHash equality holds for all four), so the fixtures the agent reasons about are identical. Each service is a plain `(event, context)` handler over a thin shared router, with state in a per-service DynamoDB table seeded lazily via a conditional-put sentinel. The route logic is a close transcription of the mock `main.py` / `mock_backend.py`: same verbs, paths, filters, response shapes, and — critically — the same status codes and `detail` strings the agent substring-matches on.

The security posture matches the mocks exactly: a static `X-API-Token` checked with a case-insensitive header-key lookup and an exact value compare, `/health` exempt, 401 `{"detail":"Invalid API token"}` on miss. The Function URL is deliberately `AuthType=NONE` because the handler enforces the token itself; layering IAM auth would break the agent's header-only contract. This is the intended design, not a gap.

GitHub is the highest-risk port and is handled correctly: three separate collections (REPO / BRANCHSET / STATS) back three distinct existence checks, all keyed by seed id `repo-N` with no name->id resolution, so an agent lookup by repo name 404s exactly as the mock does. A freshly created repo gets a BRANCHSET (default `main`) but no STATS, so it 404s on `/stats` while succeeding on branch/commit/pull. The count-vs-max ID split (commit id and PR id count-based, PR number / jira story / servicenow incident max-based) is reproduced per field.

The CDK synthesizes one python3.13 Lambda + one PAY_PER_REQUEST table + one Function URL (NONE) per service, with IAM scoped to that single table and both Function-URL and ARN CfnOutputs for Task 4. The reset script is guarded to the four exact table names, clears items only (never DeleteTable), and is unreachable by the agent. No `agent/` or `mahalo-dock/` file was touched and no LangChain import exists anywhere.

## Verification (re-run, not taken on trust)

- `& tools-lambdas/.venv/Scripts/python.exe -m pytest tools-lambdas/tests -q` -> **68 passed**, offline under moto, matching FEAT-001.
- `& infra-cdk/.venv/Scripts/python.exe -m pytest infra-cdk/tests -q` -> **20 passed**, matching FEAT-002.
- `cdk synth` -> four templates written (`MahaloMock{Jira,Confluence,Github,Servicenow}Stack`). Inspected the github template directly: `Runtime: python3.13`, `AuthType: NONE`, `BillingMode: PAY_PER_REQUEST`, handler `github.handler.lambda_handler`, env `TABLE_NAME`+`MOCK_GITHUB_TOKEN` (no `GITHUB_MODE`), outputs `GithubUrl`+`GithubArn`, and the IAM policy resource references only this stack's own table (least privilege).
- Seed equality: Get-FileHash matches for jira/confluence/github/servicenow.
- `git status` shows no changes under `agent/`; mahalo-dock working tree clean; grep for `langchain`/`langgraph` under `tools-lambdas`/`infra-cdk`/`scripts` returns nothing.

<details>
<summary>Issues (2)</summary>

1. **Auth-vs-validation ordering (LOW)** — pydantic-bodied POST routes (jira create_story, servicenow create_incident, github create_branch) check auth before the required-field 422, whereas the FastAPI mocks validate the body (422) before `verify_token` (401). Only matters when a request is both unauthenticated and malformed, which the agent never sends. Optionally reorder the 422 check ahead of the 401 check on those three routes, or record it as an intentional simplification.
2. **Untested commit predicate branch (NIT)** — the `or bool(body.get('path'))` fallback of the github commit `has_files` predicate is implemented but not covered by a test. Add a handler test posting a commit with `path` and no `files`, asserting 201 and `author_id` defaulting to `mahalo-bot`.

</details>

<details>
<summary>Details</summary>

### Seed fidelity and lazy seeding

The four seed modules are verbatim copies (hash-verified), including github's dict-keyed `BRANCHES`/`CONTRIBUTOR_STATS` and servicenow's `_SERVICE_CONTEXT`. `Store.ensure_seeded()` checks a `pk="_meta", sk="seeded"` sentinel and, if absent, deep-copies every seed item via a batched write, then sets the sentinel with `attribute_not_exists(pk)` so concurrent cold starts cannot double-seed; a `ConditionalCheckFailedException` is swallowed (another environment won the race) and any other `ClientError` propagates to the handler's 503 mapping. github's `BRANCHSET`/`STATS` store their per-repo list under a `value` attribute while everything else uses `data`, matching the design's dict-vs-list distinction.

### GitHub three-collection split and ID rules

This is the part most likely to diverge, and it does not. `create_repo` writes a `REPO` item and a `BRANCHSET` item seeded with the default `main` branch but no `STATS` item, so `test_three_collection_split_fresh_repo` confirms a fresh repo succeeds on branch/commit/pull and 404s on `/stats` — exactly the mock's `setdefault`-seeds-branches-only behavior. All repo keys are the seed id `repo-N`; `test_get_repo_by_name_404_no_resolution` asserts that a lookup by the repo *name* (`payment-service`) 404s, replicating the agent-passes-name vs mock-keys-by-id mismatch as-is. The count-vs-max split is asserted concretely: new commit `c035` (count-based over 34 seed commits), new PR id `pr-10` (count-based over 9 seed PRs), new PR `number` 145 (max-based over seed max 144).

### Exact detail strings and status codes

Handler tests assert the verbatim strings the agent substring-matches: `Branch already exists` (409), `Repository already exists` (409), `head branch is required` (422), `Field 'author_id' is required` (422), `Repository not found`/`Branch not found`/`Pull request not found` (404), and servicenow `Unknown affected_service` (404). The github branch-create 422 uses the port-owned simplified `Field 'name' is required` (pydantic-sourced in the mock), while commit/pull 422s keep the mock-backend verbatim wording — matching the design's per-route 422 pinning. Bad `pr_number` path params coerce via the router's declared int set and 422 on failure.

### Auth posture

`require_token` does a case-insensitive scan for the `x-api-token` key and compares the value with `==` (no trim, no case-fold), so absence/`None`/mismatch all 401 — mirroring the mocks' `x_api_token != API_TOKEN`. `/health` skips the check on every service. The Function URL is `AuthType=NONE` by design (the token is the real gate); this is the correct choice to keep the agent's existing header-only contract working, and the synthesized template confirms `AuthType: NONE` with CDK adding the public invoke permission.

The one divergence is ordering: because the mocks' pydantic layer validates the body before the route body (where `verify_token` lives), a request that is simultaneously malformed and unauthenticated yields 422 in the mock but 401 in the port. The agent always sends a valid token, so this is unreachable on real traffic; captured as a LOW finding.

### CDK, IAM, and the reset script

`MockServiceStack` is instantiated four times. Each stack: one `mahalo-mock-<svc>` table (pk/sk string, PAY_PER_REQUEST, RemovalPolicy.DESTROY); one python3.13 `lambda.Function` bundling `../tools-lambdas` with the other three service dirs, tests, venv, caches and dev-reqs excluded; `table.grant_read_write_data(fn)` producing an inline policy whose resource references only this stack's table (verified in the synthesized JSON to be a single-table `Fn::GetAtt`); a Function URL (NONE); and `*Url`/`*Arn` CfnOutputs. `GITHUB_MODE` is deliberately unset so `/health` reports `{"mode":"mock"}`. `scripts/reset-mock-tables.ps1` is `SupportsShouldProcess`/`ConfirmImpact=High`, iterates the four hard-coded table names with a defense-in-depth allow-list check, scans pk/sk and deletes items (including the sentinel), and never issues DeleteTable — a contained blast radius for a destructive maintenance action.

</details>

<details>
<summary>File map</summary>

- `tools-lambdas/common/{router,auth,responses,dynamo_store}.py` — shared runtime: event normalization + routing, token check, JSON/Decimal responses, lazy-seeding DynamoDB store.
- `tools-lambdas/{jira,confluence,github,servicenow}/{handler,routes,seed_data}.py` — per-service entrypoint, ported route logic, verbatim seed data.
- `tools-lambdas/tests/*` — conftest (moto table + synthetic Function-URL / API-GW events) and five test modules (router + four handlers); 68 tests.
- `infra-cdk/app.py`, `infra-cdk/mahalo_infra/mock_service_stack.py` — four-stack app and the reusable per-service stack.
- `infra-cdk/tests/test_synth.py` — 20 CDK assertion tests (table, python3.13 function, Function URL NONE, single-table IAM).
- `scripts/reset-mock-tables.ps1` — operator-only, exact-name, item-clear reset.

Full diff: these are untracked working-tree files under `tools-lambdas/`, `infra-cdk/`, `scripts/`, and `docs/.agents/tasks/task3-*`; review with `git status` / `git add -N` + `git diff`.

</details>
