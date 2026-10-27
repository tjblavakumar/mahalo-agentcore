"""Strands read-only tools for the Mock GitHub service.

Ported verbatim (names, params, endpoints, docstrings, output formatting) from
mahalo-dock's ``github_tools.py``, with the Strands ``@tool`` in place of the
original decorator and module-level functions reading config from
``agent.config.settings``. Write tools are deferred to Task 2.
"""

from __future__ import annotations

from typing import Optional

from strands import tool

from agent.config import settings
from agent.tools.http import make_request


def _github_request(endpoint: str = "", params: Optional[dict] = None) -> dict:
    """Make a GET request to the GitHub mock service."""
    return make_request(settings.github_url, settings.github_token, endpoint=endpoint, params=params)


@tool
def github_list_repos() -> str:
    """List all available GitHub repositories."""
    data = _github_request(endpoint="/repos")
    if "error" in data:
        return f"Error: {data['error']}"

    output = "Available repositories:\n"
    for r in data.get("repos", []):
        output += f"- **{r['name']}** ({r['language']}) - {r['description']}\n"
        output += f"  Last push: {r['last_push']} | Open issues: {r['open_issues']}\n"
    return output


@tool
def github_get_pull_requests(repo_id: str, status: Optional[str] = None, author_id: Optional[str] = None) -> str:
    """Get pull requests for a repository. repo_id MUST be a real repository
    NAME as returned by github_list_repos (e.g. "payment-service"). Do NOT
    invent ids like "repo-1"/"repo-4" — call github_list_repos first and use
    a name from that list.
    Optional filters: status (open/draft/merged/closed), author_id (dev-1 through dev-6)."""
    params = {}
    if status:
        params["status"] = status
    if author_id:
        params["author_id"] = author_id
    data = _github_request(endpoint=f"/repos/{repo_id}/pulls", params=params)
    if "error" in data:
        return f"Error: {data['error']}"

    prs = data.get("pull_requests", [])
    if not prs:
        return f"No pull requests found for {repo_id}"

    output = f"Pull requests for {repo_id} ({len(prs)} found):\n"
    for pr in prs:
        output += f"\n🔀 **PR #{pr['number']}**: {pr['title']}\n"
        output += f"   Author: {pr['author']} | Status: {pr['status']} | Branch: {pr['branch']}\n"
        output += f"   +{pr['additions']}/-{pr['deletions']} ({pr['files_changed']} files)\n"
        if pr.get("linked_story"):
            output += f"   Linked story: {pr['linked_story']}\n"
        if pr.get("reviews"):
            for review in pr["reviews"]:
                output += f"   Review: {review['reviewer']} - {review['status']}\n"
    return output


@tool
def github_get_commits(repo_id: str, branch: Optional[str] = None, author: Optional[str] = None) -> str:
    """Get recent commits for a repository. Can filter by branch name or author (name or dev-ID).
    repo_id MUST be a real repository NAME from github_list_repos (e.g.
    "payment-service"). Do NOT invent ids like "repo-1"."""
    params = {}
    if branch:
        params["branch"] = branch
    if author:
        params["author"] = author
    data = _github_request(endpoint=f"/repos/{repo_id}/commits", params=params)
    if "error" in data:
        return f"Error: {data['error']}"

    commits = data.get("commits", [])
    if not commits:
        return "No commits found"

    output = f"Recent commits ({len(commits)}):\n"
    for c in commits:
        output += f"- [{c['date']}] {c['message']} (by {c['author']}, +{c['additions']}/-{c['deletions']})\n"
    return output


@tool
def github_get_repo_stats(repo_id: str) -> str:
    """Get repository statistics including contributor activity, total commits, and branch info.
    repo_id MUST be a real repository NAME from github_list_repos (e.g.
    "payment-service"). Do NOT invent ids like "repo-1"."""
    data = _github_request(endpoint=f"/repos/{repo_id}/stats")
    if "error" in data:
        return f"Error: {data['error']}"

    output = f"Repository stats for {repo_id}:\n"
    output += f"- Total commits: {data['total_commits']}\n"
    output += f"- Total additions: {data['total_additions']}\n"
    output += f"- Total deletions: {data['total_deletions']}\n"
    output += f"- Active branches: {data['active_branches']}\n"
    output += f"- Open PRs: {data['open_prs']}\n"
    output += "\nContributors:\n"
    for c in data.get("contributors", []):
        output += f"  - {c['author']}: {c['commits']} commits (+{c['additions']}/-{c['deletions']})\n"
    return output


@tool
def github_pull_requests_all_repos() -> str:
    """Get open pull requests across EVERY repository, grouped by repo, in one
    call. Use this for a delivery/portfolio overview instead of calling
    github_get_pull_requests once per repo."""
    repos_data = _github_request(endpoint="/repos")
    if "error" in repos_data:
        return f"Error: {repos_data['error']}"
    repos = repos_data.get("repos", [])
    if not repos:
        return "No repositories found."

    output = "Pull requests across all repositories:\n"
    for repo in repos:
        # Key off the stored seed id; the mock filters PRs by repo_id, so the
        # repo NAME would return an empty list.
        repo_id = repo["id"]
        repo_name = repo.get("name", repo_id)
        data = _github_request(endpoint=f"/repos/{repo_id}/pulls")
        prs = data.get("pull_requests", []) if isinstance(data, dict) else []
        output += f"\n=== {repo_name} ({len(prs)} PRs) ===\n"
        if not prs:
            output += "  (no pull requests)\n"
        for pr in prs:
            output += f"  🔀 PR #{pr['number']}: {pr['title']}\n"
            output += f"     Author: {pr['author']} | Status: {pr['status']} | Branch: {pr['branch']}\n"
            if pr.get("linked_story"):
                output += f"     Linked story: {pr['linked_story']}\n"
    return output


GITHUB_TOOLS = [
    github_list_repos,
    github_get_pull_requests,
    github_get_commits,
    github_get_repo_stats,
    github_pull_requests_all_repos,
]
