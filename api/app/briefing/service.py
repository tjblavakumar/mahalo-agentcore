"""Briefing service: cached raw records -> events -> ranked briefing for one identity."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.auth import _PERSONA_MAP, Identity
from app.briefing import rank, sources
from app.briefing.rank import BriefingUnavailable

__all__ = ["BriefingUnavailable", "get_briefing", "persona_key"]


def persona_key(identity: Identity) -> str:
    """Reverse of the one persona table in ``app.auth`` (developer is the fallback)."""
    for key, (dev_id, _role) in _PERSONA_MAP.items():
        if dev_id == identity.developer_id:
            return key
    return "dev"


def get_briefing(identity: Identity, now: Optional[datetime] = None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    raw = sources.get_raw(now)
    events = sources.normalize(raw)
    return rank.build_briefing(persona_key(identity), identity.developer_id, events, raw, now)