"""Skills router tests (skills design, E.2 and the Error handling table), moto-backed.

Offline: ``@mock_aws`` fakes DynamoDB, ``invoke_runtime`` is patched and its
request bodies are captured. Built-ins come from a temp directory.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from moto import mock_aws

from app import builtin_skills
from app.main import app
from app.models import (
    ChatResponse,
    SkillCheck,
    SkillRunInfo,
    SkillPutResponse,
    SkillsListResponse,
)
from app.routers import skills as skills_router
from app.skills import MAX_USER_SKILLS, sha256_hex

_TABLE_NAME = "mahalo-skills"
_PM = {"X-Mahalo-Persona": "pm"}
_GOLDEN = Path(__file__).resolve().parents[2] / "frontend/src/lib/skills/__fixtures__"

_BUILTIN_TEXT = "---\nname: jira-roadmap\ndescription: Built-in roadmap\n---\nRead Jira.\n"


def _skill_text(cmd: str = "TEAM_STANDUP", desc: str = "Standup notes", body: str = "List the work.") -> str:
    return f"---\nname: {cmd.lower().replace('_', '-')}\ndescription: {desc}\n---\n{body}\n"


def _put(client, cmd="TEAM_STANDUP", content=None, overwrite=False, headers=None, filename=None):
    return client.put(
        f"/skills/{cmd}",
        json={
            "filename": filename or f"{cmd}_SKILL.md",
            "content": content if content is not None else _skill_text(cmd),
            "overwrite": overwrite,
        },
        headers=headers or _PM,
    )


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    (tmp_path / "JIRA_ROADMAP_SKILL.md").write_text(_BUILTIN_TEXT, encoding="utf-8")
    (tmp_path / "BAD_ONE_SKILL.md").write_text("no frontmatter", encoding="utf-8")
    monkeypatch.setattr(
        builtin_skills, "settings", dataclasses.replace(builtin_skills.settings, skills_dir=str(tmp_path))
    )
    builtin_skills.reset_cache()
    yield tmp_path
    builtin_skills.reset_cache()


@pytest.fixture
def table(skills_dir):
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=_TABLE_NAME,
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
        client.get_waiter("table_exists").wait(TableName=_TABLE_NAME)
        skills_router._table = None
        try:
            yield boto3.resource("dynamodb", region_name="us-east-1").Table(_TABLE_NAME)
        finally:
            skills_router._table = None


@pytest.fixture
def client(table):
    return TestClient(app)


class _BrokenTable:
    """A table whose every call raises a DynamoDB ClientError."""

    def __getattr__(self, name):
        def boom(*a, **k):
            raise ClientError({"Error": {"Code": "InternalServerError", "Message": "x"}}, name)

        return boom


@pytest.fixture
def broken(client, monkeypatch):
    monkeypatch.setattr(skills_router, "_get_table", lambda: _BrokenTable())


def _code(resp):
    return resp.json()["detail"]["code"]


# --- built-in loader -----------------------------------------------------------


def test_invalid_builtin_is_skipped_with_error_log(skills_dir, caplog):
    with caplog.at_level(logging.ERROR, logger="app.builtin_skills"):
        found = builtin_skills.load_builtins()
    assert list(found) == ["JIRA_ROADMAP"]
    assert "BAD_ONE_SKILL.md" in caplog.text


def test_builtin_loader_is_cached(skills_dir):
    first = builtin_skills.load_builtins()
    (skills_dir / "NEW_ONE_SKILL.md").write_text(_skill_text("NEW_ONE"), encoding="utf-8")
    assert builtin_skills.load_builtins() is first


# --- GET /skills ----------------------------------------------------------------


def test_list_has_builtin_user_projects_limits_and_no_content(client):
    assert _put(client).status_code == 200
    resp = client.get("/skills")
    assert resp.status_code == 200
    body = resp.json()
    SkillsListResponse.model_validate(body)
    assert [s["name"] for s in body["skills"]] == ["JIRA_ROADMAP", "TEAM_STANDUP"]
    builtin, user = body["skills"]
    assert builtin["builtin"] is True and builtin["updated_at"] is None
    assert user["builtin"] is False and user["updated_by"] == "pm"
    assert all("content" not in s for s in body["skills"])
    assert body["projects"] == ["PAY", "CART", "AUTH", "PROD", "ORD"]
    assert body["limits"] == {"max_bytes": 16384, "max_user_skills": 50, "tool_call_budget": 20}


def test_list_loops_on_last_evaluated_key(client, monkeypatch):
    pages = [
        {"Items": [{"skillName": "AAA_ONE", "description": "a", "contentSha256": "h", "sizeBytes": 1}],
         "LastEvaluatedKey": {"libraryId": "common", "skillName": "AAA_ONE"}},
        {"Items": [{"skillName": "BBB_TWO", "description": "b", "contentSha256": "h", "sizeBytes": 2}]},
    ]
    calls = []

    class _Paged:
        def query(self, **kwargs):
            calls.append(kwargs)
            return pages[len(calls) - 1]

    monkeypatch.setattr(skills_router, "_get_table", lambda: _Paged())
    names = [s["name"] for s in client.get("/skills").json()["skills"]]
    assert names == ["JIRA_ROADMAP", "AAA_ONE", "BBB_TWO"]
    assert "ExclusiveStartKey" in calls[1]
    assert "content" not in calls[0]["ExpressionAttributeNames"].values()


def test_list_hides_user_row_shadowed_by_builtin(client, table, caplog):
    table.put_item(Item={"libraryId": "common", "skillName": "JIRA_ROADMAP", "description": "user", "contentSha256": "h", "sizeBytes": 1})
    skills_router._shadow_warned = False
    with caplog.at_level(logging.WARNING, logger="app.routers.skills"):
        body = client.get("/skills").json()
    assert [(s["name"], s["builtin"]) for s in body["skills"]] == [("JIRA_ROADMAP", True)]
    assert "shadowed" in caplog.text


def test_list_dynamodb_error_is_502(broken, client):
    resp = client.get("/skills")
    assert resp.status_code == 502
    assert _code(resp) == "upstream_error"
    assert resp.json()["detail"]["message"] == "Skills read failed"


# --- GET /skills/{name} ---------------------------------------------------------


def test_get_user_and_builtin(client):
    _put(client)
    user = client.get("/skills/TEAM_STANDUP").json()
    assert user["content"] == _skill_text() and user["filename"] == "TEAM_STANDUP_SKILL.md"
    assert user["content_sha256"] == sha256_hex(_skill_text())
    builtin = client.get("/skills/JIRA_ROADMAP").json()
    assert builtin["builtin"] is True and builtin["content"] == _BUILTIN_TEXT


def test_get_unknown_is_404(client):
    resp = client.get("/skills/NOPE_SKILL_X")
    assert resp.status_code == 404
    assert resp.json()["detail"] == {"code": "skill_not_found", "message": "Skill not found"}


@pytest.mark.parametrize("name", ["lower_case", "JIRA", "A" * 70 + "_B"])
def test_get_bad_name_is_422_without_code(client, name):
    resp = client.get(f"/skills/{name}")
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)


def test_get_dynamodb_error_is_502(broken, client):
    assert client.get("/skills/TEAM_STANDUP").status_code == 502


# --- PUT /skills/{name} ---------------------------------------------------------


def test_put_creates_then_overwrite_keeps_created_at(client, table):
    first = _put(client)
    assert first.status_code == 200
    body = first.json()
    SkillPutResponse.model_validate(body)
    assert body["created"] is True and body["warnings"] == []
    assert body["skill"]["updated_by"] == "pm"
    created_at = table.get_item(Key={"libraryId": "common", "skillName": "TEAM_STANDUP"})["Item"]["createdAt"]
    table.update_item(
        Key={"libraryId": "common", "skillName": "TEAM_STANDUP"},
        UpdateExpression="SET createdAt = :c",
        ExpressionAttributeValues={":c": "2020-01-01T00:00:00Z"},
    )
    assert created_at
    second = _put(client, content=_skill_text(desc="Changed"), overwrite=True, headers={"X-Mahalo-Persona": "exec"})
    assert second.status_code == 200 and second.json()["created"] is False
    item = table.get_item(Key={"libraryId": "common", "skillName": "TEAM_STANDUP"})["Item"]
    assert item["createdAt"] == "2020-01-01T00:00:00Z"
    assert item["description"] == "Changed" and item["updatedBy"] == "exec"
    assert item["contentSha256"] == sha256_hex(item["content"])


def test_put_normalises_content_and_warns_about_ignored_keys(client):
    text = "\ufeff---\r\nname: team-standup\r\ndescription: x\r\nallowed-tools: a\r\n---\r\nbody\r\n"
    body = _put(client, content=text).json()
    assert "\r" not in body["skill"]["content"] and not body["skill"]["content"].startswith("\ufeff")
    assert any("allowed-tools" in w for w in body["warnings"])


def test_put_invalid_skill_is_422_with_errors(client, table):
    resp = _put(client, content="# no frontmatter")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_skill" and detail["message"]
    assert [e["rule"] for e in detail["errors"]] == ["frontmatter_missing"]
    assert "Item" not in table.get_item(Key={"libraryId": "common", "skillName": "TEAM_STANDUP"})


def test_put_filename_must_match_path_name(client):
    resp = _put(client, filename="OTHER_NAME_SKILL.md", content=_skill_text("OTHER_NAME"))
    assert resp.status_code == 422
    assert [e["rule"] for e in resp.json()["detail"]["errors"]] == ["filename"]


def test_put_bad_path_name_is_422_without_code(client):
    resp = client.put("/skills/lowercase", json={"filename": "x", "content": "y"}, headers=_PM)
    assert resp.status_code == 422 and isinstance(resp.json()["detail"], list)


def test_put_builtin_name_is_409(client):
    resp = _put(client, cmd="JIRA_ROADMAP", content=_BUILTIN_TEXT)
    assert resp.status_code == 409 and _code(resp) == "builtin_read_only"
    assert resp.json()["detail"]["message"].startswith("Built-in skills are read-only")


def test_put_existing_without_overwrite_is_409_exists(client):
    _put(client)
    resp = _put(client, content=_skill_text(desc="Other"))
    assert resp.status_code == 409 and _code(resp) == "exists"


def test_put_conditional_put_race_is_409_exists(client, monkeypatch):
    class _Race:
        def get_item(self, **k):
            return {}

        def query(self, **k):
            return {"Count": 0}

        def put_item(self, **k):
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "PutItem")

    monkeypatch.setattr(skills_router, "_get_table", lambda: _Race())
    resp = _put(client)
    assert resp.status_code == 409 and _code(resp) == "exists"


def test_put_library_full_on_create_only(client, table):
    for i in range(MAX_USER_SKILLS):
        table.put_item(Item={"libraryId": "common", "skillName": f"FILL_{i:02d}", "content": _skill_text(), "createdAt": "t"})
    resp = _put(client)
    assert resp.status_code == 409 and _code(resp) == "library_full"
    table.put_item(Item={"libraryId": "common", "skillName": "TEAM_STANDUP", "content": "old", "createdAt": "t"})
    assert _put(client, overwrite=True).status_code == 200


def test_put_dynamodb_error_is_502(broken, client):
    resp = _put(client)
    assert resp.status_code == 502 and _code(resp) == "upstream_error"
    assert resp.json()["detail"]["message"] == "Skills write failed"


# --- DELETE /skills/{name} ------------------------------------------------------


def test_delete_user_skill_then_404(client):
    _put(client)
    resp = client.delete("/skills/TEAM_STANDUP", headers=_PM)
    assert resp.status_code == 200 and resp.json() == {"deleted": "TEAM_STANDUP"}
    again = client.delete("/skills/TEAM_STANDUP", headers=_PM)
    assert again.status_code == 404 and _code(again) == "skill_not_found"


def test_delete_builtin_is_409(client):
    resp = client.delete("/skills/JIRA_ROADMAP", headers=_PM)
    assert resp.status_code == 409 and _code(resp) == "builtin_read_only"


def test_delete_bad_name_is_422(client):
    assert client.delete("/skills/bad", headers=_PM).status_code == 422


def test_delete_dynamodb_error_is_502(broken, client):
    assert client.delete("/skills/TEAM_STANDUP").status_code == 502


# --- POST /skills/check ---------------------------------------------------------


def _check_payload():
    return json.loads((_GOLDEN / "skill_check.golden.json").read_text(encoding="utf-8"))


@pytest.fixture
def runtime(monkeypatch):
    """Patch invoke_runtime; ``runtime.reply`` is returned, bodies are captured."""

    class _Rt:
        reply: dict = {}
        raises: Exception | None = None
        calls: list = []

    rt = _Rt()
    rt.calls = []

    def fake(*, session_id, body, runtime_user_id=None):
        rt.calls.append({"session_id": session_id, "body": body})
        if rt.raises:
            raise rt.raises
        return rt.reply

    monkeypatch.setattr(skills_router, "invoke_runtime", fake)
    return rt


def test_check_builtin_builds_runtime_payload_and_copies_result(client, runtime):
    runtime.reply = {"status": "complete", "response": "", "proposal": None, "session_id": "s" * 40, "error": None, "skill_check": _check_payload()}
    resp = client.post("/skills/check", json={"name": "JIRA_ROADMAP", "project": "pay"}, headers=_PM)
    assert resp.status_code == 200
    body = resp.json()
    assert runtime.calls[0]["body"] == {
        "action": "skill_check",
        "skill_name": "JIRA_ROADMAP",
        "skill_body": "Read Jira.",
        "project": "PAY",
    }
    assert len(runtime.calls[0]["session_id"]) >= 33
    assert body["status"] == "complete" and body["project"] == "PAY" and body["error"] is None
    assert body["skill"] == {
        "name": "JIRA_ROADMAP",
        "description": "Built-in roadmap",
        "content_sha256": sha256_hex(_BUILTIN_TEXT),
        "builtin": True,
    }
    assert body["skill_check"] == _check_payload()


def test_check_user_skill_without_project_sends_null(client, runtime):
    _put(client)
    runtime.reply = {"status": "complete", "session_id": "s" * 40, "skill_check": _check_payload()}
    resp = client.post("/skills/check", json={"name": "TEAM_STANDUP"}, headers=_PM)
    assert resp.status_code == 200 and resp.json()["project"] is None
    assert runtime.calls[0]["body"]["project"] is None
    assert runtime.calls[0]["body"]["skill_body"] == "List the work."


def test_check_unknown_skill_is_404(client, runtime):
    resp = client.post("/skills/check", json={"name": "NOPE_SKILL_X"}, headers=_PM)
    assert resp.status_code == 404 and _code(resp) == "skill_not_found"
    assert runtime.calls == []


@pytest.mark.parametrize("payload", [{"name": "JIRA_ROADMAP", "project": "XYZ"}, {"name": "jira_roadmap"}, {}])
def test_check_validation_422(client, runtime, payload):
    resp = client.post("/skills/check", json=payload, headers=_PM)
    assert resp.status_code == 422 and isinstance(resp.json()["detail"], list)
    assert runtime.calls == []


def test_check_runtime_invoke_error_is_502(client, runtime):
    runtime.raises = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "InvokeAgentRuntime")
    resp = client.post("/skills/check", json={"name": "JIRA_ROADMAP"}, headers=_PM)
    assert resp.status_code == 502 and resp.json()["detail"]["message"] == "Runtime invoke failed"


@pytest.mark.parametrize("etype", ["bad_skill", "check_failed", "check_timeout", "check_empty", "check_invalid_output"])
def test_check_error_envelope_is_200_with_error(client, runtime, etype):
    runtime.reply = {"status": "error", "response": "", "session_id": "s" * 40, "error": {"type": etype, "message": "The check took too long."}}
    resp = client.post("/skills/check", json={"name": "JIRA_ROADMAP"}, headers=_PM)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error" and body["skill_check"] is None
    assert body["error"] == {"type": etype, "message": "The check took too long."}


def test_check_malformed_runtime_result_is_502(client, runtime):
    bad = _check_payload()
    bad["surprise"] = 1
    runtime.reply = {"status": "complete", "session_id": "s" * 40, "skill_check": bad}
    assert client.post("/skills/check", json={"name": "JIRA_ROADMAP"}, headers=_PM).status_code == 502


# --- POST /skills/run -----------------------------------------------------------


def _run_payload(**over):
    payload = {
        "name": "JIRA_ROADMAP",
        "project": "PAY",
        "content_sha256": sha256_hex(_BUILTIN_TEXT),
        "consented": True,
    }
    payload.update(over)
    return payload


def _run_reply(status="complete"):
    return {
        "status": status,
        "response": "Report",
        "proposal": None,
        "session_id": "s" * 40,
        "skill_run": json.loads((_GOLDEN / "skill_run.golden.json").read_text(encoding="utf-8")),
    }


def test_run_builds_payload_and_attaches_skill_run(client, runtime):
    runtime.reply = _run_reply()
    resp = client.post("/skills/run", json=_run_payload(project="pay"), headers=_PM)
    assert resp.status_code == 200
    body = resp.json()
    assert runtime.calls[0]["body"] == {
        "action": "skill_run",
        "skill_name": "JIRA_ROADMAP",
        "skill_body": "Read Jira.",
        "project": "PAY",
        "developer_id": "dev-1",
        "role": "product_manager",
        "review_model_id": "us.amazon.nova-lite-v1:0",
    }
    assert body["status"] == "complete" and body["response"] == "Report"
    assert body["skill_run"]["tool_calls_used"] == 7
    assert body["stages"] is None and body["review"] is None


def test_run_pending_approval_also_attaches_skill_run(client, runtime):
    runtime.reply = {**_run_reply("pending_approval"), "proposal": {"interrupt_id": "i1"}}
    body = client.post("/skills/run", json=_run_payload(), headers=_PM).json()
    assert body["status"] == "pending_approval" and body["proposal"] == {"interrupt_id": "i1"}
    assert body["skill_run"]["name"] == "JIRA_ROADMAP"


def test_run_user_skill(client, runtime):
    _put(client)
    runtime.reply = _run_reply()
    resp = client.post(
        "/skills/run",
        json=_run_payload(name="TEAM_STANDUP", content_sha256=sha256_hex(_skill_text())),
        headers=_PM,
    )
    assert resp.status_code == 200 and runtime.calls[0]["body"]["skill_body"] == "List the work."


def test_run_unknown_skill_is_404(client, runtime):
    resp = client.post("/skills/run", json=_run_payload(name="NOPE_SKILL_X"), headers=_PM)
    assert resp.status_code == 404 and _code(resp) == "skill_not_found"


def test_run_hash_mismatch_is_409_skill_changed(client, runtime):
    resp = client.post("/skills/run", json=_run_payload(content_sha256="0" * 64), headers=_PM)
    assert resp.status_code == 409 and _code(resp) == "skill_changed"
    assert runtime.calls == []


@pytest.mark.parametrize(
    "over",
    [
        {"consented": False},
        {"consented": "yes"},
        {"project": "XYZ"},
        {"content_sha256": "ABC"},
        {"name": "bad name"},
    ],
)
def test_run_validation_422(client, runtime, over):
    resp = client.post("/skills/run", json=_run_payload(**over), headers=_PM)
    assert resp.status_code == 422 and isinstance(resp.json()["detail"], list)


@pytest.mark.parametrize("missing", ["project", "consented", "content_sha256"])
def test_run_missing_required_field_is_422(client, runtime, missing):
    payload = _run_payload()
    del payload[missing]
    assert client.post("/skills/run", json=payload, headers=_PM).status_code == 422
    assert runtime.calls == []


def test_run_runtime_invoke_error_is_502(client, runtime):
    runtime.raises = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "InvokeAgentRuntime")
    resp = client.post("/skills/run", json=_run_payload(), headers=_PM)
    assert resp.status_code == 502 and _code(resp) == "upstream_error"


def test_run_runtime_error_envelope_is_200_status_error(client, runtime):
    runtime.reply = {"status": "error", "response": "", "session_id": "s" * 40, "error": {"type": "bad_skill", "message": "m"}}
    resp = client.post("/skills/run", json=_run_payload(), headers=_PM)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error" and body["response"] == "" and body["skill_run"] is None


def test_run_missing_skill_run_on_complete_is_502(client, runtime):
    runtime.reply = {"status": "complete", "response": "x", "session_id": "s" * 40}
    assert client.post("/skills/run", json=_run_payload(), headers=_PM).status_code == 502


# --- Golden fixtures (shared with the browser tests) ----------------------------


def _golden(name: str):
    return json.loads((_GOLDEN / name).read_text(encoding="utf-8"))


def test_golden_skill_check():
    SkillCheck.model_validate(_golden("skill_check.golden.json"))


def test_golden_skill_run():
    SkillRunInfo.model_validate(_golden("skill_run.golden.json"))


def test_golden_skills_list():
    SkillsListResponse.model_validate(_golden("skills_list.golden.json"))


def test_golden_skill_put():
    SkillPutResponse.model_validate(_golden("skill_put.golden.json"))


def test_chat_response_still_accepts_extra_keys_and_no_skill_run():
    resp = ChatResponse(response="x", session_id="s", status="complete", error={"type": "t"})
    assert resp.skill_run is None
