"""Jira mock routes ported from mahalo-dock jira/main.py.

Behavior-equivalent to the FastAPI mock: same verbs, paths, bodies, status
codes, and JSON shapes. State lives in DynamoDB via :class:`Store` with these
collections (``pk``):

    DEVELOPER, PROJECT, SPRINT, STORY   (natural id under ``sk``; record under ``data``)
    ACTIVITY                            (timestamped log of assignment, status and comment changes)
"""

import logging
from datetime import datetime, timedelta, timezone

from common.auth import require_token
from common import seed_dates
from common.responses import error, json_response
from common.router import Router

from . import seed_data

PK_DEVELOPER = "DEVELOPER"
PK_PROJECT = "PROJECT"
PK_SPRINT = "SPRINT"
PK_STORY = "STORY"
PK_ACTIVITY = "ACTIVITY"
MAX_COMMENT_CHARS = 2000
ACTIVITY_TEXT_CHARS = 200
ACTIVITY_DEFAULT_DAYS = 7
_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"

logger = logging.getLogger(__name__)


def seed_items():
    """Yield the seed items for lazy table seeding (deep-copied by the store)."""
    days = seed_dates.compute_shift_days(seed_dates.today_utc())
    sprints = seed_dates.shift_records(seed_data.SPRINTS, days, ("start_date", "end_date"))
    stories = seed_dates.shift_story_comments(seed_data.STORIES, days)
    for dev in seed_data.DEVELOPERS:
        yield {"pk": PK_DEVELOPER, "sk": dev["id"], "record": dev}
    for proj in seed_data.PROJECTS:
        yield {"pk": PK_PROJECT, "sk": proj["id"], "record": proj}
    for sprint in sprints:
        yield {"pk": PK_SPRINT, "sk": sprint["id"], "record": sprint}
    for story in stories:
        yield {"pk": PK_STORY, "sk": story["id"], "record": story}
    # Demo activity: offsets from the moment of seeding, matched to the story records.
    now = datetime.now(timezone.utc).replace(microsecond=0)
    for item in seed_data.recent_activity(now, stories):
        sk = f"demo#{item['ts']}#{item['story_id']}#{item['type']}"
        yield {"pk": PK_ACTIVITY, "sk": sk, "record": item}


def _log_activity(store, story, kind, actor=None, to=None, frm=None, text=None):
    """Append one ACTIVITY item. Never raises: a failed log must not fail the write."""
    try:
        ts = datetime.now(timezone.utc).strftime(_TS_FMT)
        item = {
            "ts": ts,
            "story_id": story["id"],
            "project_id": story["project_id"],
            "type": kind,
            "actor": actor,
            "to": to,
            "from": frm,
            "text": text[:ACTIVITY_TEXT_CHARS] if text else None,
            "origin": "write",
        }
        store.put(PK_ACTIVITY, f"{ts}#{story['id']}#{kind}", item)
    except Exception:
        logger.warning("activity log failed for %s", story.get("id"))


def build_router(store, token):
    router = Router()

    def _auth(request):
        if not require_token(request, token):
            return error(401, "Invalid API token")
        return None

    # --- Health ---

    @router.route("GET", "/health")
    def health(request):
        return json_response(200, {"status": "healthy", "service": "mock-jira", "version": "1.0.0"})

    # --- Projects ---

    @router.route("GET", "/projects")
    def list_projects(request):
        denied = _auth(request)
        if denied:
            return denied
        return json_response(200, {"projects": store.query(PK_PROJECT)})

    @router.route("POST", "/projects")
    def create_project(request):
        denied = _auth(request)
        if denied:
            return denied
        project = request.json_body or {}
        project_id = str(project.get("id") or project.get("project_id") or "PROJ").upper()
        if store.exists(PK_PROJECT, project_id):
            return error(409, "Project already exists")
        new_project = {
            "id": project_id,
            "name": project.get("name") or project_id,
            "description": project.get("description") or "",
            "status": project.get("status") or "active",
            "lead": project.get("lead") or "dev-1",
        }
        store.put(PK_PROJECT, project_id, new_project)
        return json_response(201, new_project)

    @router.route("GET", "/projects/{project_id}")
    def get_project(request):
        denied = _auth(request)
        if denied:
            return denied
        project = store.get(PK_PROJECT, request.path_params["project_id"])
        if not project:
            return error(404, "Project not found")
        return json_response(200, project)

    @router.route("GET", "/projects/{project_id}/board")
    def get_board(request):
        denied = _auth(request)
        if denied:
            return denied
        project_id = request.path_params["project_id"]
        active_sprint = next(
            (
                s
                for s in store.query(PK_SPRINT)
                if s["project_id"] == project_id and s["status"] == "active"
            ),
            None,
        )
        if not active_sprint:
            return json_response(200, {"sprint": None, "columns": {}})
        stories = store.query(PK_STORY)
        sprint_stories = [s for s in stories if s["sprint_id"] == active_sprint["id"]]
        columns = {
            "todo": [s for s in sprint_stories if s["status"] == "todo"],
            "in_progress": [s for s in sprint_stories if s["status"] == "in_progress"],
            "in_review": [s for s in sprint_stories if s["status"] == "in_review"],
            "done": [s for s in sprint_stories if s["status"] == "done"],
        }
        return json_response(200, {"sprint": active_sprint, "columns": columns})

    @router.route("GET", "/stories")
    def list_all_stories(request):
        denied = _auth(request)
        if denied:
            return denied
        stories = store.query(PK_STORY)
        project_id = request.query.get("project_id")
        status = request.query.get("status")
        assignee = request.query.get("assignee")
        if project_id:
            stories = [s for s in stories if s["project_id"] == project_id]
        if status:
            stories = [s for s in stories if s["status"] == status]
        if assignee:
            stories = [s for s in stories if s["assignee"] == assignee]
        return json_response(200, {"stories": stories, "total": len(stories)})

    @router.route("GET", "/projects/{project_id}/stories")
    def list_stories(request):
        denied = _auth(request)
        if denied:
            return denied
        project_id = request.path_params["project_id"]
        stories = [s for s in store.query(PK_STORY) if s["project_id"] == project_id]
        status = request.query.get("status")
        assignee = request.query.get("assignee")
        sprint_id = request.query.get("sprint_id")
        if status:
            stories = [s for s in stories if s["status"] == status]
        if assignee:
            stories = [s for s in stories if s["assignee"] == assignee]
        if sprint_id:
            stories = [s for s in stories if s["sprint_id"] == sprint_id]
        return json_response(200, {"stories": stories, "total": len(stories)})

    # --- Stories ---

    @router.route("GET", "/stories/{story_id}")
    def get_story(request):
        denied = _auth(request)
        if denied:
            return denied
        story = store.get(PK_STORY, request.path_params["story_id"])
        if not story:
            return error(404, "Story not found")
        result = dict(story)
        if story["assignee"]:
            dev = store.get(PK_DEVELOPER, story["assignee"])
            result["assignee_details"] = dev
        return json_response(200, result)

    @router.route("POST", "/stories")
    def create_story(request):
        denied = _auth(request)
        if denied:
            return denied
        body = request.json_body or {}
        for field in ("project_id", "title"):
            if body.get(field) in (None, ""):
                return error(422, f"Field '{field}' is required")
        project_id = body["project_id"]
        if not store.exists(PK_PROJECT, project_id):
            return error(404, "Project not found")
        project_stories = [s for s in store.query(PK_STORY) if s["project_id"] == project_id]
        max_num = 0
        for s in project_stories:
            num = int(s["id"].split("-")[1])
            if num > max_num:
                max_num = num
        new_id = f"{project_id}-{max_num + 1}"
        new_story = {
            "id": new_id,
            "project_id": project_id,
            "sprint_id": body.get("sprint_id"),
            "title": body["title"],
            "description": body.get("description", ""),
            "status": "todo",
            "priority": body.get("priority", "medium"),
            "story_points": body.get("story_points", 0),
            "assignee": body.get("assignee"),
            "acceptance_criteria": [],
            "comments": [],
        }
        store.put(PK_STORY, new_id, new_story)
        _log_activity(store, new_story, "created", to=new_story["assignee"])
        if new_story["assignee"]:
            _log_activity(store, new_story, "assigned", to=new_story["assignee"])
        return json_response(201, new_story)

    @router.route("PUT", "/stories/{story_id}")
    def update_story(request):
        denied = _auth(request)
        if denied:
            return denied
        story_id = request.path_params["story_id"]
        story = store.get(PK_STORY, story_id)
        if not story:
            return error(404, "Story not found")
        body = request.json_body or {}
        old_status = story.get("status")
        old_assignee = story.get("assignee")
        for field in ("status", "assignee", "priority", "sprint_id", "story_points"):
            if body.get(field) is not None:
                story[field] = body[field]
        store.put(PK_STORY, story_id, story)
        if story.get("assignee") != old_assignee:
            _log_activity(store, story, "assigned", to=story.get("assignee"), frm=old_assignee)
        if story.get("status") != old_status:
            _log_activity(store, story, "status", to=story.get("status"), frm=old_status)
        return json_response(200, story)

    @router.route("POST", "/stories/{story_id}/comments")
    def add_comment(request):
        denied = _auth(request)
        if denied:
            return denied
        story_id = request.path_params["story_id"]
        story = store.get(PK_STORY, story_id)
        if not story:
            return error(404, "Story not found")
        body = request.json_body
        if not isinstance(body, dict):
            return error(422, "Request body must be a JSON object")
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            return error(422, "Field 'text' is required")
        text = text.strip()
        if len(text) > MAX_COMMENT_CHARS:
            return error(422, f"Field 'text' must be at most {MAX_COMMENT_CHARS} characters")
        author = body.get("author")
        if not isinstance(author, str) or not store.exists(PK_DEVELOPER, author):
            return error(422, "Unknown author")
        story.setdefault("comments", []).append(
            {"author": author, "text": text, "date": seed_dates.today_utc().isoformat()}
        )
        store.put(PK_STORY, story_id, story)
        _log_activity(store, story, "comment", actor=author, text=text)
        return json_response(201, story)

    # --- Sprints ---

    @router.route("GET", "/sprints/{project_id}")
    def list_sprints(request):
        denied = _auth(request)
        if denied:
            return denied
        project_id = request.path_params["project_id"]
        project_sprints = [s for s in store.query(PK_SPRINT) if s["project_id"] == project_id]
        stories = store.query(PK_STORY)
        for sprint in project_sprints:
            if sprint["status"] in ("active", "completed"):
                done_stories = [
                    s for s in stories
                    if s["sprint_id"] == sprint["id"] and s["status"] == "done"
                ]
                sprint["completed_points"] = sum(s["story_points"] for s in done_stories)
                total_stories = [s for s in stories if s["sprint_id"] == sprint["id"]]
                sprint["total_points"] = sum(s["story_points"] for s in total_stories)
        return json_response(200, {"sprints": project_sprints})

    # --- Activity (read-only; not a Gateway tool) ---
    @router.route("GET", "/activity")
    def list_activity(request):
        denied = _auth(request)
        if denied:
            return denied
        since = request.query.get("since")
        if since:
            try:
                datetime.strptime(since, _TS_FMT)
            except ValueError:
                return error(422, "since must be an ISO UTC datetime")
        else:
            since = (datetime.now(timezone.utc) - timedelta(days=ACTIVITY_DEFAULT_DAYS)).strftime(
                _TS_FMT
            )
        items = [a for a in store.query(PK_ACTIVITY) if a.get("ts", "") >= since]
        items.sort(key=lambda a: a["ts"], reverse=True)
        return json_response(200, {"activity": items, "total": len(items)})

    # --- Developers ---

    @router.route("GET", "/developers")
    def list_developers(request):
        denied = _auth(request)
        if denied:
            return denied
        return json_response(200, {"developers": store.query(PK_DEVELOPER)})

    # --- Admin (not a Gateway tool; token protected) ---
    @router.route("POST", "/admin/reset")
    def admin_reset(request):
        denied = _auth(request)
        if denied:
            return denied
        counts = store.reset()
        return json_response(
            200,
            {
                "status": "ok",
                "service": "jira",
                "counts": counts,
                "shift_days": seed_dates.compute_shift_days(seed_dates.today_utc()),
            },
        )

    return router
