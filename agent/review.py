"""Read-only independent code-review sub-agent (FEAT-001).

The reviewer is a SECOND ``strands.Agent`` built per invocation — a deterministic
pipeline stage, NOT a model-chosen tool. It is constructed with ``tools=[]`` and
NO ``WriteApprovalHook``: it can never call a write tool and so never reaches the
HITL interrupt path (FR-9). The main agent and its write gate stay byte-for-byte
unchanged.

Offline-safe by construction (NFR-4): building the reviewer goes through the
factored ``_build_bedrock_model(model_id)`` whose ``BedrockModel`` construction is
lazy, so ``build_reviewer(...)`` succeeds with no AWS credentials. The single AWS
touch is the actual ``review_code`` reviewer call.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass

from strands import Agent

from agent.strands_agent import _build_bedrock_model

# Reviewer output is bounded before the call so a large code-gen turn cannot blow
# past the model's context or the read timeout.
_CODE_MAX_BYTES = 32 * 1024

# Per-file summaries (commit_files proposals only). The reviewer appends a
# delimited JSON block after its normal findings. It is parsed defensively and
# stripped from ``findings_text`` so the findings keep their old shape.
_SUMMARY_START = "===FILE_SUMMARIES==="
_SUMMARY_END = "===END_FILE_SUMMARIES==="
_SUMMARY_BLOCK_RE = re.compile(
    re.escape(_SUMMARY_START) + r"(.*?)(?:" + re.escape(_SUMMARY_END) + r"|\Z)",
    re.DOTALL,
)
_SUMMARY_MAX_CHARS = 140
_SUMMARY_MAX_FILES = 20
_TRUNCATION_NOTE = (
    "\n\nNote: the files were larger than the 32 KB review limit; some files "
    "were not fully reviewed."
)

REVIEWER_SYSTEM_PROMPT = (
    "You are an independent senior software reviewer. You are given code that "
    "another engineer generated. Do NOT rewrite the code. Review it for "
    "correctness, security, and maintainability. Respond with a single "
    "assessment line, then either a short bulleted list of specific concerns or "
    "the exact text 'no blocking issues found' when there is nothing material to "
    "flag."
)

_FILE_SUMMARY_INSTRUCTIONS = (
    "The code below is given as files, each introduced by a line "
    "'=== FILE: <path> ==='. After your assessment, append exactly one block in "
    "this form:\n"
    + _SUMMARY_START
    + '\n[{"path": "<exact path as given>", "summary": "<one short plain-language '
    'sentence saying what the file does>"}]\n'
    + _SUMMARY_END
    + "\nInclude one entry per file shown. A summary describes the file's purpose "
    "only: no code, no praise, no review comments.\n\n"
)


@dataclass
class ReviewResult:
    """The outcome of one review stage."""

    model_id: str
    findings_text: str
    status: str
    # Sanitized ``[{path, summary}]``; None when absent/unparseable/not requested.
    file_summaries: list | None = None


def build_reviewer(model_id: str) -> Agent:
    """Build the read-only review sub-agent for ``model_id``.

    Built like the main agent but with ``tools=[]`` and NO ``WriteApprovalHook``,
    so it has an empty tool set and never gates a write. Construction is
    offline-safe (the ``BedrockModel`` is lazy).
    """
    model = _build_bedrock_model(model_id)
    return Agent(
        model=model,
        tools=[],
        system_prompt=REVIEWER_SYSTEM_PROMPT,
    )


def _clean_summary(value) -> str:
    """Untrusted model text -> single-line plain text capped at 140 chars."""
    if not isinstance(value, str):
        return ""
    chars = [
        " " if unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") else c
        for c in value
    ]
    text = " ".join("".join(chars).split())
    if len(text) > _SUMMARY_MAX_CHARS:
        text = text[: _SUMMARY_MAX_CHARS - 3].rstrip() + "..."
    return text


def split_file_summaries(raw: str, allowed_paths) -> tuple[str, list | None]:
    """Split reviewer output into (findings without the block, sanitized summaries).

    Never raises. Only entries whose ``path`` exactly matches one of
    ``allowed_paths`` are kept (first one wins), capped at 20 entries. Returns
    ``None`` for the summaries when none survive.
    """
    match = _SUMMARY_BLOCK_RE.search(raw)
    if not match:
        return raw, None
    findings = (raw[: match.start()] + raw[match.end():]).strip()
    try:
        allowed = set(allowed_paths)
        data = json.loads(match.group(1).strip())
        if not isinstance(data, list):
            return findings, None
        out, seen = [], set()
        for item in data:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if not isinstance(path, str) or path not in allowed or path in seen:
                continue
            summary = _clean_summary(item.get("summary"))
            if not summary:
                continue
            seen.add(path)
            out.append({"path": path, "summary": summary})
            if len(out) >= _SUMMARY_MAX_FILES:
                break
        return findings, out or None
    except Exception:  # noqa: BLE001 - summaries are optional; never fail the review
        return findings, None


def _pack_files(files: list) -> tuple[str, list[str], bool]:
    """Pack ``{path, content}`` files into one <=32 KB text.

    Returns (text, paths of files included IN FULL, truncated). A file that was
    cut off or did not fit is not in the returned path list.
    """
    parts: list[str] = []
    full: list[str] = []
    used = 0
    truncated = False
    for entry in files:
        if not isinstance(entry, dict):
            continue
        path, content = entry.get("path"), entry.get("content")
        if not isinstance(path, str) or not isinstance(content, str) or not content:
            continue
        if truncated:
            continue
        header = f"=== FILE: {path} ===\n".encode("utf-8")
        body = content.encode("utf-8")
        remaining = _CODE_MAX_BYTES - used - len(header)
        if remaining <= 0:
            truncated = True
            continue
        if len(body) + 1 <= remaining:
            parts.append(header.decode("utf-8") + content + "\n")
            used += len(header) + len(body) + 1
            full.append(path)
        else:
            parts.append(
                header.decode("utf-8") + body[:remaining].decode("utf-8", "ignore")
            )
            truncated = True
    return "".join(parts), full, truncated


def review_code(
    reviewer: Agent, generated_code: str, context: str = "", files: list | None = None
) -> ReviewResult:
    """Run the single reviewer call over ``generated_code`` and return a result.

    ``generated_code`` is size-bounded to 32 KB before the call. On success the
    reviewer's verbatim output is returned in ``findings_text`` with
    ``status='ok'``. Any exception is recoverable: it returns ``status='error'``
    with a short message so the orchestration seam can continue without the review.

    When ``files`` (a commit_files proposal's ``{path, content}`` list) is given,
    the files are packed with path headers (same 32 KB cap), the reviewer is asked
    for a trailing per-file summary block, and ``file_summaries`` is filled for
    files that were sent in full. Summary parsing can never fail the review.
    """
    model = getattr(reviewer, "model", None)
    config = getattr(model, "config", None)
    model_id = config.get("model_id", "") if isinstance(config, dict) else ""

    full_paths: list[str] = []
    truncated = False
    prompt = "Review the following generated code:\n\n"
    if context:
        prompt += f"Context: {context}\n\n"
    if files:
        packed, full_paths, truncated = _pack_files(files)
        prompt += _FILE_SUMMARY_INSTRUCTIONS + packed
    else:
        prompt += generated_code.encode("utf-8")[:_CODE_MAX_BYTES].decode(
            "utf-8", "ignore"
        )
    try:
        result = reviewer(prompt)
        findings = str(result).strip()
        summaries = None
        if files:
            findings, summaries = split_file_summaries(findings, full_paths)
            if truncated:
                findings += _TRUNCATION_NOTE
        return ReviewResult(
            model_id=model_id,
            findings_text=findings,
            status="ok",
            file_summaries=summaries,
        )
    except Exception as exc:  # noqa: BLE001 - review is recoverable; never fatal
        return ReviewResult(
            model_id=model_id,
            findings_text=f"Review unavailable: {exc}",
            status="error",
        )
