"""24-hour window, future exclusion, four fallback modes and snapshots."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.briefing import rank, sources
from tests.briefing_data import FMT, NOW, ago, day, make_raw


def _empty_raw():
    raw = make_raw()
    for key in ("activity", "incidents", "deployments", "runs", "pages", "pulls"):
        raw[key] = []
    for s in raw["stories"]:
        s["comments"] = []
    raw["commits"] = {k: [] for k in raw["commits"]}
    return raw


def _inc(iid, opened, sev="P1", svc="payment-service", resolved=None):
    return {"id": iid, "severity": sev, "affected_service": svc, "opened_at": opened,
            "resolved_at": resolved, "title": "t"}


def _build(persona, dev_id, raw, now=NOW):
    return rank.build_briefing(persona, dev_id, sources.normalize(raw), raw, now)


def test_mode_recent_when_five_or_more_events():
    r = _build("dev", "dev-6", make_raw())
    assert r["mode"] == "recent"
    assert r["headline"] == "Since yesterday"
    assert len(r["top"]) == 5 and all(i["tag"] is None for i in r["top"])
    assert r["snapshot"] == []


def test_mode_topped_up_fills_from_earlier_with_tag():
    raw = _empty_raw()
    raw["incidents"] = [
        _inc("INC-1", ago(hours=2)), _inc("INC-2", ago(hours=3), sev="P2"),
        _inc("INC-3", ago(days=3)), _inc("INC-4", ago(days=4), sev="P2"),
        _inc("INC-5", ago(days=5)), _inc("INC-6", ago(days=6)),
    ]
    r = _build("exec", "dev-5", raw)
    assert r["mode"] == "topped_up"
    assert r["headline"] == "Since yesterday: 2 new in the last 24 hours"
    assert [i["id"] for i in r["top"]] == ["INC-1", "INC-2", "INC-3", "INC-5", "INC-6"]
    assert [i["tag"] for i in r["top"]] == [None, None, "earlier", "earlier", "earlier"]
    assert [i["id"] for i in r["items"]] == ["INC-1", "INC-2"]
    assert [i["id"] for i in r["earlier"]] == ["INC-3", "INC-5", "INC-6", "INC-4"]
    assert r["counts"] == {"last_24h": 2, "earlier": 4}


def test_mode_widened_when_nothing_in_24h():
    raw = _empty_raw()
    raw["incidents"] = [_inc(f"INC-{n}", ago(days=2, hours=n)) for n in range(1, 8)]
    r = _build("exec", "dev-5", raw)
    assert r["mode"] == "widened"
    assert r["headline"] == "Nothing new in the last 24 hours. Most recent activity:"
    assert r["items"] == []
    assert len(r["top"]) == 5 and all(i["tag"] == "earlier" for i in r["top"])
    assert r["counts"] == {"last_24h": 0, "earlier": 7}


def test_earlier_is_capped_at_50_and_items_at_150():
    raw = _empty_raw()
    raw["incidents"] = [_inc(f"INC-{n:04d}", ago(days=3, minutes=n)) for n in range(80)]
    r = _build("exec", "dev-5", raw)
    assert len(r["earlier"]) == 50
    raw["incidents"] = [_inc(f"INC-{n:04d}", ago(minutes=n + 1), svc="auth-service") for n in range(200)]
    r = _build("exec", "dev-5", raw)
    assert len(r["items"]) <= 150 and len(r["top"]) == 5  # bursts of equal times collapse but cap holds


EXPECTED_SNAPSHOT = {
    ("dev", "dev-6"): [
        "3 stories assigned to you: PAY-109, PAY-110, AUTH-306",
        "5 open stories in your projects",
        "0 open incidents on your services",
    ],
    ("pm", "dev-1"): [
        "4 open stories in your projects",
        "4 stories in the active sprint",
        "0 open incidents in your projects",
    ],
    ("exec", "dev-5"): [
        "0 open P1/P2 incidents",
        "0 open incidents in total",
        "0 failed or rolled-back production deploys in the last 7 days",
    ],
    ("arch", "dev-7"): [
        "0 high/critical security findings in seeded CI/CD runs in the last 7 days",
        "0 failed or rolled-back production deploys in the last 7 days",
        "0 open P1/P2 incidents",
        "0 Confluence pages updated in the last 30 days",
    ],
}


@pytest.mark.parametrize("key", list(EXPECTED_SNAPSHOT))
def test_mode_snapshot_lines_per_persona_including_zero_counts(key):
    r = _build(key[0], key[1], _empty_raw())
    assert r["mode"] == "snapshot"
    assert r["headline"] == "Quiet since yesterday. Where things stand:"
    assert r["snapshot"] == EXPECTED_SNAPSHOT[key]
    assert r["top"] == [] and r["items"] == [] and r["earlier"] == []


def test_snapshot_includes_last_production_deploy_and_open_counts():
    raw = _empty_raw()
    raw["deployments"] = [
        {"id": "D1", "service": "payment-service", "environment": "production", "status": "success",
         "version": "v1.2.3", "deployed_at": ago(days=20), "linked_story": None},
        {"id": "D0", "service": "payment-service", "environment": "production", "status": "failed",
         "version": "v1.0.0", "deployed_at": ago(days=40), "linked_story": None},
        {"id": "DF", "service": "payment-service", "environment": "production", "status": "failed",
         "version": "v9", "deployed_at": (NOW + timedelta(days=1)).strftime(FMT), "linked_story": None},
    ]
    raw["incidents"] = [_inc("I1", ago(days=30), sev="P3"), _inc("I2", ago(days=30), sev="P1", svc="auth-service")]
    dev = _build("dev", "dev-6", raw)["snapshot"]
    assert "2 open incidents on your services" in dev
    assert "Last production deploy of your services: payment-service v1.2.3 success" in dev
    assert "1 open P1/P2 incident" in _build("exec", "dev-5", raw)["snapshot"]


def test_snapshot_line_needs_its_source_and_zero_lines_raises():
    raw = _empty_raw()
    raw["unavailable"] = ["Jira", "ServiceNow"]
    for persona, dev_id in (("dev", "dev-6"), ("pm", "dev-1"), ("exec", "dev-5")):
        with pytest.raises(rank.BriefingUnavailable):
            _build(persona, dev_id, raw)
    # the architect still has the Confluence line
    r = _build("arch", "dev-7", raw)
    assert r["snapshot"] == ["0 Confluence pages updated in the last 30 days"]
    assert r["unavailable"] == ["Jira", "ServiceNow"]


def test_future_events_are_excluded_boundary_is_now():
    raw = _empty_raw()
    raw["incidents"] = [
        _inc("INC-NOW", NOW.strftime(FMT)),
        _inc("INC-FUT", (NOW + timedelta(seconds=1)).strftime(FMT)),
    ]
    assert [i["id"] for i in _build("exec", "dev-5", raw)["items"]] == ["INC-NOW"]


def test_24_hour_boundary_is_inclusive():
    raw = _empty_raw()
    raw["incidents"] = [
        _inc("INC-IN", (NOW - timedelta(hours=24)).strftime(FMT)),
        _inc("INC-OUT", (NOW - timedelta(hours=24, seconds=1)).strftime(FMT)),
    ]
    r = _build("exec", "dev-5", raw)
    assert [i["id"] for i in r["items"]] == ["INC-IN"]
    assert [i["id"] for i in r["earlier"]] == ["INC-OUT"]


def test_seven_day_limit():
    raw = _empty_raw()
    raw["incidents"] = [_inc("INC-OLD", ago(days=7, seconds=1)), _inc("INC-OK", ago(days=7))]
    r = _build("exec", "dev-5", raw)
    assert [i["id"] for i in r["earlier"]] == ["INC-OK"]


def test_day_precision_today_yesterday_and_future_dates():
    raw = _empty_raw()
    raw["pages"] = [
        {"id": "P-TODAY", "title": "today page", "last_updated": day(0)},
        {"id": "P-YDAY", "title": "yesterday page", "last_updated": day(1)},
        {"id": "P-OLD", "title": "old page", "last_updated": day(4)},
        {"id": "P-FUT", "title": "future page", "last_updated": day(-1)},
    ]
    r = _build("arch", "dev-7", raw)
    by = {i["id"]: i for i in r["items"] + r["earlier"]}
    assert by["P-TODAY"]["day_label"] == "today" and by["P-TODAY"]["ts"] == NOW.strftime(FMT)
    assert by["P-YDAY"]["day_label"] == "yesterday" and by["P-YDAY"]["ts"] == "2026-11-23T23:59:59Z"
    assert by["P-YDAY"]["precision"] == "day"
    assert by["P-OLD"]["day_label"] is None
    assert "P-FUT" not in by
    assert {"P-TODAY", "P-YDAY"} <= {i["id"] for i in r["items"]}
    assert "P-OLD" in {i["id"] for i in r["earlier"]}


def test_day_precision_ts_is_computed_per_request_not_frozen_in_cache():
    raw = _empty_raw()
    raw["pages"] = [{"id": "P", "title": "t", "last_updated": "2026-11-24"}]
    events = sources.normalize(raw)  # what the cache would hold
    first = rank.build_briefing("arch", "dev-7", events, raw, NOW)
    later = rank.build_briefing("arch", "dev-7", events, raw, NOW + timedelta(hours=1))
    assert first["items"][0]["ts"] == "2026-11-24T22:30:00Z"
    assert later["items"][0]["ts"] == "2026-11-24T23:30:00Z"
    # on the next day the same page is "yesterday"
    nxt = rank.build_briefing("arch", "dev-7", events, raw, NOW + timedelta(hours=3))
    assert nxt["items"][0]["day_label"] == "yesterday"


def test_field_semantics_and_generated_at():
    r = _build("arch", "dev-7", make_raw())
    assert r["generated_at"] == "2026-11-24T22:30:00Z"
    assert r["persona"] == "arch"
    assert r["counts"]["last_24h"] == len(r["items"])
    assert r["counts"]["earlier"] == len(r["earlier"])
    assert r["snapshot"] == []
    assert set(r["labels"]) == {"Jira", "ServiceNow", "Confluence", "CI/CD", "Git"}
    assert r["labels"]["CI/CD"] == "Seeded demo data. Not a live pipeline run."
    assert r["labels"]["Git"].startswith("Real Gitea.")
    for item in r["top"] + r["items"] + r["earlier"]:
        assert set(item) == {"id", "kind", "system", "line", "ts", "precision", "day_label", "ref", "count", "tag"}
        assert set(item["ref"]) == {"type", "id", "url"}
