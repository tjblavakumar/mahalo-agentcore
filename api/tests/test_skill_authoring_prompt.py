"""The sample skill in the agent prompt must pass the upload validator."""
from __future__ import annotations

import re
from pathlib import Path

from app.skills import MAX_SKILL_BYTES, validate_skill

PROMPTS = Path(__file__).resolve().parents[2] / "agent" / "prompts.py"


def _sample() -> str:
    text = PROMPTS.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.search(r"^````markdown\n(.*?)^````$", text, re.S | re.M)
    assert match, "sample skill block missing from agent/prompts.py"
    return match.group(1)


def test_prompt_sample_skill_passes_validate_skill():
    result = validate_skill("PRODUCTION_ISSUES_SKILL.md", _sample())
    assert result.ok, result.errors
    assert result.name == "production-issues"
    assert result.warnings == []
    assert len(_sample().encode("utf-8")) < MAX_SKILL_BYTES


def test_prompt_sample_skill_fails_under_a_wrong_file_name():
    result = validate_skill("OTHER_THING_SKILL.md", _sample())
    assert "name_mismatch" in result.rules
