"""Offline tests that the BASE_PROMPT rules reach every persona's system prompt."""

from __future__ import annotations

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
