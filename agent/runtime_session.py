"""Per-invocation agent build+attach for the AgentCore Runtime entrypoint (Task 6).

The Runtime entrypoint (``agent/runtime_app.py``) builds and attaches the agent
**per invocation** from the request's session id (design §D.2). This module holds
the single composition helper so the entrypoint stays thin and the Task-5 seams
(``build_agent`` -> ``attach_gateway_tools`` -> ``attach_memory``) are reused
exactly as ``agent/chat.py`` uses them — no duplication, no second agent.

``build_and_attach`` is the ONLY export. The resume/breadcrumb helpers live in
``agent/hitl.py`` (design §C.3); there is no resume helper here.

``tool_mode`` is resolved from ``settings.tool_mode`` (the Runtime-process env
constant ``MAHALO_TOOL_MODE``), never a per-request field, so both HITL legs
rebuild the identical tool registry (design §B.3 invariant).
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.config import settings
from agent.strands_agent import attach_gateway_tools, attach_memory, build_agent


@dataclass
class AttachedAgent:
    """A ready-to-run agent plus the GATEWAY teardown handle.

    ``mcp_client`` is the started Gateway ``MCPClient`` in GATEWAY mode (the
    entrypoint must ``stop(...)`` it in a ``finally``) or ``None`` in DIRECT mode.
    """

    agent: object
    mcp_client: object | None = None


def build_and_attach(
    session_id: str,
    developer_id: str = "dev-6",
    role: str = "developer",
    *,
    pending_write: bool = False,
) -> AttachedAgent:
    """Build the agent for ``session_id`` and attach Gateway (if any) + Memory.

    Mirrors ``agent/chat.py`` exactly:

    1. ``build_agent(memory=True, session_id=..., developer_id=..., role=...,
       pending_write=...)`` — offline construction (model is lazy; the Memory
       spec is plain data).
    2. In GATEWAY mode, ``attach_gateway_tools`` performs the single MCP start
       (its ``load_tools()`` owns startup — do NOT wrap in ``with mcp_client:``).
    3. ``attach_memory`` is the single AWS touch (the ``ListEvents`` rehydrate +
       hook registration), restoring history and — on a pending-write leg — the
       interrupt state.

    Returns an :class:`AttachedAgent`. The entrypoint stops ``mcp_client`` (when
    set) in a ``finally`` after the agent call completes.
    """
    result = build_agent(
        role=role,
        developer_id=developer_id,
        memory=True,
        session_id=session_id,
        pending_write=pending_write,
    )
    mcp_client = None
    if settings.tool_mode.lower() == "gateway":
        attach_gateway_tools(result.agent, result.mcp_client)
        mcp_client = result.mcp_client
    attach_memory(result.agent, result.session_manager)
    return AttachedAgent(agent=result.agent, mcp_client=mcp_client)
