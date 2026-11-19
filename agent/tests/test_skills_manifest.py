"""The capability manifest is built from the real tool descriptors (design C)."""

from __future__ import annotations

from agent import skills
from agent.approval import WRITE_TOOL_NAMES
from common import tool_schemas


def test_manifest_names_equal_tool_schema_names():
    manifest = skills.build_manifest()
    assert manifest.tool_names == set(tool_schemas.BY_NAME)
    assert len(manifest.tools) == len(tool_schemas.TOOLS)


def test_write_marks_equal_write_tool_names():
    manifest = skills.build_manifest()
    assert manifest.write_names == set(WRITE_TOOL_NAMES)
    rendered = manifest.render()
    marked = {
        line.split(" ")[1]
        for line in rendered.splitlines()
        if "WRITE (proposes a change" in line
    }
    assert marked == set(WRITE_TOOL_NAMES)


def test_cannot_do_present_and_rendered():
    manifest = skills.build_manifest()
    assert manifest.cannot_do == skills.CANNOT_DO
    assert "produce PDF, spreadsheets or any file or download" in manifest.render()
    assert "CANNOT DO" in manifest.render()


def test_descriptions_capped_and_args_listed():
    manifest = skills.build_manifest()
    assert all(len(t.description) <= 160 for t in manifest.tools)
    by_name = {t.name: t for t in manifest.tools}
    expected = tuple(tool_schemas.BY_NAME["jira_search_stories"]["input_schema"]["properties"])
    assert by_name["jira_search_stories"].args == expected


def test_manifest_follows_a_new_tool(monkeypatch):
    extra = {
        "name": "jira_new_tool", "service": "jira", "description": "New.",
        "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
    }
    monkeypatch.setattr(tool_schemas, "TOOLS", [*tool_schemas.TOOLS, extra])
    assert "jira_new_tool" in skills.build_manifest().tool_names
