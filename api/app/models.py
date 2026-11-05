"""Pydantic request/response models for the thin API (design §A.3 / §B.3).

Mirror mahalo-dock's ``ChatRequest``/``ChatResponse``/``ActionResult`` shape plus
the one new ``interrupt_id`` field the two-call HITL protocol needs. These are the
only contract the thin API exposes to the frontend.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

# --- Multi-LLM model allow-list (design §A / §B.1) ---------------------------
#
# The server-side canonical allow-list, mirroring agent/model_config.py (the
# Runtime's copy). Membership is enforced here on PUT /model-config because the
# thin-API Function URL is AuthType=NONE (NFR-6): a hand-crafted request can
# never make the Runtime invoke an off-list model. Code generation is fixed to
# a single id this slice (FR-12); code review / security pick from the review
# allow-list (security is persisted but inert this slice, FR-5).
CODE_GEN_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
REVIEW_ALLOW_LIST: frozenset[str] = frozenset(
    {
        "us.amazon.nova-lite-v1:0",
        "us.amazon.nova-micro-v1:0",
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    }
)
DEFAULT_REVIEW_MODEL_ID = "us.amazon.nova-lite-v1:0"


class ChatRequest(BaseModel):
    """Request body for a chat message."""

    message: str
    session_id: Optional[str] = None
    # Accepted for frontend compatibility; currently unused (Out of Scope).
    project_id: Optional[int] = None


class StageInfo(BaseModel):
    """One executed pipeline stage (generate / review), design §E.

    All fields optional-with-defaults so a Runtime reply carrying only a subset
    (or an old client ignoring the field entirely) still validates (FR-19).
    """

    stage: Optional[str] = None
    model_id: Optional[str] = None
    model_label: Optional[str] = None
    status: Optional[str] = None
    fallback: Optional[bool] = None


class ReviewInfo(BaseModel):
    """The code-review stage result, present only when review ran (design §E)."""

    model_id: Optional[str] = None
    model_label: Optional[str] = None
    findings: Optional[str] = None
    status: Optional[str] = None


class ChatResponse(BaseModel):
    """Response from the agent, projected from the Runtime reply."""

    response: str
    proposal: Optional[dict] = None
    session_id: str
    status: str
    # --- NEW, additive-optional (design §E); old clients ignore these ---
    stages: Optional[list[StageInfo]] = None
    review: Optional[ReviewInfo] = None


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
    # A chained write re-proposes on the approve turn: status is then
    # "pending_approval" and ``proposal`` carries the next write to approve.
    status: str = "complete"
    proposal: Optional[dict] = None


# --- Custom dashboard persistence models (design §3.3) -----------------------

# Allowed VizSpec types (design §1.2); the structural guard keys off this set.
# "pie" is a chart type with the same required keys (xKey/series/data); the
# optional bar "orientation" field stays opaque and needs no guard change.
_VIZ_CHART_TYPES = {"line", "area", "bar", "pie"}
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


# --- Per-persona model configuration (design §B.1) ---------------------------


class ModelConfig(BaseModel):
    """A persona's per-activity model selection (design §B.1).

    ``codeGeneration`` is fixed to the single code-gen id this slice (FR-12);
    ``codeReview`` and ``security`` must be members of the server review
    allow-list. The validators are the trust boundary for the AuthType=NONE
    Function URL (NFR-6) — a value off the allow-list is a 422.
    """

    codeGeneration: str
    codeReview: str
    security: str

    @field_validator("codeGeneration")
    @classmethod
    def _check_code_gen(cls, value: str) -> str:
        if value != CODE_GEN_MODEL_ID:
            raise ValueError(f"codeGeneration must be {CODE_GEN_MODEL_ID!r}")
        return value

    @field_validator("codeReview", "security")
    @classmethod
    def _check_review(cls, value: str) -> str:
        if value not in REVIEW_ALLOW_LIST:
            raise ValueError(f"{value!r} is not an allowed review model")
        return value
