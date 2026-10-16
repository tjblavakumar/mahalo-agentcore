"""Strands WRITE tool for the Mock ServiceNow service (Task 2, HITL-gated).

Thin ``@tool`` function mirroring the Task 1 read-module pattern: read config
from ``agent.config.settings``, call the shared ``make_request`` seam, return a
formatted string, never raise. The real POST happens here only after the write is
approved by the hook (FEAT-002).
"""

from __future__ import annotations

from typing import Optional

import httpx

from strands import tool

from agent.config import settings
from agent.tools.http import make_request


@tool
def servicenow_create_incident(
    title: str,
    affected_service: str,
    severity: str = "P3",
    description: str = "",
    assignee: Optional[str] = None,
    linked_deployment: Optional[str] = None,
) -> str:
    """Open a new incident in ServiceNow. [WRITE ACTION - REQUIRES APPROVAL]
    affected_service: payment-service, cart-service, auth-service,
    product-service, or order-service.
    severity: P1 (critical) | P2 (high) | P3 (medium) | P4 (low), default P3.
    description: optional detail. assignee: optional developer ID.
    linked_deployment: optional deployment ID this incident relates to."""
    body = {
        "title": title,
        "affected_service": affected_service,
        "severity": severity,
        "description": description,
        "assignee": assignee,
        "linked_deployment": linked_deployment,
    }
    try:
        data = make_request(
            settings.servicenow_url,
            settings.servicenow_token,
            endpoint="/incidents",
            method="POST",
            body=body,
        )
    except (httpx.HTTPError, OSError) as exc:
        return f"❌ Failed to open incident: {exc}"

    if "error" in data:
        return f"❌ Failed to open incident: {data['error']}"
    return (
        f"✅ Incident opened successfully: **{data['id']}** - "
        f"{data['title']} ({data['severity']})"
    )


SERVICENOW_WRITE_TOOLS = [servicenow_create_incident]
