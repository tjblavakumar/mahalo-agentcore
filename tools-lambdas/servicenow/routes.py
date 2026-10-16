"""ServiceNow mock routes ported from mahalo-dock servicenow/main.py.

Collections (``pk``): SERVICE, DEPLOYMENT, INCIDENT
(natural id under ``sk``; record under ``data``).
"""

from datetime import datetime, timezone

from common.auth import require_token
from common.responses import error, json_response
from common.router import Router

from . import seed_data

PK_SERVICE = "SERVICE"
PK_DEPLOYMENT = "DEPLOYMENT"
PK_INCIDENT = "INCIDENT"


def seed_items():
    for svc in seed_data.SERVICES:
        yield {"pk": PK_SERVICE, "sk": svc["id"], "record": svc}
    for dep in seed_data.DEPLOYMENTS:
        yield {"pk": PK_DEPLOYMENT, "sk": dep["id"], "record": dep}
    for inc in seed_data.INCIDENTS:
        yield {"pk": PK_INCIDENT, "sk": inc["id"], "record": inc}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_router(store, token):
    router = Router()

    def _auth(request):
        if not require_token(request, token):
            return error(401, "Invalid API token")
        return None

    @router.route("GET", "/health")
    def health(request):
        return json_response(
            200, {"status": "healthy", "service": "mock-servicenow", "version": "1.0.0"}
        )

    # --- Services ---

    @router.route("GET", "/services")
    def list_services(request):
        denied = _auth(request)
        if denied:
            return denied
        return json_response(200, {"services": store.query(PK_SERVICE)})

    # --- Deployments ---

    @router.route("GET", "/deployments")
    def list_deployments(request):
        denied = _auth(request)
        if denied:
            return denied
        deployments = store.query(PK_DEPLOYMENT)
        service = request.query.get("service")
        environment = request.query.get("environment")
        status = request.query.get("status")
        if service:
            deployments = [d for d in deployments if d["service"] == service]
        if environment:
            deployments = [d for d in deployments if d["environment"] == environment]
        if status:
            deployments = [d for d in deployments if d["status"] == status]
        deployments.sort(key=lambda d: d.get("deployed_at", ""), reverse=True)
        return json_response(200, {"deployments": deployments, "total": len(deployments)})

    @router.route("GET", "/deployments/{deployment_id}")
    def get_deployment(request):
        denied = _auth(request)
        if denied:
            return denied
        dep = store.get(PK_DEPLOYMENT, request.path_params["deployment_id"])
        if not dep:
            return error(404, "Deployment not found")
        return json_response(200, dep)

    # --- Incidents ---

    @router.route("GET", "/incidents")
    def list_incidents(request):
        denied = _auth(request)
        if denied:
            return denied
        incidents = store.query(PK_INCIDENT)
        severity = request.query.get("severity")
        status = request.query.get("status")
        service = request.query.get("service")
        assignee = request.query.get("assignee")
        if severity:
            incidents = [i for i in incidents if i["severity"] == severity]
        if status:
            incidents = [i for i in incidents if i["status"] == status]
        if service:
            incidents = [i for i in incidents if i["affected_service"] == service]
        if assignee:
            incidents = [i for i in incidents if i.get("assignee") == assignee]
        incidents.sort(key=lambda i: i.get("opened_at", ""), reverse=True)
        return json_response(200, {"incidents": incidents, "total": len(incidents)})

    @router.route("GET", "/incidents/{incident_id}")
    def get_incident(request):
        denied = _auth(request)
        if denied:
            return denied
        inc = store.get(PK_INCIDENT, request.path_params["incident_id"])
        if not inc:
            return error(404, "Incident not found")
        return json_response(200, inc)

    @router.route("POST", "/incidents")
    def create_incident(request):
        denied = _auth(request)
        if denied:
            return denied
        body = request.json_body or {}
        for field in ("title", "affected_service"):
            if body.get(field) in (None, ""):
                return error(422, f"Field '{field}' is required")
        affected_service = body["affected_service"]
        if not store.exists(PK_SERVICE, affected_service):
            return error(404, "Unknown affected_service")
        max_num = 2000
        for i in store.query(PK_INCIDENT):
            try:
                num = int(i["id"].split("-")[1])
                max_num = max(max_num, num)
            except (IndexError, ValueError):
                continue
        new_id = f"INC-{max_num + 1}"
        new_incident = {
            "id": new_id,
            "title": body["title"],
            "severity": body.get("severity", "P3"),
            "status": "open",
            "affected_service": affected_service,
            "assignee": body.get("assignee"),
            "opened_at": _now(),
            "resolved_at": None,
            "linked_deployment": body.get("linked_deployment"),
            "description": body.get("description", ""),
        }
        store.put(PK_INCIDENT, new_id, new_incident)
        return json_response(201, new_incident)

    @router.route("PUT", "/incidents/{incident_id}")
    def update_incident(request):
        denied = _auth(request)
        if denied:
            return denied
        incident_id = request.path_params["incident_id"]
        inc = store.get(PK_INCIDENT, incident_id)
        if not inc:
            return error(404, "Incident not found")
        body = request.json_body or {}
        if body.get("status") is not None:
            inc["status"] = body["status"]
            if body["status"] == "resolved" and not inc.get("resolved_at"):
                inc["resolved_at"] = _now()
        if body.get("severity") is not None:
            inc["severity"] = body["severity"]
        if body.get("assignee") is not None:
            inc["assignee"] = body["assignee"]
        store.put(PK_INCIDENT, incident_id, inc)
        return json_response(200, inc)

    # --- Stats ---

    @router.route("GET", "/stats")
    def get_stats(request):
        denied = _auth(request)
        if denied:
            return denied
        deployments = store.query(PK_DEPLOYMENT)
        incidents = store.query(PK_INCIDENT)
        by_status = {}
        for d in deployments:
            by_status[d["status"]] = by_status.get(d["status"], 0) + 1
        open_incidents = [i for i in incidents if i["status"] != "resolved"]
        by_severity = {}
        for i in open_incidents:
            by_severity[i["severity"]] = by_severity.get(i["severity"], 0) + 1
        return json_response(
            200,
            {
                "total_deployments": len(deployments),
                "deployments_by_status": by_status,
                "total_incidents": len(incidents),
                "open_incidents": len(open_incidents),
                "open_incidents_by_severity": by_severity,
            },
        )

    return router
