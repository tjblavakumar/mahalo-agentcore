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
