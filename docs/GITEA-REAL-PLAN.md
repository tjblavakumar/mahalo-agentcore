# Gitea "real mode" + demo-data plan — decisions & progress tracker

Single source of truth for the "point the agent at real Gitea so persona changes
are visible" work. Created 2026-10-25. Keep this updated as steps complete.

## Goal (user's words, paraphrased)

Make the live demo show that every persona's git changes (branches / commits /
PRs created by the agent) land in a REAL Gitea the user can open and see. Gitea
features themselves are NOT the demo — Gitea is just the real backend that proves
the agent's writes are real. The headline demo is: log into Mahalo as PM / Dev /
Exec, ask questions or open the dashboard, and have the agent answer across mock
Jira + mock Confluence + mock ServiceNow + Gitea-as-GitHub seamlessly.

## Locked decisions

1. **Single Gitea user.** One admin user `mahalo_admin` owns ALL repos and ALL
   activity. The user logs into Gitea once as this admin and sees every
   persona's changes in one place. NO per-persona Gitea accounts.
   - Rationale: Gitea's own user features aren't part of the demo; the current
     `GiteaBackend` is already single-user, so this needs ZERO backend rework
     (big saving vs. the rejected per-user plan).
   - REJECTED alternative: 6 Gitea users + bidirectional login↔dev-id backend
     mapping. Dropped as unnecessary effort.

2. **Attribution = "simple" option (user chose).** Git commit author stays
   `mahalo_admin`. The persona's name is carried in the COMMIT MESSAGE and the
   PR TITLE/BODY (e.g. "feat: Google Pay — authored by Marcus Chen (PM)"). No
   per-commit author identity; attribution lives in the text. One login shows
   all users' updates, each labeled.
   - REJECTED alternative: set per-commit git author name/email to the persona.
     Not chosen (simple wins).

3. **Do NOT fully migrate the DynamoDB mock data into Gitea.** Seed only what is
   visually convincing:
   - Repos: ALL 5 (payment-service, cart-service, auth-service,
     product-service, order-service) — match the 5 Jira projects.
   - Branches + open PRs: YES, full coverage — this is what the user points at.
   - Commits: PARTIAL — a representative commit or two per feature branch (real
     Gitea commits need real file content pushed). NOT a 1:1 replay of all ~34
     seed commits.
   - Pre-computed stats / contributor tables: NO — real mode DERIVES stats from
     actual Gitea commit history, so seed stat tables are ignored.
   - Note: the GitHub mock's data is in DynamoDB (loaded from
     `tools-lambdas/github/seed_data.py`), NOT MariaDB. (MariaDB/SQLite is
     Gitea's OWN internal DB.)

4. **Known/accepted consequence:** real mode and mock mode are NOT byte-identical.
   Mock reports exact seed numbers (e.g. "342 additions, 8 files"); real reflects
   what's actually in Gitea. Same STORY (repos, features, PRs, personas), a few
   METRICS differ. Accepted for the demo.

5. **Reachability:** SOLVED via EIP + CloudFront HTTPS/443. See the critical
   account-policy finding below.

6. **CRITICAL ACCOUNT POLICY — 0.0.0.0/0 ingress on non-standard ports is
   auto-removed.** This account has a drift-remediation / config-enforcement
   mechanism that STRIPS any security-group ingress rule opening a non-standard
   port (e.g. 3000) to `0.0.0.0/0` — within SECONDS. This is why every attempt to
   "open 3000 to the world" failed (original CDK deploy's rule never persisted;
   two manual 0.0.0.0/0 adds vanished immediately) and caused the CloudFront 504
   (origin unreachable). FIX: scope the 3000 ingress to the AWS-managed CloudFront
   origin-facing prefix list `pl-3b927c52`
   (com.amazonaws.global.cloudfront.origin-facing). A prefix-list-scoped rule
   SURVIVES (verified 45s+). Live rule: sgr-0ad28d2ad42ca22dc (tcp/3000 <-
   pl-3b927c52) on SG sg-04c06aeba215f7b94.
   IMPLICATION for the GitHub Lambda real-mode path: a non-VPC Lambda has no fixed
   egress IP and we CANNOT open 3000 to 0.0.0.0/0 (auto-removed). So the Lambda
   must NOT reach Gitea directly over the public EIP:3000. Instead, point the
   Lambda's GITEA_URL at the CloudFront HTTPS endpoint
   (https://d3ec76atxiij9a.cloudfront.net) so its REST calls go through 443 (the
   distribution already forwards all methods / no caching). This replaces the
   earlier "Lambda hits http://<eip>:3000 internally" assumption. Confirm during
   STEP 3 wiring.
   NOTE: the committed gitea_stack.py still defines the 3000 ingress as
   `GiteaIngressCidr` default 0.0.0.0/0 — that default will be auto-stripped if
   ever redeployed; update it to the CloudFront prefix list in the CDK too (later
   hardening, not blocking the demo).

6. **Deliverable:** a demo login sheet — the 3 Mahalo persona logins + the single
   Gitea admin login — so the user can switch personas during the demo.

## Reference facts (from investigation)

- Gitea stack LIVE: instance `i-06d65fadd3fbd211b`,
  URL `http://ec2-100-61-181-17.compute-1.amazonaws.com:3000`, admin
  `mahalo_admin` / password in SSM `/mahalo/gitea/admin-password`, adapter token
  in SSM `/mahalo/gitea/adapter-token`. Seed repo `payment-service` (README only).
- **SG blocker:** the Gitea security group currently has ONLY port 22 (SSH) from
  `3.83.200.219/32`. There is NO port-3000 ingress rule at all — this is why the
  browser times out. (The CDK default was GiteaIngressCidr=0.0.0.0/0 but the 3000
  rule is missing in the live SG.)
- **GiteaBackend is single-user** (`tools-lambdas/github/gitea_backend.py`): all
  git activity performed as the one owner (`mahalo_admin`); maps that one login
  to `DEMO_DEVELOPER_ID` (default dev-6). Fits decision #1 with no change.
- GitHub Lambda flips to real via CDK `-c giteaMode=real`; `app.py` already
  carries the non-secret Gitea env refs (`GITEA_URL`, `GITEA_ADMIN_USER`,
  `GITEA_PUBLIC_URL`, `DEMO_DEVELOPER_ID`, `GITEA_TOKEN_PARAM`). NOTE: these
  placeholder values (gitea.internal / gitea.public) must be updated to the real
  instance URL before flipping.
- Shared model across services: devs dev-1..dev-6
  (Marcus Chen / Sarah Johnson / Raj Patel / Emily Zhang / David Kim / Lava Dev);
  projects PAY, CART, AUTH, PROD, ORD. Personas: PM=dev-1 Marcus, Dev=dev-6 Lava,
  Exec=dev-5 David.

## Plan / progress

- [x] STEP 1 — Reachability SOLVED + USER-CONFIRMED (2026-10-25). Browser URL:
      https://d3ec76atxiij9a.cloudfront.net/ loads the Gitea login; user logged in
      as mahalo_admin. (EIP + CloudFront HTTPS/443 + CloudFront-prefix-list SG rule.)
      PROGRESS:
      - Added SG ingress rule sgr-050c093493d6c81b3 (tcp/3000 from 0.0.0.0/0) to
        SG sg-04c06aeba215f7b94. User tested — STILL timed out.
      - ROOT CAUSE FOUND: the instance had a CGNAT public IP (100.61.181.17, in
        100.64.0.0/10) which is NOT internet-routable, so it was never reachable
        regardless of SG. (Likely why the VDI also couldn't reach it.)
      - FIX APPLIED: allocated Elastic IP 32.193.103.5
        (eipalloc-0d582218ab8434359) and associated it with the instance
        (eipassoc-0c19a0d53795ce3d6). NEW public endpoint:
        32.193.103.5 / ec2-32-193-103-5.compute-1.amazonaws.com. EIP allocation
        is NOT blocked in this account (good to know).
      - User tested http://32.193.103.5:3000 — STILL timed out. CONCLUSION: the
        routable EIP proves routing is fixed, so the user's network blocks PORT
        3000 specifically (only 443 passes the corporate proxy). → MUST front
        Gitea with HTTPS on 443.
      - DECISION: CloudFront distribution over 443 → origin = the EIP host on
        HTTP:3000 (CloudFront reaches it over AWS's network; the office network
        only needs 443 to CloudFront). Mirrors how the frontend is served.
        Set Gitea ROOT_URL + GITEA_PUBLIC_URL to the CloudFront domain so links
        render correctly. Keep the EIP (CloudFront origin + stable address).
      - IMPORTANT: GiteaPublicUrl CfnOutput + the github Lambda GITEA_PUBLIC_URL
        env must be updated to whatever endpoint ends up working (EIP host or
        CloudFront domain) before/when flipping to real mode.
      - DONE (HTTPS/443 reachability SOLVED): CloudFront distribution
        E2KKG6SJXJ4K1M created (status Deployed). New HTTPS URL for the user:
        https://d3ec76atxiij9a.cloudfront.net/ (login mahalo_admin, password in
        SSM /mahalo/gitea/admin-password). Gitea ROOT_URL set to
        https://d3ec76atxiij9a.cloudfront.net/ via SSM; HTTP_PORT still 3000 and
        the internal Lambda path (http://<eip>:3000) is unchanged. Origin
        verified healthy server-side after the ROOT_URL change + restart.
        Distribution created OUT-OF-BAND (aws cloudfront create-distribution);
        the equivalent CDK change is committed in gitea_stack.py but NOT
        cdk-deployed. Edge curl could not be run from the VDI (same 443-only
        proxy blocks arbitrary hosts) — final browser check is the user's.
        Details: docs/.agents/tasks/gitea-cloudfront.md.
- [x] STEP 2 — Seed Gitea (under `mahalo_admin`): 5 repos + feature branches +
      open PRs + representative commits; persona name in commit messages / PR
      title+body. DONE 2026-10-25 (see live-state note below).
- [x] STEP 3 — Flip GitHub Lambda to `giteaMode=real`; wire real Gitea URL +
      token env; redeploy. DONE 2026-10-25 (see live-state note below).
- [x] STEP 4 — Verify E2E: reads return the 5 real repos + labeled PRs; a HITL
      approve created a real branch (confirmed in Gitea, HTTP 200); a HITL reject
      wrote nothing (HTTP 404). DONE 2026-10-25 (see live-state note below).
- [x] STEP 5 — DONE 2026-10-25. Demo login sheet + run guide written to
      docs/DEMO-LOGINS.md (3 Mahalo personas pm/dev/exec + the single Gitea admin
      mahalo_admin / (password in SSM /mahalo/gitea/admin-password) at https://d3ec76atxiij9a.cloudfront.net/,
      the 4-system table, and a suggested demo script). Consolidated docs/DEMO.md
      updated: §7 now states real Gitea mode is the ACTIVE path.

## ALL STEPS COMPLETE (2026-10-25)

The demo is live and end-to-end: log into Mahalo as any persona → the agent
answers across mock Jira/Confluence/ServiceNow + REAL Gitea; HITL writes land in
Gitea (visible at the CloudFront URL as mahalo_admin). Reachability solved
(EIP + CloudFront HTTPS + CloudFront-prefix-list SG rule). PR/commit links are
browser-clickable (publicize fix). See docs/DEMO-LOGINS.md to run the demo.

## Live-state notes (update as we go)

- 2026-10-25 STEP 1 reachability SOLVED via CloudFront (workflow wf_80b05ca619730b03, APPROVED, commit f38cd66):
  - Browser HTTPS URL: https://d3ec76atxiij9a.cloudfront.net/ (login mahalo_admin / password in SSM /mahalo/gitea/admin-password).
  - CloudFront dist E2KKG6SJXJ4K1M, Deployed. Origin = EIP host (ec2-32-193-103-5.compute-1.amazonaws.com) HTTP:3000, caching disabled, ALLOW_ALL methods, AllViewerExceptHostHeader, redirect-to-https.
  - Gitea ROOT_URL set to the CloudFront URL via SSM; HTTP_PORT=3000 + 0.0.0.0 bind unchanged so the internal Lambda path is intact.
  - CDK change committed to gitea_stack.py (out-of-band note; NOT cdk-deployed) + GiteaCloudFrontUrl output + synth test (8/8 pass).
  - Server-side verified (dist Deployed, origin /api/healthz pass, ROOT_URL/HTTP_PORT confirmed). Browser login is the USER'S check (workflow is behind the same 443-only proxy).
  - EIP 32.193.103.5 retained as the CloudFront origin + stable address.
  - Report: docs/.agents/tasks/gitea-cloudfront.md.

- 2026-10-25 STEP 2 (SEED) + STEP 3 (REAL-MODE FLIP) + STEP 4 (E2E VERIFY) DONE.
  Full evidence: docs/.agents/tasks/gitea-real-e2e.md.
  - SEED (STEP 2): idempotent stdlib Python seeder (gitea/seed_gitea.py) run on
    i-06d65fadd3fbd211b via SSM against localhost:3000, all owned by mahalo_admin
    (single-user + simple-attribution unchanged). Verified on the box:
    5 repos (payment-service, cart-service, auth-service, product-service,
    order-service); 10 feature branches (PAY-105/106/107/108, CART-204/206,
    AUTH-304/306, PROD-403, ORD-503); 9 open PRs (PAY-107 has a branch but no seed
    PR, so none opened); 1 representative real-content file+commit per feature
    branch. Persona labels present on PR titles + commit messages
    (e.g. "— authored by Marcus Chen (Product Manager)"). git author stays
    mahalo_admin. (Plan said "11 branches"; actual is 10 — payment-service has 4
    feature branches, not 5. Matches seed_data.py.)
  - REAL-MODE FLIP (STEP 3): infra-cdk/app.py _GITEA_ENV GITEA_URL +
    GITEA_PUBLIC_URL set to https://d3ec76atxiij9a.cloudfront.net (other fields
    unchanged). ssm:GetParameter grant was already present in
    mock_service_stack.py (no grant edit). DEPLOY-PATH GAP FOUND + FIXED: the
    first real-mode deploy 500'd because gitea_backend.py imports httpx but the
    Lambda asset pip-installs nothing and httpx was only in requirements-dev.txt
    (excluded). VDI has NO Docker so the Docker-based BundlingOptions path is
    unusable. Fix (Docker-free, github-only, no behavior change): vendored
    httpx==0.28.1 + pure-Python deps into tools-lambdas/github/_vendor/ and added
    a sys.path.append fallback in gitea_backend.py before `import httpx`
    (dev/test venv still uses its own httpx). _vendor ships only in the github
    Lambda (CDK excludes github/ from the other three). Deployed ONLY
    MahaloMockGithubStack -c giteaMode=real → UPDATE_COMPLETE. Deployed Lambda env
    confirmed: GITHUB_MODE=real, GITEA_URL=GITEA_PUBLIC_URL=
    https://d3ec76atxiij9a.cloudfront.net, GITEA_ADMIN_USER=mahalo_admin,
    DEMO_DEVELOPER_ID=dev-6, GITEA_TOKEN_PARAM=/mahalo/gitea/adapter-token.
    MahaloGiteaStack NOT redeployed.
  - E2E (STEP 4) via the deployed agent thin API
    (https://dkgwvy2h42xkejgmjc3tsvi4ku0qcyuz.lambda-url.us-east-1.on.aws), header
    X-Mahalo-Persona: dev:
    * READ "list my repositories" → all 5 real repos (verbatim: a table listing
      auth-service / cart-service / order-service / payment-service /
      product-service, Python, main, last push 2026-10-25).
    * READ "show open pull requests for payment-service" → the 3 seeded PRs with
      persona labels (PR#3 David Kim/Executive PAY-108; PR#2 Raj Patel/Developer
      PAY-106; PR#1 Marcus Chen/Product Manager PAY-105).
    * HITL WRITE "create a branch called feature/demo-smoke off main in
      payment-service" → /chat returned status=pending_approval + interrupt_id;
      /chat/approve {approved:true} → "Branch **feature/demo-smoke** created in
      **payment-service** forked from **main**." Branch confirmed in Gitea on the
      box: GET /repos/mahalo_admin/payment-service/branches/feature/demo-smoke →
      HTTP 200.
    * HITL REJECT "feature/demo-reject" → /chat/approve {approved:false} → "The
      branch creation was rejected." Gitea GET of that branch → HTTP 404 (nothing
      written).
  - PR-URL HOST MISMATCH — FIXED (follow-up, 2026-10-25, commit 2a28259 +
    github Lambda redeploy): agent-echoed PR urls previously rendered the EIP/
    localhost host (Gitea stamps html_url from the request host, which _publicize
    only rewrote when it exactly matched base_url). Rewrote
    GiteaBackend._publicize to swap the ENTIRE scheme+host[:port] origin of any
    absolute Gitea URL for GITEA_PUBLIC_URL (the CloudFront URL), so links are
    always browser-clickable regardless of which internal host Gitea used. Added
    regression test test_real_publicizes_url_from_any_internal_host (github
    handler suite 26 passed). Redeployed MahaloMockGithubStack -c giteaMode=real
    (UPDATE_COMPLETE). VERIFIED LIVE through the agent: "show open PRs for
    payment-service" now returns links like
    https://d3ec76atxiij9a.cloudfront.net/mahalo_admin/payment-service/pulls/3.
  - REMAINING cosmetic (not fixed, inherent to single-user decision #1): the
    agent appends "(dev-6)" to every PR author because the single-user backend
    maps the Gitea owner -> DEMO_DEVELOPER_ID=dev-6. The real author NAME in the
    PR title is correct (Marcus Chen / Raj Patel / David Kim); only the trailing
    dev-id tag is uniform. Accepted (consequence of "everything owned by one
    user").
  - Committed: infra-cdk/app.py + tools-lambdas/github/gitea_backend.py (httpx
    vendor shim) + tools-lambdas/github/_vendor/ on a new branch. Seeder/verifier
    helper scripts saved under gitea/.
