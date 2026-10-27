"""Server-side Jira composites for Gateway (MCP) mode.

Two of the Jira operations are NOT a single HTTP call in DIRECT mode: the agent
resolves a person's name to a dev-id (via ``/developers``) and fans out over
projects/stories. In GATEWAY mode that orchestration must happen behind the tool,
so these handlers reproduce it server-side by calling the Lambda's own routes
through the in-process ``Router`` and reusing the shared
``common.assignee.resolve_assignee`` (the one source of truth also used by the
agent wrapper).

Each composite returns a plain JSON dict (the structured data, not a formatted
string); the model re-renders it. Data equivalence with DIRECT mode — same
records, same ids, same keyword filter — is what is guaranteed.
"""

from __future__ import annotations

from typing import Any, Dict, List

from common.assignee import resolve_assignee
from common.gateway_dispatch import get_json


def _developers(router, token) -> List[dict]:
    data = get_json(router, token, "/developers")
    return data.get("developers", []) if isinstance(data, dict) else []


def _project_ids(router, token) -> List[str]:
    data = get_json(router, token, "/projects")
    projects = data.get("projects", []) if isinstance(data, dict) else []
    return [p["id"] for p in projects]


def _stories_for_project(router, token, project_id: str, params: Dict[str, str]) -> List[dict]:
    data = get_json(router, token, f"/projects/{project_id}/stories", query=params)
    return data.get("stories", []) if isinstance(data, dict) else []


def _resolve_or_error(assignee: str, developers: List[dict]) -> Dict[str, Any] | str:
    """Return the resolved dev-id, or an ``{"error": ...}`` dict like DIRECT mode."""
    dev_id = resolve_assignee(assignee, developers)
    if not dev_id:
        names = ", ".join(f"{d['name']} ({d['id']})" for d in developers)
        return {"error": f"Could not resolve assignee '{assignee}'. Available developers: {names}"}
    return dev_id


def stories_by_assignee(store, router, token, args: Dict[str, Any]) -> Dict[str, Any]:
    """Reproduce ``jira_get_stories_by_assignee``: resolve name, fan out, collect."""
    assignee = args.get("assignee")
    status = args.get("status")
    project_id = args.get("project_id")

    developers = _developers(router, token)
    dev_id = _resolve_or_error(assignee, developers)
    if isinstance(dev_id, dict):
        return dev_id

    params: Dict[str, str] = {"assignee": dev_id}
    if status:
        params["status"] = status

    results: List[dict] = []
    if project_id:
        results = _stories_for_project(router, token, project_id, params)
    else:
        for pid in _project_ids(router, token):
            results.extend(_stories_for_project(router, token, pid, params))

    return {"stories": results, "total": len(results), "assignee": dev_id}


def search_stories(store, router, token, args: Dict[str, Any]) -> Dict[str, Any]:
    """Reproduce ``jira_search_stories``: optional name resolution + keyword filter."""
    query = args.get("query")
    project_id = args.get("project_id")
    status = args.get("status")
    assignee = args.get("assignee")

    developers = _developers(router, token)

    assignee_id = None
    if assignee:
        resolved = _resolve_or_error(assignee, developers)
        if isinstance(resolved, dict):
            return resolved
        assignee_id = resolved

    keyword = (query or "").strip().lower()

    def _matches_keyword(s: dict) -> bool:
        if not keyword:
            return True
        return keyword in s["title"].lower() or keyword in s.get("description", "").lower()

    params: Dict[str, str] = {}
    if status:
        params["status"] = status
    if assignee_id:
        params["assignee"] = assignee_id

    results: List[dict] = []
    if project_id:
        stories = _stories_for_project(router, token, project_id, params)
        results = [s for s in stories if _matches_keyword(s)]
    else:
        for pid in _project_ids(router, token):
            stories = _stories_for_project(router, token, pid, params)
            results.extend(s for s in stories if _matches_keyword(s))

    return {"stories": results, "total": len(results)}


def portfolio_sprint_status(store, router, token, args: Dict[str, Any]) -> Dict[str, Any]:
    """Reproduce the per-project ``jira_get_sprint_info`` + ``jira_get_board`` fan-out.

    One call returns, per project, the sprint info and the current sprint board the
    delivery overview needs — collapsing the model's ``jira_get_sprint_info`` ×N +
    ``jira_get_board`` ×N loop server-side. Ignores ``args`` (no inputs).

    For each project in ``/projects`` order it issues the same two GETs the granular
    tools do and nests the sub-bodies VERBATIM so the data is field-for-field
    equivalent with DIRECT mode:

    * ``sprints`` — the ``"sprints"`` value of ``GET /sprints/{project_id}`` (the
      active sprint carries the route-computed ``completed_points``/``total_points``);
    * ``board`` — the whole body of ``GET /projects/{project_id}/board`` (``{"sprint":
      ..., "columns": ...}``; an inactive-sprint project yields ``columns: {}``,
      nested as-is — the composite never normalizes it).
    """
    projects: List[Dict[str, Any]] = []
    for project_id in _project_ids(router, token):
        sprint_data = get_json(router, token, f"/sprints/{project_id}")
        sprints = sprint_data.get("sprints", []) if isinstance(sprint_data, dict) else []
        board = get_json(router, token, f"/projects/{project_id}/board")
        projects.append(
            {
                "project_id": project_id,
                "sprints": sprints,
                "board": board,
            }
        )

    return {"projects": projects, "total_projects": len(projects)}
