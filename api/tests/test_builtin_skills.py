"""The two shipped built-in skills (skills design, Example skills), offline."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app import builtin_skills
from app.main import app
from app.routers import skills as skills_router
from app.skills import MAX_DESCRIPTION_CHARS, MAX_SKILL_BYTES, validate_skill

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
FILES = ["JIRA_ROADMAP_SKILL.md", "JIRA_SPRINT_REPORT_SKILL.md"]

# Mirror of agent.approval.WRITE_TOOL_NAMES (the API cannot import the agent).
_WRITE_TOOLS = [
    "jira_create_story", "jira_update_story", "github_create_branch",
    "github_commit_files", "github_open_pull_request", "servicenow_create_incident",
]


def _text(filename: str) -> str:
    return (SKILLS_DIR / filename).read_bytes().decode("utf-8")


@pytest.mark.parametrize("filename", FILES)
def test_builtin_validates_and_matches_filename(filename):
    text = _text(filename)
    result = validate_skill(filename, text)
    assert result.ok, result.rules
    expected = filename.removesuffix("_SKILL.md").lower().replace("_", "-")
    assert re.search(rf"^name: {re.escape(expected)}$", text, re.MULTILINE)
    assert 0 < len(result.description) <= MAX_DESCRIPTION_CHARS
    assert len(text.encode("utf-8")) < MAX_SKILL_BYTES
    assert "\r" not in text


@pytest.mark.parametrize("filename", FILES)
def test_builtin_names_no_write_tool(filename):
    text = _text(filename)
    for name in _WRITE_TOOLS:
        assert not re.search(rf"(?<![A-Za-z0-9_]){name}(?![A-Za-z0-9_])", text), name


def test_write_tool_mirror_matches_agent_list():
    source = (Path(__file__).resolve().parents[2] / "agent" / "approval.py").read_text(encoding="utf-8")
    for name in _WRITE_TOOLS:
        assert f'"{name}"' in source, name


def test_router_lists_both_from_repo_skills_dir(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setattr(
        builtin_skills, "settings", dataclasses.replace(builtin_skills.settings, skills_dir=str(SKILLS_DIR))
    )
    builtin_skills.reset_cache()
    try:
        with mock_aws():
            boto3.client("dynamodb", region_name="us-east-1").create_table(
                TableName="mahalo-skills",
                KeySchema=[
                    {"AttributeName": "libraryId", "KeyType": "HASH"},
                    {"AttributeName": "skillName", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "libraryId", "AttributeType": "S"},
                    {"AttributeName": "skillName", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            skills_router._table = None
            try:
                body = TestClient(app).get("/skills").json()
            finally:
                skills_router._table = None
        listed = {s["name"]: s for s in body["skills"]}
        assert {"JIRA_ROADMAP", "JIRA_SPRINT_REPORT"} <= set(listed)
        assert listed["JIRA_ROADMAP"]["builtin"] and listed["JIRA_SPRINT_REPORT"]["builtin"]
    finally:
        builtin_skills.reset_cache()
