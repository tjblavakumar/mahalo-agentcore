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

5. **Reachability:** open the SG on port 3000 first and have the user test the
   URL. If the user's network blocks non-443 (browser got ERR_CONNECTION_TIMED_OUT),
   front Gitea with HTTPS on 443 (CloudFront or ALB). Decide after the test.

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

- [x] STEP 1 — Reachability SOLVED. (EIP + CloudFront HTTPS/443.) Browser URL:
      https://d3ec76atxiij9a.cloudfront.net/  — PENDING final user browser login test.
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
- [ ] STEP 2 — Seed Gitea (under `mahalo_admin`): 5 repos + feature branches +
      open PRs + representative commits; persona name in commit messages / PR
      title+body.
- [ ] STEP 3 — Flip GitHub Lambda to `giteaMode=real`; wire real Gitea URL +
      token env; redeploy.
- [ ] STEP 4 — Verify E2E: as each persona, make a write in Mahalo → confirm it
      appears in the single admin Gitea view; confirm reads (list repos / PRs)
      match Jira.
- [ ] STEP 5 — Deliver the demo login sheet (3 Mahalo personas + 1 Gitea admin).

## Live-state notes (update as we go)

- 2026-10-25 STEP 1 reachability SOLVED via CloudFront (workflow wf_80b05ca619730b03, APPROVED, commit f38cd66):
  - Browser HTTPS URL: https://d3ec76atxiij9a.cloudfront.net/ (login mahalo_admin / password in SSM /mahalo/gitea/admin-password).
  - CloudFront dist E2KKG6SJXJ4K1M, Deployed. Origin = EIP host (ec2-32-193-103-5.compute-1.amazonaws.com) HTTP:3000, caching disabled, ALLOW_ALL methods, AllViewerExceptHostHeader, redirect-to-https.
  - Gitea ROOT_URL set to the CloudFront URL via SSM; HTTP_PORT=3000 + 0.0.0.0 bind unchanged so the internal Lambda path is intact.
  - CDK change committed to gitea_stack.py (out-of-band note; NOT cdk-deployed) + GiteaCloudFrontUrl output + synth test (8/8 pass).
  - Server-side verified (dist Deployed, origin /api/healthz pass, ROOT_URL/HTTP_PORT confirmed). Browser login is the USER'S check (workflow is behind the same 443-only proxy).
  - EIP 32.193.103.5 retained as the CloudFront origin + stable address.
  - Report: docs/.agents/tasks/gitea-cloudfront.md.
