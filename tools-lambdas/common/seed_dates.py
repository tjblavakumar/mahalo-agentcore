"""Pure helpers that re-base mock seed dates so the demo always looks current.

The seed data is authored around ``ANCHOR`` (a mid-sprint day). At seed time the
dates are shifted by a whole number of weeks so weekdays are preserved and the
active sprint window still contains "today". Nothing here mutates its input.
"""
import copy
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List

ANCHOR = date(2026, 8, 19)

_DATE_FMT = "%Y-%m-%d"
_DATETIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


def today_utc() -> date:
    """The single clock seam (tests monkeypatch this)."""
    return datetime.now(timezone.utc).date()


def compute_shift_days(today: date, anchor: date = ANCHOR) -> int:
    """Return a multiple of 7 days that moves ``anchor`` closest to ``today``."""
    return 7 * round((today - anchor).days / 7)


def shift_value(value: Any, days: int) -> Any:
    """Shift an ISO date / ``...THH:MM:SSZ`` datetime string; pass others through."""
    if not isinstance(value, str) or not value:
        return value
    try:
        if len(value) == 10:
            return (datetime.strptime(value, _DATE_FMT) + timedelta(days=days)).strftime(_DATE_FMT)
        return (datetime.strptime(value, _DATETIME_FMT) + timedelta(days=days)).strftime(_DATETIME_FMT)
    except ValueError:
        return value


def shift_records(records: Iterable[Dict[str, Any]], days: int, fields: Iterable[str]) -> List[Dict[str, Any]]:
    """Return deep copies of ``records`` with the named top-level fields shifted."""
    names = tuple(fields)
    out = []
    for rec in records:
        new = copy.deepcopy(rec)
        for name in names:
            if name in new:
                new[name] = shift_value(new[name], days)
        out.append(new)
    return out


def shift_story_comments(stories: Iterable[Dict[str, Any]], days: int) -> List[Dict[str, Any]]:
    """Return deep copies of Jira stories with ``comments[].date`` shifted."""
    out = []
    for story in stories:
        new = copy.deepcopy(story)
        for comment in new.get("comments") or []:
            if isinstance(comment, dict) and "date" in comment:
                comment["date"] = shift_value(comment["date"], days)
        out.append(new)
    return out
