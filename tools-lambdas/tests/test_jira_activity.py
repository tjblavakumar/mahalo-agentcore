"""ACTIVITY log, GET /activity and demo activity seed for the Jira mock."""
import importlib
from datetime import datetime, timedelta, timezone

import pytest

from common import tool_schemas
from jira import routes, seed_data
from tests.conftest import body_of, make_event

TOKEN = "mock-jira-token-12345"
_FMT = "%Y-%m-%dT%H:%M:%SZ"


@pytest.fixture
def handler(dynamo_table, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", dynamo_table)
    monkeypatch.setenv("MOCK_JIRA_TOKEN", TOKEN)
    import jira.handler as h

    importlib.reload(h)
    h._store = None
    h._router = None
    return h


def invoke(handler, method, path, **kwargs):
    return handler.lambda_handler(make_event(method, path, **kwargs), None)


def _activity(handler, **query):
    resp = invoke(handler, "GET", "/activity", token=TOKEN, query=query or None)
    assert resp["statusCode"] == 200
    return body_of(resp)["activity"]


def _live(handler):
    """Activity written by routes (not the demo seed)."""
    return [a for a in _activity(handler) if a["origin"] == "write"]


def test_update_story_logs_status_and_assignee_with_from_to(handler):
    before = body_of(invoke(handler, "GET", "/stories/PAY-107", token=TOKEN))
    resp = invoke(
        handler, "PUT", "/stories/PAY-107", token=TOKEN,
        body={"status": "in_review", "assignee": "dev-7"},
    )
    assert resp["statusCode"] == 200
    items = {a["type"]: a for a in _live(handler)}
    assert items["status"]["from"] == before["status"]
    assert items["status"]["to"] == "in_review"
    assert items["assigned"]["from"] == before["assignee"]
    assert items["assigned"]["to"] == "dev-7"
    assert items["status"]["story_id"] == "PAY-107"


def test_update_story_unchanged_values_write_nothing(handler):
    before = body_of(invoke(handler, "GET", "/stories/PAY-107", token=TOKEN))
    invoke(
        handler, "PUT", "/stories/PAY-107", token=TOKEN,
        body={"status": before["status"], "assignee": before["assignee"], "priority": "high"},
    )
    assert _live(handler) == []


def test_add_comment_logs_author_and_text(handler):
    resp = invoke(
        handler, "POST", "/stories/PAY-110/comments", token=TOKEN,
        body={"author": "dev-7", "text": "Design review: please add an ADR"},
    )
    assert resp["statusCode"] == 201
    (item,) = _live(handler)
    assert item["type"] == "comment"
    assert item["actor"] == "dev-7"
    assert item["text"] == "Design review: please add an ADR"


def test_create_story_logs_created_and_assigned(handler):
    resp = invoke(
        handler, "POST", "/stories", token=TOKEN,
        body={"project_id": "PAY", "title": "New thing", "assignee": "dev-6"},
    )
    assert resp["statusCode"] == 201
    new_id = body_of(resp)["id"]
    kinds = sorted(a["type"] for a in _live(handler) if a["story_id"] == new_id)
    assert kinds == ["assigned", "created"]


def test_story_and_comment_responses_have_no_activity_fields(handler):
    resp = invoke(
        handler, "POST", "/stories/PAY-110/comments", token=TOKEN,
        body={"author": "dev-7", "text": "hello"},
    )
    story = body_of(resp)
    assert set(story) == {
        "id", "project_id", "sprint_id", "title", "description", "status", "priority",
        "story_points", "assignee", "acceptance_criteria", "comments",
    }
    assert set(story["comments"][-1]) == {"author", "text", "date"}


def test_activity_write_failure_does_not_fail_the_route(handler, monkeypatch):
    invoke(handler, "GET", "/projects", token=TOKEN)  # initialise the store
    store = handler._store
    real_put = store.put

    def failing_put(pk, sk, record, attr="data"):
        if pk == routes.PK_ACTIVITY:
            raise RuntimeError("boom")
        return real_put(pk, sk, record, attr)

    monkeypatch.setattr(store, "put", failing_put)
    resp = invoke(
        handler, "POST", "/stories/PAY-110/comments", token=TOKEN,
        body={"author": "dev-7", "text": "still saved"},
    )
    assert resp["statusCode"] == 201
    assert body_of(resp)["comments"][-1]["text"] == "still saved"


def test_activity_requires_token(handler):
    assert invoke(handler, "GET", "/activity")["statusCode"] == 401


def test_activity_since_filters_and_sorts_descending(handler):
    invoke(handler, "GET", "/projects", token=TOKEN)
    store = handler._store
    now = datetime.now(timezone.utc)
    for hours in (1, 30, 200):
        ts = (now - timedelta(hours=hours)).strftime(_FMT)
        store.put("ACTIVITY", f"t#{ts}", {"ts": ts, "story_id": "X-1", "type": "status", "origin": "write"})
    since = (now - timedelta(hours=48)).strftime(_FMT)
    got = [a for a in _activity(handler, since=since) if a["story_id"] == "X-1"]
    assert len(got) == 2
    all_ts = [a["ts"] for a in _activity(handler, since=since)]
    assert all_ts == sorted(all_ts, reverse=True)
    default = [a for a in _activity(handler) if a["story_id"] == "X-1"]
    assert len(default) == 2  # default window is 7 days; the 200 h item is excluded


def test_activity_rejects_bad_since(handler):
    resp = invoke(handler, "GET", "/activity", token=TOKEN, query={"since": "yesterday"})
    assert resp["statusCode"] == 422
    assert body_of(resp)["detail"] == "since must be an ISO UTC datetime"


def test_activity_with_1100_items_is_sorted(handler):
    invoke(handler, "GET", "/projects", token=TOKEN)
    store = handler._store
    base = datetime.now(timezone.utc) - timedelta(hours=100)
    store.batch_write(
        {
            "pk": "ACTIVITY",
            "sk": f"bulk#{i:05d}",
            "record": {
                "ts": (base + timedelta(seconds=i)).strftime(_FMT),
                "story_id": "B-1",
                "type": "status",
                "origin": "write",
            },
        }
        for i in range(1100)
    )
    got = [a for a in _activity(handler) if a["story_id"] == "B-1"]
    assert len(got) == 1100
    ts = [a["ts"] for a in got]
    assert ts == sorted(ts, reverse=True)


def test_activity_is_not_a_gateway_tool():
    assert "/activity" not in repr(vars(tool_schemas))


def test_seed_items_include_demo_activity(handler):
    items = list(routes.seed_items())
    activity = [i for i in items if i["pk"] == "ACTIVITY"]
    assert activity
    assert all(i["record"]["origin"] == "demo-seed" for i in activity)
    assert all(i["sk"].startswith("demo#") for i in activity)
    stories = {i["record"]["id"]: i["record"] for i in items if i["pk"] == "STORY"}
    for rec in (i["record"] for i in activity):
        story = stories[rec["story_id"]]
        if rec["type"] == "assigned":
            assert story["assignee"] == rec["to"]
        if rec["type"] == "status":
            assert story["status"] == rec["to"]
        if rec["type"] == "comment":
            assert any(
                c["author"] == rec["actor"] and c["text"] == rec["text"] for c in story["comments"]
            )
    assigned = {r["record"]["story_id"] for r in activity if r["record"]["type"] == "assigned"}
    assert {"PAY-109", "PAY-110"} <= assigned


def test_recent_activity_offsets_are_relative_to_now_and_skip_mismatches():
    now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)
    stories = [
        {"id": "A-1", "project_id": "A", "assignee": "dev-6", "status": "todo", "comments": []},
        {
            "id": "A-2", "project_id": "A", "assignee": "dev-2", "status": "in_review",
            "comments": [{"author": "dev-1", "text": "ok", "date": "2026-11-24"}],
        },
    ]
    out = seed_data.recent_activity(now, stories)
    by = {(i["story_id"], i["type"]): i for i in out}
    assert by[("A-1", "assigned")]["ts"] == "2026-11-24T10:00:00Z"
    assert by[("A-2", "status")]["to"] == "in_review"
    assert by[("A-2", "comment")]["actor"] == "dev-1"
    # A story whose record does not support any claim yields nothing.
    stories = [{"id": "B-1", "project_id": "B", "assignee": "dev-2", "status": "todo", "comments": []}]
    assert seed_data.recent_activity(now, stories) == []
