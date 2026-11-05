"""Shared Bedrock model allow-list + review-model resolver (FEAT-001).

Offline-safe by construction: this module declares only plain constants and pure
functions — it imports no boto3 / BedrockModel and constructs no AWS client, so
``import agent.model_config`` succeeds with no AWS credentials (NFR-4).

The allow-list is server-enforced because the Function URL is ``AuthType=NONE``
(NFR-6): a client-supplied ``review_model_id`` that is absent or off-list is
silently resolved to the default review model rather than trusted.
"""

from __future__ import annotations

# The fixed code-generation model (the main agent's model, Sonnet 4.5).
CODE_GEN_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
CODE_GEN_MODEL_LABEL = "Claude Sonnet 4.5"

# The review models the server will accept, id -> human label.
REVIEW_ALLOW_LIST: dict[str, str] = {
    "us.amazon.nova-lite-v1:0": "Nova Lite",
    "us.amazon.nova-micro-v1:0": "Nova Micro",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": "Claude Haiku 4.5",
}

# The review model used when none is requested or the request is off-list.
DEFAULT_REVIEW_MODEL_ID = "us.amazon.nova-lite-v1:0"


def label(model_id: str) -> str:
    """Return the human label for a known model id, or the id itself if unknown."""
    if model_id == CODE_GEN_MODEL_ID:
        return CODE_GEN_MODEL_LABEL
    return REVIEW_ALLOW_LIST.get(model_id, model_id)


def resolve_review_model(requested_id) -> tuple[str, bool]:
    """Resolve a requested review model id against the allow-list.

    Returns ``(resolved_id, did_fallback)``: the id unchanged with
    ``did_fallback=False`` when it is on the review allow-list, else
    ``(DEFAULT_REVIEW_MODEL_ID, True)`` for an absent or off-list id.
    """
    if isinstance(requested_id, str) and requested_id in REVIEW_ALLOW_LIST:
        return requested_id, False
    return DEFAULT_REVIEW_MODEL_ID, True
