"""Agent-side IDENTITY-mode tests (Task 5), all offline.

The Identity slice brokers the Jira API key for ONE representative outbound path
(``jira_create_story``) at call time. Offline-safety: ``@requires_api_key`` is
applied only to a body-local ``_inner`` inside ``_fetch_jira_token``, so no
``IdentityClient`` / boto3 client is built at import or at ``build_agent`` — only
on a real enabled call. These tests assert that split with NO live AWS.
"""

from __future__ import annotations

import importlib

from strands import Agent

_IDENTITY = {
    "role": "developer",
    "user_name": "Lava Dev",
    "user_role": "Developer",
    "developer_id": "dev-6",
}


def _restore():
    # Clear the toggles BEFORE reloading so the live modules recapture the
    # default (off) settings. ``importlib.reload`` mutates the module in place,
    # so other test modules holding a reference to jira_write_tools see this
    # restored state too; the env must be clean at reload time (monkeypatch only
    # undoes setenv AFTER this finally-block runs).
    import os

    import agent.config as config
    import agent.strands_agent as sa
    import agent.tools.jira_write_tools as jwt

    os.environ.pop("MAHALO_IDENTITY_ENABLED", None)
    importlib.reload(config)
    importlib.reload(jwt)
    importlib.reload(sa)


# --------------------------------------------------------------------------- #
# (a) No IdentityClient / boto3 client is built at import or at build_agent.
# --------------------------------------------------------------------------- #

def test_no_identity_client_built_at_import_or_build(monkeypatch):
    # Patch IdentityClient.__init__ to a tripwire BEFORE importing the module.
    import bedrock_agentcore.identity.auth as auth

    def _boom(self, *a, **k):
        raise AssertionError("IdentityClient must NOT be constructed at import/build")

    monkeypatch.setattr(auth.IdentityClient, "__init__", _boom, raising=True)

    import agent.config as config

    monkeypatch.setenv("MAHALO_IDENTITY_ENABLED", "true")
    importlib.reload(config)
    import agent.tools.jira_write_tools as jwt

    importlib.reload(jwt)  # import must not build a client
    import agent.strands_agent as sa

    importlib.reload(sa)
    try:
        # build_agent (identity on) must not construct an IdentityClient either.
        result = sa.build_agent(identity=True, **_IDENTITY)
        assert isinstance(result.agent, Agent)
    finally:
        _restore()


# --------------------------------------------------------------------------- #
# (b) Identity OFF -> static token path (existing behavior unchanged).
# --------------------------------------------------------------------------- #

def test_identity_off_uses_static_token(monkeypatch):
    import agent.config as config

    monkeypatch.delenv("MAHALO_IDENTITY_ENABLED", raising=False)
    importlib.reload(config)
    import agent.tools.jira_write_tools as jwt

    importlib.reload(jwt)
    try:
        used = {}

        def _fake_make_request(url, token, *, endpoint, method, body):
            used["token"] = token
            return {"id": "PAY-999", "title": body["title"]}

        monkeypatch.setattr(jwt, "make_request", _fake_make_request)
        # If identity were (wrongly) consulted, this would be used instead.
        monkeypatch.setattr(
            jwt, "_fetch_jira_token", lambda: (_ for _ in ()).throw(AssertionError("should not fetch"))
        )

        out = jwt.jira_create_story._tool_func(
            project_id="PAY", title="T", description="D"
        )
        assert "PAY-999" in out
        assert used["token"] == jwt.settings.jira_token
    finally:
        _restore()


# --------------------------------------------------------------------------- #
# (c) Identity ON -> brokered token flows into make_request; key never logged.
# --------------------------------------------------------------------------- #

def test_identity_on_uses_brokered_token(monkeypatch):
    import agent.config as config

    monkeypatch.setenv("MAHALO_IDENTITY_ENABLED", "true")
    importlib.reload(config)
    import agent.tools.jira_write_tools as jwt

    importlib.reload(jwt)
    try:
        used = {}

        def _fake_make_request(url, token, *, endpoint, method, body):
            used["token"] = token
            return {"id": "PAY-777", "title": body["title"]}

        monkeypatch.setattr(jwt, "make_request", _fake_make_request)
        # Stub the brokered fetch (no AWS); returns a fake key value.
        monkeypatch.setattr(jwt, "_fetch_jira_token", lambda: "brokered-secret-key")

        out = jwt.jira_create_story._tool_func(
            project_id="PAY", title="T", description="D"
        )
        assert "PAY-777" in out
        assert used["token"] == "brokered-secret-key"
        # The key value is never surfaced in the tool output.
        assert "brokered-secret-key" not in out
    finally:
        _restore()


# --------------------------------------------------------------------------- #
# (d) A credential-fetch failure is caught; type-name only, no key value.
# --------------------------------------------------------------------------- #

def test_identity_fetch_failure_is_caught(monkeypatch):
    import agent.config as config

    monkeypatch.setenv("MAHALO_IDENTITY_ENABLED", "true")
    importlib.reload(config)
    import agent.tools.jira_write_tools as jwt

    importlib.reload(jwt)
    try:
        class _CredError(Exception):
            pass

        def _raise():
            raise _CredError("super-secret-key-leaked")

        monkeypatch.setattr(jwt, "_fetch_jira_token", _raise)
        # make_request must never run if the fetch failed.
        monkeypatch.setattr(
            jwt, "make_request",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")),
        )

        out = jwt.jira_create_story._tool_func(
            project_id="PAY", title="T", description="D"
        )
        assert "credential fetch failed" in out
        assert "_CredError" in out  # type-name only
        assert "super-secret-key-leaked" not in out  # never the message/value
    finally:
        _restore()

