"""Human-in-the-loop approval gate for the Task 2 WRITE tools.

The gate is the native Strands 1.61.1 interrupt mechanism (decided in
``docs/.agents/tasks/task2-hitl-decision.md``): a ``HookProvider`` on
``BeforeToolCallEvent`` intercepts the six write tools *before their body runs*.

- First pass: ``event.interrupt("write_approval", reason=proposal)`` raises
  ``InterruptException`` — the agent loop stops and ``agent(...)`` returns an
  ``AgentResult`` with ``stop_reason == "interrupt"`` carrying our ``Interrupt``.
  No HTTP write happens because the tool body never executed.
- Resume pass: the same event fires again, ``interrupt(...)`` now RETURNS the
  stored response. On a non-``APPROVE`` response the hook sets
  ``event.cancel_tool`` so the framework turns it into an error-status tool
  result and the body (the POST/PUT) still never runs.

Read tools are not in ``WRITE_TOOL_NAMES`` so they pass straight through.
"""

from __future__ import annotations

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

# The six write @tool function names the hook gates on (FEAT-001 exports).
WRITE_TOOL_NAMES: set[str] = {
    "jira_create_story",
    "jira_update_story",
    "github_create_branch",
    "github_commit_files",
    "github_open_pull_request",
    "servicenow_create_incident",
}

# Map a write tool name -> (system, action). ``action`` is the mahalo-dock action
# name (the key the [SYSTEM] templates switch on), NOT the strands tool name.
_SYSTEM_BY_PREFIX = {
    "jira": "jira",
    "github": "github",
    "servicenow": "servicenow",
}


def _bare_name(name: str) -> str:
    """Return the bare tool name.

    In GATEWAY mode the Gateway renames every tool to ``"<target>___<tool>"``
    (triple underscore); in DIRECT mode the name is already bare. ``rsplit`` on
    ``___`` strips the Gateway prefix and is a no-op for a bare local name, so
    one code path serves both modes.
    """
    return name.rsplit("___", 1)[-1]


def build_proposal(tool_use) -> dict:
    """Build the human-readable approval proposal from a tool-use payload.

    Returns ``{"action", "system", "params", "description"}`` where ``action`` is
    the tool name with its service prefix stripped (e.g. ``github_create_branch``
    -> ``create_branch``), ``system`` is the prefix (``jira``/``github``/
    ``servicenow``), ``params`` is a copy of ``tool_use["input"]`` (its keys are
    the tool's own parameter names), and ``description`` is a human sentence.
    """
    name = _bare_name(tool_use["name"])
    prefix, _, action = name.partition("_")
    system = _SYSTEM_BY_PREFIX.get(prefix, prefix)
    params = dict(tool_use.get("input") or {})

    return {
        "action": action,
        "system": system,
        "params": params,
        "description": _describe(action, params),
    }


def _describe(action: str, p: dict) -> str:
    """A human sentence summarizing the proposed write, from raw tool args.

    The summary is built from the model-supplied arguments only (the tool body
    does not run pre-approval), per the design's "less rich summary" decision.
    """
    if action == "create_story":
        return (
            f"Create story '{p.get('title', '')}' in project "
            f"{p.get('project_id', '')}"
        )
    if action == "update_story":
        return f"Update story {p.get('story_id', '')}"
    if action == "create_branch":
        return (
            f"Create branch '{p.get('branch_name', '')}' in "
            f"{p.get('repo_id', '')} from {p.get('from_branch', 'main')}"
        )
    if action == "commit_files":
        return (
            f"Commit files to branch '{p.get('branch', '')}' in "
            f"{p.get('repo_id', '')}"
        )
    if action == "open_pull_request":
        return (
            f"Open a pull request from '{p.get('head', '')}' into "
            f"'{p.get('base', 'main')}' in {p.get('repo_id', '')}"
        )
    if action == "create_incident":
        return (
            f"Open a {p.get('severity', 'P3')} incident '{p.get('title', '')}' "
            f"for {p.get('affected_service', '')}"
        )
    # Generic fallback (should not happen for the six gated writes).
    return f"Execute the '{action}' write action"


class WriteApprovalHook(HookProvider):
    """Gate the six write tools behind a human-in-the-loop interrupt."""

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call)

    def _before_tool_call(self, event: BeforeToolCallEvent) -> None:
        # Strip the Gateway ``<target>___<tool>`` prefix before matching so the
        # six write names are recognized in both DIRECT and GATEWAY modes.
        if _bare_name(event.tool_use["name"]) not in WRITE_TOOL_NAMES:
            # Read tools pass straight through (no-op).
            return

        # First pass raises InterruptException and stops the loop; on resume this
        # returns the stored response instead.
        response = event.interrupt("write_approval", reason=build_proposal(event.tool_use))
        if response != "APPROVE":
            event.cancel_tool = "Write rejected by user."
