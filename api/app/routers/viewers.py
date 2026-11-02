"""Viewer router: read-only allow-list proxy to the mock services + demo refresh.

* ``GET /view/{system}/{path}`` forwards ONLY allow-listed GET paths to the Jira,
  Confluence or ServiceNow mock Lambda Function URLs. The mock API token is added
  server-side and no client header is forwarded, so the token never reaches the
  browser. Anything not on the allow-list is rejected WITHOUT calling upstream.
* ``POST /admin/refresh-demo-data`` resets the three mock services to a fresh
  seed (dates re-based to today), guarded by a global 60 s cooldown.

Stdlib ``urllib`` only (no new dependency in the Lambda bundle). Settings are read
per request so tests (and config changes) take effect without a reload.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.auth import Identity, current_identity
from app.config import Settings
from app.routers import dashboard

logger = logging.getLogger(__name__)
router = APIRouter(tags=["viewers"])

SYSTEMS = ("jira", "confluence", "servicenow")
COOLDOWN_SECONDS = 60
PROXY_TIMEOUT_SECONDS = 10
RESET_TIMEOUT_SECONDS = 25
_COOLDOWN_KEY = "_admin_refresh"

# One path segment: letters, digits, underscore, hyphen. No dots, percent signs or
# slashes, so traversal (``..``, ``%2e%2e``) or empty segments can never match.
_SEG = r"[A-Za-z0-9_-]+"
_ALLOW: dict[str, tuple[re.Pattern[str], ...]] = {
    system: tuple(re.compile(p.replace("{id}", _SEG)) for p in patterns)
    for system, patterns in {
        "jira": (
            r"projects",
            r"projects/{id}",
            r"projects/{id}/board",
            r"projects/{id}/stories",
            r"stories",
            r"stories/{id}",
            r"sprints/{id}",
            r"developers",
        ),
        "confluence": (
            r"spaces",
            r"spaces/{id}",
            r"spaces/{id}/pages",
            r"pages",
            r"pages/{id}",
            r"search",
        ),
        "servicenow": (
            r"services",
            r"deployments",
            r"deployments/{id}",
            r"incidents",
            r"incidents/{id}",
            r"stats",
        ),
    }.items()
}


class _UpstreamError(Exception):
    """Upstream unreachable, timed out, or returned an unusable status."""


def _urlopen(req: urllib.request.Request, timeout: float):
    """Single seam for outbound HTTP (tests patch this)."""
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - https/http base URL from env


def _target(system: str, cfg: Settings) -> tuple[str, str]:
    """Return ``(base_url, token)`` for a system or raise 503 when unconfigured."""
    base = getattr(cfg, f"{system}_url")
    token = getattr(cfg, f"{system}_token")
    if not base or not token:
        raise HTTPException(status_code=503, detail=f"{system} viewer is not configured")
    return base, token


def _call(
    method: str, url: str, token: str, timeout: float
) -> tuple[int, bytes]:
    """Perform one upstream call; return ``(status, body)`` for 2xx and 404."""
    req = urllib.request.Request(url, method=method, headers={"X-API-Token": token})
    if method == "POST":
        req.data = b""
    try:
        with _urlopen(req, timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 404, exc.read()
        raise _UpstreamError(f"upstream returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise _UpstreamError("upstream unreachable") from exc


@router.get("/view/{system}/{path:path}")
def view(
    system: str,
    path: str,
    request: Request,
    _ident: Identity = Depends(current_identity),
) -> Response:
    """Read-only proxy for allow-listed mock GET endpoints."""
    patterns = _ALLOW.get(system)
    if patterns is None or not any(p.fullmatch(path) for p in patterns):
        raise HTTPException(status_code=404, detail="Not found")
    base, token = _target(system, Settings())
    url = f"{base}/{path}"
    query = request.url.query
    if query:
        url = f"{url}?{query}"
    try:
        status, body = _call("GET", url, token, PROXY_TIMEOUT_SECONDS)
    except _UpstreamError:
        logger.warning("viewer upstream failure system=%s path=%s", system, path)
        raise HTTPException(status_code=502, detail=f"Upstream {system} unavailable")
    return Response(content=body, status_code=status, media_type="application/json")


def _claim_cooldown(now: float) -> Optional[int]:
    """Claim the global refresh slot; return seconds to wait when cooling down."""
    table = dashboard._get_table()
    try:
        table.put_item(
            Item={
                "personaId": _COOLDOWN_KEY,
                "lastRefreshEpoch": int(now),
                "updatedAt": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            },
            ConditionExpression="attribute_not_exists(personaId) OR lastRefreshEpoch <= :cutoff",
            ExpressionAttributeValues={":cutoff": int(now) - COOLDOWN_SECONDS},
        )
        return None
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
    item = table.get_item(Key={"personaId": _COOLDOWN_KEY}).get("Item") or {}
    last = item.get("lastRefreshEpoch", Decimal(int(now)))
    return max(1, math.ceil(float(last) + COOLDOWN_SECONDS - now))


def _reset_one(system: str, cfg: Settings) -> dict[str, Any]:
    base, token = _target(system, cfg)
    try:
        _status, body = _call("POST", f"{base}/admin/reset", token, RESET_TIMEOUT_SECONDS)
        data = json.loads(body)
        return {
            "ok": True,
            "counts": data.get("counts", {}),
            "shift_days": data.get("shift_days"),
        }
    except (_UpstreamError, ValueError, AttributeError) as exc:
        logger.warning("refresh failed system=%s: %s", system, exc)
        return {"ok": False, "error": f"{system} reset failed"}


@router.post("/admin/refresh-demo-data")
def refresh_demo_data(_ident: Identity = Depends(current_identity)) -> JSONResponse:
    """Reset Jira, Confluence and ServiceNow mock data (global 60 s cooldown)."""
    cfg = Settings()
    for system in SYSTEMS:
        _target(system, cfg)  # 503 before claiming the cooldown slot
    now = time.time()
    try:
        wait = _claim_cooldown(now)
    except (ClientError, BotoCoreError):
        logger.exception("refresh cooldown store failed")
        raise HTTPException(status_code=502, detail="Cooldown store unavailable")
    if wait is not None:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Demo data was refreshed recently",
                "retry_after_seconds": wait,
            },
            headers={"Retry-After": str(wait)},
        )
    with ThreadPoolExecutor(max_workers=len(SYSTEMS)) as pool:
        futures = {s: pool.submit(_reset_one, s, cfg) for s in SYSTEMS}
        results = {s: f.result() for s, f in futures.items()}
    return JSONResponse(
        status_code=200,
        content={
            "results": results,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
