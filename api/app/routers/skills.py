"""Skills router: the shared skill library plus check and run (design E.2).

Built-ins (packaged files) are read-only and listed alongside user rows in the
``mahalo-skills`` table. The table is built lazily so importing this module is
offline-safe. Every error has the body ``{detail:{code,message,errors?}}``;
FastAPI request-validation 422s keep their default body.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal, Optional

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field, ValidationError, field_validator

from app import builtin_skills
from app.auth import Identity, current_identity
from app.config import settings
from app.models import (
    ChatResponse,
    SkillCheck,
    SkillCheckError,
    SkillCheckResponse,
    SkillCheckSkill,
    SkillDetail,
    SkillLimits,
    SkillPutResponse,
    SkillRunInfo,
    SkillsListResponse,
    SkillSummary,
)
from app.routers import chat as chat_router
from app.runtime_client import invoke_runtime
from app.skills import (
    COMMAND_NAME_PATTERN,
    LIBRARY_ID,
    MAX_COMMAND_NAME_LEN,
    MAX_SKILL_BYTES,
    MAX_USER_SKILLS,
    SKILL_PROJECTS,
    TOOL_CALL_BUDGET,
    is_command_name,
    normalise_project,
    sha256_hex,
    validate_skill,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skills", tags=["skills"])

_table = None
_shadow_warned = False

NamePath = Annotated[str, Path(pattern=COMMAND_NAME_PATTERN, max_length=MAX_COMMAND_NAME_LEN)]
_LIST_ATTRS = ["skillName", "description", "contentSha256", "sizeBytes", "updatedAt", "updatedBy"]


def _get_table():
    """Build the boto3 DynamoDB resource Table once, on first use (not import)."""
    global _table
    if _table is None:
        import boto3

        resource = boto3.resource("dynamodb", region_name=settings.region)
        _table = resource.Table(settings.skills_table)
    return _table


def _err(status: int, code: str, message: str, errors: list[dict] | None = None):
    detail: dict = {"code": code, "message": message}
    if errors is not None:
        detail["errors"] = errors
    return HTTPException(status_code=status, detail=detail)


def _upstream(message: str, exc: Exception):
    logger.exception(message)
    return _err(502, "upstream_error", message)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _int(value) -> int:
    return int(value) if isinstance(value, (int, Decimal)) else 0


def _builtin_summary(b: builtin_skills.BuiltinSkill) -> SkillSummary:
    return SkillSummary(
        name=b.name,
        description=b.description,
        builtin=True,
        size_bytes=b.size_bytes,
        content_sha256=b.content_sha256,
    )


def _builtin_detail(b: builtin_skills.BuiltinSkill) -> SkillDetail:
    return SkillDetail(
        **_builtin_summary(b).model_dump(), filename=b.filename, content=b.content
    )


def _user_summary(item: dict) -> SkillSummary:
    return SkillSummary(
        name=item["skillName"],
        description=item.get("description", ""),
        builtin=False,
        size_bytes=_int(item.get("sizeBytes")),
        content_sha256=item.get("contentSha256", ""),
        updated_at=item.get("updatedAt"),
        updated_by=item.get("updatedBy"),
    )


def _user_detail(item: dict) -> SkillDetail:
    return SkillDetail(
        **_user_summary(item).model_dump(),
        filename=f"{item['skillName']}_SKILL.md",
        content=item["content"],
    )


def _warn_shadowed(user_names: set[str], builtins: dict) -> None:
    global _shadow_warned
    shadowed = sorted(user_names & set(builtins))
    if shadowed and not _shadow_warned:
        _shadow_warned = True
        logger.warning("User skills shadowed by built-ins: %s", ", ".join(shadowed))


def _load_skill(name: str) -> dict:
    """Return ``{name, description, content_sha256, builtin, body}`` or raise 404/502."""
    builtins = builtin_skills.load_builtins()
    if name in builtins:
        b = builtins[name]
        return {
            "name": name,
            "description": b.description,
            "content_sha256": b.content_sha256,
            "builtin": True,
            "body": b.body,
        }
    try:
        item = _get_table().get_item(Key={"libraryId": LIBRARY_ID, "skillName": name}).get("Item")
    except (BotoCoreError, ClientError) as exc:
        raise _upstream("Skills read failed", exc)
    if not item:
        raise _err(404, "skill_not_found", "Skill not found")
    parsed = validate_skill(f"{name}_SKILL.md", item["content"])
    return {
        "name": name,
        "description": item.get("description", ""),
        "content_sha256": item.get("contentSha256", ""),
        "builtin": False,
        "body": parsed.body,
    }


def _count_user_skills() -> int:
    table = _get_table()
    total, start = 0, None
    while True:
        kwargs: dict = {
            "KeyConditionExpression": "libraryId = :l",
            "ExpressionAttributeValues": {":l": LIBRARY_ID},
            "Select": "COUNT",
        }
        if start:
            kwargs["ExclusiveStartKey"] = start
        resp = table.query(**kwargs)
        total += resp.get("Count", 0)
        start = resp.get("LastEvaluatedKey")
        if not start:
            return total


# --- Request bodies -----------------------------------------------------------


class SkillPutRequest(BaseModel):
    filename: str
    content: str
    overwrite: bool = False


def _check_project(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    project = normalise_project(value)
    if project is None:
        raise ValueError(f"project must be one of {', '.join(SKILL_PROJECTS)}")
    return project


def _check_name(value: str) -> str:
    if not is_command_name(value):
        raise ValueError("name is not a valid skill command name")
    return value


class SkillCheckRequest(BaseModel):
    name: str
    project: Optional[str] = None
    session_id: Optional[str] = None

    _name = field_validator("name")(_check_name)
    _project = field_validator("project")(_check_project)


class SkillRunRequest(BaseModel):
    name: str
    project: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consented: Literal[True]
    session_id: Optional[str] = None

    _name = field_validator("name")(_check_name)
    _project = field_validator("project")(_check_project)


# --- Library endpoints --------------------------------------------------------


@router.get("", response_model=SkillsListResponse)
def list_skills(ident: Identity = Depends(current_identity)) -> SkillsListResponse:
    """List built-in and user skills (no ``content``)."""
    builtins = builtin_skills.load_builtins()
    table = _get_table()
    items: list[dict] = []
    start = None
    try:
        while True:
            kwargs: dict = {
                "KeyConditionExpression": "libraryId = :l",
                "ExpressionAttributeValues": {":l": LIBRARY_ID},
                "ProjectionExpression": ", ".join(f"#{i}" for i in range(len(_LIST_ATTRS))),
                "ExpressionAttributeNames": {f"#{i}": a for i, a in enumerate(_LIST_ATTRS)},
            }
            if start:
                kwargs["ExclusiveStartKey"] = start
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            start = resp.get("LastEvaluatedKey")
            if not start:
                break
    except (BotoCoreError, ClientError) as exc:
        raise _upstream("Skills read failed", exc)
    _warn_shadowed({i["skillName"] for i in items}, builtins)
    skills = [_builtin_summary(builtins[n]) for n in sorted(builtins)]
    skills += [_user_summary(i) for i in items if i["skillName"] not in builtins]
    return SkillsListResponse(
        skills=skills,
        projects=list(SKILL_PROJECTS),
        limits=SkillLimits(
            max_bytes=MAX_SKILL_BYTES,
            max_user_skills=MAX_USER_SKILLS,
            tool_call_budget=TOOL_CALL_BUDGET,
        ),
    )


@router.post("/check", response_model=SkillCheckResponse)
def check_skill(
    req: SkillCheckRequest, ident: Identity = Depends(current_identity)
) -> SkillCheckResponse:
    """Ask the Runtime to plan the skill (read-only); the API copies the result."""
    skill = _load_skill(req.name)
    session_id = chat_router._runtime_session_id(req.session_id)
    try:
        out = invoke_runtime(
            session_id=session_id,
            body={
                "action": "skill_check",
                "skill_name": req.name,
                "skill_body": skill["body"],
                "project": req.project,
            },
            runtime_user_id=chat_router._runtime_user_id(ident),
        )
    except (BotoCoreError, ClientError) as exc:
        raise _upstream("Runtime invoke failed", exc)
    info = SkillCheckSkill(
        name=skill["name"],
        description=skill["description"],
        content_sha256=skill["content_sha256"],
        builtin=skill["builtin"],
    )
    sid = out.get("session_id", session_id)
    if out.get("status") == "error" or out.get("error"):
        err = out.get("error") or {}
        return SkillCheckResponse(
            status="error",
            session_id=sid,
            skill=info,
            project=req.project,
            skill_check=None,
            error=SkillCheckError(
                type=str(err.get("type", "check_failed")),
                message=str(err.get("message", "The check failed.")),
            ),
        )
    try:
        check = SkillCheck.model_validate(out.get("skill_check"))
    except ValidationError as exc:
        raise _upstream("Runtime returned an invalid skill check", exc)
    return SkillCheckResponse(
        status="complete",
        session_id=sid,
        skill=info,
        project=req.project,
        skill_check=check,
        error=None,
    )


@router.post("/run", response_model=ChatResponse)
def run_skill(req: SkillRunRequest, ident: Identity = Depends(current_identity)) -> ChatResponse:
    """Run a checked skill through the Runtime; needs consent and a matching hash."""
    skill = _load_skill(req.name)
    if skill["content_sha256"] != req.content_sha256:
        raise _err(409, "skill_changed", "This skill changed after the check. Check it again.")
    session_id = chat_router._runtime_session_id(req.session_id)
    review_model_id = chat_router._review_model_id(ident)
    try:
        out = invoke_runtime(
            session_id=session_id,
            body={
                "action": "skill_run",
                "skill_name": req.name,
                "skill_body": skill["body"],
                "project": req.project,
                "developer_id": ident.developer_id,
                "role": ident.role,
                "review_model_id": review_model_id,
            },
            runtime_user_id=chat_router._runtime_user_id(ident),
        )
    except (BotoCoreError, ClientError) as exc:
        raise _upstream("Runtime invoke failed", exc)
    status = out.get("status", "complete")
    skill_run = None
    if status in ("complete", "pending_approval"):
        try:
            skill_run = SkillRunInfo.model_validate(out.get("skill_run"))
        except ValidationError as exc:
            raise _upstream("Runtime returned an invalid skill run", exc)
    return ChatResponse(
        response=out.get("response", "") or "",
        proposal=out.get("proposal"),
        session_id=out.get("session_id", session_id),
        status=status,
        stages=out.get("stages"),
        review=out.get("review"),
        skill_run=skill_run,
    )


@router.get("/{name}", response_model=SkillDetail)
def get_skill(name: NamePath, ident: Identity = Depends(current_identity)) -> SkillDetail:
    builtins = builtin_skills.load_builtins()
    if name in builtins:
        return _builtin_detail(builtins[name])
    try:
        item = _get_table().get_item(Key={"libraryId": LIBRARY_ID, "skillName": name}).get("Item")
    except (BotoCoreError, ClientError) as exc:
        raise _upstream("Skills read failed", exc)
    if not item:
        raise _err(404, "skill_not_found", "Skill not found")
    return _user_detail(item)


@router.put("/{name}", response_model=SkillPutResponse)
def put_skill(
    name: NamePath,
    body: SkillPutRequest,
    ident: Identity = Depends(current_identity),
) -> SkillPutResponse:
    """Create or overwrite a user skill after the full server-side validation."""
    result = validate_skill(body.filename, body.content, expected_name=name)
    if not result.ok:
        raise _err(422, "invalid_skill", "The skill file is not valid.", result.errors)
    if name in builtin_skills.load_builtins():
        raise _err(
            409,
            "builtin_read_only",
            "Built-in skills are read-only. Upload under a different name.",
        )
    persona = {
        "product_manager": "pm",
        "architect": "arch",
        "developer": "dev",
        "executive": "exec",
    }.get(ident.role, "dev")
    key = {"libraryId": LIBRARY_ID, "skillName": name}
    table = _get_table()
    try:
        existing = table.get_item(Key=key).get("Item")
        if existing and not body.overwrite:
            raise _err(409, "exists", "A skill with this name already exists.")
        if not existing and _count_user_skills() >= MAX_USER_SKILLS:
            raise _err(
                409,
                "library_full",
                f"The library already holds {MAX_USER_SKILLS} skills. Delete one first.",
            )
        now = _now()
        item = {
            **key,
            "description": result.description,
            "content": result.content,
            "contentSha256": sha256_hex(result.content),
            "sizeBytes": len(result.content.encode("utf-8")),
            "createdAt": existing["createdAt"] if existing else now,
            "updatedAt": now,
            "updatedBy": persona,
        }
        kwargs = {} if existing else {"ConditionExpression": "attribute_not_exists(skillName)"}
        table.put_item(Item=item, **kwargs)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise _err(409, "exists", "A skill with this name already exists.")
        raise _upstream("Skills write failed", exc)
    except BotoCoreError as exc:
        raise _upstream("Skills write failed", exc)
    return SkillPutResponse(
        skill=_user_detail(item), created=existing is None, warnings=result.warnings
    )


@router.delete("/{name}")
def delete_skill(name: NamePath, ident: Identity = Depends(current_identity)) -> dict:
    if name in builtin_skills.load_builtins():
        raise _err(
            409,
            "builtin_read_only",
            "Built-in skills are read-only. Upload under a different name.",
        )
    try:
        resp = _get_table().delete_item(
            Key={"libraryId": LIBRARY_ID, "skillName": name}, ReturnValues="ALL_OLD"
        )
    except (BotoCoreError, ClientError) as exc:
        raise _upstream("Skills write failed", exc)
    if not resp.get("Attributes"):
        raise _err(404, "skill_not_found", "Skill not found")
    return {"deleted": name}
