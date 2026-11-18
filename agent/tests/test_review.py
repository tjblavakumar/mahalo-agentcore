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


# --------------------------------------------------------------------------- #
# Per-file summaries (commit_files proposals)
# --------------------------------------------------------------------------- #

import json  # noqa: E402

from agent.review import split_file_summaries  # noqa: E402

_FILES = [
    {"path": "src/a.py", "content": "print('a')"},
    {"path": "src/b.py", "content": "print('b')"},
]


def _block(items):
    return "\n===FILE_SUMMARIES===\n" + json.dumps(items) + "\n===END_FILE_SUMMARIES==="


def test_summaries_good_output_and_findings_unchanged():
    raw = "Looks fine.\nno blocking issues found" + _block(
        [
            {"path": "src/a.py", "summary": "Prints the letter a."},
            {"path": "src/b.py", "summary": "Prints the letter b."},
        ]
    )
    reviewer = _FakeReviewer("us.amazon.nova-lite-v1:0", result=raw)
    out = review_code(reviewer, "ignored", files=_FILES)

    assert out.findings_text == "Looks fine.\nno blocking issues found"
    assert out.file_summaries == [
        {"path": "src/a.py", "summary": "Prints the letter a."},
        {"path": "src/b.py", "summary": "Prints the letter b."},
    ]
    assert "=== FILE: src/a.py ===" in reviewer.calls[0]


def test_summaries_malformed_output_is_omitted_not_fatal():
    for raw in (
        "ok" + "\n===FILE_SUMMARIES===\nnot json\n===END_FILE_SUMMARIES===",
        "ok\n===FILE_SUMMARIES===\n[{\"path\": \"src/a.py\"",  # cut off, no end
        "ok\n===FILE_SUMMARIES===\n{\"path\": \"src/a.py\"}\n===END_FILE_SUMMARIES===",
        "ok, no block at all",
    ):
        out = review_code(
            _FakeReviewer("m", result=raw), "x", files=_FILES
        )
        assert out.status == "ok"
        assert out.file_summaries is None
        assert "FILE_SUMMARIES" not in out.findings_text


def test_summaries_invented_path_dropped_and_dupes_ignored():
    raw = "ok" + _block(
        [
            {"path": "src/evil.py", "summary": "invented"},
            {"path": "src/a.py", "summary": "Real."},
            {"path": "src/a.py", "summary": "Duplicate."},
            {"path": "src/b.py", "summary": 42},
            "junk",
        ]
    )
    _, out = split_file_summaries(raw, ["src/a.py", "src/b.py"])
    assert out == [{"path": "src/a.py", "summary": "Real."}]


def test_summaries_trimmed_and_sanitized():
    long = "word " * 100
    raw = "ok" + _block(
        [
            {"path": "src/a.py", "summary": long},
            {"path": "src/b.py", "summary": "Line one\n\x00line\ttwo\u202e end"},
        ]
    )
    _, out = split_file_summaries(raw, ["src/a.py", "src/b.py"])
    assert len(out[0]["summary"]) <= 140
    assert out[0]["summary"].endswith("...")
    assert out[1]["summary"] == "Line one line two end"


def test_summaries_capped_at_20():
    paths = [f"f{i}.py" for i in range(30)]
    raw = "ok" + _block([{"path": p, "summary": "s"} for p in paths])
    _, out = split_file_summaries(raw, paths)
    assert len(out) == 20


def test_summaries_truncated_input_omits_cut_files_and_keeps_note():
    files = [
        {"path": "small.py", "content": "x = 1\n"},
        {"path": "big.py", "content": "y" * (40 * 1024)},
        {"path": "after.py", "content": "z = 3\n"},
    ]
    raw = "ok" + _block(
        [
            {"path": "small.py", "summary": "Small."},
            {"path": "big.py", "summary": "Invented for cut file."},
            {"path": "after.py", "summary": "Never shown."},
        ]
    )
    reviewer = _FakeReviewer("m", result=raw)
    out = review_code(reviewer, "ignored", files=files)

    assert out.file_summaries == [{"path": "small.py", "summary": "Small."}]
    assert "32 KB review limit" in out.findings_text
    assert "after.py ===" not in reviewer.calls[0].split("sentence saying")[-1]
    assert len(reviewer.calls[0].encode("utf-8")) < 33 * 1024 + 2000


def test_no_files_means_old_behaviour_and_no_summaries():
    raw = "ok" + _block([{"path": "src/a.py", "summary": "x"}])
    out = review_code(_FakeReviewer("m", result=raw), "code")
    assert out.file_summaries is None
    assert out.findings_text == raw  # untouched when no files were passed
