"""Parity tests pinning the composites to DIRECT-mode behavior (Task 4).

Two guarantees:

1. ``common.assignee.resolve_assignee`` resolves identically across all SIX
   branches of the original agent resolver (exact-name, first-name,
   email-local-part, no-match, ``dev-`` passthrough, ambiguous->None).
2. The ServiceNow composite's grouped data matches the data the agent
   aggregation produces for the same services/deployments fixture.
"""

from __future__ import annotations

import os
import sys

import pytest

from common.assignee import resolve_assignee

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


_DEVELOPERS = [
    {"id": "dev-1", "name": "Alice Nguyen", "email": "alice@ecommerce.io"},
    {"id": "dev-3", "name": "Raj Patel", "email": "raj@ecommerce.io"},
    {"id": "dev-7", "name": "Raj Sharma", "email": "rajsharma@ecommerce.io"},
]


@pytest.mark.parametrize(
    "assignee,expected",
    [
        ("Raj Patel", "dev-3"),        # exact full-name
        ("alice", "dev-1"),            # first-name / substring (unique)
        ("raj@ecommerce.io", "dev-3"), # exact email
        ("nobody", None),             # no-match
        ("dev-9", "dev-9"),           # dev- passthrough (ignores the directory)
        ("raj", None),                # ambiguous: Raj Patel AND Raj Sharma -> None
    ],
)
def test_resolve_assignee_all_six_branches(assignee, expected):
    assert resolve_assignee(assignee, _DEVELOPERS) == expected


def test_dev_passthrough_independent_of_directory():
    # The ``dev-`` branch short-circuits before consulting the developer list.
    assert resolve_assignee("dev-5", []) == "dev-5"


def test_empty_input_returns_none():
    assert resolve_assignee("", _DEVELOPERS) is None


# --------------------------------------------------------------------------- #
# ServiceNow composite data parity with the agent aggregation.
# --------------------------------------------------------------------------- #

def _agent_group(services, deployments):
    """Reproduce agent/tools/servicenow_tools.py grouping (data only)."""
    service_by_id = {s["id"]: s for s in services}
    grouped: dict[str, list] = {}
    for d in deployments:
        grouped.setdefault(d.get("service", "unknown"), []).append(d)
    out = {}
    for service_id, records in grouped.items():
        service = service_by_id.get(service_id, {})
        by_status: dict[str, int] = {}
        for r in records:
            by_status[r.get("status", "unknown")] = by_status.get(r.get("status", "unknown"), 0) + 1
        latest = max(records, key=lambda r: r.get("deployed_at", ""))
        out[service_id] = {
            "project_id": service.get("project_id", "unmapped"),
            "project_name": service.get("name", service_id),
            "count": len(records),
            "status_counts": by_status,
            "latest_id": latest.get("id", "unknown"),
        }
    return out


def test_servicenow_composite_matches_agent_aggregation(dynamo_table, monkeypatch):
    import importlib

    monkeypatch.setenv("TABLE_NAME", dynamo_table)
    monkeypatch.setenv("MOCK_SERVICENOW_TOKEN", "mock-servicenow-token-12345")
    import servicenow.handler as h

    importlib.reload(h)
    h._store = None
    h._router = None
    store, router = h._get_router()
    store.ensure_seeded()

    from servicenow.composites import deployment_status

    composite = deployment_status(store, router, "mock-servicenow-token-12345", {})

    services = store.query("SERVICE")
    deployments = store.query("DEPLOYMENT")
    expected = _agent_group(services, deployments)

    assert composite["total_deployments"] == len(deployments)
    composite_by_service = {p["service"]: p for p in composite["projects"]}
    assert set(composite_by_service) == set(expected)
    for service_id, exp in expected.items():
        got = composite_by_service[service_id]
        assert got["project_id"] == exp["project_id"]
        assert got["project_name"] == exp["project_name"]
        assert got["count"] == exp["count"]
        assert got["status_counts"] == exp["status_counts"]
        assert got["latest"]["id"] == exp["latest_id"]


# --------------------------------------------------------------------------- #
# Jira portfolio composite data parity with the per-project granular fan-out.
# --------------------------------------------------------------------------- #

_JIRA_TOKEN = "mock-jira-token-12345"


def _jira_router(dynamo_table, monkeypatch):
    import importlib

    monkeypatch.setenv("TABLE_NAME", dynamo_table)
    monkeypatch.setenv("MOCK_JIRA_TOKEN", _JIRA_TOKEN)
    import jira.handler as h

    importlib.reload(h)
    h._store = None
    h._router = None
    store, router = h._get_router()
    store.ensure_seeded()
    return store, router


def test_jira_portfolio_composite_matches_per_project_fanout(dynamo_table, monkeypatch):
    from common.gateway_dispatch import get_json
    from jira.composites import portfolio_sprint_status

    store, router = _jira_router(dynamo_table, monkeypatch)

    composite = portfolio_sprint_status(store, router, _JIRA_TOKEN, {})

    project_ids = [p["id"] for p in get_json(router, _JIRA_TOKEN, "/projects")["projects"]]
    assert composite["total_projects"] == len(project_ids)
    assert [p["project_id"] for p in composite["projects"]] == project_ids

    for i, project_id in enumerate(project_ids):
        entry = composite["projects"][i]
        # Byte-for-byte parity against the live granular route bodies.
        live_sprints = get_json(router, _JIRA_TOKEN, f"/sprints/{project_id}")["sprints"]
        live_board = get_json(router, _JIRA_TOKEN, f"/projects/{project_id}/board")
        assert entry["sprints"] == live_sprints
        assert entry["board"] == live_board
        # The active sprint's route-computed points ride through verbatim.
        for sprint in entry["sprints"]:
            if sprint["status"] == "active":
                assert "completed_points" in sprint
                assert "total_points" in sprint


# --------------------------------------------------------------------------- #
# GitHub all-repos PR composite: parity, count invariant, adapter reachability.
# --------------------------------------------------------------------------- #

_GITHUB_TOKEN = "mock-github-token-12345"


def _github_router(dynamo_table, monkeypatch):
    import importlib

    monkeypatch.setenv("TABLE_NAME", dynamo_table)
    monkeypatch.setenv("MOCK_GITHUB_TOKEN", _GITHUB_TOKEN)
    monkeypatch.setenv("GITHUB_MODE", "mock")
    import github.handler as h

    importlib.reload(h)
    h._store = None
    h._router = None
    store, router = h._get_router()
    store.ensure_seeded()
    return store, router


def test_github_all_repos_composite_matches_per_repo_fanout(dynamo_table, monkeypatch):
    from common.gateway_dispatch import get_json
    from github.composites import pull_requests_all_repos

    store, router = _github_router(dynamo_table, monkeypatch)

    composite = pull_requests_all_repos(store, router, _GITHUB_TOKEN, {})

    repos = get_json(router, _GITHUB_TOKEN, "/repos")["repos"]
    assert [r["repo_id"] for r in composite["repos"]] == [r["id"] for r in repos]

    for i, repo in enumerate(repos):
        entry = composite["repos"][i]
        live = get_json(router, _GITHUB_TOKEN, f"/repos/{repo['id']}/pulls")
        assert entry["pull_requests"] == live["pull_requests"]
        assert entry["total"] == live["total"]
        assert entry["repo_name"] == repo["name"]

    # Seed-pinned sanity: fails loudly if the seed drifts.
    by_id = {r["repo_id"]: r for r in composite["repos"]}
    assert by_id["repo-1"]["total"] == 3
    assert composite["total_pull_requests"] == 9


def test_github_all_repos_composite_total_is_sum_of_rows(dynamo_table, monkeypatch):
    # MEDIUM-1 invariant: top-level count equals the sum of the composite's OWN
    # per-repo totals, so a future status filter cannot silently drift it.
    from github.composites import pull_requests_all_repos

    store, router = _github_router(dynamo_table, monkeypatch)
    composite = pull_requests_all_repos(store, router, _GITHUB_TOKEN, {})
    assert composite["total_pull_requests"] == sum(r["total"] for r in composite["repos"])


def test_github_all_repos_composite_reachable_via_adapter(dynamo_table, monkeypatch):
    # MEDIUM-2 reachability: the adapter swallows ImportError, so a wrong dotted
    # path would fail SILENTLY. Dispatch THROUGH the adapter and assert real data
    # comes back, proving github.composites.pull_requests_all_repos resolves.
    from common import gateway_adapter

    store, router = _github_router(dynamo_table, monkeypatch)
    result = gateway_adapter.handle(
        "mock-github___github_pull_requests_all_repos", store, router, {}, _GITHUB_TOKEN
    )
    assert "error" not in result
    assert "repos" in result and result["repos"]
    assert result["total_pull_requests"] == sum(r["total"] for r in result["repos"])
