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
    import agent.tools.cicd_tools as cicd

    modules = (confluence, github, jira, servicenow, cicd)
    used = set(re.findall(r"\b(?:jira|servicenow|confluence|github|cicd)_[a-z_]+", sample))
    assert used
    for name in used:
        assert any(hasattr(m, name) for m in modules), name
    assert not used & {"jira_create_story", "jira_update_story", "servicenow_create_incident"}
    assert not any(n.startswith("github_commit") or n.startswith("github_create") for n in used)


@pytest.mark.parametrize("role", sorted(ROLE_PROMPTS))
def test_cicd_honesty_and_feature_status_rules_present(role):
    prompt = _built(role)
    assert "12. CI/CD HONESTY" in prompt
    section = prompt.split("12. CI/CD HONESTY")[1].split("You have access")[0]
    assert "seeded demo data, not a live pipeline" in section
    assert "nothing ran for code Mahalo committed" in section
    assert 'name "CI/CD" among the systems cited' in section
    assert "quote ref_note" in section
    assert '"just ran"' in section
    assert "repository's actual commit" in section
    assert "no pipeline run recorded" in section
    assert "deployments_without_pipeline_run" in section
    assert "13. FEATURE STATUS" in section
    for name in ("jira_get_story", "github_get_repo_stats", "github_get_pull_requests",
                 "cicd_story_delivery_status"):
        assert name in section
    for part in ("Story", "Code", "Review", "Pipeline", "Deployment", "Incidents"):
        assert part in section
    # The prompt and tool schemas are sent on every turn: keep rules 12 and 13 short.
    assert len("12. CI/CD HONESTY" + section) < 1200


@pytest.mark.parametrize("role", sorted(ROLE_PROMPTS))
def test_rule_10_still_says_no_test_cases_but_allows_pipeline_counts(role):
    prompt = _built(role)
    rule10 = prompt.split("10. NO TEST DATA")[1].split("11. SKILL FILES")[0]
    assert "hold NO test cases, coverage, or QA results" in rule10
    assert "CI/CD pipeline counts and scan findings" in rule10
    assert "do not show which test cases exist" in rule10.replace("They do not", "do not")


@pytest.mark.parametrize("role", sorted(ROLE_PROMPTS))
def test_branch_naming_hint_in_check_in_flow(role):
    prompt = _built(role)
    flow = prompt.split("CHECK-IN-CODE FLOW")[1].split("A `[SYSTEM]` message")[0]
    assert "feature/<STORY-ID>-<short-slug>" in flow
    assert "feature/PAY-109-crypto-payments" in flow
    assert "propose github_create_branch first" in flow


@pytest.mark.parametrize("role", sorted(ROLE_PROMPTS))
def test_skill_rule_lists_cicd_results_and_no_longer_blocks_test_results(role):
    rule11 = _built(role).split("11. SKILL FILES")[1].split("12. CI/CD HONESTY")[0]
    assert "recorded CI/CD pipeline results" in rule11
    assert "test cases or coverage" in rule11
    assert "test results," not in rule11


@pytest.mark.parametrize("role", sorted(ROLE_PROMPTS))
def test_portfolio_overviews_include_pipeline_and_security(role):
    prompt = _built(role)
    assert "PORTFOLIO SECURITY:" in prompt
    rule = prompt.split("PORTFOLIO SECURITY:")[1].split("\n")[0]
    assert "cicd_pipeline_summary" in rule
    assert "Pipeline and security" in rule
    assert "even when the user listed other topics" in rule
    assert "recorded CI/CD demo data" in rule
