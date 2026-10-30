# Deploying mahalo-agentcore to a personal, unrestricted AWS account

A clone-and-run migration analysis + plan. Goal: take this repo to the user's
**own personal AWS account** (no corporate guardrails) as a **scripted,
repeatable demo** they can deploy end-to-end and present from, **without opening
the IDE/workspace** — a plain `git clone` + a documented command sequence.

> Status of this document: **ANALYSIS + PLAN only.** Nothing here has been
> deployed or changed. Findings are grounded in the repo as read on the date of
> writing; every claim is tagged **[MEASURED]** (verified from code/docs) or
> **[RECOMMENDATION]** (proposed change / judgement). Service-availability items
> that depend on the user's specific account/region are tagged **[RISK]**.

---

## Bottom line (read this first)

**The change is SMALL-to-MEDIUM, and much smaller than the corporate operational
history makes it look.** The hard engineering was already done: the CDK app is
account/region-agnostic by construction (account + region come from the
environment; see `infra-cdk/app.py`), the mock data **self-seeds** on first
Lambda call, and the frontend/agent read all their endpoints from env/CfnOutputs
rather than hardcoded values. The corporate pain (no local Docker → an EC2
builder; an SG-ingress-stripping SCP → a CloudFront-on-443 workaround for Gitea;
the two-phase hand-built frontend) is almost **entirely corporate policy, not
the app**, and collapses on an unrestricted account **with local Docker**.

What actually must change is concentrated and well-scoped:

1. **Three hardcoded live-environment values** inside `app.py` and
   `gitea_stack.py` (the previous account's CloudFront Gitea URL and the EIP host
   DNS) must become parameters/auto-derived. [MEASURED]
2. **One stale deploy script** (`scripts/builder-deploy.sh --phase frontend`)
   references a `IdentityPoolId` output that no longer exists (Cognito was removed
   in "Task 7c") and would fail fast. A fresh, Docker-local top-level
   `deploy.sh` should replace the builder path for personal use. [MEASURED]
3. **A few out-of-band manual steps** (Gitea install-lock fix, admin-password SSM
   param pre-creation, CloudFront-for-Gitea) must be folded into CDK + a bootstrap
   step so the run is hands-off. [MEASURED + RECOMMENDATION]

Rough total effort: **~3–5 focused days** for a polished clone-and-run
experience, dominated by writing/testing one `deploy.sh`, folding Gitea bootstrap
into UserData, and parameterizing the three live values. The single biggest
*risk* is not code — it is **AgentCore service availability + model access in the
user's chosen region/account** (Runtime, Gateway, Memory, and Bedrock Claude
Sonnet 4.5 enablement), which is outside this repo's control. [RISK]

If the user is willing to run the **mock GitHub path** (the default) and skip
real Gitea for the first demo, the migration is even smaller — effectively
"parameterize nothing new, run a Docker-local `cdk deploy`, script the frontend
two-phase" — because the Gitea stack and its workarounds drop out entirely.

---

## 1. Inventory: every environment-specific value and what it must become

Legend for "Current state": **ENV-CLEAN** = already env/param-driven, nothing to
do; **HARDCODED** = a literal that must be parameterized; **DOC-ONLY** = appears
only in docs (no code change needed, but update for truthfulness).

| # | Value | Example (corporate) | Where | Current state | What it must become |
|---|---|---|---|---|---|
| 1 | AWS account id | `<AWS_ACCOUNT_ID>` | `app.py` `_ACCOUNT` | **ENV-CLEAN** — read from `CDK_DEFAULT_ACCOUNT`/`AWS_ACCOUNT_ID` [MEASURED] | Nothing. Auto-derives from the caller's creds at synth/deploy. |
| 2 | Region | `us-east-1` | `app.py` `_REGION`, every stack via `self.region` | **ENV-CLEAN** — `CDK_DEFAULT_REGION`/`AWS_REGION`, default `us-east-1` [MEASURED] | Nothing; optionally expose as a config var in `deploy.sh`. |
| 3 | SSO profile | `lava` | `agent/config.py` `aws_profile` default; docs | **ENV-CLEAN in the container** — Dockerfile sets no `AWS_PROFILE`, and `strands_agent._build_bedrock_model` only passes `profile_name` if the profile exists in `available_profiles`, else uses the default chain [MEASURED] | Nothing for deploy. For local CLI use the user sets `AWS_PROFILE` or uses default creds. |
| 4 | Gitea CloudFront URL | `https://d3ec76atxiij9a.cloudfront.net` | `app.py` `_GITEA_ENV` (`GITEA_URL`, `GITEA_PUBLIC_URL`) [MEASURED] | **HARDCODED** — injected into the github Lambda only under `-c giteaMode=real` | A CDK context param / CfnParameter resolved from the Gitea stack's output (or the plain `:3000` public URL on a free account). **Key blocker for real-mode.** |
| 5 | Gitea EIP origin DNS | `ec2-32-193-103-5.compute-1.amazonaws.com` | `gitea_stack.py` `_GITEA_ORIGIN_DNS` [MEASURED] | **HARDCODED** — the CloudFront origin was created out-of-band against a live EIP | Auto-derive from the instance (`instance.instance_public_dns_name`) or drop the CloudFront front-door entirely (see §3). |
| 6 | CloudFront dist id (frontend) | `E1SXSYT3Z9NSTZ` | docs + builder notes only [MEASURED] | **DOC-ONLY** — the live dist is created by `MahaloFrontendStack`; the id is a CfnOutput, read at deploy | Nothing in code; the invalidation step in `deploy.sh` reads the id from the stack output. |
| 7 | Thin-API Function URL | `https://dkgw…lambda-url.us-east-1.on.aws/` | docs + `frontend/.env.example` placeholder [MEASURED] | **ENV-CLEAN** — `frontend/src/services/api.ts` reads `NEXT_PUBLIC_API_URL` at build; default is a placeholder, not a live URL | Nothing; `deploy.sh` injects the real `RuntimeApiUrl` CfnOutput at `next build`. |
| 8 | Frontend S3 bucket | `mahalofrontendstack-…-hgoxy5hs23db` | docs + builder notes [MEASURED] | **DOC-ONLY** — CDK auto-names the bucket; the name is read from the stack at deploy | Nothing; `deploy.sh` resolves the bucket from the stack for `s3 sync`. |
| 9 | Gitea CloudFront dist id | `E2KKG6SJXJ4K1M` | docs only [MEASURED] | **DOC-ONLY** — out-of-band dist; `gitea_stack.py` now defines its own `GiteaDistribution` | Nothing; or remove the Gitea CloudFront entirely (§3). |
| 10 | CloudFront prefix-list id | `pl-3b927c52` | docs only (the SG-stripping workaround) [MEASURED] | **DOC-ONLY** — never in code; `gitea_stack.py` uses `GiteaIngressCidr` (default `0.0.0.0/0`) | Nothing. The whole workaround is corporate-only (§3). |
| 11 | SSM param paths | `/mahalo/gitea/adapter-token`, `/mahalo/gitea/admin-password` | `app.py`, `gitea_stack.py` (as CfnParameter defaults), bootstrap scripts, `mock_service_stack.py` grant [MEASURED] | **ENV-CLEAN (names) / MANUAL (creation)** — names are parameters with sane defaults; the *values* are created out-of-band today | Keep the names; **automate creation** (CDK generates admin password; bootstrap mints + writes the adapter token). See §6. |
| 12 | Runtime ARN | `arn:aws:bedrock-agentcore:…:runtime/mahalo_agent_runtime-…` | docs; wired as `MAHALO_RUNTIME_ARN` [MEASURED] | **ENV-CLEAN** — `api_stack.py` wires it from the Runtime stack's `RuntimeArn` CfnOutput by direct construct reference | Nothing. |
| 13 | AMI ids | (none literal) | `gitea_stack.py`, `builder_stack.py` | **ENV-CLEAN** — `ec2.MachineImage.latest_amazon_linux2023(...)` resolves via an SSM public parameter at deploy [MEASURED] | Nothing. Region-portable automatically. |
| 14 | Instance types | `t3.small` (Gitea), `t4g.large` (builder) | `gitea_stack.py`, `builder_stack.py` [MEASURED] | **ENV-CLEAN-ish** — builder is a CfnParameter (`BuilderInstanceType`); Gitea is a literal | Builder: already a param. Gitea: optionally parameterize; `t3.small` is fine. |
| 15 | Bedrock model id | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | `runtime_stack.py` default `model_id`, IAM policy ARNs; `agent/config.py` | **ENV-CLEAN (value) / [RISK] (access)** — overridable via `BEDROCK_MODEL_ID`; the IAM inference-profile ARN is built from `self.region`/`self.account` [MEASURED] | Nothing in code. **But the account must have this model enabled in the region** (Bedrock model access). [RISK] |
| 16 | Repo git remote | `https://github.com/tjblavakumar/mahalo-agentcore.git` | `builder_stack.py` `_REPO_URL`, `builder-deploy.sh` `REPO_URL` [MEASURED] | **HARDCODED (builder-only)** — used only by the EC2 builder's UserData/clone | Irrelevant if the builder is dropped for personal use (§2). Else make it a CfnParameter/env. |
| 17 | Demo persona passwords | `pm123`/`dev123`/`exec123` | `frontend/src/lib/personas.ts`, `api/app/auth.py` [MEASURED] | **HARDCODED (by design)** — demo-only, security explicitly out of scope | Nothing; they are intentional demo credentials, not secrets. |
| 18 | Gitea admin password | (redacted; live value in SSM, plus a weak hardcoded default in `bootstrap.sh`) | `docs/DEMO-LOGINS.md`; `gitea/bootstrap.sh` default [MEASURED] | **MANUAL / weak default** — real value lives in SSM, pre-created out-of-band | **Generate** in CDK (Secrets Manager or an SSM SecureString) and read it in bootstrap. See §6. |

**Net:** of ~18 environment-touching values, only **#4, #5, #16** are true code
hardcodes that block a different account, and **#16 is builder-only**. Everything
else is already env/param/CfnOutput-driven or doc-only. The account id (#1) and
region (#2) — the things that usually hurt most — are already clean. [MEASURED]

---

## 2. The builder dependency: keep it, or `cdk deploy` directly?

**[MEASURED] Why the builder exists.** `MahaloBuilderStack`
(`infra-cdk/mahalo_infra/builder_stack.py`) stands up a transient arm64 Graviton
EC2 host with Docker + the full toolchain, reached over SSM. It exists purely
because the corporate **WorkSpaces VDI has no nested virtualization → no local
Docker**, and two deploys need Docker:

- `MahaloRuntimeStack` builds the **linux/arm64** agent image
  (`agent/Dockerfile` is `FROM --platform=linux/arm64 python:3.13-slim`) via
  `AgentRuntimeArtifact.from_asset(..., platform=LINUX_ARM64)` under
  `-c buildImage=1`.
- `MahaloApiStack` bundles the thin-API Lambda deps with
  `BundlingOptions` targeting `manylinux2014_aarch64` (the Lambda runs on
  `Architecture.ARM_64`).

**[RECOMMENDATION] Drop the builder for personal use; deploy from the user's
machine.** On a personal laptop/desktop **with Docker installed**, both Docker
steps run locally, so the entire builder stack and its SSM dance are unnecessary.
The user runs `cdk deploy` directly. This removes an always-on EC2, the
`AdministratorAccess` builder role, and the most error-prone part of the runbook.

The two paths:

| | **Direct (recommended)** | **Builder (corporate legacy)** |
|---|---|---|
| Prereq | Docker Desktop/Engine on the user's machine | Nothing local; EC2 provides Docker |
| Flow | `MAHALO_BUILD_IMAGE=1 cdk deploy …` locally | deploy builder → SSM in → `builder-deploy.sh` |
| Cost | none extra | one always-on `t4g.large` until torn down |
| Blast radius | user's own creds | a broad `AdministratorAccess` instance role |
| Keep for personal? | **Yes** | **No** — delete `MahaloBuilderStack` from `app.py` (or just never deploy it) |

**[MEASURED] The arm64 catch on an x86 machine.** The agent image and the thin-API
wheels are **arm64 (Graviton)**. If the user's personal machine is **Apple
Silicon**, this is native — no issue. If it is an **x86_64** box, building
linux/arm64 needs **QEMU emulation via Docker buildx** (`docker buildx` + a
`binfmt`/QEMU setup). Two concrete options:

- **[RECOMMENDATION-A] Keep arm64, build with buildx emulation.** Ensure
  `docker buildx` is available and a multi-arch builder is bootstrapped
  (`docker run --privileged tonistiigi/binfmt --install arm64`, then
  `docker buildx create --use`). CDK's `from_asset(platform=LINUX_ARM64)` and the
  `--platform manylinux2014_aarch64` pip bundling then work on x86 via emulation.
  Slower builds (minutes), but zero code change. This is the lowest-risk option
  because it keeps the exact Graviton runtime the agent was validated on.
- **[RECOMMENDATION-B] Switch the Runtime + thin API to x86_64.** Change
  `agent/Dockerfile` to `linux/amd64`, `runtime_stack.py` to
  `Platform.LINUX_AMD64`, `api_stack.py` to `Architecture.X86_64` +
  `manylinux2014_x86_64`. Faster native builds on an x86 machine, but a real code
  change and it diverges from the validated Graviton path. **[RISK]** AgentCore
  Runtime's container contract is documented (in the installed CDK L1 docstring,
  per `agent/Dockerfile`) as **arm64**; confirm amd64 is accepted before relying
  on B. Given that uncertainty, **prefer A** unless the user specifically wants
  x86 and can verify Runtime accepts it.

> If the user has no Docker at all and cannot install it, the builder path is the
> fallback — but that reintroduces exactly the complexity we are trying to shed.
> For a personal unrestricted account, installing Docker is the right move.

---

## 3. Corporate workarounds that collapse on an unrestricted account

**[MEASURED] The SG-ingress auto-stripping.** The corporate account runs an SCP
that strips `0.0.0.0/0` ingress on non-standard ports within seconds (documented
in `docs/CONTINUATION.md`, scoped to CloudFront prefix list `pl-3b927c52`). That
is why Gitea could not simply be exposed on `:3000` and had to be fronted by
CloudFront on 443, with the github Lambda reaching it via the HTTPS URL.

**[RECOMMENDATION] On a personal account this policy does not exist**, so:

- **Expose Gitea directly on `:3000`.** `gitea_stack.py` already opens `3000`
  via the `GiteaIngressCidr` parameter (default `0.0.0.0/0`) and emits
  `GiteaPublicUrl` (`http://<public-dns>:3000`). The browser and the github
  Lambda can both use that URL directly. No CloudFront needed.
- **Drop (or keep optional) the Gitea `GiteaDistribution`.** The CloudFront
  front-door in `gitea_stack.py` was **created out-of-band and never
  `cdk deploy`-ed** (its origin DNS `_GITEA_ORIGIN_DNS` is a hardcoded EIP host,
  value #5). For personal use, either delete that block or make it opt-in; this
  also removes hardcode #5 and the `GITEA_URL`/`GITEA_PUBLIC_URL` hardcodes (#4)
  because `giteaMode=real` can point at `GiteaPublicUrl` instead.

**[MEASURED → RECOMMENDATION] Which out-of-band steps fold back into CDK:**

| Out-of-band step today | Fold into CDK / bootstrap? | How |
|---|---|---|
| Gitea CloudFront dist created via `aws cloudfront create-distribution` | **Remove** (not needed) or keep as the already-present `GiteaDistribution` construct with an auto-derived origin | Delete `_GITEA_ORIGIN_DNS`; if kept, read origin from `instance.instance_public_dns_name` |
| Instance role missing SSM perms (fixed by hand, per CONTINUATION gotcha #1) | **Fold in** | Add `AmazonSSMManagedInstanceCore` + `ssm:PutParameter` on `/mahalo/gitea/*` to the Gitea instance role in `gitea_stack.py` |
| Gitea install-lock / `app.ini` secret patch (manual on the host) | **Fold into UserData** | Run `gitea/aws-host-bootstrap.sh` from UserData after the container is healthy (it already does the install-lock + uid-1000 chown correctly) |
| SSM param `/mahalo/gitea/admin-password` pre-created by hand | **Fold in** | Generate in CDK (Secrets Manager / SSM SecureString) — §6 |
| EIP allocation + association (out-of-band) | **Optional** | A personal account can skip the EIP; the public DNS is stable enough for a demo, or add an `ec2.CfnEIP` + association in-stack if durability matters |
| Manual `aws s3 sync` + CloudFront invalidation for the frontend | **Script** | `deploy.sh` does the two-phase build + sync + invalidate (§4) |

What **stays** inherently a step (not a defect): the **Gitea first-admin via CLI**
(`gitea admin user create` can only create the first admin via the CLI, not the
REST API — noted in `gitea/bootstrap.sh`), and **minting the adapter token** (only
returned at creation). Both are already scripted in
`gitea/aws-host-bootstrap.sh`; the fix is to *invoke* them from UserData rather
than by hand.

---

## 4. The manual frontend deploy → one scripted two-phase flow

**[MEASURED] Why it is two-phase.** The frontend is a Next.js 16 **static export**
(`next.config.ts` `output: "export"`), and `frontend/src/services/api.ts` reads
`NEXT_PUBLIC_API_URL` **at build time** (baked into the static bundle). So the
backend must be deployed first to know the thin-API Function URL, then the
frontend is built with that URL, then synced to S3 and the CloudFront cache
invalidated. `MahaloFrontendStack` gates the `BucketDeployment` behind
`-c buildFrontend=1` so `cdk synth` stays Docker-free.

**[MEASURED] The existing script is buggy for the current code.**
`scripts/builder-deploy.sh` `phase_frontend` still:

- reads `IdentityPoolId` from `MahaloFrontendStack` and **fails fast** on
  `: "${IDENTITY_POOL_ID:?…}"`, but **Cognito/the identity pool was removed in
  "Task 7c"** — `frontend_stack.py` has no identity pool and emits no
  `IdentityPoolId`. So the phase cannot succeed as written.
- exports `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID`, which the current
  `api.ts`/`.env.example` no longer consume.
- passes `--parameters FrontendOrigin=…` to `MahaloApiStack`, but `api_stack.py`
  CORS is now a wildcard (`allowed_origins=["*"]`) with **no `FrontendOrigin`
  parameter** — so that `--parameters` would error.

This matches `docs/CONTINUATION.md`, which repeatedly notes the frontend was
**built + synced by hand** and `--phase frontend` is buggy. **The script is stale
relative to the Task 7c simplification.** [MEASURED]

**[RECOMMENDATION] Replace it with a clean two-phase block in a top-level
`deploy.sh`** (Docker-local, no builder, no Cognito):

1. `MAHALO_BUILD_IMAGE=1 cdk deploy MahaloRuntimeStack MahaloApiStack
   --require-approval never --outputs-file out.json` → capture
   `RuntimeApiUrl`.
2. `cdk deploy MahaloFrontendStack --exclusively` (creates bucket + CloudFront)
   → capture `FrontendUrl` + the bucket name + the distribution id (from the
   stack resources).
3. `cd frontend && npm ci && NEXT_PUBLIC_API_URL=$RUNTIME_API_URL
   NEXT_PUBLIC_AWS_REGION=$AWS_REGION npm run build` → produces `frontend/out/`.
4. `cdk deploy MahaloFrontendStack --exclusively -c buildFrontend=1` (uploads
   `out/` via the `BucketDeployment`, which also invalidates `/*`).
   - Because the `BucketDeployment` already carries `distribution` +
     `distribution_paths=["/*"]`, the CloudFront invalidation is automatic — no
     separate `aws cloudfront create-invalidation` needed, unlike the old manual
     path. [MEASURED from `frontend_stack.py`]

No `IdentityPoolId`, no `FrontendOrigin` parameter, no `NEXT_PUBLIC_COGNITO_*`.

---

## 5. Self-contained clone-and-run

### Prerequisites on the user's machine [RECOMMENDATION, grounded in manifests]

| Tool | Version | Why (evidence) |
|---|---|---|
| AWS CLI v2 | latest | creds for the personal account (`aws configure sso` or keys); CfnOutputs, S3 sync, SSM |
| AWS credentials | — | an IAM identity/role with rights to deploy CFN/CDK + Bedrock. Unrestricted personal account assumed |
| Node.js | **24.x** | `frontend` is Next.js `16.3.3` (`frontend/package.json`); the builder toolchain pins Node 24 |
| Python | **3.13** | CDK app + lambdas target `python3.13` (`mock_service_stack.py`, `api_stack.py`); `agent/Dockerfile` is `python:3.13-slim` |
| CDK CLI (`aws-cdk`) | **2.1145.0** | pinned in `builder_stack.py` `_CDK_CLI_VERSION` to match `aws-cdk-lib>=2.251,<3`; use this to avoid CLI/lib drift |
| Docker | Engine/Desktop; **buildx** if x86 | the Runtime image + thin-API bundle (see §2) |
| `pip`/`venv` (or `uv`) | — | `infra-cdk/requirements.txt`, `agent/requirements.txt`, `api/requirements.txt` |

### The single flow (clone → demo), no IDE

A top-level **`deploy.sh`** (to be written — it does not exist yet) that runs:

```
git clone <repo> && cd mahalo-agentcore
cp deploy.config.example  deploy.config      # AWS_REGION, ADMIN_CIDR, GITEA_MODE=mock|real
./deploy.sh bootstrap    # cdk bootstrap aws://<acct>/<region> (idempotent)
./deploy.sh backend      # 4 Mock* + Gateway + MemoryIdentity + Dashboard  (no Docker)
./deploy.sh runtime-api  # Runtime image + thin-API bundle                 (Docker)
./deploy.sh frontend     # two-phase build + sync + auto-invalidate        (§4)
./deploy.sh gitea        # OPTIONAL, GITEA_MODE=real: Gitea EC2 + bootstrap + seed (§6)
./deploy.sh outputs      # print FrontendUrl + thin-API URL + Gitea URL
```

- **Mock data needs NO seed step.** [MEASURED] The mock Lambdas self-seed: on
  first invocation `handler.py` calls `store.ensure_seeded()`
  (`tools-lambdas/common/dynamo_store.py` — lazy, sentinel-guarded, idempotent),
  so Jira/Confluence/ServiceNow/GitHub-mock populate themselves. The demo works
  the moment the backend is up.
- **Teardown:** `./deploy.sh destroy` → `cdk destroy --all` (keep CDKToolkit).

### Everything currently assumed interactive / from the workspace [MEASURED]

- `aws sso login --profile lava` + hourly cred re-export (`aws configure
  export-credentials`) — corporate SSO token quirk. On a personal account the
  user configures creds **once**; no re-export dance.
- The whole **builder SSM session** (start-session / send-command / poll) — gone
  with the builder (§2).
- The **manual frontend build + S3 sync + CloudFront invalidation** — scripted
  (§4).
- The **manual Gitea install-lock fix + token mint + SSM param pre-creation** —
  folded into UserData + CDK (§3, §6).
- Reading CfnOutputs by hand to wire the next step — `deploy.sh` captures them via
  `--outputs-file` and threads them through (the existing script already shows the
  pattern in `outputs_get`/`record_output`).

---

## 6. Secrets & seed automation

**[MEASURED] Today.** The Gitea admin password and adapter token live in SSM
SecureStrings (`/mahalo/gitea/admin-password`, `/mahalo/gitea/adapter-token`),
**pre-created out-of-band**; `gitea_stack.py` only references their *names*
(CfnParameters). `aws-host-bootstrap.sh` reads the admin password from SSM, mints
the adapter token, and writes it back. The `--phase gitea` script pre-flights both
params and **fails fast if absent** — i.e. a fresh account has nothing there yet.
The seed scripts (`gitea/seed_gitea.py` for 5 repos/branches/PRs; `bootstrap.sh`
for the single seed repo) run on the host against `localhost:3000`.

**[RECOMMENDATION] For a fresh account, make it hands-off:**

1. **Generate the admin password in CDK.** Add an
   `aws_secretsmanager.Secret` (or an SSM SecureString via a small custom
   resource) in `gitea_stack.py` with `generate_secret_string`, instead of
   requiring a pre-created param. Grant the instance role read on it. The
   bootstrap reads it the same way it reads SSM today. Output a retrieval command,
   never the value. (Keep the existing CfnParameter as an override for operators
   who want to supply their own.)
2. **Mint + store the adapter token in bootstrap, from UserData.** Already
   implemented in `aws-host-bootstrap.sh` step 3–5 (mint token → `ssm put-parameter
   --type SecureString /mahalo/gitea/adapter-token`). Just **invoke it from
   UserData** after `curl /api/healthz` succeeds, and ensure the instance role has
   `ssm:PutParameter` on `/mahalo/gitea/*` (CONTINUATION gotcha #1 — fold the grant
   into CDK).
3. **Seed as part of the run.** After bootstrap, UserData (or `deploy.sh gitea`
   via SSM run-command) runs `GITEA_TOKEN=<minted> python3 gitea/seed_gitea.py` to
   create the 5 repos/branches/PRs, then `gitea/verify_gitea.py` for evidence.
4. **Mock seed:** nothing to do — lazy self-seed (§5). [MEASURED]
5. **Flip github to real mode cleanly.** Point `app.py` `_GITEA_ENV`
   `GITEA_URL`/`GITEA_PUBLIC_URL` at the Gitea stack's `GiteaPublicUrl` output
   (a CDK context param), replacing hardcode #4, and deploy
   `MahaloMockGithubStack -c giteaMode=real`.

**[RISK]** `gitea/bootstrap.sh` has a weak hardcoded default admin password, and
`DEMO-LOGINS.md` prints the live admin password in plain text. For a
personal account exposed on the public internet (Gitea `:3000`, thin-API
`AuthType=NONE`), generate a strong password (step 1) and consider narrowing
`GiteaIngressCidr` to the user's IP rather than `0.0.0.0/0`.

---

## 7. Cost & teardown

**[MEASURED] Always-on cost drivers on a personal account:**

- **Gitea EC2** (`t3.small`, AL2023) + its 20 GiB gp3 EBS — runs continuously if
  `GITEA_MODE=real`. **Skip entirely for the mock demo** → near-zero standing
  cost.
- **Builder EC2** (`t4g.large`) — **eliminated** by the direct-deploy
  recommendation (§2).
- **AgentCore Runtime** — hosts the container; `LifecycleConfiguration`
  (`idle_runtime_session_timeout=15min`, `max_lifetime=8h`) means it is not a
  classic always-on server, but has associated cost while sessions are warm.
- **No NAT gateway** — both the Gitea and builder VPCs use `nat_gateways=0`
  (public subnet only), so no NAT hourly charge. [MEASURED]
- **DynamoDB** tables are `PAY_PER_REQUEST` — negligible at demo volume.
- **ECR residual:** the arm64 agent image lands in the shared CDK bootstrap asset
  repo and is **not** GC'd by `cdk destroy MahaloRuntimeStack` (cents/month) — per
  the runbook's ECR note. [MEASURED]
- A potential **keep-warm EventBridge** (backlog follow-up #3 in CONTINUATION) —
  not built yet; would add tiny periodic-invoke cost if it lands. [MEASURED as
  "not implemented"]

**[MEASURED] Teardown.** `cdk destroy --all` works; most resources are
`RemovalPolicy.DESTROY`. **Stateful gotchas:**

- **Gitea EBS** is `DESTROY` by default (repos re-seedable) but flippable to
  `RETAIN` via `RetainGiteaData=true` — a `RETAIN` volume **survives destroy and
  must be deleted by hand** to stop EBS cost.
- **DynamoDB tables** (`mahalo-mock-*`, `mahalo-dashboards`) are `DESTROY` — data
  is lost on teardown (fine; it re-seeds). A redeploy gets a **new Gateway id/MCP
  URL** each time (CONTINUATION note), which is why the Runtime reads it from a
  CfnOutput rather than a constant — no manual fix needed. [MEASURED]
- `auto_delete_objects=True` on the frontend bucket means `cdk destroy` empties it
  via a custom resource; occasionally needs a re-run (runbook note).

---

## 8. Migration checklist with effort (S/M/L) and risks

Ordered by dependency. S ≈ <½ day, M ≈ ½–1½ days, L ≈ 2+ days.

| # | Workstream | What | Effort | Notes / risk |
|---|---|---|---|---|
| W1 | **Parameterize the 3 live hardcodes** | `app.py` `_GITEA_ENV` URLs (#4) + `gitea_stack.py` `_GITEA_ORIGIN_DNS` (#5) → context params / auto-derived from `GiteaPublicUrl`; make the builder `_REPO_URL` (#16) irrelevant | **S** | Low risk. Account/region already clean, so this is the whole "portability" code change |
| W2 | **Drop the builder for personal use** | Remove `MahaloBuilderStack` from the default `app.py` synth (or just never deploy it); document Docker-local deploy | **S** | Low risk; purely subtractive. Keep the stack file for anyone VDI-bound |
| W3 | **Fold Gitea out-of-band steps into CDK + UserData** | Instance role SSM perms + `ssm:PutParameter`; run `aws-host-bootstrap.sh` from UserData; drop/soften the CloudFront front-door; expose `:3000` directly | **M** | **[RISK]** install-lock + uid-1000 `app.ini` ownership is fiddly (CONTINUATION gotcha #2); the script handles it but UserData timing/health-wait must be right |
| W4 | **Script the frontend two-phase** | New `deploy.sh frontend`: backend → capture `RuntimeApiUrl` → `npm build` → `-c buildFrontend=1` (auto-invalidates). Delete the stale Cognito/`FrontendOrigin`/`IdentityPoolId` logic | **M** | Fixes the known-buggy `--phase frontend`. Low risk; mirrors the working manual steps |
| W5 | **Secrets & seed automation** | Generate Gitea admin password in CDK; mint+store adapter token in bootstrap from UserData; run `seed_gitea.py` + `verify_gitea.py`; mock self-seeds (nothing to do) | **M** | **[RISK]** public-internet exposure of generated creds — strengthen password + optionally narrow `GiteaIngressCidr` |
| W6 | **Top-level `deploy.sh` + README/runbook** | One script (`bootstrap`/`backend`/`runtime-api`/`frontend`/`gitea`/`outputs`/`destroy`), config file, and a clone-and-run README. Reuse `outputs_get`/`record_output` patterns | **M→L** | The main net-new artifact. Must be OS-honest (user is on Windows per env; provide bash for Git-Bash/WSL/mac, or a PowerShell sibling) |
| W7 | **arm64 build enablement (if x86 host)** | Document buildx/binfmt setup (option A) OR switch Runtime+API to x86 (option B) | **S** (A) / **M** (B) | **[RISK]** option B needs confirmation that AgentCore Runtime accepts amd64; prefer A |
| W8 | **Verify end-to-end + update docs** | Fresh-account dry-run; update `DEMO.md`/`DEMO-LOGINS.md`/`CONTINUATION.md` to drop corporate-only values and point at the new flow | **M** | Can only be fully done by the user against their account |

**Top risks, ranked:**

1. **[RISK] AgentCore service + model availability in the user's region/account.**
   Runtime, Gateway, and Memory are relatively new Bedrock AgentCore services with
   regional availability and possibly per-account quotas; Claude Sonnet 4.5 must be
   **enabled for Bedrock model access** in that region. This is outside the repo
   and cannot be asserted from code — **verify first** (`us-east-1` is safest). If
   a service/model is unavailable in the chosen region, deploy in `us-east-1` or
   wherever AgentCore + the model are GA.
2. **[RISK] arm64 image build on x86 personal hardware** (W7) — emulation is
   slower and occasionally flaky; Apple Silicon avoids it entirely.
3. **[RISK] Gitea install-lock bootstrap reliability** (W3/W5) — the `app.ini`
   secret-patch + uid-1000 ownership is the single most finicky host step;
   mitigated by the already-written `aws-host-bootstrap.sh`, but UserData health
   gating must be solid. Skipping real Gitea (mock path) removes this risk for a
   first demo.
4. **[RISK] Public exposure of `AuthType=NONE` thin API + open Gitea `:3000`** on a
   personal account reachable from the internet — acceptable for a short demo,
   but narrow CIDRs / tear down promptly.

---

## Evidence index (where each finding came from)

- Account/region env-derivation: `infra-cdk/app.py` (`_ACCOUNT`, `_REGION`, `_ENV`).
- Hardcoded Gitea URLs/EIP: `app.py` `_GITEA_ENV`; `gitea_stack.py`
  `_GITEA_ORIGIN_DNS`, `GiteaDistribution`.
- arm64 image + bundling: `agent/Dockerfile`; `runtime_stack.py`
  (`from_asset(platform=LINUX_ARM64)`); `api_stack.py` (`BundlingOptions`,
  `Architecture.ARM_64`).
- Builder rationale + SSM-only access: `builder_stack.py`;
  `docs/.agents/tasks/task7b-ec2-builder-runbook.md`.
- Stale frontend phase (Cognito/`IdentityPoolId`/`FrontendOrigin`):
  `scripts/builder-deploy.sh` `phase_frontend` vs. current `frontend_stack.py`
  (no identity pool) and `api_stack.py` (wildcard CORS, no `FrontendOrigin` param).
- Frontend build-time API URL + static export: `frontend/src/services/api.ts`,
  `frontend/.env.example`, `frontend/next.config.ts`, `frontend/package.json`.
- Lazy mock self-seed: `tools-lambdas/common/dynamo_store.py`,
  `tools-lambdas/github/handler.py` (`store.ensure_seeded()`), `*/routes.py`
  `seed_items()`.
- Secrets/seed: `gitea/aws-host-bootstrap.sh`, `gitea/bootstrap.sh`,
  `gitea/seed_gitea.py`, `gitea/verify_gitea.py`; `gitea_stack.py` SSM-name params.
- Corporate SG-stripping + CloudFront-on-443 + two-phase frontend history:
  `docs/CONTINUATION.md`.
- Cost/teardown + stack list: `docs/DEMO.md` §8–§9; `gitea_stack.py`
  (`RetainGiteaData`), `mock_service_stack.py`/`dashboard_stack.py`
  (`RemovalPolicy.DESTROY`).
- Agent region/profile container-safety: `agent/config.py`,
  `agent/strands_agent.py` (`available_profiles` check), `agent/Dockerfile`
  (no `AWS_PROFILE`).

---

## 9. Daily cost estimate — running the demo ~8 hours/day on a personal account

> **Caveat up front:** this is an ESTIMATE, not a bill. Rates below are published
> figures (late 2026, us-east-1-class); the biggest uncertainty is AgentCore
> Runtime consumption for THIS specific agent, which depends on vCPU/memory sizing
> and how long sessions stay warm — the deployment analysis could not derive that
> from code. Token counts are estimated from the latency investigation (an
> overview is a multi-turn synthesis; ~4 tool calls after the composites fix, ~21
> before). Treat the ranges as planning guidance; get a real number from Cost
> Explorer after a measured demo day.

### Key insight: usage-billed, not wall-clock
AgentCore Runtime and Lambda bill for ACTUAL usage, not for the environment being
"up." Running 8 hours does NOT mean 8 hours of Runtime compute — the Runtime bills
only while actively handling a request, plus warm/idle session time (capped by the
15-min idle session timeout). So daily cost is driven far more by HOW MANY queries
you run than by how long the stack is deployed. The standing infra (DynamoDB,
Lambda, S3, CloudFront) is cents; the EC2 for Gitea only exists in real-Gitea mode.

### Published rates used (verified via web search, late 2026)
- AgentCore Runtime (serverless microVM): ~$0.0895 per vCPU-hour + ~$0.00945 per
  GB-hour, per-second granularity.
  (https://aws.amazon.com/bedrock/agentcore/pricing/ ;
  https://builder.aws.com/content/3JpfQcT4rM40BW7AdJTPshIv5Ht/building-ai-agents-on-amazon-bedrock-agentcore-the-real-bill-component-by-component)
- Bedrock Claude Sonnet 4.5: $3.00 / 1M input tokens, $15.00 / 1M output tokens;
  cache reads ~$0.30/1M. (https://www.requesty.ai/models/bedrock/claude-sonnet-4-5)
- EC2 t3.small ~$0.0208/hr; DynamoDB on-demand negligible at demo volume; NO NAT
  (public-subnet VPCs); Lambda/S3/CloudFront pennies at demo scale.
- Content from external sources was rephrased for compliance with licensing restrictions.

### Scenario A — light demo (~30–50 agent queries across the 8h)
| Component | Estimate/day |
|---|---|
| AgentCore Runtime compute (query bursts + idle windows) | ~$0.30–1.00 |
| Bedrock Sonnet 4.5 tokens (~40 queries, ~30–60K tokens/query mixed in/out) | ~$2–6 |
| AgentCore Memory + Gateway | ~$0.10–0.50 |
| Gitea EC2 t3.small × 8h (ONLY if real-Gitea mode) | ~$0.17 |
| DynamoDB / Lambda / S3 / CloudFront | ~$0.10 |
| **Rough total** | **~$3–8 / day** |

### Scenario B — heavy (continuous testing, 150–250 queries, many overviews)
| Component | Estimate/day |
|---|---|
| AgentCore Runtime compute | ~$1–3 |
| Bedrock tokens (the dominant driver) | ~$10–25 |
| Memory + Gateway | ~$0.50–1 |
| Gitea EC2 + the rest | ~$0.30 |
| **Rough total** | **~$12–30 / day** |

### Headline
A typical 8-hour demo day is roughly **$3–8**, and realistically **under ~$30**
even under heavy testing. The single biggest lever is **Bedrock token spend**
(Sonnet 4.5 output at $15/1M), NOT infrastructure — the EC2/DynamoDB/Lambda
footprint is cents. Running the MOCK path (skip real Gitea) removes the EC2 + EBS
and drops standing cost to near-zero between queries.

### Caveats / things that move the number
- AgentCore Runtime consumption for this agent is the biggest estimate uncertainty
  (modeled from vCPU/GB-hour rates + typical bursts, not a measured run).
- Token counts are estimated; your real query mix moves the bill up or down.
- Idle cost: the 15-min idle session timeout means short warm billing windows after
  each query even when you're not actively asking (minor, but nonzero).
- If the keep-warm feature (latency follow-up #3, in progress) ships, a 10-min ping
  cadence adds a small steady token + Runtime trickle during the window — on a
  personal account, lower the cadence or disable it to save cost.
- New AWS accounts get up to ~$200 in AgentCore free-tier credits, likely covering
  many demo days.

### To get a REAL number
Deploy the mock path, run your actual demo script for one day, and read AWS Cost
Explorer / a daily budget alert. That converts every estimate above into a measured
figure. Recommend setting an AWS Budgets alert (e.g. $20/day) before the first run.
