"""Shipped skills yield verdict can_do through build_check (requirements AC 15a)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent import skills
from agent.skills import DraftStep, SkillCheckDraft

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

SPRINT_REPORT = [
    DraftStep(text="Read sprints", systems=["Jira"], tools=["jira_get_sprint_info"], est_calls=1),
    DraftStep(text="Read stories", systems=["Jira"], tools=["jira_search_stories"], est_calls=1),
    DraftStep(text="Read developers", systems=["Jira"], tools=["jira_list_developers"], est_calls=1),
]
ROADMAP = [
    DraftStep(text="Read sprints", systems=["Jira"], tools=["jira_get_sprint_info"], est_calls=1),
    DraftStep(text="Read stories", systems=["Jira"], tools=["jira_search_stories"], est_calls=1),
    DraftStep(
        text="Read incidents and deployments", systems=["ServiceNow"],
        tools=["servicenow_list_incidents", "servicenow_list_deployments"], est_calls=2,
    ),
    DraftStep(text="Read developers", systems=["Jira"], tools=["jira_list_developers"], est_calls=1),
]


@pytest.mark.parametrize(
    "filename,steps",
    [("JIRA_SPRINT_REPORT_SKILL.md", SPRINT_REPORT), ("JIRA_ROADMAP_SKILL.md", ROADMAP)],
)
def test_shipped_skill_is_can_do(filename, steps):
    body = (SKILLS_DIR / filename).read_text(encoding="utf-8")
    # Every tool the file names exists in the manifest.
    manifest = skills.build_manifest()
    for tool in set(re.findall(r"\b(?:jira|servicenow)_[a-z_]+", body)):
        assert tool in manifest.tool_names, tool
    check = skills.build_check(
        SkillCheckDraft(summary="Report.", steps=steps, gaps=[]), body, "PAY"
    )
    assert check.verdict == "can_do"
    assert check.gaps == []
    assert check.writes_involved is False
    assert check.likely_too_long is False
