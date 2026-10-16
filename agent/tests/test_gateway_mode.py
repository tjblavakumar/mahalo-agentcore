"""Agent-side GATEWAY-mode tests (Task 4), all offline.

* ``build_agent(tool_mode="gateway")`` imports/constructs cleanly with no AWS
  call or network — the MCP client is constructed, NOT started — and returns the
  ``(agent, mcp_client)`` tuple.
* EXACT bidirectional arg-set parity between each live ``@tool`` signature and
  its ``common.tool_schemas`` descriptor (a missing OR a spurious arg fails).
  This runs here because strands is installed in the agent venv.
"""

from __future__ import annotations

import inspect
import os
import sys

import pytest

from strands import Agent
from strands.tools.mcp import MCPClient

# ``common`` (under tools-lambdas) is importable because importing agent.tools
# adds it to sys.path; make the dependency explicit here too.
_TOOLS_LAMBDAS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tools-lambdas",
)
if _TOOLS_LAMBDAS not in sys.path:
    sys.path.append(_TOOLS_LAMBDAS)


_IDENTITY = {
    "role": "developer",
    "user_name": "Lava Dev",
    "user_role": "Developer",
    "developer_id": "dev-6",
}


def _fresh_gateway_client(monkeypatch, url):
    """Reload config+gateway_client with ``MAHALO_GATEWAY_MCP_URL`` set to ``url``.

    ``settings`` is a frozen dataclass read at import, so the env var is applied
    by reloading the module. The caller restores the live modules afterward.
    """
    import importlib

    import agent.config as config

    monkeypatch.setenv("MAHALO_GATEWAY_MCP_URL", url)
    importlib.reload(config)
    import agent.gateway_client as gc

    importlib.reload(gc)
    return config, gc


def _restore():
    import importlib

    import agent.config as config
    import agent.gateway_client as gc
    import agent.strands_agent as sa

    importlib.reload(config)
    importlib.reload(gc)
    importlib.reload(sa)


def test_build_agent_gateway_mode_offline(monkeypatch):
    # No AWS creds / network: construction must still succeed.
    _config, gc = _fresh_gateway_client(monkeypatch, "https://example.invalid/mcp")
    try:
        mcp_client = gc._build_gateway_mcp_client()
        assert isinstance(mcp_client, MCPClient)
        # Constructed but NOT started (no background session running).
        assert mcp_client._is_session_active() is False
    finally:
        _restore()


def test_build_agent_gateway_returns_tuple(monkeypatch):
    # The live settings default mode is "direct"; pass tool_mode explicitly and
    # give the client a URL via the reloaded module so no network is touched.
    import agent.strands_agent as sa

    _config, gc = _fresh_gateway_client(monkeypatch, "https://example.invalid/mcp")
    try:
        import importlib

        importlib.reload(sa)
        agent, mcp_client = sa.build_agent(tool_mode="gateway", **_IDENTITY)
        assert isinstance(agent, Agent)
        assert isinstance(mcp_client, MCPClient)
    finally:
        _restore()


def test_build_agent_gateway_requires_url(monkeypatch):
    _config, gc = _fresh_gateway_client(monkeypatch, "")
    try:
        with pytest.raises(ValueError):
            gc._build_gateway_mcp_client()
    finally:
        _restore()


def test_default_mode_is_direct():
    import agent.config as config

    assert config.settings.tool_mode == "direct"


# --------------------------------------------------------------------------- #
# Exact arg-set parity against the live @tool signatures.
# --------------------------------------------------------------------------- #

def _agent_tool_funcs():
    from agent.tools.confluence_tools import CONFLUENCE_TOOLS
    from agent.tools.github_tools import GITHUB_TOOLS
    from agent.tools.github_write_tools import GITHUB_WRITE_TOOLS
    from agent.tools.jira_tools import JIRA_TOOLS
    from agent.tools.jira_write_tools import JIRA_WRITE_TOOLS
    from agent.tools.servicenow_tools import SERVICENOW_TOOLS
    from agent.tools.servicenow_write_tools import SERVICENOW_WRITE_TOOLS

    tools = [
        *JIRA_TOOLS,
        *JIRA_WRITE_TOOLS,
        *GITHUB_TOOLS,
        *GITHUB_WRITE_TOOLS,
        *CONFLUENCE_TOOLS,
        *SERVICENOW_TOOLS,
        *SERVICENOW_WRITE_TOOLS,
    ]
    funcs = {}
    for t in tools:
        original = getattr(t, "_tool_func", None) or getattr(t, "__wrapped__", None) or t
        funcs[t.tool_name] = original
    return funcs


def test_exact_arg_set_parity_with_at_tool_signatures():
    from common.tool_schemas import BY_NAME

    funcs = _agent_tool_funcs()
    assert set(funcs) == set(BY_NAME), "tool name sets differ between schema and @tools"

    for name, func in funcs.items():
        sig = inspect.signature(func)
        sig_args = {
            p
            for p, param in sig.parameters.items()
            if param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)
        }
        schema_args = set(BY_NAME[name]["input_schema"].get("properties", {}))
        assert sig_args == schema_args, (
            f"{name}: @tool args {sorted(sig_args)} != schema props {sorted(schema_args)}"
        )
