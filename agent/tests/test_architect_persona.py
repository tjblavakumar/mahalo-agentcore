"""Offline tests for the Architect persona (Maya Chaya, dev-7).

Covers: role-access gating, the jira_add_comment write (tool, proposal, approval),
the architect prompt, the identity line, approve-leg role forwarding and the
design-document review skip.
"""
from __future__ import annotations

import re

import pytest
from strands.interrupt import InterruptException

from agent import approval
from agent.approval import WRITE_TOOL_NAMES, WriteApprovalHook, build_proposal
from agent.prompts import ROLE_DISPLAY, ROLE_PROMPTS
from agent.role_access import BLOCKED_TOOLS_BY_ROLE, RoleAccessApprovalHook
from agent.tools import jira_write_tools

GIT_WRITES = ["github_create_branch", "github_commit_files", "github_open_pull_request"]


class _Event:
    def __init__(self, name, tool_input=None, stored_response=None):
        self.tool_use = {"name": name, "input": tool_input or {}, "toolUseId": "tu-1"}
        self.cancel_tool = False
        self._stored = stored_response
        self.interrupt_calls = []

    def interrupt(self, name, reason=None, response=None):
        self.interrupt_calls.append({"name": name, "reason": reason})
        if self._stored is None:
            raise InterruptException(
                type("I", (), {"id": "i-1", "name": name, "reason": reason, "response": None})()
            )
        return self._stored


# --------------------------------------------------------------------------- #
# Role gating
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("prefix", ["", "mock-github___"])
@pytest.mark.parametrize("name", GIT_WRITES)
def test_architect_git_writes_cancelled_without_interrupt(name, prefix):
    event = _Event(prefix + name, {"repo_id": "r", "branch_name": "b"})
    RoleAccessApprovalHook("architect")._before_tool_call(event)
    assert event.interrupt_calls == []
    assert isinstance(event.cancel_tool, str)
    assert "Not permitted for your role" in event.cancel_tool


@pytest.mark.parametrize("role", ["product_manager", "executive"])
@pytest.mark.parametrize("prefix", ["", "mock-github___"])
@pytest.mark.parametrize("name", GIT_WRITES)
def test_pm_and_exec_git_writes_cancelled_without_interrupt(name, prefix, role):
    """B1: only the developer may create branches, commit or open PRs."""
    event = _Event(prefix + name, {"repo_id": "r", "branch_name": "b"})
    RoleAccessApprovalHook(role)._before_tool_call(event)
    assert event.interrupt_calls == []
    assert isinstance(event.cancel_tool, str)
    assert "Not permitted for your role" in event.cancel_tool


def test_only_developer_may_use_git_writes():
    for role, blocked in BLOCKED_TOOLS_BY_ROLE.items():
        if role == "developer":
            assert not (set(GIT_WRITES) & blocked)
        else:
            assert set(GIT_WRITES) <= blocked, role


@pytest.mark.parametrize("name", GIT_WRITES)
def test_developer_git_writes_still_interrupt(name):
    event = _Event(name, {"repo_id": "r", "branch_name": "b"})
    with pytest.raises(InterruptException):
        RoleAccessApprovalHook("developer")._before_tool_call(event)
    assert event.interrupt_calls[0]["name"] == "write_approval"


@pytest.mark.parametrize("role", ["product_manager", "developer", "executive"])
@pytest.mark.parametrize("prefix", ["", "mock-jira___"])
def test_other_roles_cannot_add_comment(role, prefix):
    event = _Event(prefix + "jira_add_comment", {"story_id": "PAY-109", "author": "dev-6", "text": "x"})
    RoleAccessApprovalHook(role)._before_tool_call(event)
    assert event.interrupt_calls == []
    assert isinstance(event.cancel_tool, str)


def test_architect_add_comment_raises_approval_interrupt():
    args = {"story_id": "PAY-109", "author": "dev-7", "text": "Design review: ok"}
    event = _Event("jira_add_comment", args)
    with pytest.raises(InterruptException):
        RoleAccessApprovalHook("architect")._before_tool_call(event)
    reason = event.interrupt_calls[0]["reason"]
    assert reason["system"] == "jira"
    assert reason["action"] == "add_comment"
    assert reason["description"] == "Add a design-review comment to PAY-109"
    assert reason["params"]["author"] == "dev-7"
    assert event.cancel_tool is False


@pytest.mark.parametrize("response,cancelled", [("APPROVE", False), ("REJECT", "Write rejected by user.")])
def test_architect_add_comment_resume(response, cancelled):
    event = _Event("jira_add_comment", {"story_id": "PAY-109"}, stored_response=response)
    RoleAccessApprovalHook("architect")._before_tool_call(event)
    assert event.cancel_tool == cancelled


@pytest.mark.parametrize("name", sorted(WRITE_TOOL_NAMES - set(GIT_WRITES) - {"jira_add_comment"}))
def test_architect_other_writes_still_gated(name):
    event = _Event(name, {})
    with pytest.raises(InterruptException):
        RoleAccessApprovalHook("architect")._before_tool_call(event)


def test_architect_read_tool_is_noop():
    event = _Event("jira_get_story", {"story_id": "PAY-109"})
    RoleAccessApprovalHook("architect")._before_tool_call(event)
    assert event.interrupt_calls == [] and event.cancel_tool is False


def test_blocked_table_and_base_hook_unchanged():
    assert BLOCKED_TOOLS_BY_ROLE["architect"] == frozenset(GIT_WRITES)
    assert isinstance(RoleAccessApprovalHook("developer"), WriteApprovalHook)
    # The plain parent hook still gates the three git writes for any caller.
    event = _Event("github_commit_files", {})
    with pytest.raises(InterruptException):
        WriteApprovalHook()._before_tool_call(event)


def test_write_names_match_gateway_schema_and_count():
    from common import tool_schemas

    assert len(WRITE_TOOL_NAMES) == 7
    assert WRITE_TOOL_NAMES == tool_schemas.WRITE_TOOL_NAMES


def test_proposal_for_add_comment():
    p = build_proposal(
        {"name": "mock-jira___jira_add_comment",
         "input": {"story_id": "PAY-109", "author": "dev-7", "text": "Design review: x"}}
    )
    assert (p["system"], p["action"]) == ("jira", "add_comment")
    assert approval._describe("add_comment", {}) == "Add a design-review comment to "


# --------------------------------------------------------------------------- #
# jira_add_comment tool
# --------------------------------------------------------------------------- #
def test_jira_add_comment_posts_and_formats(monkeypatch):
    calls = []

    def fake(base_url, token, endpoint="", params=None, method="GET", body=None, timeout=None):
        calls.append((endpoint, method, body))
        return {"id": "PAY-109", "title": "Crypto"}

    monkeypatch.setattr(jira_write_tools, "make_request", fake)
    out = jira_write_tools.jira_add_comment("PAY-109", "dev-7", "Design review: ok")
    assert calls == [("/stories/PAY-109/comments", "POST", {"author": "dev-7", "text": "Design review: ok"})]
    assert out.endswith("Comment added to **PAY-109** - Crypto")


def test_jira_add_comment_error_dict_and_transport_error(monkeypatch):
    import httpx

    monkeypatch.setattr(jira_write_tools, "make_request", lambda *a, **k: {"error": "Story not found"})
    assert jira_write_tools.jira_add_comment("X-1", "dev-7", "t").endswith("Failed to add comment: Story not found")

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(jira_write_tools, "make_request", boom)
    assert jira_write_tools.jira_add_comment("X-1", "dev-7", "t").endswith("Failed to add comment: down")


def test_jira_add_comment_registered_as_write_tool():
    from agent.strands_agent import READ_TOOLS, WRITE_TOOLS

    assert "jira_add_comment" in {t.tool_name for t in WRITE_TOOLS}
    assert "jira_add_comment" not in {t.tool_name for t in READ_TOOLS}


# --------------------------------------------------------------------------- #
# Prompts and identity
# --------------------------------------------------------------------------- #
def _built(role, name="Maya Chaya", label="Architect"):
    return ROLE_PROMPTS[role].format(integrations_context="ctx", user_name=name, user_role=label)


def test_architect_prompt_content():
    prompt = _built("architect")
    assert "Maya Chaya" in prompt and "Architect" in prompt
    for word in ("dependencies", "risk", "security", "reliability", "design quality"):
        assert word in prompt
    # F2: explicit override of rule 2 and the CHECK-IN-CODE flow.
    assert (
        "For you, rule 2 does not apply to github_create_branch, github_commit_files "
        "or github_open_pull_request, and the CHECK-IN-CODE flow does not apply; never call them."
    ) in prompt
    assert "Design documents and ADRs are a second exception to rule 9: reply with ONE complete file" in prompt
    assert "FOUR backticks" in prompt
    assert "author must equal the id in CURRENT USER IDENTITY (dev-7 for you)" in prompt
    assert "jira_add_comment" in prompt
    assert "cannot save the file to Confluence" in prompt
    # F4: no name: key in design document frontmatter.
    assert "Do not use a name: key in design-document frontmatter" in prompt
    # Base rules 1-13 are still present.
    for n in range(1, 14):
        assert re.search(rf"^{n}\. ", prompt, re.M), n


def test_architect_prompt_has_no_braces_beyond_placeholders():
    from agent.prompts import ARCHITECT_PROMPT, BASE_PROMPT

    extra = ARCHITECT_PROMPT[len(BASE_PROMPT):]
    assert "{" not in extra and "}" not in extra


def test_other_role_prompts_unchanged_by_architect_section():
    from agent.prompts import ARCHITECT_PROMPT

    for role in ("product_manager", "developer", "executive"):
        assert "Maya Chaya" not in ROLE_PROMPTS[role]
        assert "jira_add_comment" not in ROLE_PROMPTS[role]
    assert "architect" in ROLE_PROMPTS and ROLE_PROMPTS["architect"] is ARCHITECT_PROMPT


def test_role_display_has_only_architect():
    assert ROLE_DISPLAY == {"architect": ("Maya Chaya", "Architect")}


def _prompt_of(monkeypatch, **kwargs):
    import agent.strands_agent as sa

    captured = {}

    class _FakeAgent:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr(sa, "Agent", _FakeAgent)
    monkeypatch.setattr(sa, "_build_bedrock_model", lambda *_: object())
    sa.build_agent(tool_mode="direct", memory=False, **kwargs)
    return captured


def test_build_agent_identity_defaults(monkeypatch):
    arch = _prompt_of(monkeypatch, role="architect", developer_id="dev-7")
    assert "Current user: Maya Chaya (Role: Architect)" in arch["system_prompt"]
    assert "developer id dev-7 (Maya Chaya)" in arch["system_prompt"]
    assert isinstance(arch["hooks"][0], RoleAccessApprovalHook)
    for role in ("product_manager", "developer", "executive"):
        got = _prompt_of(monkeypatch, role=role)["system_prompt"]
        assert "Current user: Lava Dev (Role: Developer)" in got
        assert "developer id dev-6 (Lava Dev)" in got


def test_build_agent_explicit_identity_wins(monkeypatch):
    got = _prompt_of(monkeypatch, role="architect", user_name="Z", user_role="Q")["system_prompt"]
    assert "Current user: Z (Role: Q)" in got


# --------------------------------------------------------------------------- #
# Runtime: approve role forwarding and the design-doc review skip
# --------------------------------------------------------------------------- #
def test_resolve_role_accepts_architect():
    import agent.runtime_app as ra

    assert ra._resolve_role("architect") == "architect"
    assert ra._resolve_role(None) == "developer"


def test_approve_forwards_role_and_defaults_to_developer(monkeypatch):
    import agent.runtime_app as ra
    from agent.tests.test_runtime_app import _AgentResult, _FakeAgent, _FakeAttached, _FakeContext, _Interrupt
    seen = []

    def build(session_id, developer_id="dev-6", role="developer", *, pending_write=False):
        seen.append((developer_id, role, pending_write))
        agent = _FakeAgent(
            [_AgentResult(text="ok", stop_reason="end_turn")],
            restored_interrupts={"i": _Interrupt("i", {"action": "add_comment", "params": {}})},
        )
        return _FakeAttached(agent)

    monkeypatch.setattr(ra, "build_and_attach", build)
    base = {"action": "approve", "decision": "REJECT", "interrupt_id": "i", "developer_id": "dev-7"}
    ra.invoke({**base, "role": "architect"}, _FakeContext("S1"))
    ra.invoke(base, _FakeContext("S1"))
    assert seen == [("dev-7", "architect", True), ("dev-7", "developer", True)]


_DOC = "````markdown\n---\ndoc_type: adr\ntitle: Crypto\n---\n# ADR\n```python\nx = 1\n```\n````"
_SKILL = "````markdown\n---\nname: my-skill\ndescription: d\n---\nSteps\n````"
_LEGACY_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def _legacy_extract(text):
    return "\n\n".join(b.strip("\n") for b in _LEGACY_RE.findall(text))


@pytest.mark.parametrize("kind", ["adr", "design", "design-review", "ADR"])
def test_doc_fences_yield_no_code(kind):
    import agent.runtime_app as ra

    doc = _DOC.replace("doc_type: adr", f"doc_type: {kind}")
    assert ra._extract_fenced_code(f"Here is the file.\n{doc}\nDownload it.") == ""


@pytest.mark.parametrize(
    "text",
    [
        "```python\ndef f():\n    return 1\n```",
        _SKILL,
        "```md\nplain notes\n```",
        "````markdown\n---\ndoc_type: other\n---\nbody\n````",
        "````markdown\n---\ndoc_type: adr\nno closing frontmatter\n````",
    ],
)
def test_other_fences_extract_exactly_as_before(text):
    import agent.runtime_app as ra

    assert ra._extract_fenced_code(text) == _legacy_extract(text)


def test_doc_fence_does_not_hide_a_following_code_fence():
    import agent.runtime_app as ra

    text = f"{_DOC}\n\n```python\ny = 2\n```"
    assert ra._extract_fenced_code(text) == "y = 2"
