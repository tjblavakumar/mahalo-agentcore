"""Strands WRITE tools for the Mock Jira service (Task 2, HITL-gated).

Thin ``@tool`` functions that mirror the Task 1 read-module pattern: read the
base URL + token from ``agent.config.settings``, call the shared
``agent.tools.http.make_request`` seam, return a formatted string, and never
raise. The "propose vs execute" concern lives entirely in the approval hook
(FEAT-002); these bodies perform the real POST/PUT once the write is approved.

``jira_update_story`` reuses the name->dev-id resolution helpers that live in the
frozen Task 1 read module. Those helpers are module-private, so we import them
directly (the documented one-way ``jira_write_tools.py -> jira_tools.py``
dependency); ``jira_tools.py`` itself is NOT modified.
"""

from __future__ import annotations

from typing import Optional

import httpx

from strands import tool

# Module-level import is a plain import (no network, no IdentityClient / boto3
# client built). The @requires_api_key decorator is applied ONLY to the
# body-local ``_inner`` inside ``_fetch_jira_token`` below, which is defined and
# invoked solely on a real Identity-enabled call — so importing this module and
# constructing ``build_agent(identity=True)`` both stay fully offline.
from bedrock_agentcore.identity.auth import requires_api_key

from agent.config import settings
from agent.tools.http import make_request
from agent.tools.jira_tools import _fetch_developers, _resolve_assignee


def _fetch_jira_token() -> str:
    """Fetch the brokered Jira API key via AgentCore Identity (call-time only).

    ``@requires_api_key`` is applied to the INNER function, which is defined only
    when this helper runs, so the ``IdentityClient`` / boto3 clients are built
    only on a real call with identity enabled — never at import. The decorator
    injects ``api_key=`` into ``_inner`` at call time. The fetched key is a return
    value (never a tool parameter) and is never logged.
    """

    @requires_api_key(provider_name=settings.identity_jira_provider, into="api_key")
    def _inner(*, api_key: str) -> str:
        return api_key

    return _inner()


@tool
def jira_create_story(
    project_id: str,
    title: str,
    description: str,
    priority: str = "medium",
    story_points: int = 0,
    assignee: Optional[str] = None,
) -> str:
    """Create a new story in a Jira project. [WRITE ACTION - REQUIRES APPROVAL]
    project_id: the project key (e.g. PAY, CART, AUTH, PROD, ORD).
    title/description: required.
    priority: critical | high | medium | low (default medium).
    story_points: integer estimate (default 0).
    assignee: a developer ID (dev-1..dev-6) or None."""
    body = {
        "project_id": project_id,
        "title": title,
        "description": description,
        "priority": priority,
        "story_points": story_points,
        "assignee": assignee,
    }
    # Toggle is a plain body-level conditional; the decorator is never
    # "un-applied". With identity off, read the static token exactly as before.
    # The broad ``except`` is justified because the @tool contract is "never
    # raise"; the message is type-name-only and never contains the key value.
    try:
        token = _fetch_jira_token() if settings.identity_enabled else settings.jira_token
    except Exception as exc:  # noqa: BLE001 - ClientError / ValueError / etc.
        return (
            f"❌ Failed to create story: credential fetch failed "
            f"({type(exc).__name__})"
        )
    try:
        data = make_request(
            settings.jira_url,
            token,
            endpoint="/stories",
            method="POST",
            body=body,
        )
    except (httpx.HTTPError, OSError) as exc:
        return f"❌ Failed to create story: {exc}"

    if "error" in data:
        return f"❌ Failed to create story: {data['error']}"
    return f"✅ Story created successfully: **{data['id']}** - {data['title']}"


@tool
def jira_update_story(
    story_id: str,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    priority: Optional[str] = None,
    story_points: Optional[int] = None,
    sprint_id: Optional[str] = None,
) -> str:
    """Update an existing Jira story. [WRITE ACTION - REQUIRES APPROVAL]
    story_id: the story key (e.g. PAY-105) — must already exist.
    Provide ONLY the fields to change: status (todo/in_progress/in_review/done),
    assignee (a developer ID dev-1..dev-6 or a person's name, resolved to a
    dev-ID), priority, story_points, sprint_id."""
    # Pre-GET to confirm the story exists (reuses the shared read seam; GET).
    existing = make_request(
        settings.jira_url, settings.jira_token, endpoint=f"/stories/{story_id}"
    )
    if "error" in existing:
        return f"Story '{story_id}' was not found, so it cannot be updated."

    # Resolve a name-based assignee to a developer ID.
    resolved_assignee = assignee
    if assignee is not None:
        resolved_assignee = _resolve_assignee(assignee)
        if not resolved_assignee:
            developers = _fetch_developers()
            names = ", ".join(f"{d['name']} ({d['id']})" for d in developers)
            return f"Could not resolve assignee '{assignee}'. Available developers: {names}"

    # Build the change set from ONLY the provided (non-None) fields.
    changes: dict = {}
    if status is not None:
        changes["status"] = status
    if assignee is not None:
        changes["assignee"] = resolved_assignee
    if priority is not None:
        changes["priority"] = priority
    if story_points is not None:
        changes["story_points"] = story_points
    if sprint_id is not None:
        changes["sprint_id"] = sprint_id

    if not changes:
        return f"No changes specified for {story_id}. Provide at least one field to update."

    try:
        data = make_request(
            settings.jira_url,
            settings.jira_token,
            endpoint=f"/stories/{story_id}",
            method="PUT",
            body=changes,
        )
    except (httpx.HTTPError, OSError) as exc:
        return f"❌ Failed to update story: {exc}"

    if "error" in data:
        return f"❌ Failed to update story: {data['error']}"
    return f"✅ Story updated successfully: **{data['id']}** - {data['title']}"


JIRA_WRITE_TOOLS = [jira_create_story, jira_update_story]
