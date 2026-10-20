"""AgentCore Memory session-manager construction for the agent (Task 5).

Bridges Strands' native ``session_manager=`` seam to AgentCore Memory via
``bedrock_agentcore``'s ``AgentCoreMemorySessionManager`` (which subclasses
Strands' ``RepositorySessionManager``).

Offline-safety / construction-boundary note (Option 1, see
``docs/.agents/tasks/task5-verification.md``): the installed
``bedrock-agentcore 1.24.1`` ``AgentCoreMemorySessionManager.__init__`` is NOT
offline-safe — its ``super().__init__()`` reaches
``RepositorySessionManager.__init__``, which calls ``read_session`` ->
``ListEvents`` (a live network read) at construction time. The approved design's
intent was a single isolated AWS touch behind ``attach_memory`` with
``build_agent`` fully offline. To honor that intent with this SDK, the
construction boundary is relocated by one function: ``build_agent(memory=True)``
assembles only a lightweight, offline ``MemorySessionSpec`` (plain data, no boto3,
no network) and places it on ``BuildResult.session_manager``; the REAL
``AgentCoreMemorySessionManager`` is constructed inside
``agent.strands_agent.attach_memory`` via ``build_memory_session_manager(spec)``,
which is the one place that touches AWS (the rehydrate / ``ListEvents``).

Short-term-memory only: the config carries no ``retrieval_config`` (no long-term
strategy retrieval), ``filter_restored_tool_context=True`` strips historical
``toolUse``/``toolResult`` blocks on restore so a resumed session cannot replay a
half-open tool cycle, and ``batch_size=1`` writes each turn immediately (nothing
to flush / no ``close()`` dance).
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.config import settings


@dataclass(frozen=True)
class MemorySessionSpec:
    """Offline, plain-data description of a Memory session to build later.

    Assembled by ``build_agent`` with NO boto3 / network. ``attach_memory`` passes
    it to ``build_memory_session_manager`` to construct the live session manager
    (the single AWS touch). ``memory_id`` is captured from ``settings`` at build
    time so the spec is self-contained.
    """

    session_id: str
    actor_id: str
    region: str
    memory_id: str
    # Task 6 (design §C.4): default ``True`` preserves the Task-5 STM behavior
    # byte-for-byte. A pending-write session (an approve leg, or any build whose
    # restored interrupt_state carries a pending_tool_execution) sets this to
    # ``False`` so ``list_messages`` keeps the open toolUse/toolResult in the
    # restored message list and cannot disagree with the separate interrupt_state
    # restore channel across a cold Runtime process boundary.
    filter_restored_tool_context: bool = True


def build_memory_session_spec(
    session_id: str,
    actor_id: str,
    *,
    region: str,
    pending_write: bool = False,
) -> MemorySessionSpec:
    """Assemble a ``MemorySessionSpec`` — offline-safe, no network, no boto3.

    Called inside ``build_agent(memory=True)``. ``session_id`` groups one
    conversation; ``actor_id`` identifies the user (defaults to the
    ``developer_id`` threaded through ``build_agent``). ``memory_id`` is read from
    ``settings`` (already validated non-empty by ``build_agent``'s guard).

    ``pending_write`` (Task 6, design §C.4) flips the HITL restore contract: a
    pending-write session is built with ``filter_restored_tool_context=False`` so
    the open toolUse/toolResult survive the restored message list. The default
    ``False`` keeps ``filter_restored_tool_context=True`` (the exact Task-5
    behavior) for every non-pending-write session.
    """
    return MemorySessionSpec(
        session_id=session_id,
        actor_id=actor_id,
        region=region,
        memory_id=settings.memory_id,
        filter_restored_tool_context=(not pending_write),
    )


def build_memory_session_manager(spec: MemorySessionSpec):
    """Construct the live ``AgentCoreMemorySessionManager`` from a spec.

    THIS IS NOT OFFLINE-SAFE and must only be called from ``attach_memory`` (the
    single AWS touch): the SDK constructor performs a live ``ListEvents`` read to
    rehydrate (and ``create_session`` for a new session). ``bedrock_agentcore`` /
    boto3 are imported lazily inside the body so importing this module never
    requires them.
    """
    from bedrock_agentcore.memory.integrations.strands.config import (
        AgentCoreMemoryConfig,
    )
    from bedrock_agentcore.memory.integrations.strands.session_manager import (
        AgentCoreMemorySessionManager,
    )

    config = AgentCoreMemoryConfig(
        memory_id=spec.memory_id,
        session_id=spec.session_id,
        actor_id=spec.actor_id,
        # STM only: no retrieval_config => no long-term record retrieval.
        # The flag is carried on the spec (default True = Task-5 behavior); a
        # pending-write session passes False so the restored message list keeps
        # the open toolUse/toolResult intact (design §C.4).
        filter_restored_tool_context=spec.filter_restored_tool_context,
        batch_size=1,
    )
    return AgentCoreMemorySessionManager(config, region_name=spec.region)
