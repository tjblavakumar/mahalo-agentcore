"""Per-persona ranking, merging and grouping for the login briefing (pure functions)."""
from __future__ import annotations

import copy
import dataclasses
import random

import pytest

from app.briefing import rank, sources
from app.briefing.models import Event
from tests.briefing_data import NOW, ago, day, make_raw

PERSONAS = (("dev", "dev-6"), ("pm", "dev-1"), ("exec", "dev-5"), ("arch", "dev-7"))


def _build(persona, dev_id, raw=None, now=NOW):
    raw = raw or make_raw()
    return rank.build_briefing(persona, dev_id, sources.normalize(raw), raw, now)


def _ids(result, key="top"):
    return [i["id"] for i in result[key]]


def _ev(kind, **kw):
    base = dict(system="Jira", when=ago(hours=1), precision="minute", head="h", ref_id="X-1")
    base.update(kw)
    return Event(kind=kind, **base)


def _ctx(persona, dev_id, projects=("PAY",)):
    return rank.Ctx(persona, dev_id, frozenset(projects), frozenset(sources.PROJECT_SERVICE[p] for p in projects))


EXPECTED_TOP = {
    "dev": ["PAY-109", "PAY-110", "RUN-1", "DEP-1011", "DEP-1013"],
    "pm": ["INC-2011", "PAY-109", "PAY-110", "PAY-108", "DEP-1013"],
    "exec": ["INC-2001", "INC-2008", "DEP-1005", "DEP-1011", "RUN-1"],
    "arch": ["RUN-1", "DEP-1005", "DEP-1011", "cart-service#4", "product-service#2"],
}


@pytest.mark.parametrize("persona,dev_id", PERSONAS)
def test_top5_is_exact_per_persona(persona, dev_id):
    result = _build(persona, dev_id)
    assert result["mode"] == "recent"
    assert _ids(result) == EXPECTED_TOP[persona]
    assert len(result["top"]) <= 5


def test_the_four_orderings_are_pairwise_different():
    tops = [tuple(_ids(_build(p, d))) for p, d in PERSONAS]
    assert len(set(tops)) == 4


def test_ranking_is_deterministic_for_shuffled_input():
    raw = make_raw()
    events = sources.normalize(raw)
    expected = rank.build_briefing("arch", "dev-7", events, raw, NOW)
    for seed in range(5):
        shuffled = events[:]
        random.Random(seed).shuffle(shuffled)
        assert rank.build_briefing("arch", "dev-7", shuffled, raw, NOW) == expected


def test_developer_gets_assigned_to_me_first_and_you_wording():
    result = _build("dev", "dev-6")
    assert result["top"][0]["kind"] == "assigned"
    assert result["top"][0]["line"].startswith("PAY-109 assigned to you")


def test_architect_comment_scores_95_other_comment_90_for_developer():
    ctx = _ctx("dev", "dev-6")
    mine = dict(story="PAY-110", story_assignee="dev-6")
    assert rank.score(ctx, _ev("comment", actor="dev-7", **mine)) == 95
    assert rank.score(ctx, _ev("comment", actor="dev-1", **mine)) == 90
    assert rank.score(ctx, _ev("comment", actor="dev-1", story="X-9", story_assignee="dev-2", project="ORD")) is None


def test_own_authored_jira_events_are_dropped():
    result = _build("dev", "dev-6")  # dev-6 wrote a comment on AUTH-306
    assert "AUTH-306" not in _ids(result, "items")
    arch = _build("arch", "dev-7")  # the architect's own design-review comment on PAY-110
    assert all("Maya Chaya commented" not in i["line"] for i in arch["items"])


def test_exec_drops_comments_status_commits_p3_and_staging():
    result = _build("exec", "dev-5")
    ids = _ids(result, "items")
    for dropped in ("PAY-108", "ORD-503", "PAY-110", "INC-2020", "DEP-1020"):
        assert dropped not in ids
    assert {i["kind"] for i in result["items"]} <= {
        "incident_open", "deploy_bad", "deploy_ok", "finding", "run_failed", "pr_merged"}


def test_exec_scores():
    ctx = _ctx("exec", "dev-5")
    assert rank.score(ctx, _ev("incident_open", severity="P1")) == 100
    assert rank.score(ctx, _ev("incident_open", severity="P2")) == 92
    assert rank.score(ctx, _ev("incident_resolved", severity="P1")) == 80
    assert rank.score(ctx, _ev("incident_resolved", severity="P2")) == 70
    assert rank.score(ctx, _ev("incident_open", severity="P3")) is None
    assert rank.score(ctx, _ev("deploy_bad", env="production")) == 90
    assert rank.score(ctx, _ev("deploy_bad", env="staging")) is None
    assert rank.score(ctx, _ev("finding")) == 68
    assert rank.score(ctx, _ev("run_failed")) == 66
    assert rank.score(ctx, _ev("pr_merged")) == 35
    assert rank.score(ctx, _ev("pr_open")) is None
    assert rank.score(ctx, _ev("deploy_ok", env="production")) == 30
    assert rank.score(ctx, _ev("comment")) is None
    assert rank.score(ctx, _ev("commits")) is None


def test_architect_table():
    ctx = _ctx("arch", "dev-7")
    assert rank.score(ctx, _ev("finding")) == 100
    assert rank.score(ctx, _ev("comment", design=True, actor="dev-6")) == 95
    assert rank.score(ctx, _ev("comment", actor="dev-6")) == 30
    assert rank.score(ctx, _ev("status")) == 25
    assert rank.score(ctx, _ev("deploy_bad", env="production")) == 90
    assert rank.score(ctx, _ev("pr_open", design=True)) == 89
    assert rank.score(ctx, _ev("pr_merged")) == 45
    assert rank.score(ctx, _ev("page", design=True)) == 88
    assert rank.score(ctx, _ev("page")) == 55
    assert rank.score(ctx, _ev("incident_open", severity="P2")) == 86
    assert rank.score(ctx, _ev("incident_open", severity="P4")) == 62
    assert rank.score(ctx, _ev("incident_resolved", severity="P2")) == 50
    assert rank.score(ctx, _ev("commits")) is None


def test_pm_and_dev_tables():
    pm = _ctx("pm", "dev-1")
    assert rank.score(pm, _ev("incident_open", severity="P1", project="PAY")) == 95
    assert rank.score(pm, _ev("incident_open", severity="P3", project="PAY")) == 70
    assert rank.score(pm, _ev("status", project="PAY")) == 85
    assert rank.score(pm, _ev("deploy_bad", project="PAY", env="production")) == 80
    assert rank.score(pm, _ev("pr_open", project="PAY")) == 78
    assert rank.score(pm, _ev("pr_merged", project="PAY")) == 75
    assert rank.score(pm, _ev("run_failed", project="PAY")) == 60
    assert rank.score(pm, _ev("finding", project="PAY")) == 58
    assert rank.score(pm, _ev("incident_resolved", project="PAY")) == 45
    assert rank.score(pm, _ev("commits", project="PAY")) == 20
    assert rank.score(pm, _ev("incident_open", severity="P1", project="ORD")) is None
    dev = _ctx("dev", "dev-6")
    mine = dict(story="PAY-1", story_assignee="dev-6", project="PAY")
    assert rank.score(dev, _ev("assigned", to="dev-6", **mine)) == 100
    assert rank.score(dev, _ev("deploy_bad", env="staging", **mine)) == 88
    assert rank.score(dev, _ev("status", **mine)) == 80
    assert rank.score(dev, _ev("deploy_bad", env="production", project="PAY")) == 72
    assert rank.score(dev, _ev("incident_open", severity="P2", project="PAY")) == 70
    assert rank.score(dev, _ev("run_failed", project="PAY")) == 65
    assert rank.score(dev, _ev("pr_merged", project="PAY")) == 62
    assert rank.score(dev, _ev("pr_open", project="PAY")) == 60
    assert rank.score(dev, _ev("incident_open", severity="P4", project="PAY")) == 55
    assert rank.score(dev, _ev("incident_resolved", project="PAY")) == 40
    assert rank.score(dev, _ev("commits", project="PAY")) == 40
    assert rank.score(dev, _ev("pr_open", project="ORD")) is None


def test_burst_grouping_and_merges():
    exec_ = _build("exec", "dev-5")
    by_id = {i["id"]: i for i in exec_["items"]}
    assert by_id["INC-2008"]["line"] == "5 x P2 incident opened (AUTH, CART, ORD, PAY, PROD)"
    assert by_id["INC-2008"]["count"] == 5
    assert by_id["INC-2001"]["line"].startswith("P1 incident opened and resolved")
    assert "INC-2001" in by_id and len([i for i in exec_["items"] if i["id"] == "INC-2001"]) == 1
    assert by_id["DEP-1005"]["line"].startswith("Production deploy failed, then rolled back")
    assert "DEP-1004" not in by_id
    assert by_id["DEP-1011"]["line"].startswith("3 x Production deploy rolled back")


def test_burst_never_merges_events_with_different_scores():
    ts = NOW
    same = [dataclasses.replace(_ev("deploy_bad", head="Production deploy rolled back",
                                    ref_id=f"D-{i}", severity="rolled_back", project="PAY"), ts=ts, score=s)
            for i, s in enumerate((88, 72, 72, 72))]
    out = rank._burst(same)
    assert len(out) == 2
    grouped = [e for e in out if e.count == 3]
    assert len(grouped) == 1 and grouped[0].score == 72
    assert any(e.score == 88 and e.count == 1 for e in out)


def test_deploy_findings_are_folded_into_the_deployment_line():
    exec_ = _build("exec", "dev-5")
    by_id = {i["id"]: i for i in exec_["items"]}
    assert "with 1 high findings" in by_id["DEP-1030"]["line"]
    assert "RUN-3" not in by_id  # linked-deployment run is not listed twice


def test_legacy_comment_deduped_against_activity_comment():
    raw = make_raw()
    raw["stories"][4]["comments"] = [
        {"author": "dev-1", "text": "Please confirm the carrier rate limits", "date": day(0)}]
    result = _build("arch", "dev-7", raw)
    lines = [i["line"] for i in result["items"] if "carrier rate limits" in i["line"]]
    assert len(lines) == 1
    kinds = [i for i in result["items"] if i["id"] == "ORD-503" and "carrier" in i["line"]]
    assert kinds[0]["precision"] == "minute"  # the ACTIVITY item won


def test_git_own_authorship_is_dropped_but_unknown_actor_is_kept():
    assert "payment-service#1" not in _ids(_build("pm", "dev-1"), "items")  # authored by Marcus Chen
    assert "payment-service#1" in _ids(_build("dev", "dev-6"), "items")
    assert "payment-service#1" in _ids(_build("exec", "dev-5"), "items")
    assert "cart-service#4" in _ids(_build("arch", "dev-7"), "items")  # no author text: kept


def test_git_line_has_no_garbled_characters_and_url_must_be_https():
    raw = make_raw()
    result = _build("exec", "dev-5", raw)
    pr = next(i for i in result["items"] if i["id"] == "payment-service#1")
    assert pr["line"] == "PR #1 merged in payment-service: Google Pay integration"
    assert pr["ref"]["url"] == "https://git.example.test/p/1"
    arch = _build("arch", "dev-7", raw)
    pr4 = next(i for i in arch["items"] if i["id"] == "cart-service#4")
    assert pr4["ref"]["url"] is None  # http:// is not kept


def test_cross_service_pr_rule():
    raw = make_raw()
    arch = _build("arch", "dev-7", raw)
    scores_top = _ids(arch)
    assert "cart-service#4" in scores_top  # two project keys -> 89
    raw["pulls"][2]["title"] = "PAY-113 to PAY-117 range change"
    raw["pulls"][2]["branch"] = "feature/PAY-113"
    arch = _build("arch", "dev-7", raw)
    assert "cart-service#4" not in _ids(arch)  # one project -> 45


def test_commits_grouped_per_repo_and_day_and_merge_commits_skipped():
    dev = _build("pm", "dev-1")  # product-service not in pm's projects
    assert not any(i["kind"] == "commits" for i in dev["items"])
    raw = make_raw()
    raw["stories"].append({"id": "PROD-1", "project_id": "PROD", "assignee": "dev-6", "status": "todo",
                           "title": "t", "comments": []})
    result = _build("dev", "dev-6", raw)
    commits = [i for i in result["items"] + result["earlier"] if i["kind"] == "commits"]
    assert len(commits) == 1 and commits[0]["line"] == "2 commits to product-service"


@pytest.mark.parametrize(
    "persona,dev_id,expected",
    [("arch", "dev-7", 100), ("dev", "dev-6", 88), ("exec", "dev-5", 68), ("pm", "dev-1", 58)],
)
def test_finding_scores_per_persona(persona, dev_id, expected):
    raw = make_raw()
    raw["runs"] = [{
        "id": "RUN-F", "project_id": "PAY", "linked_story": "PAY-109" if persona == "dev" else "PAY-105",
        "started_at": ago(hours=2), "status": "passed", "failed_stage": None, "linked_deployment": None,
        "security": {"totals": {"high": 1, "critical": 1, "medium": 0, "low": 0}},
    }]
    raw["incidents"], raw["deployments"], raw["activity"], raw["pulls"] = [], [], [], []
    for s in raw["stories"]:
        s["comments"] = []
    result = _build(persona, dev_id, raw)
    top = result["top"][0]
    assert top["id"] == "RUN-F" and top["kind"] == "finding"
    assert top["ts"] == ago(hours=2)  # ts = run.started_at
    assert top["line"] == "2 high/critical findings on " + ("PAY-109" if persona == "dev" else "PAY-105") + " at scan"
    ev = [e for e in sources.normalize(raw) if e.ref_id == "RUN-F"][0]
    ctx = rank.make_ctx(persona, dev_id, raw)
    assert rank.score(ctx, ev) == expected


def test_finding_service_score_for_developer_and_later_passing_run_does_not_close_it():
    dev = _ctx("dev", "dev-6")
    assert rank.score(dev, _ev("finding", project="PAY", story="PAY-1", story_assignee="dev-2")) == 70
    raw = make_raw()
    raw["runs"] = [
        {"id": "RUN-A", "project_id": "PAY", "linked_story": "PAY-105", "started_at": ago(hours=5),
         "status": "failed", "failed_stage": "dependency_scan", "linked_deployment": None,
         "security": {"totals": {"high": 2, "critical": 0}}},
        {"id": "RUN-B", "project_id": "PAY", "linked_story": "PAY-105", "started_at": ago(hours=1),
         "status": "passed", "failed_stage": None, "linked_deployment": None,
         "security": {"totals": {"high": 0, "critical": 0}}},
    ]
    events = [e for e in sources.normalize(raw) if e.system == "CI/CD"]
    assert [e.ref_id for e in events] == ["RUN-A"]
    assert events[0].head == "Pipeline failed with 2 high findings"  # failed run absorbed into one line


def test_future_dated_runs_are_excluded():
    result = _build("arch", "dev-7")
    assert "RUN-4" not in _ids(result, "items") + _ids(result, "earlier")


def test_malformed_upstream_records_are_skipped_not_fatal():
    raw = make_raw()
    raw["incidents"].append({"id": "INC-X", "severity": "P1", "opened_at": "not a date", "affected_service": 3})
    raw["deployments"].append({"id": None, "deployed_at": 5})
    raw["pages"].append({"id": "P", "title": None, "last_updated": "2026-13-45"})
    result = _build("exec", "dev-5", copy.deepcopy(raw))
    assert "INC-X" not in _ids(result, "items")
