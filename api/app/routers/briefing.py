"""Login briefing router: read-only ``GET /briefing`` (no LLM, no AgentCore call)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth import Identity, current_identity
from app.briefing.service import BriefingUnavailable, get_briefing

logger = logging.getLogger(__name__)
router = APIRouter(tags=["briefing"])


@router.get("/briefing")
def briefing(ident: Identity = Depends(current_identity)) -> dict:
    """Top 5 things from the last 24 hours for the persona, plus the full list."""
    try:
        return get_briefing(ident)
    except BriefingUnavailable:
        logger.warning("briefing unavailable: no lines could be produced")
        raise HTTPException(status_code=502, detail="Briefing unavailable")