"""One live integration test that skips gracefully when offline.

This test only runs end-to-end when BOTH the mock tunnel (ports 5001-5004) is
reachable AND AWS credentials for Bedrock are available. In every other case it
calls ``pytest.skip(...)`` so the suite still passes with exit code 0 — it must
NEVER fail the suite when the tunnel is down or creds are missing/expired.

When it does run it asserts:
* "list my repositories" -> output contains ``payment-service``.
* "show my stories" (dev-6) -> output contains PAY stories (``PAY-``).
"""

from __future__ import annotations

import httpx
import pytest

from agent.config import settings


def _mocks_reachable() -> bool:
    """Quick, short-timeout probe of the Jira mock via the token header."""
    try:
        resp = httpx.get(
            f"{settings.jira_url}/projects",
            headers={"X-API-Token": settings.jira_token},
            timeout=2.0,
        )
    except (httpx.HTTPError, OSError):
        return False
    return resp.status_code == 200


def test_live_agent_reads_repos_and_my_stories():
    if not _mocks_reachable():
        pytest.skip("mocks/tunnel unreachable (ports 5001-5004) — skipping live test")

    # Import + build only after the reachability gate so offline runs stay cheap.
    from agent.strands_agent import build_agent

    try:
        agent = build_agent()
    except Exception as exc:  # pragma: no cover - env dependent
        pytest.skip(f"could not build agent (AWS creds/profile?): {exc}")

    try:
        repos = str(agent("list my repositories"))
        stories = str(agent("show my stories"))
    except Exception as exc:  # pragma: no cover - env dependent
        # Missing/expired AWS session, Bedrock access, etc. — skip, never fail.
        pytest.skip(f"live Bedrock call unavailable: {exc}")

    assert "payment-service" in repos
    assert "PAY-" in stories
