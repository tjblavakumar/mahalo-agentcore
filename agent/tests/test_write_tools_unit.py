"""Offline unit tests for the Task 2 WRITE-tool bodies.

Same style as ``test_tools_unit.py``: monkeypatch the shared ``make_request``
seam per write module with a recording fake, then assert the endpoint, verb
(``method``), request body, and byte-for-byte success strings. All offline — no
network, no AWS. FEAT-002 will extend this file with hook/driver tests.
"""

from __future__ import annotations

import httpx
import pytest

from agent.tools import github_write_tools, jira_tools, jira_write_tools, servicenow_write_tools
from agent.tools.github_write_tools import _normalize_files_arg


# --------------------------------------------------------------------------- #
# Recording fake for the shared make_request seam
# --------------------------------------------------------------------------- #

class _FakeRequest:
    """Records (endpoint, method, body, params) calls; returns scripted JSON by endpoint."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[dict] = []

    def __call__(self, base_url, token, endpoint="", params=None, method="GET", body=None, timeout=None):
        self.calls.append(
            {"endpoint": endpoint, "method": method, "body": body, "params": params}
        )
        value = self.routes.get(endpoint)
        if callable(value):
            return value(method, body)
        return value


# --------------------------------------------------------------------------- #
# Jira: jira_create_story
# --------------------------------------------------------------------------- #

def test_jira_create_story_posts_and_formats(monkeypatch):
    fake = _FakeRequest({"/stories": {"id": "PAY-200", "title": "Crypto payments"}})
    monkeypatch.setattr(jira_write_tools, "make_request", fake)

    out = jira_write_tools.jira_create_story(
        "PAY", "Crypto payments", "Add crypto support", priority="high", story_points=5, assignee="dev-6"
    )

    call = fake.calls[0]
    assert call["endpoint"] == "/stories"
    assert call["method"] == "POST"
    assert call["body"] == {
        "project_id": "PAY",
        "title": "Crypto payments",
        "description": "Add crypto support",
        "priority": "high",
        "story_points": 5,
        "assignee": "dev-6",
    }
    assert out == "✅ Story created successfully: **PAY-200** - Crypto payments"


# --------------------------------------------------------------------------- #
# Jira: jira_update_story — happy path + the three guard branches
# --------------------------------------------------------------------------- #

def test_jira_update_story_pre_get_then_put_only_provided_changes(monkeypatch):
    fake = _FakeRequest({
        "/stories/PAY-105": lambda method, body: (
            {"id": "PAY-105", "title": "Checkout", "status": "todo"}
            if method == "GET"
            else {"id": "PAY-105", "title": "Checkout"}
        ),
    })
    monkeypatch.setattr(jira_write_tools, "make_request", fake)

    out = jira_write_tools.jira_update_story("PAY-105", status="in_progress", priority="high")

    # First a GET to confirm existence, then a PUT with only the provided fields.
    assert fake.calls[0]["endpoint"] == "/stories/PAY-105"
    assert fake.calls[0]["method"] == "GET"
    put = fake.calls[1]
    assert put["endpoint"] == "/stories/PAY-105"
    assert put["method"] == "PUT"
    assert put["body"] == {"status": "in_progress", "priority": "high"}
    assert out == "✅ Story updated successfully: **PAY-105** - Checkout"


def test_jira_update_story_not_found(monkeypatch):
    fake = _FakeRequest({
        "/stories/PAY-999": {"error": "Request failed with status 404: Story not found"},
    })
    monkeypatch.setattr(jira_write_tools, "make_request", fake)

    out = jira_write_tools.jira_update_story("PAY-999", status="done")

    assert out == "Story 'PAY-999' was not found, so it cannot be updated."
    # No PUT should have been issued.
    assert all(c["method"] != "PUT" for c in fake.calls)


def test_jira_update_story_unresolved_assignee(monkeypatch):
    fake = _FakeRequest({
        "/stories/PAY-105": {"id": "PAY-105", "title": "Checkout"},
        "/developers": {"developers": [{"id": "dev-3", "name": "Raj Patel", "email": "raj@ecommerce.io"}]},
    })
    monkeypatch.setattr(jira_write_tools, "make_request", fake)
    # _resolve_assignee/_fetch_developers live in jira_tools and use ITS make_request.
    monkeypatch.setattr(jira_tools, "make_request", fake)

    out = jira_write_tools.jira_update_story("PAY-105", assignee="nobody")

    assert out.startswith("Could not resolve assignee 'nobody'.")
    assert "Raj Patel (dev-3)" in out
    assert all(c["method"] != "PUT" for c in fake.calls)


def test_jira_update_story_no_changes(monkeypatch):
    fake = _FakeRequest({"/stories/PAY-105": {"id": "PAY-105", "title": "Checkout"}})
    monkeypatch.setattr(jira_write_tools, "make_request", fake)

    out = jira_write_tools.jira_update_story("PAY-105")

    assert out == "No changes specified for PAY-105. Provide at least one field to update."
    assert all(c["method"] != "PUT" for c in fake.calls)


# --------------------------------------------------------------------------- #
# GitHub: github_create_branch — success + already-exists -> SUCCESS
# --------------------------------------------------------------------------- #

def test_github_create_branch_posts_and_formats(monkeypatch):
    fake = _FakeRequest({
        "/repos/payment-service/branches": {"name": "feature/PAY-109"},
    })
    monkeypatch.setattr(github_write_tools, "make_request", fake)

    out = github_write_tools.github_create_branch("payment-service", "feature/PAY-109")

    call = fake.calls[0]
    assert call["endpoint"] == "/repos/payment-service/branches"
    assert call["method"] == "POST"
    assert call["body"] == {"name": "feature/PAY-109", "from_branch": "main"}
    assert out == "✅ Branch created successfully: **feature/PAY-109**"


def test_github_create_branch_already_exists_is_success(monkeypatch):
    fake = _FakeRequest({
        "/repos/payment-service/branches": {
            "error": "Request failed with status 409: Branch already exists"
        },
    })
    monkeypatch.setattr(github_write_tools, "make_request", fake)

    out = github_write_tools.github_create_branch("payment-service", "feature/PAY-109")

    assert out == (
        "✅ Branch **feature/PAY-109** already exists — reusing it. "
        'Reply "commit the code" to proceed.'
    )


# --------------------------------------------------------------------------- #
# GitHub: github_commit_files + _normalize_files_arg
# --------------------------------------------------------------------------- #

def test_github_commit_files_posts_and_formats(monkeypatch):
    fake = _FakeRequest({
        "/repos/payment-service/commits": {"url": "http://x/commit/abc"},
    })
    monkeypatch.setattr(github_write_tools, "make_request", fake)

    files = [{"path": "a.py", "content": "print(1)"}, {"path": "b.py", "content": "print(2)"}]
    out = github_write_tools.github_commit_files("payment-service", "feature/PAY-109", "msg", files)

    call = fake.calls[0]
    assert call["endpoint"] == "/repos/payment-service/commits"
    assert call["method"] == "POST"
    assert call["body"] == {
        "branch": "feature/PAY-109",
        "message": "msg",
        "files": [{"path": "a.py", "content": "print(1)"}, {"path": "b.py", "content": "print(2)"}],
    }
    assert out == "✅ Committed 2 files to **feature/PAY-109**\n🔗 http://x/commit/abc"


def test_normalize_files_arg_json_string():
    out = _normalize_files_arg('[{"path": "a.py", "content": "x"}]')
    assert out == [{"path": "a.py", "content": "x"}]


def test_normalize_files_arg_single_dict():
    out = _normalize_files_arg({"path": "a.py", "content": "x"})
    assert out == [{"path": "a.py", "content": "x"}]


def test_normalize_files_arg_list():
    out = _normalize_files_arg([{"path": "a.py", "content": "x"}, {"path": "b.py", "content": "y"}])
    assert out == [{"path": "a.py", "content": "x"}, {"path": "b.py", "content": "y"}]


def test_normalize_files_arg_drops_missing_path():
    out = _normalize_files_arg([{"content": "x"}, {"path": "b.py", "content": "y"}])
    assert out == [{"path": "b.py", "content": "y"}]


def test_normalize_files_arg_coerces_content_to_str():
    out = _normalize_files_arg([{"path": "a.py", "content": 123}, {"path": "b.py"}])
    assert out == [{"path": "a.py", "content": "123"}, {"path": "b.py", "content": ""}]


# --------------------------------------------------------------------------- #
# GitHub: github_open_pull_request — title defaults to head
# --------------------------------------------------------------------------- #

def test_github_open_pull_request_title_defaults_to_head(monkeypatch):
    fake = _FakeRequest({
        "/repos/payment-service/pulls": {"number": 42, "title": "feature/PAY-109", "url": "http://x/pr/42"},
    })
    monkeypatch.setattr(github_write_tools, "make_request", fake)

    out = github_write_tools.github_open_pull_request("payment-service", "feature/PAY-109")

    call = fake.calls[0]
    assert call["endpoint"] == "/repos/payment-service/pulls"
    assert call["method"] == "POST"
    assert call["body"] == {
        "head": "feature/PAY-109",
        "base": "main",
        "title": "feature/PAY-109",
        "body": "",
    }
    assert out == "✅ Pull request opened: **#42** feature/PAY-109\n🔗 http://x/pr/42"


# --------------------------------------------------------------------------- #
# ServiceNow: servicenow_create_incident
# --------------------------------------------------------------------------- #

def test_servicenow_create_incident_posts_and_formats(monkeypatch):
    fake = _FakeRequest({
        "/incidents": {"id": "INC-3001", "title": "Auth outage", "severity": "P1"},
    })
    monkeypatch.setattr(servicenow_write_tools, "make_request", fake)

    out = servicenow_write_tools.servicenow_create_incident(
        "Auth outage", "auth-service", severity="P1", description="users locked out"
    )

    call = fake.calls[0]
    assert call["endpoint"] == "/incidents"
    assert call["method"] == "POST"
    assert call["body"] == {
        "title": "Auth outage",
        "affected_service": "auth-service",
        "severity": "P1",
        "description": "users locked out",
        "assignee": None,
        "linked_deployment": None,
    }
    assert out == "✅ Incident opened successfully: **INC-3001** - Auth outage (P1)"


# --------------------------------------------------------------------------- #
# Transport-error wrap: httpx.HTTPError -> "❌ Failed to ..." string, no raise
# --------------------------------------------------------------------------- #

def _raise_http_error(*args, **kwargs):
    raise httpx.ConnectError("tunnel down")


def test_jira_create_story_transport_error_returns_string(monkeypatch):
    monkeypatch.setattr(jira_write_tools, "make_request", _raise_http_error)
    out = jira_write_tools.jira_create_story("PAY", "t", "d")
    assert out == "❌ Failed to create story: tunnel down"


def test_github_create_branch_transport_error_returns_string(monkeypatch):
    monkeypatch.setattr(github_write_tools, "make_request", _raise_http_error)
    out = github_write_tools.github_create_branch("payment-service", "feature/x")
    assert out == "❌ Failed to create branch: tunnel down"


def test_github_commit_files_transport_error_returns_string(monkeypatch):
    monkeypatch.setattr(github_write_tools, "make_request", _raise_http_error)
    out = github_write_tools.github_commit_files("payment-service", "b", "m", [])
    assert out == "❌ Failed to commit files: tunnel down"


def test_github_open_pull_request_transport_error_returns_string(monkeypatch):
    monkeypatch.setattr(github_write_tools, "make_request", _raise_http_error)
    out = github_write_tools.github_open_pull_request("payment-service", "head")
    assert out == "❌ Failed to open pull request: tunnel down"


def test_servicenow_create_incident_transport_error_returns_string(monkeypatch):
    monkeypatch.setattr(servicenow_write_tools, "make_request", _raise_http_error)
    out = servicenow_write_tools.servicenow_create_incident("t", "auth-service")
    assert out == "❌ Failed to open incident: tunnel down"


def test_jira_update_story_transport_error_returns_string(monkeypatch):
    # Pre-GET succeeds (existence), the PUT raises a transport error.
    def seam(base_url, token, endpoint="", params=None, method="GET", body=None, timeout=None):
        if method == "GET":
            return {"id": "PAY-105", "title": "Checkout"}
        raise httpx.ConnectError("tunnel down")

    monkeypatch.setattr(jira_write_tools, "make_request", seam)
    out = jira_write_tools.jira_update_story("PAY-105", status="done")
    assert out == "❌ Failed to update story: tunnel down"
