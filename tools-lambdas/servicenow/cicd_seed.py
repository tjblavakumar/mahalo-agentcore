"""Recorded CI/CD pipeline runs for the demo (pure data, no I/O, nothing executed).

Runs are built in code on each request by :func:`build_runs`, from the stored
ServiceNow deployments (overrides and shifted dates already applied), plus nine
authored runs. They are never written to DynamoDB, so the already-seeded live
table needs no reset. Every value is demo data: no pipeline ran for any of it.

``cicd_seed`` must not import ``routes`` (``routes`` imports ``cicd``) and must
not raise at import time; literals are only turned into runs inside
``build_runs``.
"""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List

from common import seed_dates

from . import seed_data

SYSTEM = "CI/CD"
DATA_ORIGIN = "seeded"

STAGE_ORDER = (
    "build",
    "unit_tests",
    "integration_tests",
    "sast",
    "dependency_scan",
    "deploy",
)
SEVERITIES = ("critical", "high", "medium", "low")

PROJECT_SERVICE = {
    "PAY": "payment-service",
    "CART": "cart-service",
    "AUTH": "auth-service",
    "PROD": "product-service",
    "ORD": "order-service",
}
PROJECTS = tuple(PROJECT_SERVICE)

# Jira stories that ServiceNow deployments link to (after LINKED_STORY_OVERRIDES).
# The Lambda cannot import the Jira seed, so the set is stated here; a test
# recomputes it from the Jira and ServiceNow seeds. Together these stories are
# linked from 24 of the 50 deployments; the others link to ids that are not in
# Jira (for example PAY-601) and get no pipeline run.
KNOWN_STORY_IDS = frozenset(
    {
        "PAY-101", "PAY-103", "PAY-105", "PAY-106", "PAY-110",
        "CART-201", "CART-203", "CART-204", "CART-206",
        "AUTH-301", "AUTH-304", "AUTH-306",
        "PROD-401", "PROD-402", "PROD-403", "PROD-404",
        "ORD-501", "ORD-503",
    }
)

# Branch names of the github seed (the real Gitea mirrors them), by story.
FEATURE_BRANCHES = {
    "PAY-105": "feature/PAY-105-google-pay",
    "PAY-106": "feature/PAY-106-payment-retry",
    "PAY-107": "feature/PAY-107-multi-currency",
    "PAY-108": "feature/PAY-108-analytics-dashboard",
    "CART-204": "feature/CART-204-wishlist-to-cart",
    "CART-206": "feature/CART-206-shipping-estimator",
    "AUTH-304": "feature/AUTH-304-totp-2fa",
    "AUTH-306": "feature/AUTH-306-saml-sso",
    "PROD-403": "feature/PROD-403-recommendations",
    "ORD-503": "feature/ORD-503-split-fulfillment",
}

_LOW_TITLE = "Outdated transitive dependency (seeded example)"
_MEDIUM_SAST_TITLE = "Weak input validation pattern (seeded example)"

# Share of a deployment's duration per stage (percent). Build takes the remainder.
_DURATION_SHARE = (
    ("unit_tests", 25),
    ("integration_tests", 30),
    ("sast", 10),
    ("dependency_scan", 5),
    ("deploy", 15),
)
# Default stage durations (seconds) of authored runs.
_AUTHORED_DURATIONS = {
    "build": 42,
    "unit_tests": 96,
    "integration_tests": 171,
    "sast": 58,
    "dependency_scan": 33,
    "deploy": 0,
}
_AUTHORED_UNIT = (150, 0, 3)
_AUTHORED_INTEGRATION = (35, 0, 1)

_FIXED_FAILURE = {
    "failed": "Deploy stage failed (see ServiceNow deployment {dep})",
    "rolled_back": "Deployed, then rolled back (see ServiceNow deployment {dep})",
}
# Only these two deployments carry a real failure reason in their notes.
_NOTES_FAILURE_DEPLOYMENTS = ("DEP-1003", "DEP-1004")

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _sha(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:7]


def _project_of(story_id: str) -> str:
    return story_id.split("-")[0]


def _stage(name: str, status: str = "passed", duration: int = 0, **extra: Any) -> Dict[str, Any]:
    stage: Dict[str, Any] = {"name": name, "status": status, "duration_seconds": int(duration)}
    if name in ("unit_tests", "integration_tests"):
        stage["tests"] = {"passed": 0, "failed": 0, "skipped": 0}
    if name in ("sast", "dependency_scan"):
        stage["findings"] = {sev: 0 for sev in SEVERITIES}
    if name == "deploy":
        stage["environment"] = None
    stage.update(extra)
    return stage


def _tests(passed: int, failed: int, skipped: int) -> Dict[str, int]:
    return {"passed": passed, "failed": failed, "skipped": skipped}


def _finding(scanner: str, severity: str, title: str, location: str) -> Dict[str, Any]:
    return {
        "id": None,  # numbered in _finalize
        "scanner": scanner,
        "severity": severity,
        "title": title,
        "location": location,
        "status": "open",
    }


def _num(value: Any) -> int:
    """Plain int from a DynamoDB ``Decimal`` or int."""
    return int(value)


def _finalize(run: Dict[str, Any]) -> Dict[str, Any]:
    """Derive status, failed stage, totals and gate. The single owner of these."""
    stages = run["stages"]
    findings = run.pop("_findings", [])
    run_no = run["id"].split("-")[1]

    # Number findings per run: FND-<run number>-<n>, scanner order sast then dependency.
    ordered = sorted(
        findings,
        key=lambda f: (0 if f["scanner"] == "sast" else 1, SEVERITIES.index(f["severity"])),
    )
    for n, finding in enumerate(ordered, start=1):
        finding["id"] = f"FND-{run_no}-{n}"

    scanner_stage = {"sast": "sast", "dependency": "dependency_scan"}
    # 1) scan stage status follows its open findings; test stage status follows counts.
    for stage in stages:
        name = stage["name"]
        if name in ("sast", "dependency_scan") and stage["status"] in ("passed", "failed"):
            mine = [f for f in ordered if scanner_stage[f["scanner"]] == name]
            counts = {sev: 0 for sev in SEVERITIES}
            for f in mine:
                counts[f["severity"]] += 1
            stage["findings"] = counts
            stage["status"] = "failed" if counts["critical"] or counts["high"] else "passed"
        elif name in ("unit_tests", "integration_tests") and stage["status"] in ("passed", "failed"):
            stage["status"] = "failed" if stage["tests"]["failed"] > 0 else "passed"

    # 2) stages after the first failed / rolled back / in progress stage are not_run.
    blocked = False
    for stage in stages:
        if blocked and stage["status"] != "not_applicable":
            stage["status"] = "not_run"
            stage["duration_seconds"] = 0
            if "tests" in stage:
                stage["tests"] = _tests(0, 0, 0)
            if "findings" in stage:
                stage["findings"] = {sev: 0 for sev in SEVERITIES}
        if stage["status"] in ("failed", "rolled_back", "in_progress"):
            blocked = True

    ran = {s["name"] for s in stages if s["status"] in ("passed", "failed")}
    ordered = [f for f in ordered if scanner_stage[f["scanner"]] in ran]

    statuses = [s["status"] for s in stages]
    if "failed" in statuses or "rolled_back" in statuses:
        run["status"] = "failed"
    elif "in_progress" in statuses:
        run["status"] = "in_progress"
    else:
        run["status"] = "passed"
    failed = [s["name"] for s in stages if s["status"] in ("failed", "rolled_back")]
    run["failed_stage"] = failed[0] if failed else None
    if run["status"] != "failed":
        run["failure_reason"] = None

    totals = _tests(0, 0, 0)
    for stage in stages:
        if "tests" in stage and stage["status"] in ("passed", "failed"):
            for key in totals:
                totals[key] += stage["tests"][key]
    totals["total"] = totals["passed"] + totals["failed"] + totals["skipped"]
    run["tests"] = totals

    stage_by_name = {s["name"]: s for s in stages}
    sev_totals = {sev: 0 for sev in SEVERITIES}
    for f in ordered:
        sev_totals[f["severity"]] += 1
    scan_names = ("sast", "dependency_scan")
    if all(stage_by_name[n]["status"] not in ("passed", "failed") for n in scan_names):
        gate = "not_run"
    elif sev_totals["critical"] or sev_totals["high"]:
        gate = "failed"
    else:
        gate = "passed"
    run["security"] = {
        "sast": {
            "status": stage_by_name["sast"]["status"],
            "findings": dict(stage_by_name["sast"]["findings"]),
        },
        "dependency_scan": {
            "status": stage_by_name["dependency_scan"]["status"],
            "findings": dict(stage_by_name["dependency_scan"]["findings"]),
        },
        "totals": sev_totals,
        "findings": ordered,
        "gate": gate,
    }
    return run


def _base_run(
    run_id: str,
    story_id: str,
    stages: List[Dict[str, Any]],
    findings: List[Dict[str, Any]],
    **fields: Any,
) -> Dict[str, Any]:
    project = _project_of(story_id)
    run: Dict[str, Any] = {
        "id": run_id,
        "system": SYSTEM,
        "data_origin": DATA_ORIGIN,
        "anchor": "commit",
        "project_id": project,
        "service": PROJECT_SERVICE[project],
        "repo": PROJECT_SERVICE[project],
        "branch": None,
        "commit_sha": None,
        "linked_story": story_id,
        "linked_pr": None,
        "linked_deployment": None,
        "trigger": "push",
        "status": None,
        "failed_stage": None,
        "failure_reason": None,
        "started_at": None,
        "finished_at": None,
        "stages": stages,
        "_findings": findings,
    }
    run.update(fields)
    return run


# --------------------------------------------------------------------------- #
# Generated runs: one per ServiceNow deployment linked to a known Jira story.
# --------------------------------------------------------------------------- #
def _generated_run(dep: Dict[str, Any]) -> Dict[str, Any]:
    dep_id = dep["id"]
    n = int(dep_id.split("-")[1]) - 1000  # deployment number: DEP-1002 -> 2
    story = dep["linked_story"]
    duration = _num(dep.get("duration_seconds") or 0)
    production = dep["environment"] == "production"
    branch = "main" if production else FEATURE_BRANCHES.get(story, f"feature/{story}-release")

    parts = {name: duration * pct // 100 for name, pct in _DURATION_SHARE}
    parts["build"] = duration - sum(parts.values())

    stages = [_stage(name, "passed", parts[name]) for name in STAGE_ORDER]
    by_name = {s["name"]: s for s in stages}
    by_name["unit_tests"]["tests"] = _tests(120 + (n % 7) * 17, 0, n % 4)
    by_name["integration_tests"]["tests"] = _tests(30 + (n % 9) * 3, 0, n % 3)
    deploy = by_name["deploy"]
    deploy["environment"] = dep["environment"]
    deploy["status"] = {
        "success": "passed",
        "failed": "failed",
        "rolled_back": "rolled_back",
        "in_progress": "in_progress",
    }[dep["status"]]

    findings: List[Dict[str, Any]] = []
    if n % 5 == 0:
        findings.append(
            _finding("sast", "medium", _MEDIUM_SAST_TITLE, f"src/{dep['service']}")
        )
    if n % 3 == 0:
        findings.append(_finding("dependency", "low", _LOW_TITLE, "requirements.txt"))

    reason = None
    if dep["status"] in _FIXED_FAILURE:
        if dep_id in _NOTES_FAILURE_DEPLOYMENTS:
            reason = dep.get("notes")
        else:
            reason = _FIXED_FAILURE[dep["status"]].format(dep=dep_id)

    finished = None if dep["status"] == "in_progress" else dep["deployed_at"]
    started = (
        datetime.strptime(dep["deployed_at"], _FMT) - timedelta(seconds=duration)
    ).strftime(_FMT)
    return _base_run(
        f"RUN-{3100 + n}",
        story,
        stages,
        findings,
        service=dep["service"],
        repo=dep["service"],
        branch=branch,
        commit_sha=_sha(f"{dep_id}:{story}"),
        linked_deployment=dep_id,
        trigger="merge",
        failure_reason=reason,
        started_at=started,
        finished_at=finished,
    )


# --------------------------------------------------------------------------- #
# Authored runs RUN-3001..3009 (seed dates, shifted in build_runs).
# --------------------------------------------------------------------------- #
def _authored_specs() -> List[Dict[str, Any]]:
    """Plain literals, built lazily. Dates are seed-era; ``build_runs`` shifts them."""
    return [
        {
            "id": "RUN-3001", "story": "PAY-109", "date": "2026-08-23", "anchor": "story",
            "unit": (168, 0, 4), "integration": (41, 0, 2),
            "findings": [
                _finding("sast", "medium", "Hard-coded test wallet key in a fixture (seeded example)",
                         "tests/fixtures/wallet.py"),
                _finding("dependency", "high",
                         "Crypto-signing library has a known high-severity vulnerability (seeded example)",
                         "requirements.txt"),
                _finding("dependency", "low", _LOW_TITLE, "requirements.txt"),
            ],
            "deploy": "not_run",
            "reason": "Dependency scan found 1 high-severity vulnerability (seeded example)",
        },
        {
            "id": "RUN-3002", "story": "PAY-105", "date": "2026-08-21",
            "integration": (33, 2, 1), "findings": [],
            "reason": "Integration tests failed: 2 failing tests (seeded example)",
        },
        {
            "id": "RUN-3003", "story": "PAY-105", "date": "2026-08-22",
            "findings": [
                _finding("dependency", "medium",
                         "Dependency with a known medium-severity issue (seeded example)",
                         "requirements.txt"),
            ],
        },
        {
            "id": "RUN-3004", "story": "CART-206", "date": "2026-08-22",
            "unit": (112, 3, 2), "findings": [],
            "reason": "Unit tests failed: 3 failing tests (seeded example)",
        },
        {
            "id": "RUN-3005", "story": "AUTH-306", "date": "2026-08-23",
            "findings": [
                _finding("sast", "high", "SAML assertion signature not verified (seeded example)",
                         "src/auth-service"),
            ],
            "reason": "SAST found 1 high-severity issue (seeded example)",
        },
        {"id": "RUN-3006", "story": "PROD-403", "date": "2026-08-22", "findings": []},
        {
            "id": "RUN-3007", "story": "ORD-503", "date": "2026-08-23",
            "findings": [
                _finding("dependency", "high",
                         "Order-processing dependency has a known high-severity vulnerability (seeded example)",
                         "requirements.txt"),
            ],
            "reason": "Dependency scan found 1 high-severity vulnerability (seeded example)",
        },
        {
            "id": "RUN-3008", "story": "PAY-108", "date": "2026-08-22",
            "findings": [_finding("dependency", "low", _LOW_TITLE, "requirements.txt")],
        },
        {
            "id": "RUN-3009", "story": "PAY-107", "date": "2026-08-23",
            "in_progress": "integration_tests", "findings": [],
        },
    ]


def _authored_run(spec: Dict[str, Any], shift_days: int) -> Dict[str, Any]:
    story = spec["story"]
    run_id = spec["id"]
    story_anchored = spec.get("anchor") == "story"
    stages = [_stage(name, "passed", _AUTHORED_DURATIONS[name]) for name in STAGE_ORDER]
    by_name = {s["name"]: s for s in stages}
    by_name["unit_tests"]["tests"] = _tests(*spec.get("unit", _AUTHORED_UNIT))
    by_name["integration_tests"]["tests"] = _tests(*spec.get("integration", _AUTHORED_INTEGRATION))
    by_name["deploy"]["status"] = spec.get("deploy", "not_applicable")
    if spec.get("in_progress"):
        by_name[spec["in_progress"]]["status"] = "in_progress"
        by_name[spec["in_progress"]]["tests"] = _tests(0, 0, 0)
        by_name[spec["in_progress"]]["duration_seconds"] = 0

    start = datetime.strptime(spec["date"] + "T15:00:00Z", _FMT) + timedelta(days=shift_days)
    run = _base_run(
        run_id,
        story,
        stages,
        copy.deepcopy(spec["findings"]),
        anchor="story" if story_anchored else "commit",
        branch=None if story_anchored else FEATURE_BRANCHES[story],
        commit_sha=None if story_anchored else _sha(f"{run_id}:{story}"),
        trigger="push",
        failure_reason=spec.get("reason"),
        started_at=start.strftime(_FMT),
    )
    _finalize(run)
    total = sum(s["duration_seconds"] for s in run["stages"])
    if run["status"] == "in_progress":
        run["finished_at"] = None
    else:
        run["finished_at"] = (start + timedelta(seconds=total)).strftime(_FMT)
    return run


def shift_days_from(deployments: Iterable[Dict[str, Any]]) -> int:
    """Whole-week shift the stored deployments received (stored DEP-1001 minus seed)."""
    seed_at = next(
        (d["deployed_at"] for d in seed_data.DEPLOYMENTS if d["id"] == "DEP-1001"), None
    )
    stored_at = next(
        (d.get("deployed_at") for d in deployments if d.get("id") == "DEP-1001"), None
    )
    if seed_at and stored_at:
        return (datetime.strptime(stored_at, _FMT) - datetime.strptime(seed_at, _FMT)).days
    return seed_dates.compute_shift_days(seed_dates.today_utc())


def build_runs(deployments: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """All runs, newest first by ``started_at``. ``deployments`` are stored records."""
    deployments = list(deployments)
    runs: List[Dict[str, Any]] = []
    for dep in deployments:
        if dep.get("linked_story") in KNOWN_STORY_IDS:
            runs.append(_finalize(_generated_run(dep)))
    shift = shift_days_from(deployments)
    for spec in _authored_specs():
        runs.append(_authored_run(spec, shift))
    runs.sort(key=lambda r: (r["started_at"], r["id"]), reverse=True)
    return runs

