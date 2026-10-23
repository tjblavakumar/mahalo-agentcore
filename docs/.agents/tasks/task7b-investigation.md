# Task 7b — Investigation: "EC2 Docker builder" deploy path

**Status:** INVESTIGATION ONLY (Step 0). No scripts or CDK written here.
**Date:** 2026-10-18
**Workspace:** `mahalo-agentcore` only. The read-only fallback
`D:/<USER>/LavaCode/AI/mahalo-dock` is never written.
**Problem framing:** the operator workstation is an AWS WorkSpaces VDI with no
nested virtualization, so Docker cannot run locally. The CDK deploy needs Docker
for exactly two things; everything else synths and deploys Docker-free. This doc
proves *which* two, picks a builder model, and confirms the staged deploy
sequence against the real stacks.

> Every claim below cites `file:line` in this repo or an AWS doc URL. External
> content was rephrased for compliance with licensing restrictions.

---

## 1. EXACTLY what needs Docker at deploy time

Two deploy actions invoke Docker; both are flag-gated behind
`-c buildImage=1` / `MAHALO_BUILD_IMAGE=1` so the offline `cdk synth` gate never
calls Docker. Nothing else does.

### 1a. The AgentCore Runtime agent image (ARM64) — `MahaloRuntimeStack`

`infra-cdk/mahalo_infra/runtime_stack.py:55-70` has the split:

- **Offline / default branch** (`runtime_stack.py:62-70`): reads a
  `CfnParameter("AgentImageUri")` (default placeholder
  `000000000000.dkr.ecr.us-east-1.amazonaws.com/placeholder:latest`,
  `runtime_stack.py:38`) and builds the artifact with
  `AgentRuntimeArtifact.from_image_uri(image_uri)` — constructs **no**
  `DockerImageAsset`, so no Docker.
- **Operator / build branch** (`runtime_stack.py:56-61`): when `build_image` is
  true it calls
  `AgentRuntimeArtifact.from_asset(_REPO_ROOT, file="agent/Dockerfile",
  platform=ecr_assets.Platform.LINUX_ARM64)` — this **builds the ARM64 image and
  pushes it to ECR** during deploy. This is Docker need #1.

`build_image` is set from either the CDK context flag or the env var
(`runtime_stack.py:53-55`): `self.node.try_get_context("buildImage")` OR
`os.environ.get("MAHALO_BUILD_IMAGE") == "1"`. The same pattern repeats in the
API and frontend stacks.

**ARM64 is mandatory, not a preference.** The Dockerfile pins the platform:
`FROM --platform=linux/arm64 python:3.13-slim` (`agent/Dockerfile:14`), and the
CDK asset is created with `platform=ecr_assets.Platform.LINUX_ARM64`
(`runtime_stack.py:60`). This matches the AgentCore Runtime contract: AgentCore
requires ARM64 for all deployed agents and the agent must be packaged in a
container exposing the `/invocations` POST and `/ping` GET endpoints
([AgentCore getting-started-custom](https://docs.aws.amazon.com/zh_cn/bedrock-agentcore/latest/devguide/getting-started-custom.html);
content rephrased). Because the image is ARM64, the builder must either be an
**arm64/Graviton** host (native build, no emulation) or run a cross-platform
`docker buildx --platform linux/arm64` build on x86 (emulated, slower). AWS
samples build the AgentCore image with `docker buildx build --platform
linux/arm64`
([aws-samples AgentCore Dockerfile](https://github.com/aws-samples/sample-customer-support-agent-on-agentcore/blob/main/Dockerfile)).

**Does `from_asset` build+push to a CDK-managed ECR, and does the Runtime L2
need the image URI?** Yes to the first; no to the second on the build branch.
`DockerImageAsset`/`from_asset` images are built from the local Docker context
and uploaded to Amazon ECR by the CDK toolkit
([CDK ecr_assets README](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_ecr_assets-readme.html);
content rephrased). In modern CDK the target is the single ECR repository created
by `cdk bootstrap` (the `CDKToolkit` stack), not a per-asset repo
([SO: CDK push image to ECR](https://stackoverflow.com/a/67441218/4842985);
content rephrased). CDKToolkit is already bootstrapped in this account, so the
asset repo already exists. On the `from_asset` branch the L2 derives the pushed
image reference itself — the operator does **not** pass `AgentImageUri`. The
`AgentImageUri` CfnParameter is only consumed on the offline/`from_image_uri`
branch (`runtime_stack.py:63-70`); note that branch also adds an explicit ECR
pull policy because `from_image_uri` grants no IAM
(`runtime_stack.py:117-120`, `_grant_ecr_pull` at `runtime_stack.py:177-201`).

### 1b. The thin-API Lambda dependency bundling — `MahaloApiStack`

`infra-cdk/mahalo_infra/api_stack.py:49-70`:

- **Operator / build branch** (`api_stack.py:50-61`): `Code.from_asset(_API_DIR,
  bundling=BundlingOptions(image=lambda_.Runtime.PYTHON_3_13.bundling_image,
  command=[... "pip install -r requirements.txt -t /asset-output && cp -r app
  /asset-output"]))` — this runs the pip install **inside the Lambda bundling
  Docker image**, so `fastapi`/`mangum`/`pydantic`/`boto3`/`botocore` ship in the
  asset (`api/requirements.txt`). This is Docker need #2.
- **Offline / default branch** (`api_stack.py:62-70`):
  `Code.from_asset(_API_DIR)` — a plain asset, no Docker. The code comment notes
  a pre-built deps layer is the offline fallback for a *runnable* Lambda; for the
  synth gate the plain asset suffices.

`build_image` is the same OR gate as the runtime stack (`api_stack.py:47-49`).
So `MahaloApiStack` is Docker-dependent on the build branch too, for a *different*
reason (dependency bundling, not an image build). This matters for the
"prebuild-image-only" alternative in §2.

### 1c. What does NOT need Docker (confirmed)

- **`MahaloGiteaStack`** — the `gitea/gitea:1.27.3` image is pulled **by
  reference in EC2 UserData** (`gitea_stack.py:43` `_GITEA_IMAGE`, used at
  `gitea_stack.py:221-223` `docker run -d --name gitea ...`), never built as a
  `DockerImageAsset`. The docstring states the image is referenced by string so
  `cdk synth` stays Docker-free (`gitea_stack.py:2-5`). The Docker that runs is
  on the Gitea EC2 host at *runtime*, installed by UserData (`gitea_stack.py:216
  "dnf install -y docker"`) — not on the deploy host. **No deploy-time Docker.**
- **`MahaloFrontendStack`** — the `BucketDeployment` that uploads
  `frontend/out/` is flag-gated behind `-c buildFrontend=1` /
  `MAHALO_BUILD_FRONTEND=1` (`frontend_stack.py:91-100`). `BucketDeployment` does
  **not** require Docker here: it uploads an already-built static `out/`
  directory (`s3deploy.Source.asset(_FRONTEND_OUT)`, `frontend_stack.py:96`). The
  only prerequisite is that `frontend/out/` exists, which is produced by
  `npm run build` on the operator/VDI side (Node 24 is available locally, no
  Docker). So the frontend needs a prior `next build`, **not Docker**.
- **The four `MahaloMock*Stack`**, **`MahaloGatewayStack`**,
  **`MahaloMemoryIdentityStack`** — plain Lambda/DynamoDB/Gateway/Memory
  constructs with no asset bundling; Docker-free (consistent with the recorded
  offline gate: `cdk synth --all` = 10 templates Docker-free, per
  `docs/STATUS.md` and `docs/CONTINUATION.md`).

**Conclusion:** only `MahaloRuntimeStack` (ARM64 image build+push) and
`MahaloApiStack` (Lambda dep bundling) need a Docker host at deploy time, and
only when `buildImage` is set. Everything else deploys from the VDI with no
Docker.

---

## 2. Builder model — decision and alternatives

### Options considered

**Option A — EC2 builder runs the WHOLE staged deploy (RECOMMENDED / PRIMARY).**
A transient Amazon Linux 2023 **arm64/Graviton** EC2 instance (e.g. `t4g`/`c7g`)
with Docker + git + Node 24 + Python 3.13 + AWS CLI v2 + CDK installed via
user-data. It clones the repo, runs the full staged `cdk deploy ... -c
buildImage=1`, and is terminated afterward.

- *Pros:* Docker runs where it works; a single host does both Docker needs (the
  ARM64 image build AND the Lambda dep bundling) in one place. Graviton means the
  ARM64 agent image builds **natively** — no `buildx` QEMU emulation — because
  building Arm applications natively on Arm EC2 eliminates cross-compilation and
  emulation ([EC2 M6g instances](https://aws.amazon.com/ec2/instance-types/m6);
  content rephrased). The operator drives everything from one SSM shell; no local
  Docker ever needed. Teardown is clean (terminate the instance).
- *Cons:* the instance needs the full toolchain installed (user-data bootstrap)
  and broad deploy IAM; it is a short-lived but real host to manage.

**Option B — Prebuild-image-only (build+push agent image on EC2, then deploy
from the VDI).** Use the EC2 host *only* to `docker build`+push the ARM64 agent
image to ECR, then from the VDI run `cdk deploy MahaloRuntimeStack` on the
offline `from_image_uri` branch passing `--parameters
AgentImageUri=<ecr-uri>`.

- *Pros:* minimal EC2 lifetime (just a build); most of the deploy stays on the
  VDI.
- *Cons (decisive):* this only removes Docker need #1. Docker need #2 — the
  thin-API Lambda dep bundling (`api_stack.py:50-61`) — still needs Docker and
  **cannot** run on the VDI. The §1b offline branch is a *plain* asset that does
  NOT install `fastapi`/`mangum`; deploying it without bundling yields a Lambda
  that imports nothing. To avoid the second Docker need on the VDI you would have
  to add a pre-built deps-layer path for the API (the `api_stack.py:62-65`
  comment anticipates this but it is not implemented). So Option B trades one
  clean builder for two moving parts (an ECR URI to thread through plus an
  unbuilt API bundling story). Not worth it for a demo.

**Option C — AWS CodeBuild as the Docker host.** A CodeBuild project with an
ARM/Graviton compute type and privileged (Docker) mode builds the image / runs
the deploy. CodeBuild can build AArch64 Docker images on managed Graviton compute
([Arm Learning: build Docker images with CodeBuild](https://learn.arm.com/learning-paths/servers-and-cloud-computing/codebuild/codebuild/);
content rephrased), and the compute/runtime is fully managed by CodeBuild
([CodeBuild compute types](https://docs.aws.amazon.com/codebuild/latest/userguide/build-env-ref-compute-types.html);
content rephrased).

- *Pros:* no EC2 instance to manage; managed, ephemeral by nature.
- *Cons:* a buildspec + project + source wiring + role is more CDK/plumbing than
  a one-off demo stand-up warrants, and iterating/debugging a failing deploy
  inside CodeBuild is slower than an interactive SSM shell. Better fit for a
  repeatable CI pipeline (relevant to Task 8), not this first live gate.

### Decision

**Primary = Option A: a transient arm64/Graviton EC2 builder that runs the whole
staged deploy.** Rationale: it satisfies BOTH Docker needs on one host, builds
the ARM64 agent image natively (no emulation), keeps the operator on a single
interactive shell for the live gate (where measuring the invoke budget and
fixing seams interactively matters), and tears down cleanly. Options B and C are
noted: B is rejected because it leaves the API-bundling Docker need unsolved on
the VDI; C is the right shape for Task 8's repeatable pipeline but heavier than
this demo needs.

---

## 3. Repo-to-builder transfer, credentials, and operator connection

### Code transfer — git clone from GitHub (recommended)

The builder clones the public remote
`https://github.com/tjblavakumar/mahalo-agentcore` at the current commit
(`main` @ `cf4c9b7`, per the task context) — simplest, no file copy, reproducible.
Alternative: SSM-copy the working tree from the VDI (useful only if there are
uncommitted local changes the remote lacks). Since Tasks 0-7 are committed +
pushed and `main` is in sync with origin (`docs/STATUS.md`), a clean clone at
the pinned commit is sufficient and preferred. The builder then creates the two
venvs the repo expects (`infra-cdk/.venv` for CDK, `agent/.venv` for the agent;
noted in the task context) and `pip install`s from the manifests.

### AWS credentials — IAM instance profile (recommended) over SSO forwarding

Attach an **IAM instance profile** to the builder carrying the deploy
permissions (CloudFormation, the CDK asset-publishing role assumption, ECR
push/pull, Lambda, IAM role creation for the stacks, Bedrock AgentCore, S3,
CloudFront, Cognito, EC2 for Gitea, SSM). The EC2 SDK/CLI then uses the
instance-role chain automatically — the agent container already relies on this
pattern (`agent/Dockerfile:24-27` deliberately does NOT set `AWS_PROFILE` so
boto3 falls back to the execution-role chain). This is cleaner than forwarding
the operator's short-lived `lava` SSO session onto the instance (which expires
mid-deploy and would have to be re-pushed). The instance profile must ALSO
include `AmazonSSMManagedInstanceCore` so the operator can connect via Session
Manager (next).

> Note: `cdk deploy` with no `--profile` on the builder uses the instance-role
> chain. The VDI-side runbooks use `--profile lava`; on the builder, drop that
> flag (or set a profile that maps to the instance role).

### Operator connection — SSM Session Manager (recommended) over SSH

Connect with **AWS Systems Manager Session Manager**: no SSH key, no inbound
port, no public IP needed. Session Manager provides shell access to EC2 without
SSH keys, without opening port 22, and without bastion hosts, with session
logging
([oneuptime: Session Manager for EC2](https://oneuptime.com/blog/post/2026-02-12-session-manager-ec2-access-without-ssh/view);
content rephrased), and you can reach a no-ingress instance through SSM without
opening inbound ports
([AWS: accessing no-ingress EC2 with Systems Manager](https://docs.aws.amazon.com/cloud9/latest/user-guide/ec2-ssm.html);
content rephrased). This requires (a) the SSM Agent (preinstalled on Amazon Linux
2023), (b) the instance profile with `AmazonSSMManagedInstanceCore`, and (c) SSM
reachability — either a public subnet with egress or the three SSM VPC endpoints
(`ssm`, `ssmmessages`, `ec2messages`) if private
([SO: SSM not showing instances](https://stackoverflow.com/questions/67511564/aws-ssm-session-manager-not-showing-instances);
content rephrased). The operator starts a session from the VDI with
`aws ssm start-session --target <instance-id> --profile lava --region us-east-1`.
SSH-with-a-keypair is the fallback but is rejected here because it needs an open
port 22 + a managed key — unnecessary on the VDI.

---

## 4. Staged deploy sequence against the real stacks

Stack names are from `infra-cdk/app.py` (10 stacks → 10 templates). Verified
constructor wiring in `app.py`:

| Stack (app.py) | app.py line | Needs `-c buildImage=1`? | Needs Docker? |
|---|---|---|---|
| `MahaloMockJiraStack` / `…Confluence` / `…Github` / `…Servicenow` | `app.py:48-62` | No | No |
| `MahaloGatewayStack` | `app.py:65-70` | No | No |
| `MahaloMemoryIdentityStack` | `app.py:73-77` | No | No |
| `MahaloRuntimeStack` | `app.py:82-87` | **Yes** (ARM64 image build+push) | **Yes** |
| `MahaloApiStack` | `app.py:88-93` | **Yes** (Lambda dep bundling) | **Yes** |
| `MahaloGiteaStack` | `app.py:98` | No | No (image by ref in UserData) |
| `MahaloFrontendStack` | `app.py:99-104` | No (uses `-c buildFrontend=1`) | No (uploads prebuilt `out/`) |

Recommended order (CDK auto-orders via the direct construct references in
`app.py`, but deploy in gated groups to read CfnOutputs between phases — matches
`docs/CONTINUATION.md` and `task6-deploy-runbook.md`):

1. **Backend data/tools (no Docker):** the four `MahaloMock*Stack` +
   `MahaloGatewayStack` + `MahaloMemoryIdentityStack`. (CDKToolkit already
   bootstrapped; skip `cdk bootstrap`.) Capture `MemoryId`, `GatewayMcpUrl`.
2. **Runtime + thin API (BOTH need Docker):** `cdk deploy MahaloRuntimeStack
   MahaloApiStack -c buildImage=1`. Step 1 outputs (`MemoryId`,
   `GatewayMcpUrl`) feed the Runtime env (`runtime_stack.py:_environment`,
   `runtime_stack.py:130-156`). Capture `RuntimeArn` (`runtime_stack.py:171`) and
   `RuntimeApiUrl` (`api_stack.py:160`). **This group is why the EC2 builder
   exists.**
3. **Gitea (no Docker at deploy):** `cdk deploy MahaloGiteaStack --parameters
   AdminCidr=<ip>/32` only if exercising the real GitHub backend; otherwise the
   mock path is default and Gitea can be skipped for a first demo. Requires the
   two SSM SecureString params created first (`task7-deploy-runbook.md §1`), then
   the Gitea bootstrap + `cdk deploy MahaloMockGithubStack -c giteaMode=real`
   (`task7-deploy-runbook.md §3-4`).
4. **Frontend — TWO PHASE (no Docker; needs a prior `npm run build`):**
   - 4a. Deploy `MahaloApiStack` (done in step 2) and read `RuntimeApiUrl`.
   - 4b. Deploy `MahaloFrontendStack` WITHOUT the build flag to create the S3
     bucket + CloudFront + Cognito unauthenticated identity pool/role
     (`frontend_stack.py`). Read `IdentityPoolId` (`frontend_stack.py:174`) and
     `FrontendUrl` (`frontend_stack.py:180`).
   - 4c. `npm run build` with the three `NEXT_PUBLIC_*` vars set —
     `NEXT_PUBLIC_API_URL` = `RuntimeApiUrl`, `NEXT_PUBLIC_AWS_REGION` =
     `us-east-1`, `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID` = `IdentityPoolId`
     (confirmed consumed at `frontend/src/services/api.ts:25-29`; documented in
     `frontend/.env.example`). These are inlined at `next build`, emitting
     `frontend/out/`.
   - 4d. Re-deploy `MahaloFrontendStack -c buildFrontend=1` to upload
     `frontend/out/` via `BucketDeployment` (`frontend_stack.py:91-100`) — **no
     Docker**, just the prebuilt static export.
   - 4e. Re-deploy `MahaloApiStack --parameters FrontendOrigin=<FrontendUrl>` so
     the Function URL CORS `allowed_origins` includes the CloudFront domain
     (`api_stack.py:124-156`). (Ordering per `task7-deploy-runbook.md §5`.)

**Where does the frontend two-phase build run?** Node 24 is on the VDI, so
`npm run build` (4c) can run locally on the VDI — it needs no Docker. But the
EC2 builder also has Node 24, so the operator may do the whole thing (clone →
deploy → build → deploy) on the builder to keep one environment. Either works;
the frontend step is **not** a Docker constraint.

**Does `MahaloFrontendStack`'s `BucketDeployment` need Docker?** No. It uploads
the already-built `out/` directory. The only requirement is that `frontend/out/`
exists (produced by step 4c). The recorded offline gate already builds `out/`
via `npm run build` with no Docker.

---

## Open questions resolved / assumptions

- **Q: On the `from_asset` branch, does the operator still pass
  `AgentImageUri`?** Resolved: no. `from_asset` builds+pushes and the L2 derives
  the reference; `AgentImageUri` is only read on the offline `from_image_uri`
  branch (`runtime_stack.py:63-70`).
- **Q: Does the Lambda bundling need Docker?** Resolved: yes, on the build
  branch (`api_stack.py:50-61`), and there is no implemented pre-built-layer
  offline-runnable path — so the builder must do the API deploy too. This is the
  decisive reason Option A beats Option B.
- **Assumption (builder instance size):** a Graviton `t4g.medium`/`c7g.large`
  class is adequate for an ARM64 `python:3.13-slim` image build + CDK deploy;
  exact sizing is a Task-7c implementation detail, not decided here.
- **Assumption (IAM breadth):** the instance profile needs broad deploy
  permissions; enumerating the exact least-privilege policy is deferred to the
  implementation task. For a short-lived transient builder in a single-owner
  demo account, a scoped-but-broad deploy policy plus
  `AmazonSSMManagedInstanceCore` is acceptable; tighten for Task 8.
- **Commit pinning:** the task context says `main @ cf4c9b7`;
  `docs/STATUS.md`/`CONTINUATION.md` reference `d4f386f` as the last Task-7
  commit. The builder should clone whatever the operator confirms is current
  `origin/main` HEAD at stand-up time; the exact SHA is an operator input, not a
  code fact to hardcode.

---

## Summary of key findings

1. **Only two deploy actions need Docker**, both flag-gated behind
   `-c buildImage=1` / `MAHALO_BUILD_IMAGE=1`: (#1) the ARM64 agent image
   build+push in `MahaloRuntimeStack` (`runtime_stack.py:56-61`,
   `agent/Dockerfile:14`), and (#2) the thin-API Lambda dependency bundling in
   `MahaloApiStack` (`api_stack.py:50-61`). Gitea pulls its image by reference in
   UserData (no deploy Docker); the frontend uploads a prebuilt `out/` (no
   Docker). All other stacks are Docker-free.
2. **Builder model = a transient arm64/Graviton EC2 host that runs the whole
   staged deploy (Option A).** It satisfies both Docker needs on one host and
   builds the ARM64 image natively. Option B (prebuild-image-only) is rejected
   because it leaves the API-bundling Docker need unsolved on the VDI; CodeBuild
   (Option C) is noted as the better fit for Task 8's repeatable pipeline.
3. **Transfer + creds + connect:** git clone the GitHub remote at the current
   `origin/main`; use an **IAM instance profile** (cleaner than forwarding the
   SSO session); connect via **SSM Session Manager** (no SSH key, no inbound
   port). The profile must include `AmazonSSMManagedInstanceCore`.
4. **Staged sequence confirmed against the 10 stacks in `app.py`:** mocks +
   Gateway + Memory/Identity (no Docker) → Runtime + API with `-c buildImage=1`
   (Docker) → Gitea (no deploy Docker) → frontend two-phase (`npm run build`
   then `-c buildFrontend=1`, no Docker). Only Runtime and API need
   `buildImage`; the frontend `BucketDeployment` uploads prebuilt `out/` and
   needs no Docker.

**Investigation document written to:**
`docs/.agents/tasks/task7b-investigation.md`
