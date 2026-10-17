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


def test_build_agent_gateway_returns_build_result(monkeypatch):
    # The live settings default mode is "direct"; pass tool_mode explicitly and
    # give the client a URL via the reloaded module so no network is touched.
    import agent.strands_agent as sa

    _config, gc = _fresh_gateway_client(monkeypatch, "https://example.invalid/mcp")
    try:
        import importlib

        importlib.reload(sa)
        result = sa.build_agent(tool_mode="gateway", **_IDENTITY)
        assert isinstance(result.agent, Agent)
        assert isinstance(result.mcp_client, MCPClient)
        # Memory is off by default, so no session manager is constructed.
        assert result.session_manager is None
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
# Regression: the GATEWAY wiring must start the MCP client EXACTLY ONCE.
#
# Against strands 1.61.1 the double-start bug was: ``with mcp_client:`` started
# the client, then ``attach_gateway_tools`` -> ``process_tools`` -> provider
# ``load_tools()`` started it AGAIN and raised. This fake mimics the ToolProvider
# contract and raises on a SECOND ``start()``, so the old double-start ordering
# would fail here; the fixed single-start wiring attaches cleanly.
# --------------------------------------------------------------------------- #

from strands.tools.tool_provider import ToolProvider  # noqa: E402


class _FakeMCPClient(ToolProvider):
    """A ToolProvider that mirrors MCPClient's two-flag start semantics.

    * ``start()`` raises if the SESSION is already active (like
      ``MCPClient.start`` guarding on ``_is_session_active``).
    * ``load_tools()`` OWNS startup via a SEPARATE ``_tool_provider_started``
      flag (like the real client). So a client pre-started by an outer
      ``with`` (session active, but provider flag still False) makes
      ``load_tools()`` call ``start()`` again -> raises. This is exactly the
      double-start bug.
    """

    def __init__(self):
        self.start_calls = 0
        self._session_active = False
        self._tool_provider_started = False

    def start(self):
        if self._session_active:
            raise RuntimeError("the client session is currently running")
        self.start_calls += 1
        self._session_active = True
        return self

    # Context-manager surface, so an accidental ``with client:`` also starts it.
    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._session_active = False

    async def load_tools(self, **kwargs):
        if not self._tool_provider_started:
            self.start()
            self._tool_provider_started = True
        return []

    def add_consumer(self, consumer_id, **kwargs):
        pass

    def remove_consumer(self, consumer_id, **kwargs):
        pass


def test_attach_gateway_tools_starts_client_exactly_once():
    import agent.strands_agent as sa

    # A minimal agent-like object exposing the real ToolRegistry process path.
    from strands.tools.registry import ToolRegistry

    class _AgentStub:
        def __init__(self):
            self.tool_registry = ToolRegistry()

    agent = _AgentStub()
    fake = _FakeMCPClient()

    # The fixed wiring: attach_gateway_tools performs the single start. This must
    # NOT raise, and the client must have been started exactly once.
    sa.attach_gateway_tools(agent, fake)

    assert fake.start_calls == 1

    # Demonstrate the old double-start ordering would have raised: pre-starting
    # (as the removed ``with mcp_client:`` did) makes a provider load_tools()
    # start a second time.
    pre_started = _FakeMCPClient()
    pre_started.start()  # what ``with mcp_client:`` used to do
    agent2 = _AgentStub()
    with pytest.raises(ValueError):
        agent2.tool_registry.process_tools([pre_started])


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
