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


def _ask(agent, message: str) -> str:
    """Send one message to the agent and return its text response."""
    return str(agent(message)).strip()


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
