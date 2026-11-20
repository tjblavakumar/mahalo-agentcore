"""Computed sprint plan for the built-in JIRA_ROADMAP skill.

Pure module: no I/O, no clock, no randomness. ``compute_plan`` turns the five
source payloads (sprints, stories, developers, incidents, deployments) into a
frozen ``Plan``. ``render_plan`` writes every table and total from plan fields,
so a rendered number cannot differ from the computed one. The rendered plan is
the whole answer: no model writes any part of it.

Rules (the written spec that replaced steps 6-9 of the skill file):

* capacity = half-up mean of the recorded velocities of completed sprints;
* open story = status is not ``done``; groups: backlog, carry-over, planned,
  in flight (the active sprint, excluded from scheduling);
* order = lowest linked incident severity, priority, carry-over first, story id;
* fill Sprint A then Sprint B; a story is taken only if it fits;
* incidents link to stories only through linked_deployment -> linked_story;
* developers keep their assigned stories; unassigned stories go to the best
  skill match with headroom in that sprint. Capacity is per sprint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

SEVERITY_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
_UNKNOWN_SEVERITY_RANK = 5
_NO_INCIDENT_RANK = 99
PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_UNKNOWN_PRIORITY_RANK = 4
ACTIVE_INCIDENT_STATUSES = ("open", "investigating")


class PlanUnavailable(Exception):
    """The plan cannot be produced. ``message`` is the markdown shown to the user."""

    calls = 0  # source calls made before the failure (set by the fetcher)

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --------------------------------------------------------------------------- #
# Plan types
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CapacityInfo:
    velocities: tuple  # ((sprint_id, velocity), ...) in sprint order
    total: int
    count: int
    capacity: int


@dataclass(frozen=True)
class PlanRow:
    story_id: str
    title: str
    points: int
    priority: str
    assignee: Optional[str]
    assign_basis: str  # "" when the assignee was already set or none was found
    basis: str


@dataclass(frozen=True)
class SprintPlan:
    label: str  # "A" or "B"
    rows: tuple
    total: int


@dataclass(frozen=True)
class SkippedStory:
    story_id: str
    points: Optional[int]
    reason: str


@dataclass(frozen=True)
class DevLoad:
    developer_id: str
    load_a: int
    load_b: int
    capacity: Optional[int]
    over_a: int
    over_b: int


@dataclass(frozen=True)
class IncidentRow:
    incident_id: str
    severity: str
    status: str
    title: str
    state: str  # "no_link" | "deployment_missing" | "story_missing" | "done" | "open"
    detail: str
    story_id: Optional[str]
    is_risk: bool


@dataclass(frozen=True)
class Plan:
    project: str
    service: str
    capacity: CapacityInfo
    sprint_a: SprintPlan
    sprint_b: SprintPlan
    not_scheduled: tuple
    in_flight: tuple
    developers: tuple
    developer_capacity_total: int
    incidents: tuple
    data_notes: tuple


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _id_key(value) -> tuple:
    """Sort key ``(prefix, number)`` for ids such as PAY-110 or dev-6."""
    text = str(value)
    m = re.match(r"^(.*?)(\d+)$", text)
    if m:
        return (m.group(1), int(m.group(2)), text)
    return (text, 0, text)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _points(value) -> Optional[int]:
    return value if _is_int(value) and value >= 0 else None


def _rows(items) -> list:
    return [x for x in (items or []) if isinstance(x, dict)]


def _tokens(text: str) -> list:
    return re.findall(r"[a-z0-9]+", str(text).lower())


def skill_score(title: str, skills) -> tuple:
    """Return ``(score, matched_skills)`` for a story title against skill names.

    A skill matches when a title token of length >= 4 is a prefix of a part of the
    skill, or a skill part of length >= 4 is a prefix of a title token. Each skill
    counts once. ``cart-pricing`` has the parts ``cart`` and ``pricing``.
    """
    title_tokens = _tokens(title)
    matched = []
    for skill in skills or []:
        if not isinstance(skill, str):
            continue
        parts = _tokens(skill)
        hit = any(
            (len(t) >= 4 and p.startswith(t)) or (len(p) >= 4 and t.startswith(p))
            for t in title_tokens
            for p in parts
        )
        if hit:
            matched.append(skill)
    return len(matched), tuple(matched)


def _half_up_mean(total: int, count: int) -> int:
    return (2 * total + count) // (2 * count)


def _mean_text(total: int, count: int) -> str:
    return f"{total / count:.2f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------------------- #
# compute_plan
# --------------------------------------------------------------------------- #


def compute_plan(project, sprints, stories, developers, incidents, deployments) -> Plan:
    """Compute the whole plan. Raises ``PlanUnavailable`` when it cannot be sized."""
    from agent.skills import PROJECT_SERVICE  # local: keeps this module light to import

    service = PROJECT_SERVICE.get(project, "")
    notes: list = []

    proj_sprints = sorted(
        (s for s in _rows(sprints) if s.get("project_id", project) == project),
        key=lambda s: (str(s.get("start_date") or ""), _id_key(s.get("id", ""))),
    )
    proj_stories = sorted(
        (
            s for s in _rows(stories)
            if s.get("project_id", project) == project and isinstance(s.get("id"), str)
        ),
        key=lambda s: _id_key(s["id"]),
    )
    devs = sorted(
        (d for d in _rows(developers) if isinstance(d.get("id"), str)),
        key=lambda d: _id_key(d["id"]),
    )
    incs = sorted(
        (
            i for i in _rows(incidents)
            if isinstance(i.get("id"), str)
            and i.get("affected_service") == service
            and i.get("status") in ACTIVE_INCIDENT_STATUSES
        ),
        key=lambda i: _id_key(i["id"]),
    )
    deps = {
        d["id"]: d
        for d in _rows(deployments)
        if isinstance(d.get("id"), str) and d.get("service") == service
    }

    if not proj_sprints:
        raise PlanUnavailable(no_sprints_message(project))

    # --- capacity ---------------------------------------------------------
    velocities = tuple(
        (s["id"], s["velocity"])
        for s in proj_sprints
        if s.get("status") == "completed"
        and isinstance(s.get("id"), str)
        and _is_int(s.get("velocity"))
        and s["velocity"] >= 0
    )
    sprint_by_id = {s["id"]: s for s in proj_sprints if isinstance(s.get("id"), str)}

    open_stories = [s for s in proj_stories if s.get("status") != "done"]
    if not velocities:
        raise PlanUnavailable(capacity_unavailable_message(open_stories))
    v_total = sum(v for _, v in velocities)
    capacity = CapacityInfo(
        velocities=velocities,
        total=v_total,
        count=len(velocities),
        capacity=_half_up_mean(v_total, len(velocities)),
    )
    cap = capacity.capacity

    # --- incident -> deployment -> story chain ------------------------------
    story_by_id = {s["id"]: s for s in proj_stories}
    reached: dict = {}  # story id -> (severity rank, incident id, severity text)
    incident_rows_raw = []
    for inc in incs:
        sev = str(inc.get("severity", "")).strip().upper()
        rank = SEVERITY_RANK.get(sev)
        if rank is None:
            rank = _UNKNOWN_SEVERITY_RANK
            notes.append(f"Incident {inc['id']} has an unrecognised severity; it sorts after P4.")
        dep_id = inc.get("linked_deployment")
        story_id = None
        if not dep_id:
            state, detail = "no_link", "no recorded link"
        elif dep_id not in deps:
            state, detail = "deployment_missing", f"linked deployment {dep_id} not found"
        else:
            story_id = deps[dep_id].get("linked_story")
            if not story_id:
                state, detail = "no_link", "no recorded link"
                story_id = None
            elif story_id not in story_by_id:
                state, detail = "story_missing", f"linked story {story_id} not found in Jira"
            elif story_by_id[story_id].get("status") == "done":
                state, detail = "done", f"linked story {story_id} is Done"
            else:
                state, detail = "open", f"linked story {story_id}"
                best = reached.get(story_id)
                if best is None or (rank, _id_key(inc["id"])) < (best[0], _id_key(best[1])):
                    reached[story_id] = (rank, inc["id"], sev if rank != _UNKNOWN_SEVERITY_RANK else "severity unknown")
        incident_rows_raw.append((inc, sev, state, detail, story_id))

    # --- group, order -------------------------------------------------------
    candidates = []  # (sort key, story, group, basis)
    in_flight = []
    for s in open_stories:
        sid = s["id"]
        sprint_id = s.get("sprint_id")
        group = "backlog"
        if sprint_id:
            sprint = sprint_by_id.get(sprint_id)
            if sprint is None:
                notes.append(f"Story {sid} names sprint {sprint_id}, which is not recorded; treated as backlog.")
            elif sprint.get("status") == "completed":
                group = "carry-over"
            elif sprint.get("status") == "planned":
                group = "planned"
            elif sprint.get("status") == "active":
                group = "in flight"
            else:
                notes.append(f"Story {sid} is in sprint {sprint_id} with an unrecognised status; treated as backlog.")
        pts = _points(s.get("story_points"))
        if group == "in flight":
            in_flight.append(SkippedStory(sid, pts, "in flight, excluded"))
            continue
        prio = str(s.get("priority") or "").strip().lower()
        prio_rank = PRIORITY_RANK.get(prio)
        if prio_rank is None:
            prio_rank = _UNKNOWN_PRIORITY_RANK
            notes.append(f"Story {sid} has no recognised priority; it sorts after low.")
        if pts is None:
            notes.append(f"Story {sid} has no recorded points.")
        hit = reached.get(sid)
        inc_rank = hit[0] if hit else _NO_INCIDENT_RANK
        basis = f"incident {hit[2]} via {hit[1]}" if hit else group
        key = (inc_rank, prio_rank, 0 if group == "carry-over" else 1, _id_key(sid))
        candidates.append((key, s, prio if prio_rank != _UNKNOWN_PRIORITY_RANK else "unknown", basis, pts))
    candidates.sort(key=lambda c: c[0])

    # --- fill ---------------------------------------------------------------
    placed = {"A": [], "B": []}  # (story, priority text, basis, points)
    totals = {"A": 0, "B": 0}
    skipped = []
    for _key, s, prio, basis, pts in candidates:
        sid = s["id"]
        if pts is None:
            skipped.append(SkippedStory(sid, None, "points not recorded"))
            continue
        for label in ("A", "B"):
            if totals[label] + pts <= cap:
                totals[label] += pts
                placed[label].append((s, prio, basis, pts))
                break
        else:
            skipped.append(SkippedStory(sid, pts, "exceeds remaining capacity"))

    # --- developers ---------------------------------------------------------
    dev_cap: dict = {}
    for d in devs:
        cp = d.get("capacity_points")
        value = cp.get(project) if isinstance(cp, dict) else None
        dev_cap[d["id"]] = value if _is_int(value) and value >= 0 else None
    load = {d["id"]: {"A": 0, "B": 0} for d in devs}

    def _load_of(dev_id):
        return load.setdefault(dev_id, {"A": 0, "B": 0})

    # step 0: points of already-assigned stories, per sprint
    for label in ("A", "B"):
        for s, _p, _b, pts in placed[label]:
            assignee = s.get("assignee")
            if isinstance(assignee, str) and assignee:
                _load_of(assignee)[label] += pts
    # step 1: place unassigned stories against remaining headroom
    final = {"A": [], "B": []}
    for label in ("A", "B"):
        for s, prio, basis, pts in placed[label]:
            assignee = s.get("assignee")
            note = ""
            if not (isinstance(assignee, str) and assignee):
                ranked = []
                for d in devs:
                    c = dev_cap.get(d["id"])
                    if c is None:
                        continue
                    headroom = c - load[d["id"]][label]
                    if headroom < pts:
                        continue
                    score, matched = skill_score(s.get("title", ""), d.get("skills"))
                    ranked.append((-score, -headroom, _id_key(d["id"]), d["id"], matched))
                if ranked:
                    ranked.sort()
                    _s, _h, _k, dev_id, matched = ranked[0]
                    assignee = dev_id
                    load[dev_id][label] += pts
                    note = f"skill match: {', '.join(matched)}" if matched else "capacity only"
                else:
                    assignee = None
                    note = "no developer has capacity"
            final[label].append(
                PlanRow(
                    story_id=s["id"],
                    title=str(s.get("title", "")),
                    points=pts,
                    priority=prio,
                    assignee=assignee,
                    assign_basis=note,
                    basis=basis,
                )
            )

    dev_rows = []
    for dev_id in sorted(load, key=_id_key):
        c = dev_cap.get(dev_id)
        la, lb = load[dev_id]["A"], load[dev_id]["B"]
        dev_rows.append(
            DevLoad(
                developer_id=dev_id,
                load_a=la,
                load_b=lb,
                capacity=c,
                over_a=max(la - c, 0) if c is not None else 0,
                over_b=max(lb - c, 0) if c is not None else 0,
            )
        )

    # --- incidents ----------------------------------------------------------
    scheduled_in = {}
    for label in ("A", "B"):
        for row in final[label]:
            scheduled_in[row.story_id] = label
    skipped_by_id = {x.story_id: x for x in skipped}
    flight_ids = {x.story_id for x in in_flight}
    inc_rows = []
    for inc, sev, state, detail, story_id in incident_rows_raw:
        if state == "open":
            if story_id in scheduled_in:
                detail = f"{detail}, scheduled in Sprint {scheduled_in[story_id]}"
            elif story_id in flight_ids:
                detail = f"{detail}, in flight, excluded"
            elif story_id in skipped_by_id:
                detail = f"{detail}, not scheduled ({skipped_by_id[story_id].reason})"
        inc_rows.append(
            IncidentRow(
                incident_id=inc["id"],
                severity=sev or "unknown",
                status=str(inc.get("status", "")),
                title=str(inc.get("title", "")),
                state=state,
                detail=detail,
                story_id=story_id if state in ("open", "done") else None,
                is_risk=state != "open",
            )
        )

    return Plan(
        project=project,
        service=service,
        capacity=capacity,
        sprint_a=SprintPlan("A", tuple(final["A"]), totals["A"]),
        sprint_b=SprintPlan("B", tuple(final["B"]), totals["B"]),
        not_scheduled=tuple(skipped),
        in_flight=tuple(in_flight),
        developers=tuple(dev_rows),
        developer_capacity_total=sum(c for c in dev_cap.values() if c is not None),
        incidents=tuple(inc_rows),
        data_notes=tuple(notes),
    )


# --------------------------------------------------------------------------- #
# Fixed messages
# --------------------------------------------------------------------------- #


def source_unreadable_message(source: str) -> str:
    return f"Roadmap could not be computed: {source} could not be read. Nothing was changed. Try again."


def no_sprints_message(project: str) -> str:
    return f"No sprints are recorded for {project}."


def capacity_unavailable_message(open_stories) -> str:
    lines = ["Capacity cannot be sized: no completed sprint has a recorded velocity."]
    rows = [s for s in open_stories if isinstance(s, dict) and isinstance(s.get("id"), str)]
    if rows:
        lines += ["", "Open stories (not planned):", "", "| Story | Points | Priority |", "| --- | --- | --- |"]
        for s in sorted(rows, key=lambda s: _id_key(s["id"])):
            pts = _points(s.get("story_points"))
            lines.append(
                f"| {_cell(s['id'])} | {'not recorded' if pts is None else pts} "
                f"| {_cell(s.get('priority') or 'not recorded')} |"
            )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _cell(value) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    return text.strip()


def _addition(points) -> str:
    points = list(points)
    if not points:
        return "no stories = 0"
    return f"{' + '.join(str(p) for p in points)} = {sum(points)}"


def _assignee_cell(row: PlanRow) -> str:
    if row.assignee is None:
        return row.assign_basis or "unassigned"
    if row.assign_basis:
        return f"{row.assignee} ({row.assign_basis})"
    return row.assignee


def _render_sprint(sprint: SprintPlan, cap: int) -> list:
    out = [
        f"## Sprint {sprint.label} (proposed): {sprint.total} of {cap} points",
        "",
        "| Story | Title | Points | Priority | Assignee | Basis |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in sprint.rows:
        out.append(
            f"| {_cell(r.story_id)} | {_cell(r.title)} | {r.points} | {_cell(r.priority)} "
            f"| {_cell(_assignee_cell(r))} | {_cell(r.basis)} |"
        )
    out.append(f"| **Total** | | {sprint.total} | | | |")
    out += ["", f"Addition: {_addition(r.points for r in sprint.rows)}", ""]
    return out


def _points_text(points: Optional[int]) -> str:
    return "not recorded" if points is None else str(points)


def render_plan(plan: Plan) -> str:
    """Render the whole plan as markdown (LF only)."""
    cap = plan.capacity
    out = ["## Capacity", "", "Completed sprints with a recorded velocity:"]
    out += [f"- {sid}: {vel}" for sid, vel in cap.velocities]
    out += [
        "",
        f"Addition: {' + '.join(str(v) for _, v in cap.velocities)} = {cap.total}",
        f"Mean: {cap.total} / {cap.count} = {_mean_text(cap.total, cap.count)}"
        + ("" if cap.total % cap.count == 0 else f", rounded half up to {cap.capacity}"),
        f"Sprint capacity: {cap.capacity}",
        "",
    ]
    out += _render_sprint(plan.sprint_a, cap.capacity)
    out += _render_sprint(plan.sprint_b, cap.capacity)

    if plan.not_scheduled or plan.in_flight:
        out += ["## Not scheduled", "", "| Story | Points | Reason |", "| --- | --- | --- |"]
        for x in plan.not_scheduled + plan.in_flight:
            out.append(f"| {_cell(x.story_id)} | {_points_text(x.points)} | {_cell(x.reason)} |")
        out.append("")

    if plan.developers:
        out += [
            "## Developer load (Inference)",
            "",
            "| Developer | Sprint A | Sprint B | Capacity | Over by |",
            "| --- | --- | --- | --- | --- |",
        ]
        for d in plan.developers:
            over = []
            if d.over_a:
                over.append(f"Sprint A {d.over_a}")
            if d.over_b:
                over.append(f"Sprint B {d.over_b}")
            out.append(
                f"| {_cell(d.developer_id)} | {d.load_a} | {d.load_b} "
                f"| {'not recorded' if d.capacity is None else d.capacity} "
                f"| {', '.join(over) if over else '-'} |"
            )
        out += [
            "",
            f"Developer capacity total {plan.developer_capacity_total} vs sprint capacity {cap.capacity}",
            "",
        ]

    if plan.incidents:
        out += ["## Incidents and risks", ""]
        for i in plan.incidents:
            tail = " No open Jira story addresses this." if i.is_risk else ""
            out.append(f"- {i.incident_id} ({i.severity}, {i.status}): {i.detail}.{tail}")
        out.append("")

    if plan.data_notes:
        out += ["## Data notes", ""]
        out += [f"- {n}" for n in plan.data_notes]
        out.append("")

    return "\n".join(out).rstrip("\n") + "\n"

