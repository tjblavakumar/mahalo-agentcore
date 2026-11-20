"""Computed roadmap plan: planner rules and renderer.

Inputs come from the real seed (``seed_items()`` applies the date shift and the
deployment re-links), so the golden numbers below are the seed's, not invented.
"""

from __future__ import annotations

import copy
import os
import random
import sys

import pytest

_TOOLS_LAMBDAS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tools-lambdas",
)
if _TOOLS_LAMBDAS not in sys.path:
    sys.path.append(_TOOLS_LAMBDAS)

from jira import routes as jira_routes  # noqa: E402
from servicenow import routes as snow_routes  # noqa: E402

from agent import roadmap, skills  # noqa: E402


def _seed(project):
    j = list(jira_routes.seed_items())
    s = list(snow_routes.seed_items())
    service = skills.PROJECT_SERVICE[project]
    rec = lambda items, pk: [i["record"] for i in items if i["pk"] == pk]  # noqa: E731
    return {
        "sprints": [x for x in rec(j, "SPRINT") if x["project_id"] == project],
        "stories": [x for x in rec(j, "STORY") if x["project_id"] == project],
        "developers": rec(j, "DEVELOPER"),
        "incidents": [x for x in rec(s, "INCIDENT") if x["affected_service"] == service],
        "deployments": [x for x in rec(s, "DEPLOYMENT") if x["service"] == service],
    }


def _plan(project, src=None):
    src = src or _seed(project)
    return roadmap.compute_plan(
        project, src["sprints"], src["stories"], src["developers"],
        src["incidents"], src["deployments"],
    )


def _ids(sprint):
    return [r.story_id for r in sprint.rows]


# --- seed invariants ---------------------------------------------------------- #


@pytest.mark.parametrize("project", ["PAY", "CART"])
def test_sprint_invariants(project):
    src = _seed(project)
    plan = _plan(project, src)
    cap = plan.capacity.capacity
    for sprint in (plan.sprint_a, plan.sprint_b):
        assert sprint.total == sum(r.points for r in sprint.rows)
        assert sprint.total <= cap
    placed = _ids(plan.sprint_a) + _ids(plan.sprint_b)
    assert len(placed) == len(set(placed))
    by_id = {s["id"]: s for s in src["stories"]}
    sprint_status = {s["id"]: s["status"] for s in src["sprints"]}
    for sid in placed:
        story = by_id[sid]
        assert story["status"] != "done"
        assert sprint_status.get(story["sprint_id"]) != "active"
    vels = [s["velocity"] for s in src["sprints"] if s["status"] == "completed"]
    assert cap == int((2 * sum(vels) + len(vels)) // (2 * len(vels)))


def test_capacity_values():
    assert [v for _, v in _plan("PAY").capacity.velocities] == [26, 29, 31, 34]
    assert _plan("PAY").capacity.capacity == 30
    assert sorted(v for _, v in _plan("CART").capacity.velocities) == [24, 26, 28]
    assert _plan("CART").capacity.capacity == 26


def test_pay_golden():
    plan = _plan("PAY")
    assert _ids(plan.sprint_a) == ["PAY-110", "PAY-098", "PAY-099"]
    assert plan.sprint_a.total == 29
    assert _ids(plan.sprint_b) == ["PAY-092", "PAY-094", "PAY-085", "PAY-091", "PAY-095"]
    assert plan.sprint_b.total == 26
    assert {x.story_id for x in plan.not_scheduled} == {"PAY-093", "PAY-109"}
    assert {x.story_id for x in plan.in_flight} == {"PAY-105", "PAY-107", "PAY-108"}
    assert plan.sprint_a.rows[0].basis == "incident P2 via INC-2012"


def test_cart_golden():
    plan = _plan("CART")
    assert _ids(plan.sprint_a) == ["CART-208", "CART-210", "CART-112", "CART-209"]
    assert plan.sprint_a.total == 26
    assert _ids(plan.sprint_b) == ["CART-207"]
    assert plan.sprint_b.total == 5


# --- determinism -------------------------------------------------------------- #


def test_deterministic_under_shuffle():
    src = _seed("PAY")
    base = _plan("PAY", src)
    assert base == _plan("PAY", src)
    rng = random.Random(7)
    for _ in range(5):
        shuffled = copy.deepcopy(src)
        for rows in shuffled.values():
            rng.shuffle(rows)
        assert _plan("PAY", shuffled) == base


# --- developers --------------------------------------------------------------- #


def test_developer_loads_pay():
    plan = _plan("PAY")
    loads = {d.developer_id: d for d in plan.developers}
    assert loads["dev-6"].load_a == 24 and loads["dev-6"].capacity == 8
    assert loads["dev-6"].over_a == 16
    assert loads["dev-5"].load_b == 5 and loads["dev-5"].over_b == 2
    assert loads["dev-4"].capacity is None
    assert plan.developer_capacity_total == 35
    # per-developer sums equal the stories named for them
    for label, sprint in (("a", plan.sprint_a), ("b", plan.sprint_b)):
        for dev_id, d in loads.items():
            named = sum(r.points for r in sprint.rows if r.assignee == dev_id)
            assert getattr(d, f"load_{label}") == named


def test_unassigned_never_goes_to_developer_without_headroom():
    plan = _plan("PAY")
    loads = {d.developer_id: d for d in plan.developers}
    src = _seed("PAY")
    assigned_before = {s["id"] for s in src["stories"] if s["assignee"]}
    for sprint in (plan.sprint_a, plan.sprint_b):
        for r in sprint.rows:
            if r.story_id in assigned_before or r.assignee is None:
                continue
            d = loads[r.assignee]
            assert d.capacity is not None
            # points placed by code in this sprint fit in what the assigned work left
            placed = sum(
                x.points for x in sprint.rows
                if x.assignee == r.assignee and x.story_id not in assigned_before
            )
            assigned = sum(
                x.points for x in sprint.rows
                if x.assignee == r.assignee and x.story_id in assigned_before
            )
            assert placed <= max(d.capacity - assigned, 0)
            assert r.assign_basis in ("capacity only",) or r.assign_basis.startswith("skill match: ")


def _mini(stories, devs, sprints=None, incidents=(), deployments=()):
    sprints = sprints if sprints is not None else [
        {"id": "X-S1", "project_id": "PAY", "status": "completed", "velocity": 10, "start_date": "2026-01-01"},
    ]
    return {
        "sprints": sprints, "stories": stories, "developers": devs,
        "incidents": list(incidents), "deployments": list(deployments),
    }


def _story(sid, points, **kw):
    base = {
        "id": sid, "project_id": "PAY", "sprint_id": None, "title": "Something",
        "status": "todo", "priority": "medium", "story_points": points, "assignee": None,
    }
    base.update(kw)
    return base


def _dev(did, cap, skills_=()):
    return {"id": did, "skills": list(skills_), "capacity_points": {} if cap is None else {"PAY": cap}}


def test_assigned_points_counted_before_unassigned_placement():
    # PAY-1 (unassigned, ordered first) must see PAY-2's assigned 6 points for dev-1.
    stories = [
        _story("PAY-1", 3, priority="high"),
        _story("PAY-2", 6, priority="low", assignee="dev-1"),
    ]
    devs = [_dev("dev-1", 10), _dev("dev-2", 5)]
    plan = _plan("PAY", _mini(stories, devs))
    row = {r.story_id: r for r in plan.sprint_a.rows}
    assert row["PAY-2"].assignee == "dev-1"
    # dev-1 has 10 - 6 = 4 left (dev-2 has 5), so the larger headroom is dev-2
    assert row["PAY-1"].assignee == "dev-2"


def test_no_developer_has_capacity():
    plan = _plan("PAY", _mini([_story("PAY-1", 5)], [_dev("dev-1", 3), _dev("dev-4", None)]))
    row = plan.sprint_a.rows[0]
    assert row.assignee is None and row.assign_basis == "no developer has capacity"


def test_developer_ranking_skill_then_headroom_then_id():
    stories = [_story("PAY-1", 2, title="Webhooks retry handling")]
    devs = [_dev("dev-1", 9), _dev("dev-2", 5, ["webhooks"]), _dev("dev-3", 5, ["webhooks"])]
    row = _plan("PAY", _mini(stories, devs)).sprint_a.rows[0]
    assert row.assignee == "dev-2" and row.assign_basis == "skill match: webhooks"
    row = _plan("PAY", _mini([_story("PAY-1", 2)], [_dev("dev-1", 5), _dev("dev-2", 9)])).sprint_a.rows[0]
    assert row.assignee == "dev-2" and row.assign_basis == "capacity only"
    row = _plan("PAY", _mini([_story("PAY-1", 2)], [_dev("dev-3", 5), _dev("dev-2", 5)])).sprint_a.rows[0]
    assert row.assignee == "dev-2"


def test_skill_score_pinned_cases():
    assert skill_score("Webhooks retry handling", ["webhooks"]) == 1
    assert skill_score("Partial refund support", ["webhooks"]) == 0
    assert roadmap._tokens("cart-pricing") == ["cart", "pricing"]
    assert skill_score("Pricing rules", ["cart-pricing"]) == 1
    assert skill_score("Fix the cart", ["cart-pricing"]) == 1  # "cart" has 4 letters and is a part
    assert skill_score("Anything", [None, 3]) == 0


def skill_score(title, skills_):
    return roadmap.skill_score(title, skills_)[0]


# --- incidents ---------------------------------------------------------------- #


def test_incident_states_pay():
    plan = _plan("PAY")
    inc = {i.incident_id: i for i in plan.incidents}
    assert inc["INC-2002"].detail == "no recorded link" and inc["INC-2002"].is_risk
    assert inc["INC-2005"].detail == "linked story PAY-601 not found in Jira" and inc["INC-2005"].is_risk
    assert not inc["INC-2006"].is_risk and "in flight" in inc["INC-2006"].detail
    for risk in ("INC-2008", "INC-2009", "INC-2011"):
        assert inc[risk].is_risk and inc[risk].state == "done"
    assert not inc["INC-2012"].is_risk and "Sprint A" in inc["INC-2012"].detail
    assert "INC-2007" not in inc  # resolved


def test_incident_cart_no_link_and_never_by_title():
    plan = _plan("CART")
    inc = {i.incident_id: i for i in plan.incidents}
    assert inc["INC-2004"].detail == "no recorded link"
    src = _seed("CART")
    for i in src["incidents"]:
        i["linked_deployment"] = None
        i["title"] = "Problem with CART-208 pricing"
    plan = _plan("CART", src)
    assert all(i.is_risk and i.story_id is None for i in plan.incidents)
    assert all(r.basis != "incident" and not r.basis.startswith("incident") for r in plan.sprint_a.rows)


def test_incident_edges():
    stories = [_story("PAY-1", 3), _story("PAY-2", 3), _story("PAY-3", 40)]
    devs = [_dev("dev-1", 10)]
    incs = [
        {"id": "INC-1", "severity": "P3", "status": "open", "affected_service": "payment-service", "linked_deployment": "DEP-1"},
        {"id": "INC-2", "severity": "P1", "status": "open", "affected_service": "payment-service", "linked_deployment": "DEP-2"},
        {"id": "INC-3", "severity": "P9", "status": "open", "affected_service": "payment-service", "linked_deployment": "DEP-3"},
        {"id": "INC-4", "severity": "P1", "status": "resolved", "affected_service": "payment-service", "linked_deployment": "DEP-1"},
        {"id": "INC-5", "severity": "P2", "status": "open", "affected_service": "payment-service", "linked_deployment": "DEP-404"},
        {"id": "INC-6", "severity": "P2", "status": "open", "affected_service": "payment-service", "linked_deployment": "DEP-4"},
    ]
    deps = [
        {"id": "DEP-1", "service": "payment-service", "linked_story": "PAY-1"},
        {"id": "DEP-2", "service": "payment-service", "linked_story": "PAY-1"},
        {"id": "DEP-3", "service": "payment-service", "linked_story": "PAY-2"},
        {"id": "DEP-4", "service": "payment-service", "linked_story": "PAY-3"},
    ]
    plan = _plan("PAY", _mini(stories, devs, incidents=incs, deployments=deps))
    inc = {i.incident_id: i for i in plan.incidents}
    assert "INC-4" not in inc
    assert inc["INC-5"].detail == "linked deployment DEP-404 not found"
    assert "not scheduled" in inc["INC-6"].detail and not inc["INC-6"].is_risk
    # lowest severity wins when several incidents reach one story
    assert plan.sprint_a.rows[0].story_id == "PAY-1"
    assert plan.sprint_a.rows[0].basis == "incident P1 via INC-2"
    # unknown severity sorts after P4 but before stories with no incident
    assert plan.sprint_a.rows[1].story_id == "PAY-2"
    assert any("INC-3" in n for n in plan.data_notes)


def test_deployment_of_another_service_is_not_found():
    stories = [_story("PAY-1", 3)]
    incs = [{"id": "INC-1", "severity": "P1", "status": "open", "affected_service": "payment-service", "linked_deployment": "DEP-1"}]
    deps = [{"id": "DEP-1", "service": "cart-service", "linked_story": "PAY-1"}]
    plan = _plan("PAY", _mini(stories, [_dev("dev-1", 9)], incidents=incs, deployments=deps))
    assert plan.incidents[0].detail == "linked deployment DEP-1 not found"


# --- edges -------------------------------------------------------------------- #


def test_no_sprints_and_no_velocity():
    with pytest.raises(roadmap.PlanUnavailable) as e:
        _plan("PAY", _mini([], [], sprints=[]))
    assert e.value.message == "No sprints are recorded for PAY."
    sprints = [{"id": "PAY-S1", "project_id": "PAY", "status": "completed", "velocity": None}]
    with pytest.raises(roadmap.PlanUnavailable) as e:
        _plan("PAY", _mini([_story("PAY-1", 3, priority="high")], [], sprints=sprints))
    msg = e.value.message
    assert msg.startswith("Capacity cannot be sized: no completed sprint has a recorded velocity.")
    assert "| PAY-1 | 3 | high |" in msg and "\r" not in msg


def test_half_up_mean():
    sprints = [
        {"id": "PAY-S1", "project_id": "PAY", "status": "completed", "velocity": 28, "start_date": "1"},
        {"id": "PAY-S2", "project_id": "PAY", "status": "completed", "velocity": 29, "start_date": "2"},
    ]
    plan = _plan("PAY", _mini([], [], sprints=sprints))
    assert plan.capacity.capacity == 29  # 28.5 rounds up (round() would give 28)
    assert "28.5" in roadmap.render_plan(plan)


def test_point_edges_and_priority_sprint_notes():
    stories = [
        _story("PAY-1", 0),
        _story("PAY-2", None),
        _story("PAY-3", 11),  # larger than capacity 10
        _story("PAY-4", 2, priority="urgent"),
        _story("PAY-5", 2, sprint_id="NOPE"),
        _story("PAY-6", 2.5),
        _story("PAY-7", 2, status="done"),
    ]
    plan = _plan("PAY", _mini(stories, [_dev("dev-1", 10)]))
    sched = {r.story_id for r in plan.sprint_a.rows + plan.sprint_b.rows}
    assert sched == {"PAY-1", "PAY-4", "PAY-5"}
    reasons = {x.story_id: x.reason for x in plan.not_scheduled}
    assert reasons == {
        "PAY-2": "points not recorded", "PAY-6": "points not recorded",
        "PAY-3": "exceeds remaining capacity",
    }
    notes = " ".join(plan.data_notes)
    assert "PAY-2" in notes and "PAY-4" in notes and "PAY-5" in notes
    assert plan.sprint_a.rows[-1].story_id in ("PAY-4", "PAY-5")  # unknown priority sorts last


def test_linked_open_story_not_scheduled_listed_in_incidents():
    stories = [_story("PAY-1", 99)]
    incs = [{"id": "INC-1", "severity": "P1", "status": "open", "affected_service": "payment-service", "linked_deployment": "DEP-1"}]
    deps = [{"id": "DEP-1", "service": "payment-service", "linked_story": "PAY-1"}]
    plan = _plan("PAY", _mini(stories, [], incidents=incs, deployments=deps))
    assert plan.incidents[0].detail == "linked story PAY-1, not scheduled (exceeds remaining capacity)"


# --- renderer ----------------------------------------------------------------- #


@pytest.mark.parametrize("project", ["PAY", "CART"])
def test_render_totals_agree(project):
    import re

    plan = _plan(project)
    md = roadmap.render_plan(plan)
    assert "\r" not in md
    for sprint in (plan.sprint_a, plan.sprint_b):
        head = re.search(
            rf"## Sprint {sprint.label} \(proposed\): (\d+) of {plan.capacity.capacity} points", md
        )
        assert int(head.group(1)) == sprint.total
        section = md.split(f"## Sprint {sprint.label} ")[1].split("\n## ")[0]
        total_row = re.search(r"\| \*\*Total\*\* \| \| (\d+) \|", section)
        assert int(total_row.group(1)) == sprint.total
        addition = re.search(r"Addition: (.*) = (\d+)", section)
        assert int(addition.group(2)) == sprint.total
        assert sum(int(x) for x in addition.group(1).split(" + ")) == sprint.total


def test_render_section_order_and_headers():
    md = roadmap.render_plan(_plan("PAY"))
    heads = [line for line in md.split("\n") if line.startswith("## ")]
    assert heads == [
        "## Capacity",
        "## Sprint A (proposed): 29 of 30 points",
        "## Sprint B (proposed): 26 of 30 points",
        "## Not scheduled",
        "## Developer load (Inference)",
        "## Incidents and risks",
    ]
    assert "| Story | Title | Points | Priority | Assignee | Basis |" in md
    assert "| Developer | Sprint A | Sprint B | Capacity | Over by |" in md
    assert "Addition: 26 + 29 + 31 + 34 = 120" in md
    assert "Mean: 120 / 4 = 30" in md and "Sprint capacity: 30" in md
    assert "Addition: 21 + 5 + 3 = 29" in md
    assert "Developer capacity total 35 vs sprint capacity 30" in md
    assert "| dev-4 | 0 | 0 | not recorded | - |" in md
    assert "PAY-105 | 8 | in flight, excluded" in md


def test_render_minimal_plan_keeps_capacity_and_sprints():
    plan = _plan("PAY", _mini([], []))
    md = roadmap.render_plan(plan)
    heads = [line for line in md.split("\n") if line.startswith("## ")]
    assert heads == [
        "## Capacity", "## Sprint A (proposed): 0 of 10 points", "## Sprint B (proposed): 0 of 10 points",
    ]
    assert "Addition: no stories = 0" in md and "\r" not in md


def test_render_escapes_pipes_in_titles():
    plan = _plan("PAY", _mini([_story("PAY-1", 2, title="a | b\nc")], [_dev("dev-1", 5)]))
    assert "a \\| b c" in roadmap.render_plan(plan)

