"""Offline unit tests for the read-only tool HTTP wrappers.

Two layers of checking, all with NO network:

1. HTTP layer (httpx.MockTransport): asserts the shared ``make_request`` helper
   builds the right URL, sends the query params, and sets the ``X-API-Token``
   header, plus the exact error string on a non-2xx response.
2. Tool layer (monkeypatched ``make_request``): asserts a representative tool per
   service hits the right endpoint/params and formats output byte-for-byte like
   mahalo-dock, plus the Jira assignee name->dev-id resolution logic.
"""

from __future__ import annotations

import httpx
import pytest

import agent.tools.http as http_mod
from agent.tools import confluence_tools, github_tools, jira_tools, servicenow_tools


# --------------------------------------------------------------------------- #
# 1. HTTP layer — real make_request against an httpx.MockTransport
# --------------------------------------------------------------------------- #

def _patch_mock_transport(monkeypatch, handler):
    """Patch http_mod.httpx.Client so make_request routes through a MockTransport.

    The real httpx.Client is captured first so the replacement does not recurse
    into the patched attribute.
    """
    real_client = httpx.Client

    def _factory(timeout=None):
        return real_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(http_mod.httpx, "Client", _factory)


def test_make_request_builds_url_params_and_header(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["token"] = request.headers.get("X-API-Token")
        return httpx.Response(200, json={"ok": True})

    # Route httpx.Client() through the mock transport.
    _patch_mock_transport(monkeypatch, handler)

    out = http_mod.make_request(
        "http://localhost:5001",
        "mock-jira-token-12345",
        endpoint="/projects/PAY/stories",
        params={"assignee": "dev-6", "status": "todo"},
    )

    assert out == {"ok": True}
    assert seen["path"] == "/projects/PAY/stories"
    assert seen["params"] == {"assignee": "dev-6", "status": "todo"}
    assert seen["token"] == "mock-jira-token-12345"
    assert seen["url"].startswith("http://localhost:5001/projects/PAY/stories")


def test_make_request_error_string_on_non_2xx(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    _patch_mock_transport(monkeypatch, handler)

    out = http_mod.make_request("http://localhost:5003", "tok", endpoint="/repos/nope/stats")
    assert out == {"error": "Request failed with status 404: Not Found"}


# --------------------------------------------------------------------------- #
# Helper: a recording fake for the shared make_request seam
# --------------------------------------------------------------------------- #

class _FakeRequest:
    """Records (endpoint, params) calls and returns scripted JSON by endpoint."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict | None]] = []

    def __call__(self, base_url, token, endpoint="", params=None, method="GET", body=None, timeout=None):
        self.calls.append((endpoint, params))
        value = self.routes.get(endpoint)
        if callable(value):
            return value(params)
        return value


# --------------------------------------------------------------------------- #
# 2a. Jira — representative tool + output formatting
# --------------------------------------------------------------------------- #

def test_jira_list_projects_endpoint_and_formatting(monkeypatch):
    fake = _FakeRequest({
        "/projects": {"projects": [
            {"id": "PAY", "name": "Payments", "description": "Payment platform"},
        ]},
    })
    monkeypatch.setattr(jira_tools, "make_request", fake)

    out = jira_tools.jira_list_projects()

    assert ("/projects", None) in fake.calls
    assert out == "Available projects:\n- **PAY**: Payments - Payment platform\n"


def test_jira_get_stories_by_assignee_resolves_and_formats(monkeypatch):
    developers = {"developers": [
        {"id": "dev-6", "name": "Lava Dev", "email": "lava@ecommerce.io"},
    ]}
    stories = {"stories": [
        {"id": "PAY-109", "title": "Crypto payments", "status": "in_progress",
         "story_points": 5, "assignee": "dev-6"},
    ]}
    fake = _FakeRequest({
        "/developers": developers,
        "/projects/PAY/stories": stories,
    })
    monkeypatch.setattr(jira_tools, "make_request", fake)

    out = jira_tools.jira_get_stories_by_assignee("dev-6", project_id="PAY")

    # dev-6 passthrough -> assignee param, correct endpoint
    assert ("/projects/PAY/stories", {"assignee": "dev-6"}) in fake.calls
    assert out == (
        "Found 1 stories assigned to Lava Dev (dev-6):\n"
        "- [PAY-109] Crypto payments | Status: in_progress | Points: 5 | Assignee: Lava Dev\n"
    )


# --------------------------------------------------------------------------- #
# 2b. Jira assignee resolution logic (_resolve_assignee)
# --------------------------------------------------------------------------- #

@pytest.fixture
def _devs(monkeypatch):
    developers = {"developers": [
        {"id": "dev-3", "name": "Raj Patel", "email": "raj@ecommerce.io"},
        {"id": "dev-6", "name": "Lava Dev", "email": "lava@ecommerce.io"},
        {"id": "dev-4", "name": "Rachel Green", "email": "rachel@ecommerce.io"},
    ]}
    monkeypatch.setattr(jira_tools, "make_request", _FakeRequest({"/developers": developers}))


def test_resolve_assignee_dev_prefix_passthrough(_devs):
    assert jira_tools._resolve_assignee("dev-6") == "dev-6"


def test_resolve_assignee_full_name_and_email(_devs):
    assert jira_tools._resolve_assignee("Raj Patel") == "dev-3"
    assert jira_tools._resolve_assignee("lava@ecommerce.io") == "dev-6"


def test_resolve_assignee_first_name_single_match(_devs):
    assert jira_tools._resolve_assignee("raj") == "dev-3"
    # email local-part match
    assert jira_tools._resolve_assignee("lava") == "dev-6"


def test_resolve_assignee_none_when_unknown_or_ambiguous(_devs):
    assert jira_tools._resolve_assignee("nobody") is None
    assert jira_tools._resolve_assignee("") is None
    # "ra" partially matches Raj and Rachel -> ambiguous -> None
    assert jira_tools._resolve_assignee("ra") is None


def test_jira_stories_by_assignee_unresolved_message(monkeypatch):
    developers = {"developers": [
        {"id": "dev-3", "name": "Raj Patel", "email": "raj@ecommerce.io"},
    ]}
    monkeypatch.setattr(jira_tools, "make_request", _FakeRequest({"/developers": developers}))
    out = jira_tools.jira_get_stories_by_assignee("nobody")
    assert out.startswith("Could not resolve 'nobody' to a known developer.")
    assert "Raj Patel (dev-3)" in out


# --------------------------------------------------------------------------- #
# 2c. GitHub — representative tool + error path
# --------------------------------------------------------------------------- #

def test_github_list_repos_formatting(monkeypatch):
    fake = _FakeRequest({
        "/repos": {"repos": [
            {"name": "payment-service", "language": "Python",
             "description": "Payments API", "last_push": "2024-01-02", "open_issues": 3},
        ]},
    })
    monkeypatch.setattr(github_tools, "make_request", fake)

    out = github_tools.github_list_repos()

    assert ("/repos", None) in fake.calls
    assert out == (
        "Available repositories:\n"
        "- **payment-service** (Python) - Payments API\n"
        "  Last push: 2024-01-02 | Open issues: 3\n"
    )


def test_github_repo_stats_error_path(monkeypatch):
    fake = _FakeRequest({
        "/repos/nope/stats": {"error": "Request failed with status 404: Repository not found"},
    })
    monkeypatch.setattr(github_tools, "make_request", fake)

    out = github_tools.github_get_repo_stats("nope")
    assert out == "Error: Request failed with status 404: Repository not found"


# --------------------------------------------------------------------------- #
# 2d. Confluence — representative tool
# --------------------------------------------------------------------------- #

def test_confluence_search_params_and_formatting(monkeypatch):
    fake = _FakeRequest({
        "/search": {"results": [
            {"title": "Payments Arch", "space_id": "ENG", "author": "Raj",
             "last_updated": "2024-01-01", "excerpt": "x" * 200},
        ]},
    })
    monkeypatch.setattr(confluence_tools, "make_request", fake)

    out = confluence_tools.confluence_search("payments", space_id="ENG")

    assert ("/search", {"q": "payments", "space_id": "ENG"}) in fake.calls
    assert out.startswith("Found 1 documents matching 'payments':\n")
    assert "📄 **Payments Arch** (Space: ENG)" in out
    assert ("x" * 150 + "...") in out  # excerpt truncated to 150 chars


# --------------------------------------------------------------------------- #
# 2e. ServiceNow — representative tool + default-all incidents (no status param)
# --------------------------------------------------------------------------- #

def test_servicenow_list_incidents_default_no_status_filter(monkeypatch):
    fake = _FakeRequest({
        "/incidents": {"incidents": [
            {"id": "INC-2001", "severity": "P1", "title": "Auth outage",
             "status": "investigating", "affected_service": "auth-service",
             "assignee": "dev-6", "opened_at": "2024-01-01"},
        ]},
    })
    monkeypatch.setattr(servicenow_tools, "make_request", fake)

    out = servicenow_tools.servicenow_list_incidents()

    # No status filter passed by default
    assert ("/incidents", {}) in fake.calls
    assert out.startswith("Incidents (1 found):\n")
    assert "🔥 INC-2001 [P1] Auth outage" in out
    assert "Status: investigating | Service: auth-service | Assignee: dev-6" in out
