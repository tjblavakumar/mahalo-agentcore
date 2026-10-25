#!/usr/bin/env python3
"""Verify Gitea seeding on the host (stdlib only). Prints repo/branch/PR evidence."""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:3000/api/v1"
OWNER = "mahalo_admin"
TOKEN = os.environ.get("GITEA_TOKEN", "")
if not TOKEN:
    print("ERROR: GITEA_TOKEN not set", file=sys.stderr)
    sys.exit(2)


def get(path):
    req = urllib.request.Request(BASE + path, method="GET")
    req.add_header("Authorization", "token " + TOKEN)
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


repos = get("/user/repos?limit=50")
names = sorted(r["name"] for r in repos)
print("REPO COUNT: %d" % len(repos))
print("REPOS: %s" % ", ".join(names))

for repo in ("payment-service", "auth-service"):
    print("--- %s ---" % repo)
    branches = get("/repos/%s/%s/branches" % (OWNER, repo))
    print("  branches (%d): %s" % (len(branches), ", ".join(b["name"] for b in branches)))
    pulls = get("/repos/%s/%s/pulls?state=open&limit=50" % (OWNER, repo))
    print("  open PRs (%d):" % len(pulls))
    for p in pulls:
        print("    #%d  %s" % (p["number"], p["title"]))
