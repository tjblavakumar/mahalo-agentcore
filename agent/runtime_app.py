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
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent

from agent import model_config, roadmap, roadmap_fetch, skills
from agent.config import settings
from agent.hitl import emit_system_signal, resume_once
from agent.prompts import ROLE_PROMPTS
from agent.review import build_reviewer, review_code
from agent.runtime_session import build_and_attach
from agent.strands_agent import _build_bedrock_model

logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

# Entrypoint caps / defaults (design "Input validation").
_PROMPT_MAX_BYTES = 32 * 1024
_DEFAULT_DEVELOPER_ID = "dev-6"
_DEFAULT_ROLE = "developer"
_VALID_ACTIONS = {"chat", "approve", "skill_check", "skill_run"}
CHECK_DEADLINE_S = 45.0
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


# Multi-LLM review seam (FEAT-001). A fenced code block is ```[lang]\n...\n```.
_FENCED_CODE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


# Design documents / ADRs are prose, not code: a markdown fence whose frontmatter
# carries a design ``doc_type`` is removed before code extraction so it does not
# trigger the review stage. Every other fence (incl. skill drafts) is untouched.
_DOC_FENCE_RE = re.compile(
    r"(?ms)^(`{3,})[ \t]*(?:markdown|md)[ \t]*\n(.*?)\n\1[ \t]*$"
)
_DOC_TYPES = {"adr", "design", "design-review"}


def _is_doc_body(body: str) -> bool:
    lines = body.replace("\r", "").split("\n")
    if lines[0].strip() != "---":
        return False
    doc_type = None
    for line in lines[1:]:
        if line.strip() == "---":
            return doc_type in _DOC_TYPES
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() == "doc_type":
            doc_type = value.strip().lower()
    return False  # no closing frontmatter line


def _strip_doc_fences(text: str) -> str:
    def _repl(m):
        return "" if _is_doc_body(m.group(2)) else m.group(0)

    return _DOC_FENCE_RE.sub(_repl, text)


def _extract_fenced_code(text: str) -> str:
    """Return the concatenation of all fenced code blocks in ``text`` (or '')."""
    if not isinstance(text, str):
        return ""
    text = _strip_doc_fences(text)
    blocks = _FENCED_CODE_RE.findall(text)
    return "\n\n".join(b.strip("\n") for b in blocks)


def _extract_commit_files_code(proposal: dict) -> str:
    """Return the concatenated file bodies from a commit_files proposal (or '').

    The commit_files write carries ``params.files`` as a list of
    ``{path, content}`` dicts (``agent/tools/github_write_tools.py``).
    """
    params = proposal.get("params") or {}
    files = params.get("files")
    if not isinstance(files, list):
        return ""
    parts = []
    for entry in files:
        if isinstance(entry, dict):
            content = entry.get("content")
            if isinstance(content, str) and content:
                parts.append(content)
    return "\n\n".join(parts)


def _run_review(
    code: str, review_model_id: str, did_fallback: bool, files: list | None = None
) -> tuple[list, dict]:
    """Run the review stage over ``code`` and build the additive stages/review.

    Always returns a ``stages`` list that starts with the ``generate`` stage. When
    ``code`` is non-empty a ``review`` stage is appended and a ``review`` object is
    returned; otherwise the review object is ``None`` and only ``generate`` is in
    ``stages`` (FR-17: no code -> no review).
    """
    stages = [
        {
            "stage": "generate",
            "model_id": model_config.CODE_GEN_MODEL_ID,
            "model_label": model_config.CODE_GEN_MODEL_LABEL,
            "status": "ok",
        }
    ]
    if not code:
        return stages, None

    reviewer = build_reviewer(review_model_id)
    if files:
        result = review_code(reviewer, code, files=files)
    else:
        result = review_code(reviewer, code)
    stages.append(
        {
            "stage": "review",
            "model_id": review_model_id,
            "model_label": model_config.label(review_model_id),
            "status": result.status,
            "fallback": did_fallback,
        }
    )
    review = {
        "model_id": review_model_id,
        "model_label": model_config.label(review_model_id),
        "findings": result.findings_text,
        "status": result.status,
    }
    file_summaries = getattr(result, "file_summaries", None)
    if files and file_summaries:
        review["file_summaries"] = file_summaries
    return stages, review


def _handle_chat(
    payload: dict,
    session_id: str,
    *,
    extra_hooks=(),
    review_final_text: bool = True,
) -> dict:
    """Chat leg: one agent turn; return a proposal on interrupt, else the reply.

    ``extra_hooks`` are added after the approval hook (skill runs pass the budget
    hook). ``review_final_text=False`` skips the fenced-code review of a completed
    answer (``stages``/``review`` are then absent); a ``commit_files`` proposal is
    still reviewed.
    """
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
    review_model_id, did_fallback = model_config.resolve_review_model(
        payload.get("review_model_id")
    )

    attached = build_and_attach(
        session_id, developer_id=developer_id, role=role, pending_write=False
    )
    for hook in extra_hooks:
        attached.agent.hooks.add_hook(hook)
    try:
        result = attached.agent(prompt)
    finally:
        if attached.mcp_client is not None:
            attached.mcp_client.stop(None, None, None)

    if getattr(result, "stop_reason", None) == "interrupt":
        itr = result.interrupts[0]
        proposal = {**itr.reason, "interrupt_id": itr.id}
        # Review ONLY the commit_files proposal's file bodies; create_branch /
        # open_pull_request carry no code so they are not reviewed. The reviewer
        # is tools=[] and never reaches the interrupt path, so status and the
        # proposal dict are left byte-for-byte unchanged.
        code = ""
        files = None
        if itr.reason.get("system") == "github" and itr.reason.get("action") == "commit_files":
            code = _extract_commit_files_code(itr.reason)
            raw_files = (itr.reason.get("params") or {}).get("files")
            if isinstance(raw_files, list):
                files = raw_files
        stages, review = _run_review(code, review_model_id, did_fallback, files)
        out = {
            "status": "pending_approval",
            "response": "",
            "proposal": proposal,
            "session_id": session_id,
            "error": None,
            "stages": stages,
        }
        if review is not None:
            out["review"] = review
        return out

    response = str(result).strip()
    # On the complete branch review the concatenation of fenced code blocks, only
    # when at least one is present (FR-17: a no-code turn gets no review stage).
    out = {
        "status": "complete",
        "response": response,
        "proposal": None,
        "session_id": session_id,
        "error": None,
    }
    if not review_final_text:
        return out
    code = _extract_fenced_code(response) if response else ""
    stages, review = _run_review(code, review_model_id, did_fallback)
    out["stages"] = stages
    if review is not None:
        out["review"] = review
    return out


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

    # 'role' is forwarded on the approve leg: the resume replays the stored tool
    # call without a model call, then runs the tool and makes one model call for the
    # final reply, so the role is needed for both the role-access hook and the
    # role system prompt. A missing role resolves to the default (developer).
    # 'tool_mode' is the Runtime env constant, so the rebuilt registry matches the
    # chat leg's by construction.
    role = _resolve_role(payload.get("role"))
    attached = build_and_attach(
        session_id, developer_id=developer_id, role=role, pending_write=True
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


def _validate_skill_input(payload: dict, session_id: str, *, project_required: bool):
    """Return ``(name, body, project, None)`` or ``(None, None, None, error_envelope)``."""

    def bad(message: str, error_type: str):
        return None, None, None, _error(
            message, error_type=error_type, session_id=session_id
        )

    name = payload.get("skill_name")
    body = payload.get("skill_body")
    if (
        not isinstance(name, str)
        or len(name) > skills.MAX_COMMAND_NAME_LEN
        or not skills.COMMAND_NAME_RE.match(name)
    ):
        return bad("skill_name is not a valid skill command name", "bad_skill")
    if not isinstance(body, str) or not body.strip():
        return bad("skill_body must be non-empty text", "bad_skill")
    if len(body.encode("utf-8")) > skills.MAX_SKILL_BYTES:
        return bad("The skill is larger than 16 KB.", "bad_skill")
    reason = skills.refusal_reason(body)
    if reason:
        return bad(reason, "bad_skill")
    raw_project = payload.get("project")
    project = skills.normalise_project(raw_project)
    if (raw_project is not None or project_required) and project is None:
        return bad(
            "project must be one of " + ", ".join(skills.SKILL_PROJECTS),
            "bad_project",
        )
    return name, body, project, None


def _build_check_agent(manifest) -> Agent:
    """A tool-less one-shot agent: read-only by construction, no hooks, no Memory."""
    model = _build_bedrock_model(
        settings.bedrock_model_id, read_timeout=40, max_attempts=1, max_tokens=6000
    )
    return Agent(
        model=model,
        tools=[],
        system_prompt=skills.build_check_system_prompt(manifest),
    )


def _handle_skill_check(payload: dict, session_id: str) -> dict:
    """Plan a skill without running it (design C). Returns ``skill_check``."""
    name, body, project, err = _validate_skill_input(
        payload, session_id, project_required=False
    )
    if err:
        return err
    manifest = skills.build_manifest()
    check_agent = _build_check_agent(manifest)
    user_msg = skills.build_check_user_message(name, project, body, skills.new_nonce())

    pool = ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(
        check_agent, user_msg, structured_output_model=skills.SkillCheckDraft
    )
    try:
        result = fut.result(timeout=CHECK_DEADLINE_S)
    except FutureTimeout:
        pool.shutdown(wait=False)  # never the ``with`` form: it would block
        return _error(
            "The check took too long. Try again.",
            error_type="check_timeout", session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001 - in-band error envelope
        pool.shutdown(wait=False)
        logger.exception("Skill check failed")
        kind = type(exc).__name__.lower()
        if "timeout" in kind or "throttl" in kind:
            return _error(
                "The check took too long. Try again.",
                error_type="check_timeout", session_id=session_id,
            )
        return _error(
            "The check could not be completed. Try again.",
            error_type="check_failed", session_id=session_id,
        )
    pool.shutdown(wait=False)

    draft = getattr(result, "structured_output", None)
    if not isinstance(draft, skills.SkillCheckDraft):
        return _error(
            "The check returned no usable plan. Try again.",
            error_type="check_invalid_output", session_id=session_id,
        )
    try:
        check = skills.build_check(draft, body, project, manifest)
    except skills.CheckEmpty:
        return _error(
            "The check found no steps in this skill.",
            error_type="check_empty", session_id=session_id,
        )
    return {
        "status": "complete",
        "response": "",
        "proposal": None,
        "session_id": session_id,
        "error": None,
        "skill_check": check.model_dump(),
    }


def _roadmap_envelope(session_id: str, response: str, budget, name: str, project: str) -> dict:
    return {
        "status": "complete",
        "response": response,
        "proposal": None,
        "session_id": session_id,
        "error": None,
        "skill_run": budget.info(name, project),
    }


def _handle_roadmap_run(session_id: str, name: str, project: str) -> dict:
    """Run a computed built-in skill: fetch, compute and render it entirely in code.

    No model call is made: the whole answer is the rendered plan. A fetch or
    compute failure returns a fixed message and never asks the model for numbers.
    """
    budget = skills.SkillRunBudget()
    try:
        try:
            sources, calls = roadmap_fetch.fetch_sources(project)
            budget.calls = calls
        except roadmap.PlanUnavailable as exc:
            budget.calls = getattr(exc, "calls", 0)
            raise
        plan = roadmap.compute_plan(
            project,
            sources["sprints"],
            sources["stories"],
            sources["developers"],
            sources["incidents"],
            sources["deployments"],
        )
    except roadmap.PlanUnavailable as exc:
        return _roadmap_envelope(session_id, exc.message, budget, name, project)
    return _roadmap_envelope(session_id, roadmap.render_plan(plan), budget, name, project)


def _handle_skill_run(payload: dict, session_id: str) -> dict:
    """Run a consented skill as a bounded chat turn (design D)."""
    name, body, project, err = _validate_skill_input(
        payload, session_id, project_required=True
    )
    if err:
        return err
    if name in skills.COMPUTED_SKILLS:
        return _handle_roadmap_run(session_id, name, project)
    try:
        prompt = skills.wrap_skill_run(name, project, body)
    except skills.SkillRefused as exc:
        return _error(str(exc), error_type="bad_skill", session_id=session_id)

    budget = skills.SkillRunBudget()
    out = _handle_chat(
        {
            "prompt": prompt,
            "developer_id": payload.get("developer_id"),
            "role": payload.get("role"),
            "review_model_id": payload.get("review_model_id"),
        },
        session_id,
        extra_hooks=[budget],
        review_final_text=False,
    )
    if out.get("status") not in ("complete", "pending_approval"):
        return out
    if out["status"] == "complete":
        if budget.hard_stopped:
            out["response"] = budget.notice()
        elif budget.exhausted:
            out["response"] = (out.get("response") or "") + "\n\n" + budget.notice()
    out["skill_run"] = budget.info(name, project)
    return out


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
            "'action' must be one of {chat, approve, skill_check, skill_run}",
            error_type="bad_action",
            session_id=session_id,
        )

    try:
        if action == "chat":
            return _handle_chat(payload, session_id)
        if action == "skill_check":
            return _handle_skill_check(payload, session_id)
        if action == "skill_run":
            return _handle_skill_run(payload, session_id)
        return _handle_approve(payload, session_id)
    except Exception as exc:  # noqa: BLE001 - surface as an in-band error envelope
        logger.exception("Entrypoint invocation failed")
        return _error(str(exc), error_type="invocation_error", session_id=session_id)


if __name__ == "__main__":
    # In-container: uvicorn on 0.0.0.0:8080, serving /invocations + /ping.
    app.run()
