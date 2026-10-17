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

import sys

from agent.config import settings
from agent.strands_agent import attach_gateway_tools, build_agent

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


def _run_single(message: str) -> None:
    if settings.tool_mode.lower() == "gateway":
        # GATEWAY mode: attach_gateway_tools performs the SINGLE MCP start (its
        # load_tools() owns startup in strands 1.61.1); do NOT wrap in an outer
        # ``with mcp_client:`` or the client double-starts and raises. The
        # started session must stay open for every agent turn, so we stop it in
        # ``finally`` after the call completes.
        agent, mcp_client = build_agent(tool_mode="gateway", **_IDENTITY)
        try:
            attach_gateway_tools(agent, mcp_client)
            print(_ask(agent, message))
        finally:
            mcp_client.stop(None, None, None)
        return
    agent = build_agent(**_IDENTITY)
    print(_ask(agent, message))


def _run_repl() -> None:
    if settings.tool_mode.lower() == "gateway":
        # Single start via attach_gateway_tools (see _run_single); the session
        # spans every REPL turn and is torn down once the loop exits.
        agent, mcp_client = build_agent(tool_mode="gateway", **_IDENTITY)
        try:
            attach_gateway_tools(agent, mcp_client)
            _repl_loop(agent)
        finally:
            mcp_client.stop(None, None, None)
        return
    agent = build_agent(**_IDENTITY)
    _repl_loop(agent)


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


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if args:
        _run_single(" ".join(args))
    else:
        _run_repl()


if __name__ == "__main__":
    main()
