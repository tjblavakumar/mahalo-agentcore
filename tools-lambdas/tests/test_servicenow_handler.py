"""Handler tests for the ServiceNow mock Lambda."""

import importlib

import pytest

from tests.conftest import body_of, make_event

TOKEN = "mock-servicenow-token-12345"


@pytest.fixture
def handler(dynamo_table, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", dynamo_table)
    monkeypatch.setenv("MOCK_SERVICENOW_TOKEN", TOKEN)
    import servicenow.handler as h

    importlib.reload(h)
    h._store = None
    h._router = None
    return h


def invoke(handler, method, path, **kwargs):
    return handler.lambda_handler(make_event(method, path, **kwargs), None)


def test_health_no_token(handler):
    resp = invoke(handler, "GET", "/health")
    assert resp["statusCode"] == 200
    assert body_of(resp)["service"] == "mock-servicenow"


def test_auth_401(handler):
    resp = invoke(handler, "GET", "/services")
    assert resp["statusCode"] == 401


def test_list_services(handler):
    resp = invoke(handler, "GET", "/services", token=TOKEN)
    ids = {s["id"] for s in body_of(resp)["services"]}
    assert "payment-service" in ids and len(ids) == 5


def test_deployments_sorted_desc(handler):
    resp = invoke(handler, "GET", "/deployments", token=TOKEN)
    body = body_of(resp)
    assert body["total"] == 50
    dates = [d["deployed_at"] for d in body["deployments"]]
    assert dates == sorted(dates, reverse=True)


def test_deployment_filter(handler):
    resp = invoke(
        handler, "GET", "/deployments", query={"environment": "production"}, token=TOKEN
    )
    assert all(d["environment"] == "production" for d in body_of(resp)["deployments"])


def test_deployment_404(handler):
    resp = invoke(handler, "GET", "/deployments/DEP-9999", token=TOKEN)
    assert resp["statusCode"] == 404
    assert body_of(resp)["detail"] == "Deployment not found"


def test_incidents_sorted_desc_and_filter(handler):
    resp = invoke(handler, "GET", "/incidents", query={"status": "open"}, token=TOKEN)
    body = body_of(resp)
    assert all(i["status"] == "open" for i in body["incidents"])
    opened = [i["opened_at"] for i in body["incidents"]]
    assert opened == sorted(opened, reverse=True)


def test_incident_404(handler):
    resp = invoke(handler, "GET", "/incidents/INC-9999", token=TOKEN)
    assert resp["statusCode"] == 404
    assert body_of(resp)["detail"] == "Incident not found"


def test_create_incident_read_after_write(handler):
    resp = invoke(
        handler,
        "POST",
        "/incidents",
        token=TOKEN,
        body={"title": "DB outage", "affected_service": "payment-service"},
    )
    assert resp["statusCode"] == 201
    created = body_of(resp)
    assert created["id"] == "INC-2051"  # max seed 2050 -> 2051
    assert created["status"] == "open"
    assert created["severity"] == "P3"
    assert created["resolved_at"] is None

    listed = invoke(handler, "GET", "/incidents", query={"status": "open"}, token=TOKEN)
    assert any(i["id"] == "INC-2051" for i in body_of(listed)["incidents"])


def test_create_incident_missing_field_422_before_404(handler):
    # Missing title must 422 even though affected_service is unknown.
    resp = invoke(
        handler,
        "POST",
        "/incidents",
        token=TOKEN,
        body={"affected_service": "nope"},
    )
    assert resp["statusCode"] == 422
    assert body_of(resp)["detail"] == "Field 'title' is required"


def test_create_incident_unknown_service_404(handler):
    resp = invoke(
        handler,
        "POST",
        "/incidents",
        token=TOKEN,
        body={"title": "x", "affected_service": "nope"},
    )
    assert resp["statusCode"] == 404
    assert body_of(resp)["detail"] == "Unknown affected_service"


def test_update_incident_resolve_sets_resolved_at(handler):
    resp = invoke(
        handler, "PUT", "/incidents/INC-2003", token=TOKEN, body={"status": "resolved"}
    )
    assert resp["statusCode"] == 200
    updated = body_of(resp)
    assert updated["status"] == "resolved"
    assert updated["resolved_at"] is not None


def test_stats(handler):
    resp = invoke(handler, "GET", "/stats", token=TOKEN)
    body = body_of(resp)
    assert body["total_deployments"] == 50
    assert body["total_incidents"] == 50
    assert body["open_incidents"] == len(
        [i for i in body_of(invoke(handler, "GET", "/incidents", token=TOKEN))["incidents"]
         if i["status"] != "resolved"]
    )
    assert "deployments_by_status" in body
