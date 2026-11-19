"""Skill validator tests (skills design, section B), driven by shared vectors.

``fixtures/skill_validation_cases.json`` is also read by the browser validator's
tests, so both layers must agree on ok, rule ids and parsed fields.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.skills import (
    command_name_from_filename,
    is_command_name,
    normalise_project,
    sha256_hex,
    validate_skill,
)

_CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "skill_validation_cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_shared_vectors(case):
    result = validate_skill(case["filename"], case["content"])
    expect = case["expect"]
    assert result.ok is expect["ok"], result.errors
    assert sorted(result.rules) == sorted(expect["rules"])
    if "name" in expect:
        assert result.name == expect["name"]
    if "description" in expect:
        assert result.description == expect["description"]
    if "ignored_keys" in expect:
        assert result.ignored_keys == expect["ignored_keys"]


def test_vectors_cover_every_rule():
    covered = {r for c in _CASES for r in c["expect"]["rules"]}
    assert covered == {
        "filename",
        "too_large",
        "control_chars",
        "frontmatter_missing",
        "frontmatter_unclosed",
        "name_missing",
        "name_format",
        "name_mismatch",
        "description_missing",
        "description_too_long",
        "body_empty",
        "forbidden_marker",
    }


@pytest.mark.parametrize(
    "name,ok",
    [
        ("JIRA_ROADMAP", True),
        ("JIRA_SPRINT_REPORT", True),
        ("JIRA", False),
        ("jira_roadmap", False),
        ("J_ROADMAP", False),
        ("JIRA_ROADMAP_", False),
        ("JIRA__ROADMAP", False),
        ("A" * 17 + "_B", False),
        ("JIRA_" + "B" * 25, False),
    ],
)
def test_command_name(name, ok):
    assert is_command_name(name) is ok


def test_command_name_from_filename():
    assert command_name_from_filename("JIRA_ROADMAP_SKILL.md") == "JIRA_ROADMAP"
    assert command_name_from_filename("JIRA_SKILL.md") is None
    assert command_name_from_filename("JIRA_ROADMAP.md") is None


def test_expected_name_mismatch_adds_filename_rule():
    content = "---\nname: jira-roadmap\ndescription: x\n---\nbody\n"
    result = validate_skill("JIRA_ROADMAP_SKILL.md", content, expected_name="JIRA_OTHER")
    assert result.rules == ["filename"]


def test_normalised_content_and_sha():
    content = "\ufeff---\r\nname: jira-roadmap\r\ndescription: x\r\n---\r\nbody\r\n"
    result = validate_skill("JIRA_ROADMAP_SKILL.md", content)
    assert result.ok
    assert result.content == "---\nname: jira-roadmap\ndescription: x\n---\nbody\n"
    assert result.body == "body"
    assert sha256_hex(result.content) == sha256_hex(result.content.replace("\n", "\n"))
    assert len(sha256_hex("x")) == 64


def test_allowed_tools_warning():
    content = "---\nname: jira-roadmap\ndescription: x\nallowed-tools: a\n---\nbody\n"
    result = validate_skill("JIRA_ROADMAP_SKILL.md", content)
    assert result.ok
    assert any("allowed-tools" in w for w in result.warnings)


def test_lone_surrogate_is_rejected_not_raised():
    result = validate_skill("JIRA_ROADMAP_SKILL.md", "---\n\ud800")
    assert "control_chars" in result.rules


def test_normalise_project():
    assert normalise_project(" pay ") == "PAY"
    assert normalise_project("XYZ") is None
    assert normalise_project("") is None
