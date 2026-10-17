"""Build the configured Strands Agent for the local (read-only) mahalo agent.

API facts verified against the INSTALLED strands-agents 1.61.1 under
``agent/.venv/Lib/site-packages/strands`` (do not guess):

* ``from strands import Agent, tool`` — the agent class and the tool decorator.
* ``from strands.models import BedrockModel`` with
  ``BedrockModel(model_id=..., boto_session=..., boto_client_config=...)``.
  ``boto_client_config`` is the exact kwarg that accepts a botocore ``Config``,
  and ``model_id`` is a valid BedrockConfig field. The region is supplied via the
  boto3 Session because BedrockModel rejects passing both ``region_name`` and
  ``boto_session`` at once.
* ``Agent(model=..., tools=[...], system_prompt=...)``.

Building the agent is offline-safe: ``BedrockModel`` construction is lazy and
does not call AWS, so ``build_agent()`` succeeds without live credentials or
network. Only an actual agent invocation needs the ``lava`` AWS profile and a
reachable Bedrock endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass

import boto3
from botocore.config import Config
from strands import Agent
from strands.models import BedrockModel

from agent.approval import WriteApprovalHook
from agent.config import settings
from agent.gateway_client import _build_gateway_mcp_client
from agent.memory_client import (
    MemorySessionSpec,
    build_memory_session_manager,
    build_memory_session_spec,
)
from agent.prompts import ROLE_PROMPTS
from agent.tools.confluence_tools import CONFLUENCE_TOOLS
from agent.tools.github_tools import GITHUB_TOOLS
from agent.tools.github_write_tools import GITHUB_WRITE_TOOLS
from agent.tools.jira_tools import JIRA_TOOLS
from agent.tools.jira_write_tools import JIRA_WRITE_TOOLS
from agent.tools.servicenow_tools import SERVICENOW_TOOLS
from agent.tools.servicenow_write_tools import SERVICENOW_WRITE_TOOLS

READ_TOOLS = [*JIRA_TOOLS, *GITHUB_TOOLS, *CONFLUENCE_TOOLS, *SERVICENOW_TOOLS]
WRITE_TOOLS = [*JIRA_WRITE_TOOLS, *GITHUB_WRITE_TOOLS, *SERVICENOW_WRITE_TOOLS]


@dataclass
class BuildResult:
    """What ``build_agent`` returns for every mode / toggle combination.

    ``build_agent`` ALWAYS returns a ``BuildResult`` so callers read attributes
    instead of decoding a variable-arity tuple:

    * ``agent`` — the constructed ``strands.Agent`` (always present).
    * ``mcp_client`` — the Gateway ``MCPClient`` (constructed, NOT started),
      set only in GATEWAY mode; ``None`` otherwise.
    * ``session_manager`` — an OFFLINE ``MemorySessionSpec`` (plain data, no boto3
      / network), set only when Memory is enabled; ``None`` otherwise. The live
      ``AgentCoreMemorySessionManager`` is NOT built here (its SDK constructor
      does a live ``ListEvents`` read at construction). ``attach_memory`` turns
      this spec into the real manager — the single AWS touch. The attribute keeps
      the name ``session_manager`` for caller/Task-6 symmetry; it holds the
      deferred spec until ``attach_memory`` runs (see task5-verification.md).
    """

    agent: "Agent"
    mcp_client: object | None = None
    session_manager: MemorySessionSpec | None = None


def _integrations_context() -> str:
    """A short, static listing of the four systems and their base URLs."""
    return (
        f"- Jira (stories, sprints, boards, developers): {settings.jira_url}\n"
        f"- Confluence (documentation spaces/pages): {settings.confluence_url}\n"
        f"- GitHub (repositories, pull requests, commits): {settings.github_url}\n"
        f"- ServiceNow (deployments, incidents): {settings.servicenow_url}"
    )


def _build_bedrock_model() -> BedrockModel:
    """Construct the Bedrock model with a 300s read timeout and the lava profile.

    Credentials come from the AWS profile (default ``lava``) via a boto3 Session
    so no AWS keys are baked into code. If that profile is unavailable we fall
    back to the default credential chain, keeping offline import/construction
    working regardless.
    """
    boto_config = Config(
        read_timeout=settings.bedrock_read_timeout,
        connect_timeout=settings.bedrock_connect_timeout,
        retries={"max_attempts": 3, "mode": "adaptive"},
    )

    try:
        session = boto3.Session(
            profile_name=settings.aws_profile, region_name=settings.aws_region
        )
    except Exception:
        # Profile missing/misconfigured — defer to the default credential chain.
        session = boto3.Session(region_name=settings.aws_region)

    # NOTE: BedrockModel rejects passing BOTH ``region_name`` and ``boto_session``
    # ("Cannot specify both"), so the region is carried by the boto3 Session only.
    return BedrockModel(
        model_id=settings.bedrock_model_id,
        boto_session=session,
        boto_client_config=boto_config,
    )


def build_agent(
    role: str = "developer",
    user_name: str = "Lava Dev",
    user_role: str = "Developer",
    developer_id: str = "dev-6",
    tool_mode: str | None = None,
    *,
    memory: bool | None = None,
    session_id: str | None = None,
    identity: bool | None = None,
) -> "BuildResult":
    """Build and return a configured Strands Agent wrapped in a ``BuildResult``.

    The system prompt is the selected role prompt (default: developer) with the
    integrations context and user identity filled in, plus a CURRENT USER
    IDENTITY block so "me"/"my"/"mine"/"assigned to me" resolve to ``developer_id``
    (default dev-6, the demo "Lava Dev" identity).

    ``tool_mode`` selects the tool source (defaults to ``settings.tool_mode``,
    i.e. ``MAHALO_TOOL_MODE`` or ``"direct"``):

    * ``direct`` (default) — the 25 local ``@tool``s hitting HTTP endpoints.
      ``result.mcp_client`` is ``None``. This is the unchanged Task 1-2 behavior.
    * ``gateway`` — a Gateway-backed ``MCPClient`` is constructed OFFLINE-SAFE
      (NOT started) and returned on ``result.mcp_client``; the caller attaches it
      via ``attach_gateway_tools`` (which performs the single ``load_tools()``-owned
      start) and stops it when done.

    ``memory`` (Task 5, opt-in; ``None`` -> ``settings.memory_enabled``): when it
    resolves ``True`` an OFFLINE ``MemorySessionSpec`` (plain data, no boto3 /
    network) is assembled and returned on ``result.session_manager``. The live
    ``AgentCoreMemorySessionManager`` is deliberately NOT constructed here because
    its SDK constructor performs a live ``ListEvents`` read at construction time;
    ``build_agent`` must stay fully offline. The caller wires Memory live exactly
    once with ``attach_memory``, which builds the real manager from the spec (the
    single AWS touch). A ``ValueError`` is raised when ``memory`` is ``True`` but
    ``MAHALO_MEMORY_ID`` is empty (mirrors the GATEWAY URL guard). Memory composes
    with either tool mode.

    ``identity`` (Task 5, opt-in; ``None`` -> ``settings.identity_enabled``) does
    not change construction — it only governs the body-local credential fetch in
    ``agent/tools/jira_write_tools.py`` at call time. The parameter is accepted so
    callers (and Task 6) can resolve it explicitly, but the default (``None`` ->
    ``settings.identity_enabled``) leaves construction untouched.

    Either way the same prefix-aware ``WriteApprovalHook`` gates the six writes.
    """
    mode = (tool_mode or settings.tool_mode).lower()
    use_memory = settings.memory_enabled if memory is None else memory
    model = _build_bedrock_model()

    system_prompt = ROLE_PROMPTS[role].format(
        integrations_context=_integrations_context(),
        user_name=user_name,
        user_role=user_role,
    )
    system_prompt += (
        "\n\nCURRENT USER IDENTITY:\n"
        f"The logged-in user is developer id {developer_id} ({user_name}). "
        f'When the user says "me", "my", "mine", or "assigned to me", use the '
        f"developer id {developer_id} directly — do not ask who they are and do "
        f"not try to resolve their name; it is already known.\n"
    )

    # Memory session SPEC (offline, plain data — NO boto3, NO network). The live
    # manager is built later in attach_memory (its SDK constructor hits AWS).
    session_manager = None
    if use_memory:
        if not settings.memory_id:
            raise ValueError(
                "MEMORY mode requires MAHALO_MEMORY_ID (the MemoryId CfnOutput "
                "from MahaloMemoryIdentityStack)."
            )
        resolved_session_id = (
            session_id if session_id is not None else settings.session_id
        )
        session_manager = build_memory_session_spec(
            resolved_session_id,
            actor_id=developer_id,
            region=settings.memory_region,
        )

    if mode == "gateway":
        mcp_client = _build_gateway_mcp_client()  # constructed, NOT started
        # The agent is built WITHOUT the MCP tools here so construction stays
        # offline-safe: passing an MCPClient into ``Agent(tools=[...])`` would
        # eagerly ``load_tools()`` (starting the client / hitting the network).
        # The caller attaches the provider with ``attach_gateway_tools`` (the
        # single start) and stops the client afterwards (see agent/chat.py).
        agent = Agent(
            model=model,
            tools=[],
            system_prompt=system_prompt,
            hooks=[WriteApprovalHook()],
        )
        return BuildResult(
            agent=agent, mcp_client=mcp_client, session_manager=session_manager
        )

    agent = Agent(
        model=model,
        tools=[*READ_TOOLS, *WRITE_TOOLS],
        system_prompt=system_prompt,
        hooks=[WriteApprovalHook()],
    )
    return BuildResult(agent=agent, session_manager=session_manager)


def attach_gateway_tools(agent, mcp_client) -> None:
    """Register the Gateway MCP tools onto ``agent``, starting the client once.

    In strands-agents 1.61.1 an ``MCPClient`` is a ``ToolProvider``:
    ``process_tools([mcp_client])`` registers it as a provider and calls its
    ``load_tools()``, which OWNS the single startup — it calls ``start()`` and
    sets ``_tool_provider_started``. Wrapping this in an outer ``with
    mcp_client:`` first calls ``start()`` without flipping that flag, so
    ``load_tools()`` tries to ``start()`` a second time and raises
    ``MCPClientInitializationError: the client session is currently running``
    (surfaced as ``ToolProviderException`` -> ``ValueError``). So the client must
    NOT be pre-started; this helper is the single start. The caller keeps the
    started session alive for every agent turn and tears it down with
    ``mcp_client.stop(...)`` afterwards (see agent/chat.py).
    """
    agent.tool_registry.process_tools([mcp_client])


def attach_memory(agent, session_spec: "MemorySessionSpec"):
    """Wire AgentCore Memory onto ``agent`` from a spec (the single AWS step).

    This is the SINGLE place Memory touches AWS (symmetric with
    ``attach_gateway_tools`` for the Gateway client). ``build_agent`` only
    assembled an offline ``MemorySessionSpec``; here we:

    0. ``build_memory_session_manager(session_spec)`` — CONSTRUCT the live
       ``AgentCoreMemorySessionManager``. The SDK constructor itself performs the
       live ``ListEvents`` read (``RepositorySessionManager.__init__`` ->
       ``read_session``), so construction is deliberately deferred to here rather
       than ``build_agent`` (which must stay offline — see task5-verification.md).
    1. ``agent.hooks.add_hook(manager)`` — the ``HookRegistry.add_hook`` method
       (NOT ``Agent.add_hook``). ``HookRegistry.add_hook(provider)`` calls
       ``provider.register_hooks(...)``, which in sync mode installs BOTH the
       ``AgentInitializedEvent`` -> ``initialize`` callback AND the per-turn
       ``MessageAddedEvent`` / ``AfterInvocationEvent`` persistence callbacks — so
       future turns are actually written to Memory. ``Agent.add_hook`` would
       register a single callback and infer the event type from a type hint; a
       ``HookProvider`` is not a callback, so it would mis-register and the
       per-turn persistence callbacks would never be installed (Memory would
       silently persist nothing).
    2. ``manager.initialize(agent)`` — applies the rehydrated session history to
       the agent EXACTLY ONCE. ``AgentInitializedEvent`` already fired during the
       bare ``Agent(...)`` construction (when no manager was attached), so the
       callback registered in step 1 will not re-fire for this already-constructed
       agent; hence the single explicit call.
    3. ``agent._session_id = manager.session_id`` — match the agent's session id
       to the manager (the value ``Agent.__init__`` would have derived had a
       manager been passed in).

    Returns the constructed manager so callers can hold it (e.g. to print the
    resolved session id).
    """
    manager = build_memory_session_manager(session_spec)
    agent.hooks.add_hook(manager)
    manager.initialize(agent)
    agent._session_id = manager.session_id
    return manager
