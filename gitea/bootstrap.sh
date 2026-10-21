#!/usr/bin/env bash
#
# Gitea bootstrap — idempotent first-run provisioning for mahalo-agentcore.
#
# Ported from mahalo-dock/mock-services/gitea-bootstrap/bootstrap.sh. The ONLY
# functional change for AWS (design §C.3) is step 5: the adapter token is pushed
# to an AWS SSM SecureString parameter (the github Lambda reads it at cold start
# via GITEA_TOKEN_PARAM) instead of — or in addition to — the Compose shared
# -volume token file. GITEA_PUBLIC_URL is the instance browser-facing URL so the
# adapter's _publicize rewrites in-stack links to reachable ones.
#
# Runs in a one-shot container built from the SAME gitea image as the server, so
# the `gitea` CLI and the shared /data volume are available (the first admin user
# can ONLY be created via the CLI — the REST API cannot create the first admin).
#
# Steps (each idempotent / safe to re-run):
#   1. Wait for the Gitea server to report healthy.
#   2. Create an admin user via `gitea admin user create` (skip if it exists).
#   3. Generate an API token for the adapter (recreate to obtain a usable secret).
#   4. Create + seed a sample repository with real initial files (skip if present).
#   5. Persist the token to AWS SSM (GITEA_TOKEN_SSM_PARAM) and/or the token file.
#
# Configuration comes from environment variables:
#   GITEA_URL             base URL of the running server (e.g. http://localhost:3000)
#   GITEA_PUBLIC_URL      browser-facing URL (instance public DNS / ALB URL)
#   GITEA_ADMIN_USER      admin username to ensure
#   GITEA_ADMIN_PASSWORD  admin password
#   GITEA_ADMIN_EMAIL     admin email
#   GITEA_TOKEN_NAME      name of the API token to create for the adapter
#   GITEA_SEED_REPO       name of the sample repo to seed (e.g. payment-service)
#   GITEA_TOKEN_FILE      optional path to also write the token (local parity)
#   GITEA_TOKEN_SSM_PARAM AWS SSM SecureString parameter name to store the token
#   AWS_REGION            region for the SSM push (defaults from the instance)
set -euo pipefail

GITEA_URL="${GITEA_URL:-http://localhost:3000}"
GITEA_PUBLIC_URL="${GITEA_PUBLIC_URL:-${GITEA_URL}}"
GITEA_ADMIN_USER="${GITEA_ADMIN_USER:-mahalo_admin}"
GITEA_ADMIN_PASSWORD="${GITEA_ADMIN_PASSWORD:-<GITEA_ADMIN_PASSWORD>}"
GITEA_ADMIN_EMAIL="${GITEA_ADMIN_EMAIL:-admin@mahalo.local}"
GITEA_TOKEN_NAME="${GITEA_TOKEN_NAME:-mahalo-adapter}"
GITEA_SEED_REPO="${GITEA_SEED_REPO:-payment-service}"
GITEA_TOKEN_FILE="${GITEA_TOKEN_FILE:-}"
GITEA_TOKEN_SSM_PARAM="${GITEA_TOKEN_SSM_PARAM:-}"

log() { echo "[gitea-bootstrap] $*"; }

# jq is not shipped in the gitea (alpine) image; add it for reliable JSON parsing.
if ! command -v jq >/dev/null 2>&1; then
  log "installing jq..."
  apk add --no-cache jq >/dev/null 2>&1 || {
    log "ERROR: could not install jq"; exit 1;
  }
fi

# ---------------------------------------------------------------------------
# 1. Wait for the server to be healthy.
# ---------------------------------------------------------------------------
log "waiting for Gitea at ${GITEA_URL} to become healthy..."
for i in $(seq 1 60); do
  if curl -fsS "${GITEA_URL}/api/healthz" >/dev/null 2>&1; then
    log "Gitea is healthy."
    break
  fi
  if [ "$i" -eq 60 ]; then
    log "ERROR: Gitea did not become healthy in time."; exit 1
  fi
  sleep 2
done

# ---------------------------------------------------------------------------
# 2. Create the admin user (idempotent).
#    The first admin can only be created via the CLI against the shared data
#    dir. `gitea admin user list` tells us whether it already exists.
# ---------------------------------------------------------------------------
# The gitea CLI needs the server config + data dir. In the official docker image
# these live under /data/gitea/conf/app.ini and /data respectively, and the CLI
# must run as the `git` user that owns the data. GITEA_WORK_DIR/GITEA_CUSTOM are
# normally exported by the gitea entrypoint, which we bypass, so set them here.
export GITEA_WORK_DIR="${GITEA_WORK_DIR:-/data/gitea}"
GITEA_CONF="${GITEA_CONF:-/data/gitea/conf/app.ini}"
gitea_cli() {
  # Run the gitea CLI as the git user, pointed at the shared config.
  su-exec git gitea --config "${GITEA_CONF}" "$@" 2>/dev/null \
    || gitea --config "${GITEA_CONF}" "$@"
}

if gitea_cli admin user list | awk 'NR>1 {print $2}' | grep -qx "${GITEA_ADMIN_USER}"; then
  log "admin user '${GITEA_ADMIN_USER}' already exists; skipping create."
else
  log "creating admin user '${GITEA_ADMIN_USER}'..."
  gitea_cli admin user create \
    --username "${GITEA_ADMIN_USER}" \
    --password "${GITEA_ADMIN_PASSWORD}" \
    --email "${GITEA_ADMIN_EMAIL}" \
    --admin \
    --must-change-password=false
  log "admin user created."
fi

AUTH="${GITEA_ADMIN_USER}:${GITEA_ADMIN_PASSWORD}"

# ---------------------------------------------------------------------------
# 3. Generate (or reuse) an API token for the adapter.
#    Token secrets are only returned at creation time, so if a token with our
#    name already exists we delete and recreate it to obtain a usable secret.
# ---------------------------------------------------------------------------
log "ensuring API token '${GITEA_TOKEN_NAME}' exists..."
existing_token_id="$(
  curl -fsS -u "${AUTH}" \
    "${GITEA_URL}/api/v1/users/${GITEA_ADMIN_USER}/tokens" 2>/dev/null \
  | jq -r --arg n "${GITEA_TOKEN_NAME}" '.[] | select(.name==$n) | .id' | head -n1
)"

if [ -n "${existing_token_id}" ] && [ "${existing_token_id}" != "null" ]; then
  log "token '${GITEA_TOKEN_NAME}' already exists (id=${existing_token_id}); recreating to obtain a usable secret."
  curl -fsS -X DELETE -u "${AUTH}" \
    "${GITEA_URL}/api/v1/users/${GITEA_ADMIN_USER}/tokens/${existing_token_id}" >/dev/null 2>&1 || true
fi

TOKEN="$(
  curl -fsS -X POST -u "${AUTH}" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"${GITEA_TOKEN_NAME}\",\"scopes\":[\"write:repository\",\"write:user\",\"read:organization\"]}" \
    "${GITEA_URL}/api/v1/users/${GITEA_ADMIN_USER}/tokens" \
  | jq -r '.sha1'
)"

if [ -z "${TOKEN}" ] || [ "${TOKEN}" = "null" ]; then
  log "ERROR: failed to obtain API token."; exit 1
fi
log "API token obtained."

# ---------------------------------------------------------------------------
# 4. Create + seed the sample repository with real files (idempotent).
# ---------------------------------------------------------------------------
repo_exists() {
  # No `-f`: a 404 (repo absent) is an expected, non-error outcome here.
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' \
    -H "Authorization: token ${TOKEN}" \
    "${GITEA_URL}/api/v1/repos/${GITEA_ADMIN_USER}/${GITEA_SEED_REPO}" 2>/dev/null)"
  [ "${code}" = "200" ]
}

put_file() {
  # put_file <path> <commit-message> <base64-content>
  # Creates the file (POST) or, if it already exists, updates it (PUT) by
  # supplying the current blob SHA — so seeding is fully idempotent.
  #
  # NOTE: no `curl -f` here. A missing file legitimately returns 404 on the SHA
  # probe, and `-f` would make curl exit non-zero and abort the script under
  # `set -e`. We inspect the body/HTTP code ourselves instead.
  local path="$1" msg="$2" content_b64="$3"
  local api="${GITEA_URL}/api/v1/repos/${GITEA_ADMIN_USER}/${GITEA_SEED_REPO}/contents/${path}"
  local sha http

  sha="$(
    curl -sS -H "Authorization: token ${TOKEN}" "${api}?ref=main" 2>/dev/null \
      | jq -r '.sha // empty' 2>/dev/null
  )"

  if [ -n "${sha}" ]; then
    http="$(curl -sS -o /tmp/put_resp -w '%{http_code}' -X PUT \
      -H "Authorization: token ${TOKEN}" \
      -H "Content-Type: application/json" \
      -d "{\"content\":\"${content_b64}\",\"message\":\"${msg}\",\"branch\":\"main\",\"sha\":\"${sha}\"}" \
      "${api}")"
  else
    http="$(curl -sS -o /tmp/put_resp -w '%{http_code}' -X POST \
      -H "Authorization: token ${TOKEN}" \
      -H "Content-Type: application/json" \
      -d "{\"content\":\"${content_b64}\",\"message\":\"${msg}\",\"branch\":\"main\"}" \
      "${api}")"
  fi

  if [ "${http}" != "200" ] && [ "${http}" != "201" ]; then
    log "ERROR: writing ${path} failed (HTTP ${http}): $(cat /tmp/put_resp 2>/dev/null)"
    return 1
  fi
}

if repo_exists; then
  log "seed repo '${GITEA_ADMIN_USER}/${GITEA_SEED_REPO}' already exists; skipping seed."
else
  log "creating seed repo '${GITEA_SEED_REPO}' with an initial commit..."
  # auto_init gives us an initial commit + main branch so the contents API has a
  # base to add files onto.
  curl -fsS -X POST \
    -H "Authorization: token ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"${GITEA_SEED_REPO}\",\"description\":\"Payment processing microservice (mahalo-agentcore seed repo)\",\"private\":false,\"auto_init\":true,\"default_branch\":\"main\",\"readme\":\"Default\"}" \
    "${GITEA_URL}/api/v1/user/repos" >/dev/null
  log "repo created; seeding files..."

  # Real initial files. Encoded to base64 for the Gitea contents API.
  readme_b64="$(printf '%s' \
'# payment-service

Payment processing microservice seeded into Gitea for the mahalo-agentcore demo.

This repository exists so the MAHALO chatbot has a real repo to branch from,
commit real file contents into, and open pull requests against.

## Layout
- `src/payment.py` — minimal payment-charge stub
- `tests/test_payment.py` — a basic test

> Seeded by gitea-bootstrap. Safe to extend during the demo.
' | base64 -w0)"

  src_b64="$(printf '%s' \
'"""Minimal payment charge stub for the mahalo-agentcore seed repo."""


def charge(amount_cents: int, currency: str = "USD") -> dict:
    """Pretend to charge a card and return a result record."""
    if amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    return {
        "status": "succeeded",
        "amount_cents": amount_cents,
        "currency": currency,
    }
' | base64 -w0)"

  test_b64="$(printf '%s' \
'from src.payment import charge


def test_charge_succeeds():
    result = charge(1299, "USD")
    assert result["status"] == "succeeded"
    assert result["amount_cents"] == 1299
' | base64 -w0)"

  put_file "src/payment.py"        "chore: add payment stub"       "${src_b64}"
  put_file "tests/test_payment.py" "test: add basic payment test"  "${test_b64}"
  put_file "README.md"             "docs: expand seed README"      "${readme_b64}"
  log "seed files committed."
fi

# ---------------------------------------------------------------------------
# 5. Persist the token where the adapter reads it.
#    On AWS this is an SSM SecureString (GITEA_TOKEN_SSM_PARAM); the github
#    Lambda reads it at cold start via GITEA_TOKEN_PARAM. A local token file is
#    still written when GITEA_TOKEN_FILE is set (Compose parity).
# ---------------------------------------------------------------------------
if [ -n "${GITEA_TOKEN_SSM_PARAM}" ]; then
  log "pushing token to SSM SecureString ${GITEA_TOKEN_SSM_PARAM}..."
  aws ssm put-parameter \
    --name "${GITEA_TOKEN_SSM_PARAM}" \
    --type SecureString \
    --value "${TOKEN}" \
    --overwrite >/dev/null
  log "token stored in SSM."
fi

if [ -n "${GITEA_TOKEN_FILE}" ]; then
  mkdir -p "$(dirname "${GITEA_TOKEN_FILE}")"
  printf '%s' "${TOKEN}" > "${GITEA_TOKEN_FILE}"
  chmod 600 "${GITEA_TOKEN_FILE}" 2>/dev/null || true
  log "token written to ${GITEA_TOKEN_FILE}"
fi

if [ -z "${GITEA_TOKEN_SSM_PARAM}" ] && [ -z "${GITEA_TOKEN_FILE}" ]; then
  log "WARNING: neither GITEA_TOKEN_SSM_PARAM nor GITEA_TOKEN_FILE set; token not persisted."
fi

log "GITEA_PUBLIC_URL for the adapter: ${GITEA_PUBLIC_URL}"
log "bootstrap complete."
