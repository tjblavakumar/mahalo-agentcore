"""Shared HITL (human-in-the-loop) helpers for the CLI and the Runtime entrypoint.

The native Strands interrupt gate (``agent/approval.py::WriteApprovalHook``) pauses
the agent with ``stop_reason == "interrupt"`` before a write tool body runs; the
caller resumes the agent with an ``interruptResponse`` block carrying the decision.
Historically both the resume call and the ``[SYSTEM]`` breadcrumb lived as private
helpers inside ``agent/chat.py``; Task 6 adds a second consumer (the Runtime
entrypoint), so the two pieces are extracted here as the single canonical
implementation. ``agent/chat.py`` now re-uses these; behavior is unchanged.

Two functions:

* ``resume_once(agent, interrupt_id, decision) -> AgentResult`` — the single
  canonical resume: one ``agent([{ "interruptResponse": {...} }])`` call returning
  the ``AgentResult``. The caller inspects ``result.stop_reason`` to learn whether
  the tool cycle closed (``!= "interrupt"``) or re-interrupted (a chained write).
* ``emit_system_signal(agent, proposal)`` — append a ``[SYSTEM]`` breadcrumb to
  history after an APPROVED write so the branch -> commit -> PR chain is not
  re-proposed. Moved verbatim from ``agent/chat.py::_emit_system_signal`` (same
  three templates + generic fallback). Called on approve only.
"""

from __future__ import annotations


def resume_once(agent, interrupt_id: str, decision: str):
    """Resume a paused agent with one ``interruptResponse`` block; return the result.

    ``decision`` is ``"APPROVE"`` or ``"REJECT"``. On ``APPROVE`` the gate's
    ``event.interrupt(...)`` returns the decision and the write body runs; on
    ``REJECT`` the hook sets ``event.cancel_tool`` so nothing is written. This is
    a single turn — the caller loops / inspects ``result.stop_reason`` to decide
    whether a chained write re-interrupted.
    """
    return agent(
        [{"interruptResponse": {"interruptId": interrupt_id, "response": decision}}]
    )


def emit_system_signal(agent, proposal: dict) -> None:
    """Append a ``[SYSTEM]`` breadcrumb to history after an APPROVED write.

    Keyed on ``proposal["action"]`` using the three verbatim templates from
    task2-design.md for the GitHub chain, with a generic fallback for the other
    writes. Called on approve only; nothing is emitted on reject.
    """
    action = proposal["action"]
    p = proposal["params"]

    if action == "create_branch":
        msg = (
            f"[SYSTEM] The user APPROVED and the branch '{p['branch_name']}' "
            f"now exists in repo '{p['repo_id']}'. Do NOT propose creating it "
            f"again. Next, if the user asked to commit code, propose "
            f"github_commit_files to that branch with the full file contents you "
            f"prepared earlier."
        )
    elif action == "commit_files":
        msg = (
            f"[SYSTEM] The user APPROVED and the files were committed to branch "
            f"'{p['branch']}' in repo '{p['repo_id']}'. Do NOT propose "
            f"committing again. Next, if the user wants a PR, propose "
            f"github_open_pull_request from '{p['branch']}' into main."
        )
    elif action == "open_pull_request":
        msg = (
            f"[SYSTEM] The user APPROVED and a pull request was opened from "
            f"'{p['head']}' into '{p.get('base', 'main')}' in repo "
            f"'{p['repo_id']}'. The check-in flow is complete."
        )
    else:
        msg = f"[SYSTEM] The user approved and the '{action}' action was executed."

    agent.messages.append({"role": "assistant", "content": [{"text": msg}]})
