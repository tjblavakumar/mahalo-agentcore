"""Gateway Lambda-target -> in-Lambda ``Router`` adapter (Task 4, Decision E).

A Gateway Lambda-target invocation is NOT an HTTP event: the ``event`` is a flat
map of the tool's input args and the tool name arrives on
``context.client_context.custom['bedrockAgentCoreToolName']`` as
``"<targetName>___<toolName>"``. The existing ``Router`` only understands
Function-URL/API-Gateway HTTP events, so this adapter bridges the two:

1. strip the ``___`` target prefix to the bare tool name;
2. look the operation up in ``common.tool_schemas`` (the one source of truth);
3. for a composite, call the service handler (server-side orchestration);
4. otherwise build a synthetic Function-URL-v2 request from ``arg_mapping``
   (path / query / body), inject the service token so the frozen
   ``require_token`` check passes, dispatch through the ``Router``;
5. unwrap the ``{statusCode, body}`` envelope: on ``statusCode in (200, 201)``
   return the parsed JSON body (what DIRECT mode's ``make_request`` parses);
   otherwise return ``{"error": "Request failed with status <code>: <body>"}``
   — byte-identical to ``agent/tools/http.py::make_request`` for the same body.

The adapter never raises for an expected failure; it returns a JSON error object
so the Gateway sees a well-formed tool result (e.g. a GitHub 409 "already
exists" surfaces the same way DIRECT mode's ``{"error": ...}`` dict does).
"""

from __future__ import annotations

import importlib
import json
import logging
from typing import Any, Dict

from common import tool_schemas
from common.assignee import resolve_assignee
from common.gateway_dispatch import dispatch, get_json

logger = logging.getLogger()


def bare_name(tool_name: str) -> str:
    """Strip Gateway's ``<target>___<tool>`` prefix (no-op for a bare name)."""
    return tool_name.rsplit("___", 1)[-1]


def _error(status: Any, raw_body: str) -> Dict[str, Any]:
    """The DIRECT-equivalent error object (matches ``make_request`` verbatim)."""
    return {"error": f"Request failed with status {status}: {raw_body}"}


def _resolve_update_assignee(router, token, value: Any) -> Any:
    """Resolve a name->dev-id for ``jira_update_story`` (same as DIRECT mode)."""
    data = get_json(router, token, "/developers")
    developers = data.get("developers", []) if isinstance(data, dict) else []
    return resolve_assignee(value, developers)


def handle(tool_name: str, store, router, event: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Map a Gateway tool call to the ``Router`` and return plain JSON."""
    name = bare_name(tool_name)
    descriptor = tool_schemas.BY_NAME.get(name)
    if descriptor is None:
        logger.warning("Unknown Gateway tool: %s", name)
        return {"error": f"Unknown tool: {name}"}

    args = dict(event or {})

    # Composite: hand off to the service's server-side orchestration.
    composite = descriptor.get("composite")
    if composite:
        module_name, func_name = composite.rsplit(".", 1)
        try:
            module = importlib.import_module(module_name)
            func = getattr(module, func_name)
            return func(store, router, token, args)
        except Exception:  # pragma: no cover - defensive; real errors logged
            logger.exception("Composite %s failed", composite)
            return {"error": "Internal error"}

    method = descriptor["method"]
    path_template = descriptor["path_template"]
    arg_mapping = descriptor["arg_mapping"]

    path_values: Dict[str, str] = {}
    query: Dict[str, Any] = {}
    body: Dict[str, Any] = {}

    for arg_name, spec in arg_mapping.items():
        if arg_name not in args:
            continue
        value = args[arg_name]
        location = spec["in"]
        wire_name = spec["name"]
        if location == "path":
            if value in (None, ""):
                return {"error": f"Missing required argument '{arg_name}'"}
            path_values[wire_name] = value
        elif location == "query":
            if value is not None:
                query[wire_name] = value
        elif location == "body":
            # Only send provided (non-None) fields — preserves the DIRECT-mode
            # "changed fields only" semantics for jira_update_story and avoids
            # overwriting optional fields elsewhere.
            if value is None:
                continue
            if spec.get("resolve_assignee"):
                resolved = _resolve_update_assignee(router, token, value)
                if not resolved:
                    # DIRECT mode refuses the update on an unresolved name
                    # rather than writing a null assignee.
                    return {"error": f"Could not resolve assignee '{value}'."}
                value = resolved
            body[wire_name] = value

    # Fill the path template; any unfilled required segment is a missing arg.
    try:
        path = path_template.format(**path_values)
    except KeyError as exc:
        return {"error": f"Missing required argument {exc}"}

    result = dispatch(
        router,
        token,
        method,
        path,
        query=query or None,
        body=body if method in ("POST", "PUT") else None,
    )

    status = result.get("statusCode")
    raw_body = result.get("body", "")
    if status in (200, 201):
        return json.loads(raw_body) if raw_body else {}
    return _error(status, raw_body)
