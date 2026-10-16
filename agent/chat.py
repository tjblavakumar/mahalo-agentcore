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

from agent.strands_agent import build_agent

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
    """
    result = agent(message)
    while getattr(result, "stop_reason", None) == "interrupt":
        responses = []
        approved = []  # proposal dicts captured BEFORE the resume
        for itr in result.interrupts:
            proposal = itr.reason  # {"action","system","params","description"}
            print(f"\nPROPOSED: {proposal['description']}")
            ans = input("Approve this write? [y/N] ").strip().lower()
            decision = "APPROVE" if ans in {"y", "yes"} else "REJECT"
            if decision == "APPROVE":
                approved.append(proposal)
            responses.append(
                {"interruptResponse": {"interruptId": itr.id, "response": decision}}
            )
        result = agent(responses)
        for proposal in approved:
            _emit_system_signal(agent, proposal)
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
    agent = build_agent(**_IDENTITY)
    print(_ask(agent, message))


def _run_repl() -> None:
    agent = build_agent(**_IDENTITY)
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
