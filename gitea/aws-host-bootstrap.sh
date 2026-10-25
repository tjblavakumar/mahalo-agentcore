#!/usr/bin/env bash
# AWS-host Gitea bootstrap — the variant that runs ON the AL2023 EC2 host (via
# SSM Run Command), NOT inside a one-shot container.
#
# This is the script that actually provisioned MahaloGiteaStack in the live
# demo account. It differs from the sibling `bootstrap.sh` (which was written to
# run INSIDE a one-shot gitea container, Compose-style). Here every gitea CLI
# step is issued with `docker exec` into the already-running `gitea` container,
# and the REST steps use curl from the host against localhost:3000.
#
# WHY the extra "install lock" step (step 1): a fresh `gitea/gitea` container
# writes /data/gitea/conf/app.ini with INSTALL_LOCK=false and empty SECRET_KEY /
# INTERNAL_TOKEN, so the gitea CLI refuses to run ("MustInstalled ... Unable to
# load config file for an installed Gitea instance") until the install is
# completed. We generate the two secrets with `gitea generate secret`, patch
# app.ini (awk, secrets passed as awk vars so no regex interpretation), and
# restart. IMPORTANT: the patched app.ini must stay owned by uid 1000 (the `git`
# user inside the container) — if it ends up root-owned, gitea cannot write its
# auto-generated OAUTH2_JWT_SECRET on startup and crash-loops with
# "permission denied". If you edit app.ini from the host as root, chown it back:
#     chown 1000:1000 <host>/gitea/conf/app.ini && chmod 660 <host>/gitea/conf/app.ini
#
# Prereqs on the host: docker running the `gitea` container; the instance role
# with ssm:GetParameter (decrypt) + ssm:PutParameter on /mahalo/gitea/*; the SSM
# SecureString params /mahalo/gitea/admin-password (pre-created) and
# /mahalo/gitea/adapter-token (this script overwrites it with the minted token).
#
# Idempotent — safe to re-run.
set -uo pipefail

GITEA_URL="http://localhost:3000"
INI_IN_CONTAINER="/data/gitea/conf/app.ini"
ADMIN_USER="mahalo_admin"
ADMIN_EMAIL="admin@mahalo.local"
TOKEN_NAME="mahalo-adapter"
SEED_REPO="payment-service"
REGION="us-east-1"

log() { echo "[bootstrap] $*"; }

ADMIN_PASS="$(aws ssm get-parameter --name /mahalo/gitea/admin-password --with-decryption --region "$REGION" --query Parameter.Value --output text)"
if [ -z "$ADMIN_PASS" ] || [ "$ADMIN_PASS" = "None" ]; then
  log "ERROR: could not read admin password from SSM"; exit 1
fi

# ---------------------------------------------------------------------------
# 1. Ensure Gitea is install-locked (INSTALL_LOCK=true + SECRET_KEY +
#    INTERNAL_TOKEN present).
# ---------------------------------------------------------------------------
LOCKED="$(docker exec gitea sh -c "grep -c '^INSTALL_LOCK = true' $INI_IN_CONTAINER" 2>/dev/null || echo 0)"
if [ "$LOCKED" != "1" ]; then
  log "completing install: generating secrets and patching app.ini"
  SECRET="$(docker exec gitea gitea generate secret SECRET_KEY)"
  INTERNAL="$(docker exec gitea gitea generate secret INTERNAL_TOKEN)"
  if [ -z "$SECRET" ] || [ -z "$INTERNAL" ]; then log "ERROR: secret generation failed"; exit 1; fi
  # Rewrite app.ini with awk, passing secrets as awk vars (no regex interpretation).
  docker exec -e SK="$SECRET" -e IT="$INTERNAL" gitea sh -c '
    awk -v sk="$SK" -v it="$IT" '"'"'
      /^INSTALL_LOCK/   { print "INSTALL_LOCK = true"; next }
      /^SECRET_KEY/     { print "SECRET_KEY = " sk; seen_sk=1; next }
      /^INTERNAL_TOKEN/ { print "INTERNAL_TOKEN = " it; seen_it=1; next }
                        { print }
      END {
        if (!seen_sk) print "SECRET_KEY = " sk
        if (!seen_it) print "INTERNAL_TOKEN = " it
      }
    '"'"' /data/gitea/conf/app.ini > /tmp/app.ini.new && cp /tmp/app.ini.new /data/gitea/conf/app.ini
  '
  # Keep app.ini writable by the git user (uid 1000) so gitea can persist its
  # auto-generated OAUTH2_JWT_SECRET on startup (otherwise it crash-loops).
  HOSTINI="$(docker inspect gitea --format '{{ range .Mounts }}{{ if eq .Destination "/data" }}{{ .Source }}{{ end }}{{ end }}')/gitea/conf/app.ini"
  chown 1000:1000 "$HOSTINI" 2>/dev/null || true
  chmod 660 "$HOSTINI" 2>/dev/null || true
  log "restarting gitea to apply install lock"
  docker restart gitea >/dev/null
  for i in $(seq 1 60); do
    curl -fsS "$GITEA_URL/api/healthz" >/dev/null 2>&1 && break
    [ "$i" -eq 60 ] && { log "ERROR: gitea not healthy after restart"; exit 1; }
    sleep 2
  done
  log "install lock applied; gitea healthy"
else
  log "gitea already install-locked"
fi

# ---------------------------------------------------------------------------
# 2. Create the admin user (idempotent) via the CLI as the git user.
# ---------------------------------------------------------------------------
if docker exec -u git gitea gitea --config "$INI_IN_CONTAINER" admin user list 2>/dev/null | awk 'NR>1 {print $2}' | grep -qx "$ADMIN_USER"; then
  log "admin user '$ADMIN_USER' already exists"
else
  log "creating admin user '$ADMIN_USER'"
  docker exec -u git gitea gitea --config "$INI_IN_CONTAINER" admin user create \
    --username "$ADMIN_USER" --password "$ADMIN_PASS" --email "$ADMIN_EMAIL" \
    --admin --must-change-password=false
fi
if ! docker exec -u git gitea gitea --config "$INI_IN_CONTAINER" admin user list 2>/dev/null | awk 'NR>1 {print $2}' | grep -qx "$ADMIN_USER"; then
  log "ERROR: admin user not present after create"; exit 1
fi
log "admin user confirmed"

AUTH="$ADMIN_USER:$ADMIN_PASS"

# ---------------------------------------------------------------------------
# 3. Mint an API token for the adapter (recreate to obtain a usable secret).
# ---------------------------------------------------------------------------
EXIST_ID="$(curl -fsS -u "$AUTH" "$GITEA_URL/api/v1/users/$ADMIN_USER/tokens" 2>/dev/null \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print(next((t["id"] for t in d if t["name"]=="mahalo-adapter"), ""))' 2>/dev/null || echo "")"
if [ -n "$EXIST_ID" ]; then
  log "deleting existing token id=$EXIST_ID to recreate"
  curl -fsS -X DELETE -u "$AUTH" "$GITEA_URL/api/v1/users/$ADMIN_USER/tokens/$EXIST_ID" >/dev/null 2>&1 || true
fi
TOKEN="$(curl -fsS -X POST -u "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"mahalo-adapter","scopes":["write:repository","write:user","read:organization"]}' \
  "$GITEA_URL/api/v1/users/$ADMIN_USER/tokens" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["sha1"])')"
if [ -z "$TOKEN" ]; then log "ERROR: failed to mint token"; exit 1; fi
log "API token minted"

# ---------------------------------------------------------------------------
# 4. Create + seed the sample repository (idempotent).
# ---------------------------------------------------------------------------
CODE="$(curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: token $TOKEN" \
  "$GITEA_URL/api/v1/repos/$ADMIN_USER/$SEED_REPO")"
if [ "$CODE" = "200" ]; then
  log "seed repo already exists"
else
  log "creating seed repo '$SEED_REPO'"
  curl -fsS -X POST -H "Authorization: token $TOKEN" -H 'Content-Type: application/json' \
    -d '{"name":"payment-service","description":"Payment processing microservice (mahalo-agentcore seed repo)","private":false,"auto_init":true,"default_branch":"main","readme":"Default"}' \
    "$GITEA_URL/api/v1/user/repos" >/dev/null
  log "seed repo created"
fi

# ---------------------------------------------------------------------------
# 5. Push the token to SSM SecureString.
# ---------------------------------------------------------------------------
aws ssm put-parameter --name /mahalo/gitea/adapter-token --type SecureString \
  --value "$TOKEN" --overwrite --region "$REGION" >/dev/null
log "token pushed to SSM /mahalo/gitea/adapter-token"

echo "gitea bootstrap complete $(date -u +%FT%TZ)" > /data/BOOTSTRAP_READY
log "BOOTSTRAP COMPLETE"
