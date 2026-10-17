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

import boto3
from botocore.config import Config
from strands import Agent
from strands.models import BedrockModel

from agent.approval import WriteApprovalHook
from agent.config import settings
from agent.gateway_client import _build_gateway_mcp_client
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
):
    """Build and return a configured Strands Agent.

    The system prompt is the selected role prompt (default: developer) with the
    integrations context and user identity filled in, plus a CURRENT USER
    IDENTITY block so "me"/"my"/"mine"/"assigned to me" resolve to ``developer_id``
    (default dev-6, the demo "Lava Dev" identity).

    ``tool_mode`` selects the tool source (defaults to ``settings.tool_mode``,
    i.e. ``MAHALO_TOOL_MODE`` or ``"direct"``):

    * ``direct`` (default) — the 25 local ``@tool``s hitting HTTP endpoints;
      returns the bare ``Agent``. This is the unchanged Task 1-2 behavior.
    * ``gateway`` — a Gateway-backed ``MCPClient`` is returned alongside the
      agent as ``(agent, mcp_client)``. The client is constructed OFFLINE-SAFE
      (NOT started); the caller attaches it via ``attach_gateway_tools`` (which
      performs the single ``load_tools()``-owned start) and stops it when done.

    Either way the same prefix-aware ``WriteApprovalHook`` gates the six writes.
    """
    mode = (tool_mode or settings.tool_mode).lower()
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
        return agent, mcp_client

    return Agent(
        model=model,
        tools=[*READ_TOOLS, *WRITE_TOOLS],
        system_prompt=system_prompt,
        hooks=[WriteApprovalHook()],
    )


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
