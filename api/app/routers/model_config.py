"""Model-config router: GET + PUT /model-config — per-persona model selection.

A thin forwarder to one DynamoDB table (``mahalo-model-config``, design §B.1),
mirroring ``api/app/routers/dashboard.py`` exactly: it imports ZERO agent code,
builds its boto3 DynamoDB **resource** client LAZILY on first use so importing
this module stays offline-safe (NFR-4), derives the canonical ``personaId`` from
the resolved ``role`` via ``_ROLE_TO_PERSONA`` (the raw header is never re-read),
reads default-on-absent WITHOUT materialising, overwrites on PUT, 422 on
structural/allow-list validation, and 502 on a DynamoDB error.

The ``ModelConfig`` validators are the server-side allow-list trust boundary
(NFR-6): a value off the review allow-list is rejected before any ``put_item``,
so a hand-crafted request to the ``AuthType=NONE`` Function URL can never persist
an off-list model.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException

from app.auth import Identity, current_identity
from app.config import settings
from app.models import (
    CODE_GEN_MODEL_ID,
    DEFAULT_REVIEW_MODEL_ID,
    REVIEW_ALLOW_LIST,
    ModelConfig,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/model-config", tags=["model-config"])

# role -> canonical personaId. Mirror of api/app/auth.py::_PERSONA_MAP roles
# (same rule as the dashboard router).
_ROLE_TO_PERSONA: dict[str, str] = {
    "product_manager": "pm",
    "developer": "dev",
    "executive": "exec",
}
_DEFAULT_PERSONA = "dev"

# The documented defaults returned for a persona with no stored item (FR-7).
_DEFAULTS = {
    "codeGeneration": CODE_GEN_MODEL_ID,
    "codeReview": DEFAULT_REVIEW_MODEL_ID,
    "security": DEFAULT_REVIEW_MODEL_ID,
}

_table = None


def _get_table():
    """Build the boto3 DynamoDB resource Table once, on first use (not import)."""
    global _table
    if _table is None:
        import boto3

        resource = boto3.resource("dynamodb", region_name=settings.region)
        _table = resource.Table(settings.model_config_table)
    return _table


def _persona_id(ident: Identity) -> str:
    """Derive the canonical personaId from the resolved role."""
    return _ROLE_TO_PERSONA.get(ident.role, _DEFAULT_PERSONA)


def _config_is_structurally_valid(item: dict) -> bool:
    """True when a stored item carries a well-formed, on-allow-list config."""
    try:
        return (
            item.get("codeGeneration") == CODE_GEN_MODEL_ID
            and item.get("codeReview") in REVIEW_ALLOW_LIST
            and item.get("security") in REVIEW_ALLOW_LIST
        )
    except (AttributeError, TypeError):
        return False


@router.get("")
def get_model_config(ident: Identity = Depends(current_identity)) -> dict:
    """Return the persona's stored model config, or the documented defaults.

    A read never writes: an absent item returns the static defaults WITHOUT
    materializing them. A malformed stored item falls back to the defaults
    (logged warning). A DynamoDB error -> 502.
    """
    persona_id = _persona_id(ident)
    try:
        resp = _get_table().get_item(Key={"personaId": persona_id})
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Model-config GetItem failed")
        raise HTTPException(status_code=502, detail=f"Model-config read failed: {exc}")

    item = resp.get("Item")
    if not item or not _config_is_structurally_valid(item):
        if item:
            logger.warning(
                "Malformed stored model-config for persona %s; serving defaults",
                persona_id,
            )
        return dict(_DEFAULTS)

    return {
        "codeGeneration": item["codeGeneration"],
        "codeReview": item["codeReview"],
        "security": item["security"],
    }


@router.put("")
def put_model_config(
    body: ModelConfig, ident: Identity = Depends(current_identity)
) -> dict:
    """Overwrite the persona's model config (idempotent full replace).

    The body is validated by ``ModelConfig`` (pydantic 422 on a bad shape or an
    off-allow-list value); we re-check the review ids against the allow-list
    here as the explicit trust boundary (422 on off-list), stamp ``updatedAt``
    server-side, and PutItem a single item. A DynamoDB error -> 502.
    """
    persona_id = _persona_id(ident)

    config = body.model_dump()
    # Defence in depth: the ModelConfig validator already enforced this, but the
    # allow-list is the trust boundary for the AuthType=NONE URL (NFR-6).
    for key in ("codeReview", "security"):
        if config[key] not in REVIEW_ALLOW_LIST:
            raise HTTPException(
                status_code=422,
                detail=f"{config[key]!r} is not an allowed review model",
            )

    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    item = {"personaId": persona_id, **config, "updatedAt": updated_at}
    try:
        _get_table().put_item(Item=item)
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Model-config PutItem failed")
        raise HTTPException(status_code=502, detail=f"Model-config write failed: {exc}")

    return config
