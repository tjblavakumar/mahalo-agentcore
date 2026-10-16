"""Shared helpers to call the in-Lambda ``Router`` with a synthetic request.

A Gateway Lambda-target invocation is a flat args map with no HTTP envelope, so
the Gateway adapter (and the server-side composites) must synthesize a
Function-URL-v2 event, inject the service's ``X-API-Token`` (Gateway carries no
headers; IAM is the real auth boundary, so the frozen ``require_token`` check in
``routes.py`` is satisfied with the Lambda's own token), dispatch through the
existing ``Router``, and unwrap the ``{statusCode, body}`` envelope.

Kept stdlib-only and import-safe so both ``common.gateway_adapter`` and the
service ``composites`` modules share one request-building body.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


def build_event(
    method: str,
    path: str,
    token: str,
    *,
    query: Optional[Dict[str, Any]] = None,
    body: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build a synthetic Function-URL-v2 event the ``Router`` understands."""
    clean_query = {k: v for k, v in (query or {}).items() if v is not None}
    event: Dict[str, Any] = {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": "&".join(f"{k}={v}" for k, v in clean_query.items()),
        "headers": {"x-api-token": token},
        "queryStringParameters": clean_query or None,
        "requestContext": {"http": {"method": method, "path": path}},
        "isBase64Encoded": False,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def dispatch(router, token, method, path, *, query=None, body=None) -> Dict[str, Any]:
    """Dispatch a synthetic request and return the raw ``{statusCode, body}``."""
    return router.dispatch(
        build_event(method, path, token, query=query, body=body)
    )


def get_json(router, token, path, *, query=None) -> Any:
    """GET ``path`` and return the parsed JSON body (empty dict on non-2xx).

    Used by the server-side composites, whose orchestration mirrors the agent's
    DIRECT-mode fan-out where each sub-call simply reads JSON.
    """
    result = dispatch(router, token, "GET", path, query=query)
    if result.get("statusCode") in (200, 201):
        return json.loads(result["body"])
    return {}
