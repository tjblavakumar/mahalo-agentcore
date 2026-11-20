"""Fetch the five read-only payloads the computed roadmap needs.

``fetch_sources(project)`` returns ``(sources, calls)`` where ``sources`` holds the
row lists ``{"sprints", "stories", "developers", "incidents", "deployments"}`` taken
from the route JSON, and ``calls`` is the number of calls made (for
``skill_run.tool_calls_used``). On failure the raised ``PlanUnavailable`` carries
the same count as ``.calls``.

Gateway mode (the deployed Runtime) calls the existing Gateway tools through a
short-lived MCP client. Direct mode (local dev) calls the same mock routes through
``agent.tools.http.make_request``. Calls run in a fixed order and stop at the
first failure. Any failure raises ``PlanUnavailable`` with the fixed message; the
log carries only the project, the source and the error class.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import NamedTuple, Optional

from agent import gateway_client
from agent.config import settings
from agent.roadmap import PlanUnavailable, source_unreadable_message
from agent.skills import PROJECT_SERVICE
from agent.tools.http import make_request

logger = logging.getLogger(__name__)

CALL_TIMEOUT_S = 25


class _Call(NamedTuple):
    key: str  # key in the result, also the list key in the payload
    source: str  # human name used in the fixed failure message
    tool: str  # bare Gateway / agent tool name
    args: dict
    system: str  # "jira" or "servicenow"
    route: str
    params: Optional[dict]


def _calls(project: str) -> tuple:
    service = PROJECT_SERVICE[project]
    return (
        _Call("sprints", "Jira sprints", "jira_get_sprint_info",
              {"project_id": project}, "jira", f"/sprints/{project}", None),
        _Call("stories", "Jira stories", "jira_search_stories",
              {"project_id": project}, "jira", f"/projects/{project}/stories", None),
        _Call("developers", "Jira developers", "jira_list_developers",
              {}, "jira", "/developers", None),
        _Call("incidents", "ServiceNow incidents", "servicenow_list_incidents",
              {"service": service}, "servicenow", "/incidents", {"service": service}),
        _Call("deployments", "ServiceNow deployments", "servicenow_list_deployments",
              {"service": service}, "servicenow", "/deployments", {"service": service}),
    )


def _fail(project: str, source: str, reason: str, calls: int) -> PlanUnavailable:
    logger.warning("Roadmap source unreadable project=%s source=%s error=%s", project, source, reason)
    exc = PlanUnavailable(source_unreadable_message(source))
    exc.calls = calls
    return exc


def _rows(payload, key: str) -> list:
    """The row list of a route payload, or ``ValueError(reason)``."""
    if not isinstance(payload, dict):
        raise ValueError("NotADict")
    if "error" in payload:
        raise ValueError("ErrorPayload")
    rows = payload.get(key)
    if not isinstance(rows, list):
        raise ValueError("MissingList")
    if not all(isinstance(r, dict) for r in rows):
        raise ValueError("BadRows")
    return rows


def _result_payload(result):
    """Parse the JSON text of an ``MCPToolResult``-shaped dict."""
    if not isinstance(result, dict):
        raise ValueError("BadResult")
    if result.get("status") != "success" or result.get("isError"):
        raise ValueError("ToolError")
    text = None
    for block in result.get("content") or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            text = block["text"]
            break
    if text is None:
        raise ValueError("NoText")
    try:
        return json.loads(text)
    except ValueError:
        raise ValueError("NotJson") from None


def _reason(exc: Exception) -> str:
    return str(exc) if isinstance(exc, ValueError) else type(exc).__name__


class DirectFetcher:
    """Local dev: call the mock services over HTTP."""

    def fetch(self, project: str):
        sources, count = {}, 0
        for call in _calls(project):
            if call.system == "jira":
                base, token = settings.jira_url, settings.jira_token
            else:
                base, token = settings.servicenow_url, settings.servicenow_token
            count += 1
            try:
                payload = make_request(base, token, endpoint=call.route, params=call.params)
                sources[call.key] = _rows(payload, call.key)
            except Exception as exc:  # noqa: BLE001 - mapped to the fixed message
                raise _fail(project, call.source, _reason(exc), count) from None
        return sources, count


class GatewayFetcher:
    """Deployed Runtime: call the Gateway tools through a short-lived MCP client."""

    @staticmethod
    def _resolve(client) -> dict:
        """Map each bare tool name to its full ``<target>___<tool>`` Gateway name."""
        names: dict = {}
        token = None
        for _ in range(20):  # pagination guard
            page = client.list_tools_sync(pagination_token=token) if token else client.list_tools_sync()
            for tool in page:
                full = getattr(tool, "tool_name", None)
                if isinstance(full, str):
                    names.setdefault(full.rsplit("___", 1)[-1], full)
            token = getattr(page, "pagination_token", None)
            if not token:
                break
        return names

    def fetch(self, project: str):
        calls = _calls(project)
        sources, count = {}, 0
        client = None
        try:
            try:
                client = gateway_client._build_gateway_mcp_client()
                client.start()
                names = self._resolve(client)
            except Exception as exc:  # noqa: BLE001
                raise _fail(project, calls[0].source, type(exc).__name__, count) from None
            for n, call in enumerate(calls, start=1):
                full = names.get(call.tool)
                if full is None:
                    raise _fail(project, call.source, "ToolNotFound", count)
                count += 1
                try:
                    result = client.call_tool_sync(
                        f"roadmap-{n}", full, call.args,
                        read_timeout_seconds=timedelta(seconds=CALL_TIMEOUT_S),
                    )
                    sources[call.key] = _rows(_result_payload(result), call.key)
                except Exception as exc:  # noqa: BLE001
                    raise _fail(project, call.source, _reason(exc), count) from None
        finally:
            if client is not None:
                try:
                    client.stop(None, None, None)
                except Exception as exc:  # noqa: BLE001 - cleanup must not mask the result
                    logger.warning("Roadmap MCP client stop failed error=%s", type(exc).__name__)
        return sources, count


def fetch_sources(project: str):
    """Fetch all five sources. Returns ``(sources, calls_made)`` or raises ``PlanUnavailable``."""
    fetcher = GatewayFetcher() if settings.tool_mode == "gateway" else DirectFetcher()
    return fetcher.fetch(project)
