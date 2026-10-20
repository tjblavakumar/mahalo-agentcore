"""Offline unit tests for the shared HITL helpers (Task 6, item 1).

``agent/hitl.py`` is the single canonical home for the resume call and the
``[SYSTEM]`` breadcrumb, extracted verbatim from ``agent/chat.py``. These tests
assert the three chain breadcrumbs are emitted verbatim and that ``resume_once``
builds the correct ``interruptResponse`` block — no AWS, no network.
"""

from __future__ import annotations

from agent.hitl import emit_system_signal, resume_once


class _FakeAgent:
    """Records the single call payload and exposes a mutable ``messages`` list."""

    def __init__(self):
        self.messages: list = []
        self.calls: list = []

    def __call__(self, payload):
        self.calls.append(payload)
        return "RESULT"


def test_resume_once_builds_interrupt_response_block():
    agent = _FakeAgent()
    out = resume_once(agent, "itr-123", "APPROVE")
    assert out == "RESULT"
    assert agent.calls == [
        [{"interruptResponse": {"interruptId": "itr-123", "response": "APPROVE"}}]
    ]


def test_resume_once_forwards_reject_decision():
    agent = _FakeAgent()
    resume_once(agent, "itr-9", "REJECT")
    assert agent.calls[0][0]["interruptResponse"]["response"] == "REJECT"


def test_emit_system_signal_create_branch_template():
    agent = _FakeAgent()
    emit_system_signal(
        agent,
        {
            "action": "create_branch",
            "params": {"branch_name": "feature/PAY-109", "repo_id": "payment-service"},
        },
    )
    (msg,) = agent.messages
    text = msg["content"][0]["text"]
    assert msg["role"] == "assistant"
    assert "[SYSTEM] The user APPROVED and the branch 'feature/PAY-109'" in text
    assert "now exists in repo 'payment-service'" in text
    assert "propose github_commit_files" in text


def test_emit_system_signal_commit_files_template():
    agent = _FakeAgent()
    emit_system_signal(
        agent,
        {
            "action": "commit_files",
            "params": {"branch": "feature/PAY-109", "repo_id": "payment-service"},
        },
    )
    text = agent.messages[0]["content"][0]["text"]
    assert "files were committed to branch 'feature/PAY-109'" in text
    assert "propose github_open_pull_request from 'feature/PAY-109' into main" in text


def test_emit_system_signal_open_pull_request_template():
    agent = _FakeAgent()
    emit_system_signal(
        agent,
        {
            "action": "open_pull_request",
            "params": {"head": "feature/PAY-109", "repo_id": "payment-service"},
        },
    )
    text = agent.messages[0]["content"][0]["text"]
    assert "pull request was opened from 'feature/PAY-109' into 'main'" in text
    assert "The check-in flow is complete." in text


def test_emit_system_signal_generic_fallback():
    agent = _FakeAgent()
    emit_system_signal(
        agent, {"action": "create_story", "params": {"title": "X"}}
    )
    text = agent.messages[0]["content"][0]["text"]
    assert text == "[SYSTEM] The user approved and the 'create_story' action was executed."
