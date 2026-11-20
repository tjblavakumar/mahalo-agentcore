"""JIRA_ROADMAP run path: the answer is the code-computed plan only, with fixed failure messages."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[2]
for extra in (_REPO / "tools-lambdas", _REPO / "api"):
    if str(extra) not in sys.path:
        sys.path.append(str(extra))

from app import models as api_models  # noqa: E402
from servicenow import seed_data as snow_seed  # noqa: E402

import agent.runtime_app as ra  # noqa: E402
from agent import roadmap, skills  # noqa: E402
from agent.tests.test_roadmap_plan import _seed  # noqa: E402


class _Ctx:
    session_id = "S1"


def _payload(name="JIRA_ROADMAP", project="PAY", body="# Roadmap\nPlan.\n"):
    return {
        "action": "skill_run", "skill_name": name, "skill_body": body, "project": project,
        "developer_id": "dev-6", "role": "developer",
    }


def _install(monkeypatch, *, project="PAY", fetch_error=None, calls=5):
    def fake_fetch(p):
        if fetch_error:
            raise fetch_error
        return _seed(p), calls

    monkeypatch.setattr(ra.roadmap_fetch, "fetch_sources", fake_fetch)
    # The roadmap answer is code only: building any model agent or chat turn is a bug.
    monkeypatch.setattr(ra, "Agent", lambda *a, **k: pytest.fail("roadmap path must not build a model agent"))
    monkeypatch.setattr(
        ra, "_build_bedrock_model", lambda *a, **k: pytest.fail("roadmap path must not build a model")
    )
    monkeypatch.setattr(
        ra, "build_and_attach", lambda *a, **k: pytest.fail("roadmap path must not build a tool agent")
    )
    monkeypatch.setattr(ra, "_handle_chat", lambda *a, **k: pytest.fail("roadmap path must not chat"))


def _plan_md(project="PAY"):
    src = _seed(project)
    plan = roadmap.compute_plan(
        project, src["sprints"], src["stories"], src["developers"], src["incidents"], src["deployments"]
    )
    return roadmap.render_plan(plan)


# --- run path ----------------------------------------------------------------- #


def test_response_is_exactly_the_rendered_plan(monkeypatch):
    _install(monkeypatch)
    out = ra.invoke(_payload(), _Ctx())
    assert out["status"] == "complete" and out["error"] is None and out["proposal"] is None
    assert out["response"] == _plan_md()
    assert "stages" not in out and "review" not in out
    assert out["skill_run"]["tool_calls_used"] == 5
    assert out["skill_run"]["name"] == "JIRA_ROADMAP" and out["skill_run"]["project"] == "PAY"


def test_identical_input_gives_identical_answer(monkeypatch):
    _install(monkeypatch)
    first = ra.invoke(_payload(), _Ctx())["response"]
    second = ra.invoke(_payload(), _Ctx())["response"]
    assert first == second


def test_run_succeeds_even_when_the_deadline_is_tiny(monkeypatch):
    # No model call means nothing waits on Bedrock: a run completes regardless of the model deadline.
    _install(monkeypatch)
    monkeypatch.setattr(skills, "RUN_DEADLINE_S", 0.001)
    out = ra.invoke(_payload(), _Ctx())
    assert out["status"] == "complete" and out["response"] == _plan_md()


def test_fetch_failure_fixed_message_no_model_call(monkeypatch):
    err = roadmap.PlanUnavailable(roadmap.source_unreadable_message("Jira stories"))
    err.calls = 2
    _install(monkeypatch, fetch_error=err)
    out = ra.invoke(_payload(), _Ctx())
    assert out["status"] == "complete"
    assert out["response"] == (
        "Roadmap could not be computed: Jira stories could not be read. Nothing was changed. Try again."
    )
    assert out["skill_run"]["tool_calls_used"] == 2


def test_no_velocity_returns_fixed_message(monkeypatch):
    _install(monkeypatch)

    def fetch(p):
        src = _seed(p)
        for s in src["sprints"]:
            s["velocity"] = None
        return src, 5

    monkeypatch.setattr(ra.roadmap_fetch, "fetch_sources", fetch)
    out = ra.invoke(_payload(), _Ctx())
    assert out["response"].startswith("Capacity cannot be sized: no completed sprint has a recorded velocity.")
    assert "| Story | Points | Priority |" in out["response"]


def test_unexpected_error_before_plan_is_reported_by_invoke(monkeypatch):
    _install(monkeypatch)

    def boom(p):
        raise KeyError("unexpected")

    monkeypatch.setattr(ra.roadmap_fetch, "fetch_sources", boom)
    out = ra.invoke(_payload(), _Ctx())
    assert out["status"] == "error" and out["error"]["type"] == "invocation_error"


def test_cart_run(monkeypatch):
    _install(monkeypatch)
    out = ra.invoke(_payload(project="CART"), _Ctx())
    assert "## Sprint A (proposed): 26 of 26 points" in out["response"]
    assert "## Sprint B (proposed): 5 of 26 points" in out["response"]


def test_validation_still_runs_first(monkeypatch):
    _install(monkeypatch)
    out = ra.invoke(_payload(project="NOPE"), _Ctx())
    assert out["error"]["type"] == "bad_project"


# --- other skills and chat are unchanged -------------------------------------- #


def test_sprint_report_still_goes_through_chat(monkeypatch):
    seen = {}

    def fake_chat(payload, session_id, **kw):
        seen["prompt"] = payload["prompt"]
        return {"status": "complete", "response": "REPORT", "proposal": None,
                "session_id": session_id, "error": None}

    monkeypatch.setattr(ra, "_handle_chat", fake_chat)
    monkeypatch.setattr(ra.roadmap_fetch, "fetch_sources", lambda p: pytest.fail("no fetch"))
    out = ra.invoke(_payload("JIRA_SPRINT_REPORT", body="# Report\nRead.\n"), _Ctx())
    assert out["response"] == "REPORT" and "skill_run" in out
    assert seen["prompt"].startswith("[SKILL MODE]\n")
    assert "saved team skill JIRA_SPRINT_REPORT for project PAY" in seen["prompt"]


def test_chat_envelopes_unchanged():
    empty = ra._handle_chat({"prompt": "  "}, "S1")
    assert empty["status"] == "error" and empty["error"]["type"] == "bad_prompt"
    big = ra._handle_chat({"prompt": "x" * (32 * 1024 + 1)}, "S1")
    assert big["status"] == "error" and big["error"]["type"] == "prompt_too_large"


# --- contract: nothing new crosses layers -------------------------------------- #


def _validate(out):
    info = api_models.SkillRunInfo.model_validate(out["skill_run"])
    assert info.model_dump() == out["skill_run"]
    resp = api_models.ChatResponse(
        response=out["response"], proposal=out["proposal"], session_id=out["session_id"],
        status=out["status"], stages=out.get("stages"), review=out.get("review"), skill_run=info,
    )
    assert resp.status == "complete"


def test_success_envelope_validates_against_api_models(monkeypatch):
    _install(monkeypatch)
    _validate(ra.invoke(_payload(), _Ctx()))


def test_failure_envelope_validates_against_api_models(monkeypatch):
    _install(monkeypatch, fetch_error=roadmap.PlanUnavailable("x"))
    _validate(ra.invoke(_payload(), _Ctx()))


def test_skill_run_key_set_unchanged():
    assert set(skills.SkillRunInfo.model_fields) == set(api_models.SkillRunInfo.model_fields)


# --- skills constants ----------------------------------------------------------- #


def test_project_service_matches_seed():
    assert skills.PROJECT_SERVICE == {s["project_id"]: s["id"] for s in snow_seed.SERVICES}
    assert tuple(skills.PROJECT_SERVICE) == skills.SKILL_PROJECTS


def test_computed_skills_name_an_existing_builtin():
    for name in skills.COMPUTED_SKILLS:
        assert (_REPO / "skills" / f"{name}_SKILL.md").is_file()


def test_notes_machinery_is_gone():
    # The Notes paragraph was dropped by user decision: none of its parts may come back silently.
    assert not hasattr(ra, "_build_notes_agent") and not hasattr(ra, "_roadmap_notes")
    assert not hasattr(skills, "build_roadmap_notes_prompt")
    assert not hasattr(roadmap, "check_narrative")
