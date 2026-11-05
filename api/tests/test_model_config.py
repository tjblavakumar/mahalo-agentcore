"""Tests for the model-config router (design §B.1), moto-backed.

All offline: ``@mock_aws`` fakes DynamoDB, dummy creds force no real credential
lookup. The ``mahalo-model-config`` table is keyed on ``personaId`` (matching
MahaloModelConfigStack). Imports are ``app.*`` per api/conftest.py. Mirrors
api/tests/test_dashboard.py.
"""

from __future__ import annotations

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.models import (
    CODE_GEN_MODEL_ID,
    DEFAULT_REVIEW_MODEL_ID,
)
from app.routers import model_config

_TABLE_NAME = "mahalo-model-config"

# A persona header -> personaId map matching api/app/auth.py + the router.
_PM = {"X-Mahalo-Persona": "pm"}
_DEV = {"X-Mahalo-Persona": "dev"}
_EXEC = {"X-Mahalo-Persona": "exec"}

# A review model id that is NOT the default (second allow-list member).
_ALT_REVIEW = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
# A review model id that is OFF the allow-list (invoke-verified but dropped, §A).
_OFF_LIST = "us.anthropic.claude-opus-4-5-20251101-v1:0"


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch):
    """Force dummy AWS creds/region so no real credential lookup happens."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("MAHALO_MODEL_CONFIG_TABLE", _TABLE_NAME)


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
    """Create the mahalo-model-config table under moto; reset the lazy client."""
    with mock_aws():
        tbl = _create_table()
        # Reset the router's cached lazy table so it binds to THIS moto table.
        model_config._table = None
        try:
            yield tbl
        finally:
            model_config._table = None


@pytest.fixture
def client():
    # Import inside the fixture so app.main picks up the env set above.
    from app.main import app

    return TestClient(app)


# --- GET ---------------------------------------------------------------------


def test_get_without_item_returns_defaults_and_writes_nothing(table, client):
    resp = client.get("/model-config", headers=_EXEC)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "codeGeneration": CODE_GEN_MODEL_ID,
        "codeReview": DEFAULT_REVIEW_MODEL_ID,
        "security": DEFAULT_REVIEW_MODEL_ID,
    }
    # A read must NOT materialize the default: table still empty.
    scan = table.scan()
    assert scan["Count"] == 0


def test_get_returns_stored_config(table, client):
    table.put_item(
        Item={
            "personaId": "pm",
            "codeGeneration": CODE_GEN_MODEL_ID,
            "codeReview": _ALT_REVIEW,
            "security": DEFAULT_REVIEW_MODEL_ID,
            "updatedAt": "2026-01-01T00:00:00Z",
        }
    )
    resp = client.get("/model-config", headers=_PM)
    assert resp.status_code == 200
    assert resp.json() == {
        "codeGeneration": CODE_GEN_MODEL_ID,
        "codeReview": _ALT_REVIEW,
        "security": DEFAULT_REVIEW_MODEL_ID,
    }


def test_get_malformed_item_falls_back_to_defaults(table, client):
    # A stored item with an off-list review id -> serve defaults (warning log).
    table.put_item(
        Item={
            "personaId": "dev",
            "codeGeneration": CODE_GEN_MODEL_ID,
            "codeReview": _OFF_LIST,
            "security": DEFAULT_REVIEW_MODEL_ID,
        }
    )
    resp = client.get("/model-config", headers=_DEV)
    assert resp.status_code == 200
    assert resp.json()["codeReview"] == DEFAULT_REVIEW_MODEL_ID


def test_get_dynamodb_error_returns_502(client):
    # No table created -> GetItem raises a ClientError (ResourceNotFound).
    with mock_aws():
        model_config._table = None
        resp = client.get("/model-config", headers=_DEV)
        model_config._table = None
    assert resp.status_code == 502


# --- PUT ---------------------------------------------------------------------


def test_put_roundtrips_valid_config(table, client):
    body = {
        "codeGeneration": CODE_GEN_MODEL_ID,
        "codeReview": _ALT_REVIEW,
        "security": DEFAULT_REVIEW_MODEL_ID,
    }
    resp = client.put("/model-config", json=body, headers=_PM)
    assert resp.status_code == 200
    assert resp.json() == body

    # Stored with a server-stamped updatedAt; GET reads it back unchanged.
    stored = table.get_item(Key={"personaId": "pm"})["Item"]
    assert stored["codeReview"] == _ALT_REVIEW
    assert "updatedAt" in stored
    get_resp = client.get("/model-config", headers=_PM)
    assert get_resp.json() == body


def test_put_off_list_code_review_is_422(table, client):
    body = {
        "codeGeneration": CODE_GEN_MODEL_ID,
        "codeReview": _OFF_LIST,
        "security": DEFAULT_REVIEW_MODEL_ID,
    }
    resp = client.put("/model-config", json=body, headers=_PM)
    assert resp.status_code == 422
    # Nothing persisted for that persona.
    assert "Item" not in table.get_item(Key={"personaId": "pm"})


def test_put_off_list_security_is_422(table, client):
    body = {
        "codeGeneration": CODE_GEN_MODEL_ID,
        "codeReview": DEFAULT_REVIEW_MODEL_ID,
        "security": _OFF_LIST,
    }
    resp = client.put("/model-config", json=body, headers=_PM)
    assert resp.status_code == 422


def test_put_wrong_code_gen_is_422(table, client):
    # codeGeneration is fixed this slice (FR-12); any other id -> 422.
    body = {
        "codeGeneration": _ALT_REVIEW,
        "codeReview": DEFAULT_REVIEW_MODEL_ID,
        "security": DEFAULT_REVIEW_MODEL_ID,
    }
    resp = client.put("/model-config", json=body, headers=_PM)
    assert resp.status_code == 422


def test_put_dynamodb_error_returns_502(client):
    body = {
        "codeGeneration": CODE_GEN_MODEL_ID,
        "codeReview": DEFAULT_REVIEW_MODEL_ID,
        "security": DEFAULT_REVIEW_MODEL_ID,
    }
    with mock_aws():
        model_config._table = None  # no table created -> PutItem raises
        resp = client.put("/model-config", json=body, headers=_PM)
        model_config._table = None
    assert resp.status_code == 502
