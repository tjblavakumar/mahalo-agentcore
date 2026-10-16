"""Strands WRITE tools for the Mock GitHub service (Task 2, HITL-gated).

Thin ``@tool`` functions mirroring the Task 1 read-module pattern: read config
from ``agent.config.settings``, call the shared ``make_request`` seam, return a
formatted string, never raise. The real POST happens here only after the write is
approved by the hook (FEAT-002).

``github_create_branch`` treats a 409/422/"already exists" response as SUCCESS so
the branch -> commit -> PR chain can proceed on a re-run.
"""

from __future__ import annotations

import json
from typing import Optional

import httpx

from strands import tool

from agent.config import settings
from agent.tools.http import make_request


def _normalize_files_arg(files) -> list[dict]:
    """Normalize the ``files`` arg into a list of ``{"path", "content"}`` dicts.

    Tolerates a JSON string, a single dict, or a list of dicts. Each kept entry
    carries ``path`` and ``content`` (content coerced to ``str``, empty if
    missing). Entries without a path are dropped.
    """
    if isinstance(files, str):
        try:
            files = json.loads(files)
        except (ValueError, TypeError):
            return []
    if isinstance(files, dict):
        files = [files]
    if not isinstance(files, list):
        return []

    normalized: list[dict] = []
    for entry in files:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not path:
            continue
        normalized.append({"path": path, "content": str(entry.get("content", ""))})
    return normalized


@tool
def github_create_branch(repo_id: str, branch_name: str, from_branch: str = "main") -> str:
    """Create a new branch in a repository. [WRITE ACTION - REQUIRES APPROVAL]
    repo_id MUST be a real repository NAME from github_list_repos (e.g.
    "payment-service"). Do NOT invent ids like "repo-1"/"repo-4" — call
    github_list_repos first and use a name from that list.
    from_branch: the branch to fork from (default "main")."""
    body = {"name": branch_name, "from_branch": from_branch}
    try:
        data = make_request(
            settings.github_url,
            settings.github_token,
            endpoint=f"/repos/{repo_id}/branches",
            method="POST",
            body=body,
        )
    except (httpx.HTTPError, OSError) as exc:
        return f"❌ Failed to create branch: {exc}"

    if "error" in data:
        err = data["error"].lower()
        if "status 409" in err or "status 422" in err or "already exists" in err:
            return (
                f"✅ Branch **{branch_name}** already exists — reusing it. "
                f'Reply "commit the code" to proceed.'
            )
        return f"❌ Failed to create branch: {data['error']}"
    return f"✅ Branch created successfully: **{data['name']}**"


@tool
def github_commit_files(repo_id: str, branch: str, message: str, files) -> str:
    """Commit one or more files to a branch. [WRITE ACTION - REQUIRES APPROVAL]
    repo_id MUST be a real repository NAME from github_list_repos (e.g.
    "payment-service"). Do NOT invent ids like "repo-1".
    files: a list of {"path", "content"} objects. Each "content" MUST be the
    COMPLETE file text, never a diff — re-emit the full code you prepared."""
    normalized = _normalize_files_arg(files)
    body = {"branch": branch, "message": message, "files": normalized}
    try:
        data = make_request(
            settings.github_url,
            settings.github_token,
            endpoint=f"/repos/{repo_id}/commits",
            method="POST",
            body=body,
        )
    except (httpx.HTTPError, OSError) as exc:
        return f"❌ Failed to commit files: {exc}"

    if "error" in data:
        return f"❌ Failed to commit files: {data['error']}"
    result = f"✅ Committed {len(normalized)} files to **{branch}**"
    if data.get("url"):
        result += f"\n🔗 {data['url']}"
    return result


@tool
def github_open_pull_request(
    repo_id: str,
    head: str,
    base: str = "main",
    title: str = "",
    body: str = "",
) -> str:
    """Open a pull request. [WRITE ACTION - REQUIRES APPROVAL]
    repo_id MUST be a real repository NAME from github_list_repos (e.g.
    "payment-service"). Do NOT invent ids like "repo-1".
    head: the source branch; base: the target branch (default "main").
    title defaults to the head branch name if omitted."""
    request_body = {"head": head, "base": base, "title": title or head, "body": body}
    try:
        data = make_request(
            settings.github_url,
            settings.github_token,
            endpoint=f"/repos/{repo_id}/pulls",
            method="POST",
            body=request_body,
        )
    except (httpx.HTTPError, OSError) as exc:
        return f"❌ Failed to open pull request: {exc}"

    if "error" in data:
        return f"❌ Failed to open pull request: {data['error']}"
    result = f"✅ Pull request opened: **#{data['number']}** {data['title']}"
    if data.get("url"):
        result += f"\n🔗 {data['url']}"
    return result


GITHUB_WRITE_TOOLS = [github_create_branch, github_commit_files, github_open_pull_request]
