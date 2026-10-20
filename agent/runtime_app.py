"""AgentCore Runtime harness for the mahalo Strands agent (Task 6).

Hosts the existing ``agent/`` package on **Amazon Bedrock AgentCore Runtime**. The
harness is ``bedrock_agentcore.runtime.BedrockAgentCoreApp`` (a Starlette ASGI app
that answers ``POST /invocations`` + ``GET /ping`` and runs on uvicorn :8080 in the
container). A single ``@app.entrypoint`` wraps the UNCHANGED ``build_agent`` seam
via ``agent/runtime_session.build_and_attach`` and drives one agent turn per call.

Import-time offline-safety (design §A.1/§E.4): constructing ``BedrockAgentCoreApp``
is a Starlette subclass construction (no network); ``build_and_attach`` is not
called until an invocation arrives. So ``import agent.runtime_app`` succeeds with
no AWS creds — the single AWS touch stays inside the agent call (``attach_memory``
rehydrate + Bedrock invoke), exactly as in the CLI.

Request/response contract (design §A.3). The thin API (``api/``) and this
entrypoint agree on a small JSON contract:

* Request body: ``{action: "chat"|"approve", prompt?, decision?, interrupt_id?,
  developer_id?, role?}``. The session id is NOT in the body — it arrives as the
  ``X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`` header, surfaced on
  ``context.session_id``.
* Response dict: ``{response, proposal?, session_id, status, error?}`` where
  ``status`` is ``complete`` | ``pending_approval`` | ``error``.

HITL is a two-call propose->approve protocol (design §C): the ``chat`` leg returns
a ``pending_approval`` proposal when a write gate fires; the ``approve`` leg
resumes the restored interrupt and emits the ``[SYSTEM]`` breadcrumb on a closed
cycle. The breadcrumb proposal is derived from the RESTORED interrupt state
(``_restored_proposal``), so chain preservation does NOT depend on the client
echoing the proposal back (code-review finding 2); a client-supplied
``payload["proposal"]`` is accepted only as a belt-and-braces fallback. The six
writes stay gated by ``WriteApprovalHook`` (unchanged).
"""

from __future__ import annotations

import logging
import uuid

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agent.config import settings
from agent.hitl import emit_system_signal, resume_once
from agent.prompts import ROLE_PROMPTS
from agent.runtime_session import build_and_attach

logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

# Entrypoint caps / defaults (design "Input validation").
_PROMPT_MAX_BYTES = 32 * 1024
_DEFAULT_DEVELOPER_ID = "dev-6"
_DEFAULT_ROLE = "developer"
_VALID_ACTIONS = {"chat", "approve"}
_VALID_DECISIONS = {"APPROVE", "REJECT"}


def _error(message: str, *, error_type: str, session_id: str | None = None) -> dict:
    """Build the in-band error envelope (HTTP 200; the thin API forwards it)."""
    return {
        "status": "error",
        "response": "",
        "proposal": None,
        "session_id": session_id,
        "error": {"type": error_type, "message": message},
    }


def _resolve_developer_id(raw) -> str:
    """Accept a ``^dev-\\d+$`` developer id; fall back to the default on malformed."""
    if isinstance(raw, str):
        value = raw.strip()
        if value.startswith("dev-") and value[4:].isdigit():
            return value
        if value:
            logger.warning("Ignoring malformed developer_id %r; using default", raw)
    return _DEFAULT_DEVELOPER_ID


def _resolve_role(raw) -> str:
    """Accept a role that is a key in ``ROLE_PROMPTS``; else fall back to default."""
    if isinstance(raw, str) and raw.strip() in ROLE_PROMPTS:
        return raw.strip()
    if raw is not None:
        logger.warning("Ignoring unknown role %r; using default", raw)
    return _DEFAULT_ROLE


def _restored_proposal(agent, interrupt_id: str):
    """Return the pending interrupt's proposal from RESTORED session state, or None.

    After ``attach_memory`` rehydrates the agent, ``agent._interrupt_state`` carries
    the pending ``Interrupt`` keyed by id, whose ``.reason`` is exactly the
    ``build_proposal`` dict the chat leg emitted (``agent/approval.py`` passes it as
    ``event.interrupt(reason=...)``). Reading it here lets the approve leg emit the
    ``[SYSTEM]`` chain breadcrumb WITHOUT relying on the client echoing the proposal
    back (review finding 2). Returns ``None`` when no matching pending interrupt is
    found (e.g. the VM was recycled and the state was not restored).
    """
    try:
        interrupts = agent._interrupt_state.interrupts
    except AttributeError:
        return None
    pending = interrupts.get(interrupt_id)
    reason = getattr(pending, "reason", None)
    if isinstance(reason, dict) and "action" in reason:
        return reason
    return None


def _resolve_session_id(context) -> str:
    """Resolve the session id from the request context, generating one if absent.

    Via the thin API the header is always set (§B.4); a missing header means a
    direct Runtime call. We generate a uuid, warn, and ECHO it back so the caller
    can thread the follow-up on the SAME Memory conversation (design §A.4 step 2).
    """
    session_id = getattr(context, "session_id", None)
    if session_id:
        return session_id
    generated = uuid.uuid4().hex
    logger.warning(
        "No session header on the invocation; generated session id %s", generated
    )
    return generated


def _handle_chat(payload: dict, session_id: str) -> dict:
    """Chat leg: one agent turn; return a proposal on interrupt, else the reply."""
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return _error(
            "chat requires a non-empty 'prompt'",
            error_type="bad_prompt",
            session_id=session_id,
        )
    if len(prompt.encode("utf-8")) > _PROMPT_MAX_BYTES:
        return _error(
            "'prompt' exceeds the 32 KB limit",
            error_type="prompt_too_large",
            session_id=session_id,
        )

    developer_id = _resolve_developer_id(payload.get("developer_id"))
    role = _resolve_role(payload.get("role"))

    attached = build_and_attach(
        session_id, developer_id=developer_id, role=role, pending_write=False
    )
    try:
        result = attached.agent(prompt)
    finally:
        if attached.mcp_client is not None:
            attached.mcp_client.stop(None, None, None)

    if getattr(result, "stop_reason", None) == "interrupt":
        itr = result.interrupts[0]
        proposal = {**itr.reason, "interrupt_id": itr.id}
        return {
            "status": "pending_approval",
            "response": "",
            "proposal": proposal,
            "session_id": session_id,
            "error": None,
        }
    return {
        "status": "complete",
        "response": str(result).strip(),
        "proposal": None,
        "session_id": session_id,
        "error": None,
    }


def _handle_approve(payload: dict, session_id: str) -> dict:
    """Approve leg: resume the restored interrupt; emit breadcrumb on a closed cycle."""
    decision = payload.get("decision")
    if decision not in _VALID_DECISIONS:
        return _error(
            "approve requires 'decision' in {APPROVE, REJECT}",
            error_type="bad_decision",
            session_id=session_id,
        )
    interrupt_id = payload.get("interrupt_id")
    if not isinstance(interrupt_id, str) or not interrupt_id.strip():
        return _error(
            "approve requires a non-empty 'interrupt_id'",
            error_type="bad_interrupt_id",
            session_id=session_id,
        )

    developer_id = _resolve_developer_id(payload.get("developer_id"))
    interrupt_id = interrupt_id.strip()

    # The approve leg does NOT forward 'role' (design §B.3): the resume replays
    # pending_tool_execution without a model call, so the role-selected system
    # prompt is never re-consumed. 'tool_mode' is the Runtime env constant, so the
    # rebuilt registry matches the chat leg's by construction.
    attached = build_and_attach(
        session_id, developer_id=developer_id, pending_write=True
    )
    try:
        # Derive the breadcrumb proposal from the RESTORED session state before
        # resuming, so chain preservation (design §C.3) does NOT depend on the
        # client echoing the proposal back (review finding 2). attach_memory has
        # rehydrated _interrupt_state from Memory; the pending interrupt's .reason
        # is exactly the build_proposal dict the chat leg returned. A client-echoed
        # payload["proposal"] is accepted only as a belt-and-braces fallback.
        proposal = _restored_proposal(attached.agent, interrupt_id)
        if proposal is None:
            echoed = payload.get("proposal")
            if isinstance(echoed, dict) and "action" in echoed:
                proposal = echoed

        try:
            result = resume_once(attached.agent, interrupt_id, decision)
        except KeyError:
            # _InterruptState.resume raises KeyError for an unknown/stale id
            # (VM recycled, already resolved, or wrong id). Fail safe: nothing ran.
            return _error(
                "no pending interrupt for the supplied interrupt_id",
                error_type="no_pending_interrupt",
                session_id=session_id,
            )
    finally:
        if attached.mcp_client is not None:
            attached.mcp_client.stop(None, None, None)

    # On a closed (non-interrupt) cycle after an APPROVE, emit the [SYSTEM]
    # breadcrumb so the branch->commit->PR chain is not re-proposed (design §C.3).
    if (
        decision == "APPROVE"
        and getattr(result, "stop_reason", None) != "interrupt"
        and isinstance(proposal, dict)
        and "action" in proposal
    ):
        emit_system_signal(attached.agent, proposal)

    if getattr(result, "stop_reason", None) == "interrupt":
        # A chained write re-proposed on the same approve turn.
        itr = result.interrupts[0]
        return {
            "status": "pending_approval",
            "response": "",
            "proposal": {**itr.reason, "interrupt_id": itr.id},
            "session_id": session_id,
            "error": None,
        }
    return {
        "status": "complete",
        "response": str(result).strip(),
        "proposal": None,
        "session_id": session_id,
        "error": None,
    }


@app.entrypoint
def invoke(payload, context):  # 2nd param MUST be named "context" (harness introspects it)
    """The single Runtime entrypoint — validate, dispatch, return a JSON-able dict.

    A plain sync function returning a dict (design §A.2): the harness runs it in a
    threadpool so ``GET /ping`` stays healthy, and serializes the returned dict to
    one ``application/json`` response. All semantic errors return the in-band error
    envelope (HTTP 200); only malformed JSON is 400'd by the harness before us.
    """
    session_id = _resolve_session_id(context)

    if not isinstance(payload, dict):
        return _error(
            "request body must be a JSON object",
            error_type="bad_request",
            session_id=session_id,
        )

    action = payload.get("action")
    if action not in _VALID_ACTIONS:
        return _error(
            "'action' must be one of {chat, approve}",
            error_type="bad_action",
            session_id=session_id,
        )

    try:
        if action == "chat":
            return _handle_chat(payload, session_id)
        return _handle_approve(payload, session_id)
    except Exception as exc:  # noqa: BLE001 - surface as an in-band error envelope
        logger.exception("Entrypoint invocation failed")
        return _error(str(exc), error_type="invocation_error", session_id=session_id)


if __name__ == "__main__":
    # In-container: uvicorn on 0.0.0.0:8080, serving /invocations + /ping.
    app.run()
