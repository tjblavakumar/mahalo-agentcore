"""Strands read-only tools for CI/CD pipeline results (recorded demo data).

The data is served by the ServiceNow mock under ``/cicd/*``. Nothing here runs a
pipeline or writes anything. Every output starts with the data label so the
answer can say the results are seeded, not a live pipeline run.
"""

from __future__ import annotations

from typing import Optional

from strands import tool

from agent.config import settings
from agent.tools.http import make_request

_FALLBACK_LABEL = "Seeded demo data. Not a live pipeline run."


def _cicd_request(endpoint: str, params: Optional[dict] = None) -> dict:
    """Make a GET request to the CI/CD routes of the ServiceNow mock."""
    return make_request(
        settings.servicenow_url, settings.servicenow_token, endpoint=endpoint, params=params
    )


def _head(data: dict) -> str:
    return f"CI/CD: {data.get('label', _FALLBACK_LABEL)}\n"


def _sev(counts: dict) -> str:
    return ", ".join(f"{k} {counts.get(k, 0)}" for k in ("critical", "high", "medium", "low"))


def _render_run(run: dict) -> str:
    tests = run.get("tests", {})
    security = run.get("security", {})
    out = (
        f"\n{run['id']} [{run['status']}] story={run['linked_story']} "
        f"project={run['project_id']} repo={run['repo']}\n"
        f"   Branch: {run.get('branch') or 'n/a'} | Commit: {run.get('commit_sha') or 'n/a'} "
        f"| Trigger: {run.get('trigger')} | Anchor: {run.get('anchor')}\n"
        f"   Started: {run.get('started_at')} | Finished: {run.get('finished_at') or 'running'}\n"
    )
    if run.get("linked_deployment"):
        out += f"   Linked deployment: {run['linked_deployment']}\n"
    if run.get("failed_stage"):
        out += f"   Failed stage: {run['failed_stage']} - {run.get('failure_reason')}\n"
    out += "   Stages: " + ", ".join(f"{s['name']}={s['status']}" for s in run.get("stages", [])) + "\n"
    out += (
        f"   Tests: {tests.get('passed', 0)} passed, {tests.get('failed', 0)} failed, "
        f"{tests.get('skipped', 0)} skipped (total {tests.get('total', 0)})\n"
        f"   Security gate: {security.get('gate')} | Open findings: "
        f"{_sev(security.get('totals', {}))}\n"
    )
    for f in security.get("findings", []):
        out += f"     - {f['id']} [{f['severity']}] {f['scanner']}: {f['title']} ({f['location']})\n"
    return out


@tool
def cicd_get_pipeline_runs(
    story_id: Optional[str] = None,
    project_id: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
    commit: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = None,
) -> str:
    """CI/CD pipeline results (recorded demo data, read-only). Seeded sample runs, NOT live
    pipeline runs: no pipeline executed for any commit made through Mahalo. List recorded runs
    with test counts and security-scan findings (SAST, dependency scan).
    Pass story_id (e.g. PAY-109) when known; it is the most reliable key.
    Other filters: project_id (PAY|CART|AUTH|PROD|ORD), repo, branch, status
    (passed|failed|in_progress), limit (1-50, default 10).
    Use commit only for a sha already shown by this tool. Quote ref_note in the answer."""
    params = {
        k: v
        for k, v in (
            ("story_id", story_id), ("project_id", project_id), ("repo", repo),
            ("branch", branch), ("commit", commit), ("status", status), ("limit", limit),
        )
        if v not in (None, "")
    }
    data = _cicd_request("/cicd/runs", params)
    if "error" in data:
        return f"Error: {data['error']}"
    out = _head(data)
    out += f"Note: {data.get('ref_note', '')}\n"
    if data.get("message"):
        out += f"{data['message']}\n"
        return out
    match = data.get("match", {})
    out += (
        f"Pipeline runs ({data.get('returned', 0)} of {data.get('total', 0)} shown, "
        f"matched by {match.get('matched_by')}, exact ref match: {match.get('exact_ref_match')}):\n"
    )
    for run in data.get("runs", []):
        out += _render_run(run)
    return out


@tool
def cicd_pipeline_summary(project_id: Optional[str] = None) -> str:
    """CI/CD pipeline results (recorded demo data, read-only). Seeded sample runs, NOT live
    pipeline runs. Roll-up per project (or one project_id): run counts, failing stories, open
    security findings by severity, test totals of the latest runs, and
    deployments_without_pipeline_run. Use for 'which projects have failing pipelines or open
    security findings?'."""
    params = {"project_id": project_id} if project_id else {}
    data = _cicd_request("/cicd/summary", params)
    if "error" in data:
        return f"Error: {data['error']}"
    out = _head(data) + f"{data.get('scope', '')}\n"
    for p in data.get("projects", []):
        lc = p.get("latest_run_counts", {})
        out += (
            f"\n- {p['project_id']} ({p['service']}): {p['run_counts']['total']} runs "
            f"(latest per story: {lc.get('passed', 0)} passed, {lc.get('failed', 0)} failed, "
            f"{lc.get('in_progress', 0)} in progress)\n"
            f"  Open findings (latest runs): {_sev(p['open_findings'])}\n"
            f"  Tests (latest runs): {p['test_totals_latest_runs']['passed']} passed, "
            f"{p['test_totals_latest_runs']['failed']} failed, "
            f"{p['test_totals_latest_runs']['skipped']} skipped\n"
            f"  Deployments without a pipeline run: {p['deployments_without_pipeline_run']} "
            f"of {p['deployments_total']}\n"
        )
        for f in p.get("failing_stories", []):
            out += f"  Failing: {f['story_id']} {f['run_id']} at {f['failed_stage']}: {f['failure_reason']}\n"
    port = data.get("portfolio", {})
    out += (
        f"\nPortfolio: failing pipelines in {port.get('projects_with_failing_pipelines')}; "
        f"open findings in {port.get('projects_with_open_findings')}; "
        f"open high or critical in {port.get('projects_with_open_high_or_critical')}\n"
    )
    return out


@tool
def cicd_story_delivery_status(story_id: str) -> str:
    """CI/CD pipeline results (recorded demo data, read-only). Seeded sample runs, NOT live
    pipeline runs. For one story_id (e.g. PAY-109): the latest pipeline run and history, the
    ServiceNow deployments linked to the story, and incidents reachable only through those
    deployments. Empty lists mean 'not recorded'."""
    data = _cicd_request(f"/cicd/stories/{story_id}/delivery")
    if "error" in data:
        return f"Error: {data['error']}"
    out = _head(data) + f"Note: {data.get('ref_note', '')}\n"
    latest = data.get("latest_run")
    if latest:
        out += "Latest pipeline run:" + _render_run(latest)
        out += "History: " + ", ".join(
            f"{h['id']} ({h['status']}, {h['started_at']})" for h in data.get("run_history", [])
        ) + "\n"
    else:
        out += f"{data.get('message', 'No pipeline run is recorded.')}\n"
    deployments = data.get("deployments", [])
    if deployments:
        out += "Deployments (ServiceNow):\n"
        for d in deployments:
            out += (
                f"  - {d['id']}: {d['service']} {d.get('version', '')} -> {d['environment']} "
                f"[{d['status']}] at {d.get('deployed_at', 'n/a')}\n"
            )
    else:
        out += "Deployments: none recorded (no_deployment_recorded).\n"
    incidents = data.get("incidents", [])
    if incidents:
        out += "Incidents (linked through those deployments):\n"
        for i in incidents:
            out += (
                f"  - {i['id']} [{i['severity']}] {i['title']} ({i['status']}); "
                f"{i['linked_via']}\n"
            )
    else:
        out += "Incidents: none recorded for this story's deployments.\n"
    return out


CICD_TOOLS = [
    cicd_get_pipeline_runs,
    cicd_pipeline_summary,
    cicd_story_delivery_status,
]
