# Task 7b â€” Design Review: "EC2 Docker builder" deploy path

**Reviewed document:** `docs/.agents/tasks/task7b-design.md` (revision 4)
**Grounded in:** `docs/.agents/tasks/task7b-investigation.md`,
`infra-cdk/app.py`, `infra-cdk/mahalo_infra/runtime_stack.py`,
`infra-cdk/mahalo_infra/api_stack.py`, `infra-cdk/mahalo_infra/gitea_stack.py`,
`infra-cdk/mahalo_infra/frontend_stack.py`, `agent/Dockerfile`,
`frontend/package.json`, `frontend/next.config.ts`,
`frontend/src/services/api.ts`, `infra-cdk/tests/*`.
**Reviewer stance:** fresh read, no prior context. Every load-bearing claim was
checked against the actual source rather than taken on the design's word.

**Verdict:** APPROVED (0 HIGH, 0 MEDIUM, 2 NIT).

---

## Scope coverage (the five mandated checks Aâ€“E)

- **(A) Builder provisioning** â€” resolved. A dedicated `MahaloBuilderStack` CDK
  stack that synthesizes pure CloudFormation (no `DockerImageAsset`, no
  `BundlingOptions`), so it synths Docker-free on the VDI (Â§A.1, Â§E.2). arm64/
  Graviton is specified as mandatory and tied to the ARM64 agent image (Â§A.2).
  IAM scope is `AdministratorAccess` + `AmazonSSMManagedInstanceCore`, with an
  explicit lifetime-scoped justification for a transient single-owner-account
  builder (Â§A.4). SSM Session Manager access, zero ingress (Â§A.3, Â§A.5).
- **(B) Idempotent builder-side bash deploy** â€” resolved. Phase-selectable,
  idempotent `scripts/builder-deploy.sh` with flagâ†’env mapping, deterministic
  base dir, exact staged `cdk deploy` commands, `MAHALO_BUILD_IMAGE=1` exported
  throughout, and the two-phase frontend build (Â§B, Â§C).
- **(C) Output capture + frontend ordering** â€” resolved. `--outputs-file` per
  deploy, consolidated env, NEXT_PUBLIC_* injected into the `npm run build`
  environment before the bundle upload, chicken-and-egg broken by deploy-infra â†’
  read-outputs â†’ build â†’ deploy-bundle (Â§C.1â€“C.4). BucketDeployment confirmed to
  need no Docker (Â§C.2).
- **(D) Teardown of both builder and app stacks + ECR cleanup** â€” resolved.
  App-stack destroy from the builder (reverse-dependency order, idempotent
  re-run + leaf-first fallback), builder destroy from the VDI only, ECR
  bootstrap-repo image lingering noted with `cdk gc`/manual cleanup (Â§D.1â€“D.3).
- **(E) Cost/safety + offline Docker-free synth** â€” resolved. Builder cost
  itemized, app-stack cost scoped out, offline-synth guarantee stated with the
  AMI SSM-parameter resolution clarified as deploy-time, not synth-time (Â§E).

---

## Findings

### 1. NIT â€” `agent/Dockerfile` line citation is wrong (Â§A.2)

**Where:** Â§A.2 "CPU architecture" bullet states
`agent/Dockerfile:8 FROM --platform=linux/arm64 â€¦`.

**Problem:** In the actual file the `FROM --platform=linux/arm64 python:3.13-slim`
directive is on **line 14**, not line 8 (lines 1â€“13 are the header comment block).
The investigation document cites line 14 correctly; the design regressed the
citation. The architectural claim itself (ARM64 is mandatory, pinned in the
Dockerfile and matched by `runtime_stack.py:60`
`platform=ecr_assets.Platform.LINUX_ARM64`) is correct and verified â€” only the
line number is off. No implementation impact.

**Fix:** Change the citation to `agent/Dockerfile:14`:

```
The agent image is ARM64 (`agent/Dockerfile:14` `FROM --platform=linux/arm64 â€¦`;
`runtime_stack.py:60` `platform=ecr_assets.Platform.LINUX_ARM64`) â€¦
```

### 2. NIT â€” absolute, drive-letter artifact path in the header (line 10)

**Where:** Header, line 10: ``The read-only fallback
`<FALLBACK_ROOT>` is NEVER written.``

**Problem:** The review brief states that any absolute artifact path in the design
is a finding. `<FALLBACK_ROOT>` is an absolute,
drive-letter-rooted path. It appears inside a "never written" guard (so it causes
no behavior), but it is still an absolute path embedded in the design and it is
machine/user-specific, which does not travel with the repo. Everything else in the
design correctly uses forward-slash workspace-relative paths (e.g.
`docs/.agents/tasks/â€¦`, `infra-cdk/â€¦`) or builder-side POSIX absolute paths
(`/home/ssm-user/â€¦`, `/tmp/â€¦`) which are legitimate runtime paths, not
workspace-artifact references.

**Fix:** Replace the host-specific absolute path with a generic description, e.g.:

```
**Workspace:** `mahalo-agentcore` only. The read-only `mahalo-dock` fallback
workspace is NEVER written.
```

---

## Verified Assumptions (checked against source, found correct)

1. **Exactly two deploy actions need Docker, both flag-gated.** Confirmed:
   `runtime_stack.py:56-68` â€” `from_asset(..., platform=LINUX_ARM64)` on the
   `build_image` branch vs `from_image_uri(CfnParameter)` on the default branch;
   `api_stack.py:49-70` â€” `BundlingOptions(image=PYTHON_3_13.bundling_image, â€¦)`
   on the build branch vs plain `Code.from_asset(_API_DIR)` on the default
   branch. Both gated by `node.try_get_context("buildImage")` OR
   `MAHALO_BUILD_IMAGE == "1"`.
2. **Gitea needs no deploy-time Docker.** Confirmed: `gitea_stack.py` runs
   `gitea/gitea:1.27.3` by string reference in UserData (`_GITEA_IMAGE`,
   `docker run â€¦`), never a `DockerImageAsset`.
3. **Frontend BucketDeployment needs no Docker.** Confirmed:
   `frontend_stack.py` gates `s3deploy.BucketDeployment(sources=[Source.asset(
   _FRONTEND_OUT)])` behind `buildFrontend`; it uploads the prebuilt `out/`
   directory, no bundling image.
4. **Frontend build command and output dir.** Confirmed:
   `frontend/package.json` `"build": "next build"`, `next 16.3.3`;
   `frontend/next.config.ts` sets `output: "export"` + `images: {unoptimized:
   true}`, so `next build` emits `frontend/out/`, matching `_FRONTEND_OUT` in
   `frontend_stack.py`.
5. **NEXT_PUBLIC_* consumption.** Confirmed: `frontend/src/services/api.ts` reads
   `process.env.NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_AWS_REGION`,
   `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID` with silent fallbacks â€” so they must be
   set in the `npm run build` environment (the design's Â§C.4 ordering is correct).
6. **`FrontendOrigin` default placeholder.** Confirmed:
   `api_stack.py` `CfnParameter("FrontendOrigin", default=
   "https://example.cloudfront.net")`, so the Â§C.4 step-5 CORS re-deploy with the
   real `FrontendUrl` is genuinely required.
7. **`--exclusively` necessity on the frontend-phase deploys.** Confirmed:
   `frontend_stack.py` reads `api_stack.function.function_arn`, making
   `MahaloApiStack` a CDK dependency of `MahaloFrontendStack`; a bare
   `cdk deploy MahaloFrontendStack` would pull the API in and re-deploy it with
   the default `FrontendOrigin` placeholder. The Â§C.4 MEDIUM-2 resolution is
   sound.
8. **`MAHALO_BUILD_IMAGE=1` must stay set on the CORS re-deploy.** Confirmed:
   without it `api_stack.py` takes the plain-asset branch (no fastapi/mangum),
   so the design's "exported throughout" rule (Â§B.3/Â§C.4 step 5) is correct.
9. **CfnOutput names.** Confirmed present: `RuntimeArn` (`runtime_stack.py`),
   `RuntimeApiUrl` (`api_stack.py`), `IdentityPoolId` + `FrontendUrl`
   (`frontend_stack.py`), `GiteaPublicUrl` + `GiteaInstanceId` (`gitea_stack.py`).
   `MemoryId`/`GatewayMcpUrl` referenced from the memory/gateway stacks per the
   investigation.
10. **`app.py` stack count = 10 today; no `_GITEA_ENV` CfnParameter override.**
    Confirmed: 4 mocks + Gateway + MemoryIdentity + Runtime + Api + Gitea +
    Frontend = 10; `_GITEA_ENV` is a module-level dict hardcoding
    `gitea.internal`/`gitea.public` with no CfnParameter/context override â€” so the
    design's HIGH-2 deferral of the real-github flip to `task7-deploy-runbook.md`
    is justified.
11. **No total-template-count test assertion exists.** Confirmed: every file in
    `infra-cdk/tests/` uses per-stack `assertions.Template.from_stack(...)` +
    `resource_count_is(...)`; there is no `len(app.synth().stacks)` gate. The
    only "10" is the prose docstring in `frontend_stack.py`. The design's MEDIUM-2
    correction (fix the docstring to 11, optionally add a NEW `test_app.py`) is
    accurate.
12. **`test_no_docker_image_asset` reuse pattern.** Confirmed:
    `test_gitea_stack.py::test_no_docker_image_asset` asserts
    `"DockerImage" not in text` against the synthesized template â€” the pattern the
    design tells the coder to reuse for `test_builder_stack.py` exists as described
    (`test_runtime_stack.py` has an analogous offline-branch assertion too).
13. **Teardown posture.** Confirmed: `frontend_stack.py` bucket is
    `auto_delete_objects=True` + `RemovalPolicy.DESTROY`; `gitea_stack.py` EBS is
    `delete_on_termination=True` with a `DeletionPolicy` conditioned on
    `RetainGiteaData` (default Delete). The Â§D claims hold.
14. **`associate_public_ip_address` precedent.** Confirmed:
    `gitea_stack.py` sets `instance.instance.associate_public_ip_address = True`,
    the exact line Â§A.3 says it mirrors.
15. **Gitea has inbound rules; builder will not.** Confirmed: `gitea_stack.py`
    adds ingress on 22 (AdminCidr) and 3000 (GiteaIngressCidr). The design's
    "mirror the VPC pattern but with zero ingress" (Â§A.3) is a correct, deliberate
    divergence, not a copy error.
16. **Referenced existing runbook exists; new runbook uses correct prefix/path.**
    Confirmed: `docs/.agents/tasks/task7-deploy-runbook.md` exists (referenced,
    not created); the design's new artifact is
    `docs/.agents/tasks/task7b-runbook.md` (correct `task7b-` prefix, under
    `docs/.agents/tasks/`, to be created in Task 7c).

## Unverified / Wrong Assumptions

- **WRONG â€” `agent/Dockerfile` line number (Finding 1).** The design cites line 8
  for the `FROM --platform=linux/arm64` directive; it is actually line 14. The
  underlying architectural claim is correct; only the citation is wrong.
- **Deferred to implementation (correctly flagged by the design, not review
  gaps):** the exact AL2023 arm64 `dnf` package name for Python 3.13, the Node 24
  install path, the exact pinned `aws-cdk@2.x.y` CLI version, and the live-synth
  confirmation that `MahaloBuilderStack` emits no `DockerImage*` resource and that
  `cdk synth --all` reports 11 templates. These are explicitly labelled
  implementation-verify items in Â§F; they are not architectural ambiguities and
  cannot be resolved from source at design time (they require a live AL2023 arm64
  host / a credentialed synth). Not counted as findings.
- **Not independently re-verified by this review (accepted from design/
  investigation):** `MemoryId` and `GatewayMcpUrl` output names in the
  memory/gateway stacks (asserted in the investigation and consistent with the
  stacks' role in the staged sequence); the precise `cdk bootstrap` template being
  Docker-free (standard CDK behavior, not a repo fact). These do not affect the
  verdict.

---

## Verdict rationale

Zero HIGH and zero MEDIUM findings. Both findings are NIT: a wrong source-line
citation and a host-specific absolute path inside a "never written" guard â€”
neither introduces ambiguity, a feasibility gap, a wrong assumption that would
break implementation, or scope creep. Per the mechanical rule (HIGH + MEDIUM ==
0 â†’ APPROVED), the verdict is **APPROVED**. The two NITs are worth fixing for
accuracy but do not block implementation.
