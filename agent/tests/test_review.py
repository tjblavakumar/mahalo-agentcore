"""Offline unit tests for the read-only review sub-agent (FEAT-001).

All offline — no AWS creds, no network. ``build_reviewer`` is exercised against a
REAL ``strands.Agent`` (the ``BedrockModel`` is lazy, so construction does not
touch AWS). ``review_code`` is exercised against a scriptable fake reviewer so no
live Bedrock call occurs.
"""

from __future__ import annotations

from strands.hooks import BeforeToolCallEvent

from agent.review import ReviewResult, build_reviewer, review_code


def _before_tool_call_callbacks(agent):
    """The BeforeToolCallEvent callbacks registered on the agent's hook registry."""
    return list(agent.hooks._registered_callbacks.get(BeforeToolCallEvent, []))


# --------------------------------------------------------------------------- #
# build_reviewer: empty tool set + no write hook (offline)
# --------------------------------------------------------------------------- #

def test_build_reviewer_has_no_tools_and_no_write_hook():
    reviewer = build_reviewer("us.amazon.nova-lite-v1:0")

    # tools=[] -> an empty tool registry.
    assert not reviewer.tool_registry.registry
    # No WriteApprovalHook -> no BeforeToolCallEvent callback (a write-gated agent
    # registers exactly one here).
    assert _before_tool_call_callbacks(reviewer) == []
    # The resolved model id is threaded into the lazy BedrockModel.
    assert reviewer.model.config.get("model_id") == "us.amazon.nova-lite-v1:0"


# --------------------------------------------------------------------------- #
# review_code: ok shape + error path
# --------------------------------------------------------------------------- #

class _FakeModel:
    def __init__(self, model_id):
        self.config = {"model_id": model_id}


class _FakeReviewer:
    def __init__(self, model_id, result=None, exc=None):
        self.model = _FakeModel(model_id)
        self._result = result
        self._exc = exc
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        if self._exc is not None:
            raise self._exc
        return self._result


def test_review_code_ok_shape():
    reviewer = _FakeReviewer(
        "us.amazon.nova-lite-v1:0", result="LGTM\nno blocking issues found"
    )
    out = review_code(reviewer, "def add(a, b):\n    return a + b\n", context="PAY-1")

    assert isinstance(out, ReviewResult)
    assert out.status == "ok"
    assert out.model_id == "us.amazon.nova-lite-v1:0"
    assert out.findings_text == "LGTM\nno blocking issues found"
    assert len(reviewer.calls) == 1


def test_review_code_size_bounds_input():
    reviewer = _FakeReviewer("us.amazon.nova-lite-v1:0", result="ok")
    review_code(reviewer, "x" * (64 * 1024))
    # The prompt carries at most the 32 KB bound of code (plus the fixed preamble).
    assert reviewer.calls[0].count("x") == 32 * 1024


def test_review_code_error_path_is_recoverable():
    reviewer = _FakeReviewer("us.amazon.nova-micro-v1:0", exc=RuntimeError("boom"))
    out = review_code(reviewer, "code")

    assert out.status == "error"
    assert out.model_id == "us.amazon.nova-micro-v1:0"
    assert "boom" in out.findings_text
