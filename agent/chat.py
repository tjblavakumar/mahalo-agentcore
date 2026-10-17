"""CLI / REPL entrypoint for the local Strands agent.

Usage:
    python -m agent.chat "show my stories"   # single-shot
    python -m agent.chat                      # interactive REPL

The agent is built with the developer prompt and the dev-6 ("Lava Dev")
identity, so "show my stories" resolves to dev-6 (PAY stories in the seed data).

Importing this module is offline-safe (no AWS creds / network needed). Only an
actual run — sending a message — needs the ``lava`` AWS profile and a reachable
Bedrock endpoint (and the mock tunnel for the tools to return data).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

from agent.config import settings
from agent.strands_agent import attach_gateway_tools, attach_memory, build_agent

_IDENTITY = {
    "role": "developer",
    "user_name": "Lava Dev",
    "user_role": "Developer",
    "developer_id": "dev-6",
}


def _ask(agent, message) -> str:
    """Send one message to the agent and drive the HITL approval loop.

    A write tool pauses the agent with ``stop_reason == "interrupt"``; for each
    pending interrupt we show the proposal, read a yes/no, and resume the agent
    with an ``interruptResponse`` block. On approve the write body runs and we
    append a ``[SYSTEM]`` breadcrumb so the chain (branch -> commit -> PR) is not
    re-proposed; on reject nothing is written and nothing is appended.

    Breadcrumb timing matters for history validity. The resume turn replays the
    still-open ``toolUse`` assistant message and only appends its matching
    ``toolResult`` when the tool cycle closes. If that resume turn ends in ANOTHER
    interrupt (a chained or re-proposed write), the ``toolUse`` is still open and
    its ``toolResult`` has not landed yet; appending an assistant ``[SYSTEM]``
    message at that point wedges a zero-``toolUse`` turn between the open
    ``toolUse`` and its pending ``toolResult``, so the next Converse call fails
    with "toolResult blocks ... exceeds ... toolUse blocks of previous turn".
    So we DEFER each approved breadcrumb and flush the pending ones only once a
    resume returns a non-interrupt result (the cycle is fully closed and the
    message history is valid). This is mode-agnostic: in DIRECT mode each write's
    resume closes its own cycle, so the breadcrumb still lands before the model
    proposes the next chained step, keeping branch -> commit -> PR intact.
    """
    result = agent(message)
    pending_breadcrumbs: list[dict] = []  # approved proposals awaiting a closed cycle
    while getattr(result, "stop_reason", None) == "interrupt":
        responses = []
        for itr in result.interrupts:
            proposal = itr.reason  # {"action","system","params","description"}
            print(f"\nPROPOSED: {proposal['description']}")
            ans = input("Approve this write? [y/N] ").strip().lower()
            decision = "APPROVE" if ans in {"y", "yes"} else "REJECT"
            if decision == "APPROVE":
                pending_breadcrumbs.append(proposal)
            responses.append(
                {"interruptResponse": {"interruptId": itr.id, "response": decision}}
            )
        result = agent(responses)
        # Only flush breadcrumbs once the tool cycle is fully closed (this resume
        # did NOT re-interrupt). While another interrupt is pending the toolUse is
        # still open awaiting its toolResult, so inserting an assistant message
        # now would corrupt the toolUse/toolResult pairing.
        if getattr(result, "stop_reason", None) != "interrupt":
            for proposal in pending_breadcrumbs:
                _emit_system_signal(agent, proposal)
            pending_breadcrumbs = []
    return str(result).strip()


def _emit_system_signal(agent, proposal: dict) -> None:
    """Append a ``[SYSTEM]`` breadcrumb to history after an APPROVED write.

    Keyed on ``proposal["action"]`` using the three verbatim templates from
    task2-design.md for the GitHub chain, with a generic fallback for the other
    writes. Called on approve only; nothing is emitted on reject.
    """
    action = proposal["action"]
    p = proposal["params"]

    if action == "create_branch":
        msg = (
            f"[SYSTEM] The user APPROVED and the branch '{p['branch_name']}' "
            f"now exists in repo '{p['repo_id']}'. Do NOT propose creating it "
            f"again. Next, if the user asked to commit code, propose "
            f"github_commit_files to that branch with the full file contents you "
            f"prepared earlier."
        )
    elif action == "commit_files":
        msg = (
            f"[SYSTEM] The user APPROVED and the files were committed to branch "
            f"'{p['branch']}' in repo '{p['repo_id']}'. Do NOT propose "
            f"committing again. Next, if the user wants a PR, propose "
            f"github_open_pull_request from '{p['branch']}' into main."
        )
    elif action == "open_pull_request":
        msg = (
            f"[SYSTEM] The user APPROVED and a pull request was opened from "
            f"'{p['head']}' into '{p.get('base', 'main')}' in repo "
            f"'{p['repo_id']}'. The check-in flow is complete."
        )
    else:
        msg = f"[SYSTEM] The user approved and the '{action}' action was executed."

    agent.messages.append({"role": "assistant", "content": [{"text": msg}]})


def _wire_memory(result, session_id: str | None) -> None:
    """Attach Memory live (the single AWS-touching step) when enabled.

    Only runs when ``build_agent`` returned a session manager (i.e. Memory is on).
    The resume/new-session notice is printed ONLY in that case so default output
    is unchanged.
    """
    if result.session_manager is None:
        return
    # attach_memory builds the live manager from the offline spec (single AWS
    # touch) and returns it; its session_id matches the spec's.
    manager = attach_memory(result.agent, result.session_manager)
    print(f"[memory] session {manager.session_id}")


def _run_single(message: str, *, session_id: str | None = None) -> None:
    if settings.tool_mode.lower() == "gateway":
        # GATEWAY mode: attach_gateway_tools performs the SINGLE MCP start (its
        # load_tools() owns startup in strands 1.61.1); do NOT wrap in an outer
        # ``with mcp_client:`` or the client double-starts and raises. The
        # started session must stay open for every agent turn, so we stop it in
        # ``finally`` after the call completes.
        result = build_agent(tool_mode="gateway", session_id=session_id, **_IDENTITY)
        try:
            attach_gateway_tools(result.agent, result.mcp_client)
            _wire_memory(result, session_id)
            print(_ask(result.agent, message))
        finally:
            result.mcp_client.stop(None, None, None)
        return
    result = build_agent(session_id=session_id, **_IDENTITY)
    _wire_memory(result, session_id)
    print(_ask(result.agent, message))


def _run_repl(*, session_id: str | None = None) -> None:
    if settings.tool_mode.lower() == "gateway":
        # Single start via attach_gateway_tools (see _run_single); the session
        # spans every REPL turn and is torn down once the loop exits.
        result = build_agent(tool_mode="gateway", session_id=session_id, **_IDENTITY)
        try:
            attach_gateway_tools(result.agent, result.mcp_client)
            _wire_memory(result, session_id)
            _repl_loop(result.agent)
        finally:
            result.mcp_client.stop(None, None, None)
        return
    result = build_agent(session_id=session_id, **_IDENTITY)
    _wire_memory(result, session_id)
    _repl_loop(result.agent)


def _repl_loop(agent) -> None:
    print("mahalo agent (developer / dev-6). Type 'quit' or 'exit' to leave.")
    while True:
        try:
            message = input("\n> ").strip()
        except EOFError:
            print()
            break
        if not message:
            continue
        if message.lower() in {"quit", "exit"}:
            break
        print(_ask(agent, message))


def _resolve_session_id(flag_value: str | None) -> str | None:
    """Session-id precedence: ``--session-id`` > ``MAHALO_SESSION_ID`` > uuid4.

    The uuid4 fallback is used ONLY when Memory is enabled and neither the flag
    nor the env var supplied an id; when Memory is off this returns ``None`` and
    the id is never used. Returns a stripped non-empty string or ``None``.
    """
    if flag_value is not None and flag_value.strip():
        return flag_value.strip()
    env_value = os.getenv("MAHALO_SESSION_ID", "").strip()
    if env_value:
        return env_value
    if settings.memory_enabled:
        return uuid.uuid4().hex
    return None


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="agent.chat", add_help=True)
    parser.add_argument("--session-id", dest="session_id", default=None)
    parser.add_argument("message", nargs="*")
    ns = parser.parse_args(args)
    session_id = _resolve_session_id(ns.session_id)
    # Message words after options are joined with a single space, so
    # ``python -m agent.chat "show my stories"`` is unchanged and the bare-REPL
    # invocation (no message words) still enters the REPL.
    if ns.message:
        _run_single(" ".join(ns.message), session_id=session_id)
    else:
        _run_repl(session_id=session_id)


if __name__ == "__main__":
    main()
