"""Role-based tool access for the write tools.

``RoleAccessApprovalHook`` extends the unchanged :class:`WriteApprovalHook`: a tool
that the caller's role may not use is cancelled BEFORE the parent hook runs, so no
approval interrupt (and no approval card) is raised for it. Every other tool call
is delegated to the parent unchanged.

Strands runs every ``BeforeToolCallEvent`` callback and checks ``interrupts``
before ``cancel_tool``, so a separate sibling hook could not suppress the card;
hence the subclass.
"""
from __future__ import annotations

from strands.hooks import BeforeToolCallEvent

from agent.approval import WriteApprovalHook, _bare_name

# Bare tool names a role may NOT use. A role absent from this table has no extra
# restriction. ``jira_add_comment`` (design-review comment) is architect-only.
BLOCKED_TOOLS_BY_ROLE: dict[str, frozenset[str]] = {
    "architect": frozenset(
        {"github_create_branch", "github_commit_files", "github_open_pull_request"}
    ),
    "product_manager": frozenset({"jira_add_comment"}),
    "developer": frozenset({"jira_add_comment"}),
    "executive": frozenset({"jira_add_comment"}),
}


class RoleAccessApprovalHook(WriteApprovalHook):
    """``WriteApprovalHook`` that first refuses tools blocked for the role."""

    def __init__(self, role: str) -> None:
        self._role = role
        self._blocked = BLOCKED_TOOLS_BY_ROLE.get(role, frozenset())

    def _before_tool_call(self, event: BeforeToolCallEvent) -> None:
        bare = _bare_name(event.tool_use["name"])
        if bare in self._blocked:
            event.cancel_tool = (
                f"Not permitted for your role: {bare} is not available to the "
                f"{self._role} role. Ask a developer to do this."
            )
            return  # no interrupt, so no approval card
        super()._before_tool_call(event)
