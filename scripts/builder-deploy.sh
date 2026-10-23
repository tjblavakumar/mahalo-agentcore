#!/usr/bin/env bash
#
# builder-deploy.sh — builder-side staged `cdk deploy` for mahalo-agentcore
# (Task 7b, design §B/§C/§D; implements FEAT-002).
#
# WHERE THIS RUNS: on the transient arm64 EC2 BUILDER (MahaloBuilderStack),
# inside the operator's SSM Session Manager shell OR via `ssm send-command`.
# It is NEVER run on the WorkSpaces VDI. All `aws`/`cdk` commands here use the
# builder's INSTANCE ROLE credential chain — there is deliberately NO `--profile`
# anywhere in this file (the only `--profile lava` commands in this project are
# VDI-side: the start-session/send-command kickoff and the VDI teardown, both in
# the runbook).
#
# WHAT IT DOES: installs the toolchain, clones/updates the repo, then runs the
# staged, Docker-dependent `cdk deploy` of the app stacks that the VDI cannot run
# locally (no nested virtualization -> no local Docker). It is idempotent and
# re-runnable (CDK is declarative; re-deploys converge).
#
# MAHALO_BUILD_IMAGE=1 is exported ONCE at the top and kept exported for the
# WHOLE run, so every Docker-dependent deploy (Runtime image build+push, API
# Lambda dependency bundling) uses the bundled branch — including the frontend
# phase's final MahaloApiStack CORS re-deploy, which must NOT be downgraded to a
# dependency-less plain asset.
#
# PHASES (via --phase): toolchain | backend | runtime-api | frontend | gitea | all
#   toolchain    verify/install git, Docker (via sudo), Node 24, Python 3.13,
#                AWS CLI v2, pinned CDK CLI; clone/update repo; create the venvs.
#   backend      bootstrap check, then the 6 Docker-free backend stacks.
#   runtime-api  MahaloRuntimeStack + MahaloApiStack (the two Docker needs).
#   frontend     the two-phase frontend build, CORS deploy ALWAYS last.
#   gitea        deploy MahaloGiteaStack ONLY (real-github flip deferred to the
#                task7 runbook — HIGH-2 resolution; NOT emitted here).
#   all          toolchain -> backend -> runtime-api -> frontend (NOT gitea).
#
# FLAGS (the ONLY flags): --phase <name>, --commit <sha>, --admin-cidr <cidr>.
#   There is NO --gitea-mode flag and NO --profile flag.
# OVERRIDABLE ENV (no flag): REPO_URL, BUILDER_HOME, COMMIT.
set -euo pipefail

# ---------------------------------------------------------------------------
# Region / account / Docker-build flag — exported ONCE, kept for the whole run.
# ---------------------------------------------------------------------------
export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
# Docker branches ON for Runtime (ARM64 image build+push) + Api (Lambda dep
# bundling), ALWAYS — including the frontend phase's CORS re-deploy of the API.
export MAHALO_BUILD_IMAGE=1

# ---------------------------------------------------------------------------
# Overridable env (no CLI flag). Defaults match the UserData clone (design §A.5).
# ---------------------------------------------------------------------------
# git remote the toolchain phase clones (public demo repo; unauthenticated HTTPS).
REPO_URL="${REPO_URL:-https://github.com/tjblavakumar/mahalo-agentcore.git}"
# Base dir the clone + venvs + node_modules resolve under (the user we run as).
BUILDER_HOME="${BUILDER_HOME:-/home/ssm-user}"
# Checked-out revision; overridable with --commit. Defaults to origin/main HEAD.
COMMIT="${COMMIT:-origin/main}"

# Pinned CDK CLI — matches _CDK_CLI_VERSION in builder_stack.py (aws-cdk-lib
# >=2.251,<3, pinned to 2.1145.0 so the CLI never outruns the library).
CDK_CLI_VERSION="${CDK_CLI_VERSION:-2.1145.0}"
# Repo directory name under BUILDER_HOME.
REPO_DIR="mahalo-agentcore"

# Per-phase CfnOutput capture files + the consolidated env file (design §C.1).
BACKEND_OUTPUTS="/tmp/mahalo-backend-outputs.json"
RTAPI_OUTPUTS="/tmp/mahalo-rtapi-outputs.json"
FE_OUTPUTS="/tmp/mahalo-fe-outputs.json"
GITEA_OUTPUTS="/tmp/mahalo-gitea-outputs.json"
CONSOLIDATED_ENV="/tmp/mahalo-outputs.env"

# Set by the arg parser (mapped from flags). ADMIN_CIDR has no default — the
# gitea phase fails fast via ${ADMIN_CIDR:?...} if it is unset.
PHASE=""
ADMIN_CIDR="${ADMIN_CIDR:-}"

log() { echo "[builder-deploy] $*"; }
die() { echo "[builder-deploy] ERROR: $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: builder-deploy.sh --phase <phase> [--commit <sha>] [--admin-cidr <cidr>]

Runs ON the EC2 builder (instance role; no --profile). Idempotent / re-runnable.

Phases:
  toolchain      install git/Docker/Node 24/Python 3.13/AWS CLI/CDK; clone repo;
                 create infra-cdk/.venv and agent/.venv.
  backend        cdk bootstrap check, then the 6 Docker-free backend stacks
                 (MemoryIdentity, Gateway, and the 4 Mock* stacks).
  runtime-api    MahaloRuntimeStack + MahaloApiStack (the two Docker builds).
  frontend       two-phase frontend build; MahaloApiStack CORS deploy is LAST.
  gitea          deploy MahaloGiteaStack only (--admin-cidr required). The
                 real-github flip is deferred to the task7 deploy runbook.
  all            toolchain -> backend -> runtime-api -> frontend (NOT gitea).

Flags:
  --phase <name>        one of the phases above (required).
  --commit <sha>        git revision to check out (default: origin/main).
  --admin-cidr <cidr>   required for --phase gitea (e.g. 203.0.113.4/32).

Overridable env (no flag): REPO_URL, BUILDER_HOME, COMMIT, CDK_CLI_VERSION.
EOF
}

# ---------------------------------------------------------------------------
# Arg parser — maps flags to env the phase bodies read (design §B.1).
#   --phase <name> -> PHASE ; --commit <sha> -> COMMIT ; --admin-cidr -> ADMIN_CIDR
# ---------------------------------------------------------------------------
while [ "$#" -gt 0 ]; do
  case "$1" in
    --phase)
      [ "$#" -ge 2 ] || die "--phase needs a value"
      PHASE="$2"; shift 2 ;;
    --commit)
      [ "$#" -ge 2 ] || die "--commit needs a value"
      COMMIT="$2"; shift 2 ;;
    --admin-cidr)
      [ "$#" -ge 2 ] || die "--admin-cidr needs a value"
      ADMIN_CIDR="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      usage >&2; die "unknown argument: $1" ;;
  esac
done

[ -n "$PHASE" ] || { usage >&2; die "--phase is required"; }

REPO_PATH="${BUILDER_HOME}/${REPO_DIR}"

# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

# Enter the repo root from a deterministic base dir (design §B.1/§B.3). Every
# phase calls this first so the clone location, the two venvs, and node_modules
# are resolved identically on every (re-)run regardless of the starting cwd.
enter_repo() {
  cd "$BUILDER_HOME" || die "cannot cd to BUILDER_HOME=$BUILDER_HOME"
  [ -d "$REPO_PATH/.git" ] || die "repo not found at $REPO_PATH — run '--phase toolchain' first"
  cd "$REPO_PATH" || die "cannot cd to $REPO_PATH"
}

# Enter infra-cdk/ with its venv active.
enter_infra_cdk() {
  enter_repo
  cd infra-cdk || die "infra-cdk/ not found in repo"
  [ -f .venv/bin/activate ] || die "infra-cdk/.venv missing — run '--phase toolchain' first"
  # shellcheck disable=SC1091
  source .venv/bin/activate
}

# Fail-fast guards before any expensive cdk deploy (design §B.4).
require_instance_role() {
  aws sts get-caller-identity >/dev/null 2>&1 \
    || die "instance role not usable (aws sts get-caller-identity failed)"
}
require_docker() {
  # Docker is invoked via sudo throughout — do NOT rely on docker-group
  # membership (design §A.5). Passwordless sudo is the AL2023 SSM default.
  sudo docker info >/dev/null 2>&1 \
    || die "sudo docker info failed — Docker not ready (run '--phase toolchain')"
}

# Read one CfnOutput value from a `--outputs-file` JSON: outputs_get <file> <stack> <key>.
# The JSON shape is {"StackName": {"OutputKey": "value", ...}, ...}.
outputs_get() {
  local file="$1" stack="$2" key="$3"
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get(sys.argv[2],{}).get(sys.argv[3],''))" \
    "$file" "$stack" "$key"
}

# Append "KEY=value" to the consolidated env file only when value is non-empty.
record_output() {
  local name="$1" value="$2"
  [ -n "$value" ] || return 0
  echo "${name}=${value}" >> "$CONSOLIDATED_ENV"
}

# ---------------------------------------------------------------------------
# Phase: toolchain.
# ---------------------------------------------------------------------------
phase_toolchain() {
  log "phase toolchain: install/verify toolchain + clone/update repo"
  cd "$BUILDER_HOME" || die "cannot cd to BUILDER_HOME=$BUILDER_HOME"

  # Install the toolchain (guarded; UserData usually did this already at boot).
  # Docker is invoked via sudo everywhere, so group membership is not required.
  command -v git >/dev/null 2>&1 || sudo dnf install -y git || true
  if ! command -v docker >/dev/null 2>&1; then
    sudo dnf install -y docker || true
    sudo systemctl enable --now docker || true
  fi
  if ! command -v node >/dev/null 2>&1; then
    curl -fsSL https://rpm.nodesource.com/setup_24.x | sudo bash - || true
    sudo dnf install -y nodejs || true
  fi
  command -v python3.13 >/dev/null 2>&1 \
    || sudo dnf install -y python3.13 python3.13-pip \
    || sudo dnf install -y python3.13 || true
  command -v aws >/dev/null 2>&1 || sudo dnf install -y awscli || true
  command -v cdk >/dev/null 2>&1 \
    || sudo npm install -g "aws-cdk@${CDK_CLI_VERSION}" || true

  # Clone-or-update, always from the pinned base dir (design §B.3). UserData
  # already cloned on first boot; this makes the phase self-healing if that
  # boot-time clone failed or the tree is stale.
  if [ ! -d "$REPO_PATH/.git" ]; then
    git clone "$REPO_URL" "$REPO_DIR"
  else
    ( cd "$REPO_DIR" && git fetch --all --prune && git checkout "$COMMIT" && git pull --ff-only || true )
  fi

  # Pick the Python interpreter for the venvs (prefer 3.13; fall back to python3).
  local py
  if command -v python3.13 >/dev/null 2>&1; then
    py=python3.13
  else
    py=python3
  fi

  # Create + install infra-cdk/.venv.
  cd "$REPO_PATH/infra-cdk" || die "infra-cdk/ not found"
  [ -d .venv ] || "$py" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
  deactivate

  # Create + install agent/.venv.
  cd "$REPO_PATH/agent" || die "agent/ not found"
  [ -d .venv ] || "$py" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
  deactivate

  # Assertions: Node must be 24.x; Docker (via sudo) must be live.
  local node_ver
  node_ver="$(node --version 2>/dev/null || echo none)"
  case "$node_ver" in
    v24.*) log "node $node_ver OK" ;;
    *) die "node 24.x required, found: $node_ver" ;;
  esac
  require_docker
  log "phase toolchain complete"
}

# ---------------------------------------------------------------------------
# Phase: backend (NO Docker) — the 6 Docker-free stacks.
# ---------------------------------------------------------------------------
phase_backend() {
  log "phase backend: bootstrap check + 6 Docker-free backend stacks"
  enter_infra_cdk
  require_instance_role

  # Resolve the account FIRST, then bootstrap only if CDKToolkit is absent. A
  # missing assets bucket surfaces as a missing CDKToolkit stack here.
  local account
  account="$(aws sts get-caller-identity --query Account --output text)"
  [ -n "$account" ] || die "could not resolve AWS account id"
  if ! aws cloudformation describe-stacks --stack-name CDKToolkit >/dev/null 2>&1; then
    log "CDKToolkit absent — bootstrapping aws://${account}/${AWS_REGION}"
    cdk bootstrap "aws://${account}/${AWS_REGION}"
  fi

  cdk deploy \
    MahaloMemoryIdentityStack MahaloGatewayStack \
    MahaloMockJiraStack MahaloMockConfluenceStack \
    MahaloMockGithubStack MahaloMockServicenowStack \
    --require-approval never --outputs-file "$BACKEND_OUTPUTS"

  # Capture MemoryId, GatewayMcpUrl.
  local memory_id gateway_url
  memory_id="$(outputs_get "$BACKEND_OUTPUTS" MahaloMemoryIdentityStack MemoryId)"
  gateway_url="$(outputs_get "$BACKEND_OUTPUTS" MahaloGatewayStack GatewayMcpUrl)"
  record_output MemoryId "$memory_id"
  record_output GatewayMcpUrl "$gateway_url"
  log "backend outputs: MemoryId=$memory_id GatewayMcpUrl=$gateway_url"
}

# ---------------------------------------------------------------------------
# Phase: runtime-api (BOTH need Docker — the reason the builder exists).
# ---------------------------------------------------------------------------
phase_runtime_api() {
  log "phase runtime-api: MahaloRuntimeStack + MahaloApiStack (Docker)"
  enter_infra_cdk
  require_instance_role
  require_docker

  # MAHALO_BUILD_IMAGE=1 already exported (top of script): Runtime builds+pushes
  # the ARM64 agent image natively on Graviton; Api bundles its Lambda deps.
  cdk deploy MahaloRuntimeStack MahaloApiStack \
    --require-approval never --outputs-file "$RTAPI_OUTPUTS"

  # Capture RuntimeArn, RuntimeApiUrl.
  local runtime_arn runtime_api_url
  runtime_arn="$(outputs_get "$RTAPI_OUTPUTS" MahaloRuntimeStack RuntimeArn)"
  runtime_api_url="$(outputs_get "$RTAPI_OUTPUTS" MahaloApiStack RuntimeApiUrl)"
  record_output RuntimeArn "$runtime_arn"
  record_output RuntimeApiUrl "$runtime_api_url"
  log "runtime-api outputs: RuntimeArn=$runtime_arn RuntimeApiUrl=$runtime_api_url"
}

# ---------------------------------------------------------------------------
# Phase: frontend (NO Docker; needs a prior `npm run build`).
# Two-phase build; the MahaloApiStack CORS deploy is ALWAYS the last deploy.
# A partial re-run re-executes the WHOLE ordered sequence (every deploy is
# idempotent), so CORS can never be left stale (design §C.4).
# ---------------------------------------------------------------------------
phase_frontend() {
  log "phase frontend: two-phase build, API CORS deploy LAST"
  enter_infra_cdk
  require_instance_role

  # (1) RuntimeApiUrl was produced by the runtime-api phase — read it from that
  # phase's outputs file.
  [ -f "$RTAPI_OUTPUTS" ] || die "$RTAPI_OUTPUTS missing — run '--phase runtime-api' first"
  local RUNTIME_API_URL
  RUNTIME_API_URL="$(outputs_get "$RTAPI_OUTPUTS" MahaloApiStack RuntimeApiUrl)"

  # (2) Deploy MahaloFrontendStack WITHOUT the build flag to create the bucket +
  # CloudFront + Cognito. --exclusively is MANDATORY so MahaloApiStack is NOT
  # pulled in with the placeholder FrontendOrigin.
  cdk deploy MahaloFrontendStack --exclusively --require-approval never \
    --outputs-file "$FE_OUTPUTS"
  local IDENTITY_POOL_ID FRONTEND_URL
  IDENTITY_POOL_ID="$(outputs_get "$FE_OUTPUTS" MahaloFrontendStack IdentityPoolId)"
  FRONTEND_URL="$(outputs_get "$FE_OUTPUTS" MahaloFrontendStack FrontendUrl)"

  # (3) Fail-fast: a silent-fallback frontend build must be impossible.
  : "${RUNTIME_API_URL:?RuntimeApiUrl empty — re-run '--phase runtime-api'}"
  : "${IDENTITY_POOL_ID:?IdentityPoolId empty — frontend infra deploy did not emit it}"

  enter_repo
  cd frontend || die "frontend/ not found"
  npm ci
  NEXT_PUBLIC_API_URL="$RUNTIME_API_URL" \
  NEXT_PUBLIC_AWS_REGION="$AWS_REGION" \
  NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID="$IDENTITY_POOL_ID" \
    npm run build
  test -f out/index.html || die "export missing frontend/out — npm run build produced no static site"

  # (4) Re-deploy MahaloFrontendStack WITH the build flag to upload frontend/out/.
  # --exclusively again MANDATORY so the API is not pulled in with the placeholder.
  enter_infra_cdk
  cdk deploy MahaloFrontendStack --exclusively -c buildFrontend=1 \
    --require-approval never

  # (5) LAST deploy of the phase: MahaloApiStack with the REAL FrontendOrigin so
  # browser CORS points at the live CloudFront domain. MAHALO_BUILD_IMAGE=1 is
  # still exported (and -c buildImage=1 passed), so the API keeps its bundled
  # deps and is not downgraded to the plain asset.
  cdk deploy MahaloApiStack -c buildImage=1 \
    --parameters FrontendOrigin="$FRONTEND_URL" --require-approval never

  record_output IdentityPoolId "$IDENTITY_POOL_ID"
  record_output FrontendUrl "$FRONTEND_URL"
  log "frontend outputs: IdentityPoolId=$IDENTITY_POOL_ID FrontendUrl=$FRONTEND_URL"
  log "CORS deploy of MahaloApiStack (FrontendOrigin=$FRONTEND_URL) was the final deploy"
}

# ---------------------------------------------------------------------------
# Phase: gitea — deploy the Gitea host ONLY. The real-github flip
# (-c giteaMode=real) is DEFERRED to task7-deploy-runbook.md (HIGH-2): it needs
# an app.py _GITEA_ENV change that is out of scope here. This phase does NOT
# emit that flip.
# ---------------------------------------------------------------------------
phase_gitea() {
  log "phase gitea: deploy MahaloGiteaStack only (real-github flip deferred)"
  enter_infra_cdk
  require_instance_role

  # Pre-flight the two SSM SecureString params the real-github path later needs;
  # fail fast with a pointer to the runbook if absent.
  aws ssm get-parameter --name /mahalo/gitea/adapter-token >/dev/null 2>&1 \
    || die "MISSING /mahalo/gitea/adapter-token — create it per docs/.agents/tasks/task7-deploy-runbook.md §1"
  aws ssm get-parameter --name /mahalo/gitea/admin-password >/dev/null 2>&1 \
    || die "MISSING /mahalo/gitea/admin-password — create it per docs/.agents/tasks/task7-deploy-runbook.md §1"

  # AdminCidr is REQUIRED (no default in gitea_stack.py). Fail fast whether the
  # operator forgot --admin-cidr or the env var.
  cdk deploy MahaloGiteaStack \
    --parameters AdminCidr="${ADMIN_CIDR:?set --admin-cidr <cidr>}" \
    --require-approval never --outputs-file "$GITEA_OUTPUTS"

  local gitea_url gitea_instance
  gitea_url="$(outputs_get "$GITEA_OUTPUTS" MahaloGiteaStack GiteaPublicUrl)"
  gitea_instance="$(outputs_get "$GITEA_OUTPUTS" MahaloGiteaStack GiteaInstanceId)"
  record_output GiteaPublicUrl "$gitea_url"
  record_output GiteaInstanceId "$gitea_instance"
  log "Gitea deployed. GiteaPublicUrl=$gitea_url"
  log "To wire the REAL github backend (bootstrap + giteaMode=real + GiteaPublicUrl"
  log "override), follow docs/.agents/tasks/task7-deploy-runbook.md §3-5."
}

# ---------------------------------------------------------------------------
# Consolidated summary (design §C.1).
# ---------------------------------------------------------------------------
print_summary() {
  [ -f "$CONSOLIDATED_ENV" ] || return 0
  log "---------------------------------------------------------------"
  log "Consolidated CfnOutputs ($CONSOLIDATED_ENV):"
  # Echo each captured KEY=value to the SSM shell.
  while IFS= read -r line; do
    log "  $line"
  done < "$CONSOLIDATED_ENV"
  log "---------------------------------------------------------------"
}

# ---------------------------------------------------------------------------
# Dispatch.
# ---------------------------------------------------------------------------
# Start each run with a fresh consolidated env file for the phases that write it.
case "$PHASE" in
  backend|runtime-api|frontend|gitea|all) : > "$CONSOLIDATED_ENV" ;;
  *) : ;;
esac

case "$PHASE" in
  toolchain)    phase_toolchain ;;
  backend)      phase_backend ;;
  runtime-api)  phase_runtime_api ;;
  frontend)     phase_frontend ;;
  gitea)        phase_gitea ;;
  all)
    phase_toolchain
    phase_backend
    phase_runtime_api
    phase_frontend
    ;;
  *)
    usage >&2
    die "unknown --phase: $PHASE (expected toolchain|backend|runtime-api|frontend|gitea|all)"
    ;;
esac

print_summary
log "phase '$PHASE' complete"
