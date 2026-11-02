"""Tests for Store.reset() and the POST /admin/reset routes."""
import importlib

import boto3
import pytest

from common.dynamo_store import Store
from tests.conftest import body_of, make_event


def _seed():
    for i in range(60):  # > 25 so the batch path flushes more than once
        yield {"pk": "THING", "sk": f"t-{i:03d}", "record": {"id": f"t-{i:03d}"}}
    yield {"pk": "OTHER", "sk": "o-1", "record": {"id": "o-1"}}


def test_reset_deletes_everything_and_reseeds(dynamo_table):
    store = Store(dynamo_table, _seed)
    store.ensure_seeded()
    store.put("THING", "agent-made", {"id": "agent-made"})
    store.put("STRAY", "s-1", {"id": "s-1"})
    for i in range(40):
        store.put("STRAY", f"bulk-{i}", {"id": i})
    store.delete("THING", "t-000")

    counts = store.reset()

    assert counts == {"THING": 60, "OTHER": 1}
    assert store.count("THING") == 60
    assert store.get("THING", "agent-made") is None
    assert store.count("STRAY") == 0
    assert store.exists("THING", "t-000")
    assert store.exists("_meta", "seeded")
    assert store._seed_checked is True
    # the scan sees exactly seed + sentinel
    table = boto3.resource("dynamodb").Table(dynamo_table)
    assert table.scan(Select="COUNT")["Count"] == 62


def test_reset_on_empty_table_seeds(dynamo_table):
    store = Store(dynamo_table, _seed)
    assert store.reset() == {"THING": 60, "OTHER": 1}
    assert store.exists("_meta", "seeded")


SERVICES = [
    ("jira", "MOCK_JIRA_TOKEN", "mock-jira-token-12345", "STORY"),
    ("confluence", "MOCK_CONFLUENCE_TOKEN", "mock-confluence-token-12345", "PAGE"),
    ("servicenow", "MOCK_SERVICENOW_TOKEN", "mock-servicenow-token-12345", "INCIDENT"),
]


@pytest.mark.parametrize("svc,env,token,pk", SERVICES)
def test_admin_reset_route(dynamo_table, monkeypatch, svc, env, token, pk):
    monkeypatch.setenv("TABLE_NAME", dynamo_table)
    monkeypatch.setenv(env, token)
    h = importlib.import_module(f"{svc}.handler")
    importlib.reload(h)
    h._store = None
    h._router = None

    def call(**kw):
        return h.lambda_handler(make_event("POST", "/admin/reset", **kw), None)

    assert call()["statusCode"] == 401
    assert call(token="wrong")["statusCode"] == 401

    h.lambda_handler(make_event("GET", "/health"), None)
    store = h._get_store() if hasattr(h, "_get_store") else h._store
    if store is None:  # prime lazily-built store through an authenticated read
        first = {"jira": "/projects", "confluence": "/spaces", "servicenow": "/services"}[svc]
        h.lambda_handler(make_event("GET", first, token=token), None)
        store = h._store
    store.put(pk, "AGENT-MADE", {"id": "AGENT-MADE"})
    assert store.exists(pk, "AGENT-MADE")

    resp = call(token=token)
    assert resp["statusCode"] == 200
    body = body_of(resp)
    assert body["status"] == "ok" and body["service"] == svc
    assert body["shift_days"] % 7 == 0
    assert body["counts"][pk] > 0
    assert not store.exists(pk, "AGENT-MADE")
