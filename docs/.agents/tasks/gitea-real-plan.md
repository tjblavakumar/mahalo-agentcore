# Execution Plan — Seed live Gitea + flip GitHub Lambda to real mode + verify E2E

Status: PLAN ONLY. A later coder step executes this. Do NOT run AWS commands or
edit code while reading; follow the ordered items below.

Authoritative inputs read while writing this plan:
- `docs/GITEA-REAL-PLAN.md` (LOCKED decisions + live-state facts).
- `tools-lambdas/github/seed_data.py` (REPOS/BRANCHES/PULL_REQUESTS/COMMITS — source of truth for what to seed).
- `tools-lambdas/jira/seed_data.py` (DEVELOPERS dev-1..dev-6, PROJECTS).
- `infra-cdk/app.py` (`_GITEA_ENV`, `giteaMode` gating).
- `infra-cdk/mahalo_infra/mock_service_stack.py` (how gitea env + token grant are applied).
- `tools-lambdas/github/gitea_backend.py` + `handler.py` (the REST shapes + env vars the adapter expects).

## Key facts locked from the code (do not re-derive)

- Adapter addresses repos by NAME under one owner: `mahalo_admin/<name>`
  (`gitea_backend._repo_path` = `/repos/{owner}/{repo}`). So Gitea repo names MUST
  equal the mock repo names: `payment-service`, `cart-service`, `auth-service`,
  `product-service`, `order-service`.
- Repo create: `POST /api/v1/user/repos` `{name, description, private:false, auto_init:true, default_branch:"main"}`.
- Branch create: `POST /api/v1/repos/{owner}/{repo}/branches` `{new_branch_name, old_branch_name}`.
- File commit (gives a REAL commit): `POST` (new) or `PUT` (existing, needs `sha`)
  `/api/v1/repos/{owner}/{repo}/contents/{path}` with body `{content:<base64>, message, branch}`.
- PR create: `POST /api/v1/repos/{owner}/{repo}/pulls` `{head, base, title, body}`.
- Auth header on every REST call: `Authorization: token <TOKEN>` (token from SSM `/mahalo/gitea/adapter-token`).
- `mock_service_stack.py` ALREADY grants `ssm:GetParameter` + `kms:Decrypt` in real
  mode (lines: `if service == "github" and gitea_mode and gitea_token_param_name:` →
  `param = ssm.StringParameter.from_secure_string_parameter_attributes(...)` →
  `param.grant_read(fn)`). **No grant fix is required.** The only code edit needed is
  the two URL values in `app.py`.
- Git commit author stays `mahalo_admin` (single-user + simple-attribution; locked).
  Persona name/role goes in COMMIT MESSAGE and PR TITLE/BODY text.

## Environment / account facts

- Account `<AWS_ACCOUNT_ID>`, region `us-east-1`, SSO profile `lava`.
- EC2 (Gitea host): `i-06d65fadd3fbd211b`; container name `gitea`; Gitea on
  `http://localhost:3000` on the box (box reaches localhost, NOT its own CloudFront/EIP).
- Browser + Lambda path to Gitea: `https://d3ec76atxiij9a.cloudfront.net` (CloudFront
  dist `E2KKG6SJXJ4K1M`). NEVER raw `:3000` from outside; NEVER open SG 3000 to 0.0.0.0/0.
- Thin API (deployed agent): `https://dkgwvy2h42xkejgmjc3tsvi4ku0qcyuz.lambda-url.us-east-1.on.aws/`.
- SSM Run Command only (no SSH/Docker). AL2023 host has `python3`; `jq` may be absent →
  use `python3` for JSON. The gitea CONTAINER has no python3.

---

## PERSONA / ROLE RESOLUTION (from jira seed DEVELOPERS)

| dev id | Name          | Resolved role     | Persona login? | Label to use in text          |
|--------|---------------|-------------------|----------------|--------------------------------|
| dev-1  | Marcus Chen   | Product Manager   | YES (PM)       | `Marcus Chen (Product Manager)`|
| dev-2  | Sarah Johnson | Developer         | no             | `Sarah Johnson (Developer)`    |
| dev-3  | Raj Patel     | Developer         | no             | `Raj Patel (Developer)`        |
| dev-4  | Emily Zhang   | Developer         | no             | `Emily Zhang (Developer)`      |
| dev-5  | David Kim     | Executive         | YES (Exec)     | `David Kim (Executive)`        |
| dev-6  | Lava Dev      | Developer         | YES (Dev)      | `Lava Dev (Developer)`         |

Label strings are the exact text appended to commit messages and PR titles/bodies.

---

## SEEDING MATRIX (exact, extracted from github/seed_data.py)

Owner for all = `mahalo_admin`. Every repo `auto_init=true`, `default_branch=main`.
Each feature branch is created off `main`. On each feature branch, create 1–2 real
files (real bytes) and commit with the message string shown. Then open ONE PR from
that feature branch → `main` with the title/body strings shown.

Conventions used below:
- **Commit message** = `<first seed commit message for the branch> — authored by <Label>  [<linked_story>]`
- **PR title** = `<seed PR title> — authored by <Label>`
- **PR body** = `<seed PR description>\n\nauthored by <Label>\nLinked story: <linked_story>`
- **File(s)**: create a small real file whose path encodes the feature so the commit
  has real bytes (Gitea rejects empty/metadata-only commits). Suggested path +
  minimal content given per branch; content is illustrative but MUST be non-empty.

### Repo 1 — `payment-service`
Description: `Payment processing microservice (Stripe, Apple Pay, Google Pay)`

- Branch `feature/PAY-105-google-pay` (author dev-1 Marcus Chen = Product Manager, story PAY-105)
  - File: `src/payments/google_pay.py` content: `"""Google Pay via Payment Request API (PAY-105)."""\n\ndef render_google_pay_button():\n    return "google-pay-button"\n`
  - Commit msg: `feat: add Google Pay button component — authored by Marcus Chen (Product Manager)  [PAY-105]`
  - PR title: `feat: Google Pay integration — authored by Marcus Chen (Product Manager)`
  - PR body: `Implements Google Pay using Payment Request API. Linked to PAY-105.\n\nauthored by Marcus Chen (Product Manager)\nLinked story: PAY-105`
- Branch `feature/PAY-106-payment-retry` (author dev-3 Raj Patel = Developer, story PAY-106)
  - File: `src/payments/retry.py` content: `"""Payment retry with exponential backoff (PAY-106)."""\n\nBACKOFF = [1, 4, 16]\n`
  - Commit msg: `feat: add retry mechanism with exponential backoff — authored by Raj Patel (Developer)  [PAY-106]`
  - PR title: `feat: Payment retry with exponential backoff — authored by Raj Patel (Developer)`
  - PR body: `Adds automatic retry mechanism for failed payments. Max 3 attempts. Linked to PAY-106.\n\nauthored by Raj Patel (Developer)\nLinked story: PAY-106`
- Branch `feature/PAY-108-analytics-dashboard` (author dev-5 David Kim = Executive, story PAY-108)
  - File: `src/payments/analytics.py` content: `"""Payment analytics endpoints (PAY-108)."""\n\ndef success_rate():\n    return 0.0\n`
  - Commit msg: `feat: payment success rate API endpoint — authored by David Kim (Executive)  [PAY-108]`
  - PR title: `feat: Payment analytics dashboard backend — authored by David Kim (Executive)`
  - PR body: `API endpoints for payment analytics: success rates, failure reasons, revenue metrics. Linked to PAY-108.\n\nauthored by David Kim (Executive)\nLinked story: PAY-108`

NOTE on `feature/PAY-107-multi-currency`: the seed BRANCHES list includes it, but
there is NO PR for PAY-107. Decision: create the branch + one representative file +
commit (so the branch exists, matching BRANCHES), but DO NOT open a PR (there is no
seed PR). Keeps branch coverage faithful without inventing a PR.
  - File: `src/payments/multi_currency.py` content: `"""Multi-currency support EUR/GBP/JPY (PAY-107)."""\n\nCURRENCIES = ["USD", "EUR", "GBP", "JPY"]\n`
  - Commit msg: `feat: multi-currency scaffolding — authored by Marcus Chen (Product Manager)  [PAY-107]`
  (PAY-107 assignee is dev-1 Marcus Chen per jira STORIES.)

### Repo 2 — `cart-service`
Description: `Shopping cart management and checkout flow`

- Branch `feature/CART-204-wishlist-to-cart` (author dev-2 Sarah Johnson = Developer, story CART-204)
  - File: `src/cart/wishlist.py` content: `"""Move wishlist items to cart (CART-204)."""\n\ndef move_to_cart(item_id):\n    return {"moved": item_id}\n`
  - Commit msg: `feat: add move-to-cart button on wishlist items — authored by Sarah Johnson (Developer)  [CART-204]`
  - PR title: `feat: Wishlist to cart conversion — authored by Sarah Johnson (Developer)`
  - PR body: `Move items from wishlist to cart with stock check. Linked to CART-204.\n\nauthored by Sarah Johnson (Developer)\nLinked story: CART-204`
- Branch `feature/CART-206-shipping-estimator` (author dev-2 Sarah Johnson = Developer, story CART-206)
  - File: `src/cart/shipping_estimator.py` content: `"""ZIP-based shipping cost estimator (CART-206)."""\n\ndef estimate(zip_code):\n    return {"zip": zip_code, "cost": 0.0}\n`
  - Commit msg: `feat: ZIP code based shipping estimation — authored by Sarah Johnson (Developer)  [CART-206]`
  - PR title: `feat: Shipping cost estimator — authored by Sarah Johnson (Developer)`
  - PR body: `ZIP-based shipping cost estimation in cart. Linked to CART-206.\n\nauthored by Sarah Johnson (Developer)\nLinked story: CART-206`
  - NOTE: seed PR `pr-5` status is `draft`. Gitea REST has no simple "draft" flag on
    create; create a NORMAL open PR. Acceptable (story identical; metrics differ is
    already an accepted consequence in GITEA-REAL-PLAN.md decision #4).

### Repo 3 — `auth-service`
Description: `User authentication, authorization, and SSO`

- Branch `feature/AUTH-304-totp-2fa` (author dev-3 Raj Patel = Developer, story AUTH-304)
  - File: `src/auth/totp.py` content: `"""TOTP 2FA setup + verification (AUTH-304)."""\n\ndef generate_secret():\n    return "BASE32SECRET"\n`
  - Commit msg: `feat: TOTP secret generation and QR code — authored by Raj Patel (Developer)  [AUTH-304]`
  - PR title: `feat: TOTP two-factor authentication — authored by Raj Patel (Developer)`
  - PR body: `QR code setup, TOTP verification, backup codes. Linked to AUTH-304.\n\nauthored by Raj Patel (Developer)\nLinked story: AUTH-304`
- Branch `feature/AUTH-306-saml-sso` (author dev-6 Lava Dev = Developer, story AUTH-306)
  - File: `src/auth/saml_sso.py` content: `"""SAML 2.0 SSO for enterprise (AUTH-306)."""\n\ndef sp_metadata():\n    return "<EntityDescriptor/>"\n`
  - Commit msg: `feat: SAML service provider metadata endpoint — authored by Lava Dev (Developer)  [AUTH-306]`
  - PR title: `feat: SAML 2.0 SSO for enterprise customers — authored by Lava Dev (Developer)`
  - PR body: `Adds SAML-based single sign-on with IdP- and SP-initiated flows and JIT provisioning. Linked to AUTH-306.\n\nauthored by Lava Dev (Developer)\nLinked story: AUTH-306`

### Repo 4 — `product-service`
Description: `Product catalog, search, and inventory management`

- Branch `feature/PROD-403-recommendations` (author dev-4 Emily Zhang = Developer, story PROD-403)
  - File: `src/product/recommendations.py` content: `"""Collaborative-filtering recommendations (PROD-403)."""\n\ndef recommend(user_id):\n    return []\n`
  - Commit msg: `feat: collaborative filtering model training pipeline — authored by Emily Zhang (Developer)  [PROD-403]`
  - PR title: `feat: Product recommendations engine — authored by Emily Zhang (Developer)`
  - PR body: `Collaborative filtering based recommendations. Linked to PROD-403.\n\nauthored by Emily Zhang (Developer)\nLinked story: PROD-403`

### Repo 5 — `order-service`
Description: `Order processing, fulfillment, and tracking`

- Branch `feature/ORD-503-split-fulfillment` (author dev-5 David Kim = Executive, story ORD-503)
  - File: `src/order/split_fulfillment.py` content: `"""Multi-warehouse split fulfillment (ORD-503)."""\n\ndef route(order):\n    return {"shipments": []}\n`
  - Commit msg: `feat: warehouse proximity routing algorithm — authored by David Kim (Executive)  [ORD-503]`
  - PR title: `feat: Split order fulfillment — authored by David Kim (Executive)`
  - PR body: `Multi-warehouse shipping with routing algorithm. Linked to ORD-503.\n\nauthored by David Kim (Executive)\nLinked story: ORD-503`

Totals to expect after seeding: 5 repos; 11 feature branches (5+2+2+1+1, incl.
PAY-107); 9 open PRs (3+2+2+1+1 — PAY-107 has no PR).

---

## ORDERED EXECUTION ITEMS

### STEP A — Seed Gitea via SSM Run Command (idempotent)

- [ ] A1. Build a single Python seeding script locally (NOT committed to the repo;
      it is embedded into the SSM command). The script runs ON the box against
      `http://localhost:3000/api/v1`. It must:
      1. Read the token: `TOKEN=$(aws ssm get-parameter --name /mahalo/gitea/adapter-token --with-decryption --region us-east-1 --query Parameter.Value --output text)` and pass it to the script via env (`GITEA_TOKEN=$TOKEN python3 /tmp/seed.py`). Use header `Authorization: token <TOKEN>`.
      2. Use only Python stdlib (`urllib.request`, `json`, `base64`) — do NOT rely on `requests`/`jq`.
      3. Be idempotent via existence checks before every create:
         - Repo: `GET /repos/mahalo_admin/<name>` → if 404, `POST /user/repos` (auto_init).
         - Branch: `GET /repos/mahalo_admin/<name>/branches/<branch>` → if 404, `POST .../branches` `{new_branch_name,old_branch_name:"main"}`.
         - File/commit: `GET /repos/mahalo_admin/<name>/contents/<path>?ref=<branch>` → if present, PUT with returned `sha`; else POST. Body `{content:<base64 of utf-8>, message, branch}`.
         - PR: `GET /repos/mahalo_admin/<name>/pulls?state=all&limit=50`; skip if a PR with the same `head` ref already exists; else `POST .../pulls` `{head,base:"main",title,body}`.
      4. Encode the full matrix above (repos, branches, files+messages, PRs) as data at the top of the script. Use the EXACT commit-message and PR title/body strings from the matrix.
      Files: ephemeral `seed.py` on the box only (no repo file).
      Verify: covered by A3 (script runs clean, no tracebacks).

- [ ] A2. Send the script over SSM base64-encoded to dodge shell-quoting. Produce the
      command document inline: base64 the whole `seed.py`, then the SSM
      `AWS-RunShellScript` command is:
      `echo '<BASE64>' | base64 -d > /tmp/seed.py && TOKEN=$(aws ssm get-parameter --name /mahalo/gitea/adapter-token --with-decryption --region us-east-1 --query Parameter.Value --output text) && GITEA_TOKEN="$TOKEN" python3 /tmp/seed.py > /tmp/seed.out 2>&1; echo "RC=$?"; cat /tmp/seed.out`
      Invoke via: `aws ssm send-command --profile lava --region us-east-1 --instance-ids i-06d65fadd3fbd211b --document-name AWS-RunShellScript --parameters commands=["<the line above>"] --query Command.CommandId --output text`.
      Then poll `aws ssm get-command-invocation --profile lava --region us-east-1 --command-id <id> --instance-id i-06d65fadd3fbd211b` and read `StandardOutputContent`.
      PowerShell swallows stdout — redirect the get-command-invocation output to a
      file and read it back; clean up the scratch file after.
      Files: none committed.
      Verify: `Status=Success` and `RC=0` in the invocation output.

- [ ] A3. VERIFY seeding on the box (second SSM command). Run, against localhost:3000
      with the token, a Python stdlib check that prints:
      - repo count from `GET /repos/mahalo_admin` or per-name GETs → expect 5.
      - for `payment-service` and `auth-service`: `GET .../branches` and `GET .../pulls?state=open` → confirm the feature branches and open PRs exist and PR titles contain `— authored by`.
      Files: none committed.
      Verify: output lists 5 repos; payment-service shows branches
      `feature/PAY-105-google-pay`, `feature/PAY-106-payment-retry`,
      `feature/PAY-107-multi-currency`, `feature/PAY-108-analytics-dashboard` and 3 open PRs
      with labeled titles; auth-service shows the two AUTH branches + 2 open PRs.

### STEP B — Flip GitHub Lambda to real mode (CloudFront)

- [ ] B1. Edit `infra-cdk/app.py` `_GITEA_ENV`. Current lines:
      ```python
      _GITEA_ENV = {
          "GITEA_URL": "http://gitea.internal:3000",
          "GITEA_ADMIN_USER": "mahalo_admin",
          "GITEA_PUBLIC_URL": "http://gitea.public:3000",
          "DEMO_DEVELOPER_ID": "dev-6",
          "GITEA_TOKEN_PARAM": _GITEA_TOKEN_PARAM,
      }
      ```
      Change ONLY the two URL values to the CloudFront HTTPS endpoint (no trailing
      slash — the adapter `.rstrip("/")`s but keep it clean):
      ```python
      _GITEA_ENV = {
          "GITEA_URL": "https://d3ec76atxiij9a.cloudfront.net",
          "GITEA_ADMIN_USER": "mahalo_admin",
          "GITEA_PUBLIC_URL": "https://d3ec76atxiij9a.cloudfront.net",
          "DEMO_DEVELOPER_ID": "dev-6",
          "GITEA_TOKEN_PARAM": _GITEA_TOKEN_PARAM,
      }
      ```
      Leave `GITEA_ADMIN_USER`, `DEMO_DEVELOPER_ID`, `GITEA_TOKEN_PARAM` unchanged.
      Do NOT touch `mock_service_stack.py` — the ssm:GetParameter grant is already
      present (see Key facts). Do NOT edit `gitea_stack.py`.
      Files: `infra-cdk/app.py`.
      Verify: `cd infra-cdk; .\.venv\Scripts\python.exe -m pytest tests/test_synth.py -q` → all pass (default-mode tests don't assert the URL values, so they stay green).

- [ ] B2. Deploy ONLY the github stack in real mode, with the VDI credential preamble.
      In PowerShell from `infra-cdk/`:
      ```powershell
      # 1) Export SSO creds into the shell (CDK/Node can't read the SSO cache on this VDI)
      aws configure export-credentials --profile lava --format env-no-export | Out-File -Encoding ascii creds.txt
      Get-Content creds.txt | ForEach-Object { if ($_ -match '^(AWS_[A-Z_]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2]) } }
      Remove-Item creds.txt
      $env:CDK_DEFAULT_ACCOUNT="<AWS_ACCOUNT_ID>"; $env:CDK_DEFAULT_REGION="us-east-1"
      # 2) Put venv python on PATH so cdk.json's "python app.py" uses it
      $env:PATH="$PWD\.venv\Scripts;$env:PATH"
      # 3) Deploy ONLY the github stack, real mode, no --profile (creds are in env)
      cdk deploy MahaloMockGithubStack -c giteaMode=real --require-approval never
      ```
      Run with a generous timeout / background — venv python cold-starts slowly
      (Defender) and synth/deploy can exceed 120s. If "Another CLI (PID=...) is
      currently synthing": kill stale node processes and delete `cdk.out/*.lock`,
      then retry. Do NOT deploy `MahaloGiteaStack` (its SG default 0.0.0.0/0 would
      be auto-stripped and it owns stateful resources).
      Files: none.
      Verify: cdk reports `MahaloMockGithubStack` UPDATE_COMPLETE.

- [ ] B3. Confirm the deployed Lambda env. The github function logical name is the
      `Function` construct inside `MahaloMockGithubStack`; find its physical name:
      `aws cloudformation describe-stack-resources --profile lava --region us-east-1 --stack-name MahaloMockGithubStack --query "StackResources[?ResourceType=='AWS::Lambda::Function'].PhysicalResourceId" --output text`
      then:
      `aws lambda get-function-configuration --profile lava --region us-east-1 --function-name <name> --query "Environment.Variables" --output json`
      Files: none.
      Verify: env shows `GITHUB_MODE=real`, `GITEA_URL=https://d3ec76atxiij9a.cloudfront.net`,
      `GITEA_PUBLIC_URL=https://d3ec76atxiij9a.cloudfront.net`, `GITEA_ADMIN_USER=mahalo_admin`,
      `DEMO_DEVELOPER_ID=dev-6`, `GITEA_TOKEN_PARAM=/mahalo/gitea/adapter-token`.

### STEP C — End-to-end verification via the deployed agent

Thin API base: `https://dkgwvy2h42xkejgmjc3tsvi4ku0qcyuz.lambda-url.us-east-1.on.aws`.
Unsigned POST; header `X-Mahalo-Persona: <PM|Dev|Exec>`; body `{"message":"...","session_id":"<unique>"}`.
Capture ACTUAL responses into the report. Use PowerShell `Invoke-RestMethod` (or curl)
and write JSON responses to files, then read them back.

- [ ] C1. READ as Dev — list repos. `X-Mahalo-Persona: Dev`,
      body `{"message":"list my repositories","session_id":"e2e-read-repos-1"}`.
      Verify: response names all 5 real Gitea repos (payment-service, cart-service,
      auth-service, product-service, order-service).

- [ ] C2. READ as Dev — open PRs for payment-service.
      body `{"message":"show open pull requests for payment-service","session_id":"e2e-read-prs-1"}`.
      Verify: response lists the seeded PRs with the `— authored by ... ` labeled titles.

- [ ] C3. HITL WRITE as Dev — create a branch (two-call approve flow).
      Call 1: POST `/chat` `X-Mahalo-Persona: Dev`
      `{"message":"create a branch called feature/demo-smoke off main in payment-service","session_id":"e2e-write-1"}`
      → expect a proposal with status `needs_approval` and an `interrupt_id`.
      Call 2: POST `/chat/approve`
      `{"decision":"approve","interrupt_id":"<from call 1>","session_id":"e2e-write-1"}`
      → expect execution confirmation.
      Verify: `feature/demo-smoke` exists in Gitea — either ask the agent
      `{"message":"list branches for payment-service","session_id":"e2e-write-1"}`,
      OR SSM curl on the box `GET http://localhost:3000/api/v1/repos/mahalo_admin/payment-service/branches/feature/demo-smoke` (200).
      KNOWN QUIRK: a write by repo NAME vs id can 404 at the mock layer; in real mode
      repos are keyed by name so name ops work — if 404, confirm the repo exists under
      mahalo_admin and GITEA_URL points at CloudFront.

- [ ] C4. (Optional) HITL REJECT — repeat C3 call 1 with session `e2e-reject-1`, then
      `/chat/approve` `{"decision":"reject","interrupt_id":"<id>","session_id":"e2e-reject-1"}`.
      Verify: no branch created (the proposed branch is absent in Gitea).

### STEP D — Deliverables + commit

- [ ] D1. Write the E2E report `docs/.agents/tasks/gitea-real-e2e.md` capturing:
      STEP A seeding command IDs + verification output (5 repos / branches / PRs),
      STEP B deploy result + the `get-function-configuration` env dump,
      STEP C actual request/response bodies for C1–C4, and any quirks hit.
      Files: `docs/.agents/tasks/gitea-real-e2e.md`.
      Verify: file exists and contains the captured outputs.

- [ ] D2. Append a progress entry to `docs/GITEA-REAL-PLAN.md`: mark STEP 2 (seed),
      STEP 3 (flip real mode) and STEP 4 (E2E verify) done with date + a one-line
      summary each and a pointer to `gitea-real-e2e.md`.
      Files: `docs/GITEA-REAL-PLAN.md`.
      Verify: the `## Plan / progress` checkboxes for STEP 2/3/4 are checked.

- [ ] D3. Commit the code change on a new branch (never push unless asked).
      Stage ONLY `infra-cdk/app.py` (and nothing else code-wise):
      `git checkout -b gitea-real-mode-flip`
      `git add infra-cdk/app.py`
      `git commit -m "feat(gitea): point github lambda real-mode env at CloudFront HTTPS"`
      If a `mock_service_stack.py` grant fix had been needed it would be staged too —
      but it is NOT needed (grant already present), so only `app.py` is committed.
      Docs under `docs/.agents/tasks/` and `docs/GITEA-REAL-PLAN.md` may be committed
      separately if the user wants them tracked; otherwise leave them unstaged.
      Files: `infra-cdk/app.py`.
      Verify: `git show --stat HEAD` lists only `infra-cdk/app.py`.

## Assumptions / gaps noted
- `pr-5` (CART-206) is `draft` in seed; created as a normal open PR (Gitea REST
  draft-on-create is not simply exposed; story stays identical, accepted per decision #4).
- `feature/PAY-107-multi-currency` branch is seeded (in BRANCHES) but has no seed PR,
  so a branch+commit is created with NO PR.
- Reviews from the seed (`changes_requested`/`approved`/etc.) are NOT replayed — the
  adapter maps `reviews: []` and the demo story doesn't depend on them.
- Commits are PARTIAL (one representative commit per feature branch) per locked
  decision #3; real-mode metrics will differ from mock numbers (accepted, decision #4).
