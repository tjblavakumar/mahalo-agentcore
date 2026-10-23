# Task 7b — Implementation Plan: EC2 Docker builder deploy path

**Mode:** planned from the APPROVED design (`docs/.agents/tasks/task7b-design.md`;
review `docs/.agents/tasks/task7b-design-review.json` verdict APPROVED). The
architecture is already decided; this plan sequences the work faithfully without
re-deciding it.

**Scope rules (from the task):** only create/modify files UNDER the
`mahalo-agentcore` workspace; never touch `mahalo-dock`. No git commit/push. New
scripts go under `scripts/`. All new CDK must stay offline-synthable (NO Docker).
Operator commands are Windows PowerShell (VDI); the EC2 builder is Linux bash.

**Grounding (files read):** `infra-cdk/app.py` (currently 10 app stacks),
`infra-cdk/mahalo_infra/runtime_stack.py`, `api_stack.py`, `gitea_stack.py`
(the offline-safe VPC/EC2 pattern this plan mirrors), `frontend_stack.py`
(the `"stays 10"` stale docstring at line 20; `_FRONTEND_OUT = frontend/out`),
`agent/Dockerfile` (line 14 `FROM --platform=linux/arm64 python:3.13-slim`),
`infra-cdk/requirements.txt` (`aws-cdk-lib>=2.251,<3`),
`infra-cdk/tests/test_gitea_stack.py` (the per-stack assertion style + the
`test_no_docker_image_asset` `"DockerImage" not in text` pattern to reuse),
`docs/STATUS.md`, `docs/CONTINUATION.md`.

**Test/build commands (discovered):** from `infra-cdk/` with its `.venv` active —
`pytest tests -q` (baseline today: 42 passed, 1 skipped) and
`cdk synth --all` (exit 0; today 10 app templates + offline, Docker-free). The
infra-cdk dev dep is `pytest` (`infra-cdk/requirements-dev.txt`).

> NOTE: adding `MahaloBuilderStack` takes `app.py` from **10 → 11** app stacks.
> (The "8 templates" figure in STATUS.md/CONTINUATION.md predates Tasks 7's
> Gitea+Frontend stacks, which `app.py` already contains = 10; this plan uses the
> code fact of 10→11.)

---

- [ ] 1. Create `MahaloBuilderStack` — offline-synthable arm64 EC2 builder stack.
      Create the stack mirroring `gitea_stack.py`'s offline-safe pattern: an
      `availability_zones` property override returning `[f"{self.region}a"]`; a
      dedicated `ec2.Vpc(max_azs=1, nat_gateways=0)` with a single PUBLIC subnet
      (created, not looked up); a security group `allow_all_outbound=True` with
      **ZERO ingress rules**; an `iam.Role` (assumed_by `ec2.amazonaws.com`) with
      managed policies `AmazonSSMManagedInstanceCore` + `AdministratorAccess`
      (lifetime-scoped, comment the justification per design §A.4); an
      `ec2.Instance` built with `role=role` passed at construction (L2
      auto-creates the instance profile — do NOT assign `.role` after build),
      `machine_image=ec2.MachineImage.latest_amazon_linux2023(cpu_type=ec2.AmazonLinuxCpuType.ARM_64)`,
      instance type from a `CfnParameter BuilderInstanceType` (default
      `t4g.large`), `block_devices` = 40 GiB gp3 `delete_on_termination=True`
      (size from `CfnParameter BuilderVolumeSizeGiB` default 40), and the UserData
      from item 2. After construction set
      `instance.instance.associate_public_ip_address = True` and
      `instance.apply_removal_policy(RemovalPolicy.DESTROY)`. Emit CfnOutputs
      `BuilderInstanceId` and `BuilderPublicDns`. No `DockerImageAsset` / no
      `BundlingOptions`.
      Files: `infra-cdk/mahalo_infra/builder_stack.py`
      Verify: `cd infra-cdk && cdk synth MahaloBuilderStack` exits 0 with no
      Docker/credentials (offline), producing one CloudFormation template.

- [ ] 2. Add the UserData toolchain bootstrap + initial clone (inside item 1's stack).
      Build an `ec2.UserData.for_linux()` that runs as root with
      `set -uxo pipefail` (NOT `-e` at top level — each critical step guarded so a
      single failure cannot abort boot): `dnf install -y docker` +
      `systemctl enable --now docker`; a guarded best-effort
      `usermod -aG docker ssm-user 2>/dev/null || true`; `dnf install -y git`;
      Node 24 (NodeSource/nvm path the coder confirms for AL2023 arm64); Python
      3.13 via a tolerant install (`dnf install -y python3.13 python3.13-pip ||
      dnf install -y python3.13 || true`, `uv`/pyenv fallback); AWS CLI v2 (verify
      present); CDK CLI pinned to a `2.x.y` matching `aws-cdk-lib>=2.251,<3`
      (e.g. `npm install -g aws-cdk@2.251.x` — pin the exact confirmed version,
      not floating `aws-cdk@2`); an initial best-effort guarded
      `git clone "$REPO_URL" /home/ssm-user/mahalo-agentcore 2>/dev/null || true`
      (`REPO_URL` = `https://github.com/tjblavakumar/mahalo-agentcore.git`) then
      `chown -R ssm-user:ssm-user /home/ssm-user/mahalo-agentcore 2>/dev/null ||
      true`; finally `echo "builder toolchain ready" > /var/log/builder-ready`.
      This makes the §B.5 unattended `send-command` self-contained (script path
      exists at first boot). The exact Python 3.13 package name, Node 24 install
      path, and exact CDK CLI version are implementation-verify-on-host items.
      Files: `infra-cdk/mahalo_infra/builder_stack.py`
      Verify: `cd infra-cdk && cdk synth MahaloBuilderStack` still exits 0
      offline; the rendered `AWS::EC2::Instance` `UserData` contains `dnf install
      -y docker` and the `/var/log/builder-ready` marker.

- [ ] 3. Wire `MahaloBuilderStack` into the CDK app.
      Add the import and one construct line
      `MahaloBuilderStack(app, "MahaloBuilderStack", env=_ENV)` in `app.py`,
      mirroring the other standalone stacks (no cross-references).
      Files: `infra-cdk/app.py`
      Verify: `cd infra-cdk && cdk list` reports exactly **11** stacks including
      `MahaloBuilderStack`; `cdk synth --all` exits 0 offline (11 templates,
      Docker-free).

- [ ] 4. Fix the stale "stays 10" template-count docstring.
      Update the `frontend_stack.py` module docstring line that says the
      `cdk synth --all` template count "stays 10" to **11** (and any other
      doc/comment in `infra-cdk/` asserting "10 templates"). There is NO
      executable total-count assertion to edit (verified — all tests are
      per-stack).
      Files: `infra-cdk/mahalo_infra/frontend_stack.py`
      Verify: `grep` returns no remaining "stays 10"/"template count stays 10" in
      `infra-cdk/`; `cd infra-cdk && pytest tests -q` still passes (no behavior
      change).

- [ ] 5. Add per-stack assertion tests for `MahaloBuilderStack`.
      Create `test_builder_stack.py` mirroring `test_gitea_stack.py`'s
      `assertions.Template.from_stack(...)` style. Cover: exactly one VPC + one
      public subnet + zero NAT gateways; one `AWS::EC2::Instance`; the security
      group has **no ingress rule** (`SecurityGroupIngress` absent/empty); the
      instance is arm64 AL2023; a 40 GiB gp3 root volume with
      `DeleteOnTermination`; the role carries `AmazonSSMManagedInstanceCore`;
      CfnOutputs `BuilderInstanceId` + `BuilderPublicDns` present; and reuse the
      `"DockerImage" not in text` assertion against the REAL synthesized template
      (confirm it actually holds — the admin role + plain EC2/VPC/EBS introduce no
      `DockerImage*` resource). OPTIONALLY add `test_app.py` asserting
      `len(app.synth().stacks) == 11` if a hard total-count gate is wanted (NEW
      test, not an edit).
      Files: `infra-cdk/tests/test_builder_stack.py` (optional
      `infra-cdk/tests/test_app.py`)
      Verify: `cd infra-cdk && pytest tests/test_builder_stack.py -q` passes;
      `pytest tests -q` passes overall (previous 42/1 baseline plus the new
      builder tests).

- [ ] 6. Create the builder-side deploy script `scripts/builder-deploy.sh`.
      Author the idempotent, phase-selectable bash script run ON the builder
      (interactive SSM shell or `ssm send-command`). Arg parser maps
      `--phase <name>`→`PHASE`, `--commit <sha>`→`COMMIT`,
      `--admin-cidr <cidr>`→`ADMIN_CIDR`; overridable env `REPO_URL` (default the
      public demo remote), `BUILDER_HOME` (default `/home/ssm-user`), `COMMIT`
      (default `origin/main` HEAD). Every phase begins
      `cd "${BUILDER_HOME:-/home/ssm-user}"` then enters `mahalo-agentcore`.
      Export `AWS_REGION`/`AWS_DEFAULT_REGION=us-east-1` and
      `MAHALO_BUILD_IMAGE=1` ONCE at top and keep exported for the whole run. All
      `aws`/`cdk` commands on the builder use the instance role (NO `--profile`).
      Phases:
      `toolchain` (verify/install git, Docker-via-sudo, Node 24, Python 3.13, AWS
      CLI v2, pinned CDK CLI; clone-or-fetch `$REPO_URL`@`$COMMIT`; create+install
      `infra-cdk/.venv` and `agent/.venv`; assert `node --version` 24.x and
      `sudo docker info`);
      `backend` (resolve `ACCOUNT` via `sts get-caller-identity` FIRST, then
      `describe-stacks CDKToolkit || cdk bootstrap aws://$ACCOUNT/us-east-1`; then
      `cdk deploy` the 4 `MahaloMock*Stack` + Gateway + MemoryIdentity
      `--require-approval never --outputs-file /tmp/mahalo-backend-outputs.json`);
      `runtime-api` (`cdk deploy MahaloRuntimeStack MahaloApiStack
      --require-approval never --outputs-file /tmp/mahalo-rtapi-outputs.json` —
      the Docker reason the builder exists);
      `frontend` (the two-phase build, item 7);
      `gitea` (pre-flight `/mahalo/gitea/adapter-token` +
      `/mahalo/gitea/admin-password`, fail fast with task7-runbook pointer; then
      `cdk deploy MahaloGiteaStack --parameters AdminCidr="${ADMIN_CIDR:?set
      --admin-cidr}" --require-approval never --outputs-file
      /tmp/mahalo-gitea-outputs.json`; print `GiteaPublicUrl`; DO NOT emit the
      `giteaMode=real` github flip — defer to task7-deploy-runbook);
      `all` (runs toolchain→backend→runtime-api→frontend; NOT gitea). Fail-fast
      guards before expensive steps (`sts get-caller-identity`, `sudo docker
      info`, non-empty `NEXT_PUBLIC_*`). Parse each `--outputs-file` and write a
      consolidated `/tmp/mahalo-outputs.env` plus a human-readable summary.
      Files: `scripts/builder-deploy.sh`
      Verify: `bash -n scripts/builder-deploy.sh` (syntax OK) and, if available,
      `shellcheck scripts/builder-deploy.sh` reports no errors; the script's
      `--help`/usage lists the five phases. (Full deploy is an operator/live step,
      not run here.)

- [ ] 7. Implement the two-phase frontend build inside the `frontend` phase.
      In `scripts/builder-deploy.sh`'s `frontend` phase, enforce this exact
      order: (2) `cdk deploy MahaloFrontendStack --exclusively --require-approval
      never --outputs-file /tmp/mahalo-fe-outputs.json` (MANDATORY `--exclusively`
      so the API is not pulled in with the placeholder origin); read
      `RUNTIME_API_URL` (from rtapi outputs), `IDENTITY_POOL_ID`, `FRONTEND_URL`;
      (3) fail-fast `: "${RUNTIME_API_URL:?}"; : "${IDENTITY_POOL_ID:?}"`, then
      `cd frontend && npm ci` and
      `NEXT_PUBLIC_API_URL="$RUNTIME_API_URL" NEXT_PUBLIC_AWS_REGION=us-east-1
      NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID="$IDENTITY_POOL_ID" npm run build`,
      then `test -f out/index.html`; (4) `cdk deploy MahaloFrontendStack
      --exclusively -c buildFrontend=1 --require-approval never`; (5) LAST —
      `cdk deploy MahaloApiStack -c buildImage=1 --parameters
      FrontendOrigin="$FRONTEND_URL" --require-approval never` (keeps
      `MAHALO_BUILD_IMAGE=1` so the API is not downgraded to the plain asset). A
      partial `--phase frontend` re-run re-executes the whole ordered sequence.
      Files: `scripts/builder-deploy.sh`
      Verify: `bash -n scripts/builder-deploy.sh` OK; inspection confirms steps 2
      and 4 pass `--exclusively` and step 5 (API CORS with real `FrontendOrigin`)
      is the final deploy of the phase.

- [ ] 8. Write the operator runbook `docs/.agents/tasks/task7b-ec2-builder-runbook.md`.
      Author the operator runbook with every block labelled `[VDI]` (PowerShell,
      `--profile lava`) or `[builder]` (bash, instance role, no `--profile`):
      (1) `[VDI]` `aws sso login --profile lava` + `aws sts get-caller-identity
      --profile lava`; (2) `[VDI]` `cd infra-cdk; cdk deploy MahaloBuilderStack
      --profile lava` → note `BuilderInstanceId`; (3) `[VDI]` `aws ssm
      start-session --target <id> --profile lava --region us-east-1` (and the
      optional `ssm send-command` AWS-RunShellScript one-liner, with a note to
      wait for `/var/log/builder-ready` / `cloud-init status --wait` first);
      (4) `[builder]` `bash ~/mahalo-agentcore/scripts/builder-deploy.sh --phase
      all` (prints CfnOutputs); (5) `[builder]` optional `--phase gitea
      --admin-cidr <ip>/32`; (6) `[VDI, browser]` validate at `FrontendUrl`
      (a READ, a HITL propose→approve WRITE, reject-writes-nothing,
      cross-message memory); (7) `[builder]` teardown app stacks — the single
      `cdk destroy` of all ten app stacks `--force` (CDK computes reverse-dep
      order), re-run on failure (idempotent), leaf-first fallback groups listed;
      (8) `[VDI] ONLY` `cdk destroy MahaloBuilderStack --profile lava` LAST, never
      from inside the builder's own SSM session (it would kill the instance
      running the destroy). Include the ECR bootstrap-repo image cost note (§D.3).
      Files: `docs/.agents/tasks/task7b-ec2-builder-runbook.md`
      Verify: the runbook contains labelled `[VDI]`/`[builder]` blocks for all 8
      steps, both teardowns (app stacks from the builder, builder from the VDI
      last), and exact copy-paste commands; manually read through end-to-end for
      command/context correctness.

- [ ] 9. Record the EC2-builder deploy path in STATUS.md + CONTINUATION.md.
      Update `docs/STATUS.md` and `docs/CONTINUATION.md` to document the new
      no-local-Docker deploy path: the operator deploys `MahaloBuilderStack` from
      the VDI (Docker-free synth), connects via SSM, runs
      `scripts/builder-deploy.sh` on the arm64 EC2 builder to do the full staged
      deploy, validates in the browser, then tears down BOTH the app stacks (from
      the builder) and the builder (from the VDI, last). Note the stack count is
      now 11 and point to `docs/.agents/tasks/task7b-ec2-builder-runbook.md` and
      `task7b-design.md`. Keep the existing live-deploy prereqs accurate (the
      local-Docker path is superseded for the VDI by the builder).
      Files: `docs/STATUS.md`, `docs/CONTINUATION.md`
      Verify: both docs reference the EC2-builder path, the runbook path, and the
      11-stack count; read through for internal consistency with the rest of each
      doc.

- [ ] 10. Final offline gate — confirm nothing regressed and the gate stays Docker-free.
      Run the full infra-cdk offline gate.
      Files: (none — verification only)
      Verify: `cd infra-cdk && pytest tests -q` passes (prior 42/1 plus the new
      builder tests) and `cdk synth --all` exits 0 offline with **11** templates
      and no Docker invocation; confirm `mahalo-dock` was never written and no git
      commit/push was performed.

## Notes / assumptions

- Implementation-verify-on-host (not architectural): the exact AL2023 arm64
  Python 3.13 `dnf` package name, the Node 24 install path, and the exact pinned
  `aws-cdk@2.x.y` CLI version matching `aws-cdk-lib>=2.251,<3`. The design marks
  these as live-host confirmations; the plan carries tolerant fallbacks.
- The `giteaMode=real` github flip is explicitly OUT of scope (it needs an
  `app.py` `_GITEA_ENV` change owned by `task7-deploy-runbook.md`); the `gitea`
  phase stops after deploying the Gitea host.
- STATUS.md/CONTINUATION.md currently cite "8 templates" (pre-Gitea/Frontend);
  `app.py` as read contains 10 app stacks, so the builder makes 11. The plan uses
  the code fact.
