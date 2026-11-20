"""Offline tests that the BASE_PROMPT rules reach every persona's system prompt."""

from __future__ import annotations

import re

import pytest

from agent.prompts import ROLE_PROMPTS


def _built(role: str) -> str:
    # Same formatting the agent builder performs (agent/strands_agent.py).
    return ROLE_PROMPTS[role].format(
        integrations_context="ctx", user_name="Test User", user_role=role
    )


@pytest.mark.parametrize("role", sorted(ROLE_PROMPTS))
def test_code_in_replies_rule_present(role):
    prompt = _built(role)
    assert "do NOT paste full file contents" in prompt
    assert "'View code'" in prompt
    assert "repo and branch" in prompt


@pytest.mark.parametrize("role", sorted(ROLE_PROMPTS))
def test_no_test_data_and_no_invented_links_rule_present(role):
    prompt = _built(role)
    assert "hold NO test cases, coverage, or QA results" in prompt
    assert "inferences" in prompt
    assert "without a source" in prompt
    assert "linked_deployment" in prompt
    assert "no recorded link" in prompt


def _sample_skill(prompt: str) -> str:
    start = prompt.index("````markdown\n") + len("````markdown\n")
    return prompt[start : prompt.index("\n````", start)]


@pytest.mark.parametrize("role", sorted(ROLE_PROMPTS))
def test_skill_authoring_rule_present(role):
    prompt = _built(role)
    assert "11. SKILL FILES" in prompt
    assert "SYSTEM_WHAT_SKILL.md" in prompt
    assert "ONE complete skill file" in prompt
    assert "FOUR backticks" in prompt
    assert "do NOT propose github_create_branch, github_commit_files" in prompt
    assert "jira_create_story" in prompt.split("11. SKILL FILES")[1].split("\n")[0]
    assert "Do not draft a skill that could not run" in prompt
    assert "internet" in prompt
    assert "Download and Open in upload" in prompt


@pytest.mark.parametrize("role", sorted(ROLE_PROMPTS))
def test_prompt_sample_skill_shape_and_known_tools(role):
    import agent.tools.confluence_tools as confluence
    import agent.tools.github_tools as github
    import agent.tools.jira_tools as jira
    import agent.tools.servicenow_tools as servicenow

    sample = _sample_skill(_built(role))
    lines = sample.split("\n")
    assert lines[0] == "---" and lines[1] == "name: production-issues"
    assert lines[2].startswith("description: ") and len(lines[2]) < 1024
    assert lines[3] == "---"
    assert "{" not in sample  # survives str.format in the agent builder
    # Read tools only, and each one exists in the registered tool modules.
    modules = (confluence, github, jira, servicenow)
    used = set(re.findall(r"\b(?:jira|servicenow|confluence|github)_[a-z_]+", sample))
    assert used
    for name in used:
        assert any(hasattr(m, name) for m in modules), name
    assert not used & {"jira_create_story", "jira_update_story", "servicenow_create_incident"}
    assert not any(n.startswith("github_commit") or n.startswith("github_create") for n in used)
