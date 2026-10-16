"""Gateway-adapter tests: a Gateway Lambda-target call maps to the Router.

Each test invokes a service ``lambda_handler`` with a flat args ``event`` plus a
fake ``context`` carrying ``client_context.custom['bedrockAgentCoreToolName']``
(the ``<target>___<tool>`` form). Assertions cover a representative read, a write,
an error (404/409), and the three composites — checking the UNWRAPPED JSON
payload (not a formatted string) and that the error object is byte-identical to
``agent/tools/http.py::make_request`` for the same raw body.
"""

from __future__ import annotations

import importlib
import json

import pytest

from tests.conftest import body_of, make_event

JIRA_TOKEN = "mock-jira-token-12345"
GITHUB_TOKEN = "mock-github-token-12345"
SNOW_TOKEN = "mock-servicenow-token-12345"
CONF_TOKEN = "mock-confluence-token-12345"


class _FakeClientContext:
    def __init__(self, tool_name):
        self.custom = {"bedrockAgentCoreToolName": tool_name}


class _FakeContext:
    def __init__(self, tool_name):
        self.client_context = _FakeClientContext(tool_name)


def _reload(module_name, env, monkeypatch, table):
    monkeypatch.setenv("TABLE_NAME", table)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GITHUB_MODE", raising=False)
    mod = importlib.import_module(module_name)
    importlib.reload(mod)
    mod._store = None
    mod._router = None
    return mod


@pytest.fixture
def jira(dynamo_table, monkeypatch):
    return _reload("jira.handler", {"MOCK_JIRA_TOKEN": JIRA_TOKEN}, monkeypatch, dynamo_table)


@pytest.fixture
def github(dynamo_table, monkeypatch):
    return _reload("github.handler", {"MOCK_GITHUB_TOKEN": GITHUB_TOKEN}, monkeypatch, dynamo_table)


@pytest.fixture
def servicenow(dynamo_table, monkeypatch):
    return _reload(
        "servicenow.handler", {"MOCK_SERVICENOW_TOKEN": SNOW_TOKEN}, monkeypatch, dynamo_table
    )


@pytest.fixture
def confluence(dynamo_table, monkeypatch):
    return _reload(
        "confluence.handler", {"MOCK_CONFLUENCE_TOKEN": CONF_TOKEN}, monkeypatch, dynamo_table
    )


def _gw(handler, tool_name, args):
    """Invoke a handler as a Gateway target: flat args event + tool-name context."""
    return handler.lambda_handler(dict(args), _FakeContext(tool_name))


# --------------------------------------------------------------------------- #
# Read + envelope unwrap
# --------------------------------------------------------------------------- #

def test_read_returns_unwrapped_json(jira):
    out = _gw(jira, "mock-jira___jira_list_projects", {})
    # The adapter returns the route's JSON BODY directly (not {statusCode, body}).
    assert "projects" in out
    assert isinstance(out["projects"], list) and out["projects"]

    # Equivalent to what DIRECT make_request would parse from the HTTP body.
    http_resp = jira.lambda_handler(make_event("GET", "/projects", token=JIRA_TOKEN), None)
    assert out == body_of(http_resp)


def test_read_with_path_param(jira):
    out = _gw(jira, "mock-jira___jira_get_sprint_info", {"project_id": "PAY"})
    assert "sprints" in out


def test_github_get_commits_uses_author_query_not_author_id(github):
    # The quirk: commits route reads query ``author``. Unknown author -> empty.
    out = _gw(github, "mock-github___github_get_commits", {"repo_id": "repo-1", "author": "nobody-x"})
    assert out["commits"] == []
    present = _gw(github, "mock-github___github_get_commits", {"repo_id": "repo-1"})
    assert present["total"] >= 1


# --------------------------------------------------------------------------- #
# Write + branch_name -> name quirk
# --------------------------------------------------------------------------- #

def test_write_create_branch_maps_branch_name_to_name(github):
    out = _gw(
        github,
        "mock-github___github_create_branch",
        {"repo_id": "repo-1", "branch_name": "feature/gw", "from_branch": "main"},
    )
    assert out["name"] == "feature/gw"
    assert out["protected"] is False


def test_write_create_incident(servicenow):
    out = _gw(
        servicenow,
        "mock-servicenow___servicenow_create_incident",
        {"title": "GW outage", "affected_service": "auth-service", "severity": "P1"},
    )
    assert out["title"] == "GW outage"
    assert out["severity"] == "P1"
    assert out["id"].startswith("INC-")


# --------------------------------------------------------------------------- #
# Errors: byte-identical to make_request's error string
# --------------------------------------------------------------------------- #

def _make_request_error(status, raw_body):
    """Reproduce agent/tools/http.py::make_request's non-2xx error string."""
    return {"error": f"Request failed with status {status}: {raw_body}"}


def test_error_404_matches_make_request(github):
    out = _gw(github, "mock-github___github_get_repo_stats", {"repo_id": "does-not-exist"})
    expected_body = json.dumps({"detail": "Repository not found"})
    assert out == _make_request_error(404, expected_body)


def test_error_409_already_exists_matches_make_request(github):
    out = _gw(
        github,
        "mock-github___github_create_branch",
        {"repo_id": "repo-1", "branch_name": "main"},
    )
    expected_body = json.dumps({"detail": "Branch already exists"})
    assert out == _make_request_error(409, expected_body)


def test_unknown_tool_returns_error(jira):
    out = _gw(jira, "mock-jira___jira_not_a_tool", {})
    assert out == {"error": "Unknown tool: jira_not_a_tool"}


# --------------------------------------------------------------------------- #
# Composites
# --------------------------------------------------------------------------- #

def test_composite_stories_by_assignee(jira):
    out = _gw(jira, "mock-jira___jira_get_stories_by_assignee", {"assignee": "dev-6"})
    assert "stories" in out
    assert out["assignee"] == "dev-6"
    # Every returned story is actually assigned to dev-6.
    assert all(s["assignee"] == "dev-6" for s in out["stories"])


def test_composite_search_stories_keyword_filter(jira):
    out = _gw(jira, "mock-jira___jira_search_stories", {"query": "checkout"})
    assert "stories" in out
    for s in out["stories"]:
        text = (s["title"] + " " + s.get("description", "")).lower()
        assert "checkout" in text


def test_composite_servicenow_deployment_status(servicenow):
    out = _gw(servicenow, "mock-servicenow___servicenow_deployment_status_by_project", {})
    assert "projects" in out
    assert out["total_deployments"] >= 1
    for p in out["projects"]:
        assert "status_counts" in p and "latest" in p


# --------------------------------------------------------------------------- #
# The direct (non-Gateway) HTTP path still works (context has no custom).
# --------------------------------------------------------------------------- #

def test_direct_http_path_unaffected(jira):
    resp = jira.lambda_handler(make_event("GET", "/projects", token=JIRA_TOKEN), None)
    assert resp["statusCode"] == 200
    assert "projects" in body_of(resp)
