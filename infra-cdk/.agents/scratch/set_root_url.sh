#!/usr/bin/env bash
# Set Gitea [server] ROOT_URL to the CloudFront HTTPS domain, in-container app.ini.
# Does NOT touch HTTP_PORT (stays 3000) or the 0.0.0.0 bind. Keeps app.ini owned
# by uid 1000 (git) / mode 660 so Gitea can persist OAUTH2_JWT_SECRET on startup.
set -uo pipefail

ROOT_URL="https://d3ec76atxiij9a.cloudfront.net/"
GITEA_URL="http://localhost:3000"

log() { echo "[set_root_url] $*"; }

# Resolve the host path of app.ini from the container's /data bind mount.
HOSTDATA="$(docker inspect gitea --format '{{ range .Mounts }}{{ if eq .Destination "/data" }}{{ .Source }}{{ end }}{{ end }}')"
if [ -z "$HOSTDATA" ]; then log "ERROR: could not resolve /data mount source"; exit 1; fi
HOSTINI="$HOSTDATA/gitea/conf/app.ini"
if [ ! -f "$HOSTINI" ]; then log "ERROR: app.ini not found at $HOSTINI"; exit 1; fi

log "app.ini host path: $HOSTINI"
log "current ROOT_URL / HTTP_PORT before edit:"
grep -nE '^(ROOT_URL|HTTP_PORT)' "$HOSTINI" || true

# Rewrite ROOT_URL under the [server] section using awk (value passed as awk var,
# no regex interpretation). If a ROOT_URL already exists anywhere, replace it;
# otherwise insert it right after the [server] section header. HTTP_PORT and the
# listen bind are left untouched.
awk -v ru="$ROOT_URL" '
  BEGIN { in_server=0; done=0 }
  /^\[server\]/ {
    print; in_server=1; next
  }
  /^\[/ && !/^\[server\]/ {
    if (in_server==1 && done==0) { print "ROOT_URL = " ru; done=1 }
    in_server=0; print; next
  }
  /^[[:space:]]*ROOT_URL[[:space:]]*=/ {
    if (done==0) { print "ROOT_URL = " ru; done=1 }
    next
  }
  { print }
  END {
    if (done==0) {
      if (in_server==0) print "[server]"
      print "ROOT_URL = " ru
    }
  }
' "$HOSTINI" > /tmp/app.ini.new && cp /tmp/app.ini.new "$HOSTINI"

# MANDATORY: restore uid 1000 ownership + 660 so Gitea can write on startup.
chown 1000:1000 "$HOSTINI"
chmod 660 "$HOSTINI"

log "ROOT_URL / HTTP_PORT after edit:"
grep -nE '^(ROOT_URL|HTTP_PORT)' "$HOSTINI" || true

log "restarting gitea container"
docker restart gitea >/dev/null

log "polling health"
for i in $(seq 1 60); do
  if curl -fsS "$GITEA_URL/api/healthz" >/dev/null 2>&1; then
    log "gitea healthy after restart"
    curl -fsS "$GITEA_URL/api/healthz"; echo
    log "DONE"
    exit 0
  fi
  sleep 2
done
log "ERROR: gitea not healthy after restart"
exit 1
