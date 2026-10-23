# Task 7b â€” Design: "EC2 Docker builder" deploy path

**Status:** DESIGN (revision 4 â€” resolves the latest design review,
`task7b-design-review.json`: MEDIUMÃ—2, NITÃ—4, verdict CHANGES_REQUESTED).
Implementation is a later task (7c). This document is concrete enough that a
coder can implement the builder CDK stack, the builder-side deploy script, and
the operator runbook directly from it.
**Date:** 2026-10-18
**Workspace:** `mahalo-agentcore` only. The read-only fallback
`<FALLBACK_ROOT>` is NEVER written.
**Grounded in:** `docs/.agents/tasks/task7b-investigation.md`,
`infra-cdk/app.py`, `infra-cdk/mahalo_infra/runtime_stack.py`,
`infra-cdk/mahalo_infra/api_stack.py`, `infra-cdk/mahalo_infra/gitea_stack.py`,
`infra-cdk/mahalo_infra/frontend_stack.py`, `infra-cdk/requirements.txt`,
`agent/Dockerfile`, `frontend/package.json`, `frontend/next.config.ts`,
`frontend/src/services/api.ts`, and the deploy runbooks under
`docs/.agents/tasks/`.
**Review loop:** this revision resolves every finding in the latest
`docs/.agents/tasks/task7b-design-review.json` (verdict CHANGES_REQUESTED:
MEDIUMÃ—2 â€” the `ssm send-command` kickoff invoking a not-yet-cloned script path,
and the frontend-phase `MahaloFrontendStack` deploys lacking `--exclusively`;
NITÃ—4 â€” the `test_no_docker_image_asset` reuse not yet synth-confirmed, the
AL2023 arm64 AMI SSM-parameter resolution unstated in the offline-synth
guarantee, a stale `--gitea-mode real` flag reference, and a hardcoded clone
URL). Per-finding dispositions are at the end (Â§H); earlier-review fixes (the
prior MEDIUMÃ—3/NITÃ—3 round and the original HIGHÃ—2/MEDIUMÃ—5/NITÃ—4 round) still
stand and are retained there too.

---

## Overview

The operator workstation is an AWS WorkSpaces VDI with no nested virtualization,
so Docker cannot run locally. The CDK deploy needs Docker for exactly two
flag-gated actions â€” the ARM64 AgentCore agent image build+push
(`MahaloRuntimeStack`, `runtime_stack.py:56-61`) and the thin-API Lambda
dependency bundling (`MahaloApiStack`, `api_stack.py:50-61`) â€” both behind
`-c buildImage=1` / `MAHALO_BUILD_IMAGE=1`. Everything else synths and deploys
Docker-free (investigation Â§1, re-confirmed by the review's verified-assumptions
list items 1-5).

The design stands up a **transient arm64/Graviton EC2 "builder" instance** that
has Docker and the full toolchain, clones this repo, and runs the entire staged
`cdk deploy` from inside AWS â€” then is torn down. The operator never needs local
Docker. Three deliverables:

1. **`MahaloBuilderStack`** â€” a small, standalone CDK stack (an arm64 AL2023 EC2
   instance + an instance role carrying deploy permissions + SSM access, NO
   inbound ports) that the operator deploys from the VDI. It synths **without
   Docker** (pure CloudFormation; no asset build), so the offline gate is
   preserved.
2. **`scripts/builder-deploy.sh`** â€” the builder-side bash script the operator
   runs inside an SSM shell (or via `ssm send-command`). It installs the
   toolchain, clones the repo, runs the staged `cdk deploy`, performs the
   two-phase frontend build, and captures CfnOutputs. Idempotent / re-runnable,
   phase-selectable.
3. **`docs/.agents/tasks/task7b-runbook.md`** â€” the operator runbook tying it all
   together (VDI-side vs. builder-side command contexts labelled explicitly),
   including teardown.

Technology stack (LOCKED once approved): AWS CDK v2 (Python) for the builder
stack mirroring the existing `infra-cdk` stacks; Amazon Linux 2023 arm64 AMI;
bash for the builder script; AWS Systems Manager Session Manager for operator
connection; an IAM instance profile for builder credentials. No CodeBuild, no
SSH, no new language or framework.

---

## A. Builder provisioning â€” `MahaloBuilderStack`

### A.1 Decision: a dedicated small CDK stack (not a script, not console steps)

Three options were considered for creating the builder: (a) a dedicated CDK stack
the operator deploys from the VDI with no Docker; (b) a boto3/CLI provisioning
script; (c) documented console steps. **Chosen: (a), a CDK stack.** Rationale: the
repo is already 100% CDK (`infra-cdk/`), the operator already drives `cdk deploy`
from the VDI for every other stack, and a stack gives clean, declarative teardown
(`cdk destroy MahaloBuilderStack`) and a reviewable IAM surface. A boto3 script
would duplicate provisioning logic outside the IaC the whole project standardizes
on; console steps are not reproducible across the monthly account reset this
project must survive (STATUS.md). The stack **must synth Docker-free** â€” it builds
NO assets (no `DockerImageAsset`, no `BundlingOptions`), only CloudFormation
resources, so `cdk synth MahaloBuilderStack` runs on the VDI with no Docker and
the offline gate stays green (Â§E.2).

The operator deploys it from the VDI exactly like the other stacks:
`cdk deploy MahaloBuilderStack --profile lava` (no `MAHALO_BUILD_IMAGE` needed â€”
this stack never builds an image).

### A.2 Instance shape

- **Instance type:** `t4g.large` (arm64/Graviton, 2 vCPU, 8 GiB RAM). Exposed as a
  `CfnParameter` `BuilderInstanceType` (default `t4g.large`) so the operator can
  bump to `c7g.xlarge` if the image build is slow. 8 GiB comfortably holds the
  `python:3.13-slim` layer build, `npm ci` + `node_modules`, and a `cdk deploy`.
- **CPU architecture:** arm64/Graviton is **mandatory**, not a preference. The
  agent image is ARM64 (`agent/Dockerfile:8` `FROM --platform=linux/arm64 â€¦`;
  `runtime_stack.py:60` `platform=ecr_assets.Platform.LINUX_ARM64`), so a Graviton
  host builds it **natively** with no QEMU emulation.
- **AMI:** Amazon Linux 2023, arm64 â€”
  `ec2.MachineImage.latest_amazon_linux2023(cpu_type=ec2.AmazonLinuxCpuType.ARM_64)`.
  SSM Agent is preinstalled on AL2023, which the operator-connection path (Â§A.5)
  relies on.
- **Root volume:** 40 GiB gp3 (Docker layers + two venvs + `node_modules` +
  cloned repo). A `block_devices=[ec2.BlockDevice(device_name="/dev/xvda",
  volume=ec2.BlockDeviceVolume.ebs(40, volume_type=ec2.EbsDeviceVolumeType.GP3,
  delete_on_termination=True))]` â€” `delete_on_termination=True` so teardown leaves
  no orphaned EBS (Â§D). Expose the size as `BuilderVolumeSizeGiB` (default 40).

### A.3 Networking â€” no inbound, SSM-reachable

Mirror the Gitea stack's offline-safe VPC pattern (`gitea_stack.py`, verified in
the review's assumptions list item 6), but **with NO inbound rules at all** (the
builder is reached only via SSM, never a listening port):

- A dedicated `ec2.Vpc(max_azs=1, nat_gateways=0)` with a single **public** subnet
  (`SubnetType.PUBLIC`), **created, not looked up**. Add the same fixed-AZ
  `availability_zones` property override Gitea uses
  (`return [f"{self.region}a"]`) so synth needs no AWS AZ lookup and the offline
  gate holds.
- A security group with `allow_all_outbound=True` and **zero ingress rules**. SSM
  Session Manager needs only outbound 443 to the SSM endpoints; a public subnet
  with an internet route provides that egress. No port 22, no public listener.
- `instance.instance.associate_public_ip_address = True` (same line Gitea uses) so
  the instance can reach the public SSM endpoints without a NAT gateway (cost
  saver; NAT is ~$32/mo and unnecessary for a transient builder).

> Rationale for public-subnet + public IP over private-subnet + 3 SSM VPC
> endpoints: the instance is transient and holds no data; a public IP with no
> inbound rules + SSM-only access is the cheaper, simpler reachability path and
> matches the Gitea precedent. (A hardened alternative â€” private subnet + `ssm`,
> `ssmmessages`, `ec2messages` interface endpoints â€” is noted for Task 8, not
> used here.)

### A.4 IAM â€” instance role + instance profile (the credential source)

The builder authenticates to AWS via an **IAM instance role** (not forwarded SSO),
because `cdk deploy` of all app stacks runs for several minutes and a forwarded
`lava` SSO token would expire mid-deploy. The role is attached by passing
`role=` **at construction time** â€” the L2 `ec2.Instance` then auto-creates the
`CfnInstanceProfile` from the supplied role. Do NOT attempt `instance.role = role`
after construction; `.role` is read-only on the L2 once built. (The repo's only
existing `ec2.Instance`, in `gitea_stack.py`, is built with **no** role, so there
is no in-repo precedent to copy â€” this is the exact, verified construction to
use.)

```python
role = iam.Role(
    self, "BuilderRole",
    assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
    managed_policies=[
        # (1) SSM Session Manager connectivity (operator shell, no SSH).
        iam.ManagedPolicy.from_aws_managed_policy_name(
            "AmazonSSMManagedInstanceCore"),
        # (2) Broad deploy permissions â€” see justification below.
        iam.ManagedPolicy.from_aws_managed_policy_name("AdministratorAccess"),
    ],
)

instance = ec2.Instance(
    self, "BuilderInstance",
    vpc=vpc,
    vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
    instance_type=ec2.InstanceType(builder_instance_type.value_as_string),
    machine_image=ec2.MachineImage.latest_amazon_linux2023(
        cpu_type=ec2.AmazonLinuxCpuType.ARM_64),
    security_group=sg,          # zero ingress
    role=role,                  # L2 auto-creates the CfnInstanceProfile
    user_data=user_data,        # Â§A.5
    block_devices=[...],        # Â§A.2 40 GiB gp3
)
instance.instance.associate_public_ip_address = True
instance.apply_removal_policy(RemovalPolicy.DESTROY)
```

**IAM breadth â€” `AdministratorAccess`, justified and scoped by lifetime.**
`cdk deploy` of these app stacks creates/updates CloudFormation stacks spanning
Lambda, DynamoDB, IAM role creation, ECR, Bedrock AgentCore (Runtime/Gateway/
Memory/Identity), S3, CloudFront, Cognito, EC2 (Gitea), and SSM â€” and it also
assumes the CDK bootstrap roles (`cdk-*-deploy-role`, `â€¦-cfn-exec-role`). A
least-privilege policy enumerating all of this is large and brittle, and CDK's own
deploy model assumes broad `cfn-exec` permissions anyway. For a **transient**
builder in a **single-owner demo account** (<AWS_ACCOUNT_ID>) that is spun up, used,
and terminated the same session, `AdministratorAccess` + `AmazonSSMManagedInstanceCore`
is the pragmatic, correct choice. This is called out as deliberately broad; Task 8
(repeatable pipeline) is where a scoped CDK-deploy policy belongs. Expose a
`CfnParameter`-less constant so the choice is visible in code review; a comment
must state the lifetime-scoped justification.

> The role is NOT given any inbound trust beyond the EC2 service principal, and
> the stack has no inbound SG rules, so the admin credentials are reachable only
> from inside the instance (via the instance metadata service) by an operator who
> has already authenticated to SSM with their `lava` SSO identity.

### A.5 UserData â€” toolchain bootstrap + initial clone (robust, non-aborting)

UserData runs as **root** at first boot, installs the toolchain, **and performs
the initial repo clone** so the `scripts/builder-deploy.sh` path exists before
any operator kickoff (interactive OR `ssm send-command`). This is the MEDIUM-1
resolution: because UserData clones the repo and `chown`s it to `ssm-user`, the
unattended `send-command` in Â§B.5 can invoke
`/home/ssm-user/mahalo-agentcore/scripts/builder-deploy.sh` on a fresh builder
without a "No such file or directory" failure. The clone is best-effort and
guarded so a transient network blip at boot cannot abort UserData â€” the deploy
script's `toolchain` phase re-clones/updates the same tree idempotently (Â§B.3),
so a failed boot-time clone self-heals on the first script run.

The script `builder-deploy.sh` (Â§B) runs **docker via `sudo`** (passwordless sudo
is the AL2023 default for the SSM shell), so the deploy does NOT depend on the SSM
user's docker-group membership â€” this removes the `ssm-user` timing/refresh hazard
entirely. The group-add line is kept only as a best-effort convenience and is
guarded so it can never abort boot.

Each install step is made tolerant so a single wrong package name cannot abort the
whole boot under `set -e`. The exact AL2023 arm64 package name for Python 3.13 is
an **implementation-verify item** (NIT-1): the coder must confirm it on a live
AL2023 arm64 host (candidates: `python3.13` + `python3.13-pip`, or install `uv`
and let it manage the interpreter). UserData outline:

```bash
#!/bin/bash
set -uxo pipefail      # NOTE: not -e at top level; each critical step guarded.

# Docker (AL2023).
dnf install -y docker
systemctl enable --now docker
# Best-effort convenience only; MUST NOT abort boot (ssm-user may not exist yet,
# and a group add does not apply to an already-open SSM shell anyway â€” the deploy
# script uses sudo for docker, so this line is non-load-bearing).
usermod -aG docker ssm-user 2>/dev/null || true

# git, Node 24, AWS CLI v2 (AL2023 ships awscli; verify version in script).
dnf install -y git
# Node 24 via the NodeSource/nvm path the coder confirms for AL2023 arm64.
# Python 3.13 â€” VERIFY the package name on AL2023 arm64 at implementation time:
dnf install -y python3.13 python3.13-pip || dnf install -y python3.13 || true

# CDK CLI â€” pin to a version compatible with infra-cdk/requirements.txt
# (aws-cdk-lib>=2.251,<3). Install a matching CLI major.minor rather than floating
# 'aws-cdk@2' to avoid bootstrap/deploy version-drift warnings (NIT-4, prior round).
npm install -g aws-cdk@2.251   # coder pins the exact 2.x.y confirmed working

# Initial clone so scripts/builder-deploy.sh EXISTS before any kickoff (MEDIUM-1).
# Best-effort + guarded so a boot-time network blip cannot abort UserData; the
# toolchain phase re-clones/updates idempotently (Â§B.3). Clone as root, then
# chown to ssm-user so the ssm-user-run deploy script owns the whole tree and
# there is no root-vs-ssm-user ownership conflict (NIT-6 reasoning).
REPO_URL="https://github.com/tjblavakumar/mahalo-agentcore.git"
git clone "$REPO_URL" /home/ssm-user/mahalo-agentcore 2>/dev/null || true
chown -R ssm-user:ssm-user /home/ssm-user/mahalo-agentcore 2>/dev/null || true

# Mark ready for the operator's SSM shell.
echo "builder toolchain ready" > /var/log/builder-ready
```

UserData runs as root; it installs the toolchain and performs the **initial
clone into `/home/ssm-user/mahalo-agentcore`**, then `chown`s that tree to
`ssm-user`. It does NOT create the venvs or `node_modules` â€” those (and any
re-clone/update) happen in `builder-deploy.sh`, which runs as `ssm-user` and pins
its own base directory (`BUILDER_HOME`, Â§B.1/Â§B.3) so cwd is deterministic.
Because root clones into `ssm-user`'s home and immediately `chown`s it, the
ssm-user-run script owns every file it later touches â€” no ownership conflict
(NIT-6). The script re-checks each tool and re-clones/updates the tree if needed,
so a partial or failed boot-time clone/install is self-healing (idempotency, Â§B).

### A.6 Operator connection â€” SSM Session Manager

The operator connects from the **VDI** with:

```powershell
# --- VDI shell (uses the operator's lava SSO profile) ---
aws ssm start-session --target <instance-id> --profile lava --region us-east-1
```

No SSH key, no inbound port, no bastion. This requires only (a) the preinstalled
SSM Agent on AL2023, (b) `AmazonSSMManagedInstanceCore` on the instance role
(Â§A.4), and (c) SSM egress reachability (the public subnet + public IP, Â§A.3).
Alternatively the operator can fire the whole deploy non-interactively via
`aws ssm send-command` (Â§B.5).

### A.7 CfnOutputs

`BuilderInstanceId` (for `start-session` / `send-command` / terminate) and
`BuilderPublicDns` (diagnostic). No secrets are output.

### A.8 Wiring into `app.py`

Add one line, mirroring the existing standalone stacks (no cross-references, so
synth ordering is unaffected â€” review assumption item 10):

```python
from mahalo_infra.builder_stack import MahaloBuilderStack
...
MahaloBuilderStack(app, "MahaloBuilderStack", env=_ENV)
```

This takes the app from 10 stacks to **11**. The current count of 10 is the code
fact in `app.py` (4 mocks + Gateway + MemoryIdentity + Runtime + Api + Gitea +
Frontend). The coder MUST run `cdk list` / `cdk synth --all` after adding the
stack and confirm it reports exactly **11** stacks. (A `cdk synth` during
authoring could not complete in the sandbox because the deploy-branch asset
bundling is slow/credential-gated; the count is derived from the source, not a
fresh synth.)

> CORRECTION (MEDIUM-2): there is **no executable total-template-count assertion**
> in `infra-cdk/tests/` to "update." Verified against the suite: every test
> (`test_synth.py`, `test_api_stack.py`, `test_gitea_stack.py`,
> `test_frontend_stack.py`, `test_gateway_stack.py`, â€¦) asserts **per-stack**
> resource counts via `assertions.Template.from_stack(...)` +
> `resource_count_is(...)`; the only "10" is a **prose docstring** in
> `frontend_stack.py` ("the `cdk synth --all` template count stays 10"). So the
> coder's test task is: (a) update that stale docstring (and any doc that says
> "10 templates") to **11**; and (b) OPTIONALLY add a new
> `infra-cdk/tests/test_app.py` that builds the full app and asserts
> `len(app.synth().stacks) == 11` if a hard gate is wanted. The coder must NOT go
> looking for a pre-existing count assertion to bump â€” there isn't one.

---

## B. Build + deploy execution â€” `scripts/builder-deploy.sh`

### B.1 What it is and how it runs

A bash script committed at `scripts/builder-deploy.sh`, run **on the builder**
inside the operator's SSM shell (or via `ssm send-command`). It is
**idempotent / re-runnable** and **phase-selectable** via `--phase`:
`toolchain | backend | runtime-api | frontend | gitea | all`. Re-running any
phase is safe (CDK is declarative; re-deploys converge).

> FLAG â†’ ENV MAPPING (prior NIT): the script's arg parser maps each CLI flag to
> the env var the phase bodies read, so the fail-fast `:?` guards have a defined
> source: `--phase <name>` â†’ `PHASE`, `--commit <sha>` â†’ `COMMIT`,
> `--admin-cidr <cidr>` â†’ `ADMIN_CIDR`. Any of these may also be supplied
> directly as an env var (the flag just sets it); the `--phase gitea` guard
> `${ADMIN_CIDR:?set --admin-cidr}` therefore fails fast whether the operator
> forgot the flag or the env var.
>
> OVERRIDABLE ENV (no flag) â€” the clone remote is a script variable, NOT a CLI
> flag (NIT-6, this round):
>
> | variable | default | purpose |
> |---|---|---|
> | `REPO_URL` | `https://github.com/tjblavakumar/mahalo-agentcore.git` | git remote the toolchain phase clones; matches the UserData clone URL (Â§A.5) |
> | `BUILDER_HOME` | `/home/ssm-user` | base dir the clone + venvs + `node_modules` resolve under (Â§B.3) |
> | `COMMIT` | `origin/main` HEAD | checked-out revision (overridable via `--commit`) |
>
> So the toolchain phase clones with
> `git clone "${REPO_URL:-https://github.com/tjblavakumar/mahalo-agentcore.git}"`;
> the public demo remote needs no credentials for an unauthenticated HTTPS clone.
> A **private** remote would need an instance-role-readable credential (e.g. an
> SSM SecureString PAT or a CodeConnection), which is **out of scope for the
> public demo** and noted only so the coder does not assume the hardcoded public
> URL covers a private-repo case.

> BASE DIRECTORY (NIT-6): every phase begins with
> `cd "${BUILDER_HOME:-/home/ssm-user}"` and clones into / enters
> `mahalo-agentcore` **relative to that base**, so the clone location, the two
> venvs (`infra-cdk/.venv`, `agent/.venv`), and `node_modules` are deterministic
> regardless of the operator's starting cwd â€” the idempotent re-run never clones
> into the wrong place or fails a `cd`. `BUILDER_HOME` is overridable but
> defaults to `ssm-user`'s home (the user the script runs as).

> CREDENTIAL CONTEXT (NIT-3): every `aws` / `cdk` command **on the builder** uses
> the **instance role** â€” NO `--profile` flag. The only `--profile lava` commands
> in this design are **VDI-side** (the `start-session` / `send-command` kickoff in
> Â§A.6 / Â§B.5 and the VDI teardown in Â§D). The runbook (Â§G) labels every block
> `[VDI]` or `[builder]` so the two credential contexts are never conflated.

### B.2 Region and account

```bash
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)   # instance role
```

### B.3 Phases and exact commands

All `cdk` commands run from `infra-cdk/` with its `.venv` active and the Docker
env flag set as noted. **`MAHALO_BUILD_IMAGE=1` is exported once at the top of the
script and kept exported for the entire run**, so EVERY `cdk deploy` of a
Docker-dependent stack (Runtime, Api) uses the bundled branch â€” including any
re-deploy of `MahaloApiStack` in the `frontend` phase (this closes the MEDIUM-4
hazard: a CORS re-deploy without the flag would otherwise repackage the API as a
dependency-less plain asset and break it). The script sets it unconditionally:

```bash
export MAHALO_BUILD_IMAGE=1   # Docker branches ON for Runtime + Api, always.
```

**Phase `toolchain`** â€” verify/instalÂ­l git, Docker (via `sudo`), Node 24, Python
3.13, AWS CLI v2, CDK CLI; create `infra-cdk/.venv` and `agent/.venv` and
`pip install` their manifests; `node --version` must be 24.x and `docker info`
(run with `sudo`) must succeed. Clones the repo if not present, always from the
pinned base dir (NIT-6):

```bash
cd "${BUILDER_HOME:-/home/ssm-user}"
REPO_URL="${REPO_URL:-https://github.com/tjblavakumar/mahalo-agentcore.git}"
# UserData already cloned this on first boot (Â§A.5); this re-clone/update makes
# the phase self-healing if the boot-time clone failed or the tree is stale.
git clone "$REPO_URL" || \
  (cd mahalo-agentcore && git fetch && git checkout "$COMMIT" && git pull --ff-only)
```

Every subsequent phase likewise starts with `cd "${BUILDER_HOME:-/home/ssm-user}"`
then `cd mahalo-agentcore` before touching `infra-cdk/` or `frontend/`, so the
`/tmp/mahalo-*-outputs.json` paths and the venvs are resolved identically on
every (re-)run.

`$COMMIT` defaults to `origin/main` HEAD and is overridable with `--commit <sha>`
(the operator confirms the current HEAD at stand-up; the investigation notes the
STATUS/CONTINUATION SHA may lag, so do not hardcode a SHA).

**Phase `backend` (no Docker)** â€” bootstrap check, then deploy the Docker-free
backend group and capture outputs:

```bash
# Bootstrap fallback â€” account id resolved FIRST, Docker-free standard template,
# runs under the builder's admin role. 'already bootstrapped' is an EXPECTATION,
# not a fact (MEDIUM-5):
aws cloudformation describe-stacks --stack-name CDKToolkit >/dev/null 2>&1 \
  || cdk bootstrap "aws://$ACCOUNT/us-east-1"

cd infra-cdk && source .venv/bin/activate
cdk deploy MahaloMemoryIdentityStack MahaloGatewayStack \
  MahaloMockJiraStack MahaloMockConfluenceStack \
  MahaloMockGithubStack MahaloMockServicenowStack \
  --require-approval never --outputs-file /tmp/mahalo-backend-outputs.json
```

Capture `MemoryId`, `GatewayMcpUrl` from the outputs file (Â§C.1).

**Phase `runtime-api` (BOTH need Docker â€” the reason the builder exists)** â€”

```bash
# MAHALO_BUILD_IMAGE=1 already exported (top of script).
cdk deploy MahaloRuntimeStack MahaloApiStack \
  --require-approval never --outputs-file /tmp/mahalo-rtapi-outputs.json
```

Capture `RuntimeArn` and `RuntimeApiUrl` (Â§C.1). The Runtime deploy builds+pushes
the ARM64 image natively (Graviton, no emulation); the Api deploy bundles
`fastapi`/`mangum`/`boto3` into the Lambda asset via `BundlingOptions`.

**Phase `frontend` (no Docker; needs a prior `npm run build`)** â€” the two-phase
build, detailed in Â§C.

**Phase `gitea` â€” deploy the Gitea host ONLY; defer the real-github flip to the
task7 runbook (HIGH-2 resolution).** The `giteaMode=real` github-mock flip depends
on `app.py`'s module-level `_GITEA_ENV`, which hardcodes `gitea.internal` /
`gitea.public` and has **no** CfnParameter/context override for the deployed
`GiteaPublicUrl` (verified in `app.py`). Overriding it would require an `app.py`
code change that is **out of scope for this design and not in Â§F's file list**.
Therefore `--phase gitea` does exactly this and stops:

```bash
# Real-github backend is OPTIONAL and defaults OFF; the demo runs on the mock.
# Pre-flight the two SSM SecureString params the real-github path needs
# (MEDIUM-2) â€” fail fast with a pointer to the task7 runbook if absent:
aws ssm get-parameter --name /mahalo/gitea/adapter-token  >/dev/null 2>&1 || \
  { echo "MISSING /mahalo/gitea/adapter-token â€” create it per task7 runbook Â§1"; exit 1; }
aws ssm get-parameter --name /mahalo/gitea/admin-password >/dev/null 2>&1 || \
  { echo "MISSING /mahalo/gitea/admin-password â€” create it per task7 runbook Â§1"; exit 1; }

# AdminCidr is REQUIRED (no default in gitea_stack.py); GiteaIngressCidr defaults
# to 0.0.0.0/0 (token-protected) and need not be passed.
cdk deploy MahaloGiteaStack --parameters AdminCidr="${ADMIN_CIDR:?set --admin-cidr}" \
  --require-approval never --outputs-file /tmp/mahalo-gitea-outputs.json

echo "Gitea deployed. GiteaPublicUrl:"
python -c "import json;print(json.load(open('/tmp/mahalo-gitea-outputs.json'))['MahaloGiteaStack']['GiteaPublicUrl'])"
echo "To wire the REAL github backend (bootstrap + giteaMode=real + GiteaPublicUrl"
echo "override), follow docs/.agents/tasks/task7-deploy-runbook.md Â§3-5."
```

The script does NOT emit `cdk deploy MahaloMockGithubStack -c giteaMode=real`
(that command, as written against the current `app.py`, would point the github
backend at the placeholder hostnames). The entire real-github flip â€” including the
Gitea bootstrap, the token push, and whatever `app.py` change threads
`GiteaPublicUrl` into the github mock â€” is explicitly owned by
`task7-deploy-runbook.md` and flagged as an `app.py` dependency not resolved here.
For the first live demo the mock github path (default) is used and Gitea can be
skipped.

**Phase `all`** â€” runs `toolchain â†’ backend â†’ runtime-api â†’ frontend` in order
(NOT `gitea`, which is opt-in via `--phase gitea --admin-cidr <cidr>`).

### B.4 Fail-fast validation before expensive steps

Before `cdk deploy`, assert `aws sts get-caller-identity` succeeds (instance role
live) and `docker info` (via sudo) works. Before the frontend build, assert the
`NEXT_PUBLIC_*` inputs are non-empty (Â§C.4). Before `--phase gitea`, assert the
two SSM params (above) â€” there is no `--gitea-mode` flag; the Â§B.1 mapping defines
only `--phase`, `--commit`, `--admin-cidr`, and `--phase gitea` pre-flights the
SSM params unconditionally (Â§B.3). This mirrors the project's
validate-cheaply-first principle uniformly.

### B.5 Non-interactive kickoff (optional)

Instead of an interactive shell, the operator may run from the VDI:

```powershell
# --- VDI shell ---
aws ssm send-command --instance-ids <instance-id> --profile lava --region us-east-1 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo -u ssm-user bash /home/ssm-user/mahalo-agentcore/scripts/builder-deploy.sh --phase all"]' \
  --timeout-seconds 3600
```

This single `send-command` is now **self-contained on a fresh builder** (MEDIUM-1
resolution): UserData already cloned the repo to
`/home/ssm-user/mahalo-agentcore` and `chown`ed it to `ssm-user` at first boot
(Â§A.5), so the script file exists before the command runs. The absolute path
under the default `BUILDER_HOME`
(`/home/ssm-user/mahalo-agentcore/scripts/builder-deploy.sh`) matches the base dir
the script itself `cd`s to (Â§B.1), so interactive and unattended runs resolve the
same tree; the script's `toolchain` phase also re-clones/updates idempotently, so
even if the boot-time clone was slow or failed the first script run heals it.
(Wait for `/var/log/builder-ready` or poll `cloud-init status --wait` before
firing the command so UserData has finished.) Interactive SSM is recommended for
the live gate (so the operator sees CfnOutputs and can react); `send-command` is
for an unattended run.

---

## C. Output capture + frontend wiring (chicken-and-egg resolved)

### C.1 How outputs get back to the operator

Every `cdk deploy` writes `--outputs-file <path>.json`. The script parses the JSON
and both (a) echoes a human-readable summary to the SSM shell and (b) writes a
consolidated `/tmp/mahalo-outputs.env` the frontend phase sources. Keys captured:
`MemoryId`, `GatewayMcpUrl`, `RuntimeArn`, `RuntimeApiUrl`, `IdentityPoolId`,
`FrontendUrl` (and `GiteaPublicUrl`/`GiteaInstanceId` when the gitea phase runs).
These names are confirmed present as CfnOutputs in the stacks (review assumption
item 9).

### C.2 Does the frontend upload need Docker? No.

`MahaloFrontendStack`'s `BucketDeployment` uploads the already-built static
`frontend/out/` directory (`frontend_stack.py:_FRONTEND_OUT`,
`s3deploy.Source.asset(_FRONTEND_OUT)`), gated behind `-c buildFrontend=1` /
`MAHALO_BUILD_FRONTEND=1`. It invokes **no** bundling image â€” confirmed in source
(review assumption item 5). The only prerequisite is that `frontend/out/` exists,
produced by the frontend build (Â§C.3). So the frontend phase needs a prior
`next build`, **not** Docker. The builder has Node 24, so it does the build itself
(one environment for the whole deploy).

### C.3 The frontend build command and output dir â€” VERIFIED for this project

The review (MEDIUM-3) and `frontend/AGENTS.md` correctly warn that this is Next.js
**16.3.3** (`frontend/package.json`), not classic Next, so the export command and
output dir were verified against this project's actual config rather than assumed:

- **Build command:** `npm run build` â†’ `next build`
  (`frontend/package.json` `"build": "next build"`). There is no separate
  `next export` script; export is driven by config.
- **Static export + output dir:** `frontend/next.config.ts` sets
  `output: "export"` (with `images: { unoptimized: true }`). With `output:
  "export"`, `next build` emits the static site to **`out/`** by default â€” i.e.
  `frontend/out/`, exactly the directory `frontend_stack.py` hardcodes as
  `_FRONTEND_OUT`. So `npm run build` is the correct command and `frontend/out/`
  is the correct, matching output dir for THIS project. (No separate export step
  is needed in Next 16 when `output: "export"` is set.)
- **Env inlining:** `frontend/src/services/api.ts` reads `NEXT_PUBLIC_API_URL`,
  `NEXT_PUBLIC_AWS_REGION`, and `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID` via
  `process.env.*` with silent fallbacks (confirmed in source). `NEXT_PUBLIC_*`
  vars are inlined at build time, so they MUST be set in the environment of the
  `npm run build` invocation (Â§C.4), not injected afterward.

> Implementation note for the coder: `frontend/AGENTS.md` instructs reading the
> bundled Next 16 docs under `node_modules/next/dist/docs/` before touching
> frontend build mechanics. The build command and `output: "export"` â†’ `out/`
> behavior above are taken from this project's own `package.json` +
> `next.config.ts`; if a future Next bump changes the export dir, the
> `_FRONTEND_OUT` constant and this step must move together.

### C.4 The two-phase frontend build â€” ordering (chicken-and-egg resolved)

The frontend static build must inline `RuntimeApiUrl` and `IdentityPoolId`, but
those come from stacks the frontend bucket/CloudFront/Cognito also live in. Resolve
the circular dependency by deploying the frontend infrastructure **first (without
the bundle)**, reading its outputs, building, then re-deploying **with the bundle**:

1. **Phase `runtime-api` already produced `RuntimeApiUrl`** (Â§B.3). Read it from
   `/tmp/mahalo-rtapi-outputs.json`.
2. **Deploy `MahaloFrontendStack` WITHOUT the build flag** to create the S3
   bucket + CloudFront distribution + Cognito unauthenticated identity pool/role
   (no `BucketDeployment` runs because `buildFrontend` is unset). **`--exclusively`
   is MANDATORY** (MEDIUM-2): `MahaloFrontendStack` reads
   `api_stack.function.function_arn`, so CDK treats `MahaloApiStack` as a
   dependency and a bare `cdk deploy MahaloFrontendStack` would pull the API into
   the deploy set and re-deploy it with the **default** `FrontendOrigin`
   placeholder (`https://example.cloudfront.net`), clobbering any CORS wiring.
   `--exclusively` deploys ONLY the named stack and skips dependencies:
   ```bash
   cdk deploy MahaloFrontendStack --exclusively --require-approval never \
     --outputs-file /tmp/mahalo-fe-outputs.json
   ```
   Read `IdentityPoolId` and `FrontendUrl`.
3. **Fail-fast guard**, then build on the builder with the three vars set
   (empty/placeholder values are REFUSED so a silent-fallback build cannot ship):
   ```bash
   : "${RUNTIME_API_URL:?}"; : "${IDENTITY_POOL_ID:?}"
   cd frontend && npm ci
   NEXT_PUBLIC_API_URL="$RUNTIME_API_URL" \
   NEXT_PUBLIC_AWS_REGION=us-east-1 \
   NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID="$IDENTITY_POOL_ID" \
     npm run build          # emits frontend/out/ (verified Â§C.3)
   test -f out/index.html || { echo "export missing frontend/out"; exit 1; }
   ```
4. **Re-deploy `MahaloFrontendStack` WITH the build flag** to upload
   `frontend/out/` via `BucketDeployment`. **`--exclusively` again MANDATORY**
   (MEDIUM-2) so this re-deploy touches only the frontend stack and cannot pull
   `MahaloApiStack` in with the placeholder `FrontendOrigin`:
   ```bash
   cd ../infra-cdk
   cdk deploy MahaloFrontendStack --exclusively -c buildFrontend=1 \
     --require-approval never
   ```
5. **Re-deploy `MahaloApiStack` to set CORS to the real CloudFront origin** â€” with
   `MAHALO_BUILD_IMAGE=1` STILL exported (MEDIUM-4), so the API Lambda is rebuilt
   WITH its bundled deps, not downgraded to the plain asset:
   ```bash
   cdk deploy MahaloApiStack -c buildImage=1 \
     --parameters FrontendOrigin="$FRONTEND_URL" --require-approval never
   ```
   `FrontendOrigin` default is the placeholder `https://example.cloudfront.net`
   (`api_stack.py`), so overriding it with the real `FrontendUrl` is required for
   browser calls to pass CORS (review assumption item 7). Because this re-deploy
   runs inside the same script with `MAHALO_BUILD_IMAGE=1` exported, the hazard of
   a dependency-less repackage cannot occur; the script also sets the flag
   unconditionally whenever it touches `MahaloApiStack`, so a standalone
   `--phase frontend` re-run in a fresh shell is equally safe.

**Phase ordering invariant (this round, MEDIUM-2):** within `--phase frontend` the
script MUST run these in order â€” (2) frontend infra `--exclusively`, (3) build,
(4) frontend bucket upload `--exclusively`, (5) `MahaloApiStack` CORS. **Step 5
(the `MahaloApiStack` deploy with the real `FrontendOrigin`) is ALWAYS the final
deploy of the phase.** Because steps 2 and 4 use `--exclusively`, no implicit API
deploy with the placeholder origin ever runs; and because step 5 runs last and
explicitly passes the real `FrontendOrigin`, CORS always ends pointing at the live
CloudFront domain â€” never at `https://example.cloudfront.net`. The script enforces
this ordering internally, and a partial `--phase frontend` re-run re-executes the
whole ordered sequence (every CDK deploy here is idempotent), so CORS cannot be
left stale.

The operator then validates in the browser at `FrontendUrl`.

---

## D. Teardown

Two things must be destroyable: the builder, and the app stacks. The builder can
run the app-stack destroy too.

### D.1 Destroy the app stacks (from the builder, instance role)

The ten app stacks have **hard construct-reference dependencies** that
CloudFormation enforces on delete in the **reverse of create order**:
`MahaloFrontendStack` reads `api_stack.function.function_arn` â†’ depends on
`MahaloApiStack`; `MahaloApiStack` reads `runtime_stack.runtime` â†’ depends on
`MahaloRuntimeStack`; `MahaloRuntimeStack` reads `memory_stack.memory` (and
optionally the gateway); `MahaloGatewayStack` depends on the four mock stacks;
`MahaloGiteaStack` is independent (no cross-reference). **Passing all ten stacks
to a single `cdk destroy` lets CDK compute and apply the correct reverse
dependency order automatically** â€” this is why they are listed together:

```bash
# --- [builder] --- one command; CDK computes the reverse-dependency delete order
cd "${BUILDER_HOME:-/home/ssm-user}/mahalo-agentcore/infra-cdk"
source .venv/bin/activate
cdk destroy MahaloFrontendStack MahaloApiStack MahaloRuntimeStack \
  MahaloGiteaStack MahaloMemoryIdentityStack MahaloGatewayStack \
  MahaloMockJiraStack MahaloMockConfluenceStack \
  MahaloMockGithubStack MahaloMockServicenowStack --force
```

`--force` suppresses the interactive confirmation prompt but does **not** suppress
dependency errors: a *partial* or mis-ordered destroy (e.g. deleting
`MahaloRuntimeStack` while `MahaloApiStack` still references it) will error. Two
real-world retry hazards exist and the runbook must handle them:

1. **Custom-resource retry.** `MahaloFrontendStack` has a `BucketDeployment`
   custom resource and an S3 `auto_delete_objects` custom resource; CloudFront +
   S3 deletes can momentarily sit in a retry/`DELETE_IN_PROGRESS` state and
   occasionally fail the first pass.
2. **Ordering on re-run.** If the one-shot command fails midway, some stacks are
   already gone and some remain.

**Guard (idempotent):** `cdk destroy` is idempotent â€” already-deleted stacks are
skipped â€” so on ANY failure, **simply re-run the exact same command**; it
converges. If a re-run still fails, fall back to destroying in explicit
**leaf-first groups** (never a dependency before its dependents):

```bash
# --- [builder] fallback: leaf-first, dependents before dependencies ---
cdk destroy MahaloFrontendStack --force          # depends on Api
cdk destroy MahaloApiStack --force               # depends on Runtime
cdk destroy MahaloRuntimeStack --force           # depends on Memory (+ Gateway)
cdk destroy MahaloMemoryIdentityStack MahaloGatewayStack --force
cdk destroy MahaloMockJiraStack MahaloMockConfluenceStack \
  MahaloMockGithubStack MahaloMockServicenowStack --force
cdk destroy MahaloGiteaStack --force             # independent; any time
```

Teardown posture is confirmed in source (review assumption item 12): the frontend
bucket is `auto_delete_objects=True` + `RemovalPolicy.DESTROY`; the Gitea EBS is
`delete_on_termination=True` with a `DeletionPolicy` conditioned on
`RetainGiteaData` (default destroys). So once ordering/retry is handled the
destroy is clean.

### D.2 Destroy the builder â€” from the VDI ONLY, never the builder

`cdk destroy MahaloBuilderStack` tears down the instance, its role/instance
profile, SG, and VPC. Because the root volume is `delete_on_termination=True`, no
orphaned EBS remains. **This command MUST be run from the `[VDI]`, never from
inside the builder's own SSM session (MEDIUM-3):** destroying the builder stack
terminates the very instance the SSM shell is running on, which kills the
`cdk destroy` mid-flight and can strand the VPC/SG/role/EIP half-deleted. So the
builder is always destroyed **last, from the VDI**, after the app-stack destroy
(Â§D.1) has finished from inside the builder:

```powershell
# --- [VDI] ONLY â€” do NOT run this from the builder's SSM session ---
cdk destroy MahaloBuilderStack --profile lava
```

A blunt alternative â€” `aws ec2 terminate-instances --instance-ids <id>` (also
`[VDI]`) â€” works but leaves the VPC/SG/role until `cdk destroy`; prefer the CDK
destroy for a clean state.

### D.3 ECR images created by `from_asset` â€” cost note

The ARM64 agent image built by `from_asset` is pushed to the **CDK bootstrap**
asset repository (the shared `cdk-hnb659fds-container-assets-<account>-<region>`
ECR repo created by `cdk bootstrap`), not a per-stack repo. `cdk destroy
MahaloRuntimeStack` removes the Runtime but does **not** garbage-collect the
pushed image layers â€” they linger in the bootstrap ECR repo and incur small ECR
storage cost (cents/month per image). This is expected CDK behavior. Cleanup
options, documented in the runbook: leave them (negligible), or periodically run
`cdk gc` (if the CLI version supports it) / manually delete old image tags from
the bootstrap repo. Do NOT delete the CDKToolkit stack or its repo (it is the free
shared bootstrap and other deploys depend on it).

---

## E. Cost + safety

### E.1 Footprint

The builder is a single `t4g.large` (~$0.067/hr on-demand, us-east-1) + a 40 GiB
gp3 root volume (~$3.20/mo if left, prorated hourly) + a public IPv4 address
(~$0.005/hr). A full deploy run is well under an hour, so the builder's cost for a
deploy+teardown cycle is a few cents. There is no NAT gateway (public subnet),
avoiding ~$32/mo. **The builder must be terminated after the deploy** â€” it is
transient by design; the runbook makes `cdk destroy MahaloBuilderStack` a required
final step.

> SCOPE OF THIS FOOTPRINT (NIT-4): Â§E.1 prices **only the builder**. The app
> stacks carry their **own** costs â€” the Gitea EC2 instance **and its own public
> IPv4** (~$0.005/hr, the same charge that applies to the builder), CloudFront,
> the Lambdas, and DynamoDB â€” none of which are counted here. Those are torn down
> via Â§D.1 after validation, consistent with the project's
> spin-upâ†’validateâ†’tear-down pattern (STATUS.md). The builder and the app stacks
> are independent spend lines; terminating the builder does not stop app-stack
> cost and vice-versa.

### E.2 Offline-synthable guarantee

`MahaloBuilderStack` builds NO assets â€” it is pure CloudFormation (VPC, subnet,
SG, EC2 instance, IAM role/profile, EBS). It therefore synths with NO Docker and
NO AWS credentials, exactly like the Gitea stack. The fixed-AZ
`availability_zones` override (Â§A.3) keeps synth from doing an AZ lookup.

> AMI RESOLUTION IS OFFLINE (NIT-4): `latest_amazon_linux2023(cpu_type=ARM_64)`
> does NOT make a synth-time AWS call. CDK renders it as a CloudFormation
> `AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>` template parameter whose
> default is the public AL2023 arm64 AMI SSM parameter path; CloudFormation
> resolves the concrete AMI id at **deploy** time. This is identical to how the
> Gitea stack resolves its x86 AMI (`gitea_stack.py` uses
> `latest_amazon_linux2023()`), and is confirmed Docker-free and credential-free
> by `test_gitea_stack.py`'s passing offline synth. It is NOT a credentialed
> `from_lookup`-style call â€” the coder should not mistake it for one.

The
coder MUST confirm `cdk synth --all` still exits 0 and now lists **11** templates
(Â§A.8, MEDIUM-2), and that the existing per-stack infra-cdk assertion suite still
passes with the new stack. (There is no total-count gate assertion today; the
"11" confirmation is a `cdk list`/`cdk synth --all` check plus the stale-docstring
fix and the OPTIONAL new `test_app.py` described in Â§A.8/Â§F â€” not an edit to a
pre-existing count assertion.)

### E.3 Safety

No inbound ports; credentials are an instance role reachable only from inside the
instance by an SSM-authenticated operator. The admin-breadth role is deliberately
lifetime-scoped to a transient builder in a single-owner demo account (Â§A.4).
Nothing is written outside `mahalo-agentcore`; `mahalo-dock` is never touched.

---

## F. Files to create / modify (for the implementer, Task 7c)

Create:
- `infra-cdk/mahalo_infra/builder_stack.py` â€” `MahaloBuilderStack` (Â§A). No
  `DockerImageAsset` / `BundlingOptions`; mirrors the Gitea stack's offline-safe
  VPC/EC2 patterns; `role=` passed at construction; zero ingress.
- `scripts/builder-deploy.sh` â€” the builder-side staged deploy script (Â§B/Â§C/Â§D),
  phase-selectable, idempotent, `MAHALO_BUILD_IMAGE=1` exported throughout. Clone
  remote is the overridable `REPO_URL` script variable (default the public demo
  remote, Â§B.1); the frontend phase uses `--exclusively` on the two
  `MahaloFrontendStack` deploys and keeps the `MahaloApiStack` CORS deploy last
  (Â§C.4, MEDIUM-2).
- `docs/.agents/tasks/task7b-runbook.md` â€” operator runbook (Â§G), every block
  labelled `[VDI]` / `[builder]`.

Modify:
- `infra-cdk/app.py` â€” add the single `MahaloBuilderStack(app, "MahaloBuilderStack",
  env=_ENV)` line (Â§A.8).
- `infra-cdk/mahalo_infra/frontend_stack.py` â€” update the stale module docstring
  that says the `cdk synth --all` template count "stays 10" to **11** (MEDIUM-2).
  Update any other doc/comment that asserts "10 templates" the same way.
- `infra-cdk/tests/` â€” add a new `test_builder_stack.py` with per-stack
  `MahaloBuilderStack` assertions mirroring the existing per-stack test style
  (`assertions.Template.from_stack(...)`): the role has
  `AmazonSSMManagedInstanceCore`, the SG has **no ingress rule**, the instance is
  arm64 AL2023, and the stack synthesizes **no** `DockerImageAsset` (reuse the
  `test_gitea_stack.py::test_no_docker_image_asset` pattern, which asserts the
  literal substring `"DockerImage"` is absent from the synthesized template JSON).
  **NIT-3 (this round):** the coder MUST actually synth `MahaloBuilderStack` and
  confirm the `'DockerImage' not in text` assertion holds for the REAL template
  before relying on the reused pattern â€” the `AdministratorAccess` +
  `AmazonSSMManagedInstanceCore` role and the plain EC2/VPC/EBS resources
  introduce no `DockerImage*` resource, so it is expected to hold, but this must
  be verified against the generated template, not assumed. OPTIONALLY add a
  `test_app.py` asserting `len(app.synth().stacks) == 11` if a hard total-count
  gate is desired (MEDIUM-2) â€” there is no such assertion to "update" today, so
  this is a NEW test, not an edit.

Explicitly NOT modified by this design (flagged dependency, HIGH-2): `app.py`'s
`_GITEA_ENV` override to thread the real `GiteaPublicUrl` into the github mock â€”
that belongs to the real-github flow owned by `task7-deploy-runbook.md` and would
need its own CfnParameter/context design.

Implementation-verify items the coder must confirm on a live AL2023 arm64 host
(not architectural decisions): the exact Python 3.13 `dnf` package name, the
Node 24 install path, and the exact pinned `aws-cdk@2.x.y` CLI version that
matches `aws-cdk-lib>=2.251,<3`. Plus this round's NIT-3: synth
`MahaloBuilderStack` and confirm the reused `'DockerImage' not in text` assertion
actually holds against the real template (Â§F test bullet).

---

## G. Operator runbook outline (`task7b-runbook.md`)

Each block labelled with its credential context (NIT-3):

1. `[VDI]` `aws sso login --profile lava`; `aws sts get-caller-identity --profile lava`.
2. `[VDI]` `cd infra-cdk; cdk deploy MahaloBuilderStack --profile lava` â†’ note
   `BuilderInstanceId`.
3. `[VDI]` `aws ssm start-session --target <BuilderInstanceId> --profile lava
   --region us-east-1`.
4. `[builder]` (no `--profile`): the repo was already cloned to
   `~/mahalo-agentcore` by UserData at first boot (Â§A.5); run
   `bash ~/mahalo-agentcore/scripts/builder-deploy.sh --phase all` (toolchain
   re-clone/update + venvs â†’ backend â†’ runtime-api â†’ two-phase frontend with the
   `--exclusively`/step-5-CORS-last ordering; prints CfnOutputs). (Wait for
   `/var/log/builder-ready` / `cloud-init status --wait` first.)
5. `[builder]` optional real-github: `--phase gitea --admin-cidr <ip>/32` (stops
   after Gitea; follow `task7-deploy-runbook.md Â§3-5` for the mock flip).
6. `[VDI, browser]` validate at `FrontendUrl`: a READ, a HITL proposeâ†’approve
   WRITE, reject-writes-nothing, cross-message memory.
7. `[builder]` teardown app stacks: the single `cdk destroy <10 stacks> --force`
   (Â§D.1); CDK deletes in reverse dependency order. On any failure, **re-run the
   same command** (idempotent); if it still fails, use the Â§D.1 leaf-first
   fallback groups. Do this from the builder BEFORE step 8.
8. `[VDI] ONLY` `cdk destroy MahaloBuilderStack --profile lava` â€” terminate the
   builder **last, from the VDI**. **Never** run this from inside the builder's
   SSM session (it would kill the instance running the destroy mid-flight â€”
   MEDIUM-3).

---

## H. Responses to the design review findings

### H.0 Latest review (revision 3 â†’ this revision 4)

`docs/.agents/tasks/task7b-design-review.json` â€” verdict CHANGES_REQUESTED
(MEDIUMÃ—2, NITÃ—4). All six findings align with the original requirements (Aâ€“E)
and are resolved in this revision â€” none backlogged, none ignored:

- **MEDIUM-1 (`ssm send-command` invokes a not-yet-cloned script path, Â§B.5 /
  Â§A.5) â€” ADDRESSED.** Chose the "UserData does the initial clone" fix (over the
  two-command send-command) because it keeps the unattended kickoff a SINGLE
  command and also benefits the interactive path. Â§A.5 now has root UserData
  `git clone` the repo into `/home/ssm-user/mahalo-agentcore` and `chown -R
  ssm-user:ssm-user` it at first boot (best-effort/guarded so a boot-time network
  blip cannot abort UserData; the `toolchain` phase re-clones/updates
  idempotently). Â§B.5's single `send-command` is now self-contained on a fresh
  builder, with a note to wait for `/var/log/builder-ready` / `cloud-init status
  --wait` first. The old "UserData clones nothing" claim is removed; the NIT-6
  ownership reasoning is re-noted â€” root clones into ssm-user's home then chowns,
  so the ssm-user-run script owns every file it touches (no conflict).
- **MEDIUM-2 (frontend-phase `MahaloFrontendStack` deploys lack `--exclusively`,
  Â§C.4) â€” ADDRESSED.** Â§C.4 steps 2 and 4 now pass `--exclusively` (stated
  MANDATORY, with the reason: `MahaloFrontendStack` reads
  `api_stack.function.function_arn`, so a bare deploy would pull `MahaloApiStack`
  in with the placeholder `FrontendOrigin`). A new **phase ordering invariant**
  paragraph states step 5 (API CORS with the real `FrontendOrigin`) is ALWAYS the
  final deploy of the phase, that the script enforces this order internally, and
  that a partial `--phase frontend` re-run re-executes the whole ordered sequence
  so CORS can never be left pointing at `https://example.cloudfront.net`.
- **NIT-3 (`test_no_docker_image_asset` reuse asserted without synth, Â§F) â€”
  ADDRESSED.** Â§F's test bullet now states the coder MUST synth
  `MahaloBuilderStack` and confirm the `'DockerImage' not in text` assertion holds
  against the REAL template before relying on the reused pattern (noting the
  admin-role + plain EC2/VPC/EBS resources are expected to introduce no
  `DockerImage*` resource, but it must be verified, not assumed). Also added to
  the Â§F implementation-verify list.
- **NIT-4 (AMI SSM-parameter resolution unstated in the offline-synth guarantee,
  Â§E.2) â€” ADDRESSED.** Â§E.2 now explicitly notes that
  `latest_amazon_linux2023(cpu_type=ARM_64)` renders as a CloudFormation
  `AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>` reference resolved at DEPLOY
  time (no synth-time AWS call), identical to the Gitea stack's AMI handling and
  confirmed Docker-/credential-free by `test_gitea_stack.py` â€” not a `from_lookup`
  credentialed call.
- **NIT-5 (stale `--gitea-mode real` flag reference, Â§B.4) â€” ADDRESSED.** Â§B.4 no
  longer references `--gitea-mode real`; it now reads "Before `--phase gitea`,
  assert the two SSM params," and explicitly states no `--gitea-mode` flag exists
  (the Â§B.1 mapping defines only `--phase`, `--commit`, `--admin-cidr`; the gitea
  phase pre-flights the SSM params unconditionally).
- **NIT-6 (hardcoded clone URL, Â§B.1/Â§B.3/Â§A.5) â€” ADDRESSED.** The clone remote is
  now the overridable script variable `REPO_URL`
  (`${REPO_URL:-https://github.com/tjblavakumar/mahalo-agentcore.git}`), added to
  a new overridable-env table in Â§B.1, used in both Â§A.5 (UserData) and Â§B.3
  (toolchain phase) so they stay in sync, with a one-line note that a private
  remote would need an instance-role-readable credential (out of scope for the
  public demo).

### H.0-prev Prior review round (the earlier revision-2 â†’ revision-3 MEDIUMÃ—3/NITÃ—3) â€” fixes retained

These were resolved in the previous revision and still stand:

- **(prev) MEDIUM-1 (teardown destroy ordering/retry, Â§D.1) â€” ADDRESSED.** Â§D.1
  passes all ten stacks to one `cdk destroy` (CDK computes reverse dependency
  order), spells out the Frontendâ†’Apiâ†’Runtimeâ†’Memory/Gatewayâ†’mocks chain (Gitea
  independent), notes `--force` suppresses the prompt but not dependency errors,
  warns about `BucketDeployment`/`auto_delete_objects` custom-resource retry, and
  gives an idempotent re-run guard + a leaf-first fallback sequence.
- **(prev) MEDIUM-2 (nonexistent template-count assertion) â€” ADDRESSED.** There is
  no total-count assertion in `infra-cdk/tests/`; Â§A.8/Â§E.2/Â§F instruct fixing the
  stale "stays 10" docstring in `frontend_stack.py` to 11, adding a per-stack
  `test_builder_stack.py`, and OPTIONALLY a `test_app.py` with
  `len(app.synth().stacks) == 11` â€” all flagged as NEW, not an edit to a gate.
- **(prev) MEDIUM-3 (self-destruct teardown) â€” ADDRESSED.** Â§D.2 and Â§G step 8
  mark `cdk destroy MahaloBuilderStack` `[VDI] ONLY`, never from the builder's own
  SSM session.
- **(prev) NIT (builder-only cost framing, Â§E.1) â€” ADDRESSED.** Â§E.1 prices only
  the builder and scopes app-stack costs out.
- **(prev) NIT (flagâ†’env arg mapping, Â§B.1) â€” ADDRESSED.** The
  `--phase/--commit/--admin-cidr â†’ PHASE/COMMIT/ADMIN_CIDR` mapping is specified.
- **(prev) NIT (base-dir determinism, Â§B.1/Â§B.3) â€” ADDRESSED.** Every phase
  `cd "${BUILDER_HOME:-/home/ssm-user}"` before clone/venvs.

### H.1 Original review round (HIGHÃ—2, MEDIUMÃ—5, NITÃ—4) â€” fixes retained

The first `task7b-design-review` iteration was resolved in an earlier revision and
those fixes still stand; recorded here for continuity (the NIT numbers below are
that original round's, distinct from Â§H.0's latest-round numbering):

- **HIGH-1 (instance role mechanism) â€” ADDRESSED.** Â§A.4 now specifies passing
  `role=` at `ec2.Instance` construction (the L2 auto-creates the
  `CfnInstanceProfile`), shows the exact code, states `.role` is read-only
  post-build, and removes the false "same mechanism in the repo" claim (the Gitea
  instance has no role and is not precedent).
- **HIGH-2 (gitea-real URL wiring gap) â€” ADDRESSED.** Â§B.3 `--phase gitea` now
  stops after `cdk deploy MahaloGiteaStack` + printing `GiteaPublicUrl`, and does
  NOT emit `cdk deploy MahaloMockGithubStack -c giteaMode=real`. The real-github
  flip (including the `app.py` `_GITEA_ENV` override) is explicitly deferred to
  `task7-deploy-runbook.md` and flagged in Â§F as an `app.py` dependency outside
  this design.
- **MEDIUM-1 (`ssm-user` docker-group race) â€” ADDRESSED.** Â§A.5: the deploy script
  runs docker via passwordless `sudo` (not group membership); the `usermod` line
  is guarded `â€¦ 2>/dev/null || true` and declared non-load-bearing; top-level
  UserData drops `-e` so no single step aborts boot.
- **MEDIUM-2 (gitea SSM param pre-flight) â€” ADDRESSED.** Â§B.3 `--phase gitea`
  (real) now pre-flights `/mahalo/gitea/adapter-token` and
  `/mahalo/gitea/admin-password` via `aws ssm get-parameter` and fails fast with a
  pointer to the task7 runbook Â§1.
- **MEDIUM-3 (frontend build command/dir unverified) â€” ADDRESSED.** Â§C.3 verifies
  against this project's `frontend/package.json` (`"build": "next build"`, Next
  16.3.3) and `frontend/next.config.ts` (`output: "export"` â†’ `out/` by default),
  matching `frontend_stack.py`'s `_FRONTEND_OUT`. Cites the AGENTS.md read-the-docs
  caveat.
- **MEDIUM-4 (API re-deploy drops bundled deps) â€” ADDRESSED.** Â§B.3/Â§C.4 step 5:
  `MAHALO_BUILD_IMAGE=1` is exported for the whole script and set unconditionally
  whenever `MahaloApiStack` is deployed, including the CORS re-deploy and any
  standalone `--phase frontend` re-run (step 5 also passes `-c buildImage=1`
  explicitly as belt-and-suspenders).
- **MEDIUM-5 (bootstrap assumption/fallback) â€” ADDRESSED.** Â§B.3 `--phase backend`
  resolves `ACCOUNT` via `sts get-caller-identity` FIRST, then
  `describe-stacks CDKToolkit || cdk bootstrap aws://$ACCOUNT/us-east-1`; states
  bootstrap is Docker-free (standard template) under the admin role; treats
  "already bootstrapped" as an expectation, not a fact.
- **NIT-1 (AL2023 Python 3.13 package name) â€” ADDRESSED.** Â§A.5 marks it an
  implementation-verify item with a tolerant install (`|| â€¦ || true`) and a
  `uv`/pyenv fallback; listed in Â§F.
- **NIT-2 (template count 10â†’11 unverified) â€” ADDRESSED, then SUPERSEDED by
  latest MEDIUM-2.** Â§A.8/Â§E.2 require the coder to run `cdk list`/`cdk synth
  --all` and confirm exactly 11. (A sandbox synth during authoring could not
  finish â€” credential-gated/slow â€” so 11 is derived from `app.py`'s source count
  of 10.) NOTE: the revision-2 phrasing "update the gate assertion" was WRONG â€”
  no such assertion exists; see H.0 MEDIUM-2 and Â§A.8/Â§E.2/Â§F for the corrected
  docstring-fix + optional new-test guidance.
- **NIT-3 (VDI vs builder credential contexts) â€” ADDRESSED.** Â§B.1 and the Â§G
  runbook label every command block `[VDI]` (with `--profile lava`) or `[builder]`
  (instance role, no `--profile`).
- **NIT-4 (floating CDK CLI) â€” ADDRESSED.** Â§A.5/Â§F pin the CDK CLI to a `2.x.y`
  matching `aws-cdk-lib>=2.251,<3` rather than floating `aws-cdk@2`.

**Design document written to:** `docs/.agents/tasks/task7b-design.md`
