"""Dashboard router: GET + PUT /dashboard/widgets — per-persona viz persistence.

A thin forwarder to one DynamoDB table (``mahalo-dashboards``, §3.1). Like the
chat router it imports ZERO agent/LangChain code; its only AWS dependency is a
boto3 DynamoDB **resource** client built LAZILY on first use (mirroring
``runtime_client.py``) so importing this module stays offline-safe.

Identity: ``current_identity`` maps ``X-Mahalo-Persona`` to ``{developer_id,
role}``; this router derives the canonical ``personaId`` from ``role`` via
``_ROLE_TO_PERSONA`` (single source of identity — the raw header is never
re-read). The numeric float<->Decimal boundary (§3.3a) is owned by
``dashboard_serde``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException

from app.auth import Identity, current_identity
from app.config import settings
from app.dashboard_seed import default_widgets_for
from app.dashboard_serde import _decimalize, _undecimalize
from app.models import DashboardWidgets, spec_is_structurally_valid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# role -> canonical personaId. Mirror of api/app/auth.py::_PERSONA_MAP roles.
_ROLE_TO_PERSONA: dict[str, str] = {
    "product_manager": "pm",
    "developer": "dev",
    "executive": "exec",
}
_DEFAULT_PERSONA = "dev"

_table = None


def _get_table():
    """Build the boto3 DynamoDB resource Table once, on first use (not import)."""
    global _table
    if _table is None:
        import boto3

        resource = boto3.resource("dynamodb", region_name=settings.region)
        _table = resource.Table(settings.dashboard_table)
    return _table


def _persona_id(ident: Identity) -> str:
    """Derive the canonical personaId from the resolved role."""
    return _ROLE_TO_PERSONA.get(ident.role, _DEFAULT_PERSONA)


@router.get("/widgets")
def get_widgets(ident: Identity = Depends(current_identity)) -> dict:
    """Return the persona's stored widgets, or the seeded default if none exist.

    A read never writes: an absent item returns the static default WITHOUT
    materializing it. A malformed stored item falls back to the default (logged
    warning). A DynamoDB error -> 502.
    """
    persona_id = _persona_id(ident)
    try:
        resp = _get_table().get_item(Key={"personaId": persona_id})
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Dashboard GetItem failed")
        raise HTTPException(status_code=502, detail=f"Dashboard read failed: {exc}")

    item = resp.get("Item")
    if not item or "widgets" not in item:
        return {"widgets": default_widgets_for(persona_id)}

    try:
        widgets = _undecimalize(item["widgets"])
        if not isinstance(widgets, list):
            raise ValueError("stored widgets is not a list")
    except (ValueError, TypeError):
        logger.warning(
            "Malformed stored dashboard for persona %s; serving seeded default",
            persona_id,
        )
        return {"widgets": default_widgets_for(persona_id)}

    return {"widgets": widgets}


@router.put("/widgets")
def put_widgets(
    body: DashboardWidgets, ident: Identity = Depends(current_identity)
) -> dict:
    """Overwrite the persona's entire widget set (idempotent full replace).

    Runs the structural spec guard (422 on fail), converts floats to Decimal for
    the resource client (§3.3a), stamps ``updatedAt`` server-side, and PutItems a
    single item. A DynamoDB error -> 502.
    """
    persona_id = _persona_id(ident)

    body_dict = body.model_dump()
    for widget in body_dict["widgets"]:
        if not spec_is_structurally_valid(widget["spec"]):
            raise HTTPException(
                status_code=422,
                detail=f"Widget {widget['id']!r} has a structurally invalid spec",
            )

    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    item = _decimalize(
        {
            "personaId": persona_id,
            "widgets": body_dict["widgets"],
            "updatedAt": updated_at,
        }
    )
    try:
        _get_table().put_item(Item=item)
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Dashboard PutItem failed")
        raise HTTPException(status_code=502, detail=f"Dashboard write failed: {exc}")

    return {"widgets": body_dict["widgets"]}
