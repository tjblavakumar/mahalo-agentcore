# Task 7b — Operator Runbook: EC2 Docker-builder deploy path

**Audience:** the operator deploying mahalo-agentcore end-to-end from an AWS
WorkSpaces VDI that has **no local Docker** (no nested virtualization).
**Authoritative design:** `docs/.agents/tasks/task7b-design.md` (§A–§G).
**Builder script:** `scripts/builder-deploy.sh` (FEAT-002) — the flags and phases
in this runbook match that file exactly.
**Account / region / profile:** `<AWS_ACCOUNT_ID>` / `us-east-1` / SSO profile `lava`.

---

## Why this path exists

The VDI cannot run Docker, but two CDK deploys need it: the ARM64 AgentCore agent
image build+push (`MahaloRuntimeStack`) and the thin-API Lambda dependency
bundling (`MahaloApiStack`). So instead of building locally, the operator:

1. deploys a tiny, **Docker-free** CDK stack (`MahaloBuilderStack`) from the VDI
   that stands up a transient arm64/Graviton EC2 "builder" with Docker and the
   full toolchain,
2. connects to it via **SSM Session Manager** (no SSH, no inbound ports),
3. runs `scripts/builder-deploy.sh --phase all` on the builder to do the whole
   staged `cdk deploy` from inside AWS,
4. validates in the browser,
5. tears down the app stacks **from the builder**, then tears down the builder
   **from the VDI last**.

The app now has **11 CDK stacks** (the 10 app stacks + `MahaloBuilderStack`).

---

## Command-context convention (read this first)

Every command block below is labelled with the shell it runs in and the
credential it uses. They are NOT interchangeable:

- **`[VDI]`** — Windows PowerShell on the WorkSpaces VDI. Uses your `lava` SSO
  identity, so **every** `aws`/`cdk` command carries `--profile lava`.
- **`[builder]`** — Linux bash on the EC2 builder, inside the SSM shell. Uses the
  builder's **instance role**, so **no** command carries `--profile` (there is no
  `lava` profile on the builder, and `scripts/builder-deploy.sh` contains no
  `--profile` anywhere).

If you ever find yourself typing `--profile` on the builder, or omitting it on the
VDI, stop — you are in the wrong context.

---

## Step 1 — `[VDI]` authenticate

```powershell
# [VDI] PowerShell
aws sso login --profile lava
aws sts get-caller-identity --profile lava
```

The second command must print account `<AWS_ACCOUNT_ID>`. The SSO token lasts only a
few hours; if a later VDI step fails with an auth error, re-run `aws sso login
--profile lava`. (The builder does NOT use this token — it has its own instance
role — so a token expiring mid-deploy does not interrupt the builder's work.)

---

## Step 2 — `[VDI]` deploy the builder stack (Docker-free)

`MahaloBuilderStack` is pure CloudFormation (VPC, public subnet, security group
with zero ingress, arm64 AL2023 EC2 instance, instance role/profile, EBS). It
builds **no** Docker assets, so it deploys fine from the Docker-less VDI.

```powershell
# [VDI] PowerShell — from the repo root
cd infra-cdk
cdk deploy MahaloBuilderStack --profile lava
```

When it finishes, note the CfnOutputs:

- **`BuilderInstanceId`** — e.g. `i-0abc123...`; used in Step 3 for
  `start-session` / `send-command` and in Step 8 only as a blunt-terminate
  fallback.
- `BuilderPublicDns` — diagnostic only.

---

## Step 3 — `[VDI]` connect to the builder via SSM

No SSH key and no inbound port — the builder is reached only through SSM Session
Manager. **Before connecting**, give UserData time to finish the toolchain install
and the initial repo clone (it writes `/var/log/builder-ready` when done).

### Option A — interactive SSM shell (recommended for the live gate)

```powershell
# [VDI] PowerShell — replace <BuilderInstanceId> with the Step 2 output
aws ssm start-session --target <BuilderInstanceId> --profile lava --region us-east-1
```

You are now in a `[builder]` bash shell. Confirm UserData is done before Step 4:

```bash
# [builder] bash — wait for first-boot UserData to finish
cloud-init status --wait
cat /var/log/builder-ready   # prints: builder toolchain ready
```

Interactive is recommended for the live gate so you SEE the CfnOutputs as the
deploy prints them and can react.

### Option B — single unattended kickoff (no interactive shell)

Instead of opening a shell, fire the whole deploy from the VDI in one command.
UserData already cloned the repo to `/home/ssm-user/mahalo-agentcore` and chowned
it to `ssm-user` at first boot, so the script path exists on a fresh builder.
**Wait for `/var/log/builder-ready` (or `cloud-init status --wait`) first.**

```powershell
# [VDI] PowerShell — replace <BuilderInstanceId>; runs builder-deploy.sh --phase all
aws ssm send-command --instance-ids <BuilderInstanceId> --profile lava --region us-east-1 `
  --document-name "AWS-RunShellScript" `
  --parameters 'commands=["sudo -u ssm-user bash /home/ssm-user/mahalo-agentcore/scripts/builder-deploy.sh --phase all"]' `
  --timeout-seconds 3600
```

Poll the command with `aws ssm list-command-invocations --command-id <id>
--details --profile lava --region us-east-1` to read status/output. If you use
Option B, you have effectively performed Step 4 — skip to Step 6 (validation).

---

## Step 4 — `[builder]` run the full staged deploy

In the interactive SSM shell from Step 3 Option A (instance-role creds — **no
`--profile`**):

```bash
# [builder] bash — the full staged deploy
bash ~/mahalo-agentcore/scripts/builder-deploy.sh --phase all
```

`--phase all` runs these phases in order (matches `scripts/builder-deploy.sh`):

1. **`toolchain`** — verify/install git, Docker (invoked via `sudo`), Node 24,
   Python 3.13, AWS CLI v2, the pinned CDK CLI; re-clone/update the repo
   idempotently; create `infra-cdk/.venv` and `agent/.venv`.
2. **`backend`** — `cdk bootstrap` check, then deploy the 6 Docker-free backend
   stacks (`MahaloMemoryIdentityStack`, `MahaloGatewayStack`, and the four
   `MahaloMock*Stack`). Captures `MemoryId`, `GatewayMcpUrl`.
3. **`runtime-api`** — deploy `MahaloRuntimeStack` + `MahaloApiStack` (the two
   Docker builds: the ARM64 agent image built natively on Graviton, and the API
   Lambda dependency bundle). Captures `RuntimeArn`, `RuntimeApiUrl`.
4. **`frontend`** — the two-phase build with the ordering the script enforces:
   deploy `MahaloFrontendStack --exclusively` (infra only) → read `IdentityPoolId`
   + `FrontendUrl` → `npm ci` + `npm run build` with the `NEXT_PUBLIC_*` vars
   inlined → re-deploy `MahaloFrontendStack --exclusively -c buildFrontend=1`
   (uploads `frontend/out/`) → **last**, re-deploy `MahaloApiStack -c buildImage=1
   --parameters FrontendOrigin=<FrontendUrl>` so browser CORS points at the live
   CloudFront domain. `MAHALO_BUILD_IMAGE=1` stays exported throughout, so the API
   keeps its bundled deps on that final CORS re-deploy.

`--phase all` does **not** run `gitea` (it is opt-in, Step 5). The script is
idempotent — on any transient failure, re-run the exact same command and it
converges. At the end it prints a consolidated CfnOutputs summary (see Step 5's
output note / Step 6).

> `--phase all` expands to `toolchain → backend → runtime-api → frontend`. You can
> also run any single phase, e.g. `bash ~/mahalo-agentcore/scripts/builder-deploy.sh
> --phase runtime-api`, to resume after a failure.

---

## Step 5 — `[builder]` optional: deploy real-GitHub Gitea

Only if you want to exercise the **real** GitHub backend instead of the default
mock. This deploys the Gitea host **only** and stops — the mock→real flip is owned
by `docs/.agents/tasks/task7-deploy-runbook.md §3-5`.

```bash
# [builder] bash — --admin-cidr is REQUIRED for this phase
bash ~/mahalo-agentcore/scripts/builder-deploy.sh --phase gitea --admin-cidr <your-ip>/32
```

`--admin-cidr` has no default; the script fails fast if it is missing. The phase
also pre-flights the two SSM SecureString params (`/mahalo/gitea/adapter-token`,
`/mahalo/gitea/admin-password`) and fails fast pointing at
`task7-deploy-runbook.md §1` if they are absent. For the first demo, skip this
step — the mock GitHub path is the default.

---

## Retrieve the CfnOutputs

The deploy writes per-phase `--outputs-file` JSON under `/tmp` and a consolidated
`/tmp/mahalo-outputs.env` that `builder-deploy.sh` echoes to the shell at the end
of the run. The values you need for validation:

```bash
# [builder] bash — the consolidated capture
cat /tmp/mahalo-outputs.env
```

Key outputs:

- **`RuntimeApiUrl`** (`MahaloApiStack`) — the thin-API Function URL.
- **`IdentityPoolId`** (`MahaloFrontendStack`) — the Cognito unauthenticated
  Identity Pool that the browser uses for SigV4.
- **`FrontendUrl`** (`MahaloFrontendStack`) — the **CloudFront URL** you open in
  the browser for Step 6.
- (`MemoryId`, `GatewayMcpUrl`, `RuntimeArn` are also captured; `GiteaPublicUrl` /
  `GiteaInstanceId` appear only if you ran Step 5.)

---

## Step 6 — `[VDI, browser]` validate at the CloudFront URL

Open the `FrontendUrl` (the CloudFront URL) in a browser on the VDI and exercise:

1. **READ** — ask "list my repositories". Expect the seeded repos including
   **`payment-service`** (routed browser → thin API → Runtime → Gateway → github
   Lambda → DynamoDB).
2. **WRITE with the two-call propose→approve HITL** — ask to create a branch or a
   story. The agent returns a **proposal card** and writes nothing yet (first
   `/chat` call). Click **approve** → the second `/chat/approve` call executes the
   write once. Then **reject** a fresh proposal and confirm **nothing is written**
   (follow up with a read to verify).
3. **Session memory** — confirm cross-message context persists within the session
   (a follow-up question that relies on the previous turn resolves correctly).

Known, expected quirks (not bugs): a github write keyed by repo **name** may 404
against the mock (it keys by repo **id**) — the HITL gate still fires correctly.

---

## Step 7 — `[builder]` tear down the app stacks

Do this **from the builder** (instance-role creds, no `--profile`), BEFORE
touching the builder itself. One command — CDK computes the reverse-dependency
delete order automatically:

```bash
# [builder] bash
cd ~/mahalo-agentcore/infra-cdk && source .venv/bin/activate && \
cdk destroy MahaloFrontendStack MahaloApiStack MahaloRuntimeStack \
  MahaloGiteaStack MahaloMemoryIdentityStack MahaloGatewayStack \
  MahaloMockJiraStack MahaloMockConfluenceStack \
  MahaloMockGithubStack MahaloMockServicenowStack --force
```

`--force` suppresses the interactive confirmation prompt but does **not** suppress
dependency errors. `cdk destroy` is idempotent (already-deleted stacks are
skipped), so **on ANY failure, re-run the exact same command** — it converges
(this also clears the `BucketDeployment` / `auto_delete_objects` custom-resource
retry hiccup on CloudFront+S3 deletes).

If a re-run still fails, fall back to leaf-first groups (dependents before their
dependencies):

```bash
# [builder] bash — leaf-first fallback
cdk destroy MahaloFrontendStack --force          # depends on Api
cdk destroy MahaloApiStack --force               # depends on Runtime
cdk destroy MahaloRuntimeStack --force           # depends on Memory (+ Gateway)
cdk destroy MahaloMemoryIdentityStack MahaloGatewayStack --force
cdk destroy MahaloMockJiraStack MahaloMockConfluenceStack \
  MahaloMockGithubStack MahaloMockServicenowStack --force
cdk destroy MahaloGiteaStack --force             # independent; any time
```

> **ECR bootstrap-repo residual cost note:** the ARM64 agent image built by
> `from_asset` is pushed to the shared **CDK bootstrap** asset repo
> (`cdk-hnb659fds-container-assets-<account>-<region>`), not a per-stack repo.
> `cdk destroy MahaloRuntimeStack` removes the Runtime but does **not**
> garbage-collect those pushed image layers — they linger in the bootstrap ECR
> repo at a small storage cost (cents/month per image). This is expected CDK
> behavior. Options: leave them (negligible), or periodically `cdk gc` / manually
> delete old image tags from the bootstrap repo. Do **NOT** delete the
> `CDKToolkit` stack or its repo — it is the free shared bootstrap other deploys
> depend on.

---

## Step 8 — `[VDI] ONLY` tear down the builder (LAST)

Destroy the builder stack **from the VDI**, after Step 7 has finished from inside
the builder. This removes the instance, its role/instance profile, security group,
and VPC; the root volume is `delete_on_termination=True`, so no orphaned EBS
remains.

```powershell
# [VDI] PowerShell — from the repo root
cd infra-cdk
cdk destroy MahaloBuilderStack --profile lava
```

> ⚠️ **NEVER run Step 8 from inside the builder's own SSM session.** Destroying
> `MahaloBuilderStack` terminates the very instance the SSM shell is running on,
> which kills the `cdk destroy` mid-flight and can strand the VPC/SG/role/EIP
> half-deleted. The builder is always destroyed **last, from the VDI**.

A blunt alternative — `aws ec2 terminate-instances --instance-ids
<BuilderInstanceId> --profile lava --region us-east-1` (also `[VDI]`) — terminates
the instance but leaves the VPC/SG/role until a `cdk destroy`; **prefer
`cdk destroy MahaloBuilderStack` for a clean state.**

---

## Quick reference — all commands by context

| Step | Context | Command |
|------|---------|---------|
| 1 | `[VDI]` | `aws sso login --profile lava` → `aws sts get-caller-identity --profile lava` |
| 2 | `[VDI]` | `cd infra-cdk; cdk deploy MahaloBuilderStack --profile lava` |
| 3A | `[VDI]` | `aws ssm start-session --target <id> --profile lava --region us-east-1` |
| 3B | `[VDI]` | `aws ssm send-command … --parameters 'commands=["sudo -u ssm-user bash /home/ssm-user/mahalo-agentcore/scripts/builder-deploy.sh --phase all"]' --timeout-seconds 3600` |
| 4 | `[builder]` | `bash ~/mahalo-agentcore/scripts/builder-deploy.sh --phase all` |
| 5 | `[builder]` | `bash ~/mahalo-agentcore/scripts/builder-deploy.sh --phase gitea --admin-cidr <ip>/32` |
| 6 | `[VDI, browser]` | open `FrontendUrl`: READ, HITL propose→approve WRITE, reject-writes-nothing, session memory |
| 7 | `[builder]` | `cdk destroy <10 app stacks> --force` (re-run on failure; leaf-first fallback) |
| 8 | `[VDI] ONLY` | `cd infra-cdk; cdk destroy MahaloBuilderStack --profile lava` |

**No `[builder]` command uses `--profile`; no `[VDI]` command omits it.**
