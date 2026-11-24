"""Event and Item dataclasses for the login briefing."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass
class Event:
    """One normalized event. ``when`` is the raw source string; ``ts`` is set by rank.py."""

    kind: str  # assigned created status comment incident_open incident_resolved deploy_bad
    # deploy_ok run_failed finding pr_open pr_merged commits page
    system: str  # Jira ServiceNow CI/CD Confluence Git
    when: str  # "YYYY-MM-DDTHH:MM:SSZ" or "YYYY-MM-DD"
    precision: str  # "minute" | "day"
    head: str  # short text without the detail, used for burst lines
    tail: str = ""  # ": detail" appended to head
    project: Optional[str] = None
    story: Optional[str] = None
    story_assignee: Optional[str] = None
    actor: Optional[str] = None
    to: Optional[str] = None
    severity: Optional[str] = None
    env: Optional[str] = None
    ref_type: str = "story"
    ref_id: str = ""
    url: Optional[str] = None
    design: bool = False  # PR/page/comment text mentions design/architecture/ADR or spans services
    legacy: bool = False  # Jira comment derived from story.comments (day precision)
    text: str = ""  # comment text (for dedupe)
    head_to_me: Optional[str] = None  # alternative head when the event targets the persona
    count: int = 1
    ts: Optional[datetime] = None
    score: int = 0
    day_label: Optional[str] = None
    tag: Optional[str] = None

    @property
    def line(self) -> str:
        return (self.head + self.tail)[:120]


def to_item(e: Event) -> dict[str, Any]:
    return {
        "id": e.ref_id,
        "kind": e.kind,
        "system": e.system,
        "line": e.line,
        "ts": e.ts.strftime(TS_FORMAT) if e.ts else None,
        "precision": e.precision,
        "day_label": e.day_label,
        "ref": {"type": e.ref_type, "id": e.ref_id, "url": e.url},
        "count": e.count,
        "tag": e.tag,
    }
