"""Shared fixture data for the briefing tests (shapes copied from the live mocks)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 11, 24, 22, 30, 0, tzinfo=timezone.utc)
FMT = "%Y-%m-%dT%H:%M:%SZ"


def ago(**kw) -> str:
    return (NOW - timedelta(**kw)).strftime(FMT)


def day(offset_days: int) -> str:
    return (NOW - timedelta(days=offset_days)).strftime("%Y-%m-%d")


def _story(sid, status, assignee, comments=(), sprint="PAY-3"):
    return {
        "id": sid, "project_id": sid.split("-")[0], "sprint_id": sprint,
        "title": f"Title of {sid}", "status": status, "assignee": assignee,
        "comments": [dict(c) for c in comments],
    }


def _inc(iid, sev, svc, opened, resolved=None, title="Something broke"):
    return {
        "id": iid, "severity": sev, "affected_service": svc, "opened_at": opened,
        "resolved_at": resolved, "title": title, "status": "resolved" if resolved else "open",
    }


def _dep(did, svc, story, when, status="rolled_back", env="production", version="v9.2.8"):
    return {
        "id": did, "service": svc, "linked_story": story, "deployed_at": when,
        "status": status, "environment": env, "version": version,
    }


def _run(rid, project, story, started, status="failed", stage="dependency_scan",
         high=0, critical=0, linked_dep=None):
    return {
        "id": rid, "project_id": project, "linked_story": story, "started_at": started,
        "status": status, "failed_stage": stage if status == "failed" else None,
        "linked_deployment": linked_dep,
        "security": {"totals": {"high": high, "critical": critical, "medium": 0, "low": 0}},
    }


SERVICES = {
    "PAY": "payment-service", "CART": "cart-service", "AUTH": "auth-service",
    "PROD": "product-service", "ORD": "order-service",
}


def make_raw() -> dict:
    """A day of activity shaped like the live data, relative to ``NOW``."""
    developers = [
        {"id": f"dev-{i}", "name": n}
        for i, n in enumerate(
            ["Marcus Chen", "Sarah Johnson", "Raj Patel", "Emily Zhang", "David Kim",
             "Lava Dev", "Maya Chaya"], start=1)
    ]
    projects = [
        {"id": "PAY", "lead": "dev-1"}, {"id": "CART", "lead": "dev-2"},
        {"id": "AUTH", "lead": "dev-3"}, {"id": "PROD", "lead": "dev-4"},
        {"id": "ORD", "lead": "dev-5"},
    ]
    stories = [
        _story("PAY-109", "todo", "dev-6"),
        _story("PAY-110", "todo", "dev-6"),
        _story("AUTH-306", "in_progress", "dev-6"),
        _story("PAY-108", "in_review", "dev-5",
               [{"author": "dev-1", "text": "PR ready for review", "date": day(0)}]),
        _story("ORD-503", "in_progress", "dev-5",
               [{"author": "dev-5", "text": "Warehouse routing done", "date": day(0)}]),
        _story("PAY-105", "in_progress", "dev-1"),
        _story("CART-206", "in_progress", "dev-2"),
        _story("PROD-403", "in_progress", "dev-4"),
        _story("PAY-064", "done", "dev-6", sprint=None),
    ]
    activity = [
        {"ts": ago(hours=2), "story_id": "PAY-109", "project_id": "PAY", "type": "assigned",
         "actor": None, "to": "dev-6", "from": None, "text": None, "origin": "demo-seed"},
        {"ts": ago(hours=3), "story_id": "PAY-110", "project_id": "PAY", "type": "comment",
         "actor": "dev-7", "to": None, "from": None, "origin": "write",
         "text": "Design review: please add an ADR for the fraud rules"},
        {"ts": ago(hours=4), "story_id": "PAY-108", "project_id": "PAY", "type": "status",
         "actor": None, "to": "in_review", "from": "in_progress", "text": None, "origin": "write"},
        {"ts": ago(hours=1), "story_id": "ORD-503", "project_id": "ORD", "type": "comment",
         "actor": "dev-1", "to": None, "from": None, "origin": "write",
         "text": "Please confirm the carrier rate limits"},
        {"ts": ago(hours=5), "story_id": "AUTH-306", "project_id": "AUTH", "type": "comment",
         "actor": "dev-6", "to": None, "from": None, "origin": "write", "text": "my own note"},
    ]
    incidents = [
        _inc("INC-2001", "P1", "product-service", ago(hours=6), ago(hours=5), "Recs returning 500s"),
        _inc("INC-2008", "P2", "auth-service", ago(hours=10, minutes=15)),
        _inc("INC-2009", "P2", "cart-service", ago(hours=10, minutes=15)),
        _inc("INC-2010", "P2", "order-service", ago(hours=10, minutes=15)),
        _inc("INC-2011", "P2", "payment-service", ago(hours=10, minutes=15)),
        _inc("INC-2012", "P2", "product-service", ago(hours=10, minutes=15)),
        _inc("INC-2020", "P3", "payment-service", ago(hours=8), title="Slow settlement report"),
        _inc("INC-2030", "P1", "payment-service", ago(days=4), title="Old outage"),
        _inc("INC-9000", "P1", "payment-service", (NOW + timedelta(hours=3)).strftime(FMT),
             title="Future incident"),
    ]
    deployments = [
        _dep("DEP-1011", "auth-service", "AUTH-306", ago(hours=7)),
        _dep("DEP-1012", "order-service", "ORD-503", ago(hours=7)),
        _dep("DEP-1013", "payment-service", "PAY-110", ago(hours=7)),
        _dep("DEP-1004", "product-service", "PROD-403", ago(hours=5, minutes=45), status="failed"),
        _dep("DEP-1005", "product-service", "PROD-403", ago(hours=4)),
        _dep("DEP-1020", "payment-service", "PAY-110", ago(hours=9), status="failed", env="staging"),
        _dep("DEP-1030", "order-service", "ORD-503", ago(hours=9), status="success", version="v9.3.0"),
        _dep("DEP-1014", "payment-service", "PAY-110", ago(days=3), status="failed"),
    ]
    runs = [
        _run("RUN-1", "PAY", "PAY-109", ago(hours=3), high=2),
        _run("RUN-2", "AUTH", "AUTH-306", ago(hours=12), status="failed", stage="unit_tests"),
        _run("RUN-3", "ORD", "ORD-503", ago(hours=9), status="passed", high=1, linked_dep="DEP-1030"),
        _run("RUN-4", "PAY", "PAY-107", (NOW + timedelta(days=2)).strftime(FMT), high=1),
    ]
    pages = [
        {"id": "ENG-005", "title": "SAML 2.0 SSO - Technical Design", "author": "Maya Chaya",
         "last_updated": day(0)},
        {"id": "API-001", "title": "Payment Service API Specification", "author": "Marcus Chen",
         "last_updated": day(1)},
    ]
    pulls = [
        {"repo_id": "payment-service", "number": 1, "status": "merged", "branch": "feature/PAY-1-gpay",
         "title": "Google Pay integration \u00e2\u20ac\u201d authored by Marcus Chen (Product Manager)",
         "description": "authored by Marcus Chen (Product Manager)", "created_at": day(3),
         "updated_at": day(1), "url": "https://git.example.test/p/1"},
        {"repo_id": "product-service", "number": 2, "status": "merged",
         "branch": "feature/PROD-406-migration-validator",
         "title": "PROD-406: Architecture design for deploy-safe migration checks \u00e2\u20ac\u201d authored by Lava Dev (Developer)",
         "description": "", "created_at": day(3), "updated_at": day(1), "url": "https://git.example.test/p/2"},
        {"repo_id": "cart-service", "number": 4, "status": "open", "branch": "feature/x",
         "title": "CART-12 and AUTH-7 shared session change", "description": "",
         "created_at": day(1), "updated_at": day(1), "url": "http://insecure.example.test/p/4"},
        {"repo_id": "order-service", "number": 5, "status": "closed", "branch": "feature/y",
         "title": "closed one", "description": "", "created_at": day(1), "updated_at": day(1)},
    ]
    commits = {svc: [] for svc in SERVICES.values()}
    commits["product-service"] = [
        {"id": "a", "message": "Merge pull request 'PROD-406' (#2)", "date": day(1)},
        {"id": "b", "message": "Add validator", "date": day(1)},
        {"id": "c", "message": "Add tests", "date": day(1)},
        {"id": "d", "message": "Initial commit", "date": day(30)},
    ]
    return {
        "stories": stories, "activity": activity, "developers": developers, "projects": projects,
        "sprints": [{"id": "PAY-3", "status": "active", "project_id": "PAY"}],
        "incidents": incidents, "deployments": deployments, "runs": runs, "pages": pages,
        "pulls": pulls, "commits": commits, "unavailable": [],
    }
