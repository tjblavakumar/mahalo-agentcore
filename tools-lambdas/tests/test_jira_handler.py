"""Handler tests for the Jira mock Lambda."""

import importlib

import pytest

from tests.conftest import body_of, make_event

TOKEN = "mock-jira-token-12345"


@pytest.fixture
def handler(dynamo_table, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", dynamo_table)
    monkeypatch.setenv("MOCK_JIRA_TOKEN", TOKEN)
    import jira.handler as h

    importlib.reload(h)
    # Reset module-level singletons so the fresh table/env are picked up.
    h._store = None
    h._router = None
    return h


def invoke(handler, method, path, **kwargs):
    return handler.lambda_handler(make_event(method, path, **kwargs), None)


def test_health_no_token(handler):
    resp = invoke(handler, "GET", "/health")
    assert resp["statusCode"] == 200
    assert body_of(resp)["service"] == "mock-jira"


def test_auth_missing_token_401(handler):
    resp = invoke(handler, "GET", "/projects")
    assert resp["statusCode"] == 401
    assert body_of(resp)["detail"] == "Invalid API token"


def test_auth_wrong_token_401(handler):
    resp = invoke(handler, "GET", "/projects", token="wrong")
    assert resp["statusCode"] == 401


def test_list_projects(handler):
    resp = invoke(handler, "GET", "/projects", token=TOKEN)
    assert resp["statusCode"] == 200
    ids = {p["id"] for p in body_of(resp)["projects"]}
    assert {"PAY", "CART", "AUTH", "PROD", "ORD"} == ids


def test_list_developers(handler):
    resp = invoke(handler, "GET", "/developers", token=TOKEN)
    assert resp["statusCode"] == 200
    assert len(body_of(resp)["developers"]) == 6


def test_get_project_404(handler):
    resp = invoke(handler, "GET", "/projects/NOPE", token=TOKEN)
    assert resp["statusCode"] == 404
    assert body_of(resp)["detail"] == "Project not found"


def test_get_story_enriches_assignee(handler):
    resp = invoke(handler, "GET", "/stories/PAY-105", token=TOKEN)
    assert resp["statusCode"] == 200
    story = body_of(resp)
    assert story["assignee"] == "dev-1"
    assert story["assignee_details"]["name"] == "Marcus Chen"


def test_get_story_404(handler):
    resp = invoke(handler, "GET", "/stories/PAY-9999", token=TOKEN)
    assert resp["statusCode"] == 404
    assert body_of(resp)["detail"] == "Story not found"


def test_board_active_sprint(handler):
    resp = invoke(handler, "GET", "/projects/PAY/board", token=TOKEN)
    assert resp["statusCode"] == 200
    board = body_of(resp)
    assert board["sprint"]["id"] == "PAY-S2"
    # PAY-S2 stories: 105 in_progress, 106 in_progress, 107 todo, 108 in_review
    assert {s["id"] for s in board["columns"]["in_progress"]} == {"PAY-105", "PAY-106"}
    assert {s["id"] for s in board["columns"]["todo"]} == {"PAY-107"}
    assert {s["id"] for s in board["columns"]["in_review"]} == {"PAY-108"}


def test_sprints_active_velocity(handler):
    resp = invoke(handler, "GET", "/sprints/PAY", token=TOKEN)
    assert resp["statusCode"] == 200
    sprints = body_of(resp)["sprints"]
    active = next(s for s in sprints if s["status"] == "active")
    # PAY-S2 has no done stories -> completed_points 0; total = 8+5+13+8 = 34
    assert active["completed_points"] == 0
    assert active["total_points"] == 34


def test_create_story_read_after_write(handler):
    resp = invoke(
        handler,
        "POST",
        "/stories",
        token=TOKEN,
        body={"project_id": "PAY", "title": "New feature", "story_points": 3},
    )
    assert resp["statusCode"] == 201
    created = body_of(resp)
    assert created["id"] == "PAY-111"
    assert created["status"] == "todo"
    assert created["acceptance_criteria"] == []
    assert created["comments"] == []

    read = invoke(handler, "GET", "/stories/PAY-111", token=TOKEN)
    assert read["statusCode"] == 200
    assert body_of(read)["title"] == "New feature"


def test_create_story_422_before_404(handler):
    # Missing title must 422 even when project is unknown.
    resp = invoke(
        handler,
        "POST",
        "/stories",
        token=TOKEN,
        body={"project_id": "NOPE"},
    )
    assert resp["statusCode"] == 422
    assert body_of(resp)["detail"] == "Field 'title' is required"


def test_create_story_unknown_project_404(handler):
    resp = invoke(
        handler,
        "POST",
        "/stories",
        token=TOKEN,
        body={"project_id": "NOPE", "title": "x"},
    )
    assert resp["statusCode"] == 404
    assert body_of(resp)["detail"] == "Project not found"


def test_create_project_409_duplicate(handler):
    resp = invoke(handler, "POST", "/projects", token=TOKEN, body={"id": "pay"})
    assert resp["statusCode"] == 409
    assert body_of(resp)["detail"] == "Project already exists"


def test_update_story_applies_only_provided(handler):
    resp = invoke(
        handler,
        "PUT",
        "/stories/PAY-107",
        token=TOKEN,
        body={"status": "in_progress"},
    )
    assert resp["statusCode"] == 200
    updated = body_of(resp)
    assert updated["status"] == "in_progress"
    assert updated["assignee"] == "dev-1"  # unchanged


def test_update_story_404(handler):
    resp = invoke(handler, "PUT", "/stories/PAY-9999", token=TOKEN, body={"status": "done"})
    assert resp["statusCode"] == 404
