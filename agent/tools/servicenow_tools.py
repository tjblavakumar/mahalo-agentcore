"""Strands read-only tools for the Mock ServiceNow service (deployments + incidents).

Ported verbatim (names, params, endpoints, docstrings, output formatting) from
mahalo-dock's ``servicenow_tools.py``, with the Strands ``@tool`` and
module-level config from ``agent.config.settings``. The write tool
(``servicenow_create_incident``) is deferred to Task 2.
"""

from __future__ import annotations

from typing import Optional

from strands import tool

from agent.config import settings
from agent.tools.http import make_request


def _servicenow_request(endpoint: str = "", params: Optional[dict] = None) -> dict:
    """Make a GET request to the ServiceNow mock service."""
    return make_request(
        settings.servicenow_url, settings.servicenow_token, endpoint=endpoint, params=params
    )


@tool
def servicenow_list_deployments(
    service: Optional[str] = None,
    environment: Optional[str] = None,
    status: Optional[str] = None,
) -> str:
    """List deployments tracked in ServiceNow.
    service: payment-service, cart-service, auth-service, product-service, or order-service.
    environment: staging | production. status: success | failed | rolled_back | in_progress."""
    params = {}
    if service:
        params["service"] = service
    if environment:
        params["environment"] = environment
    if status:
        params["status"] = status
    data = _servicenow_request(endpoint="/deployments", params=params)
    if "error" in data:
        return f"Error: {data['error']}"

    deployments = data.get("deployments", [])
    if not deployments:
        return "No deployments found for the given filters."

    output = f"Deployments ({len(deployments)} found):\n"
    for d in deployments:
        output += (
            f"\n🚀 {d['id']}: {d['service']} {d['version']} -> {d['environment']}\n"
            f"   Status: {d['status']} | By: {d.get('deployed_by', 'unknown')} | At: {d.get('deployed_at', 'n/a')}\n"
        )
        if d.get("linked_story") or d.get("linked_pr"):
            output += f"   Linked: story={d.get('linked_story', '-')} pr={d.get('linked_pr', '-')}\n"
        if d.get("notes"):
            output += f"   Notes: {d['notes']}\n"
    return output


@tool
def servicenow_deployment_status_by_project() -> str:
    """Summarize deployment statuses grouped by every ServiceNow project/service."""
    services_data = _servicenow_request(endpoint="/services")
    deployments_data = _servicenow_request(endpoint="/deployments")
    if "error" in services_data:
        return f"Error: {services_data['error']}"
    if "error" in deployments_data:
        return f"Error: {deployments_data['error']}"

    services = services_data.get("services", [])
    deployments = deployments_data.get("deployments", [])
    if not deployments:
        return "No deployment records found in ServiceNow."

    service_by_id = {service["id"]: service for service in services}
    grouped: dict[str, list[dict]] = {}
    for deployment in deployments:
        grouped.setdefault(deployment.get("service", "unknown"), []).append(deployment)

    output = f"Deployment status by project (ServiceNow, {len(deployments)} total):\n"
    for service_id, records in grouped.items():
        service = service_by_id.get(service_id, {})
        project_id = service.get("project_id", "unmapped")
        project_name = service.get("name", service_id)
        by_status: dict[str, int] = {}
        for record in records:
            status = record.get("status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1
        statuses = ", ".join(
            f"{status}: {count}" for status, count in sorted(by_status.items())
        )
        latest = max(records, key=lambda record: record.get("deployed_at", ""))
        output += (
            f"\n- {project_id} / {project_name} ({service_id}): {len(records)} deployments\n"
            f"  Status counts: {statuses}\n"
            f"  Latest: {latest.get('id', 'unknown')} {latest.get('version', '')} "
            f"({latest.get('status', 'unknown')}, {latest.get('environment', 'unknown')}, "
            f"{latest.get('deployed_at', 'unknown')})\n"
        )
    return output


@tool
def servicenow_list_incidents(
    severity: Optional[str] = None,
    status: Optional[str] = None,
    service: Optional[str] = None,
) -> str:
    """List incidents tracked in ServiceNow. By default (no filters) returns ALL incidents regardless of status.
    Only pass a status filter if the user explicitly asks for a specific status. Do NOT assume "open".
    Note: incidents that are being actively worked on include BOTH 'open' AND 'investigating' statuses;
    'resolved' incidents are closed. If the user asks who is "addressing"/"working on" incidents, include
    both open and investigating (i.e. call once with no status filter and report all non-resolved ones),
    rather than filtering to status='open' alone.
    severity: P1 (critical) | P2 (high) | P3 (medium) | P4 (low).
    status: open | investigating | resolved (omit to get all).
    service: filter by affected service (e.g. auth-service)."""
    params = {}
    if severity:
        params["severity"] = severity
    if status:
        params["status"] = status
    if service:
        params["service"] = service
    data = _servicenow_request(endpoint="/incidents", params=params)
    if "error" in data:
        return f"Error: {data['error']}"

    incidents = data.get("incidents", [])
    if not incidents:
        return "No incidents found for the given filters."

    output = f"Incidents ({len(incidents)} found):\n"
    for i in incidents:
        output += (
            f"\n🔥 {i['id']} [{i['severity']}] {i['title']}\n"
            f"   Status: {i['status']} | Service: {i['affected_service']} | Assignee: {i.get('assignee', 'Unassigned')}\n"
            f"   Opened: {i.get('opened_at', 'n/a')}"
        )
        if i.get("resolved_at"):
            output += f" | Resolved: {i['resolved_at']}"
        output += "\n"
        if i.get("linked_deployment"):
            output += f"   Linked deployment: {i['linked_deployment']}\n"
    return output


@tool
def servicenow_get_incident(incident_id: str) -> str:
    """Get full details of a specific incident by ID (e.g. INC-2001)."""
    data = _servicenow_request(endpoint=f"/incidents/{incident_id}")
    if "error" in data:
        return f"Error: {data['error']}"

    output = f"**{data['id']}: {data['title']}**\n"
    output += f"- Severity: {data['severity']}\n"
    output += f"- Status: {data['status']}\n"
    output += f"- Affected service: {data['affected_service']}\n"
    output += f"- Assignee: {data.get('assignee', 'Unassigned')}\n"
    output += f"- Opened: {data.get('opened_at', 'n/a')}\n"
    if data.get("resolved_at"):
        output += f"- Resolved: {data['resolved_at']}\n"
    if data.get("linked_deployment"):
        output += f"- Linked deployment: {data['linked_deployment']}\n"
    if data.get("description"):
        output += f"\n{data['description']}\n"
    return output


@tool
def servicenow_get_stats() -> str:
    """Get a portfolio-level deployment and incident health summary (good for executives)."""
    data = _servicenow_request(endpoint="/stats")
    if "error" in data:
        return f"Error: {data['error']}"

    output = "ServiceNow health summary:\n"
    output += f"- Total deployments: {data['total_deployments']}\n"
    for status, count in data.get("deployments_by_status", {}).items():
        output += f"    {status}: {count}\n"
    output += f"- Total incidents: {data['total_incidents']} (open: {data['open_incidents']})\n"
    for sev, count in data.get("open_incidents_by_severity", {}).items():
        output += f"    {sev}: {count}\n"
    return output


SERVICENOW_TOOLS = [
    servicenow_list_deployments,
    servicenow_deployment_status_by_project,
    servicenow_list_incidents,
    servicenow_get_incident,
    servicenow_get_stats,
]
