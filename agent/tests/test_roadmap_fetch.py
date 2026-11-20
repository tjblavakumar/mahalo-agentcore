"""Roadmap source fetch: Gateway (fake MCP client) and Direct (patched HTTP)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent import roadmap, roadmap_fetch

FULL = {
    "jira_get_sprint_info": "jira___jira_get_sprint_info",
    "jira_search_stories": "jira___jira_search_stories",
    "jira_list_developers": "jira___jira_list_developers",
    "servicenow_list_incidents": "servicenow___servicenow_list_incidents",
    "servicenow_list_deployments": "servicenow___servicenow_list_deployments",
}
PAYLOADS = {
    "jira_get_sprint_info": {"sprints": [{"id": "PAY-S1"}]},
    "jira_search_stories": {"stories": [{"id": "PAY-1"}], "total": 1},
    "jira_list_developers": {"developers": [{"id": "dev-1"}]},
    "servicenow_list_incidents": {"incidents": [{"id": "INC-1"}]},
    "servicenow_list_deployments": {"deployments": [{"id": "DEP-1"}]},
}
FIXED = "Roadmap could not be computed: {} could not be read. Nothing was changed. Try again."


def ok(payload):
    return {"status": "success", "toolUseId": "x", "content": [{"text": json.dumps(payload)}]}


class FakeClient:
    def __init__(self, results=None, *, tools=None, start_error=None, call_error=None, list_error=None):
        self.results = results or {n: ok(p) for n, p in PAYLOADS.items()}
        self.tools = FULL if tools is None else tools
        self.start_error, self.call_error, self.list_error = start_error, call_error, list_error
        self.calls, self.started, self.stopped = [], False, 0

    def start(self):
        self.started = True
        if self.start_error:
            raise self.start_error
        return self

    def stop(self, *a):
        self.stopped += 1

    def list_tools_sync(self, pagination_token=None):
        if self.list_error:
            raise self.list_error
        page = [SimpleNamespace(tool_name=full) for full in self.tools.values()]
        return _Page(page)

    def call_tool_sync(self, tool_use_id, name, arguments=None, **kw):
        self.calls.append((tool_use_id, name, arguments))
        if self.call_error:
            raise self.call_error
        bare = name.rsplit("___", 1)[-1]
        return self.results[bare]


class _Page(list):
    pagination_token = None


def _run(client, monkeypatch, project="PAY"):
    monkeypatch.setattr(roadmap_fetch.gateway_client, "_build_gateway_mcp_client", lambda: client)
    return roadmap_fetch.GatewayFetcher().fetch(project)


def test_success_all_five_in_order_with_full_names(monkeypatch):
    client = FakeClient()
    sources, calls = _run(client, monkeypatch)
    assert calls == 5
    assert sources == {
        "sprints": [{"id": "PAY-S1"}], "stories": [{"id": "PAY-1"}],
        "developers": [{"id": "dev-1"}], "incidents": [{"id": "INC-1"}],
        "deployments": [{"id": "DEP-1"}],
    }
    assert [c[1] for c in client.calls] == list(FULL.values())
    assert [c[2] for c in client.calls] == [
        {"project_id": "PAY"}, {"project_id": "PAY"}, {},
        {"service": "payment-service"}, {"service": "payment-service"},
    ]
    assert client.stopped == 1


def test_cart_uses_cart_service(monkeypatch):
    client = FakeClient()
    _run(client, monkeypatch, "CART")
    assert client.calls[3][2] == {"service": "cart-service"}


def _bad(result):
    results = {n: ok(p) for n, p in PAYLOADS.items()}
    results["servicenow_list_incidents"] = result
    return FakeClient(results)


@pytest.mark.parametrize(
    "client,source,calls",
    [
        (_bad({"status": "error", "toolUseId": "x", "content": [{"text": "boom"}]}), "ServiceNow incidents", 4),
        (_bad({"status": "success", "isError": True, "content": [{"text": "{}"}]}), "ServiceNow incidents", 4),
        (_bad({"status": "success", "content": []}), "ServiceNow incidents", 4),
        (_bad({"status": "success", "content": [{"image": "x"}]}), "ServiceNow incidents", 4),
        (_bad({"status": "success", "content": [{"text": "not json"}]}), "ServiceNow incidents", 4),
        (_bad(ok(["a list"])), "ServiceNow incidents", 4),
        (_bad(ok({"error": "nope"})), "ServiceNow incidents", 4),
        (_bad(ok({"other": []})), "ServiceNow incidents", 4),
        (_bad(ok({"incidents": ["not a dict"]})), "ServiceNow incidents", 4),
        (FakeClient(call_error=TimeoutError("slow")), "Jira sprints", 1),
        (FakeClient(tools={k: v for k, v in FULL.items() if k != "jira_list_developers"}), "Jira developers", 2),
        (FakeClient(list_error=RuntimeError("down")), "Jira sprints", 0),
        (FakeClient(start_error=RuntimeError("no start")), "Jira sprints", 0),
    ],
)
def test_failures_map_to_fixed_message_and_stop_client(monkeypatch, client, source, calls):
    with pytest.raises(roadmap.PlanUnavailable) as e:
        _run(client, monkeypatch)
    assert e.value.message == FIXED.format(source)
    assert e.value.calls == calls
    assert client.stopped == 1


def test_stop_called_when_build_fails_is_not_needed(monkeypatch):
    def boom():
        raise ValueError("no url")

    monkeypatch.setattr(roadmap_fetch.gateway_client, "_build_gateway_mcp_client", boom)
    with pytest.raises(roadmap.PlanUnavailable) as e:
        roadmap_fetch.GatewayFetcher().fetch("PAY")
    assert e.value.message == FIXED.format("Jira sprints")


def test_log_has_no_payload(monkeypatch, caplog):
    client = _bad(ok({"error": "secret-token-123"}))
    with caplog.at_level("WARNING"):
        with pytest.raises(roadmap.PlanUnavailable):
            _run(client, monkeypatch)
    assert "secret-token-123" not in caplog.text
    assert "ServiceNow incidents" in caplog.text and "ErrorPayload" in caplog.text


# --- direct ------------------------------------------------------------------- #


def test_direct_success_and_routes(monkeypatch):
    seen = []

    def fake(base, token, endpoint="", params=None, **kw):
        seen.append((endpoint, params))
        key = {"/sprints/PAY": "sprints", "/projects/PAY/stories": "stories",
               "/developers": "developers", "/incidents": "incidents",
               "/deployments": "deployments"}[endpoint]
        return {key: [{"id": key}]}

    monkeypatch.setattr(roadmap_fetch, "make_request", fake)
    sources, calls = roadmap_fetch.DirectFetcher().fetch("PAY")
    assert calls == 5 and set(sources) == {"sprints", "stories", "developers", "incidents", "deployments"}
    assert seen[3] == ("/incidents", {"service": "payment-service"})
    assert seen[4] == ("/deployments", {"service": "payment-service"})


@pytest.mark.parametrize("bad", [{"error": "Request failed with status 500: x"}, {"sprints": "no"}, []])
def test_direct_failure(monkeypatch, bad):
    monkeypatch.setattr(roadmap_fetch, "make_request", lambda *a, **k: bad)
    with pytest.raises(roadmap.PlanUnavailable) as e:
        roadmap_fetch.DirectFetcher().fetch("PAY")
    assert e.value.message == FIXED.format("Jira sprints") and e.value.calls == 1


def test_direct_exception(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(roadmap_fetch, "make_request", boom)
    with pytest.raises(roadmap.PlanUnavailable):
        roadmap_fetch.DirectFetcher().fetch("PAY")


def test_fetch_sources_picks_by_tool_mode(monkeypatch):
    chosen = []
    monkeypatch.setattr(roadmap_fetch.GatewayFetcher, "fetch", lambda self, p: chosen.append("gw") or ({}, 5))
    monkeypatch.setattr(roadmap_fetch.DirectFetcher, "fetch", lambda self, p: chosen.append("direct") or ({}, 5))
    monkeypatch.setattr(roadmap_fetch, "settings", SimpleNamespace(tool_mode="gateway"))
    roadmap_fetch.fetch_sources("PAY")
    monkeypatch.setattr(roadmap_fetch, "settings", SimpleNamespace(tool_mode="direct"))
    roadmap_fetch.fetch_sources("PAY")
    assert chosen == ["gw", "direct"]
