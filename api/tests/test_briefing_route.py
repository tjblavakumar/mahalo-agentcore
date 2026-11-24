"""GET /briefing route: persona selection, upstream failures, cache, read-only, no agent imports."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import time
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.briefing import service, sources
from app.main import app
from app.routers import viewers
from tests.briefing_data import NOW, make_raw

_HOSTS = {
    "jira.example.test": "Jira",
    "snow.example.test": "ServiceNow",
    "conf.example.test": "Confluence",
    "git.example.test": "Git",
}
_TOKENS = {"JIRA": "tok-jira", "SERVICENOW": "tok-snow", "CONFLUENCE": "tok-conf", "GITHUB": "tok-git"}


class _Resp:
    def __init__(self, body: bytes, status: int = 200):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Upstream:
    """Serves the fixture records by URL and records every request."""

    def __init__(self):
        self.raw = make_raw()
        self.requests = []
        self.down: set[str] = set()
        self.not_found: set[str] = set()
        self.delay: dict[str, float] = {}

    def __call__(self, req, timeout):
        self.requests.append(req)
        host = req.full_url.split("/")[2]
        system = _HOSTS[host]
        path = "/" + req.full_url.split("/", 3)[3]
        if self.delay.get(system):
            time.sleep(self.delay[system])
        if system in self.down:
            raise urllib.error.URLError("down")
        if system == "Jira" and path.startswith("/activity") and "Jira-activity" in self.not_found:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b"{}"))
        return _Resp(json.dumps(self._payload(system, path)).encode())

    def _payload(self, system, path):
        raw = self.raw
        route = path.split("?")[0]
        if route == "/stories":
            return {"stories": raw["stories"]}
        if route == "/activity":
            return {"activity": raw["activity"]}
        if route == "/developers":
            return {"developers": raw["developers"]}
        if route == "/projects":
            return {"projects": raw["projects"]}
        if route.startswith("/sprints/"):
            pid = route.rsplit("/", 1)[1]
            return {"sprints": [s for s in raw["sprints"] if s["project_id"] == pid]}
        if route == "/incidents":
            return {"incidents": raw["incidents"]}
        if route == "/deployments":
            return {"deployments": raw["deployments"]}
        if route == "/cicd/runs":
            return {"runs": raw["runs"]}
        if route == "/pages":
            return {"pages": raw["pages"]}
        if route == "/pulls":
            return {"pull_requests": raw["pulls"]}
        if route.startswith("/repos/") and route.endswith("/commits"):
            return {"commits": raw["commits"].get(route.split("/")[2], [])}
        raise AssertionError(f"unexpected upstream path {path}")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for system, host in (("JIRA", "jira"), ("SERVICENOW", "snow"), ("CONFLUENCE", "conf"), ("GITHUB", "git")):
        monkeypatch.setenv(f"MAHALO_{system}_URL", f"https://{host}.example.test/")
        monkeypatch.setenv(f"MAHALO_{system}_TOKEN", _TOKENS[system])
    sources.clear_cache()
    yield
    sources.clear_cache()


@pytest.fixture
def upstream(monkeypatch):
    up = Upstream()
    monkeypatch.setattr(viewers, "_urlopen", up)

    class _Clock:
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(service, "datetime", _Clock)
    return up


@pytest.fixture
def client():
    return TestClient(app)


def _get(client, persona=None):
    headers = {"X-Mahalo-Persona": persona} if persona else {}
    return client.get("/briefing", headers=headers)


def test_header_selects_persona_and_unknown_falls_back_to_dev(client, upstream):
    tops = {}
    for persona in ("pm", "dev", "exec", "arch"):
        resp = _get(client, persona)
        assert resp.status_code == 200
        body = resp.json()
        assert body["persona"] == persona
        assert len(body["top"]) <= 5
        tops[persona] = [i["id"] for i in body["top"]]
    assert len({tuple(v) for v in tops.values()}) == 4
    for odd in (None, "nobody", ""):
        resp = _get(client, odd)
        assert resp.status_code == 200 and resp.json()["persona"] == "dev"


def test_response_shape(client, upstream):
    body = _get(client, "dev").json()
    assert set(body) == {"persona", "generated_at", "mode", "headline", "counts", "top", "items",
                         "earlier", "snapshot", "unavailable", "labels"}
    assert body["unavailable"] == []
    assert body["generated_at"] == "2026-11-24T22:30:00Z"


def test_one_source_down_gives_200_with_unavailable(client, upstream):
    upstream.down.add("Confluence")
    body = _get(client, "arch").json()
    assert body["unavailable"] == ["Confluence"]
    assert all(i["system"] != "Confluence" for i in body["items"])
    assert body["items"]


def test_git_not_configured_is_unavailable(client, upstream, monkeypatch):
    monkeypatch.delenv("MAHALO_GITHUB_URL")
    body = _get(client, "exec").json()
    assert body["unavailable"] == ["Git"]
    assert all(i["system"] != "Git" for i in body["items"])
    assert not any("git.example.test" in r.full_url for r in upstream.requests)


def test_jira_activity_404_is_tolerated(client, upstream):
    upstream.not_found.add("Jira-activity")
    body = _get(client, "dev").json()
    assert body["unavailable"] == []
    assert all(i["kind"] != "assigned" for i in body["items"])


def test_all_sources_down_returns_502(client, upstream):
    upstream.down.update({"Jira", "ServiceNow", "Confluence", "Git"})
    resp = _get(client, "dev")
    assert resp.status_code == 502
    assert resp.json() == {"detail": "Briefing unavailable"}


def test_all_requests_are_get_and_token_never_leaks(client, upstream):
    resp = _get(client, "arch")
    assert upstream.requests
    assert {r.get_method() for r in upstream.requests} == {"GET"}
    assert all(r.data is None for r in upstream.requests)
    for token in _TOKENS.values():
        assert token not in resp.text
    assert "example.test/p/" in resp.text  # https PR url is passed through
    assert "tok-" not in json.dumps(resp.json())


def test_cache_hit_ttl_and_partial_ttl(client, upstream, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(sources, "_monotonic", lambda: clock["t"])
    _get(client, "dev")
    calls = len(upstream.requests)
    assert calls == 19  # Jira 9, ServiceNow 3, Confluence 1, Git 6
    _get(client, "pm")
    _get(client, "arch")
    assert len(upstream.requests) == calls  # four personas share one refresh
    clock["t"] += 59
    _get(client, "exec")
    assert len(upstream.requests) == calls
    clock["t"] += 2  # past the 60 s TTL
    _get(client, "dev")
    assert len(upstream.requests) == 2 * calls
    # a partial snapshot is cached for only 10 s
    upstream.down.add("Git")
    sources.clear_cache()
    before = len(upstream.requests)
    _get(client, "dev")
    after_first = len(upstream.requests)
    assert after_first > before
    clock["t"] += 9
    _get(client, "dev")
    assert len(upstream.requests) == after_first
    clock["t"] += 2
    _get(client, "dev")
    assert len(upstream.requests) > after_first


def test_slow_upstream_hits_deadline_and_is_reported_unavailable(client, upstream, monkeypatch):
    monkeypatch.setattr(sources, "DEADLINE_SECONDS", 0.3)
    upstream.delay["Confluence"] = 2.0
    started = time.monotonic()
    body = _get(client, "arch").json()
    assert time.monotonic() - started < 1.5
    assert body["unavailable"] == ["Confluence"]
    assert body["items"]


def test_only_get_is_allowed(client, upstream):
    for method in ("post", "put", "delete", "patch"):
        assert getattr(client, method)("/briefing").status_code == 405


def test_importing_the_api_loads_no_agent_framework():
    code = (
        "import sys, app.main;"
        "bad=[m for m in sys.modules if m.split('.')[0] in ('agent','strands','langchain','langgraph')];"
        "print(bad)"
    )
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"
