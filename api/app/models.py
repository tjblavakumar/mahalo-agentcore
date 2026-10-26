"""Pydantic request/response models for the thin API (design §A.3 / §B.3).

Mirror mahalo-dock's ``ChatRequest``/``ChatResponse``/``ActionResult`` shape plus
the one new ``interrupt_id`` field the two-call HITL protocol needs. These are the
only contract the thin API exposes to the frontend.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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


# --- Custom dashboard persistence models (design §3.3) -----------------------

# Allowed VizSpec types (design §1.2); the structural guard keys off this set.
_VIZ_CHART_TYPES = {"line", "area", "bar"}
_VIZ_TYPES = _VIZ_CHART_TYPES | {"table"}


class WidgetLayout(BaseModel):
    """The single stored ``lg`` (12-col) grid layout for one widget (§1.4)."""

    x: int = Field(ge=0, le=48)
    y: int = Field(ge=0, le=48)
    w: int = Field(ge=1, le=48)
    h: int = Field(ge=1, le=48)


class SavedWidget(BaseModel):
    """One persisted widget: a client id + an opaque VizSpec + its layout."""

    id: str = Field(min_length=1, max_length=64)
    spec: dict  # opaque VizSpec; structurally guarded by the PUT route (§3.3).
    layout: WidgetLayout


class DashboardWidgets(BaseModel):
    """A persona's full dashboard widget set (overwrite-save, §3.2)."""

    widgets: list[SavedWidget] = Field(min_length=0, max_length=24)


def spec_is_structurally_valid(spec: object) -> bool:
    """Minimal server-side structural guard on a stored ``spec`` (design §3.3).

    Not the full frontend validator — just enough that a hand-crafted PUT to the
    ``AuthType=NONE`` Function URL can't poison a dashboard with junk that later
    crashes the renderer. Checks ``spec`` is a dict with an allowed ``type`` and
    the type-appropriate keys present (charts: ``xKey``/``series``/``data``;
    table: ``columns``/``rows``).
    """
    if not isinstance(spec, dict):
        return False
    spec_type = spec.get("type")
    if spec_type not in _VIZ_TYPES:
        return False
    if not isinstance(spec.get("title"), str) or not spec["title"].strip():
        return False
    if spec_type in _VIZ_CHART_TYPES:
        if not isinstance(spec.get("xKey"), str) or not spec["xKey"].strip():
            return False
        if not isinstance(spec.get("series"), list) or not spec["series"]:
            return False
        if not isinstance(spec.get("data"), list):
            return False
        return True
    # table
    if not isinstance(spec.get("columns"), list) or not spec["columns"]:
        return False
    if not isinstance(spec.get("rows"), list):
        return False
    return True
