"""Pydantic request/response models for the thin API (design §A.3 / §B.3).

Mirror mahalo-dock's ``ChatRequest``/``ChatResponse``/``ActionResult`` shape plus
the one new ``interrupt_id`` field the two-call HITL protocol needs. These are the
only contract the thin API exposes to the frontend.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Request body for a chat message."""

    message: str
    session_id: Optional[str] = None
    # Accepted for frontend compatibility; currently unused (Out of Scope).
    project_id: Optional[int] = None


class ChatResponse(BaseModel):
    """Response from the agent, projected from the Runtime reply."""

    response: str
    proposal: Optional[dict] = None
    session_id: str
    status: str


class ApprovalRequest(BaseModel):
    """Request to approve or reject a pending write (two-call HITL protocol)."""

    session_id: str
    interrupt_id: str
    approved: bool
    # OPTIONAL belt-and-braces echo of the proposal from the preceding /chat reply.
    # NOT required for chain correctness: the Runtime derives the [SYSTEM] breadcrumb
    # from its own restored interrupt state (design §B.3, code-review finding 2). A
    # client that sends only {session_id, interrupt_id, approved} is fully supported.
    proposal: Optional[dict] = None


class ActionResult(BaseModel):
    """Result of an approve/reject, projected from the Runtime reply."""

    success: bool
    message: str
    session_id: str
