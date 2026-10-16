"""Unit tests for the shared router and the lazy-seed store."""

from common.dynamo_store import Store
from common.router import Request, Router

from tests.conftest import body_of, make_apigw_event, make_event


def _echo(request):
    from common.responses import json_response

    return json_response(200, {"path_params": request.path_params, "query": request.query})


def _build_router():
    router = Router()
    router.add("GET", "/repos/{repo_id}/pulls/{pr_number}", _echo, int_params={"pr_number"})
    router.add("GET", "/repos/{repo_id}", _echo)
    router.add("POST", "/repos", _echo)
    return router


def test_path_param_extraction():
    router = _build_router()
    resp = router.dispatch(make_event("GET", "/repos/repo-1"))
    assert resp["statusCode"] == 200
    assert body_of(resp)["path_params"] == {"repo_id": "repo-1"}


def test_int_coercion_ok():
    router = _build_router()
    resp = router.dispatch(make_event("GET", "/repos/repo-1/pulls/142"))
    assert resp["statusCode"] == 200
    assert body_of(resp)["path_params"] == {"repo_id": "repo-1", "pr_number": 142}


def test_int_coercion_bad_value_422():
    router = _build_router()
    resp = router.dispatch(make_event("GET", "/repos/repo-1/pulls/not-an-int"))
    assert resp["statusCode"] == 422


def test_unmatched_route_404():
    router = _build_router()
    resp = router.dispatch(make_event("GET", "/nope/here"))
    assert resp["statusCode"] == 404
    assert body_of(resp)["detail"] == "Not found"


def test_matched_path_wrong_verb_404():
    router = _build_router()
    resp = router.dispatch(make_event("DELETE", "/repos/repo-1"))
    assert resp["statusCode"] == 404


def test_malformed_json_body_400():
    router = _build_router()
    event = make_event("POST", "/repos")
    event["body"] = "{not valid json"
    resp = router.dispatch(event)
    assert resp["statusCode"] == 400
    assert body_of(resp)["detail"] == "Invalid JSON body"


def test_function_url_query_parsing():
    router = _build_router()
    resp = router.dispatch(make_event("GET", "/repos/repo-1", query={"status": "open"}))
    assert body_of(resp)["query"] == {"status": "open"}


def test_apigw_fallback_shape():
    router = _build_router()
    resp = router.dispatch(make_apigw_event("GET", "/repos/repo-1", query={"status": "open"}))
    assert resp["statusCode"] == 200
    decoded = body_of(resp)
    assert decoded["path_params"] == {"repo_id": "repo-1"}
    assert decoded["query"] == {"status": "open"}


def test_request_dataclass_defaults():
    request = Request(method="GET", path="/x")
    assert request.path_params == {}
    assert request.query == {}
    assert request.headers == {}
    assert request.json_body is None


# --- Lazy-seed store behavior ---

def _seed_items():
    yield {"pk": "WIDGET", "sk": "w-1", "record": {"id": "w-1", "name": "one"}}
    yield {"pk": "WIDGET", "sk": "w-2", "record": {"id": "w-2", "name": "two"}}


def test_lazy_seed_seeds_once(dynamo_table):
    store = Store(dynamo_table, seed_items=_seed_items)
    store.ensure_seeded()
    assert store.count("WIDGET") == 2
    assert store.get("WIDGET", "w-1") == {"id": "w-1", "name": "one"}

    # A second, fresh Store over the same table must NOT double-seed.
    store2 = Store(dynamo_table, seed_items=_seed_items)
    store2.ensure_seeded()
    assert store2.count("WIDGET") == 2


def test_store_put_get_delete_roundtrip(dynamo_table):
    store = Store(dynamo_table)
    store.put("WIDGET", "w-9", {"id": "w-9"})
    assert store.get("WIDGET", "w-9") == {"id": "w-9"}
    assert store.exists("WIDGET", "w-9") is True
    store.delete("WIDGET", "w-9")
    assert store.get("WIDGET", "w-9") is None
    assert store.exists("WIDGET", "w-9") is False
