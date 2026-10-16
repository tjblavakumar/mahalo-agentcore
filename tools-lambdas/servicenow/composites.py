"""Server-side ServiceNow composite for Gateway (MCP) mode.

``servicenow_deployment_status_by_project`` is not a single HTTP call in DIRECT
mode: the agent joins ``/services`` with ``/deployments`` and produces a
grouped-by-service aggregation. This handler reproduces that join server-side by
calling the Lambda's own routes through the in-process ``Router`` and composing
the same records, returning plain JSON (the model re-renders it).
"""

from __future__ import annotations

from typing import Any, Dict, List

from common.gateway_dispatch import get_json


def deployment_status(store, router, token, args: Dict[str, Any]) -> Dict[str, Any]:
    """Group deployments by service, mirroring the agent aggregation's data."""
    services_data = get_json(router, token, "/services")
    deployments_data = get_json(router, token, "/deployments")

    services = services_data.get("services", []) if isinstance(services_data, dict) else []
    deployments = (
        deployments_data.get("deployments", []) if isinstance(deployments_data, dict) else []
    )

    service_by_id = {s["id"]: s for s in services}
    grouped: Dict[str, List[dict]] = {}
    for deployment in deployments:
        grouped.setdefault(deployment.get("service", "unknown"), []).append(deployment)

    projects: List[Dict[str, Any]] = []
    for service_id, records in grouped.items():
        service = service_by_id.get(service_id, {})
        by_status: Dict[str, int] = {}
        for record in records:
            status = record.get("status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1
        latest = max(records, key=lambda r: r.get("deployed_at", "")) if records else {}
        projects.append(
            {
                "service": service_id,
                "project_id": service.get("project_id", "unmapped"),
                "project_name": service.get("name", service_id),
                "count": len(records),
                "status_counts": by_status,
                "latest": {
                    "id": latest.get("id", "unknown"),
                    "version": latest.get("version", ""),
                    "status": latest.get("status", "unknown"),
                    "environment": latest.get("environment", "unknown"),
                    "deployed_at": latest.get("deployed_at", "unknown"),
                },
            }
        )

    return {"total_deployments": len(deployments), "projects": projects}
