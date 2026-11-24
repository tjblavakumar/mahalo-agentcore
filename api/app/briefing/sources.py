"""Upstream fetch (GET only), caching and normalization for the login briefing.

Imports only stdlib, FastAPI-free helpers and ``app.*``: no agent, LangChain or
Strands import (R3). Every upstream call is a GET (R6). The cache holds the raw,
persona-independent source records (original date strings and precision), never
ranked output or day-precision timestamps, so the window is always evaluated
against the current clock in ``rank.py``.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.briefing.models import Event
from app.config import Settings
from app.routers import viewers

logger = logging.getLogger(__name__)

CALL_TIMEOUT_SECONDS = 4
DEADLINE_SECONDS = 6
CACHE_TTL_OK_SECONDS = 60
CACHE_TTL_PARTIAL_SECONDS = 10
ACTIVITY_DAYS = 7
RUNS_LIMIT = 50

SYSTEMS = ("Jira", "ServiceNow", "Confluence", "Git")

# Same project -> service map as tools-lambdas servicenow cicd_seed.PROJECT_SERVICE;
# the Gitea repo name equals the service id.
PROJECT_SERVICE = {
    "PAY": "payment-service",
    "CART": "cart-service",
    "AUTH": "auth-service",
    "PROD": "product-service",
    "ORD": "order-service",
}
SERVICE_PROJECT = {v: k for k, v in PROJECT_SERVICE.items()}

_AUTHORED_BY = re.compile(r" authored by ([^()]+?) \(")
_PROJECT_KEY = re.compile(r"\b([A-Z]{2,5})-\d+\b")
_DESIGN_WORDS = re.compile(r"\b(adr|architecture|design|abstraction)\b", re.IGNORECASE)
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class _SourceDown(Exception):
    """A source did not answer usably."""


# --------------------------------------------------------------------------- fetch

_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "ttl": 0.0, "raw": None}
_warned_unconfigured: set[str] = set()


def _monotonic() -> float:
    """Clock seam for the cache (tests patch this)."""
    return time.monotonic()


def _get_json(base: str, token: str, path: str, *, tolerate_404: bool = False) -> Any:
    try:
        status, body = viewers._call("GET", f"{base}{path}", token, CALL_TIMEOUT_SECONDS)
    except viewers._UpstreamError as exc:
        raise _SourceDown(str(exc)) from exc
    if status == 404:
        if tolerate_404:
            return None
        raise _SourceDown("not found")
    try:
        return json.loads(body)
    except (ValueError, TypeError) as exc:
        raise _SourceDown("invalid JSON") from exc


def _list(payload: Any, key: str) -> list:
    if payload is None:
        return []
    items = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise _SourceDown(f"unexpected shape for {key}")
    return [i for i in items if isinstance(i, dict)]


def _plan(cfg: Settings, since: str) -> tuple[list[tuple], list[str]]:
    """Return ``(calls, unconfigured)``; a call is ``(system, key, base, token, path, tolerate)``."""
    bases = {
        "Jira": (cfg.jira_url, cfg.jira_token),
        "ServiceNow": (cfg.servicenow_url, cfg.servicenow_token),
        "Confluence": (cfg.confluence_url, cfg.confluence_token),
        "Git": (cfg.github_url, cfg.github_token),
    }
    paths: dict[str, list[tuple[str, str, bool]]] = {
        "Jira": [
            ("stories", "/stories", False),
            ("activity", f"/activity?since={since}", True),
            ("developers", "/developers", False),
            ("projects", "/projects", False),
        ]
        + [(f"sprints:{p}", f"/sprints/{p}", False) for p in PROJECT_SERVICE],
        "ServiceNow": [
            ("incidents", "/incidents", False),
            ("deployments", "/deployments", False),
            ("runs", f"/cicd/runs?limit={RUNS_LIMIT}", False),
        ],
        "Confluence": [("pages", "/pages", False)],
        "Git": [("pulls", "/pulls", False)]
        + [(f"commits:{svc}", f"/repos/{svc}/commits", False) for svc in PROJECT_SERVICE.values()],
    }
    calls: list[tuple] = []
    unconfigured: list[str] = []
    for system in SYSTEMS:
        base, token = bases[system]
        if not base or not token:
            unconfigured.append(system)
            continue
        for key, path, tolerate in paths[system]:
            calls.append((system, key, base, token, path, tolerate))
    return calls, unconfigured


def _fetch_raw(now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=ACTIVITY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg = Settings()
    calls, unconfigured = _plan(cfg, since)
    unavailable: set[str] = set(unconfigured)
    for system in unconfigured:
        if system not in _warned_unconfigured:
            _warned_unconfigured.add(system)
            logger.info("briefing source not configured: %s", system)

    results: dict[tuple[str, str], Any] = {}
    if calls:
        # No ``with`` block: the context manager would wait for slow threads on exit.
        executor = ThreadPoolExecutor(max_workers=len(calls))
        futures = {
            executor.submit(_get_json, base, token, path, tolerate_404=tol): (system, key)
            for system, key, base, token, path, tol in calls
        }
        done, not_done = wait(list(futures), timeout=DEADLINE_SECONDS)
        executor.shutdown(wait=False, cancel_futures=True)
        for fut in not_done:
            unavailable.add(futures[fut][0])
            logger.warning("briefing source timed out: %s", futures[fut][0])
        for fut in done:
            system, key = futures[fut]
            try:
                results[(system, key)] = fut.result()
            except _SourceDown:
                unavailable.add(system)
                logger.warning("briefing source failed: system=%s call=%s", system, key.split(":")[0])
            except Exception:  # defensive: never let one call fail the whole fetch
                unavailable.add(system)
                logger.warning("briefing source error: system=%s", system)

    def grab(system: str, key: str, payload_key: str) -> list:
        if system in unavailable or (system, key) not in results:
            return []
        try:
            return _list(results[(system, key)], payload_key)
        except _SourceDown:
            unavailable.add(system)
            return []

    raw: dict[str, Any] = {
        "stories": grab("Jira", "stories", "stories"),
        "activity": grab("Jira", "activity", "activity"),
        "developers": grab("Jira", "developers", "developers"),
        "projects": grab("Jira", "projects", "projects"),
        "sprints": [s for p in PROJECT_SERVICE for s in grab("Jira", f"sprints:{p}", "sprints")],
        "incidents": grab("ServiceNow", "incidents", "incidents"),
        "deployments": grab("ServiceNow", "deployments", "deployments"),
        "runs": grab("ServiceNow", "runs", "runs"),
        "pages": grab("Confluence", "pages", "pages"),
        "pulls": grab("Git", "pulls", "pull_requests"),
        "commits": {
            svc: grab("Git", f"commits:{svc}", "commits") for svc in PROJECT_SERVICE.values()
        },
    }
    if "Jira" in unavailable:  # a late shape error may have cleared one list only
        for k in ("stories", "activity", "developers", "projects", "sprints"):
            raw[k] = []
    raw["unavailable"] = sorted(unavailable, key=SYSTEMS.index)
    return raw


def get_raw(now: Optional[datetime] = None) -> dict[str, Any]:
    """Return cached raw source records, refreshing when the TTL has elapsed."""
    try:
        with _cache_lock:
            tick = _monotonic()
            if _cache["raw"] is not None and tick - _cache["at"] < _cache["ttl"]:
                return _cache["raw"]
            raw = _fetch_raw(now)
            _cache.update(
                at=_monotonic(),
                ttl=CACHE_TTL_PARTIAL_SECONDS if raw["unavailable"] else CACHE_TTL_OK_SECONDS,
                raw=raw,
            )
            return raw
    except Exception:
        logger.warning("briefing cache failure; fetching directly")
        return _fetch_raw(now)


def clear_cache() -> None:
    with _cache_lock:
        _cache.update(at=0.0, ttl=0.0, raw=None)


# ------------------------------------------------------------------- normalization


def _valid_when(value: Any) -> Optional[str]:
    """Return ``"minute"``/``"day"`` for an accepted timestamp string, else ``None``."""
    if not isinstance(value, str):
        return None
    try:
        if _DATETIME_RE.match(value):
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
            return "minute"
        if _DATE_RE.match(value):
            datetime.strptime(value, "%Y-%m-%d")
            return "day"
    except ValueError:
        return None
    return None


def _s(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _clip(text: str, n: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "..."


def _safe_url(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value.startswith("https://") else None


def _title_before_author(title: str) -> str:
    head = title.split(" authored by")[0]
    return re.sub(r"[^A-Za-z0-9]+$", "", head)


def extract_actor(texts: list[str], by_name: dict[str, str]) -> Optional[str]:
    """Developer id named in `` authored by <Name> (`` in the first text that has it."""
    for text in texts:
        m = _AUTHORED_BY.search(text or "")
        if m:
            return by_name.get(m.group(1).strip())
    return None


def _bad_deploy_head(env: str, status: str) -> str:
    return f"{env.capitalize()} deploy {status.replace('_', ' ')}"


def normalize(raw: dict[str, Any]) -> list[Event]:
    """Turn raw source records into events. Pure: no clock, no I/O."""
    events: list[Event] = []
    stories = {s["id"]: s for s in raw["stories"] if isinstance(s.get("id"), str)}
    names = {d["id"]: _s(d.get("name")) for d in raw["developers"] if isinstance(d.get("id"), str)}
    by_name = {n: i for i, n in names.items() if n}

    def who(dev_id: Any) -> str:
        return names.get(dev_id) or _s(dev_id) or "Someone"

    def assignee_of(story_id: Optional[str]) -> Optional[str]:
        story = stories.get(story_id or "")
        value = story.get("assignee") if story else None
        return value if isinstance(value, str) else None

    # Jira activity (full timestamps)
    activity: list[dict] = []
    for a in raw["activity"]:
        if _valid_when(a.get("ts")) == "minute" and isinstance(a.get("story_id"), str):
            activity.append(a)
    assigned_keys = {
        (a["story_id"], a.get("to")) for a in activity if a.get("type") == "assigned"
    }
    for a in activity:
        kind = a.get("type")
        sid = a["story_id"]
        proj = a.get("project_id") if isinstance(a.get("project_id"), str) else sid.split("-")[0]
        title = _clip(_s(stories.get(sid, {}).get("title")), 60)
        suffix = f": {title}" if title else ""
        base = dict(
            system="Jira", when=a["ts"], precision="minute", project=proj, story=sid,
            story_assignee=assignee_of(sid), ref_type="story", ref_id=sid,
        )
        actor = a.get("actor") if isinstance(a.get("actor"), str) else None
        to = a.get("to") if isinstance(a.get("to"), str) else None
        if kind == "assigned":
            events.append(Event(kind="assigned", head=f"{sid} assigned to {who(to)}", tail=suffix,
                                head_to_me=f"{sid} assigned to you", to=to, actor=actor, **base))
        elif kind == "created":
            if (sid, to) in assigned_keys:
                continue  # the matching "assigned" item already reports it
            events.append(Event(kind="created", head=f"{sid} created", tail=suffix, to=to,
                                head_to_me=f"{sid} created for you" if to else None,
                                actor=actor, **base))
        elif kind == "status" and to:
            events.append(Event(kind="status", head=f"{sid} moved to {to}", tail=suffix, to=to,
                                actor=actor, **base))
        elif kind == "comment":
            text = _s(a.get("text"))
            events.append(Event(kind="comment", head=f"{who(actor)} commented on {sid}",
                                tail=f": {_clip(text)}", actor=actor, text=text, design=bool(
                                    _DESIGN_WORDS.search(text)), **base))

    # Legacy Jira comments (day precision)
    for sid, story in stories.items():
        for c in story.get("comments") or []:
            if not isinstance(c, dict) or _valid_when(c.get("date")) != "day":
                continue
            text = _s(c.get("text"))
            author = c.get("author") if isinstance(c.get("author"), str) else None
            events.append(Event(
                kind="comment", system="Jira", when=c["date"], precision="day",
                head=f"{who(author)} commented on {sid}", tail=f": {_clip(text)}",
                project=_s(story.get("project_id")) or sid.split("-")[0], story=sid,
                story_assignee=assignee_of(sid), actor=author, ref_type="story", ref_id=sid,
                legacy=True, text=text, design=bool(_DESIGN_WORDS.search(text)),
            ))

    # CI/CD runs: linked-deployment runs are folded into the deployment line.
    run_findings: dict[str, int] = {}
    for r in raw["runs"]:
        sec = r.get("security") if isinstance(r.get("security"), dict) else {}
        totals = sec.get("totals") if isinstance(sec.get("totals"), dict) else {}
        n = int(totals.get("high") or 0) + int(totals.get("critical") or 0)
        dep = r.get("linked_deployment")
        if isinstance(dep, str) and dep:
            run_findings[dep] = run_findings.get(dep, 0) + n
            continue
        when = r.get("started_at")
        if _valid_when(when) != "minute":
            continue
        rid = _s(r.get("id"))
        story = r.get("linked_story") if isinstance(r.get("linked_story"), str) else None
        proj = _s(r.get("project_id")) or None
        stage = _s(r.get("failed_stage")) or "scan"
        failed = r.get("status") == "failed"
        common = dict(
            system="CI/CD", when=when, precision="minute", project=proj, story=story,
            story_assignee=assignee_of(story), ref_type="run", ref_id=rid,
        )
        if n > 0:
            head = (f"Pipeline failed with {n} high findings" if failed
                    else f"{n} high/critical findings")
            events.append(Event(kind="finding", head=head, tail=f" on {story or proj} at {stage}",
                                count=1, **common))
        elif failed:
            events.append(Event(kind="run_failed", head="Pipeline failed",
                                tail=f" on {story or proj} at {stage}", **common))

    # ServiceNow deployments and incidents
    for d in raw["deployments"]:
        when = d.get("deployed_at")
        if _valid_when(when) != "minute":
            continue
        service = _s(d.get("service"))
        env = _s(d.get("environment"))
        status = _s(d.get("status"))
        story = d.get("linked_story") if isinstance(d.get("linked_story"), str) else None
        did = _s(d.get("id"))
        found = run_findings.get(did, 0)
        extra = f" with {found} high findings" if found else ""
        tail = f": {service} {_s(d.get('version'))}" + (f" ({story})" if story else "") + extra
        common = dict(
            system="ServiceNow", when=when, precision="minute",
            project=SERVICE_PROJECT.get(service), story=story, story_assignee=assignee_of(story),
            env=env, ref_type="deployment", ref_id=did,
        )
        if status in ("failed", "rolled_back"):
            events.append(Event(kind="deploy_bad", head=_bad_deploy_head(env, status), tail=tail,
                                severity=status, **common))
        elif status == "success" and env == "production":
            events.append(Event(kind="deploy_ok", head="Production deploy succeeded", tail=tail,
                                **common))
    for i in raw["incidents"]:
        service = _s(i.get("affected_service"))
        sev = _s(i.get("severity"))
        title = _clip(_s(i.get("title")), 70)
        iid = _s(i.get("id"))
        common = dict(
            system="ServiceNow", precision="minute", project=SERVICE_PROJECT.get(service),
            severity=sev, ref_type="incident", ref_id=iid,
        )
        if _valid_when(i.get("opened_at")) == "minute":
            events.append(Event(kind="incident_open", when=i["opened_at"],
                                head=f"{sev} incident opened", tail=f": {title}", **common))
        if _valid_when(i.get("resolved_at")) == "minute":
            events.append(Event(kind="incident_resolved", when=i["resolved_at"],
                                head=f"{sev} incident resolved", tail=f": {title}", **common))

    # Confluence pages (day precision)
    for p in raw["pages"]:
        if _valid_when(p.get("last_updated")) != "day":
            continue
        title = _s(p.get("title"))
        events.append(Event(
            kind="page", system="Confluence", when=p["last_updated"], precision="day",
            head="Page updated", tail=f": {_clip(title, 70)}", ref_type="page",
            ref_id=_s(p.get("id")), design=bool(_DESIGN_WORDS.search(title)),
            actor=by_name.get(_s(p.get("author"))),
        ))

    # Git (day precision)
    for pr in raw["pulls"]:
        repo = _s(pr.get("repo_id"))
        status = _s(pr.get("status"))
        if status not in ("open", "merged"):
            continue
        when = pr.get("updated_at") if status == "merged" else pr.get("created_at")
        if _valid_when(when) != "day":
            continue
        title = _s(pr.get("title"))
        branch = _s(pr.get("branch"))
        keys = {m.group(1) for m in _PROJECT_KEY.finditer(title + " " + branch)}
        cross = len(keys) >= 2
        word = "merged" if status == "merged" else "opened"
        number = pr.get("number")
        events.append(Event(
            kind="pr_merged" if status == "merged" else "pr_open", system="Git", when=when,
            precision="day", head=f"PR #{number} {word} in {repo}",
            tail=f": {_clip(_title_before_author(title), 70)}",
            project=SERVICE_PROJECT.get(repo), ref_type="pr", ref_id=f"{repo}#{number}",
            url=_safe_url(pr.get("url")),
            design=cross or bool(_DESIGN_WORDS.search(_title_before_author(title) + " " + branch)),
            actor=extract_actor([title, _s(pr.get("description"))], by_name),
        ))
    for repo, commits in raw["commits"].items():
        groups: dict[tuple[str, Optional[str]], int] = {}
        for c in commits:
            msg = _s(c.get("message"))
            if msg.startswith("Merge pull request") or msg.strip() == "Initial commit":
                continue
            if _valid_when(c.get("date")) != "day":
                continue
            key = (c["date"], extract_actor([msg], by_name))
            groups[key] = groups.get(key, 0) + 1
        for (date, actor), n in groups.items():
            events.append(Event(
                kind="commits", system="Git", when=date, precision="day",
                head=f"{n} commit{'s' if n != 1 else ''} to {repo}", project=SERVICE_PROJECT.get(repo),
                ref_type="repo", ref_id=repo, actor=actor, count=n,
            ))
    return events
