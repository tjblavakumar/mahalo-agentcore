"""Offline unit tests for the Runtime harness + entrypoint (Task 6, items 3-6).

All offline — no AWS creds, no network. The real ``build_and_attach`` is stubbed
so the entrypoint's request/response shaping and validation are exercised without
a live agent/Memory/Bedrock touch. Also covers:

* the ``_build_bedrock_model`` profile-resolution fix (item 3) — exercises the
  REAL ``available_profiles`` path, never a forced ``Session`` raise;
* ``build_and_attach`` composition order (item 4);
* the import-time offline-safety of ``agent.runtime_app`` (item 5);
* the ``agent/requirements.txt`` harness-dep pins (item 6).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

class _FakeContext:
    def __init__(self, session_id=None):
        self.session_id = session_id


class _Interrupt:
    def __init__(self, interrupt_id, reason):
        self.id = interrupt_id
        self.reason = reason


class _AgentResult:
    def __init__(self, text="", stop_reason=None, interrupts=None):
        self._text = text
        self.stop_reason = stop_reason
        self.interrupts = interrupts or []

    def __str__(self):
        return self._text


class _InterruptState:
    """Minimal stand-in for strands ``_InterruptState`` (just the ``interrupts`` map)."""

    def __init__(self, interrupts=None):
        self.interrupts = interrupts or {}


class _FakeAgent:
    """Scriptable agent: returns queued results for each call; records messages.

    ``restored_interrupts`` seeds ``_interrupt_state.interrupts`` so the approve
    leg can derive the breadcrumb proposal from RESTORED session state (finding 2).
    """

    def __init__(self, results, restored_interrupts=None):
        self._results = list(results)
        self.messages = []
        self.calls = []
        if restored_interrupts is not None:
            self._interrupt_state = _InterruptState(restored_interrupts)

    def __call__(self, payload):
        self.calls.append(payload)
        return self._results.pop(0)


class _FakeAttached:
    def __init__(self, agent, mcp_client=None):
        self.agent = agent
        self.mcp_client = mcp_client


# --------------------------------------------------------------------------- #
# (item 5) import-time offline-safety + harness registration
# --------------------------------------------------------------------------- #

def test_import_and_app_registration_offline():
    import agent.runtime_app as ra
    from bedrock_agentcore.runtime import BedrockAgentCoreApp

    assert isinstance(ra.app, BedrockAgentCoreApp)
    # The entrypoint handler is registered under the harness "main" slot.
    assert ra.app.handlers.get("main") is ra.invoke


# --------------------------------------------------------------------------- #
# (item 5) chat leg
# --------------------------------------------------------------------------- #

def test_chat_complete(monkeypatch):
    import agent.runtime_app as ra

    agent = _FakeAgent([_AgentResult(text="hello world", stop_reason="end_turn")])
    captured = {}

    def _fake_build(session_id, developer_id="dev-6", role="developer", *, pending_write=False):
        captured.update(
            session_id=session_id, developer_id=developer_id, role=role,
            pending_write=pending_write,
        )
        return _FakeAttached(agent)

    monkeypatch.setattr(ra, "build_and_attach", _fake_build)

    out = ra.invoke({"action": "chat", "prompt": "hi"}, _FakeContext("S1"))

    assert out["status"] == "complete"
    assert out["response"] == "hello world"
    assert out["proposal"] is None
    assert out["session_id"] == "S1"
    # chat leg builds with pending_write=False and the request role.
    assert captured == {
        "session_id": "S1", "developer_id": "dev-6", "role": "developer",
        "pending_write": False,
    }


def test_chat_pending_approval(monkeypatch):
    import agent.runtime_app as ra

    reason = {"action": "create_branch", "system": "github", "params": {},
              "description": "Create branch"}
    agent = _FakeAgent(
        [_AgentResult(stop_reason="interrupt", interrupts=[_Interrupt("itr-1", reason)])]
    )
    monkeypatch.setattr(ra, "build_and_attach", lambda *a, **k: _FakeAttached(agent))

    out = ra.invoke({"action": "chat", "prompt": "make a branch"}, _FakeContext("S1"))

    assert out["status"] == "pending_approval"
    assert out["response"] == ""
    assert out["proposal"] == {**reason, "interrupt_id": "itr-1"}
    assert out["session_id"] == "S1"


def test_chat_respects_developer_id_and_role(monkeypatch):
    import agent.runtime_app as ra

    agent = _FakeAgent([_AgentResult(text="ok", stop_reason="end_turn")])
    captured = {}

    def _fake_build(session_id, developer_id="dev-6", role="developer", *, pending_write=False):
        captured.update(developer_id=developer_id, role=role)
        return _FakeAttached(agent)

    monkeypatch.setattr(ra, "build_and_attach", _fake_build)
    ra.invoke(
        {"action": "chat", "prompt": "x", "developer_id": "dev-3", "role": "executive"},
        _FakeContext("S1"),
    )
    assert captured == {"developer_id": "dev-3", "role": "executive"}


def test_chat_malformed_developer_id_and_role_fall_back(monkeypatch):
    import agent.runtime_app as ra

    agent = _FakeAgent([_AgentResult(text="ok", stop_reason="end_turn")])
    captured = {}

    def _fake_build(session_id, developer_id="dev-6", role="developer", *, pending_write=False):
        captured.update(developer_id=developer_id, role=role)
        return _FakeAttached(agent)

    monkeypatch.setattr(ra, "build_and_attach", _fake_build)
    ra.invoke(
        {"action": "chat", "prompt": "x", "developer_id": "bogus", "role": "wizard"},
        _FakeContext("S1"),
    )
    assert captured == {"developer_id": "dev-6", "role": "developer"}


def test_chat_stops_gateway_client_in_finally(monkeypatch):
    import agent.runtime_app as ra

    stops = []

    class _MCP:
        def stop(self, *a):
            stops.append(a)

    agent = _FakeAgent([_AgentResult(text="ok", stop_reason="end_turn")])
    monkeypatch.setattr(
        ra, "build_and_attach", lambda *a, **k: _FakeAttached(agent, _MCP())
    )
    ra.invoke({"action": "chat", "prompt": "x"}, _FakeContext("S1"))
    assert stops == [(None, None, None)]


# --------------------------------------------------------------------------- #
# (item 5) approve leg
# --------------------------------------------------------------------------- #

def test_approve_emits_breadcrumb_from_restored_state(monkeypatch):
    """Finding 2: the breadcrumb is derived from RESTORED session state, so the
    chain is preserved WITHOUT the client echoing the proposal back. The payload
    carries NO 'proposal' field here — restored _interrupt_state supplies it."""
    import agent.runtime_app as ra

    restored = {
        "itr-1": _Interrupt(
            "itr-1",
            {"action": "create_branch",
             "params": {"branch_name": "feat/x", "repo_id": "svc"}},
        )
    }
    agent = _FakeAgent(
        [_AgentResult(text="done", stop_reason="end_turn")],
        restored_interrupts=restored,
    )
    captured = {}

    def _fake_build(session_id, developer_id="dev-6", role="developer", *, pending_write=False):
        captured.update(pending_write=pending_write, role=role)
        return _FakeAttached(agent)

    monkeypatch.setattr(ra, "build_and_attach", _fake_build)

    # NOTE: no "proposal" in the payload — the client did not echo it.
    out = ra.invoke(
        {"action": "approve", "decision": "APPROVE", "interrupt_id": "itr-1"},
        _FakeContext("S1"),
    )

    assert out["status"] == "complete"
    assert out["response"] == "done"
    # approve leg builds pending_write=True and lets role default.
    assert captured == {"pending_write": True, "role": "developer"}
    # the resume used the correct interruptResponse block.
    assert agent.calls[0] == [
        {"interruptResponse": {"interruptId": "itr-1", "response": "APPROVE"}}
    ]
    # breadcrumb appended (create_branch template) despite no client echo.
    text = agent.messages[0]["content"][0]["text"]
    assert "[SYSTEM] The user APPROVED and the branch 'feat/x'" in text


def test_approve_emits_breadcrumb_from_client_echo_fallback(monkeypatch):
    """Belt-and-braces: when restored state has no matching interrupt (e.g. VM
    recycled), a client-echoed proposal is still accepted as a fallback."""
    import agent.runtime_app as ra

    # No restored_interrupts -> _restored_proposal returns None -> echo fallback.
    agent = _FakeAgent([_AgentResult(text="done", stop_reason="end_turn")])
    monkeypatch.setattr(ra, "build_and_attach", lambda *a, **k: _FakeAttached(agent))

    proposal = {"action": "create_branch",
                "params": {"branch_name": "feat/x", "repo_id": "svc"}}
    out = ra.invoke(
        {"action": "approve", "decision": "APPROVE", "interrupt_id": "itr-1",
         "proposal": proposal},
        _FakeContext("S1"),
    )

    assert out["status"] == "complete"
    text = agent.messages[0]["content"][0]["text"]
    assert "[SYSTEM] The user APPROVED and the branch 'feat/x'" in text


def test_approve_reject_emits_no_breadcrumb(monkeypatch):
    import agent.runtime_app as ra

    agent = _FakeAgent([_AgentResult(text="rejected", stop_reason="end_turn")])
    monkeypatch.setattr(ra, "build_and_attach", lambda *a, **k: _FakeAttached(agent))

    out = ra.invoke(
        {"action": "approve", "decision": "REJECT", "interrupt_id": "itr-1",
         "proposal": {"action": "create_branch", "params": {}}},
        _FakeContext("S1"),
    )
    assert out["status"] == "complete"
    assert agent.messages == []  # nothing emitted on reject


def test_approve_unknown_interrupt_id(monkeypatch):
    import agent.runtime_app as ra

    class _RaisingAgent:
        messages = []

        def __call__(self, payload):
            raise KeyError("no such interrupt")

    monkeypatch.setattr(
        ra, "build_and_attach", lambda *a, **k: _FakeAttached(_RaisingAgent())
    )
    out = ra.invoke(
        {"action": "approve", "decision": "APPROVE", "interrupt_id": "stale"},
        _FakeContext("S1"),
    )
    assert out["status"] == "error"
    assert out["error"]["type"] == "no_pending_interrupt"


def test_approve_chained_reproposal(monkeypatch):
    import agent.runtime_app as ra

    reason = {"action": "commit_files", "system": "github", "params": {},
              "description": "Commit"}
    agent = _FakeAgent(
        [_AgentResult(stop_reason="interrupt", interrupts=[_Interrupt("itr-2", reason)])]
    )
    monkeypatch.setattr(ra, "build_and_attach", lambda *a, **k: _FakeAttached(agent))
    out = ra.invoke(
        {"action": "approve", "decision": "APPROVE", "interrupt_id": "itr-1"},
        _FakeContext("S1"),
    )
    assert out["status"] == "pending_approval"
    assert out["proposal"]["interrupt_id"] == "itr-2"


# --------------------------------------------------------------------------- #
# (item 5) validation + session id
# --------------------------------------------------------------------------- #

def test_bad_action():
    import agent.runtime_app as ra

    out = ra.invoke({"action": "delete"}, _FakeContext("S1"))
    assert out["status"] == "error" and out["error"]["type"] == "bad_action"


def test_missing_action():
    import agent.runtime_app as ra

    out = ra.invoke({"prompt": "x"}, _FakeContext("S1"))
    assert out["error"]["type"] == "bad_action"


def test_chat_empty_prompt():
    import agent.runtime_app as ra

    out = ra.invoke({"action": "chat", "prompt": "   "}, _FakeContext("S1"))
    assert out["error"]["type"] == "bad_prompt"


def test_chat_oversized_prompt():
    import agent.runtime_app as ra

    big = "a" * (32 * 1024 + 1)
    out = ra.invoke({"action": "chat", "prompt": big}, _FakeContext("S1"))
    assert out["error"]["type"] == "prompt_too_large"


def test_approve_bad_decision():
    import agent.runtime_app as ra

    out = ra.invoke(
        {"action": "approve", "decision": "MAYBE", "interrupt_id": "x"},
        _FakeContext("S1"),
    )
    assert out["error"]["type"] == "bad_decision"


def test_approve_missing_interrupt_id():
    import agent.runtime_app as ra

    out = ra.invoke(
        {"action": "approve", "decision": "APPROVE"}, _FakeContext("S1")
    )
    assert out["error"]["type"] == "bad_interrupt_id"


def test_non_dict_payload():
    import agent.runtime_app as ra

    out = ra.invoke(["not", "a", "dict"], _FakeContext("S1"))
    assert out["error"]["type"] == "bad_request"


def test_missing_session_header_generates_and_echoes_id(monkeypatch):
    import agent.runtime_app as ra

    agent = _FakeAgent([_AgentResult(text="ok", stop_reason="end_turn")])
    monkeypatch.setattr(ra, "build_and_attach", lambda *a, **k: _FakeAttached(agent))

    out = ra.invoke({"action": "chat", "prompt": "x"}, _FakeContext(None))
    assert out["status"] == "complete"
    # A generated uuid4 hex (32 chars) is echoed back.
    assert out["session_id"] and len(out["session_id"]) == 32


# --------------------------------------------------------------------------- #
# (item 4) build_and_attach composition
# --------------------------------------------------------------------------- #

def test_build_and_attach_direct_order(monkeypatch):
    import agent.runtime_session as rs

    calls = []

    class _BR:
        def __init__(self):
            self.agent = object()
            self.mcp_client = None
            self.session_manager = object()

    def _fake_build_agent(**kwargs):
        calls.append(("build_agent", kwargs))
        return _BR()

    def _fake_attach_memory(agent, spec):
        calls.append(("attach_memory", agent, spec))

    monkeypatch.setattr(rs, "build_agent", _fake_build_agent)
    monkeypatch.setattr(rs, "attach_memory", _fake_attach_memory)
    import dataclasses
    monkeypatch.setattr(rs, "settings", dataclasses.replace(rs.settings, tool_mode="direct"))

    out = rs.build_and_attach("S1", developer_id="dev-6", pending_write=True)

    assert out.mcp_client is None
    assert [c[0] for c in calls] == ["build_agent", "attach_memory"]
    assert calls[0][1]["pending_write"] is True
    assert calls[0][1]["memory"] is True
    assert calls[0][1]["session_id"] == "S1"


def test_build_and_attach_gateway_order(monkeypatch):
    import agent.runtime_session as rs

    calls = []
    mcp = object()

    class _BR:
        def __init__(self):
            self.agent = object()
            self.mcp_client = mcp
            self.session_manager = object()

    monkeypatch.setattr(rs, "build_agent", lambda **k: _BR())
    monkeypatch.setattr(
        rs, "attach_gateway_tools", lambda a, m: calls.append(("gw", a, m))
    )
    monkeypatch.setattr(rs, "attach_memory", lambda a, s: calls.append(("mem", a, s)))
    import dataclasses
    monkeypatch.setattr(rs, "settings", dataclasses.replace(rs.settings, tool_mode="gateway"))

    out = rs.build_and_attach("S2")

    assert out.mcp_client is mcp
    assert [c[0] for c in calls] == ["gw", "mem"]  # gateway attached before memory


# --------------------------------------------------------------------------- #
# (item 3) _build_bedrock_model profile resolution — exercises the REAL path
# --------------------------------------------------------------------------- #

def test_build_bedrock_model_omits_profile_when_absent(monkeypatch):
    """Container case: no 'lava' in available_profiles => no profile_name passed."""
    import agent.strands_agent as sa

    class _FakeBotocoreSession:
        available_profiles = ["default", "other"]

    monkeypatch.setattr(sa.botocore.session, "Session", _FakeBotocoreSession)

    seen = {}

    def _spy_session(**kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(sa.boto3, "Session", _spy_session)
    monkeypatch.setattr(sa, "BedrockModel", lambda **k: ("model", k))

    sa._build_bedrock_model("us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert "profile_name" not in seen
    assert "region_name" in seen


def test_build_bedrock_model_passes_profile_when_present(monkeypatch):
    """Local case: 'lava' present => profile_name='lava' is passed (CLI unchanged)."""
    import agent.strands_agent as sa

    class _FakeBotocoreSession:
        available_profiles = ["default", "lava"]

    monkeypatch.setattr(sa.botocore.session, "Session", _FakeBotocoreSession)
    import dataclasses
    monkeypatch.setattr(sa, "settings", dataclasses.replace(sa.settings, aws_profile="lava"))

    seen = {}

    def _spy_session(**kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(sa.boto3, "Session", _spy_session)
    monkeypatch.setattr(sa, "BedrockModel", lambda **k: ("model", k))

    sa._build_bedrock_model("us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert seen.get("profile_name") == "lava"


# --------------------------------------------------------------------------- #
# (item 6) container reproducibility — requirements pins
# --------------------------------------------------------------------------- #

def test_agent_requirements_pin_harness_deps():
    req = Path(__file__).resolve().parents[1] / "requirements.txt"
    text = req.read_text(encoding="utf-8")
    assert re.search(r"^bedrock-agentcore==1\.24\.1\s*$", text, re.MULTILINE)
    assert re.search(r"^strands-agents==1\.61\.1\s*$", text, re.MULTILINE)


# --------------------------------------------------------------------------- #
# (FEAT-001) multi-LLM review seam on _handle_chat
# --------------------------------------------------------------------------- #

from agent import model_config as _mc  # noqa: E402


class _FakeReviewResult:
    def __init__(self, model_id, findings_text="no blocking issues found", status="ok"):
        self.model_id = model_id
        self.findings_text = findings_text
        self.status = status


def _patch_review(monkeypatch):
    """Stub build_reviewer/review_code so no live Bedrock call occurs; record calls."""
    import agent.runtime_app as ra

    seen = {"codes": []}

    def _fake_build_reviewer(model_id):
        seen["reviewer_model_id"] = model_id
        return object()

    def _fake_review_code(reviewer, code, context=""):
        seen["codes"].append(code)
        return _FakeReviewResult(seen.get("reviewer_model_id", ""))

    monkeypatch.setattr(ra, "build_reviewer", _fake_build_reviewer)
    monkeypatch.setattr(ra, "review_code", _fake_review_code)
    return seen


def test_chat_complete_with_fenced_block_adds_review(monkeypatch):
    import agent.runtime_app as ra

    seen = _patch_review(monkeypatch)
    response = "Here you go:\n```python\ndef f():\n    return 1\n```\nDone."
    agent = _FakeAgent([_AgentResult(text=response, stop_reason="end_turn")])
    monkeypatch.setattr(ra, "build_and_attach", lambda *a, **k: _FakeAttached(agent))

    out = ra.invoke({"action": "chat", "prompt": "write code"}, _FakeContext("S1"))

    assert out["status"] == "complete"
    # stages: generate (code-gen id) + review (resolved default review id), distinct.
    stage_ids = [s["model_id"] for s in out["stages"]]
    assert stage_ids == [_mc.CODE_GEN_MODEL_ID, _mc.DEFAULT_REVIEW_MODEL_ID]
    assert stage_ids[0] != stage_ids[1]
    assert out["stages"][0]["stage"] == "generate"
    assert out["stages"][1]["stage"] == "review"
    # a review object is attached.
    assert out["review"]["model_id"] == _mc.DEFAULT_REVIEW_MODEL_ID
    assert out["review"]["status"] == "ok"
    # the fenced code (not the prose) was handed to the reviewer.
    assert "def f():" in seen["codes"][0]
    assert "Here you go" not in seen["codes"][0]


def test_chat_complete_no_fenced_block_has_no_review(monkeypatch):
    import agent.runtime_app as ra

    _patch_review(monkeypatch)
    agent = _FakeAgent([_AgentResult(text="just prose, no code", stop_reason="end_turn")])
    monkeypatch.setattr(ra, "build_and_attach", lambda *a, **k: _FakeAttached(agent))

    out = ra.invoke({"action": "chat", "prompt": "hi"}, _FakeContext("S1"))

    assert out["status"] == "complete"
    assert out["response"] == "just prose, no code"
    assert [s["stage"] for s in out["stages"]] == ["generate"]
    assert "review" not in out


def test_chat_interrupt_commit_files_reviews_params_files(monkeypatch):
    import agent.runtime_app as ra

    seen = _patch_review(monkeypatch)
    reason = {
        "action": "commit_files",
        "system": "github",
        "params": {
            "repo_id": "payment-service",
            "branch": "feat/x",
            "files": [
                {"path": "a.py", "content": "print('a')"},
                {"path": "b.py", "content": "print('b')"},
            ],
        },
        "description": "Commit files to branch 'feat/x' in payment-service",
    }
    expected_proposal = {**reason, "interrupt_id": "itr-9"}
    agent = _FakeAgent(
        [_AgentResult(stop_reason="interrupt", interrupts=[_Interrupt("itr-9", reason)])]
    )
    monkeypatch.setattr(ra, "build_and_attach", lambda *a, **k: _FakeAttached(agent))

    out = ra.invoke({"action": "chat", "prompt": "commit it"}, _FakeContext("S1"))

    # status + proposal unchanged (byte-for-byte).
    assert out["status"] == "pending_approval"
    assert out["proposal"] == expected_proposal
    # review stage present, built from params.files.
    assert [s["stage"] for s in out["stages"]] == ["generate", "review"]
    assert out["stages"][1]["model_id"] == _mc.DEFAULT_REVIEW_MODEL_ID
    assert out["review"]["status"] == "ok"
    assert "print('a')" in seen["codes"][0]
    assert "print('b')" in seen["codes"][0]


def _load_api_chat_response():
    """Import the thin API's ``ChatResponse`` model to guard the cross-layer contract.

    The api package is a pure-pydantic sibling (no agent-only deps), so its
    ``app.models`` imports cleanly under the agent venv. We add ``api/`` to
    sys.path here (there is no shared conftest) so this agent-side test can feed a
    REAL ``_handle_chat`` payload through the model the frontend actually receives.
    """
    import sys

    api_dir = Path(__file__).resolve().parents[2] / "api"
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from app.models import ChatResponse  # noqa: E402

    return ChatResponse


def test_handle_chat_payload_roundtrips_through_api_chat_response(monkeypatch):
    """Contract: a real _handle_chat payload keeps its labels through ChatResponse.

    Guards the FR-15/AC-6 trust line end to end: the agent emits ``model_label``
    on every stage and on the review object, so the API's ChatResponse (whose
    StageInfo/ReviewInfo fields are optional-with-defaults) does NOT silently drop
    them to None. A per-layer fixture can't catch a key-name drift here — this
    feeds the actual agent output into the actual API model.
    """
    import agent.runtime_app as ra

    _patch_review(monkeypatch)
    response = "Here you go:\n```python\ndef f():\n    return 1\n```\nDone."
    agent = _FakeAgent([_AgentResult(text=response, stop_reason="end_turn")])
    monkeypatch.setattr(ra, "build_and_attach", lambda *a, **k: _FakeAttached(agent))

    out = ra.invoke({"action": "chat", "prompt": "write code"}, _FakeContext("S1"))

    ChatResponse = _load_api_chat_response()
    projected = ChatResponse(**out)

    # Both stages carry a non-null model_label through the API model.
    assert [s.stage for s in projected.stages] == ["generate", "review"]
    assert projected.stages[0].model_label == _mc.CODE_GEN_MODEL_LABEL
    assert projected.stages[0].status == "ok"
    assert projected.stages[1].model_label == _mc.label(_mc.DEFAULT_REVIEW_MODEL_ID)
    # The review summary's model_label survives projection (trust line target).
    assert projected.review is not None
    assert projected.review.model_label == _mc.label(_mc.DEFAULT_REVIEW_MODEL_ID)


def test_chat_interrupt_create_branch_has_no_review(monkeypatch):
    import agent.runtime_app as ra

    _patch_review(monkeypatch)
    reason = {"action": "create_branch", "system": "github", "params": {},
              "description": "Create branch"}
    agent = _FakeAgent(
        [_AgentResult(stop_reason="interrupt", interrupts=[_Interrupt("itr-1", reason)])]
    )
    monkeypatch.setattr(ra, "build_and_attach", lambda *a, **k: _FakeAttached(agent))

    out = ra.invoke({"action": "chat", "prompt": "make a branch"}, _FakeContext("S1"))

    assert out["status"] == "pending_approval"
    assert out["proposal"] == {**reason, "interrupt_id": "itr-1"}
    assert [s["stage"] for s in out["stages"]] == ["generate"]
    assert "review" not in out


def test_approve_leg_output_unchanged_by_seam(monkeypatch):
    """The approve leg attaches no stages/review keys (seam is chat-only)."""
    import agent.runtime_app as ra

    _patch_review(monkeypatch)
    agent = _FakeAgent([_AgentResult(text="done", stop_reason="end_turn")])
    monkeypatch.setattr(ra, "build_and_attach", lambda *a, **k: _FakeAttached(agent))

    proposal = {"action": "create_branch",
                "params": {"branch_name": "feat/x", "repo_id": "svc"}}
    out = ra.invoke(
        {"action": "approve", "decision": "APPROVE", "interrupt_id": "itr-1",
         "proposal": proposal},
        _FakeContext("S1"),
    )

    assert out["status"] == "complete"
    assert out["response"] == "done"
    assert "stages" not in out
    assert "review" not in out


def test_resolve_review_model_passthrough_and_fallback():
    for allowed in _mc.REVIEW_ALLOW_LIST:
        assert _mc.resolve_review_model(allowed) == (allowed, False)
    assert _mc.resolve_review_model("off-list-id") == (_mc.DEFAULT_REVIEW_MODEL_ID, True)
    assert _mc.resolve_review_model(None) == (_mc.DEFAULT_REVIEW_MODEL_ID, True)
