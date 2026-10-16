"""Single source of truth for assignee name -> developer-ID resolution.

This is the one behavioral body behind BOTH the agent-side
``agent.tools.jira_tools._resolve_assignee`` (DIRECT mode) and the Lambda-side
Jira composites (GATEWAY mode), so the two modes resolve an assignee reference
identically. It is a pure, stdlib-only function: the caller supplies the
developer directory, so there is no HTTP/network dependency and it runs the same
in either process.

Reproduces exactly the six branches of the original ``_resolve_assignee``:

1. empty/falsey input -> ``None``;
2. a ``dev-`` prefixed value -> that value lower-cased, WITHOUT consulting the
   developer list (short-circuit);
3. exact full-name or email match -> that developer's id;
4-5. first-name / substring / email-local-part match -> the single match's id;
6. zero or >1 ambiguous matches -> ``None``.
"""

from __future__ import annotations

from typing import Optional


def resolve_assignee(assignee: str, developers: list[dict]) -> Optional[str]:
    """Resolve an assignee reference to a developer ID, or ``None``.

    ``developers`` is the developer directory (each a dict with ``id``, ``name``
    and optional ``email``). A ``dev-`` prefixed input short-circuits and is
    returned lower-cased without consulting ``developers``.
    """
    if not assignee:
        return None
    val = assignee.strip().lower()
    # Already a developer ID (short-circuits before touching ``developers``).
    if val.startswith("dev-"):
        return val
    # Exact full-name or email match first.
    for d in developers:
        if val == d["name"].lower() or val == d.get("email", "").lower():
            return d["id"]
    # First-name / partial / email-local-part match.
    matches = [
        d
        for d in developers
        if val in d["name"].lower()
        or val == d.get("email", "").split("@")[0].lower()
        or d["name"].lower().split()[0] == val
    ]
    if len(matches) == 1:
        return matches[0]["id"]
    return None
