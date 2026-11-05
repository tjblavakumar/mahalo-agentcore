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

from dataclasses import dataclass

from strands import Agent

from agent.strands_agent import _build_bedrock_model

# Reviewer output is bounded before the call so a large code-gen turn cannot blow
# past the model's context or the read timeout.
_CODE_MAX_BYTES = 32 * 1024

REVIEWER_SYSTEM_PROMPT = (
    "You are an independent senior software reviewer. You are given code that "
    "another engineer generated. Do NOT rewrite the code. Review it for "
    "correctness, security, and maintainability. Respond with a single "
    "assessment line, then either a short bulleted list of specific concerns or "
    "the exact text 'no blocking issues found' when there is nothing material to "
    "flag."
)


@dataclass
class ReviewResult:
    """The outcome of one review stage."""

    model_id: str
    findings_text: str
    status: str


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


def review_code(reviewer: Agent, generated_code: str, context: str = "") -> ReviewResult:
    """Run the single reviewer call over ``generated_code`` and return a result.

    ``generated_code`` is size-bounded to 32 KB before the call. On success the
    reviewer's verbatim output is returned in ``findings_text`` with
    ``status='ok'``. Any exception is recoverable: it returns ``status='error'``
    with a short message so the orchestration seam can continue without the review.
    """
    model = getattr(reviewer, "model", None)
    config = getattr(model, "config", None)
    model_id = config.get("model_id", "") if isinstance(config, dict) else ""

    code = generated_code.encode("utf-8")[:_CODE_MAX_BYTES].decode("utf-8", "ignore")
    prompt = "Review the following generated code:\n\n"
    if context:
        prompt += f"Context: {context}\n\n"
    prompt += code

    try:
        result = reviewer(prompt)
        return ReviewResult(
            model_id=model_id,
            findings_text=str(result).strip(),
            status="ok",
        )
    except Exception as exc:  # noqa: BLE001 - review is recoverable; never fatal
        return ReviewResult(
            model_id=model_id,
            findings_text=f"Review unavailable: {exc}",
            status="error",
        )
