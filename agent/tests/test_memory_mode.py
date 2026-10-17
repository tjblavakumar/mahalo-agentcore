"""Agent-side MEMORY-mode tests (Task 5), all offline.

Mirrors ``test_gateway_mode.py``'s reload style (``settings`` is a frozen
dataclass read at import, so env toggles are applied by ``importlib.reload``).

Construction-boundary note (Option 1): the installed
``AgentCoreMemorySessionManager.__init__`` performs a live ``ListEvents`` read,
so ``build_agent(memory=True)`` must NOT construct it — it assembles only an
offline ``MemorySessionSpec``. ``attach_memory`` is the single AWS touch: it
builds the real manager, registers its hooks, and calls ``initialize`` once.
These tests assert exactly that split with NO live AWS (the manager + its
registration are stubbed).
"""

from __future__ import annotations

import importlib

import pytest

from strands import Agent

_IDENTITY = {
    "role": "developer",
    "user_name": "Lava Dev",
    "user_role": "Developer",
    "developer_id": "dev-6",
}


def _reload_with(monkeypatch, **env):
    """Reload config + memory_client + strands_agent with the given env vars.

    Returns ``(config, strands_agent)``. The caller restores the live modules
    via ``_restore()`` in a ``finally``.
    """
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import agent.config as config

    importlib.reload(config)
    import agent.gateway_client as gc

    importlib.reload(gc)
    import agent.memory_client as mc

    importlib.reload(mc)
    import agent.strands_agent as sa

    importlib.reload(sa)
    return config, sa


def _restore():
    # Clear toggles BEFORE reloading so the live modules recapture defaults
    # (monkeypatch only undoes setenv AFTER the finally-block runs, and
    # importlib.reload mutates modules in place — see test_identity_mode._restore).
    import os

    import agent.config as config
    import agent.gateway_client as gc
    import agent.memory_client as mc
    import agent.strands_agent as sa

    for _var in (
        "MAHALO_MEMORY_ENABLED",
        "MAHALO_MEMORY_ID",
        "MAHALO_SESSION_ID",
        "MAHALO_GATEWAY_MCP_URL",
    ):
        os.environ.pop(_var, None)
    importlib.reload(config)
    importlib.reload(gc)
    importlib.reload(mc)
    importlib.reload(sa)


# --------------------------------------------------------------------------- #
# (a) build_agent(memory=True) is OFFLINE: builds a spec, no live manager.
# --------------------------------------------------------------------------- #

def test_build_agent_memory_offline_builds_spec_not_manager(monkeypatch):
    # No AWS creds / network; memory on with a valid id. build_agent must build a
    # plain MemorySessionSpec and construct NO live AgentCoreMemorySessionManager.
    _config, sa = _reload_with(
        monkeypatch,
        MAHALO_MEMORY_ENABLED="true",
        MAHALO_MEMORY_ID="mahalo-memory-abc123XYZ",
    )
    try:
        from agent.memory_client import MemorySessionSpec

        # A sentinel guards against the live manager being constructed at build.
        import agent.memory_client as mc

        def _boom(_spec):
            raise AssertionError("build_memory_session_manager must NOT run at build time")

        monkeypatch.setattr(mc, "build_memory_session_manager", _boom)
        # strands_agent imported the name directly; patch there too.
        monkeypatch.setattr(sa, "build_memory_session_manager", _boom)

        result = sa.build_agent(memory=True, session_id="s1", **_IDENTITY)

        assert isinstance(result.agent, Agent)
        assert isinstance(result.session_manager, MemorySessionSpec)
        assert result.session_manager.session_id == "s1"
        assert result.session_manager.actor_id == "dev-6"
        assert result.session_manager.memory_id == "mahalo-memory-abc123XYZ"
        # The agent itself has no session manager wired at construction.
        assert getattr(result.agent, "_session_manager", None) is None
    finally:
        _restore()


# --------------------------------------------------------------------------- #
# (b) attach_memory builds the manager, registers hooks via the registry
#     (register_hooks -> per-turn callbacks), calls initialize once, sets id.
# --------------------------------------------------------------------------- #

def test_attach_memory_registers_provider_and_initializes_once(monkeypatch):
    _config, sa = _reload_with(
        monkeypatch,
        MAHALO_MEMORY_ENABLED="true",
        MAHALO_MEMORY_ID="mahalo-memory-abc123XYZ",
    )
    try:
        import agent.memory_client as mc
        from agent.memory_client import MemorySessionSpec
        from strands.hooks import AfterInvocationEvent, MessageAddedEvent

        init_calls = []
        register_calls = []

        class _FakeManager:
            """Mimics AgentCoreMemorySessionManager's HookProvider contract."""

            def __init__(self, session_id):
                self.session_id = session_id

            def register_hooks(self, registry, **kwargs):
                register_calls.append(registry)
                # Install the per-turn persistence callbacks the real sync-mode
                # register_hooks installs, so we can assert they are present.
                registry.add_callback(MessageAddedEvent, lambda e: None)
                registry.add_callback(AfterInvocationEvent, lambda e: None)

            def initialize(self, agent, **kwargs):
                init_calls.append(agent)

        built_specs = []

        def _fake_build(spec):
            built_specs.append(spec)
            return _FakeManager(spec.session_id)

        monkeypatch.setattr(mc, "build_memory_session_manager", _fake_build)
        monkeypatch.setattr(sa, "build_memory_session_manager", _fake_build)

        # Build offline (memory off here to avoid building a spec twice), then
        # attach with an explicit spec.
        result = sa.build_agent(**_IDENTITY)
        spec = MemorySessionSpec(
            session_id="s1", actor_id="dev-6", region="us-east-1",
            memory_id="mahalo-memory-abc123XYZ",
        )
        manager = sa.attach_memory(result.agent, spec)

        # The manager was built from the spec exactly once.
        assert built_specs == [spec]
        # register_hooks ran (via agent.hooks.add_hook -> provider.register_hooks).
        assert len(register_calls) == 1
        # The per-turn persistence callbacks are present on the registry.
        assert result.agent.hooks.has_callbacks()
        assert result.agent.hooks.get_callbacks_for(
            MessageAddedEvent(agent=result.agent, message={"role": "user", "content": []})
        )
        # initialize called exactly once with the agent.
        assert init_calls == [result.agent]
        # session id matched to the manager.
        assert result.agent._session_id == "s1"
        assert manager.session_id == "s1"
    finally:
        _restore()


# --------------------------------------------------------------------------- #
# (c) build_agent(memory=True) with empty MAHALO_MEMORY_ID raises ValueError.
# --------------------------------------------------------------------------- #

def test_build_agent_memory_requires_memory_id(monkeypatch):
    _config, sa = _reload_with(
        monkeypatch, MAHALO_MEMORY_ENABLED="true", MAHALO_MEMORY_ID=""
    )
    try:
        with pytest.raises(ValueError):
            sa.build_agent(memory=True, session_id="s1", **_IDENTITY)
    finally:
        _restore()


# --------------------------------------------------------------------------- #
# (d) Memory OFF (default) builds no spec; DIRECT shape preserved.
# --------------------------------------------------------------------------- #

def test_build_agent_memory_off_builds_no_spec(monkeypatch):
    monkeypatch.delenv("MAHALO_MEMORY_ENABLED", raising=False)
    monkeypatch.delenv("MAHALO_MEMORY_ID", raising=False)
    import agent.config as config
    import agent.strands_agent as sa

    importlib.reload(config)
    importlib.reload(sa)
    try:
        result = sa.build_agent(**_IDENTITY)
        assert isinstance(result.agent, Agent)
        assert result.mcp_client is None
        assert result.session_manager is None
    finally:
        _restore()


# --------------------------------------------------------------------------- #
# (e) BuildResult shape across the four DIRECT/GATEWAY x memory off/on rows.
# --------------------------------------------------------------------------- #

def test_build_result_shapes_for_all_rows(monkeypatch):
    # NOTE: assert by class NAME (not identity) because importlib.reload creates a
    # fresh MemorySessionSpec class object that differs from any top-level import.

    # DIRECT, memory off (clean env first).
    monkeypatch.delenv("MAHALO_MEMORY_ENABLED", raising=False)
    monkeypatch.delenv("MAHALO_MEMORY_ID", raising=False)
    import agent.config as config
    import agent.strands_agent as sa

    importlib.reload(config)
    importlib.reload(sa)
    r = sa.build_agent(**_IDENTITY)
    assert r.mcp_client is None and r.session_manager is None

    # DIRECT, memory on + GATEWAY, memory off/on — reload with both toggles /
    # a gateway url so construction stays offline.
    _config, sa = _reload_with(
        monkeypatch,
        MAHALO_MEMORY_ENABLED="true",
        MAHALO_MEMORY_ID="mahalo-memory-abc123XYZ",
        MAHALO_GATEWAY_MCP_URL="https://example.invalid/mcp",
    )
    try:
        from strands.tools.mcp import MCPClient

        # DIRECT + memory on.
        r = sa.build_agent(memory=True, session_id="s1", **_IDENTITY)
        assert r.mcp_client is None
        assert type(r.session_manager).__name__ == "MemorySessionSpec"

        # GATEWAY + memory off.
        r = sa.build_agent(tool_mode="gateway", memory=False, **_IDENTITY)
        assert isinstance(r.mcp_client, MCPClient)
        assert r.session_manager is None

        # GATEWAY + memory on.
        r = sa.build_agent(
            tool_mode="gateway", memory=True, session_id="s2", **_IDENTITY
        )
        assert isinstance(r.mcp_client, MCPClient)
        assert type(r.session_manager).__name__ == "MemorySessionSpec"
        assert r.session_manager.session_id == "s2"
    finally:
        _restore()


# --------------------------------------------------------------------------- #
# (f) build_memory_session_manager assembles the STM config from a spec.
# --------------------------------------------------------------------------- #

def test_build_memory_session_manager_stm_config(monkeypatch):
    _config, sa = _reload_with(
        monkeypatch,
        MAHALO_MEMORY_ENABLED="true",
        MAHALO_MEMORY_ID="mahalo-memory-abc123XYZ",
    )
    try:
        import agent.memory_client as mc
        from agent.memory_client import MemorySessionSpec

        captured = {}

        class _FakeConfig:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        class _FakeManager:
            def __init__(self, config, region_name=None):
                captured["region_name"] = region_name
                captured["config"] = config

        # Patch the lazily-imported SDK symbols at their source modules.
        import bedrock_agentcore.memory.integrations.strands.config as cfgmod
        import bedrock_agentcore.memory.integrations.strands.session_manager as smmod

        monkeypatch.setattr(cfgmod, "AgentCoreMemoryConfig", _FakeConfig)
        monkeypatch.setattr(smmod, "AgentCoreMemorySessionManager", _FakeManager)

        spec = MemorySessionSpec(
            session_id="s9", actor_id="dev-6", region="us-west-2",
            memory_id="mahalo-memory-abc123XYZ",
        )
        mc.build_memory_session_manager(spec)

        assert captured["memory_id"] == "mahalo-memory-abc123XYZ"
        assert captured["session_id"] == "s9"
        assert captured["actor_id"] == "dev-6"
        assert captured["filter_restored_tool_context"] is True
        assert captured["batch_size"] == 1
        # STM only: no retrieval_config passed.
        assert "retrieval_config" not in captured
        assert captured["region_name"] == "us-west-2"
    finally:
        _restore()


# --------------------------------------------------------------------------- #
# (g) _resolve_session_id precedence + argv joins to one message / bare REPL.
# --------------------------------------------------------------------------- #

def test_resolve_session_id_flag_wins(monkeypatch):
    _config, _sa = _reload_with(monkeypatch, MAHALO_MEMORY_ENABLED="true")
    try:
        monkeypatch.setenv("MAHALO_SESSION_ID", "env-sess")
        import agent.chat as chat

        importlib.reload(chat)
        assert chat._resolve_session_id("  flag-sess  ") == "flag-sess"
    finally:
        _restore()


def test_resolve_session_id_env_then_uuid(monkeypatch):
    _config, _sa = _reload_with(monkeypatch, MAHALO_MEMORY_ENABLED="true")
    try:
        monkeypatch.setenv("MAHALO_SESSION_ID", "env-sess")
        import agent.chat as chat

        importlib.reload(chat)
        assert chat._resolve_session_id(None) == "env-sess"

        # No flag, no env, memory on -> a generated uuid (non-empty hex).
        monkeypatch.setenv("MAHALO_SESSION_ID", "")
        generated = chat._resolve_session_id(None)
        assert generated and len(generated) == 32
    finally:
        _restore()


def test_resolve_session_id_none_when_memory_off(monkeypatch):
    _config, _sa = _reload_with(monkeypatch, MAHALO_MEMORY_ENABLED="false")
    try:
        monkeypatch.delenv("MAHALO_SESSION_ID", raising=False)
        import agent.chat as chat

        importlib.reload(chat)
        assert chat._resolve_session_id(None) is None
    finally:
        _restore()


def test_main_argv_joins_message_and_bare_repl(monkeypatch):
    import agent.chat as chat

    importlib.reload(chat)

    calls = {}

    def _fake_single(message, *, session_id=None):
        calls["single"] = (message, session_id)

    def _fake_repl(*, session_id=None):
        calls["repl"] = session_id

    monkeypatch.setattr(chat, "_run_single", _fake_single)
    monkeypatch.setattr(chat, "_run_repl", _fake_repl)

    # argv with message words joins to the exact single-shot message.
    chat.main(["show", "my", "stories"])
    assert calls.get("single") == ("show my stories", None)

    # A single quoted-style arg is passed through unchanged.
    calls.clear()
    chat.main(["show my stories"])
    assert calls.get("single") == ("show my stories", None)

    # Bare argv -> REPL path.
    calls.clear()
    chat.main([])
    assert "repl" in calls
