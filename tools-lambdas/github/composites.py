"""Server-side GitHub composites for Gateway (MCP) mode.

``github_pull_requests_all_repos`` is not a single HTTP call in DIRECT mode: the
agent lists repos then fans out, calling ``github_get_pull_requests`` once per
repo. This handler reproduces that fan-out server-side by calling the Lambda's
own routes through the in-process ``Router`` and grouping the pull requests by
repo, returning plain JSON (the model re-renders it).

Like the Jira/ServiceNow composites it reads only through
``common.gateway_dispatch.get_json`` and never dereferences ``store`` — so it
works unchanged on both the mock DynamoDB path and the real Gitea path (both
register the same ``GET /repos`` and ``GET /repos/{repo_id}/pulls`` routes).
"""

from __future__ import annotations

from typing import Any, Dict, List

from common.gateway_dispatch import get_json


def pull_requests_all_repos(store, router, token, args: Dict[str, Any]) -> Dict[str, Any]:
    """Reproduce the per-repo ``github_get_pull_requests`` fan-out, grouped by repo.

    Ignores ``args`` (no inputs). GETs ``/repos`` then, for each repo, GETs
    ``/repos/{repo["id"]}/pulls`` using the SEED id (``repo-1``…) — NOT the repo
    name — because the mock route filters PRs by the stored ``repo_id`` (the seed
    id); keying by name would return an empty list. Feeding each repo's own ``id``
    from ``/repos`` back into the pulls route keeps the round-trip internally
    consistent on the real Gitea path too.

    Each per-repo ``pull_requests``/``total`` is carried VERBATIM from the route
    body; the top-level ``total_pull_requests`` is the sum of the per-repo totals.
    """
    repos_data = get_json(router, token, "/repos")
    repos = repos_data.get("repos", []) if isinstance(repos_data, dict) else []

    grouped: List[Dict[str, Any]] = []
    for repo in repos:
        repo_id = repo["id"]
        pulls_data = get_json(router, token, f"/repos/{repo_id}/pulls")
        if isinstance(pulls_data, dict):
            pull_requests = pulls_data.get("pull_requests", [])
            total = pulls_data.get("total", len(pull_requests))
        else:
            pull_requests = []
            total = 0
        grouped.append(
            {
                "repo_id": repo_id,
                "repo_name": repo.get("name", repo_id),
                "pull_requests": pull_requests,
                "total": total,
            }
        )

    return {
        "repos": grouped,
        "total_pull_requests": sum(r["total"] for r in grouped),
    }
