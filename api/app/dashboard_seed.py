"""Static precomputed per-persona default dashboards (design §3.4).

Returned by ``GET /dashboard/widgets`` when a persona has no stored item, so a
first login is never empty. Each default is a real renderable ``VizSpec`` (same
envelope as §1.2) with a sensible ``lg`` grid layout. Numbers are hand-authored
to look plausible against the seed projects (PAY/CART/AUTH/PROD/ORD); they do
NOT need to match live mock data (user approved "your assumption is good to
start"). ``default_widgets_for`` returns DEEP COPIES so callers can't mutate the
module constants.
"""

from __future__ import annotations

import copy

# PM (pm, Marcus Chen): two bars.
_PM_WIDGETS: list[dict] = [
    {
        "id": "seed-pm-story-points",
        "spec": {
            "type": "bar",
            "title": "Story points by sprint",
            "xKey": "sprint",
            "series": [
                {"name": "Committed", "dataKey": "committed"},
                {"name": "Completed", "dataKey": "completed"},
            ],
            "data": [
                {"sprint": "S-21", "committed": 40, "completed": 34},
                {"sprint": "S-22", "committed": 38, "completed": 38},
                {"sprint": "S-23", "committed": 42, "completed": 36},
                {"sprint": "S-24", "committed": 36, "completed": 33},
                {"sprint": "S-25", "committed": 44, "completed": 41},
                {"sprint": "S-26", "committed": 40, "completed": 39},
            ],
        },
        "layout": {"x": 0, "y": 0, "w": 6, "h": 8},
    },
    {
        "id": "seed-pm-open-prs",
        "spec": {
            "type": "bar",
            "title": "Open PRs by project",
            "xKey": "project",
            "series": [{"name": "Open PRs", "dataKey": "open"}],
            "data": [
                {"project": "PAY", "open": 7},
                {"project": "CART", "open": 4},
                {"project": "AUTH", "open": 3},
                {"project": "PROD", "open": 6},
                {"project": "ORD", "open": 5},
            ],
        },
        "layout": {"x": 6, "y": 0, "w": 6, "h": 8},
    },
]

# Dev (dev, Lava Dev): a table + a bar.
_DEV_WIDGETS: list[dict] = [
    {
        "id": "seed-dev-open-prs",
        "spec": {
            "type": "table",
            "title": "My open PRs",
            "columns": [
                {"key": "repo", "label": "Repository"},
                {"key": "title", "label": "Title"},
                {"key": "status", "label": "Status"},
            ],
            "rows": [
                {
                    "repo": "payment-service",
                    "title": "feat: Apple Pay support",
                    "status": "In Review",
                },
                {
                    "repo": "cart-service",
                    "title": "fix: coupon rounding",
                    "status": "Open",
                },
                {
                    "repo": "auth-service",
                    "title": "chore: rotate JWT keys",
                    "status": "Open",
                },
            ],
        },
        "layout": {"x": 0, "y": 0, "w": 6, "h": 8},
    },
    {
        "id": "seed-dev-stories-by-status",
        "spec": {
            "type": "bar",
            "title": "My stories by status",
            "xKey": "status",
            "series": [{"name": "Count", "dataKey": "count"}],
            "data": [
                {"status": "To Do", "count": 5},
                {"status": "In Progress", "count": 3},
                {"status": "In Review", "count": 2},
                {"status": "Done", "count": 8},
            ],
        },
        "layout": {"x": 6, "y": 0, "w": 6, "h": 8},
    },
]

# Exec (exec, David Kim): the ONE concrete single-series health bar (§3.4).
_EXEC_WIDGETS: list[dict] = [
    {
        "id": "seed-exec-delivery-health",
        "spec": {
            "type": "bar",
            "title": "Delivery health by project",
            "xKey": "project",
            "series": [{"name": "Health score", "dataKey": "health"}],
            "data": [
                {"project": "PAY", "health": 82},
                {"project": "CART", "health": 74},
                {"project": "AUTH", "health": 68},
                {"project": "PROD", "health": 91},
                {"project": "ORD", "health": 57},
            ],
        },
        "layout": {"x": 0, "y": 0, "w": 12, "h": 8},
    },
]

_DEFAULTS: dict[str, list[dict]] = {
    "pm": _PM_WIDGETS,
    "dev": _DEV_WIDGETS,
    "exec": _EXEC_WIDGETS,
}


def default_widgets_for(persona_id: str) -> list[dict]:
    """Return DEEP COPIES of the static default widgets for ``persona_id``.

    Unknown persona ids fall back to the developer set (matches the safe default
    in ``api/app/auth.py``). Copies protect the module constants from mutation.
    """
    widgets = _DEFAULTS.get(persona_id, _DEV_WIDGETS)
    return copy.deepcopy(widgets)
