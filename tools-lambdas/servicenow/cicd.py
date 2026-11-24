"""Read-only ``/cicd/*`` routes: recorded CI/CD pipeline results (demo data).

Nothing here executes a pipeline or writes anything. Runs are built per request
from the stored deployments by ``cicd_seed.build_runs`` and compared in memory.
Every response says the data is seeded and not a live pipeline run.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from common.responses import error, json_response

from . import cicd_seed

LABEL = "Seeded demo data. Not a live pipeline run."
PROVENANCE = (
    "Recorded sample results seeded for the Mahalo demo. No pipeline executed for any "
    "commit created through Mahalo."
)
SEEDED_REF_NOTE = "Branch and commit shown are seeded sample values, not read from Gitea."
STORY_ANCHOR_NOTE = (
    "This is a sample run recorded for story {story}. It was not produced by the branch "
    "or commit you asked about."
)

_STORY_RE = re.compile(r"^[A-Za-z]{2,6}-\d{1,5}$")
_STORY_IN_TEXT_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2,6}-\d{1,5})(?![0-9])")
_HEX_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_STATUSES = ("passed", "failed", "in_progress")
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50


def extract_story_id(text: str) -> Optional[str]:
    """First story id in ``text`` whose project prefix is one of the five projects."""
    for match in _STORY_IN_TEXT_RE.finditer(text or ""):
        candidate = match.group(1).upper()
        if candidate.split("-")[0] in cicd_seed.PROJECTS:
            return candidate
    return None


def _envelope() -> Dict[str, Any]:
    return {"system": cicd_seed.SYSTEM, "data_origin": cicd_seed.DATA_ORIGIN,
            "label": LABEL, "provenance": PROVENANCE}


def _latest_per_story(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The run with the greatest ``started_at`` for each linked story."""
    latest: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        current = latest.get(run["linked_story"])
        if current is None or (run["started_at"], run["id"]) > (current["started_at"], current["id"]):
            latest[run["linked_story"]] = run
    return sorted(latest.values(), key=lambda r: (r["started_at"], r["id"]), reverse=True)


def _validate_runs_query(query: Dict[str, str]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return (clean params, 422 response)."""
    clean: Dict[str, Any] = {}
    story = query.get("story_id")
    if story:
        if not _STORY_RE.match(story):
            return None, error(422, "story_id must look like PAY-109")
        clean["story_id"] = story.upper()
    project = query.get("project_id")
    if project:
        if project.upper() not in cicd_seed.PROJECTS:
            return None, error(422, "project_id must be one of PAY, CART, AUTH, PROD, ORD")
        clean["project_id"] = project.upper()
    repo = query.get("repo")
    if repo:
        if len(repo) > 64:
            return None, error(422, "repo must be at most 64 characters")
        clean["repo"] = repo
    branch = query.get("branch")
    if branch:
        if len(branch) > 200:
            return None, error(422, "branch must be at most 200 characters")
        clean["branch"] = branch
    commit = query.get("commit")
    if commit:
        if not _HEX_RE.match(commit):
            return None, error(422, "commit must be a hex sha of 7 to 40 characters")
        clean["commit"] = commit.lower()
    status = query.get("status")
    if status:
        if status not in _STATUSES:
            return None, error(422, "status must be one of passed, failed, in_progress")
        clean["status"] = status
    limit = query.get("limit")
    if limit not in (None, ""):
        try:
            value = int(limit)
        except (TypeError, ValueError):
            return None, error(422, "limit must be an integer from 1 to 50")
        if not 1 <= value <= _MAX_LIMIT:
            return None, error(422, "limit must be an integer from 1 to 50")
        clean["limit"] = value
    return clean, None


def query_runs(runs: List[Dict[str, Any]], params: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve and filter runs (see design D3). Pure; returns the response body."""
    story = params.get("story_id")
    branch = params.get("branch")
    commit = params.get("commit")
    notes: List[str] = [SEEDED_REF_NOTE]
    matched_by = "filters"
    exact_branch = [r for r in runs if branch and r["branch"] == branch]
    extracted = extract_story_id(branch) if branch else None

    if story:
        candidates = [r for r in runs if r["linked_story"] == story]
        matched_by = "story_id"
        if branch:
            other = None
            if exact_branch:
                stories = {r["linked_story"] for r in exact_branch}
                if len(stories) == 1 and story not in stories:
                    other = next(iter(stories))
            elif extracted and extracted != story:
                other = extracted
            if other:
                notes.append(f"Branch {branch} belongs to story {other}, not {story}. "
                             f"Showing runs for {story}.")
    elif branch:
        if exact_branch:
            candidates, matched_by = exact_branch, "branch_exact"
        elif extracted:
            candidates = [r for r in runs if r["linked_story"] == extracted]
            matched_by = "story_id_in_branch"
        else:
            candidates, matched_by = [], "branch_exact"
    elif commit:
        candidates = [r for r in runs if r["commit_sha"] and r["commit_sha"].startswith(commit)]
        matched_by = "commit_sha"
    else:
        candidates = list(runs)

    if params.get("project_id"):
        candidates = [r for r in candidates if r["project_id"] == params["project_id"]]
    if params.get("repo"):
        candidates = [r for r in candidates if params["repo"] in (r["repo"], r["service"])]
    if params.get("status"):
        candidates = [r for r in candidates if r["status"] == params["status"]]
    candidates.sort(key=lambda r: (r["started_at"], r["id"]), reverse=True)
    total = len(candidates)
    returned = candidates[: params.get("limit", _DEFAULT_LIMIT)]

    out_runs = []
    for run in returned:
        item = dict(run)
        item["exact_ref_match"] = bool(
            run["anchor"] == "commit"
            and (
                (matched_by == "branch_exact" and branch and run["branch"] == branch)
                or (matched_by == "commit_sha" and commit and run["commit_sha"]
                    and run["commit_sha"].startswith(commit))
            )
        )
        out_runs.append(item)

    if branch and matched_by in ("story_id", "story_id_in_branch") and not any(
        r["branch"] == branch for r in returned
    ):
        if matched_by == "story_id_in_branch":
            notes.append(
                f"No run is recorded for branch {branch} (sha unknown). Showing the recorded "
                f"run for story {extracted}, matched by the story ID in the branch name."
            )
        else:
            notes.append(
                f"No run is recorded for branch {branch} (sha unknown). Showing the "
                f"recorded runs for story {story}."
            )
    if commit and not any(
        r["commit_sha"] and r["commit_sha"].startswith(commit) for r in returned
    ):
        notes.append(f"No run is recorded for commit {commit}.")
    for sid in sorted({r["linked_story"] for r in returned if r["anchor"] == "story"}):
        notes.append(STORY_ANCHOR_NOTE.format(story=sid))

    body = _envelope()
    body.update(
        {
            "match": {
                "matched_by": matched_by,
                "exact_ref_match": any(r["exact_ref_match"] for r in out_runs),
                "ref_is_seeded": True,
            },
            "ref_note": " ".join(notes),
            "runs": out_runs,
            "total": total,
            "returned": len(out_runs),
        }
    )
    if not out_runs:
        wanted = ", ".join(f"{k}={v}" for k, v in params.items() if k != "limit") or "any filter"
        body["message"] = f"No pipeline run is recorded for {wanted}."
    return body


def summarize(runs: List[Dict[str, Any]], deployments: List[Dict[str, Any]],
              project_id: Optional[str] = None) -> Dict[str, Any]:
    """Per-project pipeline roll-up, computed in code (design D4 tool 2)."""
    with_run = {r["linked_deployment"] for r in runs if r["linked_deployment"]}
    latest_all = _latest_per_story(runs)
    wanted = [project_id] if project_id else list(cicd_seed.PROJECTS)

    def _project(pid: str) -> Dict[str, Any]:
        service = cicd_seed.PROJECT_SERVICE[pid]
        mine = [r for r in runs if r["project_id"] == pid]
        latest = [r for r in latest_all if r["project_id"] == pid]
        counts = {s: 0 for s in _STATUSES}
        for r in mine:
            counts[r["status"]] += 1
        latest_counts = {s: 0 for s in _STATUSES}
        for r in latest:
            latest_counts[r["status"]] += 1
        findings = {sev: 0 for sev in cicd_seed.SEVERITIES}
        tests = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
        for r in latest:
            for sev, n in r["security"]["totals"].items():
                findings[sev] += n
            for key in tests:
                tests[key] += r["tests"][key]
        deps = [d for d in deployments if d["service"] == service]
        return {
            "project_id": pid,
            "service": service,
            "run_counts": dict(counts, total=len(mine)),
            "latest_run_counts": dict(latest_counts, total=len(latest)),
            "failing_stories": [
                {"story_id": r["linked_story"], "run_id": r["id"],
                 "failed_stage": r["failed_stage"], "failure_reason": r["failure_reason"]}
                for r in latest if r["status"] == "failed"
            ],
            "open_findings": findings,
            "open_findings_total": sum(findings.values()),
            "stories_with_open_high_or_critical": sorted(
                r["linked_story"] for r in latest
                if r["security"]["totals"]["high"] or r["security"]["totals"]["critical"]
            ),
            "test_totals_latest_runs": tests,
            "latest_runs": [
                {"story_id": r["linked_story"], "run_id": r["id"], "status": r["status"],
                 "started_at": r["started_at"], "gate": r["security"]["gate"]}
                for r in latest
            ],
            "deployments_total": len(deps),
            "deployments_without_pipeline_run": sum(1 for d in deps if d["id"] not in with_run),
        }

    projects = [_project(pid) for pid in wanted]
    portfolio_findings = {sev: sum(p["open_findings"][sev] for p in projects)
                          for sev in cicd_seed.SEVERITIES}
    scoped = [d for d in deployments
              if not project_id or d["service"] == cicd_seed.PROJECT_SERVICE[project_id]]
    body = _envelope()
    body.update(
        {
            "scope": (f"Pipeline runs recorded for {sum(1 for d in scoped if d['id'] in with_run)} "
                      f"of {len(scoped)} deployments. Counts here differ from ServiceNow's "
                      "all-deployment counts."),
            "projects": projects,
            "portfolio": {
                "runs": sum(p["run_counts"]["total"] for p in projects),
                "projects_with_failing_pipelines": [
                    p["project_id"] for p in projects if p["failing_stories"]
                ],
                "projects_with_open_findings": [
                    p["project_id"] for p in projects if p["open_findings_total"]
                ],
                "projects_with_open_high_or_critical": [
                    p["project_id"] for p in projects
                    if p["open_findings"]["high"] or p["open_findings"]["critical"]
                ],
                "open_findings": portfolio_findings,
            },
        }
    )
    return body


def delivery(runs: List[Dict[str, Any]], deployments: List[Dict[str, Any]],
             incidents: List[Dict[str, Any]], story_id: str) -> Dict[str, Any]:
    """One story across pipeline, deployments and incidents (design D4 tool 3)."""
    mine = sorted((r for r in runs if r["linked_story"] == story_id),
                  key=lambda r: (r["started_at"], r["id"]), reverse=True)
    deps = sorted((d for d in deployments if d.get("linked_story") == story_id),
                  key=lambda d: d.get("deployed_at", ""), reverse=True)
    dep_ids = {d["id"] for d in deps}
    linked_incidents = []
    for inc in sorted(incidents, key=lambda i: i.get("opened_at", ""), reverse=True):
        if inc.get("linked_deployment") in dep_ids:
            item = dict(inc)
            item["linked_via"] = f"linked_deployment {inc['linked_deployment']}"
            linked_incidents.append(item)
    notes = [SEEDED_REF_NOTE]
    if mine and mine[0]["anchor"] == "story":
        notes.append(STORY_ANCHOR_NOTE.format(story=story_id))
    body = _envelope()
    body.update(
        {
            "story_id": story_id,
            "ref_note": " ".join(notes),
            "latest_run": mine[0] if mine else None,
            "run_history": [
                {"id": r["id"], "status": r["status"], "started_at": r["started_at"],
                 "anchor": r["anchor"], "failed_stage": r["failed_stage"]}
                for r in mine
            ],
            "deployments": deps,
            "incidents": linked_incidents,
            "no_run_recorded": not mine,
            "no_deployment_recorded": not deps,
        }
    )
    if not mine:
        body["message"] = f"No pipeline run is recorded for {story_id}."
    return body


def register_routes(router, store, auth) -> None:
    """Add the three GET routes. ``auth(request)`` returns an error response or None."""
    from .routes import PK_DEPLOYMENT, PK_INCIDENT  # late: routes imports this module

    def _runs():
        deployments = store.query(PK_DEPLOYMENT)
        return cicd_seed.build_runs(deployments), deployments

    @router.route("GET", "/cicd/runs")
    def cicd_runs(request):
        denied = auth(request)
        if denied:
            return denied
        params, bad = _validate_runs_query(request.query)
        if bad:
            return bad
        runs, _ = _runs()
        return json_response(200, query_runs(runs, params))

    @router.route("GET", "/cicd/summary")
    def cicd_summary(request):
        denied = auth(request)
        if denied:
            return denied
        project = request.query.get("project_id")
        if project:
            if project.upper() not in cicd_seed.PROJECTS:
                return error(422, "project_id must be one of PAY, CART, AUTH, PROD, ORD")
            project = project.upper()
        runs, deployments = _runs()
        return json_response(200, summarize(runs, deployments, project or None))

    @router.route("GET", "/cicd/stories/{story_id}/delivery")
    def cicd_delivery(request):
        denied = auth(request)
        if denied:
            return denied
        story = request.path_params["story_id"]
        if not _STORY_RE.match(story):
            return error(422, "story_id must look like PAY-109")
        runs, deployments = _runs()
        return json_response(
            200, delivery(runs, deployments, store.query(PK_INCIDENT), story.upper())
        )
