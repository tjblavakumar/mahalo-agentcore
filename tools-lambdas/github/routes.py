"""GitHub mock routes ported from mahalo-dock github/main.py + mock_backend.py.

Mock mode ONLY (``GITHUB_MODE=mock``); the Gitea backend is not ported.

Three collections preserve the mock's three distinct existence checks:
    REPO      pk="REPO",     sk=repo_id   repo record under ``data``
    BRANCHSET pk="BRANCHSET", sk=repo_id  per-repo branch list under ``value``
    STATS     pk="STATS",    sk=repo_id   per-repo contributor list under ``value``
    PULL      pk="PULL",     sk=pr_id     PR record under ``data``
    COMMIT    pk="COMMIT",   sk=commit_id commit record under ``data``

All repo keys are the seed id ``repo-N`` (never the repo name); there is no
name->id resolution, so the agent passing a repo name 404s exactly as the mock.
"""

import os

from common.auth import require_token
from common.responses import error, json_response
from common.router import Router

from . import seed_data
from .backend_base import BackendError

PK_REPO = "REPO"
PK_BRANCHSET = "BRANCHSET"
PK_STATS = "STATS"
PK_PULL = "PULL"
PK_COMMIT = "COMMIT"

_VALUE = "value"


def seed_items():
    for repo in seed_data.REPOS:
        yield {"pk": PK_REPO, "sk": repo["id"], "record": repo}
    for repo_id, branches in seed_data.BRANCHES.items():
        yield {"pk": PK_BRANCHSET, "sk": repo_id, "attr": _VALUE, "record": branches}
    for repo_id, stats in seed_data.CONTRIBUTOR_STATS.items():
        yield {"pk": PK_STATS, "sk": repo_id, "attr": _VALUE, "record": stats}
    for pr in seed_data.PULL_REQUESTS:
        yield {"pk": PK_PULL, "sk": pr["id"], "record": pr}
    for commit in seed_data.COMMITS:
        yield {"pk": PK_COMMIT, "sk": commit["id"], "record": commit}


def build_router(store, token):
    router = Router()
    github_mode = os.environ.get("GITHUB_MODE", "mock").strip().lower()

    def _auth(request):
        if not require_token(request, token):
            return error(401, "Invalid API token")
        return None

    def _branches(repo_id):
        """Per-repo branch list, or ``None`` when the repo has no BRANCHSET."""
        return store.get(PK_BRANCHSET, repo_id, attr=_VALUE)

    @router.route("GET", "/health")
    def health(request):
        return json_response(
            200,
            {
                "status": "healthy",
                "service": "github-adapter",
                "version": "2.0.0",
                "mode": github_mode,
            },
        )

    # --- Repos ---

    @router.route("POST", "/repos")
    def create_repo(request):
        denied = _auth(request)
        if denied:
            return denied
        repo = request.json_body or {}
        repo_id = str(repo.get("name") or "repo").lower().strip()
        if store.exists(PK_REPO, repo_id):
            return error(409, "Repository already exists")
        new_repo = {
            "id": repo_id,
            "name": repo_id,
            "description": repo.get("description") or "",
            "language": repo.get("language") or "Python",
            "default_branch": repo.get("default_branch") or "main",
            "stars": 0,
            "open_issues": 0,
            "last_push": "2026-08-29",
        }
        store.put(PK_REPO, repo_id, new_repo)
        if _branches(repo_id) is None:
            store.put(
                PK_BRANCHSET,
                repo_id,
                [{"name": "main", "protected": True, "last_commit": "2026-08-29"}],
                attr=_VALUE,
            )
        return json_response(201, new_repo)

    @router.route("GET", "/repos")
    def list_repos(request):
        denied = _auth(request)
        if denied:
            return denied
        return json_response(200, {"repos": store.query(PK_REPO)})

    @router.route("GET", "/repos/{repo_id}")
    def get_repo(request):
        denied = _auth(request)
        if denied:
            return denied
        repo = store.get(PK_REPO, request.path_params["repo_id"])
        if not repo:
            return error(404, "Repository not found")
        return json_response(200, repo)

    # --- Branches ---

    @router.route("GET", "/repos/{repo_id}/branches")
    def list_branches(request):
        denied = _auth(request)
        if denied:
            return denied
        branches = _branches(request.path_params["repo_id"])
        if branches is None:
            return error(404, "Repository not found")
        return json_response(200, {"branches": branches})

    @router.route("POST", "/repos/{repo_id}/branches")
    def create_branch(request):
        denied = _auth(request)
        if denied:
            return denied
        body = request.json_body or {}
        name = body.get("name")
        if name in (None, ""):
            return error(422, "Field 'name' is required")
        repo_id = request.path_params["repo_id"]
        branches = _branches(repo_id)
        if branches is None:
            return error(404, "Repository not found")
        if any(b["name"] == name for b in branches):
            return error(409, "Branch already exists")
        new_branch = {"name": name, "protected": False, "last_commit": "2026-08-25"}
        branches.append(new_branch)
        store.put(PK_BRANCHSET, repo_id, branches, attr=_VALUE)
        return json_response(201, new_branch)

    # --- Pull requests ---

    @router.route("GET", "/pulls")
    def list_all_pulls(request):
        denied = _auth(request)
        if denied:
            return denied
        prs = store.query(PK_PULL)
        repo_id = request.query.get("repo_id")
        status = request.query.get("status")
        author_id = request.query.get("author_id")
        if repo_id:
            prs = [pr for pr in prs if pr["repo_id"] == repo_id]
        if status:
            prs = [pr for pr in prs if pr["status"] == status]
        if author_id:
            prs = [pr for pr in prs if pr["author_id"] == author_id]
        return json_response(200, {"pull_requests": prs, "total": len(prs)})

    @router.route("GET", "/repos/{repo_id}/pulls")
    def list_pulls(request):
        denied = _auth(request)
        if denied:
            return denied
        repo_id = request.path_params["repo_id"]
        prs = [pr for pr in store.query(PK_PULL) if pr["repo_id"] == repo_id]
        status = request.query.get("status")
        author_id = request.query.get("author_id")
        if status:
            prs = [pr for pr in prs if pr["status"] == status]
        if author_id:
            prs = [pr for pr in prs if pr["author_id"] == author_id]
        return json_response(200, {"pull_requests": prs, "total": len(prs)})

    @router.route("GET", "/repos/{repo_id}/pulls/{pr_number}", int_params={"pr_number"})
    def get_pull(request):
        denied = _auth(request)
        if denied:
            return denied
        repo_id = request.path_params["repo_id"]
        pr_number = request.path_params["pr_number"]
        pr = next(
            (
                pr
                for pr in store.query(PK_PULL)
                if pr["repo_id"] == repo_id and pr["number"] == pr_number
            ),
            None,
        )
        if not pr:
            return error(404, "Pull request not found")
        return json_response(200, pr)

    @router.route("POST", "/repos/{repo_id}/pulls")
    def create_pull(request):
        denied = _auth(request)
        if denied:
            return denied
        repo_id = request.path_params["repo_id"]
        if _branches(repo_id) is None:
            return error(404, "Repository not found")
        req = request.json_body or {}
        head = req.get("head") or req.get("branch")
        base = req.get("base") or req.get("target_branch") or "main"
        if not head:
            return error(422, "head branch is required")
        all_prs = store.query(PK_PULL)
        next_number = max((pr["number"] for pr in all_prs), default=0) + 1
        new_id = f"pr-{store.count(PK_PULL) + 1}"
        new_pr = {
            "id": new_id,
            "repo_id": repo_id,
            "number": next_number,
            "title": req.get("title") or head,
            "description": req.get("body") or req.get("description") or "",
            "author": req.get("author") or req.get("author_id") or "mahalo-bot",
            "author_id": req.get("author_id") or "mahalo-bot",
            "status": "open",
            "branch": head,
            "target_branch": base,
            "created_at": "2026-08-29",
            "updated_at": "2026-08-29",
            "additions": req.get("additions", 0),
            "deletions": req.get("deletions", 0),
            "files_changed": req.get("files_changed", 0),
            "reviews": [],
            "linked_story": req.get("linked_story"),
            "url": None,
        }
        store.put(PK_PULL, new_id, new_pr)
        return json_response(201, new_pr)

    # --- Commits ---

    @router.route("GET", "/repos/{repo_id}/commits")
    def list_commits(request):
        denied = _auth(request)
        if denied:
            return denied
        repo_id = request.path_params["repo_id"]
        commits = [c for c in store.query(PK_COMMIT) if c["repo_id"] == repo_id]
        branch = request.query.get("branch")
        author = request.query.get("author")
        if branch:
            commits = [c for c in commits if c["branch"] == branch]
        if author:
            commits = [
                c
                for c in commits
                if author.lower() in c["author"].lower() or c["author_id"] == author
            ]
        commits.sort(key=lambda x: x["date"], reverse=True)
        return json_response(200, {"commits": commits, "total": len(commits)})

    @router.route("POST", "/repos/{repo_id}/commits")
    def create_commit(request):
        denied = _auth(request)
        if denied:
            return denied
        repo_id = request.path_params["repo_id"]
        branches = _branches(repo_id)
        if branches is None:
            return error(404, "Repository not found")
        req = request.json_body or {}
        has_files = isinstance(req.get("files"), list) or req.get("path")
        required = ("branch", "message") if has_files else ("branch", "message", "author_id")
        for field in required:
            if req.get(field) in (None, ""):
                return error(422, f"Field '{field}' is required")
        if has_files and not req.get("author_id"):
            req = {**req, "author_id": "mahalo-bot"}

        branch_name = req.get("branch")
        branch = next((b for b in branches if b["name"] == branch_name), None)
        if not branch:
            return error(404, "Branch not found")

        author_id = req.get("author_id")
        author_name = author_id
        found = False
        for stats in store.query(PK_STATS, attr=_VALUE):
            for stat in stats:
                if stat["author_id"] == author_id:
                    author_name = stat["author"]
                    found = True
                    break
            if found:
                break

        new_id = f"c{store.count(PK_COMMIT) + 1:03d}"
        new_commit = {
            "id": new_id,
            "repo_id": repo_id,
            "branch": branch_name,
            "author": author_name,
            "author_id": author_id,
            "message": req.get("message"),
            "date": "2026-08-25",
            "additions": req.get("additions", 0),
            "deletions": req.get("deletions", 0),
        }
        store.put(PK_COMMIT, new_id, new_commit)
        return json_response(201, new_commit)

    # --- Docs ---

    @router.route("POST", "/repos/{repo_id}/readme")
    def create_readme(request):
        denied = _auth(request)
        if denied:
            return denied
        repo_id = request.path_params["repo_id"]
        if _branches(repo_id) is None:
            return error(404, "Repository not found")
        readme = request.json_body or {}
        return json_response(
            201,
            {
                "repo_id": repo_id,
                "title": readme.get("title") or "README.md",
                "content": readme.get("content") or "",
                "updated_at": "2026-08-29",
            },
        )

    # --- Stats ---

    @router.route("GET", "/repos/{repo_id}/stats")
    def get_stats(request):
        denied = _auth(request)
        if denied:
            return denied
        repo_id = request.path_params["repo_id"]
        contributors = store.get(PK_STATS, repo_id, attr=_VALUE)
        if contributors is None:
            return error(404, "Repository not found")
        total_commits = sum(c["commits"] for c in contributors)
        total_additions = sum(c["additions"] for c in contributors)
        total_deletions = sum(c["deletions"] for c in contributors)
        branches = _branches(repo_id) or []
        open_prs = len(
            [
                pr
                for pr in store.query(PK_PULL)
                if pr["repo_id"] == repo_id and pr["status"] == "open"
            ]
        )
        return json_response(
            200,
            {
                "repo_id": repo_id,
                "contributors": contributors,
                "total_commits": total_commits,
                "total_additions": total_additions,
                "total_deletions": total_deletions,
                "active_branches": len(branches),
                "open_prs": open_prs,
            },
        )

    return router


def build_gitea_router(backend):
    """Build the real-mode (``GITHUB_MODE=real``) router backed by Gitea.

    Registers the SAME route table (paths/verbs/int-param coercion) as
    :func:`build_router` so DIRECT and Gateway invocations are indistinguishable
    from the mock path, but delegates each route to the :class:`GiteaBackend`
    instance instead of the DynamoDB ``Store``. A :class:`BackendError` raised by
    the backend is mapped to the common ``error(status, detail)`` helper, exactly
    as mahalo-dock's ``main.py::_call`` mapped it to an ``HTTPException``.

    Auth is unchanged: the service still enforces the static ``X-API-Token``
    against ``MOCK_GITHUB_TOKEN`` (the same token the Gateway adapter injects), so
    flipping the mode never changes the edge contract. The Gitea API token (SSM)
    authenticates the Lambda->Gitea hop and is held inside ``backend`` only.

    Note: :func:`build_router` and its ``(store, token)`` signature/mock behavior
    are left untouched; this is a strictly additive sibling.
    """
    router = Router()
    github_mode = os.environ.get("GITHUB_MODE", "mock").strip().lower()
    token = os.environ.get("MOCK_GITHUB_TOKEN", "mock-github-token-12345")

    def _auth(request):
        if not require_token(request, token):
            return error(401, "Invalid API token")
        return None

    def _call(fn, *args, **kwargs):
        """Invoke a backend method, mapping BackendError -> error() response."""
        try:
            return fn(*args, **kwargs)
        except BackendError as e:
            return error(e.status, e.detail)

    @router.route("GET", "/health")
    def health(request):
        return json_response(
            200,
            {
                "status": "healthy",
                "service": "github-adapter",
                "version": "2.0.0",
                "mode": github_mode,
            },
        )

    # --- Repos ---

    @router.route("POST", "/repos")
    def create_repo(request):
        denied = _auth(request)
        if denied:
            return denied
        result = _call(backend.create_repo, request.json_body or {})
        if isinstance(result, dict) and "statusCode" in result:
            return result
        return json_response(201, result)

    @router.route("GET", "/repos")
    def list_repos(request):
        denied = _auth(request)
        if denied:
            return denied
        result = _call(backend.list_repos)
        if isinstance(result, dict) and "statusCode" in result:
            return result
        return json_response(200, result)

    @router.route("GET", "/repos/{repo_id}")
    def get_repo(request):
        denied = _auth(request)
        if denied:
            return denied
        result = _call(backend.get_repo, request.path_params["repo_id"])
        if isinstance(result, dict) and "statusCode" in result:
            return result
        return json_response(200, result)

    # --- Branches ---

    @router.route("GET", "/repos/{repo_id}/branches")
    def list_branches(request):
        denied = _auth(request)
        if denied:
            return denied
        result = _call(backend.list_branches, request.path_params["repo_id"])
        if isinstance(result, dict) and "statusCode" in result:
            return result
        return json_response(200, result)

    @router.route("POST", "/repos/{repo_id}/branches")
    def create_branch(request):
        denied = _auth(request)
        if denied:
            return denied
        body = request.json_body or {}
        name = body.get("name")
        if name in (None, ""):
            return error(422, "Field 'name' is required")
        result = _call(
            backend.create_branch,
            request.path_params["repo_id"],
            name,
            body.get("from_branch") or "main",
        )
        if isinstance(result, dict) and "statusCode" in result:
            return result
        return json_response(201, result)

    # --- Pull requests ---

    @router.route("GET", "/pulls")
    def list_all_pulls(request):
        denied = _auth(request)
        if denied:
            return denied
        result = _call(
            backend.list_all_pulls,
            request.query.get("status"),
            request.query.get("author_id"),
            request.query.get("repo_id"),
        )
        if isinstance(result, dict) and "statusCode" in result:
            return result
        return json_response(200, result)

    @router.route("GET", "/repos/{repo_id}/pulls")
    def list_pulls(request):
        denied = _auth(request)
        if denied:
            return denied
        result = _call(
            backend.list_pulls,
            request.path_params["repo_id"],
            request.query.get("status"),
            request.query.get("author_id"),
        )
        if isinstance(result, dict) and "statusCode" in result:
            return result
        return json_response(200, result)

    @router.route("GET", "/repos/{repo_id}/pulls/{pr_number}", int_params={"pr_number"})
    def get_pull(request):
        denied = _auth(request)
        if denied:
            return denied
        result = _call(
            backend.get_pull,
            request.path_params["repo_id"],
            request.path_params["pr_number"],
        )
        if isinstance(result, dict) and "statusCode" in result:
            return result
        return json_response(200, result)

    @router.route("POST", "/repos/{repo_id}/pulls")
    def create_pull(request):
        denied = _auth(request)
        if denied:
            return denied
        result = _call(
            backend.create_pull,
            request.path_params["repo_id"],
            request.json_body or {},
        )
        if isinstance(result, dict) and "statusCode" in result:
            return result
        return json_response(201, result)

    # --- Commits ---

    @router.route("GET", "/repos/{repo_id}/commits")
    def list_commits(request):
        denied = _auth(request)
        if denied:
            return denied
        result = _call(
            backend.list_commits,
            request.path_params["repo_id"],
            request.query.get("branch"),
            request.query.get("author"),
        )
        if isinstance(result, dict) and "statusCode" in result:
            return result
        return json_response(200, result)

    @router.route("POST", "/repos/{repo_id}/commits")
    def create_commit(request):
        denied = _auth(request)
        if denied:
            return denied
        result = _call(
            backend.create_commit,
            request.path_params["repo_id"],
            request.json_body or {},
        )
        if isinstance(result, dict) and "statusCode" in result:
            return result
        return json_response(201, result)

    # --- Docs ---

    @router.route("POST", "/repos/{repo_id}/readme")
    def create_readme(request):
        denied = _auth(request)
        if denied:
            return denied
        result = _call(
            backend.create_readme,
            request.path_params["repo_id"],
            request.json_body or {},
        )
        if isinstance(result, dict) and "statusCode" in result:
            return result
        return json_response(201, result)

    # --- Stats ---

    @router.route("GET", "/repos/{repo_id}/stats")
    def get_stats(request):
        denied = _auth(request)
        if denied:
            return denied
        result = _call(backend.get_stats, request.path_params["repo_id"])
        if isinstance(result, dict) and "statusCode" in result:
            return result
        return json_response(200, result)

    return router
