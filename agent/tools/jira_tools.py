"""Strands read-only tools for the Mock Jira service.

Ported from mahalo-dock's ``jira_tools.py``: same tool names, parameters,
endpoints, behavioral docstrings, and human-readable output formatting. The
original tool decorator is replaced by the Strands ``@tool``, and the
per-instance closure factory is replaced by module-level functions that read the
base URL and token from ``agent.config.settings``. Write tools are deferred to
Task 2.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from strands import tool

from agent.config import settings
from agent.tools.http import make_request

# Pin assignee name->dev-id resolution to the SINGLE source of truth shared with
# the Gateway-mode Lambda composites (tools-lambdas/common/assignee.py). The
# resolver body lives there; this module keeps the thin HTTP-fetching wrapper.
# The shim adds the repo-root ``tools-lambdas`` dir to ``sys.path`` so ``common``
# imports as a top-level package exactly as it does inside each Lambda asset.
# This is import-time only, offline-safe (no AWS/network), and a no-op if the
# path is already present.
_TOOLS_LAMBDAS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tools-lambdas",
)
if _TOOLS_LAMBDAS_DIR not in sys.path:
    sys.path.append(_TOOLS_LAMBDAS_DIR)

from common.assignee import resolve_assignee as _resolve_assignee_impl  # noqa: E402


def _jira_request(endpoint: str = "", params: Optional[dict] = None) -> dict:
    """Make a GET request to the Jira mock service."""
    return make_request(settings.jira_url, settings.jira_token, endpoint=endpoint, params=params)


def _fetch_developers() -> list[dict]:
    """Fetch the developer directory from Jira."""
    data = _jira_request(endpoint="/developers")
    return data.get("developers", []) if isinstance(data, dict) else []


def _resolve_assignee(assignee: str) -> Optional[str]:
    """Resolve an assignee reference to a developer ID.

    Accepts a developer ID (dev-1..dev-5) as-is, or resolves a person's
    name (full name, first name, or email local-part) to their dev-ID.
    Returns None if no confident match is found.

    Thin wrapper over the shared ``common.assignee.resolve_assignee`` body (the
    one source of truth also used by the Gateway-mode Jira composites). The
    ``dev-`` short-circuit avoids an unnecessary ``/developers`` fetch, matching
    the resolver's own short-circuit.
    """
    if not assignee:
        return None
    if assignee.strip().lower().startswith("dev-"):
        return _resolve_assignee_impl(assignee, [])
    return _resolve_assignee_impl(assignee, _fetch_developers())


def _format_stories(results: list[dict], label: str, developers: Optional[list[dict]] = None) -> str:
    """Format a list of stories with human-readable assignee names."""
    dev_by_id = {d["id"]: d["name"] for d in (developers or [])}
    output = f"Found {len(results)} stories {label}:\n"
    for s in results:
        assignee_id = s.get("assignee")
        assignee_name = dev_by_id.get(assignee_id, assignee_id or "Unassigned")
        output += (
            f"- [{s['id']}] {s['title']} | Status: {s['status']} | "
            f"Points: {s['story_points']} | Assignee: {assignee_name}\n"
        )
    return output


@tool
def jira_list_developers() -> str:
    """List all developers (team members) in Jira with their IDs, names, and emails.
    Use this to resolve a person's name (e.g. 'Raj') to their developer ID (e.g. dev-3)
    before filtering stories, PRs, or commits by assignee/author."""
    developers = _fetch_developers()
    if not developers:
        return "No developers found."
    output = "Developers:\n"
    for d in developers:
        output += f"- {d['id']}: {d['name']} ({d.get('email', 'no email')})\n"
    return output


@tool
def jira_get_stories_by_assignee(assignee: str, status: Optional[str] = None, project_id: Optional[str] = None) -> str:
    """Get all Jira stories assigned to a specific person across all projects (or one project).
    assignee: a developer ID (dev-1..dev-5) OR a person's name/first name (e.g. 'Raj', 'Raj Patel').
    Names are automatically resolved to developer IDs.
    Optional filters: status (todo/in_progress/in_review/done), project_id."""
    developers = _fetch_developers()
    dev_id = _resolve_assignee(assignee)
    if not dev_id:
        names = ", ".join(f"{d['name']} ({d['id']})" for d in developers)
        return (
            f"Could not resolve '{assignee}' to a known developer. "
            f"Available developers: {names}"
        )

    params = {"assignee": dev_id}
    if status:
        params["status"] = status

    results = []
    if project_id:
        data = _jira_request(endpoint=f"/projects/{project_id}/stories", params=params)
        results = data.get("stories", []) if isinstance(data, dict) else []
    else:
        projects_data = _jira_request(endpoint="/projects")
        for proj in projects_data.get("projects", []) if isinstance(projects_data, dict) else []:
            data = _jira_request(endpoint=f"/projects/{proj['id']}/stories", params=params)
            results.extend(data.get("stories", []) if isinstance(data, dict) else [])

    dev_name = next((d["name"] for d in developers if d["id"] == dev_id), dev_id)
    if not results:
        status_note = f" with status '{status}'" if status else ""
        return f"No stories assigned to {dev_name} ({dev_id}){status_note}."

    return _format_stories(results, f"assigned to {dev_name} ({dev_id})", developers)


@tool
def jira_search_stories(query: Optional[str] = None, project_id: Optional[str] = None, status: Optional[str] = None, assignee: Optional[str] = None) -> str:
    """Search for stories in Jira. Can filter by project_id, status (todo/in_progress/in_review/done), and assignee.
    query: optional keyword matched against story title/description. Omit it to list all stories matching the filters.
    assignee: a developer ID (dev-1..dev-5) OR a person's name (e.g. 'Raj') which will be resolved automatically.
    If filtering by a person, prefer the jira_get_stories_by_assignee tool.
    If project_id is not specified, searches across all projects."""
    developers = _fetch_developers()

    # Resolve a name-based assignee to a developer ID for the API filter
    assignee_id = None
    if assignee:
        assignee_id = _resolve_assignee(assignee)
        if not assignee_id:
            names = ", ".join(f"{d['name']} ({d['id']})" for d in developers)
            return f"Could not resolve assignee '{assignee}'. Available developers: {names}"

    keyword = (query or "").strip().lower()

    def _matches_keyword(s: dict) -> bool:
        if not keyword:
            return True
        return keyword in s["title"].lower() or keyword in s.get("description", "").lower()

    def _base_params() -> dict:
        params = {}
        if status:
            params["status"] = status
        if assignee_id:
            params["assignee"] = assignee_id
        return params

    results = []
    if project_id:
        data = _jira_request(endpoint=f"/projects/{project_id}/stories", params=_base_params())
        stories = data.get("stories", []) if isinstance(data, dict) else []
        results = [s for s in stories if _matches_keyword(s)]
    else:
        projects_data = _jira_request(endpoint="/projects")
        for proj in projects_data.get("projects", []) if isinstance(projects_data, dict) else []:
            data = _jira_request(endpoint=f"/projects/{proj['id']}/stories", params=_base_params())
            stories = data.get("stories", []) if isinstance(data, dict) else []
            results.extend(s for s in stories if _matches_keyword(s))

    if not results:
        descriptor = f"matching '{query}'" if query else "matching the given filters"
        return f"No stories found {descriptor}."

    label = f"matching '{query}'" if query else "matching the given filters"
    return _format_stories(results, label, developers)


@tool
def jira_get_story(story_id: str) -> str:
    """Get detailed information about a specific Jira story by its ID (e.g., PAY-105)."""
    data = _jira_request(endpoint=f"/stories/{story_id}")
    if "error" in data:
        return f"Error: {data['error']}"

    output = f"**{data['id']}: {data['title']}**\n"
    output += f"- Status: {data['status']}\n"
    output += f"- Priority: {data['priority']}\n"
    output += f"- Story Points: {data['story_points']}\n"
    output += f"- Assignee: {data.get('assignee_details', {}).get('name', data.get('assignee', 'Unassigned'))}\n"
    output += f"- Sprint: {data.get('sprint_id', 'Backlog')}\n"
    output += f"\nDescription: {data['description']}\n"
    if data.get("acceptance_criteria"):
        output += "\nAcceptance Criteria:\n"
        for ac in data["acceptance_criteria"]:
            output += f"  - {ac}\n"
    if data.get("comments"):
        output += "\nComments:\n"
        for c in data["comments"]:
            output += f"  - [{c['date']}] {c['author']}: {c['text']}\n"
    return output


@tool
def jira_get_sprint_info(project_id: str) -> str:
    """Get sprint information and velocity data for a project. Use project IDs like PAY, CART, AUTH, PROD, ORD."""
    data = _jira_request(endpoint=f"/sprints/{project_id}")
    if "error" in data:
        return f"Error: {data['error']}"

    output = f"Sprints for project {project_id}:\n"
    for sprint in data.get("sprints", []):
        output += f"\n**{sprint['name']}** ({sprint['status']})\n"
        output += f"  Period: {sprint['start_date']} to {sprint['end_date']}\n"
        if sprint.get("velocity"):
            output += f"  Velocity: {sprint['velocity']} points\n"
        if sprint.get("completed_points") is not None:
            output += f"  Completed: {sprint['completed_points']}/{sprint['total_points']} points\n"
    return output


@tool
def jira_get_board(project_id: str) -> str:
    """Get the current sprint board showing stories grouped by status for a project."""
    data = _jira_request(endpoint=f"/projects/{project_id}/board")
    if "error" in data:
        return f"Error: {data['error']}"

    if not data.get("sprint"):
        return f"No active sprint found for project {project_id}"

    sprint = data["sprint"]
    columns = data["columns"]
    output = f"**Sprint Board: {sprint['name']}** ({sprint['start_date']} to {sprint['end_date']})\n\n"

    for col_name, stories in columns.items():
        output += f"📌 {col_name.upper()} ({len(stories)}):\n"
        for s in stories:
            output += f"  - [{s['id']}] {s['title']} ({s['story_points']}pts) - {s.get('assignee', 'Unassigned')}\n"
        output += "\n"
    return output


@tool
def jira_list_projects() -> str:
    """List all available Jira projects."""
    data = _jira_request(endpoint="/projects")
    if "error" in data:
        return f"Error: {data['error']}"

    output = "Available projects:\n"
    for p in data.get("projects", []):
        output += f"- **{p['id']}**: {p['name']} - {p['description']}\n"
    return output


JIRA_TOOLS = [
    jira_list_projects,
    jira_list_developers,
    jira_search_stories,
    jira_get_stories_by_assignee,
    jira_get_story,
    jira_get_sprint_info,
    jira_get_board,
]
