"""Seed enrichment integrity (skills design section F)."""

import importlib
from datetime import timedelta

import pytest

from common import seed_dates
from common.seed_dates import ANCHOR
from jira import routes as jira_routes
from jira import seed_data as jira_seed
from servicenow import routes as sn_routes
from servicenow import seed_data as sn_seed
from tests.conftest import body_of, make_event

TOKEN = "mock-jira-token-12345"
PROJECTS = ("PAY", "CART", "AUTH", "PROD", "ORD")

# key -> (title, status, assignee) of the stories that existed before enrichment.
ORIGINAL_STORIES = {
    "PAY-101": ("Implement Stripe webhook handler", "done", "dev-1"),
    "PAY-102": ("Add Apple Pay integration", "done", "dev-1"),
    "PAY-103": ("PCI compliance audit fixes", "done", "dev-3"),
    "PAY-104": ("Refund processing optimization", "done", "dev-5"),
    "PAY-105": ("Google Pay integration", "in_progress", "dev-1"),
    "PAY-106": ("Payment retry mechanism", "done", "dev-3"),
    "PAY-107": ("Multi-currency support", "todo", "dev-1"),
    "PAY-108": ("Payment analytics dashboard", "in_review", "dev-5"),
    "PAY-109": ("Cryptocurrency payment option", "todo", "dev-6"),
    "PAY-110": ("Fraud detection enhancement", "todo", "dev-6"),
    "CART-201": ("Implement cart persistence across sessions", "done", "dev-2"),
    "CART-202": ("Quantity update performance fix", "done", "dev-2"),
    "CART-203": ("Coupon code system", "done", "dev-4"),
    "CART-204": ("Wishlist to cart conversion", "done", "dev-2"),
    "CART-205": ("Cart abandonment email trigger", "todo", "dev-4"),
    "CART-206": ("Shipping cost estimator", "in_progress", "dev-2"),
    "AUTH-301": ("Implement OAuth2 with Google", "done", "dev-3"),
    "AUTH-302": ("Password reset flow", "done", "dev-3"),
    "AUTH-303": ("Rate limiting on login endpoint", "done", "dev-3"),
    "AUTH-304": ("Two-factor authentication (TOTP)", "done", "dev-3"),
    "AUTH-305": ("Session management improvements", "todo", "dev-3"),
    "AUTH-306": ("Single Sign-On (SSO) with SAML for enterprise customers", "in_progress", "dev-6"),
    "PROD-401": ("Elasticsearch integration for product search", "done", "dev-4"),
    "PROD-402": ("Product image optimization pipeline", "done", "dev-4"),
    "PROD-403": ("Product recommendations engine", "in_progress", "dev-4"),
    "PROD-404": ("Inventory low-stock alerts", "done", "dev-5"),
    "ORD-501": ("Order tracking real-time updates", "done", "dev-5"),
    "ORD-502": ("Return request automation", "done", "dev-5"),
    "ORD-503": ("Split order fulfillment", "in_progress", "dev-5"),
    "ORD-504": ("Order bulk export for accounting", "done", "dev-5"),
}

RELINKS = {
    "DEP-1008": "PAY-105", "DEP-1010": "PAY-106", "DEP-1011": "PAY-101",
    "DEP-1013": "PAY-103", "DEP-1014": "PAY-110",
    "DEP-1016": "CART-203", "DEP-1020": "CART-201", "DEP-1022": "CART-206",
    "DEP-1025": "AUTH-306", "DEP-1028": "AUTH-301", "DEP-1031": "AUTH-304",
    "DEP-1034": "PROD-403", "DEP-1035": "PROD-404", "DEP-1036": "PROD-401",
    "DEP-1037": "PROD-402",
    "DEP-1042": "ORD-503", "DEP-1043": "ORD-501", "DEP-1048": "ORD-503",
}


def _records(items, pk):
    return [i["record"] for i in items if i["pk"] == pk]


def _jira(monkeypatch, offset=0):
    monkeypatch.setattr(seed_dates, "today_utc", lambda: ANCHOR + timedelta(days=offset))
    items = list(jira_routes.seed_items())
    return (
        _records(items, "SPRINT"),
        _records(items, "STORY"),
        _records(items, "DEVELOPER"),
    )


def test_ids_are_unique(monkeypatch):
    sprints, stories, _ = _jira(monkeypatch)
    assert len({s["id"] for s in sprints}) == len(sprints)
    assert len({s["id"] for s in stories}) == len(stories)
    assert len(stories) == len(ORIGINAL_STORIES) + 74
    assert len(sprints) == 11 + 11


def test_story_sprint_refs_share_project(monkeypatch):
    sprints, stories, _ = _jira(monkeypatch)
    sprint_project = {s["id"]: s["project_id"] for s in sprints}
    for story in stories:
        assert story["id"].startswith(story["project_id"] + "-")
        if story["sprint_id"] is not None:
            assert sprint_project[story["sprint_id"]] == story["project_id"], story["id"]


def test_velocity_equals_done_points_for_completed_sprints(monkeypatch):
    sprints, stories, _ = _jira(monkeypatch)
    for sprint in sprints:
        if sprint["status"] != "completed":
            continue
        done = sum(
            s["story_points"] for s in stories
            if s["sprint_id"] == sprint["id"] and s["status"] == "done"
        )
        assert done == sprint["velocity"], sprint["id"]


def test_completed_sprint_counts_and_velocity_series(monkeypatch):
    sprints, _, _ = _jira(monkeypatch)
    series = {}
    for sprint in sorted(sprints, key=lambda s: s["end_date"]):
        if sprint["status"] == "completed":
            series.setdefault(sprint["project_id"], []).append(sprint["velocity"])
    assert series == {
        "PAY": [26, 29, 31, 34],
        "CART": [24, 26, 28],
        "AUTH": [18, 19, 21],
        "PROD": [26, 29, 31],
        "ORD": [21, 24, 26],
    }


def test_new_history_sprints_end_before_s1(monkeypatch):
    sprints, _, _ = _jira(monkeypatch)
    by_id = {s["id"]: s for s in sprints}
    for sprint in sprints:
        if "-H" in sprint["id"]:
            s1 = by_id[sprint["project_id"] + "-S1"]
            assert sprint["end_date"] < s1["start_date"]


def test_existing_stories_unchanged(monkeypatch):
    _, stories, _ = _jira(monkeypatch)
    by_id = {s["id"]: s for s in stories}
    for key, (title, status, assignee) in ORIGINAL_STORIES.items():
        story = by_id[key]
        assert (story["title"], story["status"], story["assignee"]) == (title, status, assignee)


def test_pay_numbers_stay_at_or_below_110(monkeypatch):
    _, stories, _ = _jira(monkeypatch)
    assert max(int(s["id"].split("-")[1]) for s in stories if s["project_id"] == "PAY") == 110


def test_pay_s2_untouched(monkeypatch):
    _, stories, _ = _jira(monkeypatch)
    s2 = [s for s in stories if s["sprint_id"] == "PAY-S2"]
    assert sum(s["story_points"] for s in s2) == 34
    assert sum(1 for s in s2 if s["status"] == "done") == 1


def test_new_story_content(monkeypatch):
    _, stories, _ = _jira(monkeypatch)
    new = [s for s in stories if s["id"] not in ORIGINAL_STORIES]
    assert len(new) == 74
    for story in new:
        assert story["description"]
        assert len(story["acceptance_criteria"]) == 2
        assert story["priority"] in ("critical", "high", "medium", "low")
    backlog = [s for s in new if s["sprint_id"] is None]
    assert backlog and all(s["assignee"] is None and s["status"] == "todo" for s in backlog)
    carry = [s for s in new if s["sprint_id"] and s["sprint_id"] != "PAY-S2" and s["status"] != "done"]
    assert len(carry) == 9
    assert all(len(s["comments"]) == 1 for s in carry)


def test_pay_worked_example(monkeypatch):
    _, stories, _ = _jira(monkeypatch)
    s1 = [s for s in stories if s["sprint_id"] == "PAY-S1"]
    done = [s for s in s1 if s["status"] == "done"]
    pending = [s for s in s1 if s["status"] != "done"]
    assert sum(s["story_points"] for s in done) == 34
    assert sum(s["story_points"] for s in pending) == 8
    assert {s["id"] for s in pending} == {"PAY-098", "PAY-099"}


def test_developer_fields(monkeypatch):
    _, _, devs = _jira(monkeypatch)
    by_id = {d["id"]: d for d in devs}
    assert len(devs) == 6
    for dev in devs:
        assert dev["skills"] and dev["capacity_points"]
    assert "primary_service" not in by_id["dev-6"]
    assert by_id["dev-1"]["capacity_points"] == {"PAY": 16, "CART": 5}
    totals = {p: sum(d["capacity_points"].get(p, 0) for d in devs) for p in PROJECTS}
    assert totals == {"PAY": 35, "CART": 26, "AUTH": 21, "PROD": 23, "ORD": 21}


def test_servicenow_relinks_resolve(monkeypatch):
    _, stories, _ = _jira(monkeypatch)
    story_ids = {s["id"] for s in stories}
    items = list(sn_routes.seed_items())
    deployments = {d["id"]: d for d in _records(items, "DEPLOYMENT")}
    for dep_id, story in RELINKS.items():
        assert deployments[dep_id]["linked_story"] == story
        assert story in story_ids
    assert deployments["DEP-1007"]["linked_story"] == "PAY-601"
    incidents = {i["id"]: i for i in _records(items, "INCIDENT")}
    assert incidents["INC-2002"]["linked_deployment"] in (None, "")


def test_relink_does_not_mutate_module_constants(monkeypatch):
    before = {d["id"]: d["linked_story"] for d in sn_seed.DEPLOYMENTS}
    list(sn_routes.seed_items())
    assert {d["id"]: d["linked_story"] for d in sn_seed.DEPLOYMENTS} == before
    assert before["DEP-1014"] != "PAY-110"


@pytest.mark.parametrize("offset", [-30, -3, 0, 4, 45, 200])
def test_shift_preserved_for_new_sprints(monkeypatch, offset):
    days = seed_dates.compute_shift_days(ANCHOR + timedelta(days=offset))
    sprints, stories, _ = _jira(monkeypatch, offset)
    h1 = next(s for s in sprints if s["id"] == "PAY-H1")
    assert h1["start_date"] == seed_dates.shift_value("2026-07-14", days)
    assert h1["end_date"] == seed_dates.shift_value("2026-07-25", days)
    story = next(s for s in stories if s["id"] == "PAY-085")
    assert story["comments"][0]["date"] == seed_dates.shift_value("2026-07-24", days)


def test_list_sprints_has_points_for_completed(dynamo_table, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", dynamo_table)
    monkeypatch.setenv("MOCK_JIRA_TOKEN", TOKEN)
    import jira.handler as h

    importlib.reload(h)
    h._store = None
    h._router = None
    resp = h.lambda_handler(make_event("GET", "/sprints/PAY", token=TOKEN), None)
    sprints = {s["id"]: s for s in body_of(resp)["sprints"]}
    assert sprints["PAY-S1"]["completed_points"] == 34
    assert sprints["PAY-S1"]["total_points"] == 42
    assert sprints["PAY-H3"]["completed_points"] == 26
    assert "completed_points" not in sprints["PAY-S3"]
