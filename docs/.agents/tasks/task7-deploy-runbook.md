# Task 7 — Deploy runbook (DEFERRED operator steps)

**None of this is run in the offline gate.** The automated gate is synth + unit
tests only (`cdk synth --all` Docker-free / cred-free producing 10 templates,
`pytest tests -q`, `pytest tools-lambdas/tests -q`, and the frontend
`npm ci/lint/test/build`). The live wiring below — creating SSM secrets, `cdk
deploy`, Gitea bootstrap + repo seed, flipping the github Lambda to `real`, the
ordered frontend deploy, and the end-to-end smoke test — is a **documented
operator procedure** (design §E.4 / §D.2 / §C.3). Run it by hand, with real AWS
credentials, when standing the demo up.

All CDK commands run from `infra-cdk/` with its own `.venv` active. Windows
PowerShell: use `;` (not `&&`) and `$env:VAR="x"` for env vars.

---

## 0. Prerequisites

- The infra-cdk `.venv` is active and `cdk --version` works.
- Real AWS credentials for account `<AWS_ACCOUNT_ID>` / region `us-east-1`
  (profile `lava`), e.g. `cdk deploy ... --profile lava`.
- The account/region is bootstrapped for CDK assets
  (`cdk bootstrap` — one-time; NOT run in the offline gate).

---

## 1. Create the SSM SecureString parameters (secrets)

The stacks reference these by **name** only; create them with real values first.
Pick the same names the stacks default to (or pass overrides as CfnParameters).

```powershell
# Gitea admin password (used by the bootstrap to create the first admin).
aws ssm put-parameter --profile lava --region us-east-1 `
  --name "/mahalo/gitea/admin-password" --type SecureString `
  --value "<a-strong-password>" --overwrite

# Adapter API token placeholder — the bootstrap OVERWRITES this with the real
# minted token in step 3. Create it so the github Lambda's read-grant resolves.
aws ssm put-parameter --profile lava --region us-east-1 `
  --name "/mahalo/gitea/adapter-token" --type SecureString `
  --value "placeholder-overwritten-by-bootstrap" --overwrite
```

---

## 2. Deploy the Gitea host

```powershell
cdk deploy MahaloGiteaStack --profile lava `
  --parameters AdminCidr="<your-ip>/32"
```

- `AdminCidr` restricts SSH (22). `GiteaIngressCidr` defaults to `0.0.0.0/0` on
  3000 (protected by the Gitea API token); narrow it to a prefix list / known
  CIDR to harden.
- `RetainGiteaData=true` keeps the EBS data volume across teardown; default
  `false` wipes repos on destroy (they are re-seedable by the bootstrap).
- UserData installs Docker, mounts the gp3 data volume at `/data`, and runs
  `gitea/gitea:1.27.3` by image reference. It waits for `/api/healthz` and writes
  `/data/BOOTSTRAP_READY`.

Read the stack outputs: `GiteaPublicUrl`, `GiteaInstanceId`,
`GiteaAdapterTokenParam`.

---

## 3. Bootstrap Gitea: first admin, token, seed repo

On the instance (SSH in, or SSM Session Manager), run the ported bootstrap with
the SSM param + public URL set so it pushes the minted token to SSM:

```bash
export GITEA_URL="http://localhost:3000"
export GITEA_PUBLIC_URL="<GiteaPublicUrl from step 2>"
export GITEA_ADMIN_USER="mahalo_admin"
export GITEA_ADMIN_PASSWORD="<the password from step 1>"
export GITEA_TOKEN_SSM_PARAM="/mahalo/gitea/adapter-token"
export AWS_REGION="us-east-1"

# Run gitea/bootstrap.sh (idempotent): creates the admin via the gitea CLI,
# mints the adapter token (scopes write:repository/write:user/read:organization),
# seeds the payment-service repo, and pushes the token to the SSM SecureString.
docker run --rm \
  -e GITEA_URL -e GITEA_PUBLIC_URL -e GITEA_ADMIN_USER -e GITEA_ADMIN_PASSWORD \
  -e GITEA_TOKEN_SSM_PARAM -e AWS_REGION \
  -v /data:/data --network host \
  <gitea-bootstrap-image> /usr/local/bin/bootstrap.sh
```

Confirm Gitea is healthy and the seed repo exists:

```bash
curl -fsS "$GITEA_PUBLIC_URL/api/healthz"
curl -fsS -H "Authorization: token <token>" \
  "$GITEA_PUBLIC_URL/api/v1/repos/mahalo_admin/payment-service"
```

The bootstrap is idempotent — re-running it is safe (admin/token/repo are
reused or recreated to a usable state).

---

## 4. Flip the github Lambda to the Gitea backend

```powershell
cdk deploy MahaloMockGithubStack -c giteaMode=real --profile lava
```

- This adds `GITHUB_MODE=real` + the Gitea env (`GITEA_URL`, `GITEA_ADMIN_USER`,
  `GITEA_PUBLIC_URL`, `DEMO_DEVELOPER_ID`, `GITEA_TOKEN_PARAM`) and the SSM
  read-grant to the **github** instance ONLY; the other three mock stacks are
  unchanged.
- Point `GITEA_URL` / `GITEA_PUBLIC_URL` at the step-2 `GiteaPublicUrl`
  (update `_GITEA_ENV` in `app.py`, or override via the mechanism you prefer, to
  the real public URL before this deploy).
- The Lambda stays non-VPC and reaches Gitea over the public endpoint,
  authenticated by the SSM token resolved once at cold start.

---

## 5. Frontend deploy (ordered — the chicken-and-egg, design §D.2)

`NEXT_PUBLIC_*` are inlined at `next build`, and the browser calls the Function
URL directly (not through CloudFront). So the build needs the API URL + identity
pool id, which both exist BEFORE the bundle is built.

1. Deploy the API and read its URL:
   ```powershell
   cdk deploy MahaloApiStack --profile lava
   # Read the RuntimeApiUrl output.
   ```
2. Deploy the frontend stack WITHOUT the build flag to stand up the bucket,
   CloudFront distribution, and Cognito identity pool + role:
   ```powershell
   cdk deploy MahaloFrontendStack --profile lava
   # Read the IdentityPoolId and FrontendUrl (CloudFront domain) outputs.
   ```
3. Set the build-time env and build the static export:
   ```powershell
   cd ../frontend
   $env:NEXT_PUBLIC_API_URL="<RuntimeApiUrl>"
   $env:NEXT_PUBLIC_AWS_REGION="us-east-1"
   $env:NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID="<IdentityPoolId>"
   npm run build    # emits frontend/out/
   cd ../infra-cdk
   ```
4. Re-deploy the frontend stack WITH the build flag to upload `frontend/out`:
   ```powershell
   cdk deploy MahaloFrontendStack -c buildFrontend=1 --profile lava
   ```
5. Re-deploy the API so the Function URL CORS `allowed_origins` includes the
   CloudFront domain from step 2:
   ```powershell
   cdk deploy MahaloApiStack --profile lava `
     --parameters FrontendOrigin="<FrontendUrl>"
   ```

The CloudFront domain is stable after step 2, so steps 3–5 have no further
circular dependency. (An operator may pin a custom domain to decouple entirely.)

---

## 6. End-to-end smoke test

1. Open the CloudFront `FrontendUrl` in a browser.
2. Send a chat message. The browser fetches temp creds from the unauthenticated
   identity pool, signs a SigV4 request, and calls the Function URL directly
   (CORS preflight is answered unsigned; the signed `POST` carries the SigV4
   headers).
3. Trigger a HITL write (e.g. "open a PR on payment-service"). Approve the
   proposal card; confirm the write lands in Gitea (new branch/commit/PR visible
   at `GiteaPublicUrl`), proving browser → CloudFront static app → direct SigV4
   call → thin API → Runtime → github Lambda (real) → Gitea.

---

## Teardown

`cdk destroy` the Task-7 stacks (and the rest) to reset. The S3 bucket
(`auto_delete_objects=True`) and the Gitea EBS volume (`RemovalPolicy.DESTROY`)
are removed unless `RetainGiteaData=true` was set. Repos are re-seedable by
re-running the bootstrap (step 3) on the next stand-up.
