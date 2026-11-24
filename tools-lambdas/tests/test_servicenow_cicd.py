"""CI/CD pipeline results (read-only demo data) in the ServiceNow mock.

Seed-consistency and query-logic tests are pure (no AWS); the route, reset and
Gateway-adapter tests run through ``lambda_handler`` under moto.
"""
from __future__ import annotations

import importlib
import json
import re
from datetime import datetime

import pytest

from common import seed_dates
from github import seed_data as github_seed
from jira import seed_data as jira_seed
from servicenow import cicd, cicd_seed, routes
from servicenow import seed_data as snow_seed
from tests.conftest import body_of, make_event

TOKEN = "mock-servicenow-token-12345"
_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _seeded(pk):
    return [item["record"] for item in routes.seed_items() if item["pk"] == pk]


@pytest.fixture(scope="module")
def deployments():
    return _seeded(routes.PK_DEPLOYMENT)


@pytest.fixture(scope="module")
def incidents():
    return _seeded(routes.PK_INCIDENT)


@pytest.fixture(scope="module")
def runs(deployments):
    return cicd_seed.build_runs(deployments)


@pytest.fixture(scope="module")
def by_id(runs):
    return {r["id"]: r for r in runs}


JIRA_IDS = {s["id"] for s in jira_seed.STORIES}


# --------------------------------------------------------------------------- #
# Seed consistency
# --------------------------------------------------------------------------- #
def test_known_story_ids_match_the_seeds(deployments):
    linked = {d["linked_story"] for d in deployments if d["linked_story"] in JIRA_IDS}
    assert linked == set(cicd_seed.KNOWN_STORY_IDS)
    assert sum(1 for d in deployments if d["linked_story"] in JIRA_IDS) == 24


def test_run_counts_and_ids(runs, deployments):
    generated = [r for r in runs if r["linked_deployment"]]
    assert len(generated) == 24
    assert len(runs) == 33
    assert len({r["id"] for r in runs}) == 33
    for run in generated:
        assert run["id"] == f"RUN-{3100 + int(run['linked_deployment'].split('-')[1]) - 1000}"
    assert {r["id"] for r in runs if not r["linked_deployment"]} == {
        f"RUN-30{n:02d}" for n in range(1, 10)
    }


def test_every_run_links_to_real_jira_story_and_matching_deployment(runs, deployments):
    dep_by_id = {d["id"]: d for d in deployments}
    for run in runs:
        assert run["linked_story"] in JIRA_IDS, run["id"]
        assert run["system"] == "CI/CD" and run["data_origin"] == "seeded"
        assert run["linked_pr"] is None
        assert run["service"] == run["repo"] == cicd_seed.PROJECT_SERVICE[run["project_id"]]
        assert run["linked_story"].startswith(run["project_id"] + "-")
        dep_id = run["linked_deployment"]
        if not dep_id:
            continue
        dep = dep_by_id[dep_id]
        assert dep["service"] == run["service"]
        assert dep["linked_story"] == run["linked_story"]
        deploy = run["stages"][-1]
        assert deploy["environment"] == dep["environment"]
        assert deploy["status"] == {
            "success": "passed", "failed": "failed",
            "rolled_back": "rolled_back", "in_progress": "in_progress",
        }[dep["status"]]
        assert run["status"] == {
            "success": "passed", "failed": "failed",
            "rolled_back": "failed", "in_progress": "in_progress",
        }[dep["status"]]


def test_generated_runs_end_at_the_deployment_time(runs, deployments):
    dep_by_id = {d["id"]: d for d in deployments}
    for run in runs:
        dep_id = run["linked_deployment"]
        if not dep_id:
            continue
        dep = dep_by_id[dep_id]
        started = datetime.strptime(run["started_at"], _FMT)
        deployed = datetime.strptime(dep["deployed_at"], _FMT)
        assert (deployed - started).total_seconds() == dep["duration_seconds"]
        assert sum(s["duration_seconds"] for s in run["stages"]) == dep["duration_seconds"]
        if dep["status"] == "in_progress":
            assert run["finished_at"] is None
        else:
            assert run["finished_at"] == dep["deployed_at"]
        assert run["branch"] == ("main" if dep["environment"] == "production" else run["branch"])
        if dep["environment"] == "staging":
            assert run["branch"].startswith(f"feature/{run['linked_story']}-")


def test_branch_shas_and_triggers(runs):
    for run in runs:
        if run["id"] == "RUN-3001":
            assert run["commit_sha"] is None and run["branch"] is None
            continue
        assert re.fullmatch(r"[0-9a-f]{7}", run["commit_sha"])
        assert run["trigger"] == ("merge" if run["linked_deployment"] else "push")
        if not run["linked_deployment"]:
            assert run["branch"].startswith(f"feature/{run['linked_story']}-")


def test_authored_branches_exist_in_github_seed(runs):
    seed_branches = {b["name"] for bs in github_seed.BRANCHES.values() for b in bs}
    assert set(cicd_seed.FEATURE_BRANCHES.values()) <= seed_branches
    for run in runs:
        if not run["linked_deployment"] and run["branch"]:
            assert run["branch"] in seed_branches


def test_stage_order_and_derived_values(runs):
    for run in runs:
        stages = run["stages"]
        assert [s["name"] for s in stages] == list(cicd_seed.STAGE_ORDER)
        statuses = [s["status"] for s in stages]
        if "failed" in statuses or "rolled_back" in statuses:
            assert run["status"] == "failed"
        elif "in_progress" in statuses:
            assert run["status"] == "in_progress"
        else:
            assert run["status"] == "passed"
        bad = [s["name"] for s in stages if s["status"] in ("failed", "rolled_back")]
        assert run["failed_stage"] == (bad[0] if bad else None)
        finished = [s for s in stages if "tests" in s and s["status"] in ("passed", "failed")]
        for key in ("passed", "failed", "skipped"):
            assert run["tests"][key] == sum(s["tests"][key] for s in finished)
        assert run["tests"]["total"] == sum(run["tests"][k] for k in ("passed", "failed", "skipped"))
        # stages after the first failed / in-progress stage did not run
        blocked = False
        for stage in stages:
            if blocked:
                assert stage["status"] in ("not_run", "not_applicable"), run["id"]
            if stage["status"] in ("failed", "rolled_back", "in_progress"):
                blocked = True


def test_scan_stage_status_follows_open_findings(runs):
    for run in runs:
        sec = run["security"]
        for stage in run["stages"]:
            if stage["name"] not in ("sast", "dependency_scan"):
                continue
            mine = [
                f for f in sec["findings"]
                if {"sast": "sast", "dependency": "dependency_scan"}[f["scanner"]] == stage["name"]
            ]
            for sev in cicd_seed.SEVERITIES:
                assert stage["findings"][sev] == sum(1 for f in mine if f["severity"] == sev)
            if stage["status"] in ("passed", "failed"):
                serious = stage["findings"]["critical"] + stage["findings"]["high"]
                assert (stage["status"] == "failed") == (serious > 0), run["id"]
            else:
                assert not mine and sum(stage["findings"].values()) == 0
            assert sec[stage["name"]]["status"] == stage["status"]
        for sev in cicd_seed.SEVERITIES:
            assert sec["totals"][sev] == sum(1 for f in sec["findings"] if f["severity"] == sev)
        if sec["gate"] == "failed":
            assert sec["totals"]["critical"] + sec["totals"]["high"] > 0
        if sec["gate"] == "passed":
            assert sec["totals"]["critical"] + sec["totals"]["high"] == 0
        assert all(f["status"] == "open" for f in sec["findings"])
        for f in sec["findings"]:
            assert f["title"].endswith("(seeded example)")
            assert not re.search(r"CVE-\d", json.dumps(f))
            assert f["id"].startswith(f"FND-{run['id'].split('-')[1]}-")


def test_failure_reason_rules(runs, deployments):
    notes = {d["id"]: d["notes"] for d in deployments}
    for run in runs:
        if run["status"] == "failed":
            assert run["failure_reason"], run["id"]
        else:
            assert run["failure_reason"] is None, run["id"]
        if run["failure_reason"]:
            assert "release for" not in run["failure_reason"]
    assert runs and {r["id"]: r for r in runs}["RUN-3103"]["failure_reason"] == notes["DEP-1003"]
    assert {r["id"]: r for r in runs}["RUN-3104"]["failure_reason"] == notes["DEP-1004"]
    for dep_id in ("DEP-1010", "DEP-1016"):
        run = {r["id"]: r for r in runs}[f"RUN-{3100 + int(dep_id[4:]) - 1000}"]
        assert run["failure_reason"].endswith(f"(see ServiceNow deployment {dep_id})")


def test_in_progress_run_has_no_totals_beyond_finished_stages(by_id):
    run = by_id["RUN-3009"]
    assert run["status"] == "in_progress" and run["finished_at"] is None
    assert run["stages"][2]["status"] == "in_progress"
    assert [s["status"] for s in run["stages"][3:]] == ["not_run", "not_run", "not_applicable"]
    assert run["tests"] == {"passed": 150, "failed": 0, "skipped": 3, "total": 153}
    assert run["security"]["gate"] == "not_run"


def test_pay_109_run(by_id):
    run = by_id["RUN-3001"]
    assert run["anchor"] == "story" and run["branch"] is None and run["commit_sha"] is None
    assert run["status"] == "failed" and run["failed_stage"] == "dependency_scan"
    assert run["stages"][-1]["status"] == "not_run"
    assert run["tests"] == {"passed": 209, "failed": 0, "skipped": 6, "total": 215}
    assert run["security"]["totals"] == {"critical": 0, "high": 1, "medium": 1, "low": 1}
    assert run["security"]["gate"] == "failed"
    assert run["linked_deployment"] is None


def test_authored_run_outcomes(by_id):
    assert by_id["RUN-3002"]["failed_stage"] == "integration_tests"
    assert by_id["RUN-3002"]["stages"][2]["tests"] == {"passed": 33, "failed": 2, "skipped": 1}
    assert by_id["RUN-3003"]["status"] == "passed"
    assert by_id["RUN-3003"]["security"]["totals"]["medium"] == 1
    assert by_id["RUN-3004"]["failed_stage"] == "unit_tests"
    assert by_id["RUN-3004"]["stages"][1]["tests"]["failed"] == 3
    assert by_id["RUN-3005"]["failed_stage"] == "sast"
    assert by_id["RUN-3006"]["status"] == "passed" and not by_id["RUN-3006"]["security"]["findings"]
    assert by_id["RUN-3007"]["failed_stage"] == "dependency_scan"
    assert by_id["RUN-3008"]["status"] == "passed"
    assert by_id["RUN-3008"]["security"]["totals"]["low"] == 1
    for rid in ("RUN-3002", "RUN-3003", "RUN-3004", "RUN-3005", "RUN-3006", "RUN-3007", "RUN-3008", "RUN-3009"):
        assert by_id[rid]["stages"][-1]["status"] in ("not_applicable",)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T1[5-9]:00:00Z", by_id[rid]["started_at"])


def test_every_project_has_failure_and_open_finding_in_latest_runs(runs):
    latest = cicd._latest_per_story(runs)
    for project in cicd_seed.PROJECTS:
        mine = [r for r in latest if r["project_id"] == project]
        assert any(r["status"] == "failed" for r in mine), project
        assert any(r["security"]["findings"] for r in mine), project
    serious = {
        r["project_id"] for r in latest
        if r["security"]["totals"]["high"] or r["security"]["totals"]["critical"]
    }
    assert {"PAY", "AUTH", "ORD"} <= serious


def test_authored_runs_start_after_deployment_linked_runs_of_same_story(runs):
    for run in runs:
        if run["linked_deployment"]:
            continue
        for other in runs:
            if other["linked_deployment"] and other["linked_story"] == run["linked_story"]:
                assert run["started_at"] > (other["finished_at"] or other["started_at"]), (
                    run["id"], other["id"],
                )


def test_latest_run_per_story_is_the_newest(runs):
    latest = {r["linked_story"]: r for r in cicd._latest_per_story(runs)}
    assert latest["PAY-105"]["id"] == "RUN-3003"
    assert latest["PAY-109"]["id"] == "RUN-3001"


def test_dates_follow_the_live_shift_and_keep_the_weekday(deployments):
    days = seed_dates.compute_shift_days(seed_dates.today_utc())
    assert cicd_seed.shift_days_from(deployments) == days
    assert days % 7 == 0
    shifted = cicd_seed.build_runs(deployments)
    unshifted = cicd_seed.build_runs(
        seed_dates.shift_records(deployments, -days, ("deployed_at",))
    )
    for a, b in zip(sorted(shifted, key=lambda r: r["id"]), sorted(unshifted, key=lambda r: r["id"])):
        assert a["id"] == b["id"]
        sa = datetime.strptime(a["started_at"], _FMT)
        sb = datetime.strptime(b["started_at"], _FMT)
        assert (sa - sb).days == days
        assert sa.weekday() == sb.weekday()


def test_shift_falls_back_without_dep_1001(deployments):
    rest = [d for d in deployments if d["id"] != "DEP-1001"]
    assert cicd_seed.shift_days_from(rest) == seed_dates.compute_shift_days(seed_dates.today_utc())


def test_cicd_seed_does_not_import_routes():
    source = open(cicd_seed.__file__, encoding="utf-8").read()
    assert not re.search(r"^\s*(from \. import routes|from \.routes|import routes)", source, re.M)


# --------------------------------------------------------------------------- #
# Story id extraction
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,expected",
    [
        ("feature/PAY-109-crypto", "PAY-109"),
        ("feature_pay-109", "PAY-109"),
        ("PAY-109", "PAY-109"),
        ("fix-12-PAY-109", "PAY-109"),
        ("feature/AUTH-306-saml-sso", "AUTH-306"),
        ("PAY-1090-x", "PAY-1090"),
        ("PAY-10", "PAY-10"),
        ("PAY-123456", None),
        ("feature/ABC-1-x", None),
        ("crypto-payments", None),
        ("xPAY-109", None),
        ("PAY-109-and-CART-201", "PAY-109"),
        ("", None),
    ],
)
def test_extract_story_id(text, expected):
    assert cicd.extract_story_id(text) == expected


# --------------------------------------------------------------------------- #
# Query logic
# --------------------------------------------------------------------------- #
def test_story_id_resolves_first(runs):
    body = cicd.query_runs(runs, {"story_id": "PAY-109"})
    assert [r["id"] for r in body["runs"]] == ["RUN-3001"]
    assert body["match"] == {"matched_by": "story_id", "exact_ref_match": False, "ref_is_seeded": True}
    assert body["label"] == "Seeded demo data. Not a live pipeline run."
    assert body["system"] == "CI/CD" and body["data_origin"] == "seeded"
    assert cicd.SEEDED_REF_NOTE in body["ref_note"]
    assert "sample run recorded for story PAY-109" in body["ref_note"]


def test_unrecorded_live_branch_returns_story_run_never_exact(runs):
    body = cicd.query_runs(runs, {"branch": "feature/PAY-109-crypto-payments"})
    assert [r["id"] for r in body["runs"]] == ["RUN-3001"]
    assert body["match"]["matched_by"] == "story_id_in_branch"
    assert body["match"]["exact_ref_match"] is False
    assert body["runs"][0]["exact_ref_match"] is False
    assert "No run is recorded for branch feature/PAY-109-crypto-payments (sha unknown)" in body["ref_note"]
    assert "not produced by the branch or commit you asked about" in body["ref_note"]


def test_branch_without_story_id_is_empty_not_simulated(runs):
    body = cicd.query_runs(runs, {"branch": "crypto-payments"})
    assert body["runs"] == [] and body["total"] == 0
    assert body["message"].startswith("No pipeline run is recorded for")
    assert cicd.SEEDED_REF_NOTE in body["ref_note"]


def test_exact_branch_hit_on_commit_anchored_run(runs):
    body = cicd.query_runs(runs, {"branch": "feature/PAY-105-google-pay"})
    assert [r["id"] for r in body["runs"]] == ["RUN-3003", "RUN-3002"]
    assert body["match"]["matched_by"] == "branch_exact"
    assert body["match"]["ref_is_seeded"] is True
    assert body["match"]["exact_ref_match"] is True
    # Even an exact seeded match is never presented as a Gitea commit.
    assert cicd.SEEDED_REF_NOTE in body["ref_note"]
    assert "No run is recorded for branch" not in body["ref_note"]


def test_branch_main_matches_production_runs_but_stays_seeded(runs):
    body = cicd.query_runs(runs, {"branch": "main", "limit": 50})
    assert body["total"] > 1
    assert all(r["branch"] == "main" for r in body["runs"])
    assert body["match"]["ref_is_seeded"] is True
    assert cicd.SEEDED_REF_NOTE in body["ref_note"]


def test_commit_sha_prefix_match_and_ignored_with_story_or_branch(runs, by_id):
    sha = by_id["RUN-3002"]["commit_sha"]
    body = cicd.query_runs(runs, {"commit": sha})
    assert [r["id"] for r in body["runs"]] == ["RUN-3002"]
    assert body["match"]["matched_by"] == "commit_sha" and body["match"]["exact_ref_match"] is True
    assert cicd.SEEDED_REF_NOTE in body["ref_note"]
    prefix = cicd.query_runs(runs, {"commit": sha[:7]})
    assert [r["id"] for r in prefix["runs"]] == ["RUN-3002"]
    # A live sha that cannot match must not wipe out a correct story match.
    live = cicd.query_runs(runs, {"story_id": "PAY-109", "commit": "abcdef1"})
    assert [r["id"] for r in live["runs"]] == ["RUN-3001"]
    assert "No run is recorded for commit abcdef1." in live["ref_note"]
    alone = cicd.query_runs(runs, {"commit": "abcdef1"})
    assert alone["runs"] == [] and "No pipeline run is recorded" in alone["message"]


def test_filters_and_limit_apply_after_resolution(runs):
    body = cicd.query_runs(runs, {"story_id": "PAY-105", "status": "failed"})
    assert [r["id"] for r in body["runs"]] == ["RUN-3002"]
    assert all(r["linked_story"] == "PAY-105" and r["status"] == "failed" for r in body["runs"])
    mismatch = cicd.query_runs(runs, {"story_id": "PAY-105", "project_id": "CART"})
    assert mismatch["runs"] == [] and "No pipeline run is recorded" in mismatch["message"]
    limited = cicd.query_runs(runs, {"limit": 3})
    assert len(limited["runs"]) == 3 and limited["total"] == 33 and limited["returned"] == 3
    dates = [r["started_at"] for r in cicd.query_runs(runs, {"limit": 50})["runs"]]
    assert dates == sorted(dates, reverse=True)
    assert cicd.query_runs(runs, {"repo": "no-such-repo"})["runs"] == []
    assert all(
        r["repo"] == "cart-service" for r in cicd.query_runs(runs, {"repo": "cart-service", "limit": 50})["runs"]
    )


def test_conflicting_story_and_branch_names_the_conflict(runs):
    body = cicd.query_runs(runs, {"story_id": "PAY-109", "branch": "feature/AUTH-306-saml-sso"})
    assert [r["id"] for r in body["runs"]] == ["RUN-3001"]
    assert "Branch feature/AUTH-306-saml-sso belongs to story AUTH-306, not PAY-109." in body["ref_note"]


# --------------------------------------------------------------------------- #
# Summary and delivery
# --------------------------------------------------------------------------- #
def test_summary_matches_independent_recomputation(runs, deployments):
    body = cicd.summarize(runs, deployments)
    latest = {}
    for r in sorted(runs, key=lambda r: r["started_at"]):
        latest[r["linked_story"]] = r
    assert [p["project_id"] for p in body["projects"]] == list(cicd_seed.PROJECTS)
    for p in body["projects"]:
        pid = p["project_id"]
        mine = [r for r in runs if r["project_id"] == pid]
        assert p["run_counts"]["total"] == len(mine)
        for status in ("passed", "failed", "in_progress"):
            assert p["run_counts"][status] == sum(1 for r in mine if r["status"] == status)
        lat = [r for r in latest.values() if r["project_id"] == pid]
        assert {f["story_id"] for f in p["failing_stories"]} == {
            r["linked_story"] for r in lat if r["status"] == "failed"
        }
        for sev in cicd_seed.SEVERITIES:
            assert p["open_findings"][sev] == sum(r["security"]["totals"][sev] for r in lat)
        assert p["test_totals_latest_runs"]["passed"] == sum(r["tests"]["passed"] for r in lat)
        service = cicd_seed.PROJECT_SERVICE[pid]
        deps = [d for d in snow_seed.DEPLOYMENTS if d["service"] == service]
        with_run = {r["linked_deployment"] for r in mine if r["linked_deployment"]}
        assert p["deployments_total"] == len(deps)
        assert p["deployments_without_pipeline_run"] == len(deps) - len(with_run)
    assert sum(p["deployments_without_pipeline_run"] for p in body["projects"]) == 50 - 24
    assert "recorded for 24 of 50 deployments" in body["scope"]
    assert set(body["portfolio"]["projects_with_open_high_or_critical"]) >= {"PAY", "AUTH", "ORD"}
    assert set(body["portfolio"]["projects_with_failing_pipelines"]) == set(cicd_seed.PROJECTS)
    assert body["label"] == "Seeded demo data. Not a live pipeline run."


def test_summary_single_project(runs, deployments):
    body = cicd.summarize(runs, deployments, "PAY")
    assert [p["project_id"] for p in body["projects"]] == ["PAY"]
    assert body["portfolio"]["projects_with_open_findings"] == ["PAY"]


def test_delivery_pay_109_has_no_deployment_or_incident(runs, deployments, incidents):
    body = cicd.delivery(runs, deployments, incidents, "PAY-109")
    assert body["latest_run"]["id"] == "RUN-3001"
    assert body["deployments"] == [] and body["incidents"] == []
    assert body["no_deployment_recorded"] is True and body["no_run_recorded"] is False
    assert "sample run recorded for story PAY-109" in body["ref_note"]


def test_delivery_pay_105_links_incidents_only_through_deployments(runs, deployments, incidents):
    body = cicd.delivery(runs, deployments, incidents, "PAY-105")
    assert {d["id"] for d in body["deployments"]} == {"DEP-1002", "DEP-1008"}
    expected = {i["id"] for i in incidents if i.get("linked_deployment") in {"DEP-1002", "DEP-1008"}}
    assert {i["id"] for i in body["incidents"]} == expected
    assert all(i["linked_via"] == f"linked_deployment {i['linked_deployment']}" for i in body["incidents"])
    assert body["latest_run"]["id"] == "RUN-3003"
    assert [h["id"] for h in body["run_history"]][:2] == ["RUN-3003", "RUN-3002"]


def test_delivery_unknown_story_says_nothing_recorded(runs, deployments, incidents):
    body = cicd.delivery(runs, deployments, incidents, "PAY-999")
    assert body["latest_run"] is None and body["no_run_recorded"] is True
    assert "No pipeline run is recorded for PAY-999" in body["message"]


# --------------------------------------------------------------------------- #
# Routes (moto)
# --------------------------------------------------------------------------- #
@pytest.fixture
def handler(dynamo_table, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", dynamo_table)
    monkeypatch.setenv("MOCK_SERVICENOW_TOKEN", TOKEN)
    import servicenow.handler as h

    importlib.reload(h)
    h._store = None
    h._router = None
    return h


def invoke(handler, method, path, **kwargs):
    return handler.lambda_handler(make_event(method, path, **kwargs), None)


def test_routes_require_token(handler):
    for path in ("/cicd/runs", "/cicd/summary", "/cicd/stories/PAY-109/delivery"):
        resp = invoke(handler, "GET", path)
        assert resp["statusCode"] == 401
        assert body_of(resp)["detail"] == "Invalid API token"


def test_runs_route_for_pay_109_and_live_branch(handler):
    resp = invoke(handler, "GET", "/cicd/runs", query={"story_id": "pay-109"}, token=TOKEN)
    assert resp["statusCode"] == 200
    body = body_of(resp)
    assert [r["id"] for r in body["runs"]] == ["RUN-3001"]
    assert body["runs"][0]["tests"]["total"] == 215
    live = body_of(
        invoke(handler, "GET", "/cicd/runs",
               query={"branch": "feature/PAY-109-crypto-payments"}, token=TOKEN)
    )
    assert live["runs"][0]["id"] == "RUN-3001"
    assert live["match"]["exact_ref_match"] is False
    assert live["ref_note"]


def test_runs_route_branch_main_and_seeded_sha(handler):
    main = body_of(invoke(handler, "GET", "/cicd/runs", query={"branch": "main"}, token=TOKEN))
    assert main["total"] > 1 and main["match"]["ref_is_seeded"] is True
    sha = main["runs"][0]["commit_sha"]
    by_sha = body_of(invoke(handler, "GET", "/cicd/runs", query={"commit": sha}, token=TOKEN))
    assert by_sha["runs"][0]["commit_sha"] == sha
    assert cicd.SEEDED_REF_NOTE in by_sha["ref_note"]


def test_runs_shift_matches_the_stored_deployments(handler):
    body = body_of(invoke(handler, "GET", "/cicd/runs", query={"story_id": "PAY-105"}, token=TOKEN))
    deps = body_of(invoke(handler, "GET", "/deployments", token=TOKEN))["deployments"]
    dep = next(d for d in deps if d["id"] == "DEP-1008")
    run8 = next(r for r in body["runs"] if r["linked_deployment"] == "DEP-1008")
    assert run8["finished_at"] is None  # DEP-1008 is in progress
    assert (
        datetime.strptime(dep["deployed_at"], _FMT) - datetime.strptime(run8["started_at"], _FMT)
    ).total_seconds() == dep["duration_seconds"]


@pytest.mark.parametrize(
    "query",
    [
        {"story_id": "bad"},
        {"story_id": "PAY-123456"},
        {"project_id": "XYZ"},
        {"status": "weird"},
        {"limit": "0"},
        {"limit": "51"},
        {"limit": "abc"},
        {"commit": "xyz1234"},
        {"commit": "abc12"},
        {"branch": "b" * 201},
        {"repo": "r" * 65},
    ],
)
def test_runs_validation_422(handler, query):
    resp = invoke(handler, "GET", "/cicd/runs", query=query, token=TOKEN)
    assert resp["statusCode"] == 422
    assert "detail" in body_of(resp)


def test_summary_and_delivery_routes_and_validation(handler):
    assert invoke(handler, "GET", "/cicd/summary", query={"project_id": "ZZ"}, token=TOKEN)["statusCode"] == 422
    body = body_of(invoke(handler, "GET", "/cicd/summary", query={"project_id": "pay"}, token=TOKEN))
    assert [p["project_id"] for p in body["projects"]] == ["PAY"]
    resp = invoke(handler, "GET", "/cicd/stories/PAY-109/delivery", token=TOKEN)
    assert resp["statusCode"] == 200
    assert body_of(resp)["no_deployment_recorded"] is True
    assert invoke(handler, "GET", "/cicd/stories/nonsense/delivery", token=TOKEN)["statusCode"] == 422
    pay105 = body_of(invoke(handler, "GET", "/cicd/stories/PAY-105/delivery", token=TOKEN))
    assert {d["id"] for d in pay105["deployments"]} == {"DEP-1002", "DEP-1008"}


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_cicd_routes_are_read_only(handler, method):
    for path in ("/cicd/runs", "/cicd/summary", "/cicd/stories/PAY-109/delivery"):
        resp = invoke(handler, method, path, token=TOKEN, body={})
        assert resp["statusCode"] == 404


def test_reset_counts_unchanged_and_nothing_stored(handler, dynamo_table):
    import boto3

    resp = invoke(handler, "POST", "/admin/reset", token=TOKEN)
    counts = body_of(resp)["counts"]
    assert counts == {"SERVICE": 5, "DEPLOYMENT": 50, "INCIDENT": 50}
    items = boto3.client("dynamodb", region_name="us-east-1").scan(TableName=dynamo_table)["Items"]
    assert not any("CICD" in i["pk"]["S"].upper() for i in items)
    assert not any(i["sk"]["S"].startswith("RUN-") for i in items)


class _Ctx:
    def __init__(self, name):
        self.client_context = type("C", (), {"custom": {"bedrockAgentCoreToolName": name}})()


def test_gateway_adapter_matches_route_and_maps_422(handler):
    route = body_of(invoke(handler, "GET", "/cicd/runs", query={"story_id": "PAY-109"}, token=TOKEN))
    via = handler.lambda_handler(
        {"story_id": "PAY-109"}, _Ctx("mock-servicenow___cicd_get_pipeline_runs")
    )
    assert via == route
    bad = handler.lambda_handler(
        {"story_id": "nope"}, _Ctx("mock-servicenow___cicd_get_pipeline_runs")
    )
    assert bad["error"].startswith("Request failed with status 422:")
    delivery = handler.lambda_handler(
        {"story_id": "PAY-109"}, _Ctx("mock-servicenow___cicd_story_delivery_status")
    )
    assert delivery["story_id"] == "PAY-109"
    summary = handler.lambda_handler({}, _Ctx("mock-servicenow___cicd_pipeline_summary"))
    assert len(summary["projects"]) == 5
    limited = handler.lambda_handler(
        {"project_id": "PAY", "limit": 2}, _Ctx("mock-servicenow___cicd_get_pipeline_runs")
    )
    assert len(limited["runs"]) == 2
