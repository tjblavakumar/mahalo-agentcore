"""Handler tests for the Confluence mock Lambda."""

import importlib

import pytest

from tests.conftest import body_of, make_event

TOKEN = "mock-confluence-token-12345"


@pytest.fixture
def handler(dynamo_table, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", dynamo_table)
    monkeypatch.setenv("MOCK_CONFLUENCE_TOKEN", TOKEN)
    import confluence.handler as h

    importlib.reload(h)
    h._store = None
    h._router = None
    return h


def invoke(handler, method, path, **kwargs):
    return handler.lambda_handler(make_event(method, path, **kwargs), None)


def test_health_no_token(handler):
    resp = invoke(handler, "GET", "/health")
    assert resp["statusCode"] == 200
    assert body_of(resp)["service"] == "mock-confluence"


def test_auth_401(handler):
    resp = invoke(handler, "GET", "/spaces")
    assert resp["statusCode"] == 401


def test_list_spaces(handler):
    resp = invoke(handler, "GET", "/spaces", token=TOKEN)
    ids = {s["id"] for s in body_of(resp)["spaces"]}
    assert {"ENG", "SEC", "PROD", "API"} == ids


def test_get_space_404(handler):
    resp = invoke(handler, "GET", "/spaces/NOPE", token=TOKEN)
    assert resp["statusCode"] == 404
    assert body_of(resp)["detail"] == "Space not found"


def test_list_pages_summary_only(handler):
    resp = invoke(handler, "GET", "/pages", query={"space_id": "ENG"}, token=TOKEN)
    body = body_of(resp)
    assert body["total"] == 5
    for p in body["pages"]:
        assert "content" not in p
        assert set(p.keys()) == {"id", "title", "author", "last_updated", "space_id"}


def test_get_page_full_content(handler):
    resp = invoke(handler, "GET", "/pages/ENG-001", token=TOKEN)
    assert resp["statusCode"] == 200
    page = body_of(resp)
    assert "content" in page
    assert page["title"].startswith("ADR-001")


def test_get_page_404(handler):
    resp = invoke(handler, "GET", "/pages/NOPE-999", token=TOKEN)
    assert resp["statusCode"] == 404
    assert body_of(resp)["detail"] == "Page not found"


def test_search_missing_q_422(handler):
    resp = invoke(handler, "GET", "/search", token=TOKEN)
    assert resp["statusCode"] == 422
    assert body_of(resp)["detail"] == "Field 'q' is required"


def test_search_title_relevance(handler):
    resp = invoke(handler, "GET", "/search", query={"q": "Microservices"}, token=TOKEN)
    assert resp["statusCode"] == 200
    body = body_of(resp)
    assert body["query"] == "Microservices"
    assert body["total"] >= 1
    # Title hit on ENG-001 -> relevance 1.0; results sorted desc by relevance.
    assert body["results"][0]["relevance"] == 1.0
    assert "excerpt" in body["results"][0]


def test_create_page_read_after_write(handler):
    resp = invoke(
        handler,
        "POST",
        "/spaces/ENG/pages",
        token=TOKEN,
        body={"title": "Runbook", "content": "steps"},
    )
    assert resp["statusCode"] == 201
    created = body_of(resp)
    # 14 seed pages -> count-based fallback id, uppercased.
    assert created["id"] == "ENG-015"
    assert created["author"] == "System"

    read = invoke(handler, "GET", "/pages/ENG-015", token=TOKEN)
    assert read["statusCode"] == 200
    assert body_of(read)["content"] == "steps"


def test_create_page_unknown_space_404(handler):
    resp = invoke(handler, "POST", "/spaces/NOPE/pages", token=TOKEN, body={"title": "x"})
    assert resp["statusCode"] == 404
    assert body_of(resp)["detail"] == "Space not found"


def test_create_space_409(handler):
    resp = invoke(handler, "POST", "/spaces", token=TOKEN, body={"id": "eng"})
    assert resp["statusCode"] == 409
    assert body_of(resp)["detail"] == "Space already exists"
