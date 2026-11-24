"""Deterministic per-persona ranking, window tiers and snapshot for the login briefing.

Pure functions: no I/O and no clock reads. ``now`` is always passed in, so the
24-hour window, the future-event exclusion and the day-precision rule are owned
here and nowhere else. The only sort key is ``(-score, -ts, ref)``.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.briefing.models import TS_FORMAT, Event, to_item
from app.briefing.sources import PROJECT_SERVICE, SERVICE_PROJECT

TOP_N = 5
MAX_ITEMS = 150
MAX_EARLIER = 50
WINDOW = timedelta(hours=24)
EARLIER_WINDOW = timedelta(days=7)
BURST_MIN = 3
ARCHITECT_ID = "dev-7"
P12 = ("P1", "P2")

LABELS = {
    "Jira": "Demo data",
    "ServiceNow": "Demo data",
    "Confluence": "Demo data",
    "CI/CD": "Seeded demo data. Not a live pipeline run.",
    "Git": "Real Gitea. One admin user; the persona appears in PR and commit titles.",
}

HEADLINE_RECENT = "Since yesterday"
HEADLINE_WIDENED = "Nothing new in the last 24 hours. Most recent activity:"
HEADLINE_SNAPSHOT = "Quiet since yesterday. Where things stand:"


class BriefingUnavailable(Exception):
    """No event line and no snapshot line could be produced."""


@dataclass(frozen=True)
class Ctx:
    persona: str
    dev_id: str
    my_projects: frozenset
    my_services: frozenset


def make_ctx(persona: str, dev_id: str, raw: dict[str, Any]) -> Ctx:
    if persona in ("exec", "arch"):
        projects = frozenset(PROJECT_SERVICE)
    else:
        projects = {
            s.get("project_id")
            for s in raw["stories"]
            if s.get("assignee") == dev_id and isinstance(s.get("project_id"), str)
        }
        if persona == "pm":
            projects |= {
                p.get("id") for p in raw["projects"]
                if p.get("lead") == dev_id and isinstance(p.get("id"), str)
            }
        projects = frozenset(p for p in projects if p in PROJECT_SERVICE)
    return Ctx(persona, dev_id, projects, frozenset(PROJECT_SERVICE[p] for p in projects))


# ----------------------------------------------------------------------- scoring


def _dev(c: Ctx, e: Event) -> Optional[int]:
    k = e.kind
    mine = e.story is not None and e.story_assignee == c.dev_id
    if k in ("assigned", "created") and e.to == c.dev_id:
        return 100
    if k == "comment" and mine:
        return 95 if e.actor == ARCHITECT_ID else 90
    if k in ("deploy_bad", "run_failed", "finding") and mine:
        return 88
    if k == "status" and mine:
        return 80
    if e.project not in c.my_projects:
        return None
    if k == "deploy_bad":
        return 72 if e.env == "production" else None
    if k == "incident_open":
        return 70 if e.severity in P12 else 55
    if k == "finding":
        return 70
    if k == "run_failed":
        return 65
    return {"pr_merged": 62, "pr_open": 60, "incident_resolved": 40, "commits": 40}.get(k)


def _pm(c: Ctx, e: Event) -> Optional[int]:
    k = e.kind
    if e.project not in c.my_projects:
        return None
    if k in ("assigned", "created", "status", "comment"):
        return 85
    if k == "incident_open":
        return 95 if e.severity in P12 else 70
    if k == "deploy_bad":
        return 80 if e.env == "production" else None
    return {
        "pr_open": 78, "pr_merged": 75, "run_failed": 60, "finding": 58,
        "incident_resolved": 45, "commits": 20,
    }.get(k)


def _exec(c: Ctx, e: Event) -> Optional[int]:
    k = e.kind
    if k == "incident_open":
        return {"P1": 100, "P2": 92}.get(e.severity or "")
    if k == "incident_resolved":
        return {"P1": 80, "P2": 70}.get(e.severity or "")
    if k == "deploy_bad":
        return 90 if e.env == "production" else None
    if k == "deploy_ok":
        return 30
    return {"finding": 68, "run_failed": 66, "pr_merged": 35}.get(k)


def _arch(c: Ctx, e: Event) -> Optional[int]:
    k = e.kind
    if k == "finding":
        return 100
    if k == "comment":
        return 95 if e.design else 30
    if k == "deploy_bad":
        return 90 if e.env == "production" else None
    if k in ("pr_open", "pr_merged"):
        return 89 if e.design else 45
    if k == "page":
        return 88 if e.design else 55
    if k == "incident_open":
        return 86 if e.severity in P12 else 62
    if k == "incident_resolved":
        return 50
    if k == "status":
        return 25
    return None


_SCORERS = {"dev": _dev, "pm": _pm, "exec": _exec, "arch": _arch}


def score(ctx: Ctx, e: Event) -> Optional[int]:
    """Score one event for the persona; ``None`` drops it."""
    return _SCORERS[ctx.persona](ctx, e)


# -------------------------------------------------------------------- time rules


def effective_ts(e: Event, now: datetime) -> tuple[Optional[datetime], Optional[str]]:
    """Return ``(ts, day_label)``; ``ts`` is ``None`` for an unusable or future-dated day."""
    if e.precision == "minute":
        return datetime.strptime(e.when, TS_FORMAT).replace(tzinfo=timezone.utc), None
    day = datetime.strptime(e.when, "%Y-%m-%d").date()
    today = now.date()
    if day > today:
        return None, None
    if day == today:
        return now, "today"
    ts = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)
    return ts, ("yesterday" if day == today - timedelta(days=1) else None)


def _sort_key(e: Event) -> tuple:
    return (-e.score, -e.ts.timestamp(), e.ref_id)


# ------------------------------------------------------------------------ pipeline


def _drop_legacy_duplicates(events: list[Event]) -> list[Event]:
    seen = {
        (e.story, e.actor, e.text[:200])
        for e in events
        if e.kind == "comment" and not e.legacy
    }
    return [
        e for e in events
        if not (e.kind == "comment" and e.legacy and (e.story, e.actor, e.text[:200]) in seen)
    ]


def _merge_incidents(events: list[Event]) -> list[Event]:
    opened = {e.ref_id: e for e in events if e.kind == "incident_open"}
    out = []
    for e in events:
        if e.kind == "incident_resolved" and e.ref_id in opened:
            opened[e.ref_id].head = f"{opened[e.ref_id].severity} incident opened and resolved"
            continue
        out.append(e)
    return out


def _merge_deploys(events: list[Event]) -> list[Event]:
    groups: dict[tuple, list[Event]] = {}
    for e in events:
        if e.kind == "deploy_bad":
            groups.setdefault((e.project, e.story, e.env), []).append(e)
    drop: set[int] = set()
    for group in groups.values():
        failed = [e for e in group if e.severity == "failed"]
        rolled = [e for e in group if e.severity == "rolled_back"]
        if len(group) == 2 and len(failed) == 1 and len(rolled) == 1:
            first, last = sorted(group, key=lambda x: x.when)
            last.head = f"{(last.env or '').capitalize()} deploy failed, then rolled back"
            last.score = max(first.score, last.score)
            drop.add(id(first))
    return [e for e in events if id(e) not in drop]


def _burst(events: list[Event]) -> list[Event]:
    groups: dict[tuple, list[Event]] = {}
    out: list[Event] = []
    for e in events:
        if e.precision == "minute" and e.kind != "commits":
            groups.setdefault((e.kind, e.head, e.ts, e.score), []).append(e)
        else:
            out.append(e)
    for members in groups.values():
        if len(members) < BURST_MIN:
            out.extend(members)
            continue
        members.sort(key=lambda x: x.ref_id)
        first = dataclasses.replace(members[0])
        projects = sorted({m.project for m in members if m.project})
        first.head = f"{len(members)} x {first.head}" + (f" ({', '.join(projects)})" if projects else "")
        first.tail = ""
        first.count = len(members)
        out.append(first)
    return out


def _tier_pipeline(events: list[Event]) -> list[Event]:
    events = _merge_incidents(events)
    events = _merge_deploys(events)
    events = _burst(events)
    return sorted(events, key=_sort_key)


def rank_events(ctx: Ctx, events: list[Event], now: datetime) -> tuple[list[Event], list[Event]]:
    """Return ``(last_24h, earlier)`` ranked event lists (days 2 to 7 in ``earlier``)."""
    stamped: list[Event] = []
    for src in events:
        ts, label = effective_ts(src, now)
        if ts is None or ts > now or ts < now - EARLIER_WINDOW:
            continue
        # Own-authored Jira and Git events never appear in the author's briefing.
        if src.system in ("Jira", "Git") and src.actor == ctx.dev_id:
            continue
        stamped.append(dataclasses.replace(src, ts=ts, day_label=label))
    stamped = _drop_legacy_duplicates(stamped)
    recent: list[Event] = []
    earlier: list[Event] = []
    for e in stamped:
        s = score(ctx, e)
        if s is None:
            continue
        e.score = s
        if e.head_to_me and e.to == ctx.dev_id:
            e.head = e.head_to_me
        (recent if e.ts >= now - WINDOW else earlier).append(e)
    return _tier_pipeline(recent), _tier_pipeline(earlier)


# --------------------------------------------------------------------- snapshot


def _noun(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _parse(value: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(value, TS_FORMAT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _open_incidents(raw: dict, now: datetime) -> list[dict]:
    out = []
    for i in raw["incidents"]:
        opened = _parse(i.get("opened_at"))
        resolved = _parse(i.get("resolved_at"))
        if opened and opened <= now and (resolved is None or resolved > now):
            out.append(i)
    return out


def _last_prod_deploy(raw: dict, now: datetime, projects: Optional[frozenset]) -> Optional[dict]:
    best, best_ts = None, None
    for d in raw["deployments"]:
        ts = _parse(d.get("deployed_at"))
        if not ts or ts > now or d.get("environment") != "production":
            continue
        if projects is not None and SERVICE_PROJECT.get(d.get("service")) not in projects:
            continue
        if best_ts is None or ts > best_ts:
            best, best_ts = d, ts
    return best


def _deploy_line(prefix: str, d: Optional[dict]) -> list[str]:
    if not d:
        return []
    return [f"{prefix}: {d.get('service')} {d.get('version')} {str(d.get('status')).replace('_', ' ')}"]


def _bad_prod_deploys(raw: dict, now: datetime) -> int:
    n = 0
    for d in raw["deployments"]:
        ts = _parse(d.get("deployed_at"))
        if ts and now - EARLIER_WINDOW <= ts <= now and d.get("environment") == "production" \
                and d.get("status") in ("failed", "rolled_back"):
            n += 1
    return n


def snapshot_lines(ctx: Ctx, raw: dict[str, Any], now: datetime) -> list[str]:
    """Where-things-stand lines from current state. A line needs its source to have answered."""
    down = set(raw.get("unavailable", []))
    jira, snow, conf = "Jira" not in down, "ServiceNow" not in down, "Confluence" not in down
    lines: list[str] = []
    stories = raw["stories"]
    open_in = [
        s for s in stories
        if s.get("status") != "done" and s.get("project_id") in ctx.my_projects
    ]
    if ctx.persona == "dev":
        if jira:
            mine = [s["id"] for s in stories if s.get("assignee") == ctx.dev_id and s.get("status") != "done"]
            more = f" and {len(mine) - 3} more" if len(mine) > 3 else ""
            listing = f": {', '.join(mine[:3])}{more}" if mine else ""
            lines.append(f"{_noun(len(mine), 'story', 'stories')} assigned to you{listing}")
            lines.append(f"{_noun(len(open_in), 'open story', 'open stories')} in your projects")
        if snow:
            n = sum(1 for i in _open_incidents(raw, now) if SERVICE_PROJECT.get(i.get("affected_service")) in ctx.my_projects)
            lines.append(f"{_noun(n, 'open incident', 'open incidents')} on your services")
            lines += _deploy_line("Last production deploy of your services", _last_prod_deploy(raw, now, ctx.my_projects))
    elif ctx.persona == "pm":
        if jira:
            active = {s.get("id") for s in raw["sprints"] if s.get("status") == "active"}
            in_sprint = [s for s in stories if s.get("sprint_id") in active and s.get("project_id") in ctx.my_projects]
            lines.append(f"{_noun(len(open_in), 'open story', 'open stories')} in your projects")
            lines.append(f"{_noun(len(in_sprint), 'story', 'stories')} in the active sprint")
        if snow:
            n = sum(1 for i in _open_incidents(raw, now) if SERVICE_PROJECT.get(i.get("affected_service")) in ctx.my_projects)
            lines.append(f"{_noun(n, 'open incident', 'open incidents')} in your projects")
            lines += _deploy_line("Last production deploy in your projects", _last_prod_deploy(raw, now, ctx.my_projects))
    elif ctx.persona == "exec":
        if snow:
            opened = _open_incidents(raw, now)
            lines.append(f"{_noun(sum(1 for i in opened if i.get('severity') in P12), 'open P1/P2 incident', 'open P1/P2 incidents')}")
            lines.append(f"{_noun(len(opened), 'open incident', 'open incidents')} in total")
            lines += _deploy_line("Last production deploy", _last_prod_deploy(raw, now, None))
            n = _bad_prod_deploys(raw, now)
            lines.append(f"{_noun(n, 'failed or rolled-back production deploy', 'failed or rolled-back production deploys')} in the last 7 days")
    else:  # arch
        if snow:
            n = 0
            for r in raw["runs"]:
                ts = _parse(r.get("started_at"))
                totals = (r.get("security") or {}).get("totals") or {}
                if ts and now - EARLIER_WINDOW <= ts <= now and (totals.get("high") or 0) + (totals.get("critical") or 0) > 0:
                    n += 1
            lines.append(f"{_noun(n, 'high/critical security finding', 'high/critical security findings')} in seeded CI/CD runs in the last 7 days")
            n = _bad_prod_deploys(raw, now)
            lines.append(f"{_noun(n, 'failed or rolled-back production deploy', 'failed or rolled-back production deploys')} in the last 7 days")
            n = sum(1 for i in _open_incidents(raw, now) if i.get("severity") in P12)
            lines.append(f"{_noun(n, 'open P1/P2 incident', 'open P1/P2 incidents')}")
        if conf:
            cutoff = (now - timedelta(days=30)).date().isoformat()
            today = now.date().isoformat()
            n = sum(1 for p in raw["pages"] if isinstance(p.get("last_updated"), str) and cutoff <= p["last_updated"] <= today)
            lines.append(f"{_noun(n, 'Confluence page', 'Confluence pages')} updated in the last 30 days")
    return lines[:TOP_N]


# ------------------------------------------------------------------------ result


def build_briefing(
    persona: str, dev_id: str, events: list[Event], raw: dict[str, Any], now: datetime
) -> dict[str, Any]:
    """Rank events for the persona and apply the four-mode window fallback."""
    ctx = make_ctx(persona, dev_id, raw)
    recent, earlier = rank_events(ctx, events, now)
    recent, earlier = recent[:MAX_ITEMS], earlier[:MAX_EARLIER]
    n24 = len(recent)
    snapshot: list[str] = []
    if n24 >= TOP_N:
        mode, headline = "recent", HEADLINE_RECENT
        top = recent[:TOP_N]
    elif n24 >= 1:
        mode = "topped_up"
        headline = f"Since yesterday: {n24} new in the last 24 hours"
        top = recent + [dataclasses.replace(e, tag="earlier") for e in earlier[: TOP_N - n24]]
    elif earlier:
        mode, headline = "widened", HEADLINE_WIDENED
        top = [dataclasses.replace(e, tag="earlier") for e in earlier[:TOP_N]]
    else:
        mode, headline = "snapshot", HEADLINE_SNAPSHOT
        top = []
        snapshot = snapshot_lines(ctx, raw, now)
        if not snapshot:
            raise BriefingUnavailable("no event and no snapshot line could be produced")
    return {
        "persona": persona,
        "generated_at": now.strftime(TS_FORMAT),
        "mode": mode,
        "headline": headline,
        "counts": {"last_24h": n24, "earlier": len(earlier)},
        "top": [to_item(e) for e in top],
        "items": [to_item(e) for e in recent],
        "earlier": [to_item(e) for e in earlier],
        "snapshot": snapshot,
        "unavailable": list(raw.get("unavailable", [])),
        "labels": dict(LABELS),
    }
