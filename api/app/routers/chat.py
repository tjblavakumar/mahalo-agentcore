"""Chat router: POST /chat + POST /chat/approve — a pure Runtime forwarder.

Ported in SHAPE from mahalo-dock's ``routers/chat.py`` but thinned to a forwarder:
no DB, no openai/demo branch, no ``execute_proposed_action`` (that logic lives in
the agent on the Runtime now). The endpoints forward the §A.3 JSON contract and
map the Runtime reply back onto ``ChatResponse``/``ActionResult``.

Error mapping (design §B.6):
* Runtime invoke throws -> HTTP 502 (retryable at the edge).
* Runtime returns ``{"status":"error"}`` -> HTTP 200 with ``success=false``
  (mirrors mahalo-dock's ``ActionResult``).
* pydantic validation -> HTTP 422 (FastAPI default).
* an approve is NEVER auto-retried (it could double-apply a write).
"""

from __future__ import annotations

import logging
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException

from app.auth import Identity, current_identity
from app.config import settings
from app.models import ActionResult, ApprovalRequest, ChatRequest, ChatResponse
from app.runtime_client import invoke_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# AgentCore Runtime requires runtimeSessionId length >= 33 (validated live:
# "Invalid length for parameter runtimeSessionId, valid min length: 33"). A
# browser-supplied session_id can be shorter, which previously 502'd every chat.
# Normalize ANY client value to a stable, compliant id in one place.
_MIN_RUNTIME_SESSION_LEN = 33


def _runtime_session_id(client_session_id: str | None) -> str:
    """Return a Runtime-valid session id (>=33 chars) for a client session.

    - Missing -> a fresh uuid4 hex-ish id (36 chars).
    - Present but too short -> deterministically padded so the SAME client
      session always maps to the SAME Runtime session (preserving Memory
      continuity across turns), while clearing the >=33 floor. Padding is a
      fixed suffix of the client id's own sanitized chars; it never collides
      a distinct client id into the same runtime id for demo-length ids.
    - Present and long enough -> used as-is.
    """
    sid = (client_session_id or "").strip()
    if not sid:
        return "mahalo-" + uuid.uuid4().hex  # 7 + 32 = 39 chars
    if len(sid) >= _MIN_RUNTIME_SESSION_LEN:
        return sid
    # Deterministic pad: prefix the client id with a stable marker and repeat
    # the id until it clears the floor. Same input -> same output.
    padded = sid
    while len(padded) < _MIN_RUNTIME_SESSION_LEN:
        padded = f"{padded}-{sid}"
    return padded[: max(_MIN_RUNTIME_SESSION_LEN, len(sid) + 8)]


def _runtime_user_id(ident: Identity) -> str | None:
    """Send runtimeUserId only when Identity is enabled (off for the MVP, §D.4)."""
    return ident.developer_id if settings.identity_enabled else None


@router.post("", response_model=ChatResponse)
def send_message(req: ChatRequest, ident: Identity = Depends(current_identity)) -> ChatResponse:
    """Forward a chat message to the Runtime and project the reply."""
    # Normalize to a Runtime-valid (>=33 char) session id, and echo THAT back so
    # the client reuses the same id next turn (stable Memory continuity).
    session_id = _runtime_session_id(req.session_id)
    try:
        out = invoke_runtime(
            session_id=session_id,
            body={
                "action": "chat",
                "prompt": req.message,
                "developer_id": ident.developer_id,
                "role": ident.role,
            },
            runtime_user_id=_runtime_user_id(ident),
        )
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Runtime invoke failed")
        raise HTTPException(status_code=502, detail=f"Runtime invoke failed: {exc}")

    return ChatResponse(
        response=out.get("response", ""),
        proposal=out.get("proposal"),
        session_id=out.get("session_id", session_id),
        status=out.get("status", "complete"),
    )


@router.post("/approve", response_model=ActionResult)
def approve_action(
    req: ApprovalRequest, ident: Identity = Depends(current_identity)
) -> ActionResult:
    """Forward an approve/reject decision to the Runtime and project the reply.

    Note (design §B.3): the approve leg forwards ``developer_id`` but NOT ``role``
    and NOT ``tool_mode`` — the resume replays the pending tool execution without
    a model call, and ``tool_mode`` is a Runtime-process env constant.

    The optional ``proposal`` echo is forwarded verbatim when the client supplies
    it, but it is NOT required for chain correctness: the Runtime derives the
    ``[SYSTEM]`` breadcrumb from its own restored interrupt state (design §B.3,
    code-review finding 2). A mahalo-dock frontend sending only
    ``{session_id, interrupt_id, approved}`` is fully supported.
    """
    decision = "APPROVE" if req.approved else "REJECT"
    # Normalize identically to /chat so the approve lands on the SAME Runtime
    # session as the chat turn that produced this interrupt.
    session_id = _runtime_session_id(req.session_id)
    try:
        out = invoke_runtime(
            session_id=session_id,
            body={
                "action": "approve",
                "decision": decision,
                "interrupt_id": req.interrupt_id,
                "developer_id": ident.developer_id,
                "proposal": req.proposal,
            },
            runtime_user_id=_runtime_user_id(ident),
        )
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Runtime invoke failed")
        raise HTTPException(status_code=502, detail=f"Runtime invoke failed: {exc}")

    error = out.get("error")
    message = out.get("response", "") or (error.get("message", "") if error else "")
    return ActionResult(
        success=(out.get("status") != "error"),
        message=message,
        session_id=session_id,
    )
