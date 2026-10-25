# Gitea behind HTTPS/443 via CloudFront — task report

## Outcome
The live Gitea instance is now reachable over HTTPS on port 443 through a
CloudFront distribution. A corporate network that only allows outbound 443 can
open the Gitea web UI + REST API at the URL below. The internal Lambda write
path (plain HTTP:3000 to the EIP) is untouched.

## User-facing access
- **HTTPS URL (give this to the user):** https://d3ec76atxiij9a.cloudfront.net/
- **Login user:** `mahalo_admin`
- **Password:** stored in SSM SecureString `/mahalo/gitea/admin-password`
  (referenced by name; value not echoed here).

## CloudFront distribution
- **Distribution Id:** `E2KKG6SJXJ4K1M`
- **Domain:** `d3ec76atxiij9a.cloudfront.net`
- **Status:** `Deployed` (verified via `aws cloudfront get-distribution`).
- **Origin:** `ec2-32-193-103-5.compute-1.amazonaws.com` (EIP-backed public DNS),
  custom origin, **HTTP only**, **port 3000**.
- **Cache behavior (single default behavior):**
  - Viewer protocol policy: `redirect-to-https` (so 443 works).
  - Allowed methods: all 7 (GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE) — login
    + REST writes need POST/PUT/DELETE/PATCH.
  - Cache policy: managed **CachingDisabled**
    (`4135ea2d-6df8-44a3-9df3-4b5a84be39ad`) — Gitea is fully dynamic/authenticated.
  - Origin request policy: managed **AllViewerExceptHostHeader**
    (`b689b0a8-53d0-40ab-baf2-68738e2966ac`) — forwards all viewer headers (except
    Host), all cookies, all query strings, so Gitea sessions/cookies work.

## Gitea ROOT_URL change
- Set `[server] ROOT_URL = https://d3ec76atxiij9a.cloudfront.net/` in the
  in-container `app.ini` (`/data/gitea/conf/app.ini`), applied via SSM Run Command
  (`AWS-RunShellScript`) on `i-06d65fadd3fbd211b` — no SSH, no local Docker.
- **Unchanged:** `HTTP_PORT = 3000` and the `0.0.0.0` listen bind. The github
  Lambda keeps reaching Gitea at `http://<eip>:3000` internally; it does not go
  through CloudFront.
- app.ini was `chown 1000:1000` + `chmod 660` after the edit (mandatory — else
  Gitea crash-loops writing OAUTH2_JWT_SECRET), then `docker restart gitea`.
- Before → after: `ROOT_URL` was empty, now the CloudFront HTTPS URL.

## Deploy path: OUT-OF-BAND (no cdk deploy)
`MahaloGiteaStack` owns the live, stateful instance + EBS volume, and the EIP
association was created out-of-band (not owned by the stack). A `cdk deploy` was
judged too risky (could reconcile/drop the out-of-band EIP association or disturb
the running instance). Per the plan's chosen path:
- The CloudFront distribution was created **out-of-band** with
  `aws cloudfront create-distribution`.
- The **equivalent CDK change is committed** to
  `infra-cdk/mahalo_infra/gitea_stack.py` (a `cloudfront.Distribution` with the
  same settings + a `GiteaCloudFrontUrl` CfnOutput) so the IaC stays truthful for
  a future clean redeploy. A code comment notes it was applied out-of-band and
  NOT `cdk deploy`-ed this task.
- A synth assertion test (`test_cloudfront_distribution_present`) was added to
  `infra-cdk/tests/test_gitea_stack.py`.

## Verification — what was and wasn't checked
Verified server-side:
- **Distribution Status = Deployed** (`aws cloudfront get-distribution`).
- **Origin healthy after the ROOT_URL change + restart**: SSM-run
  `curl http://localhost:3000/api/healthz` on the instance returned
  `{"status":"pass", ...}` (database:ping pass, cache:ping pass).
- **ROOT_URL set / HTTP_PORT intact**: the SSM script re-grepped app.ini — 
  `ROOT_URL = https://d3ec76atxiij9a.cloudfront.net/` and `HTTP_PORT = 3000`.
- **CDK change is synth-green**: `pytest tests/test_gitea_stack.py` → 8 passed
  (7 existing + the new distribution assertion).

NOT verified from here (deferred to the user's browser):
- **Edge check** (`https://d3ec76atxiij9a.cloudfront.net/api/healthz` and
  `/user/login`) could NOT be run from this VDI — it sits behind the same
  corporate proxy that blocks arbitrary outbound hosts on 443 (curl returned
  HTTP 000 / timeout). This is exactly the constraint CloudFront is meant to solve
  from the user's own network, so the final confirmation is the user opening the
  HTTPS URL in their browser and logging in as `mahalo_admin`.

## Scope kept
- Did NOT flip the github Lambda to real mode.
- Did NOT seed Gitea data.
- Did NOT change HTTP_PORT or the 0.0.0.0 bind.
- Did NOT run `cdk deploy`, and did NOT touch the instance, EBS volume, or EIP
  association.
