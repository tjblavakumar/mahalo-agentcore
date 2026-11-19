"""Agent <-> API contract for skills (design E.3).

The API models live in ``api/app`` (pydantic only, stdlib only for ``app.skills``)
so they load here without the API's own virtualenv. The router tests need
FastAPI; they are skipped where it is not installed (the agent venv) and run
where both packages are importable.
"""

from __future__ import annotations

import json
import sys
import typing
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

import agent.runtime_app as ra
from agent import skills
from agent.skills import DraftStep, SkillCheckDraft

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "frontend" / "src" / "lib" / "skills" / "__fixtures__"

if str(REPO_ROOT / "api") not in sys.path:
    sys.path.append(str(REPO_ROOT / "api"))

from app import models as api_models  # noqa: E402
from app import skills as api_skills  # noqa: E402

BODY = "# Report\nRead the sprint.\n"


class _Ctx:
    session_id = "S1"


def _keys(model: type[BaseModel]):
    """Recursive key structure: ``{field: nested keys or None}``."""
    out = {}
    for name, field in model.model_fields.items():
        nested = None
        stack = [field.annotation]
        while stack:
            ann = stack.pop()
            if isinstance(ann, type) and issubclass(ann, BaseModel):
                nested = _keys(ann)
            else:
                stack.extend(typing.get_args(ann))
        out[name] = nested
    return out


def _json_keys(value):
    if isinstance(value, dict):
        return {k: _json_keys(v) for k, v in value.items()}
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return _json_keys(value[0])
    return None


# --- real handler output --------------------------------------------------- #


class _CheckResult:
    def __init__(self, draft):
        self.structured_output = draft


def _check_out(monkeypatch):
    draft = SkillCheckDraft(
        summary="Reports on a sprint.",
        steps=[
            DraftStep(
                text="Read sprint", systems=["jira"],
                tools=["jira_get_sprint_info", "jira_update_story"], est_calls=2,
            )
        ],
        gaps=[],
    )
    monkeypatch.setattr(
        ra, "_build_check_agent", lambda m: (lambda msg, **kw: _CheckResult(draft))
    )
    payload = {
        "action": "skill_check", "skill_name": "JIRA_SPRINT_REPORT",
        "skill_body": BODY, "project": "PAY",
    }
    return ra.invoke(payload, _Ctx())


class _Text:
    stop_reason = "end_turn"
    interrupts: list = []

    def __init__(self, text):
        self._text = text

    def __str__(self):
        return self._text


class _OkAgent:
    hooks = SimpleNamespace(add_hook=lambda h: None)

    def __call__(self, prompt):
        return _Text("Done")


RUN_PAYLOAD = {
    "action": "skill_run", "skill_name": "JIRA_SPRINT_REPORT", "skill_body": BODY,
    "project": "PAY", "developer_id": "dev-6", "role": "developer",
    "review_model_id": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
}


def _run_out(monkeypatch, payload=None):
    monkeypatch.setattr(
        ra, "build_and_attach", lambda *a, **k: SimpleNamespace(agent=_OkAgent(), mcp_client=None)
    )
    return ra.invoke(dict(payload or RUN_PAYLOAD), _Ctx())

def test_check_output_validates_against_strict_api_model(monkeypatch):
    out = _check_out(monkeypatch)
    assert out["status"] == "complete"
    check = api_models.SkillCheck.model_validate(out["skill_check"])
    assert check.model_dump() == out["skill_check"]
    assert check.writes_involved is True


def test_run_output_validates_against_strict_api_model(monkeypatch):
    out = _run_out(monkeypatch)
    info = api_models.SkillRunInfo.model_validate(out["skill_run"])
    assert info.model_dump() == out["skill_run"]
    resp = api_models.ChatResponse(
        response=out["response"], proposal=out["proposal"], session_id=out["session_id"],
        status=out["status"], stages=out.get("stages"), review=out.get("review"),
        skill_run=info,
    )
    assert resp.stages is None and resp.review is None


def test_api_models_reject_renamed_or_extra_keys(monkeypatch):
    bad = dict(_check_out(monkeypatch)["skill_check"], extra_key=1)
    with pytest.raises(Exception):
        api_models.SkillCheck.model_validate(bad)
    renamed = dict(_run_out(monkeypatch)["skill_run"])
    renamed["calls"] = renamed.pop("tool_calls_used")
    with pytest.raises(Exception):
        api_models.SkillRunInfo.model_validate(renamed)


# --- key sets and constants ------------------------------------------------- #


def test_skill_check_key_sets_equal_recursively():
    assert _keys(skills.SkillCheck) == _keys(api_models.SkillCheck)


def test_skill_run_info_key_sets_equal():
    assert _keys(skills.SkillRunInfo) == _keys(api_models.SkillRunInfo)


def test_constants_equal_between_layers():
    assert skills.SKILL_PROJECTS == api_skills.SKILL_PROJECTS
    assert skills.MAX_SKILL_BYTES == api_skills.MAX_SKILL_BYTES
    assert skills.MAX_USER_SKILLS == api_skills.MAX_USER_SKILLS
    assert skills.TOOL_CALL_BUDGET == api_skills.TOOL_CALL_BUDGET
    assert skills.COMMAND_NAME_RE.pattern == api_skills.COMMAND_NAME_RE.pattern
    assert skills.MAX_COMMAND_NAME_LEN == api_skills.MAX_COMMAND_NAME_LEN
    assert skills.SYSTEM_MARKER_RE.pattern == api_skills.SYSTEM_MARKER_RE.pattern
    assert skills.SKILL_DELIMITER == api_skills.SKILL_DELIMITER


def test_gap_kind_and_verdict_literals_equal():
    for name in ("kind", "severity"):
        a = typing.get_args(skills.SkillCheckGap.model_fields[name].annotation)
        b = typing.get_args(api_models.SkillCheckGap.model_fields[name].annotation)
        assert a == b
    assert typing.get_args(skills.SkillCheck.model_fields["verdict"].annotation) == typing.get_args(
        api_models.SkillCheck.model_fields["verdict"].annotation
    )
    assert tuple(typing.get_args(skills.SkillCheckGap.model_fields["kind"].annotation)) == skills.GAP_KINDS


# --- golden fixtures (shared with the frontend tests) ------------------------ #


def _golden(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_golden_skill_check_loads_in_both_layers():
    data = _golden("skill_check.golden.json")
    api_models.SkillCheck.model_validate(data)
    skills.SkillCheck.model_validate(data)
    assert _json_keys(data) == _json_keys(skills.SkillCheck(**data).model_dump())


def test_golden_skill_run_loads_in_both_layers():
    data = _golden("skill_run.golden.json")
    api_models.SkillRunInfo.model_validate(data)
    skills.SkillRunInfo.model_validate(data)


def test_golden_list_and_put_load_in_api_models():
    api_models.SkillsListResponse.model_validate(_golden("skills_list.golden.json"))
    api_models.SkillPutResponse.model_validate(_golden("skill_put.golden.json"))


# --- real router functions (needs FastAPI) ----------------------------------- #


@pytest.fixture
def router(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("botocore")
    from app.auth import Identity
    from app.routers import chat as chat_router
    from app.routers import skills as router_mod

    monkeypatch.setattr(chat_router, "_review_model_id", lambda ident: "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    monkeypatch.setattr(
        router_mod,
        "_load_skill",
        lambda name: {
            "name": name, "description": "d", "content_sha256": "a" * 64,
            "builtin": True, "body": BODY,
        },
    )
    return SimpleNamespace(mod=router_mod, ident=Identity(developer_id="dev-6", role="developer"))


def _assert_no_none(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            if k in ("error", "proposal", "stages", "review", "updated_at", "updated_by"):
                continue
            _assert_no_none(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _assert_no_none(v, f"{path}[{i}]")
    else:
        assert value is not None, f"{path} is None"


def test_router_check_round_trip_and_request_direction(monkeypatch, router):
    captured = {}

    def fake_invoke(*, session_id, body, runtime_user_id=None):
        captured.update(body)
        return _check_out(monkeypatch)

    monkeypatch.setattr(router.mod, "invoke_runtime", fake_invoke)
    resp = router.mod.check_skill(
        router.mod.SkillCheckRequest(name="JIRA_SPRINT_REPORT", project="pay"), router.ident
    )
    assert resp.status == "complete"
    dumped = resp.model_dump(exclude={"error"})
    _assert_no_none(dumped)
    assert dumped["skill_check"]["steps"][0]["tools"] == ["jira_get_sprint_info", "jira_update_story"]
    assert set(captured) == {"action", "skill_name", "skill_body", "project"}
    # The exact dict the API sends is accepted by the Runtime (no bad_* error).
    monkeypatch.setattr(ra, "_build_check_agent", lambda m: (lambda msg, **kw: _CheckResult(
        SkillCheckDraft(summary="s", steps=[DraftStep(text="t")]))))
    assert ra.invoke(dict(captured), _Ctx())["status"] == "complete"


def test_router_run_round_trip_and_request_direction(monkeypatch, router):
    captured = {}

    def fake_invoke(*, session_id, body, runtime_user_id=None):
        captured.update(body)
        return _run_out(monkeypatch)

    monkeypatch.setattr(router.mod, "invoke_runtime", fake_invoke)
    req = router.mod.SkillRunRequest(
        name="JIRA_SPRINT_REPORT", project="PAY", content_sha256="a" * 64, consented=True
    )
    resp = router.mod.run_skill(req, router.ident)
    assert resp.status == "complete" and resp.skill_run is not None
    assert resp.skill_run.tool_call_budget == 20
    assert resp.stages is None and resp.review is None
    assert set(captured) == {
        "action", "skill_name", "skill_body", "project", "developer_id", "role",
        "review_model_id",
    }
    # Feed the exact API body to the Runtime: no bad_* error.
    assert _run_out(monkeypatch, captured)["status"] == "complete"