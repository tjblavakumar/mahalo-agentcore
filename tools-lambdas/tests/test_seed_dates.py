"""Tests for seed date shifting and the shifted seed_items of each service."""
import copy
from datetime import date, datetime, timedelta

import pytest

from common import seed_dates
from common.seed_dates import (
    ANCHOR,
    compute_shift_days,
    shift_records,
    shift_story_comments,
    shift_value,
)


def test_anchor_shift_is_zero():
    assert compute_shift_days(ANCHOR) == 0


@pytest.mark.parametrize("offset", [-400, -31, -4, -3, 0, 3, 4, 10, 45, 365])
def test_shift_is_multiple_of_seven(offset):
    assert compute_shift_days(ANCHOR + timedelta(days=offset)) % 7 == 0


def test_shift_rounds_to_nearest_week():
    assert compute_shift_days(ANCHOR + timedelta(days=3)) == 0
    assert compute_shift_days(ANCHOR + timedelta(days=4)) == 7
    assert compute_shift_days(date(2026, 9, 30)) == 42


def test_shift_value_date_and_datetime():
    assert shift_value("2026-08-11", 7) == "2026-08-18"
    assert shift_value("2026-08-11", -14) == "2026-07-28"
    assert shift_value("2026-08-18T14:05:09Z", 7) == "2026-08-25T14:05:09Z"
    assert shift_value("2026-12-30T23:59:59Z", 7) == "2027-01-06T23:59:59Z"


@pytest.mark.parametrize("value", [None, "", "hello", "2026-13-45", 42, "PAY-S2"])
def test_shift_value_leaves_others_untouched(value):
    assert shift_value(value, 21) == value


def test_weekday_preserved():
    days = compute_shift_days(date(2027, 3, 3))
    before = datetime.strptime("2026-08-11", "%Y-%m-%d").date()
    after = datetime.strptime(shift_value("2026-08-11", days), "%Y-%m-%d").date()
    assert before.weekday() == after.weekday()


def test_shift_records_copies_and_limits_fields():
    recs = [{"id": "x", "start_date": "2026-08-11", "name": "2026-08-11", "end_date": None}]
    original = copy.deepcopy(recs)
    out = shift_records(recs, 7, ("start_date", "end_date", "missing"))
    assert recs == original
    assert out[0]["start_date"] == "2026-08-18"
    assert out[0]["end_date"] is None
    assert out[0]["name"] == "2026-08-11"
    assert out[0]["id"] == "x"
    assert out[0] is not recs[0]


def test_shift_story_comments_nested_and_not_mutating():
    stories = [{"id": "A-1", "comments": [{"author": "dev-1", "date": "2026-08-10", "text": "hi"}]},
               {"id": "A-2", "comments": []}, {"id": "A-3"}]
    original = copy.deepcopy(stories)
    out = shift_story_comments(stories, 14)
    assert stories == original
    assert out[0]["comments"][0]["date"] == "2026-08-24"
    assert out[0]["comments"][0]["text"] == "hi"
    assert out[1]["comments"] == [] and "comments" not in out[2]


@pytest.mark.parametrize("offset", [-3, -2, -1, 0, 1, 2, 3, 30, 100, -200])
def test_active_sprint_contains_today(monkeypatch, offset):
    from jira import routes

    today = ANCHOR + timedelta(days=offset)
    monkeypatch.setattr(seed_dates, "today_utc", lambda: today)
    sprints = [i["record"] for i in routes.seed_items() if i["pk"] == "SPRINT"]
    active = [s for s in sprints if s["status"] == "active"]
    assert len(active) == 5
    if abs(offset) <= 3:
        for s in active:
            assert s["start_date"] <= today.isoformat() <= s["end_date"]


def test_seed_items_do_not_mutate_seed_constants(monkeypatch):
    from confluence import routes as conf
    from jira import routes as jira
    from jira import seed_data as jira_seed
    from servicenow import routes as snow
    from servicenow import seed_data as snow_seed
    from confluence import seed_data as conf_seed

    snapshot = copy.deepcopy((jira_seed.SPRINTS, jira_seed.STORIES, snow_seed.DEPLOYMENTS,
                              snow_seed.INCIDENTS, conf_seed.PAGES))
    monkeypatch.setattr(seed_dates, "today_utc", lambda: date(2027, 1, 5))
    shifted = {
        "jira": list(jira.seed_items()),
        "snow": list(snow.seed_items()),
        "conf": list(conf.seed_items()),
    }
    assert (jira_seed.SPRINTS, jira_seed.STORIES, snow_seed.DEPLOYMENTS,
            snow_seed.INCIDENTS, conf_seed.PAGES) == snapshot
    # keys and ids unchanged, dates moved
    assert [i["sk"] for i in shifted["jira"] if i["pk"] == "STORY"] == [s["id"] for s in jira_seed.STORIES]
    pay_s2 = next(i["record"] for i in shifted["jira"] if i["sk"] == "PAY-S2")
    assert pay_s2["start_date"] != "2026-08-11"
    inc = [i["record"] for i in shifted["snow"] if i["pk"] == "INCIDENT"]
    assert all(r["opened_at"] != o["opened_at"] for r, o in zip(inc, snow_seed.INCIDENTS))
    assert [r["resolved_at"] is None for r in inc] == [o["resolved_at"] is None for o in snow_seed.INCIDENTS]
    page = next(i["record"] for i in shifted["conf"] if i["pk"] == "PAGE")
    assert page["last_updated"] != conf_seed.PAGES[0]["last_updated"]


def test_every_active_board_has_done_and_progress():
    from jira import seed_data

    for proj in seed_data.PROJECTS:
        active = next(s for s in seed_data.SPRINTS if s["project_id"] == proj["id"] and s["status"] == "active")
        stories = [s for s in seed_data.STORIES if s["sprint_id"] == active["id"]]
        done = [s for s in stories if s["status"] == "done"]
        assert done, proj["id"]
        assert sum(s["story_points"] for s in done) > 0
