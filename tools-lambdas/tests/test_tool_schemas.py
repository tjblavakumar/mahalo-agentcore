"""Structure parity tests for the single-source-of-truth tool registry (Task 4).

Asserts the 27 descriptors in ``common.tool_schemas``: the right count, the
write-name set equal to the HITL set, each schema a top-level ``object``, exactly
one of ``method``/``composite`` per tool, and that no tool/write name contains the
Gateway ``___`` delimiter (the HITL strip invariant). The EXACT bidirectional
arg-set parity against the live ``@tool`` signatures runs in the agent suite,
where strands is installed.
"""

from __future__ import annotations

from common.tool_schemas import BY_NAME, TOOLS, WRITE_TOOL_NAMES  # noqa: F401

# NOTE: the EXACT bidirectional arg-set parity against the live ``@tool``
# signatures runs in the AGENT suite (agent/tests/test_gateway_mode.py), where
# strands is installed. This lambda-side file asserts the schema structure that
# is checkable without importing the agent package.

# The six write tool names the HITL hook gates on (must equal agent/approval.py).
_EXPECTED_WRITES = {
    "jira_create_story",
    "jira_update_story",
    "github_create_branch",
    "github_commit_files",
    "github_open_pull_request",
    "servicenow_create_incident",
}


def test_twenty_five_tools():
    assert len(TOOLS) == 27
    assert len(BY_NAME) == 27


def test_write_name_set_matches():
    assert WRITE_TOOL_NAMES == _EXPECTED_WRITES


def test_every_schema_is_object():
    for descriptor in TOOLS:
        assert descriptor["input_schema"]["type"] == "object"


def test_no_name_contains_gateway_delimiter():
    for descriptor in TOOLS:
        assert "___" not in descriptor["name"]
    for name in WRITE_TOOL_NAMES:
        assert "___" not in name


def test_read_tools_have_method_or_composite():
    for descriptor in TOOLS:
        assert ("method" in descriptor) ^ bool(descriptor.get("composite")), descriptor["name"]
