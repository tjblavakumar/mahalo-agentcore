"""A tiny path/verb router plus Lambda event normalization.

Normalizes a Lambda **Function URL v2** event (``requestContext.http.method``,
``rawPath``, ``rawQueryString``/``queryStringParameters``, base64-aware JSON
``body``) into a framework-agnostic :class:`Request`. When
``requestContext.http`` is absent it falls back to the top-level
``httpMethod``/``path``/``queryStringParameters`` shape (API Gateway /
direct-invoke), keeping the handler usable if a later task registers the
function by ARN and synthesizes a non-Function-URL event.

Routes are registered as ``(METHOD, path_template)`` where ``path_template``
supports ``{param}`` segments. Declared int params are coerced; a non-int value
yields a 422. Unmatched routes yield 404 ``{"detail": "Not found"}``; a
malformed JSON body on POST/PUT yields 400 ``{"detail": "Invalid JSON body"}``.
"""

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs

from common.responses import error

# Sentinel the handler for malformed JSON bodies.
_INVALID_JSON = object()


@dataclass
class Request:
    """A normalized HTTP request, independent of the Lambda event source."""

    method: str
    path: str
    path_params: Dict[str, Any] = field(default_factory=dict)
    query: Dict[str, str] = field(default_factory=dict)
    json_body: Any = None
    headers: Dict[str, str] = field(default_factory=dict)


def _decode_body(event: Dict[str, Any]) -> Any:
    """Return the parsed JSON body, ``None`` if empty, or the invalid sentinel."""
    raw = event.get("body")
    if raw is None or raw == "":
        return None
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except Exception:
            return _INVALID_JSON
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return _INVALID_JSON


def _parse_query(event: Dict[str, Any]) -> Dict[str, str]:
    """Build a flat query dict from either event shape."""
    params = event.get("queryStringParameters")
    if params:
        return {k: v for k, v in params.items() if v is not None}
    raw_qs = event.get("rawQueryString")
    if raw_qs:
        return {k: v[-1] for k, v in parse_qs(raw_qs, keep_blank_values=True).items()}
    return {}


def _normalize(event: Dict[str, Any]) -> Tuple[str, str, Dict[str, str], Dict[str, str], Any]:
    """Return (method, path, query, headers, body-or-sentinel) from any shape."""
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") if isinstance(request_context, dict) else None
    if http:
        method = http.get("method", "GET")
        path = event.get("rawPath") or http.get("path") or "/"
    else:
        method = event.get("httpMethod", "GET")
        path = event.get("path") or "/"
    headers = {k: v for k, v in (event.get("headers") or {}).items()}
    query = _parse_query(event)
    body = _decode_body(event)
    return method.upper(), path, query, headers, body


class Router:
    """Registers routes and dispatches normalized requests to them."""

    def __init__(self) -> None:
        # Each entry: (method, segments, int_params, handler)
        self._routes: List[Tuple[str, List[str], set, Callable]] = []

    def add(
        self,
        method: str,
        path_template: str,
        handler: Callable[[Request], Dict[str, Any]],
        int_params: Optional[set] = None,
    ) -> None:
        segments = [s for s in path_template.strip("/").split("/") if s != ""]
        self._routes.append((method.upper(), segments, set(int_params or ()), handler))

    def route(
        self, method: str, path_template: str, int_params: Optional[set] = None
    ) -> Callable:
        """Decorator form of :meth:`add`."""

        def _decorator(fn: Callable[[Request], Dict[str, Any]]) -> Callable:
            self.add(method, path_template, fn, int_params)
            return fn

        return _decorator

    @staticmethod
    def _match(
        segments: List[str], int_params: set, path_parts: List[str]
    ) -> Optional[Dict[str, Any]]:
        """Return extracted path params if the template matches, else ``None``.

        Raises :class:`ValueError` when a declared int param cannot be coerced
        (the caller maps this to a 422).
        """
        if len(segments) != len(path_parts):
            return None
        params: Dict[str, Any] = {}
        for template_seg, actual_seg in zip(segments, path_parts):
            if template_seg.startswith("{") and template_seg.endswith("}"):
                name = template_seg[1:-1]
                if name in int_params:
                    params[name] = int(actual_seg)  # may raise ValueError
                else:
                    params[name] = actual_seg
            elif template_seg != actual_seg:
                return None
        return params

    def dispatch(self, event: Dict[str, Any]) -> Dict[str, Any]:
        method, path, query, headers, body = _normalize(event)

        if body is _INVALID_JSON:
            return error(400, "Invalid JSON body")

        path_parts = [p for p in path.strip("/").split("/") if p != ""]
        matched_path = False

        for route_method, segments, int_params, handler in self._routes:
            try:
                params = self._match(segments, int_params, path_parts)
            except ValueError:
                # A declared int param failed coercion on a path-matching route.
                return error(422, "Invalid path parameter")
            if params is None:
                continue
            matched_path = True
            if route_method != method:
                continue
            request = Request(
                method=method,
                path=path,
                path_params=params,
                query=query,
                json_body=body,
                headers=headers,
            )
            return handler(request)

        # Path shape matched but no verb matched, or nothing matched at all.
        return error(404, "Not found")
