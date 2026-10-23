# Task 7b code review — EC2 Docker-builder deploy path (FEAT-002 + FEAT-003)

Reviews the builder-side deploy script `scripts/builder-deploy.sh` (FEAT-002), the
operator runbook `docs/.agents/tasks/task7b-ec2-builder-runbook.md` (FEAT-003), and
the `docs/STATUS.md` / `docs/CONTINUATION.md` updates (FEAT-003), against the
APPROVED design `docs/.agents/tasks/task7b-design.md` (§B/§C/§D/§G) and the FEAT-002 /
FEAT-003 acceptance criteria. The script runs on a transient arm64 EC2 builder inside
an SSM shell; it drives the full staged `cdk deploy` of the 10 app stacks using the
instance-role credential chain, performs the two-phase frontend build, and captures
CfnOutputs. The runbook ties the VDI-side and builder-side command contexts together
and documents teardown. STATUS/CONTINUATION record the VDI-no-Docker builder path.

Watch for: nothing blocking. The coder's self-verification (`task7b-verification.md`)
recorded `bash -n` clean, an offline `cdk synth` of all 11 templates, and the
infra-cdk suite at 66 passed / 1 skipped; I re-confirmed the three grep-checkable
invariants (both frontend deploys `--exclusively`, no executable `giteaMode=real`, no
`--profile` anywhere) directly on disk (confirmed). One non-blocking observation: the
frontend phase re-reads `RUNTIME_API_URL` from the rtapi outputs file but never
records it to the consolidated env (possible — cosmetic, see below).

**Verdict**: APPROVED

## High-level view

The script gates every builder-side action on the instance-role chain and carries no
`--profile` — the credential-context split the design demands (VDI uses `--profile lava`,
builder uses the instance role) is enforced structurally, not just documented. Flags are
exactly `--phase`/`--commit`/`--admin-cidr`; there is no `--gitea-mode`.

`MAHALO_BUILD_IMAGE=1` is exported once at the top and never unset, so the two
Docker-dependent deploys (Runtime image, Api Lambda bundle) always take the bundled
branch — including the frontend phase's final CORS re-deploy of `MahaloApiStack`, which
is the hazard the design (MEDIUM-4) flagged.

The staged order matches §B: backend group → runtime-api → the two-phase frontend with
both `MahaloFrontendStack` deploys `--exclusively` and the `MahaloApiStack` CORS deploy
strictly last, then an opt-in gitea phase that deploys `MahaloGiteaStack` and stops — no
real-github flip is emitted (the HIGH-2 resolution). `--phase all` deliberately excludes
gitea.

The runbook mirrors the script's phases and flags, labels every block `[VDI]` or
`[builder]`, tears down the app stacks from the builder and the builder from the VDI last
with an explicit self-destruct warning, covers browser validation (READ + two-call
propose→approve HITL + reject-writes-nothing + session memory), and carries the ECR
bootstrap-repo residual-cost note. STATUS and CONTINUATION both record the builder deploy
path, the 11-stack count, and the resume pointer.

The coder recorded its own verification evidence; no test suite or synth was re-run for
this review, and no writes left the workspace.

<details>
<summary>Issues (1)</summary>

1. **RuntimeApiUrl not in consolidated env (non-blocking)** — the frontend phase reads
   `RUNTIME_API_URL` from the rtapi outputs file for the build but never calls
   `record_output RuntimeApiUrl`; the runtime-api phase already records it, so
   `/tmp/mahalo-outputs.env` is complete after a full `--phase all` run. Only a
   standalone `--phase frontend` run (which truncates the consolidated env at dispatch)
   would omit it. Optional: record it in the frontend phase too for symmetry.

</details>

<details>
<summary>Details</summary>

### Credential-context split enforced in the script, not just the prose

The design's single most load-bearing invariant is that builder-side `aws`/`cdk` commands
use the instance role (no `--profile`) while only VDI-side commands carry `--profile lava`
(design §B.1 NIT-3). The script enforces this structurally: the arg parser accepts only
`--phase`, `--commit`, `--admin-cidr`, and `-h/--help`, and a grep across the file finds
`--profile` only inside the header comment that explains why it is absent — never on an
executable command (confirmed). There is no `--gitea-mode` flag, matching the design's
removal of the stale reference (NIT-5). The `require_instance_role` guard
(`aws sts get-caller-identity`) runs before every expensive deploy, so a dead instance
role fails fast rather than mid-deploy.

### MAHALO_BUILD_IMAGE stays exported across the whole run

`export MAHALO_BUILD_IMAGE=1` sits at the top of the script and is never unset, so the
Runtime image build and the Api Lambda bundle both take the Docker branch, and critically
the frontend phase's final CORS re-deploy of `MahaloApiStack` does too. That re-deploy
also passes `-c buildImage=1` explicitly as belt-and-suspenders. This closes the MEDIUM-4
hazard the design called out — a CORS re-deploy without the flag would repackage the API
as a dependency-less plain asset and break it. `AWS_REGION`/`AWS_DEFAULT_REGION` are
likewise exported once at `us-east-1`.

### Staged deploy order matches §B exactly

```
toolchain → backend → runtime-api → frontend              (--phase all)
             │           │            │
             │           │            └─ (2) MahaloFrontendStack --exclusively
             │           │               (3) npm ci + npm run build (NEXT_PUBLIC_* inlined)
             │           │               (4) MahaloFrontendStack --exclusively -c buildFrontend=1
             │           │               (5) MahaloApiStack CORS  ← ALWAYS LAST
             │           └─ MahaloRuntimeStack + MahaloApiStack (Docker)
             └─ MahaloMemoryIdentityStack + MahaloGatewayStack + 4× MahaloMock*Stack

gitea (opt-in, NOT in `all`) → MahaloGiteaStack only, then stops
```

The backend phase deploys exactly the six Docker-free stacks (MemoryIdentity, Gateway,
and the four mocks) and captures `MemoryId`/`GatewayMcpUrl`. The runtime-api phase
deploys Runtime + Api behind the Docker guard and captures `RuntimeArn`/`RuntimeApiUrl`.
The `all` dispatch runs `toolchain → backend → runtime-api → frontend` and deliberately
omits gitea, matching the design.

### Two-phase frontend: both deploys `--exclusively`, CORS strictly last

This is the MEDIUM-2 resolution and the FEAT-002 acceptance criterion with the narrowest
failure mode, so it is worth being concrete. Both `MahaloFrontendStack` deploys carry
`--exclusively` (lines 328 and 350, confirmed), so a bare deploy can never pull
`MahaloApiStack` in with the placeholder `FrontendOrigin`. Between them, the build runs
with the three `NEXT_PUBLIC_*` vars inlined and a `test -f out/index.html` guard that
fails the phase if the static export is empty. Before the build, fail-fast `:?` guards on
`RUNTIME_API_URL` and `IDENTITY_POOL_ID` make a silent-fallback build impossible. The
final deploy of the phase is `MahaloApiStack -c buildImage=1 --parameters
FrontendOrigin="$FRONTEND_URL"`, so CORS always ends pointing at the live CloudFront
origin. Because the whole ordered sequence re-runs on a partial `--phase frontend`
re-invocation and every deploy is idempotent, CORS cannot be left stale.

One asymmetry worth noting (non-blocking): the phase reads `RUNTIME_API_URL` from the
rtapi outputs file to drive the build but never `record_output RuntimeApiUrl` — only the
runtime-api phase records it. After a full `--phase all` run the consolidated env is
complete because runtime-api ran first; a standalone `--phase frontend` run truncates
`/tmp/mahalo-outputs.env` at dispatch and would omit `RuntimeApiUrl` from it. Cosmetic
(the value is still in the rtapi outputs file and the build uses it correctly), but
recording it in the frontend phase too would make the consolidated env symmetric for
single-phase runs.

### Gitea phase stops after the host deploy — no real-github flip

`phase_gitea` pre-flights the two SSM SecureString params
(`/mahalo/gitea/adapter-token`, `/mahalo/gitea/admin-password`), failing fast with a
pointer to `task7-deploy-runbook.md §1` if absent, then deploys `MahaloGiteaStack` with
the required `AdminCidr` (via `${ADMIN_CIDR:?...}`) and prints `GiteaPublicUrl`. It does
not emit `cdk deploy MahaloMockGithubStack -c giteaMode=real` — a grep confirms the only
`giteaMode=real` occurrences are a comment and a log line explaining the deferral to the
task7 runbook (confirmed). This is the HIGH-2 resolution verbatim: the flip needs an
`app.py` `_GITEA_ENV` change out of scope here.

### Output capture, bootstrap fallback, idempotency

Each `cdk deploy` writes `--outputs-file`, `outputs_get` parses values with a small
Python one-liner, and `record_output` appends only non-empty keys to
`/tmp/mahalo-outputs.env`, which `print_summary` echoes at the end of the run. The backend
phase resolves the account id first, then bootstraps only when `CDKToolkit` is absent
(`describe-stacks … || cdk bootstrap`), matching the MEDIUM-5 fallback. Every phase enters
the repo from the pinned `BUILDER_HOME` base dir via `enter_repo`/`enter_infra_cdk`, so
clone location, venvs, and outputs paths are deterministic across re-runs, and the
toolchain phase clone-or-updates idempotently. The dispatch truncates the consolidated env
only for phases that write it, which is why a standalone `--phase frontend` run has the
narrow omission noted above.

### Runbook matches the script and covers teardown + validation

The runbook's eight steps track the script's flags and phases. Step 4 describes the same
`toolchain → backend → runtime-api → frontend` order and the `--exclusively` / CORS-last
frontend ordering; every block is labelled `[VDI]` (with `--profile lava`) or `[builder]`
(instance role, no `--profile`), and the quick-reference table repeats the convention with
the closing assertion that no `[builder]` command uses `--profile` and no `[VDI]` command
omits it. Teardown destroys the ten app stacks from the builder (step 7, one `cdk destroy`
with CDK computing reverse-dependency order, plus the idempotent re-run guidance and the
leaf-first fallback groups) and the builder from the VDI last (step 8), with an explicit
"NEVER run this from inside the builder's own SSM session" warning — the MEDIUM-3
self-destruct hazard. The ECR bootstrap-repo residual-cost note is present in step 7.
Browser validation (step 6) covers a READ (list repositories → payment-service), the
two-call propose→approve HITL WRITE, reject-writes-nothing, and cross-message session
memory, and faithfully carries the known github-name-vs-repo-id 404 quirk as expected
behavior rather than a bug.

### STATUS / CONTINUATION record the builder path and resume pointer

STATUS.md's NEXT ACTION and "AWS deployed state" section both state the VDI-no-Docker
builder path (deploy `MahaloBuilderStack` from the VDI → SSM into the arm64 builder → run
`scripts/builder-deploy.sh --phase all` → validate → tear down builder-then-VDI-last),
the 11-stack count, and the runbook/design paths. CONTINUATION.md's RESUME block carries
the same six-step summary, the no-local-Docker rationale, the 11-stack count, and the
runbook path as the immediate next action, so a fresh session resumes on the correct
route.

### Verification evidence (recorded by the coder; not re-run here)

`task7b-verification.md` records `bash -n scripts/builder-deploy.sh` exit 0, an offline
`cdk synth` producing all 11 templates with only benign warnings, `'DockerImage'` absent
from the builder template, and `pytest tests -q` at 66 passed / 1 skipped (the skip is the
pre-existing operator-only Docker `from_asset` branch). No live/billable deploy, no git
commit/push, no write outside the workspace, and `mahalo-dock` untouched. Per the review
instruction the suites were not re-run; the three grep-checkable FEAT-002 invariants were
spot-confirmed on disk and matched the evidence, leaving no articulable doubt that would
justify re-running anything.

</details>

<details>
<summary>File map</summary>

- `scripts/builder-deploy.sh` — new builder-side staged deploy script (FEAT-002): phase
  dispatch, instance-role chain, `MAHALO_BUILD_IMAGE=1` throughout, two-phase frontend with
  `--exclusively` + CORS-last, gitea-host-only phase, output capture.
- `docs/.agents/tasks/task7b-ec2-builder-runbook.md` — new operator runbook (FEAT-003):
  eight `[VDI]`/`[builder]`-labelled steps, teardown (app stacks from builder, builder from
  VDI last), browser validation, ECR cost note, quick-reference table.
- `docs/STATUS.md` — updated: VDI-no-Docker builder deploy path, 11-stack count, runbook
  pointer.
- `docs/CONTINUATION.md` — updated: RESUME block with the builder deploy path, 11-stack
  count, runbook pointer as next action.

Source of truth: `docs/.agents/tasks/task7b-design.md` (APPROVED). FEAT scope:
`docs/.agents/tasks/task7b-ec2-builder/features/FEAT-002.json`, `FEAT-003.json`.
Verification evidence: `docs/.agents/tasks/task7b-verification.md`.

</details>
