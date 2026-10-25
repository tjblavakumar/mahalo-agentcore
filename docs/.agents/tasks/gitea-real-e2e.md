# Gitea real-mode seed + flip — E2E verification report

Date: 2026-10-25. Account `<AWS_ACCOUNT_ID>`, region `us-east-1`, SSO profile `lava`.
Executes the plan at `docs/.agents/tasks/gitea-real-plan.md`. All on-box work via
SSM Run Command (AWS-RunShellScript) on `i-06d65fadd3fbd211b`; agent E2E via the
thin API Function URL. This file records exactly what was run and observed so the
evidence can be read without re-running anything.

## STEP A — Seed live Gitea (SSM Run Command, idempotent)

Seed script (stdlib-only Python, base64-encoded into the SSM command, decoded on
the host, run as `GITEA_TOKEN=<ssm adapter-token> python3 /tmp/seed.py`) is saved
at `gitea/seed_gitea.py`. It is idempotent (GET existence check before every
create). All objects owned by `mahalo_admin`; git author stays `mahalo_admin`;
persona name+role carried in commit messages and PR title/body (simple
attribution, single-user model — unchanged).

- Command ids: `2cbee8ca-fd2f-4055-91a3-36b16c61fcd6` (first run, hit a transient
  Gitea `403 cannot lock ref` race on cart-service), then re-run
  `9638e290-1968-43a7-b04b-6eccf916ae0f` → `Status=Success`, `RC=0`.
- Seed summary line from the host: `SEED SUMMARY: repos=5 branches=10 prs_attempted=9`.

### STEP A verification (command id `2e5123ab-5486-4f46-8091-c31a057c2e9d`, RC=0)

`GITEA_TOKEN=<token> python3 /tmp/verify.py` against `http://localhost:3000/api/v1`:

```
REPO COUNT: 5
REPOS: auth-service, cart-service, order-service, payment-service, product-service
--- payment-service ---
  branches (5): feature/PAY-108-analytics-dashboard, feature/PAY-107-multi-currency,
                feature/PAY-106-payment-retry, feature/PAY-105-google-pay, main
  open PRs (3):
    #3  feat: Payment analytics dashboard backend — authored by David Kim (Executive)
    #2  feat: Payment retry with exponential backoff — authored by Raj Patel (Developer)
    #1  feat: Google Pay integration — authored by Marcus Chen (Product Manager)
--- auth-service ---
  branches (3): feature/AUTH-306-saml-sso, feature/AUTH-304-totp-2fa, main
  open PRs (2):
    #2  feat: SAML 2.0 SSO for enterprise customers — authored by Lava Dev (Developer)
    #1  feat: TOTP two-factor authentication — authored by Raj Patel (Developer)
```

Seeded totals (matching `tools-lambdas/github/seed_data.py`):
- 5 repos: payment-service, cart-service, auth-service, product-service, order-service.
- 10 feature branches: PAY-105/106/107/108 (4), CART-204/206 (2), AUTH-304/306 (2),
  PROD-403 (1), ORD-503 (1). (Plan note "11" was an arithmetic slip —
  payment-service has 4 feature branches, not 5.)
- 9 open PRs (PAY-107 has a branch but no seed PR, so no PR was opened for it).
- 1 representative real-content file + commit per feature branch; commit message
  carries `— authored by <Name> (<role>)  [<story>]`.
- Persona labels confirmed on PR titles (Product Manager / Developer / Executive).

## STEP B — Flip GitHub Lambda to real mode (CloudFront)

Code change: `infra-cdk/app.py` `_GITEA_ENV` — `GITEA_URL` and `GITEA_PUBLIC_URL`
changed from the `gitea.internal` / `gitea.public` placeholders to
`https://d3ec76atxiij9a.cloudfront.net`. `GITEA_ADMIN_USER=mahalo_admin`,
`DEMO_DEVELOPER_ID=dev-6`, `GITEA_TOKEN_PARAM=/mahalo/gitea/adapter-token`
unchanged. `infra-cdk/tests/test_synth.py` → 20 passed.

The `ssm:GetParameter` grant for the token was already present in
`mock_service_stack.py` (real-mode branch) — no grant edit needed.

### Deploy-path gap found and fixed (httpx packaging)

First deploy of `MahaloMockGithubStack -c giteaMode=real` succeeded, but the first
agent READ returned an internal HTTP 500. CloudWatch
(`/aws/lambda/MahaloMockGithubStack-Function76856677-dEbVZIas4Vsd`) showed:

```
File "/var/task/github/gitea_backend.py", line 31, in <module>
    import httpx
ModuleNotFoundError: No module named 'httpx'
```

Root cause: the mock path imports no third-party deps, and the github Lambda asset
(`Code.from_asset("../tools-lambdas")`) does no pip install. `httpx` existed only
in `requirements-dev.txt` (which the asset excludes), so the real-mode adapter had
no HTTP client at runtime. The VDI has NO Docker, so the project's Docker-based
`BundlingOptions` path (used by `api_stack` behind `-c buildImage=1`) is not usable.

Fix (Docker-free, github-only, no behavior change): vendored `httpx==0.28.1` and
its pure-Python dependency closure (`httpcore`, `h11`, `anyio`, `sniffio` via anyio,
`idna`, `certifi`, `typing_extensions`) into `tools-lambdas/github/_vendor/`, and
added a `sys.path.append(<_vendor>)` fallback at the top of `gitea_backend.py`
BEFORE `import httpx` (appended, not prepended, so the dev/test venv keeps using its
own httpx). The CDK exclude list drops `github/` from the other three service
Lambdas, so `_vendor/` ships only in the github Lambda. `tools-lambdas`
`test_github_handler.py` → 25 passed after the change.

Redeploy command (second deploy) `MahaloMockGithubStack -c giteaMode=real
--require-approval never` → `UPDATE_COMPLETE`, `DEPLOY2_EXIT=0`.

### STEP B verification — deployed Lambda env

`aws lambda get-function-configuration --function-name
MahaloMockGithubStack-Function76856677-dEbVZIas4Vsd --query Environment.Variables`:

```json
{
    "GITEA_TOKEN_PARAM": "/mahalo/gitea/adapter-token",
    "DEMO_DEVELOPER_ID": "dev-6",
    "TABLE_NAME": "mahalo-mock-github",
    "GITEA_URL": "https://d3ec76atxiij9a.cloudfront.net",
    "MOCK_GITHUB_TOKEN": "mock-github-token-12345",
    "GITHUB_MODE": "real",
    "GITEA_ADMIN_USER": "mahalo_admin",
    "GITEA_PUBLIC_URL": "https://d3ec76atxiij9a.cloudfront.net"
}
```

`GITHUB_MODE=real` + both URLs on CloudFront HTTPS — confirmed.

## STEP C — End-to-end verification via the deployed agent

Thin API base: `https://dkgwvy2h42xkejgmjc3tsvi4ku0qcyuz.lambda-url.us-east-1.on.aws`.
Unsigned POST; header `X-Mahalo-Persona: dev` (dev → dev-6 Lava Dev). NOTE: the
deployed `/chat/approve` contract takes `{"session_id","interrupt_id","approved":
true|false}` (boolean `approved`) — not a `decision` string — per `api/app/models.py`.

### C1 — READ as Dev: "list my repositories" (session `e2e-read-repos-1`)

Response (verbatim): all 5 real Gitea repos returned as a table —
`auth-service`, `cart-service`, `order-service`, `payment-service`,
`product-service` (all Python, default branch `main`, last push 2026-10-25). PASS.

### C2 — READ as Dev: "show open pull requests for payment-service" (session `e2e-read-prs-1`)

Response (verbatim excerpt): "There are **3 open PRs** in payment-service" —
- PR #3 Payment analytics dashboard backend, `feature/PAY-108-analytics-dashboard`,
  "David Kim/Executive", linked PAY-108.
- PR #2 Payment retry with exponential backoff, `feature/PAY-106-payment-retry`,
  "Raj Patel/Developer", linked PAY-106.
- PR #1 Google Pay integration, `feature/PAY-105-google-pay`,
  "Marcus Chen/Product Manager", linked PAY-105.

Persona labels visible on every PR. Real Gitea PR numbers (#1–#3). PASS.

### C3 — HITL WRITE as Dev: create `feature/demo-smoke` off main in payment-service (session `e2e-write-1`)

Call 1 `POST /chat` → `status=pending_approval`, proposal:
```json
{"action":"create_branch","system":"github",
 "params":{"repo_id":"payment-service","branch_name":"feature/demo-smoke","from_branch":"main"},
 "description":"Create branch 'feature/demo-smoke' in payment-service from main",
 "interrupt_id":"v1:before_tool_call:tooluse_i6U7pqZjMujFjNLIWUXHXP:7d5e9fc0-3c3f-5943-8604-6d9221a8aa70"}
```
Call 2 `POST /chat/approve` `{approved:true, interrupt_id:<above>, session_id:e2e-write-1}`
→ `{"success":true,"message":"Branch **feature/demo-smoke** created in
**payment-service** forked from **main**. ..."}`.

Verification (two independent checks):
1. Agent "list branches for payment-service" → lists `feature/demo-smoke`
   ("just created by you") alongside main + PAY branches.
2. Direct Gitea on the box (SSM command id `4e0d409e-2971-4be6-ae30-21b707b2237d`):
   `GET /repos/mahalo_admin/payment-service/branches/feature/demo-smoke` → `HTTP=200`.

The HITL write landed in the real Gitea. PASS.

### C4 — HITL REJECT as Dev: propose `feature/demo-reject`, then reject (session `e2e-reject-1`)

Call 1 `POST /chat` → `status=pending_approval` (proposal create_branch
feature/demo-reject). Call 2 `POST /chat/approve` `{approved:false,...}` →
`{"success":true,"message":"The branch creation was rejected. ..."}`.

Verification: direct Gitea on the box (SSM command id
`ee4b8bff-2656-4353-a878-bedb52a69dc6`):
`GET /repos/mahalo_admin/payment-service/branches/feature/demo-reject` → `HTTP=404`.
Reject wrote nothing. PASS.

## Known quirk (cosmetic, not blocking)

In C2 the PR `url` fields render as
`http://ec2-32-193-103-5.compute-1.amazonaws.com/...` rather than the CloudFront
domain. Gitea derives `html_url` from the request host/its stored host, and the
adapter's `_publicize` only rewrites occurrences of the configured base URL. Reads
and writes work correctly; only the echoed hyperlink host differs. The browser demo
view is opened directly at `https://d3ec76atxiij9a.cloudfront.net/` so this does not
affect the user-facing demo. Left as-is (changing Gitea host/ROOT_URL config is out
of scope and the links are not part of the acceptance path).

## Result

Reads return the real Gitea repos and the labeled PRs; the HITL approve created a
real branch confirmed present in Gitea (HTTP 200); the HITL reject created nothing
(HTTP 404). Real mode is live end-to-end through CloudFront.
