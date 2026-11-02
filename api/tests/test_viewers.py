"""Tests for the read-only viewer proxy + refresh endpoint (upstream HTTP mocked)."""
from __future__ import annotations

import io
import json
import urllib.error

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.main import app
from app.routers import dashboard, viewers

_TABLE = "mahalo-dashboards"
_URLS = {
    "jira": "https://jira.example.test",
    "confluence": "https://conf.example.test",
    "servicenow": "https://snow.example.test",
}
_TOKENS = {"jira": "tok-jira", "confluence": "tok-conf", "servicenow": "tok-snow"}


class _Resp:
    def __init__(self, status=200, body=b"{}"):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Upstream:
    """Records outbound requests and replays a scripted reply."""

    def __init__(self):
        self.calls = []
        self.handler = lambda req: _Resp(200, b'{"ok": true}')

    def __call__(self, req, timeout):
        self.calls.append((req, timeout))
        return self.handler(req)


@pytest.fixture
def upstream(monkeypatch):
    up = Upstream()
    monkeypatch.setattr(viewers, "_urlopen", up)
    return up


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k, v in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SECURITY_TOKEN": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
        "MAHALO_DASHBOARD_TABLE": _TABLE,
    }.items():
        monkeypatch.setenv(k, v)
    for s in viewers.SYSTEMS:
        monkeypatch.setenv(f"MAHALO_{s.upper()}_URL", _URLS[s] + "/")  # trailing slash stripped
        monkeypatch.setenv(f"MAHALO_{s.upper()}_TOKEN", _TOKENS[s])


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def table():
    with mock_aws():
        c = boto3.client("dynamodb", region_name="us-east-1")
        c.create_table(
            TableName=_TABLE,
            KeySchema=[{"AttributeName": "personaId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "personaId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        dashboard._table = None
        yield boto3.resource("dynamodb", region_name="us-east-1").Table(_TABLE)
        dashboard._table = None


# --- proxy: allow-list -----------------------------------------------------

@pytest.mark.parametrize(
    "system,path",
    [
        ("jira", "projects"), ("jira", "projects/PAY"), ("jira", "projects/PAY/board"),
        ("jira", "projects/PAY/stories"), ("jira", "stories"), ("jira", "stories/CART-205"),
        ("jira", "sprints/PAY"), ("jira", "developers"),
        ("confluence", "spaces"), ("confluence", "spaces/ENG"), ("confluence", "spaces/ENG/pages"),
        ("confluence", "pages"), ("confluence", "pages/p-1"), ("confluence", "search"),
        ("servicenow", "services"), ("servicenow", "deployments"), ("servicenow", "deployments/d-1"),
        ("servicenow", "incidents"), ("servicenow", "incidents/INC1"), ("servicenow", "stats"),
    ],
)
def test_allowed_paths_reach_upstream(client, upstream, system, path):
    r = client.get(f"/view/{system}/{path}")
    assert r.status_code == 200 and r.json() == {"ok": True}
    req, timeout = upstream.calls[0]
    assert req.full_url == f"{_URLS[system]}/{path}"
    assert req.get_method() == "GET"
    assert timeout == 10


@pytest.mark.parametrize(
    "system,path",
    [
        ("jira", "admin/reset"), ("jira", "../x"), ("jira", "%2e%2e/x"), ("jira", "projects/../admin/reset"),
        ("jira", "projects/%2e%2e"), ("jira", "projects/PAY/board/extra"), ("jira", "health"),
        ("jira", ""), ("jira", "projects/"), ("jira", "projects//board"), ("jira", "projects/P%2FAY"),
        ("jira", "sprints"), ("confluence", "admin/reset"), ("confluence", "spaces/ENG/pages/x"),
        ("servicenow", "admin/reset"), ("servicenow", "stats/x"),
        ("github", "repos"), ("unknown", "projects"),
    ],
)
def test_rejected_paths_never_call_upstream(client, upstream, system, path):
    r = client.get(f"/view/{system}/{path}")
    assert r.status_code in (404, 405)
    assert upstream.calls == []


@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_non_get_verbs_rejected(client, upstream, method):
    r = getattr(client, method)("/view/jira/stories")
    assert r.status_code in (404, 405)
    assert upstream.calls == []


def test_query_string_passthrough(client, upstream):
    client.get("/view/jira/stories?project_id=CART&status=todo")
    req, _ = upstream.calls[0]
    assert req.full_url == f"{_URLS['jira']}/stories?project_id=CART&status=todo"


def test_token_added_and_client_headers_not_forwarded(client, upstream):
    client.get(
        "/view/jira/projects",
        headers={
            "X-Mahalo-Persona": "pm",
            "Authorization": "Bearer secret",
            "Cookie": "a=b",
            "X-API-Token": "client-supplied",
        },
    )
    req, _ = upstream.calls[0]
    headers = {k.lower(): v for k, v in req.header_items()}
    assert headers == {"x-api-token": "tok-jira"}


def test_upstream_404_passed_through(client, upstream):
    def boom(req):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b'{"detail":"Story not found"}'))

    upstream.handler = boom
    r = client.get("/view/jira/stories/CART-999")
    assert r.status_code == 404 and r.json() == {"detail": "Story not found"}


@pytest.mark.parametrize(
    "exc",
    [
        urllib.error.URLError("down"),
        TimeoutError("slow"),
        urllib.error.HTTPError("u", 500, "err", {}, io.BytesIO(b"x")),
        urllib.error.HTTPError("u", 401, "bad token", {}, io.BytesIO(b"x")),
    ],
)
def test_upstream_failure_is_502(client, upstream, exc):
    def boom(req):
        raise exc

    upstream.handler = boom
    r = client.get("/view/jira/projects")
    assert r.status_code == 502
    assert "tok-jira" not in r.text


def test_missing_config_is_503(client, upstream, monkeypatch):
    monkeypatch.delenv("MAHALO_JIRA_URL")
    r = client.get("/view/jira/projects")
    assert r.status_code == 503 and "not configured" in r.json()["detail"]
    assert upstream.calls == []
    monkeypatch.setenv("MAHALO_JIRA_URL", _URLS["jira"])
    monkeypatch.delenv("MAHALO_JIRA_TOKEN")
    assert client.get("/view/jira/projects").status_code == 503


# --- refresh ---------------------------------------------------------------

def _reset_reply(req):
    svc = next(s for s, u in _URLS.items() if req.full_url.startswith(u))
    return _Resp(200, json.dumps({"status": "ok", "service": svc, "counts": {"X": 1}, "shift_days": 14}).encode())


def test_refresh_ok_then_cooldown_then_ok_after_window(client, upstream, table, monkeypatch):
    upstream.handler = _reset_reply
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(viewers.time, "time", lambda: clock["t"])

    r = client.post("/admin/refresh-demo-data")
    assert r.status_code == 200
    body = r.json()
    assert set(body["results"]) == {"jira", "confluence", "servicenow"}
    for s in body["results"].values():
        assert s == {"ok": True, "counts": {"X": 1}, "shift_days": 14}
    assert body["refreshed_at"]
    assert sorted(c[0].full_url for c in upstream.calls) == sorted(f"{u}/admin/reset" for u in _URLS.values())
    assert all(c[0].get_method() == "POST" for c in upstream.calls)
    assert {dict(c[0].header_items())["X-api-token"] for c in upstream.calls} == set(_TOKENS.values())

    n = len(upstream.calls)
    clock["t"] += 20
    r2 = client.post("/admin/refresh-demo-data")
    assert r2.status_code == 429
    assert r2.json()["retry_after_seconds"] == 40
    assert len(upstream.calls) == n

    clock["t"] += 41
    assert client.post("/admin/refresh-demo-data").status_code == 200


def test_refresh_partial_failure_still_200(client, upstream, table):
    def handler(req):
        if req.full_url.startswith(_URLS["confluence"]):
            raise urllib.error.URLError("down")
        return _reset_reply(req)

    upstream.handler = handler
    r = client.post("/admin/refresh-demo-data")
    assert r.status_code == 200
    res = r.json()["results"]
    assert res["jira"]["ok"] and res["servicenow"]["ok"]
    assert res["confluence"] == {"ok": False, "error": "confluence reset failed"}


def test_refresh_missing_config_503_and_no_cooldown_claim(client, upstream, table, monkeypatch):
    monkeypatch.delenv("MAHALO_SERVICENOW_URL")
    assert client.post("/admin/refresh-demo-data").status_code == 503
    assert upstream.calls == []
    assert "Item" not in table.get_item(Key={"personaId": "_admin_refresh"})


def test_reserved_item_not_returned_by_dashboard(client, upstream, table):
    upstream.handler = _reset_reply
    assert client.post("/admin/refresh-demo-data").status_code == 200
    for persona in ("pm", "dev", "exec"):
        r = client.get("/dashboard/widgets", headers={"X-Mahalo-Persona": persona})
        assert r.status_code == 200
        assert "lastRefreshEpoch" not in r.text
