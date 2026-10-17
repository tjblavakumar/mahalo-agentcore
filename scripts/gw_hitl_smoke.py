"""Live HITL-write smoke driver for GATEWAY mode (Task 4 verification).

Drives the SAME ``chat._ask``/interrupt path chat.py uses, but feeds a scripted
answer through ``builtins.input`` so no interactive stdin is needed. Runs the
GATEWAY lifecycle exactly like ``chat._run_single`` (single start via
``attach_gateway_tools``, ``mcp_client.stop`` in ``finally``).

Usage (GATEWAY mode env must be set — MAHALO_TOOL_MODE=gateway,
MAHALO_GATEWAY_MCP_URL=<deployed Gateway MCP URL>, plus AWS_PROFILE/AWS_REGION):
    python -m scripts.gw_hitl_smoke <approve|reject> "<message>"

A convenience for re-running the propose/approve/reject gate against a deployed
Gateway without an interactive terminal; not part of the shipped agent runtime.
"""

from __future__ import annotations

import builtins
import sys

from agent import chat
from agent.strands_agent import attach_gateway_tools, build_agent


def _run(decision: str, message: str) -> None:
    answer = "y" if decision == "approve" else "n"

    # Feed the scripted yes/no into the exact input() prompt chat._ask uses.
    orig_input = builtins.input

    def fake_input(prompt: str = "") -> str:
        print(f"{prompt}{answer}   <- scripted {decision.upper()}")
        return answer

    builtins.input = fake_input
    try:
        agent, mcp_client = build_agent(tool_mode="gateway", **chat._IDENTITY)
        try:
            attach_gateway_tools(agent, mcp_client)
            print("=== AGENT FINAL ANSWER ===")
            print(chat._ask(agent, message))
        finally:
            mcp_client.stop(None, None, None)
    finally:
        builtins.input = orig_input


if __name__ == "__main__":
    _run(sys.argv[1], sys.argv[2])
