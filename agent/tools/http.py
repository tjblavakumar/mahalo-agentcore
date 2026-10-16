"""Shared httpx request helper used by every mock-system tool.

All four services (Jira, Confluence, GitHub, ServiceNow) talk HTTP with the same
static ``X-API-Token`` header and the same success/error contract, so this is the
single seam the unit tests monkeypatch. Task 1 tools are READ-ONLY (GET), but the
signature stays general so the write tools in Task 2 can reuse it.
"""

from __future__ import annotations

from typing import Optional

import httpx

from agent.config import settings


def make_request(
    base_url: str,
    token: str,
    endpoint: str = "",
    params: Optional[dict] = None,
    method: str = "GET",
    body: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> dict:
    """Call a mock service and return the parsed JSON (or an ``error`` dict).

    On a 200/201 response the decoded JSON body is returned. On any other status
    the returned dict is ``{"error": "Request failed with status {code}: {text}"}``
    — the exact string mahalo-dock used so error output stays byte-for-byte equal.
    """
    headers = {"X-API-Token": token}
    full_url = f"{base_url}{endpoint}"
    request_timeout = timeout if timeout is not None else settings.http_timeout

    with httpx.Client(timeout=request_timeout) as client:
        if method == "GET":
            response = client.get(full_url, headers=headers, params=params)
        elif method == "POST":
            response = client.post(full_url, headers=headers, json=body)
        elif method == "PUT":
            response = client.put(full_url, headers=headers, json=body)
        else:
            return {"error": f"Unsupported method: {method}"}

    if response.status_code in (200, 201):
        return response.json()
    return {"error": f"Request failed with status {response.status_code}: {response.text}"}
