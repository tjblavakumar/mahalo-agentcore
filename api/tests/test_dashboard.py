"""Tests for the dashboard router + seed + serde (design §9), moto-backed.

All offline: ``@mock_aws`` fakes DynamoDB, dummy creds force no real credential
lookup. The ``mahalo-dashboards`` table is keyed on ``personaId`` (matching
MahaloDashboardStack). Imports are ``app.*`` per api/conftest.py.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.routers import dashboard
from app.dashboard_seed import default_widgets_for
from app.dashboard_serde import _decimalize, _undecimalize
from app.models import spec_is_structurally_valid

_TABLE_NAME = "mahalo-dashboards"

# A persona header -> personaId map matching api/app/auth.py + the router.
_PM = {"X-Mahalo-Persona": "pm"}
_DEV = {"X-Mahalo-Persona": "dev"}
_EXEC = {"X-Mahalo-Persona": "exec"}


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch):
    """Force dummy AWS creds/region so no real credential lookup happens."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("MAHALO_DASHBOARD_TABLE", _TABLE_NAME)


def _create_table():
    client = boto3.client("dynamodb", region_name="us-east-1")
    client.create_table(
        TableName=_TABLE_NAME,
        KeySchema=[{"AttributeName": "personaId", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "personaId", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=_TABLE_NAME)
    return boto3.resource("dynamodb", region_name="us-east-1").Table(_TABLE_NAME)


@pytest.fixture
def table():
    """Create the mahalo-dashboards table under moto; reset the lazy client."""
    with mock_aws():
        tbl = _create_table()
        # Reset the router's cached lazy table so it binds to THIS moto table.
        dashboard._table = None
        try:
            yield tbl
        finally:
            dashboard._table = None


@pytest.fixture
def client():
    # Import inside the fixture so app.main picks up the env set above.
    from app.main import app

    return TestClient(app)


# --- GET ---------------------------------------------------------------------


def test_get_returns_stored_item(table, client):
    table.put_item(
        Item={
            "personaId": "pm",
            "widgets": [
                {
                    "id": "w1",
                    "spec": {
                        "type": "bar",
                        "title": "Stored",
                        "xKey": "x",
                        "series": [{"name": "S", "dataKey": "v"}],
                        "data": [{"x": "A", "v": Decimal("3")}],
                    },
                    "layout": {"x": 0, "y": 0, "w": 6, "h": 8},
                }
            ],
            "updatedAt": "2026-01-01T00:00:00Z",
        }
    )
    resp = client.get("/dashboard/widgets", headers=_PM)
    assert resp.status_code == 200
    widgets = resp.json()["widgets"]
    assert widgets[0]["id"] == "w1"
    # Decimal converted back to a plain number.
    assert widgets[0]["spec"]["data"][0]["v"] == 3


def test_get_without_item_returns_seed_and_writes_nothing(table, client):
    resp = client.get("/dashboard/widgets", headers=_EXEC)
    assert resp.status_code == 200
    widgets = resp.json()["widgets"]
    assert widgets == default_widgets_for("exec")
    # A read must NOT materialize the default: table still empty.
    scan = table.scan()
    assert scan["Count"] == 0


def test_get_dynamodb_error_returns_502(client, monkeypatch):
    # No table created -> GetItem raises a ClientError (ResourceNotFound).
    with mock_aws():
        dashboard._table = None
        resp = client.get("/dashboard/widgets", headers=_DEV)
        dashboard._table = None
    assert resp.status_code == 502


# --- PUT ---------------------------------------------------------------------


def test_put_overwrites_with_float_roundtrip(table, client):
    body = {
        "widgets": [
            {
                "id": "w_ratio",
                "spec": {
                    "type": "line",
                    "title": "Velocity ratio",
                    "xKey": "sprint",
                    "series": [{"name": "Ratio", "dataKey": "ratio"}],
                    "data": [{"sprint": "S-1", "ratio": 0.83}],
                },
                "layout": {"x": 0, "y": 0, "w": 6, "h": 8},
            }
        ]
    }
    resp = client.put("/dashboard/widgets", json=body, headers=_PM)
    assert resp.status_code == 200
    assert resp.json()["widgets"][0]["spec"]["data"][0]["ratio"] == 0.83

    # Stored as Decimal (write side); GET reads it back as a float.
    stored = table.get_item(Key={"personaId": "pm"})["Item"]
    assert stored["widgets"][0]["spec"]["data"][0]["ratio"] == Decimal("0.83")
    get_resp = client.get("/dashboard/widgets", headers=_PM)
    assert get_resp.json()["widgets"][0]["spec"]["data"][0]["ratio"] == 0.83


def test_put_dynamodb_error_returns_502(client):
    body = {
        "widgets": [
            {
                "id": "w1",
                "spec": {
                    "type": "bar",
                    "title": "T",
                    "xKey": "x",
                    "series": [{"name": "S", "dataKey": "v"}],
                    "data": [{"x": "A", "v": 1}],
                },
                "layout": {"x": 0, "y": 0, "w": 6, "h": 8},
            }
        ]
    }
    with mock_aws():
        dashboard._table = None  # no table created -> PutItem raises
        resp = client.put("/dashboard/widgets", json=body, headers=_PM)
        dashboard._table = None
    assert resp.status_code == 502


def test_put_bad_body_pydantic_422(table, client):
    # Missing required layout field -> pydantic 422.
    bad = {"widgets": [{"id": "w1", "spec": {"type": "bar"}}]}
    resp = client.put("/dashboard/widgets", json=bad, headers=_PM)
    assert resp.status_code == 422


def test_put_structurally_invalid_spec_422(table, client):
    # Well-formed SavedWidget but the spec fails the structural guard (bad type).
    bad = {
        "widgets": [
            {
                "id": "w1",
                "spec": {"type": "pie", "title": "Nope"},
                "layout": {"x": 0, "y": 0, "w": 6, "h": 8},
            }
        ]
    }
    resp = client.put("/dashboard/widgets", json=bad, headers=_PM)
    assert resp.status_code == 422


# --- Seed + serde ------------------------------------------------------------


@pytest.mark.parametrize(
    "persona, count",
    [("pm", 2), ("dev", 2), ("exec", 1)],
)
def test_default_widgets_counts_and_guard(persona, count):
    widgets = default_widgets_for(persona)
    assert len(widgets) == count
    for widget in widgets:
        assert spec_is_structurally_valid(widget["spec"])


def test_exec_default_is_the_health_bar():
    (widget,) = default_widgets_for("exec")
    spec = widget["spec"]
    assert spec["type"] == "bar"
    assert spec["title"] == "Delivery health by project"
    assert spec["series"] == [{"name": "Health score", "dataKey": "health"}]
    assert spec_is_structurally_valid(spec)


def test_default_widgets_returns_deep_copies():
    first = default_widgets_for("pm")
    first[0]["spec"]["title"] = "mutated"
    second = default_widgets_for("pm")
    assert second[0]["spec"]["title"] == "Story points by sprint"


def test_decimalize_undecimalize_roundtrip():
    decimalized = _decimalize({"ratio": 0.83})
    assert decimalized["ratio"] == Decimal("0.83")
    assert _undecimalize(decimalized) == {"ratio": 0.83}
    # Integers stay ints through the round-trip.
    assert _undecimalize(_decimalize({"n": 5})) == {"n": 5}
    assert isinstance(_undecimalize(Decimal("5")), int)
