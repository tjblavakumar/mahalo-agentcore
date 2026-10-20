"""Offline unit tests for the thin API (Task 6, items 7-10).

All offline — no AWS creds, no network. The boto3 ``bedrock-agentcore`` client is
NEVER constructed: ``invoke_runtime`` is monkeypatched (router tests) or its lazy
client accessor is stubbed (runtime_client test). Confirms the thin API imports
offline, forwards the §A.3 contract, maps replies/errors correctly, and imports
no ``agent``/``langchain`` code.

Import note (review finding 1): the thin API is packaged as a Lambda with asset
root ``api/`` and handler ``app.main.handler`` — the ``app`` package is the module
root at runtime, NOT ``api.app``. So intra-package imports are ``app.*`` and these
tests import ``app.*`` too, exercising the SAME import path the deployed Lambda
uses. ``conftest.py`` puts ``api/`` on ``sys.path`` so ``app`` resolves.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


_API_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# import-safety (items 7-10)
# --------------------------------------------------------------------------- #

def test_imports_offline():
    import app.auth  # noqa: F401
    import app.config  # noqa: F401
    import app.main  # noqa: F401
    import app.models  # noqa: F401
    import app.runtime_client as rc

    # The lazy boto3 client is NOT constructed at import time.
    assert rc._client is None


def test_imports_from_asset_root_only(monkeypatch):
    """Regression guard for finding 1: with ONLY the Lambda asset root (``api/``)
    on ``sys.path`` and no ``api`` package importable, ``app.main`` (the deployed
    handler module ``app.main.handler``) must still import. This reproduces the
    cold-start module resolution the offline synth gate cannot exercise.
    """
    # Drop any already-imported app.* / api.* modules so the import is fresh.
    for name in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    for name in [m for m in list(sys.modules) if m == "api" or m.startswith("api.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)

    # Only the asset root on sys.path — exactly what the Lambda runtime sees.
    monkeypatch.setattr(sys, "path", [str(_API_ROOT)] + [p for p in sys.path if p])

    import importlib

    main = importlib.import_module("app.main")
    assert hasattr(main, "handler")  # the Mangum Lambda entry point
    assert hasattr(main, "app")


def test_no_agent_or_langchain_imports():
    """The thin API must not pull the agent or any LangChain code into the edge."""
    import app.main  # noqa: F401

    bad = [m for m in sys.modules if m == "agent" or m.startswith("agent.")]
    bad += [m for m in sys.modules if "langchain" in m]
    assert not bad, f"thin API must not import: {bad}"


# --------------------------------------------------------------------------- #
# runtime_client (item 8)
# --------------------------------------------------------------------------- #

def test_invoke_runtime_round_trip(monkeypatch):
    import app.runtime_client as rc

    captured = {}

    class _FakeClient:
        def invoke_agent_runtime(self, **kwargs):
            captured.update(kwargs)
            return {"response": io.BytesIO(json.dumps({"status": "complete"}).encode())}

    import dataclasses
    monkeypatch.setattr(rc, "_get_client", lambda: _FakeClient())
    monkeypatch.setattr(
        rc, "settings",
        dataclasses.replace(
            rc.settings, runtime_arn="arn:aws:bedrock-agentcore:us-east-1:1:runtime/x"
        ),
    )

    out = rc.invoke_runtime(session_id="S1", body={"action": "chat", "prompt": "hi"})

    assert out == {"status": "complete"}
    assert captured["runtimeSessionId"] == "S1"
    assert captured["contentType"] == "application/json"
    assert captured["accept"] == "application/json"
    assert json.loads(captured["payload"]) == {"action": "chat", "prompt": "hi"}
    # Identity off: no runtimeUserId.
    assert "runtimeUserId" not in captured


def test_invoke_runtime_sets_user_id_when_provided(monkeypatch):
    import app.runtime_client as rc

    captured = {}

    class _FakeClient:
        def invoke_agent_runtime(self, **kwargs):
            captured.update(kwargs)
            return {"response": io.BytesIO(b"{}")}

    monkeypatch.setattr(rc, "_get_client", lambda: _FakeClient())
    rc.invoke_runtime(session_id="S1", body={}, runtime_user_id="dev-6")
    assert captured["runtimeUserId"] == "dev-6"


# --------------------------------------------------------------------------- #
# routers (item 9)
# --------------------------------------------------------------------------- #

def _client():
    import app.main as main

    return TestClient(main.app)


def test_chat_proposal_passthrough(monkeypatch):
    import app.routers.chat as chat

    def _fake_invoke(*, session_id, body, runtime_user_id=None):
        assert body["action"] == "chat"
        assert body["prompt"] == "make a branch"
        assert body["developer_id"] == "dev-6"
        return {
            "status": "pending_approval",
            "response": "",
            "proposal": {"action": "create_branch", "interrupt_id": "itr-1"},
            "session_id": session_id,
        }

    monkeypatch.setattr(chat, "invoke_runtime", _fake_invoke)
    resp = _client().post("/chat", json={"message": "make a branch", "session_id": "S1"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending_approval"
    assert data["proposal"]["interrupt_id"] == "itr-1"
    assert data["session_id"] == "S1"


def test_chat_complete_passthrough(monkeypatch):
    import app.routers.chat as chat

    monkeypatch.setattr(
        chat, "invoke_runtime",
        lambda *, session_id, body, runtime_user_id=None: {
            "status": "complete", "response": "hi there", "session_id": session_id,
        },
    )
    resp = _client().post("/chat", json={"message": "hello"})
    data = resp.json()
    assert data["status"] == "complete"
    assert data["response"] == "hi there"
    # A session id was generated (str(uuid4), 36 chars) and echoed.
    assert len(data["session_id"]) == 36


def test_chat_invoke_failure_is_502(monkeypatch):
    import app.routers.chat as chat
    from botocore.exceptions import ClientError

    def _boom(*, session_id, body, runtime_user_id=None):
        raise ClientError({"Error": {"Code": "ThrottlingException"}}, "InvokeAgentRuntime")

    monkeypatch.setattr(chat, "invoke_runtime", _boom)
    resp = _client().post("/chat", json={"message": "hello"})
    assert resp.status_code == 502


def test_chat_validation_error_is_422():
    resp = _client().post("/chat", json={"nope": 1})
    assert resp.status_code == 422


def test_approve_success_maps_to_action_result(monkeypatch):
    import app.routers.chat as chat

    def _fake_invoke(*, session_id, body, runtime_user_id=None):
        assert body["action"] == "approve"
        assert body["decision"] == "APPROVE"
        assert body["interrupt_id"] == "itr-1"
        # role is NOT forwarded on approve (design §B.3).
        assert "role" not in body
        return {"status": "complete", "response": "done", "session_id": session_id}

    monkeypatch.setattr(chat, "invoke_runtime", _fake_invoke)
    resp = _client().post(
        "/chat/approve",
        json={"session_id": "S1", "interrupt_id": "itr-1", "approved": True},
    )
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "done"
    assert data["session_id"] == "S1"


def test_approve_forwards_proposal_echo(monkeypatch):
    """The approve contract carries the proposal echo (finding 2) so the Runtime can
    emit the [SYSTEM] breadcrumb on a cold approve process. The thin API forwards
    ``req.proposal`` verbatim; when the client omits it the field is absent.
    """
    captured = {}

    import app.routers.chat as chat

    def _fake_invoke(*, session_id, body, runtime_user_id=None):
        captured.update(body)
        return {"status": "complete", "response": "done", "session_id": session_id}

    monkeypatch.setattr(chat, "invoke_runtime", _fake_invoke)
    proposal = {"action": "create_branch", "system": "github",
                "params": {"branch_name": "feat", "repo_id": "o/r"}}
    resp = _client().post(
        "/chat/approve",
        json={"session_id": "S1", "interrupt_id": "itr-1", "approved": True,
              "proposal": proposal},
    )
    assert resp.status_code == 200
    assert captured["proposal"] == proposal


def test_approve_reject_forwards_reject(monkeypatch):
    import app.routers.chat as chat

    captured = {}

    def _fake_invoke(*, session_id, body, runtime_user_id=None):
        captured.update(body)
        return {"status": "complete", "response": "rejected", "session_id": session_id}

    monkeypatch.setattr(chat, "invoke_runtime", _fake_invoke)
    resp = _client().post(
        "/chat/approve",
        json={"session_id": "S1", "interrupt_id": "itr-1", "approved": False},
    )
    assert captured["decision"] == "REJECT"
    assert resp.json()["success"] is True


def test_approve_runtime_error_maps_to_success_false(monkeypatch):
    import app.routers.chat as chat

    monkeypatch.setattr(
        chat, "invoke_runtime",
        lambda *, session_id, body, runtime_user_id=None: {
            "status": "error", "response": "",
            "error": {"type": "no_pending_interrupt", "message": "stale id"},
        },
    )
    resp = _client().post(
        "/chat/approve",
        json={"session_id": "S1", "interrupt_id": "stale", "approved": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["message"] == "stale id"


def test_approve_missing_interrupt_id_is_422():
    resp = _client().post("/chat/approve", json={"session_id": "S1", "approved": True})
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# zero-LangChain / no-agent guard over the source tree (item 10)
# --------------------------------------------------------------------------- #

def test_no_langchain_or_agent_in_api_source():
    api_root = Path(__file__).resolve().parents[1]
    for py in api_root.rglob("*.py"):
        if ".venv" in py.parts:
            continue
        for raw in py.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            # Only flag actual import statements, not prose in docstrings/comments.
            if line.startswith(("import ", "from ")):
                assert "langchain" not in line.lower(), f"langchain import in {py}: {line}"
                assert not line.startswith(("import agent", "from agent")), (
                    f"agent import in {py}: {line}"
                )
