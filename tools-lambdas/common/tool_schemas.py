"""Single source of truth for the 25 Gateway MCP tools (Task 4).

One descriptor per agent operation, consumed by BOTH:

* the CDK ``MahaloGatewayStack`` (``name``, ``description``, ``input_schema``
  feed each Gateway target's ``toolSchema.inlinePayload``), and
* the Lambda ``common.gateway_adapter`` (``method``, ``path_template``,
  ``arg_mapping`` and ``composite`` tell the adapter how to turn a flat Gateway
  args map into the existing in-Lambda ``Router`` call).

Because both sides read this one module, the published schema and the adapter
mapping cannot drift. The tool ``name`` equals the current Strands ``@tool``
function name verbatim so prompts, docstrings and the HITL write-name set carry
over unchanged. Pure data + stdlib; importable from both ``infra-cdk`` and the
Lambdas.

``arg_mapping`` keys classify each declared input argument:

* ``path``  -> fills a ``{segment}`` in ``path_template``;
* ``query`` -> becomes a query-string param (GET);
* ``body``  -> becomes a JSON body field (POST/PUT).

An ``arg_mapping`` entry maps the TOOL arg name to the WIRE name the route reads
(usually identical; the documented quirks are ``branch_name`` -> ``name`` and
the composite-only transforms). ``composite`` names the ``service.func`` handler
that reproduces agent-only orchestration server-side (see the composite modules).
"""

from __future__ import annotations

from typing import Any, Dict, List

# A JSON-Schema-subset ``object`` property. Only the keys AgentCore's
# SchemaDefinition understands (type/description/properties/required/items).
_STR = {"type": "string"}
_INT = {"type": "integer"}


def _obj(properties: Dict[str, Any], required: List[str] | None = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


# --------------------------------------------------------------------------- #
# The 25 tool descriptors. Grouped by service for readability; ``service`` tags
# which Gateway target (and Lambda) each belongs to.
# --------------------------------------------------------------------------- #

TOOLS: List[Dict[str, Any]] = [
    # ----- Jira (9: 7 read + 2 write) -----
    {
        "name": "jira_list_projects",
        "service": "jira",
        "description": "List all available Jira projects.",
        "input_schema": _obj({}),
        "method": "GET",
        "path_template": "/projects",
        "arg_mapping": {},
    },
    {
        "name": "jira_list_developers",
        "service": "jira",
        "description": (
            "List all developers (team members) in Jira with their IDs, names, "
            "and emails. Use this to resolve a person's name (e.g. 'Raj') to "
            "their developer ID (e.g. dev-3) before filtering stories, PRs, or "
            "commits by assignee/author."
        ),
        "input_schema": _obj({}),
        "method": "GET",
        "path_template": "/developers",
        "arg_mapping": {},
    },
    {
        "name": "jira_search_stories",
        "service": "jira",
        "description": (
            "Search for stories in Jira. Can filter by project_id, status "
            "(todo/in_progress/in_review/done), and assignee. query: optional "
            "keyword matched against story title/description. Omit it to list "
            "all stories matching the filters. assignee: a developer ID "
            "(dev-1..dev-5) OR a person's name (e.g. 'Raj') which will be "
            "resolved automatically. If filtering by a person, prefer "
            "jira_get_stories_by_assignee. If project_id is not specified, "
            "searches across all projects."
        ),
        "input_schema": _obj(
            {
                "query": _STR,
                "project_id": _STR,
                "status": _STR,
                "assignee": _STR,
            }
        ),
        "composite": "jira.composites.search_stories",
    },
    {
        "name": "jira_get_stories_by_assignee",
        "service": "jira",
        "description": (
            "Get all Jira stories assigned to a specific person across all "
            "projects (or one project). assignee: a developer ID (dev-1..dev-5) "
            "OR a person's name/first name (e.g. 'Raj', 'Raj Patel'). Names are "
            "automatically resolved to developer IDs. Optional filters: status "
            "(todo/in_progress/in_review/done), project_id."
        ),
        "input_schema": _obj(
            {
                "assignee": _STR,
                "status": _STR,
                "project_id": _STR,
            },
            required=["assignee"],
        ),
        "composite": "jira.composites.stories_by_assignee",
    },
    {
        "name": "jira_get_story",
        "service": "jira",
        "description": (
            "Get detailed information about a specific Jira story by its ID "
            "(e.g., PAY-105)."
        ),
        "input_schema": _obj({"story_id": _STR}, required=["story_id"]),
        "method": "GET",
        "path_template": "/stories/{story_id}",
        "arg_mapping": {"story_id": {"in": "path", "name": "story_id"}},
    },
    {
        "name": "jira_get_sprint_info",
        "service": "jira",
        "description": (
            "Get sprint information and velocity data for a project. Use project "
            "IDs like PAY, CART, AUTH, PROD, ORD."
        ),
        "input_schema": _obj({"project_id": _STR}, required=["project_id"]),
        "method": "GET",
        "path_template": "/sprints/{project_id}",
        "arg_mapping": {"project_id": {"in": "path", "name": "project_id"}},
    },
    {
        "name": "jira_get_board",
        "service": "jira",
        "description": (
            "Get the current sprint board showing stories grouped by status for "
            "a project."
        ),
        "input_schema": _obj({"project_id": _STR}, required=["project_id"]),
        "method": "GET",
        "path_template": "/projects/{project_id}/board",
        "arg_mapping": {"project_id": {"in": "path", "name": "project_id"}},
    },
    {
        "name": "jira_create_story",
        "service": "jira",
        "description": (
            "Create a new story in a Jira project. [WRITE ACTION - REQUIRES "
            "APPROVAL] project_id: the project key (e.g. PAY, CART, AUTH, PROD, "
            "ORD). title/description: required. priority: critical | high | "
            "medium | low (default medium). story_points: integer estimate "
            "(default 0). assignee: a developer ID (dev-1..dev-6) or None."
        ),
        "input_schema": _obj(
            {
                "project_id": _STR,
                "title": _STR,
                "description": _STR,
                "priority": _STR,
                "story_points": _INT,
                "assignee": _STR,
            },
            required=["project_id", "title", "description"],
        ),
        "method": "POST",
        "path_template": "/stories",
        "arg_mapping": {
            "project_id": {"in": "body", "name": "project_id"},
            "title": {"in": "body", "name": "title"},
            "description": {"in": "body", "name": "description"},
            "priority": {"in": "body", "name": "priority"},
            "story_points": {"in": "body", "name": "story_points"},
            "assignee": {"in": "body", "name": "assignee"},
        },
    },
    {
        "name": "jira_update_story",
        "service": "jira",
        "description": (
            "Update an existing Jira story. [WRITE ACTION - REQUIRES APPROVAL] "
            "story_id: the story key (e.g. PAY-105) — must already exist. "
            "Provide ONLY the fields to change: status "
            "(todo/in_progress/in_review/done), assignee (a developer ID "
            "dev-1..dev-6 or a person's name, resolved to a dev-ID), priority, "
            "story_points, sprint_id."
        ),
        "input_schema": _obj(
            {
                "story_id": _STR,
                "status": _STR,
                "assignee": _STR,
                "priority": _STR,
                "story_points": _INT,
                "sprint_id": _STR,
            },
            required=["story_id"],
        ),
        "method": "PUT",
        "path_template": "/stories/{story_id}",
        # ``assignee`` is resolved name->dev-id by the composite-free adapter
        # path (see gateway_adapter); only changed (non-None) fields are sent.
        "arg_mapping": {
            "story_id": {"in": "path", "name": "story_id"},
            "status": {"in": "body", "name": "status"},
            "assignee": {"in": "body", "name": "assignee", "resolve_assignee": True},
            "priority": {"in": "body", "name": "priority"},
            "story_points": {"in": "body", "name": "story_points"},
            "sprint_id": {"in": "body", "name": "sprint_id"},
        },
    },
    # ----- GitHub (7: 4 read + 3 write) -----
    {
        "name": "github_list_repos",
        "service": "github",
        "description": "List all available GitHub repositories.",
        "input_schema": _obj({}),
        "method": "GET",
        "path_template": "/repos",
        "arg_mapping": {},
    },
    {
        "name": "github_get_pull_requests",
        "service": "github",
        "description": (
            "Get pull requests for a repository. repo_id MUST be a real "
            "repository NAME as returned by github_list_repos (e.g. "
            '"payment-service"). Do NOT invent ids like "repo-1"/"repo-4" — '
            "call github_list_repos first and use a name from that list. "
            "Optional filters: status (open/draft/merged/closed), author_id "
            "(dev-1 through dev-6)."
        ),
        "input_schema": _obj(
            {"repo_id": _STR, "status": _STR, "author_id": _STR},
            required=["repo_id"],
        ),
        "method": "GET",
        "path_template": "/repos/{repo_id}/pulls",
        "arg_mapping": {
            "repo_id": {"in": "path", "name": "repo_id"},
            "status": {"in": "query", "name": "status"},
            "author_id": {"in": "query", "name": "author_id"},
        },
    },
    {
        "name": "github_get_commits",
        "service": "github",
        "description": (
            "Get recent commits for a repository. Can filter by branch name or "
            "author (name or dev-ID). repo_id MUST be a real repository NAME "
            'from github_list_repos (e.g. "payment-service"). Do NOT invent ids '
            'like "repo-1".'
        ),
        "input_schema": _obj(
            {"repo_id": _STR, "branch": _STR, "author": _STR},
            required=["repo_id"],
        ),
        "method": "GET",
        "path_template": "/repos/{repo_id}/commits",
        # NOTE: the commits route reads query ``author`` (NOT ``author_id``).
        "arg_mapping": {
            "repo_id": {"in": "path", "name": "repo_id"},
            "branch": {"in": "query", "name": "branch"},
            "author": {"in": "query", "name": "author"},
        },
    },
    {
        "name": "github_get_repo_stats",
        "service": "github",
        "description": (
            "Get repository statistics including contributor activity, total "
            "commits, and branch info. repo_id MUST be a real repository NAME "
            'from github_list_repos (e.g. "payment-service"). Do NOT invent ids '
            'like "repo-1".'
        ),
        "input_schema": _obj({"repo_id": _STR}, required=["repo_id"]),
        "method": "GET",
        "path_template": "/repos/{repo_id}/stats",
        "arg_mapping": {"repo_id": {"in": "path", "name": "repo_id"}},
    },
    {
        "name": "github_create_branch",
        "service": "github",
        "description": (
            "Create a new branch in a repository. [WRITE ACTION - REQUIRES "
            "APPROVAL] repo_id MUST be a real repository NAME from "
            'github_list_repos (e.g. "payment-service"). Do NOT invent ids like '
            '"repo-1"/"repo-4" — call github_list_repos first and use a name '
            "from that list. from_branch: the branch to fork from "
            '(default "main").'
        ),
        "input_schema": _obj(
            {"repo_id": _STR, "branch_name": _STR, "from_branch": _STR},
            required=["repo_id", "branch_name"],
        ),
        "method": "POST",
        "path_template": "/repos/{repo_id}/branches",
        # NOTE: the route reads ``body["name"]``; the tool arg is ``branch_name``.
        "arg_mapping": {
            "repo_id": {"in": "path", "name": "repo_id"},
            "branch_name": {"in": "body", "name": "name"},
            "from_branch": {"in": "body", "name": "from_branch"},
        },
    },
    {
        "name": "github_commit_files",
        "service": "github",
        "description": (
            "Commit one or more files to a branch. [WRITE ACTION - REQUIRES "
            "APPROVAL] repo_id MUST be a real repository NAME from "
            'github_list_repos (e.g. "payment-service"). Do NOT invent ids like '
            '"repo-1". files: a list of {"path", "content"} objects. Each '
            '"content" MUST be the COMPLETE file text, never a diff.'
        ),
        "input_schema": _obj(
            {
                "repo_id": _STR,
                "branch": _STR,
                "message": _STR,
                "files": {
                    "type": "array",
                    "items": _obj(
                        {"path": _STR, "content": _STR}, required=["path"]
                    ),
                },
            },
            required=["repo_id", "branch", "message", "files"],
        ),
        "method": "POST",
        "path_template": "/repos/{repo_id}/commits",
        "arg_mapping": {
            "repo_id": {"in": "path", "name": "repo_id"},
            "branch": {"in": "body", "name": "branch"},
            "message": {"in": "body", "name": "message"},
            "files": {"in": "body", "name": "files"},
        },
    },
    {
        "name": "github_open_pull_request",
        "service": "github",
        "description": (
            "Open a pull request. [WRITE ACTION - REQUIRES APPROVAL] repo_id "
            'MUST be a real repository NAME from github_list_repos (e.g. '
            '"payment-service"). Do NOT invent ids like "repo-1". head: the '
            'source branch; base: the target branch (default "main"). title '
            "defaults to the head branch name if omitted."
        ),
        "input_schema": _obj(
            {"repo_id": _STR, "head": _STR, "base": _STR, "title": _STR, "body": _STR},
            required=["repo_id", "head"],
        ),
        "method": "POST",
        "path_template": "/repos/{repo_id}/pulls",
        "arg_mapping": {
            "repo_id": {"in": "path", "name": "repo_id"},
            "head": {"in": "body", "name": "head"},
            "base": {"in": "body", "name": "base"},
            "title": {"in": "body", "name": "title"},
            "body": {"in": "body", "name": "body"},
        },
    },
    # ----- Confluence (3 read) -----
    {
        "name": "confluence_search",
        "service": "confluence",
        "description": (
            "Search Confluence documentation by keyword. Optionally filter by "
            "space_id (ENG, SEC, PROD, API). Use this to find architecture docs, "
            "security guidelines, API specs, requirements, and retrospectives."
        ),
        "input_schema": _obj({"query": _STR, "space_id": _STR}, required=["query"]),
        "method": "GET",
        "path_template": "/search",
        # NOTE: the search route reads query ``q`` (the tool arg is ``query``).
        "arg_mapping": {
            "query": {"in": "query", "name": "q"},
            "space_id": {"in": "query", "name": "space_id"},
        },
    },
    {
        "name": "confluence_get_page",
        "service": "confluence",
        "description": (
            "Get the full content of a Confluence page by its ID (e.g., ENG-001, "
            "SEC-001, PROD-001, API-001). Use this after searching to read the "
            "full document content."
        ),
        "input_schema": _obj({"page_id": _STR}, required=["page_id"]),
        "method": "GET",
        "path_template": "/pages/{page_id}",
        "arg_mapping": {"page_id": {"in": "path", "name": "page_id"}},
    },
    {
        "name": "confluence_list_spaces",
        "service": "confluence",
        "description": "List all available Confluence spaces.",
        "input_schema": _obj({}),
        "method": "GET",
        "path_template": "/spaces",
        "arg_mapping": {},
    },
    # ----- ServiceNow (6: 5 read + 1 write) -----
    {
        "name": "servicenow_list_deployments",
        "service": "servicenow",
        "description": (
            "List deployments tracked in ServiceNow. service: payment-service, "
            "cart-service, auth-service, product-service, or order-service. "
            "environment: staging | production. status: success | failed | "
            "rolled_back | in_progress."
        ),
        "input_schema": _obj({"service": _STR, "environment": _STR, "status": _STR}),
        "method": "GET",
        "path_template": "/deployments",
        "arg_mapping": {
            "service": {"in": "query", "name": "service"},
            "environment": {"in": "query", "name": "environment"},
            "status": {"in": "query", "name": "status"},
        },
    },
    {
        "name": "servicenow_deployment_status_by_project",
        "service": "servicenow",
        "description": (
            "Summarize deployment statuses grouped by every ServiceNow "
            "project/service."
        ),
        "input_schema": _obj({}),
        "composite": "servicenow.composites.deployment_status",
    },
    {
        "name": "servicenow_list_incidents",
        "service": "servicenow",
        "description": (
            "List incidents tracked in ServiceNow. By default (no filters) "
            "returns ALL incidents regardless of status. Only pass a status "
            'filter if the user explicitly asks for a specific status. Do NOT '
            'assume "open". Incidents actively worked on include BOTH open AND '
            "investigating; resolved incidents are closed. severity: P1 "
            "(critical) | P2 (high) | P3 (medium) | P4 (low). status: open | "
            "investigating | resolved (omit to get all). service: filter by "
            "affected service (e.g. auth-service)."
        ),
        "input_schema": _obj({"severity": _STR, "status": _STR, "service": _STR}),
        "method": "GET",
        "path_template": "/incidents",
        # The route also accepts an ``assignee`` filter, but the current @tool
        # does NOT expose it, so neither does this schema (stay DIRECT-equivalent).
        "arg_mapping": {
            "severity": {"in": "query", "name": "severity"},
            "status": {"in": "query", "name": "status"},
            "service": {"in": "query", "name": "service"},
        },
    },
    {
        "name": "servicenow_get_incident",
        "service": "servicenow",
        "description": "Get full details of a specific incident by ID (e.g. INC-2001).",
        "input_schema": _obj({"incident_id": _STR}, required=["incident_id"]),
        "method": "GET",
        "path_template": "/incidents/{incident_id}",
        "arg_mapping": {"incident_id": {"in": "path", "name": "incident_id"}},
    },
    {
        "name": "servicenow_get_stats",
        "service": "servicenow",
        "description": (
            "Get a portfolio-level deployment and incident health summary (good "
            "for executives)."
        ),
        "input_schema": _obj({}),
        "method": "GET",
        "path_template": "/stats",
        "arg_mapping": {},
    },
    {
        "name": "servicenow_create_incident",
        "service": "servicenow",
        "description": (
            "Open a new incident in ServiceNow. [WRITE ACTION - REQUIRES "
            "APPROVAL] affected_service: payment-service, cart-service, "
            "auth-service, product-service, or order-service. severity: P1 "
            "(critical) | P2 (high) | P3 (medium) | P4 (low), default P3. "
            "description: optional detail. assignee: optional developer ID. "
            "linked_deployment: optional deployment ID this incident relates to."
        ),
        "input_schema": _obj(
            {
                "title": _STR,
                "affected_service": _STR,
                "severity": _STR,
                "description": _STR,
                "assignee": _STR,
                "linked_deployment": _STR,
            },
            required=["title", "affected_service"],
        ),
        "method": "POST",
        "path_template": "/incidents",
        "arg_mapping": {
            "title": {"in": "body", "name": "title"},
            "affected_service": {"in": "body", "name": "affected_service"},
            "severity": {"in": "body", "name": "severity"},
            "description": {"in": "body", "name": "description"},
            "assignee": {"in": "body", "name": "assignee"},
            "linked_deployment": {"in": "body", "name": "linked_deployment"},
        },
    },
]

# name -> descriptor, for O(1) adapter lookup.
BY_NAME: Dict[str, Dict[str, Any]] = {t["name"]: t for t in TOOLS}

# The six write tools (bare names), mirroring agent/approval.py::WRITE_TOOL_NAMES.
WRITE_TOOL_NAMES = {
    "jira_create_story",
    "jira_update_story",
    "github_create_branch",
    "github_commit_files",
    "github_open_pull_request",
    "servicenow_create_incident",
}


def tools_for_service(service: str) -> List[Dict[str, Any]]:
    """Return the descriptors belonging to one Gateway target (``mock-<svc>``)."""
    return [t for t in TOOLS if t["service"] == service]
