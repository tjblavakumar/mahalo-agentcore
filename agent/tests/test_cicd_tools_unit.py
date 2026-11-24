"""Offline unit tests for the read-only CI/CD pipeline tools (no network)."""
from __future__ import annotations

import inspect

import pytest

from agent.approval import WRITE_TOOL_NAMES
from agent.strands_agent import READ_TOOLS, WRITE_TOOLS, _integrations_context
from agent.tools import cicd_tools
from common import tool_schemas

LABEL = "Seeded demo data. Not a live pipeline run."
RUN = {
    "id": "RUN-3001", "status": "failed", "linked_story": "PAY-109", "project_id": "PAY",
    "repo": "payment-service", "branch": None, "commit_sha": None, "trigger": "push",
    "anchor": "story", "started_at": "2026-08-23T15:00:00Z", "finished_at": "2026-08-23T15:06:40Z",
    "linked_deployment": None, "failed_stage": "dependency_scan",
    "failure_reason": "Dependency scan found 1 high-severity vulnerability (seeded example)",
    "stages": [{"name": "build", "status": "passed"}, {"name": "dependency_scan", "status": "failed"}],
    "tests": {"passed": 209, "failed": 0, "skipped": 6, "total": 215},
    "security": {
        "gate": "failed",
        "totals": {"critical": 0, "high": 1, "medium": 1, "low": 1},
        "findings": [{"id": "FND-3001-2", "severity": "high", "scanner": "dependency",
                      "title": "Crypto-signing library has a known vulnerability (seeded example)",
                      "location": "requirements.txt"}],
    },
}


class _Fake:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, base_url, token, endpoint="", params=None, method="GET", body=None, timeout=None):
        self.calls.append((endpoint, params, method))
        return self.routes[endpoint]


def test_runs_tool_calls_route_with_only_given_params_and_leads_with_label(monkeypatch):
    fake = _Fake({"/cicd/runs": {
        "label": LABEL, "ref_note": "Branch and commit shown are seeded sample values, not read from Gitea.",
        "match": {"matched_by": "story_id", "exact_ref_match": False},
        "runs": [RUN], "total": 1, "returned": 1,
    }})
    monkeypatch.setattr(cicd_tools, "make_request", fake)
    out = cicd_tools.cicd_get_pipeline_runs(story_id="PAY-109", limit=5)
    assert fake.calls == [("/cicd/runs", {"story_id": "PAY-109", "limit": 5}, "GET")]
    assert out.startswith(f"CI/CD: {LABEL}\n")
    assert "not read from Gitea" in out
    assert "RUN-3001 [failed] story=PAY-109" in out
    assert "Failed stage: dependency_scan" in out
    assert "Tests: 209 passed, 0 failed, 6 skipped (total 215)" in out
    assert "Security gate: failed | Open findings: critical 0, high 1, medium 1, low 1" in out
    assert "FND-3001-2 [high] dependency" in out


def test_runs_tool_empty_result_says_no_run_recorded(monkeypatch):
    fake = _Fake({"/cicd/runs": {
        "label": LABEL, "ref_note": "n", "runs": [], "total": 0,
        "message": "No pipeline run is recorded for branch=crypto.",
    }})
    monkeypatch.setattr(cicd_tools, "make_request", fake)
    out = cicd_tools.cicd_get_pipeline_runs(branch="crypto")
    assert "No pipeline run is recorded for branch=crypto." in out
    assert "RUN-" not in out


def test_tools_pass_error_through(monkeypatch):
    err = {"error": "Request failed with status 422: {\"detail\":\"story_id must look like PAY-109\"}"}
    monkeypatch.setattr(cicd_tools, "make_request", _Fake({
        "/cicd/runs": err, "/cicd/summary": err, "/cicd/stories/x/delivery": err,
    }))
    assert cicd_tools.cicd_get_pipeline_runs(story_id="x").startswith("Error: Request failed with status 422")
    assert cicd_tools.cicd_pipeline_summary().startswith("Error: ")
    assert cicd_tools.cicd_story_delivery_status("x").startswith("Error: ")


def test_summary_tool_formats_scope_and_projects(monkeypatch):
    project = {
        "project_id": "PAY", "service": "payment-service",
        "run_counts": {"total": 8}, "latest_run_counts": {"passed": 3, "failed": 1, "in_progress": 1},
        "open_findings": {"critical": 0, "high": 1, "medium": 2, "low": 1},
        "test_totals_latest_runs": {"passed": 900, "failed": 2, "skipped": 10},
        "deployments_without_pipeline_run": 5, "deployments_total": 10,
        "failing_stories": [{"story_id": "PAY-109", "run_id": "RUN-3001",
                             "failed_stage": "dependency_scan", "failure_reason": "x"}],
    }
    fake = _Fake({"/cicd/summary": {
        "label": LABEL, "scope": "Pipeline runs recorded for 24 of 50 deployments.",
        "projects": [project],
        "portfolio": {"projects_with_failing_pipelines": ["PAY"], "projects_with_open_findings": ["PAY"],
                      "projects_with_open_high_or_critical": ["PAY"]},
    }})
    monkeypatch.setattr(cicd_tools, "make_request", fake)
    out = cicd_tools.cicd_pipeline_summary(project_id="PAY")
    assert fake.calls == [("/cicd/summary", {"project_id": "PAY"}, "GET")]
    assert out.startswith(f"CI/CD: {LABEL}\n")
    assert "recorded for 24 of 50 deployments" in out
    assert "Deployments without a pipeline run: 5 of 10" in out
    assert "Failing: PAY-109 RUN-3001 at dependency_scan" in out


def test_delivery_tool_says_not_recorded_for_empty_sections(monkeypatch):
    fake = _Fake({"/cicd/stories/PAY-109/delivery": {
        "label": LABEL, "ref_note": "note", "latest_run": RUN,
        "run_history": [{"id": "RUN-3001", "status": "failed", "started_at": "2026-08-23T15:00:00Z"}],
        "deployments": [], "incidents": [], "no_deployment_recorded": True,
    }})
    monkeypatch.setattr(cicd_tools, "make_request", fake)
    out = cicd_tools.cicd_story_delivery_status("PAY-109")
    assert fake.calls == [("/cicd/stories/PAY-109/delivery", None, "GET")]
    assert "Latest pipeline run:" in out and "History: RUN-3001 (failed" in out
    assert "Deployments: none recorded" in out
    assert "Incidents: none recorded" in out


def test_delivery_tool_lists_deployments_and_incidents_with_links(monkeypatch):
    fake = _Fake({"/cicd/stories/PAY-105/delivery": {
        "label": LABEL, "ref_note": "n", "latest_run": None, "message": "No pipeline run is recorded for PAY-105.",
        "deployments": [{"id": "DEP-1002", "service": "payment-service", "version": "v3.1.2",
                         "environment": "production", "status": "success", "deployed_at": "d"}],
        "incidents": [{"id": "INC-2006", "severity": "P4", "title": "t", "status": "open",
                       "linked_via": "linked_deployment DEP-1008"}],
    }})
    monkeypatch.setattr(cicd_tools, "make_request", fake)
    out = cicd_tools.cicd_story_delivery_status("PAY-105")
    assert "No pipeline run is recorded for PAY-105." in out
    assert "DEP-1002: payment-service v3.1.2 -> production [success]" in out
    assert "INC-2006 [P4] t (open); linked_deployment DEP-1008" in out


def test_tools_are_read_only_and_registered():
    names = {t.tool_name for t in cicd_tools.CICD_TOOLS}
    assert names == {"cicd_get_pipeline_runs", "cicd_pipeline_summary", "cicd_story_delivery_status"}
    assert names <= {t.tool_name for t in READ_TOOLS}
    assert not names & {t.tool_name for t in WRITE_TOOLS}
    assert not any(n.startswith("cicd_") for n in WRITE_TOOL_NAMES)
    assert len(WRITE_TOOL_NAMES) == 6
    assert names <= set(tool_schemas.BY_NAME)
    assert all(tool_schemas.BY_NAME[n]["service"] == "servicenow" for n in names)
    assert all(tool_schemas.BY_NAME[n].get("method") == "GET" for n in names)
    assert not names & tool_schemas.WRITE_TOOL_NAMES


def test_tool_descriptions_name_cicd_and_seeded_data():
    for name in ("cicd_get_pipeline_runs", "cicd_pipeline_summary", "cicd_story_delivery_status"):
        desc = tool_schemas.BY_NAME[name]["description"]
        assert desc.startswith("CI/CD pipeline results (recorded demo data, read-only)")
        assert "NOT live" in desc
        doc = inspect.getdoc(
            next(t for t in cicd_tools.CICD_TOOLS if t.tool_name == name)._tool_func
        )
        assert doc.startswith("CI/CD pipeline results (recorded demo data, read-only)")


def test_integrations_context_lists_cicd():
    assert "CI/CD (recorded pipeline results, seeded demo data" in _integrations_context()
