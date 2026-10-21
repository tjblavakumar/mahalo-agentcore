"""Gitea-backed implementation of the GitHub adapter (``GITHUB_MODE=real``).

Ported from ``mahalo-dock/mock-services/github/gitea_backend.py``. Translates
MAHALO's stable GitHub contract to Gitea's REST API and maps Gitea responses
back into the exact JSON shapes MAHALO already expects (the same shapes the
DynamoDB-backed mock path emits in ``routes.py``/``seed_data.py``).

Repo identity mapping
---------------------
MAHALO addresses repos by a flat ``repo_id`` (e.g. ``payment-service``). Gitea
addresses them as ``owner/repo``. We treat ``repo_id`` as the Gitea repo *name*
under a single owner (the bootstrap admin), so ``payment-service`` resolves to
``<owner>/payment-service``.

Adaptation to the tools-lambdas layout: the only change from the mahalo-dock
source is the import of ``BackendError``/``GithubBackend`` from the sibling
``backend_base`` module via a package-relative import (``from .backend_base``),
and the token-resolution fallback that lets ``handler.py`` inject the SSM-resolved
token at construction time. ``httpx`` stays the HTTP client, imported lazily so
the mock path never loads it.
"""

from __future__ import annotations

import base64
import datetime
import logging
import os
from typing import Any, Optional

import httpx

from .backend_base import BackendError, GithubBackend

logger = logging.getLogger("github-adapter.gitea")


def _date_only(ts: Optional[str]) -> str:
    """Reduce an ISO timestamp (2026-10-14T03:30:56Z) to a date (2026-10-14)."""
    if not ts:
        return ""
    return ts.split("T", 1)[0]


class GiteaBackend(GithubBackend):
    """Adapter backend that translates the MAHALO contract to Gitea's REST API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        owner: Optional[str] = None,
        public_url: Optional[str] = None,
        demo_developer_id: Optional[str] = None,
    ):
        self.base_url = (
            base_url or os.environ.get("GITEA_URL", "http://gitea:3000")
        ).rstrip("/")
        self.token = token or os.environ.get("GITEA_TOKEN", "") or self._read_token_file()
        self.owner = owner or os.environ.get("GITEA_ADMIN_USER", "mahalo_admin")
        self.api = f"{self.base_url}/api/v1"
        # Single-user demo: all real git activity is performed by the one Gitea
        # user (the admin/owner). The app, however, filters PRs/commits by a
        # developer id (e.g. dev-6) that represents the logged-in demo user.
        # Map the Gitea owner's login -> that demo developer id so the dashboard
        # ("My PRs"/"Recent Commits" filtered by author=dev-6) and the agent see
        # the activity as the demo developer's. Configurable via env.
        self.demo_developer_id = demo_developer_id or os.environ.get(
            "DEMO_DEVELOPER_ID", "dev-6"
        )
        # Gitea derives html_url from the request Host, so links returned to the
        # adapter come back as the in-stack base (http://gitea:3000/...), which a
        # browser can't reach. Rewrite them to the browser-facing public URL.
        self.public_url = (
            public_url or os.environ.get("GITEA_PUBLIC_URL", "http://localhost:3001")
        ).rstrip("/")

    def _publicize(self, url: Optional[str]) -> Optional[str]:
        """Rewrite an in-stack Gitea URL to the browser-reachable public URL."""
        if not url:
            return url
        return url.replace(self.base_url, self.public_url)

    def _map_author_id(self, login: Optional[str]) -> str:
        """Map a Gitea login to the reported author_id.

        For the single-user demo, the owner/admin login is reported as the demo
        developer id so the app's dev-id-based filters match. Any other login is
        passed through unchanged.
        """
        if login and login == self.owner:
            return self.demo_developer_id
        return login or self.demo_developer_id

    @staticmethod
    def _read_token_file() -> str:
        """Read the adapter token from GITEA_TOKEN_FILE (local/parity fallback).

        Lets a local Compose-style run avoid passing the token as an env var: the
        bootstrap writes it to a shared volume and the adapter reads it at
        startup. On AWS the token comes from SSM (resolved in ``handler.py``).
        """
        path = os.environ.get("GITEA_TOKEN_FILE", "")
        if not path:
            return ""
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            logger.warning("GITEA_TOKEN_FILE=%s not readable yet", path)
            return ""

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        return {
            "Authorization": f"token {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        ok: tuple = (200, 201),
        allow_404: bool = False,
    ) -> Any:
        """Call Gitea and return parsed JSON, translating failures to BackendError.

        When ``allow_404`` is True a 404 returns ``None`` instead of raising,
        which lets callers use a GET as an existence check.
        """
        url = f"{self.api}{path}"
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.request(
                    method, url, headers=self._headers(), params=params, json=json_body
                )
        except httpx.HTTPError as e:
            logger.error("Gitea request failed: %s %s -> %s", method, path, e)
            raise BackendError(502, f"Gitea request failed: {e}")

        if resp.status_code == 404:
            if allow_404:
                return None
            raise BackendError(404, "Not found")
        if resp.status_code not in ok:
            # Surface Gitea's own message where possible.
            detail = resp.text
            try:
                detail = resp.json().get("message", detail)
            except Exception:
                pass
            raise BackendError(resp.status_code, f"Gitea error: {detail}")

        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def _repo_path(self, repo_id: str) -> str:
        return f"/repos/{self.owner}/{repo_id}"

    # ------------------------------------------------------------------
    # Mappers: Gitea shape -> MAHALO shape
    # ------------------------------------------------------------------

    def _map_repo(self, g: dict) -> dict:
        return {
            "id": g.get("name"),
            "name": g.get("name"),
            "description": g.get("description") or "",
            "language": g.get("language") or "Python",
            "default_branch": g.get("default_branch") or "main",
            "stars": g.get("stars_count", 0),
            "open_issues": g.get("open_issues_count", 0),
            "last_push": _date_only(g.get("updated_at")),
        }

    def _map_branch(self, g: dict) -> dict:
        commit = g.get("commit") or {}
        author = commit.get("author") or {}
        return {
            "name": g.get("name"),
            "protected": bool(g.get("protected", False)),
            "last_commit": _date_only(author.get("date") or commit.get("timestamp")),
        }

    def _map_pull(self, g: dict, repo_id: str) -> dict:
        user = g.get("user") or {}
        head = g.get("head") or {}
        base = g.get("base") or {}
        # Gitea state is "open"/"closed"; a merged PR is closed with merged=true.
        status = g.get("state") or "open"
        if g.get("merged"):
            status = "merged"
        return {
            "id": f"pr-{g.get('number')}",
            "repo_id": repo_id,
            "number": g.get("number"),
            "title": g.get("title") or "",
            "description": g.get("body") or "",
            "author": user.get("full_name") or user.get("login") or "",
            "author_id": self._map_author_id(user.get("login")),
            "status": status,
            "branch": head.get("ref") or "",
            "target_branch": base.get("ref") or "main",
            "created_at": _date_only(g.get("created_at")),
            "updated_at": _date_only(g.get("updated_at")),
            "additions": g.get("additions", 0),
            "deletions": g.get("deletions", 0),
            "files_changed": g.get("changed_files", 0),
            "reviews": [],
            "linked_story": None,
            "url": self._publicize(g.get("html_url")),
        }

    def _map_commit(self, g: dict, repo_id: str) -> dict:
        commit = g.get("commit") or {}
        c_author = commit.get("author") or {}
        gitea_author = g.get("author") or {}
        stats = g.get("stats") or {}
        return {
            "id": g.get("sha"),
            "repo_id": repo_id,
            "branch": "",  # Gitea's commit list isn't branch-tagged; filled by caller when known
            "author": c_author.get("name") or gitea_author.get("login") or "",
            "author_id": self._map_author_id(
                gitea_author.get("login") or c_author.get("name")
            ),
            "message": (commit.get("message") or "").strip(),
            "date": _date_only(c_author.get("date")),
            "additions": stats.get("additions", 0),
            "deletions": stats.get("deletions", 0),
        }

    # ------------------------------------------------------------------
    # Repos
    # ------------------------------------------------------------------

    def create_repo(self, repo: dict) -> dict:
        name = str(repo.get("name") or "").strip()
        if not name:
            raise BackendError(422, "Repository name is required")

        # 409 if it already exists, mirroring the mock's behavior.
        existing = self._request(
            "GET", self._repo_path(name), ok=(200,), allow_404=True
        )
        if existing is not None:
            raise BackendError(409, "Repository already exists")

        body = {
            "name": name,
            "description": repo.get("description") or "",
            "private": bool(repo.get("private", False)),
            "auto_init": True,
            "default_branch": repo.get("default_branch") or "main",
        }
        g = self._request("POST", "/user/repos", json_body=body, ok=(201,))
        return self._map_repo(g)

    def list_repos(self) -> dict:
        # List repos owned by the adapter owner. Paginate defensively.
        repos: list = []
        page = 1
        while True:
            batch = self._request(
                "GET", "/user/repos", params={"page": page, "limit": 50}
            )
            if not batch:
                break
            repos.extend(batch)
            if len(batch) < 50:
                break
            page += 1
        return {"repos": [self._map_repo(r) for r in repos]}

    def get_repo(self, repo_id: str) -> dict:
        g = self._request("GET", self._repo_path(repo_id))
        return self._map_repo(g)

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    def list_branches(self, repo_id: str) -> dict:
        g = self._request("GET", f"{self._repo_path(repo_id)}/branches")
        return {"branches": [self._map_branch(b) for b in (g or [])]}

    def create_branch(self, repo_id: str, name: str, from_branch: str) -> dict:
        # Confirm the repo exists first so we return 404 (not 500) for bad repos.
        repo = self._request("GET", self._repo_path(repo_id), allow_404=True)
        if repo is None:
            raise BackendError(404, "Repository not found")

        # Duplicate branch -> 409, mirroring the mock.
        existing = self._request(
            "GET",
            f"{self._repo_path(repo_id)}/branches/{name}",
            ok=(200,),
            allow_404=True,
        )
        if existing is not None:
            raise BackendError(409, "Branch already exists")

        body = {"new_branch_name": name, "old_branch_name": from_branch or "main"}
        g = self._request(
            "POST", f"{self._repo_path(repo_id)}/branches", json_body=body, ok=(201,)
        )
        return self._map_branch(g)

    # ------------------------------------------------------------------
    # Pull requests
    # ------------------------------------------------------------------

    def _fetch_pulls(self, repo_id: str) -> list:
        """Fetch all PRs (any state) for a repo, mapped to MAHALO shape."""
        out: list = []
        page = 1
        while True:
            batch = self._request(
                "GET",
                f"{self._repo_path(repo_id)}/pulls",
                params={"state": "all", "page": page, "limit": 50},
            )
            if not batch:
                break
            out.extend(batch)
            if len(batch) < 50:
                break
            page += 1
        return [self._map_pull(p, repo_id) for p in out]

    def _filter_pulls(
        self, prs: list, status: Optional[str], author_id: Optional[str]
    ) -> list:
        if status:
            prs = [p for p in prs if p["status"] == status]
        if author_id:
            prs = [p for p in prs if p["author_id"] == author_id]
        return prs

    def list_all_pulls(
        self,
        status: Optional[str] = None,
        author_id: Optional[str] = None,
        repo_id: Optional[str] = None,
    ) -> dict:
        if repo_id:
            repo_ids = [repo_id]
        else:
            repo_ids = [r["id"] for r in self.list_repos()["repos"]]
        prs: list = []
        for rid in repo_ids:
            prs.extend(self._fetch_pulls(rid))
        prs = self._filter_pulls(prs, status, author_id)
        return {"pull_requests": prs, "total": len(prs)}

    def list_pulls(
        self,
        repo_id: str,
        status: Optional[str] = None,
        author_id: Optional[str] = None,
    ) -> dict:
        prs = self._filter_pulls(self._fetch_pulls(repo_id), status, author_id)
        return {"pull_requests": prs, "total": len(prs)}

    def get_pull(self, repo_id: str, pr_number: int) -> dict:
        g = self._request("GET", f"{self._repo_path(repo_id)}/pulls/{pr_number}")
        return self._map_pull(g, repo_id)

    def create_pull(self, repo_id: str, request: dict) -> dict:
        """Create a real pull request in Gitea (head -> base)."""
        if self._request("GET", self._repo_path(repo_id), allow_404=True) is None:
            raise BackendError(404, "Repository not found")

        # Accept MAHALO-style keys with sensible fallbacks.
        head = request.get("head") or request.get("branch")
        base = request.get("base") or request.get("target_branch") or "main"
        title = request.get("title") or head
        body = request.get("body") or request.get("description") or ""
        if not head:
            raise BackendError(422, "head branch is required")

        g = self._request(
            "POST",
            f"{self._repo_path(repo_id)}/pulls",
            json_body={"head": head, "base": base, "title": title, "body": body},
            ok=(201,),
        )
        return self._map_pull(g, repo_id)

    # ------------------------------------------------------------------
    # Commits
    # ------------------------------------------------------------------

    def list_commits(
        self,
        repo_id: str,
        branch: Optional[str] = None,
        author: Optional[str] = None,
    ) -> dict:
        params: dict = {"limit": 50, "stat": "true"}
        if branch:
            params["sha"] = branch  # Gitea accepts a branch name as the sha ref
        commits = self._request(
            "GET", f"{self._repo_path(repo_id)}/commits", params=params
        )
        mapped = [self._map_commit(c, repo_id) for c in (commits or [])]
        if branch:
            for m in mapped:
                m["branch"] = branch
        if author:
            a = author.lower()
            mapped = [
                m
                for m in mapped
                if a in (m["author"] or "").lower() or m["author_id"] == author
            ]
        return {"commits": mapped, "total": len(mapped)}

    def create_commit(self, repo_id: str, request: dict) -> dict:
        """Write real file contents to a branch, producing a real commit.

        Accepts the file-contents shape::

            {"branch": "feature/x", "message": "msg",
             "files": [{"path": "src/a.py", "content": "<utf-8 text>"}, ...]}

        A single ``{"path": ..., "content": ...}`` (without ``files``) is also
        accepted for convenience. ``content`` is plain UTF-8 text; the adapter
        base64-encodes it for Gitea's contents API.
        """
        branch = request.get("branch")
        message = request.get("message") or "Update files"
        if not branch:
            raise BackendError(422, "Field 'branch' is required")

        files = self._normalize_files(request)
        if not files:
            raise BackendError(
                422,
                "Real mode requires file contents: provide 'files':[{path,content}] "
                "(metadata-only commits are not supported against Gitea).",
            )

        # Confirm the repo + branch exist (clean 404 instead of a Gitea 500).
        if self._request("GET", self._repo_path(repo_id), allow_404=True) is None:
            raise BackendError(404, "Repository not found")
        if self._request(
            "GET",
            f"{self._repo_path(repo_id)}/branches/{branch}",
            ok=(200,),
            allow_404=True,
        ) is None:
            raise BackendError(404, "Branch not found")

        last = None
        total_add = 0
        for f in files:
            last = self._write_file(repo_id, branch, f["path"], f["content"], message)
            # Gitea returns the file content record; approximate additions by lines.
            total_add += (f["content"].count("\n") + 1) if f["content"] else 0

        # Map the resulting commit into MAHALO's commit shape.
        commit = (last or {}).get("commit") or {}
        author = commit.get("author") or {}
        sha = commit.get("sha") or (last or {}).get("sha") or ""
        return {
            "id": sha,
            "repo_id": repo_id,
            "branch": branch,
            "author": author.get("name") or self.owner,
            "author_id": self._map_author_id(self.owner),
            "message": message,
            "date": _date_only(author.get("date")),
            "additions": total_add,
            "deletions": 0,
            "files_committed": [f["path"] for f in files],
            "url": self._publicize(commit.get("html_url") or (last or {}).get("html_url")),
        }

    def _normalize_files(self, request: dict) -> list:
        """Extract a list of {path, content} from the request, validating shape."""
        files = request.get("files")
        if files is None and request.get("path") is not None:
            files = [{"path": request["path"], "content": request.get("content", "")}]
        if not isinstance(files, list):
            return []
        out = []
        for f in files:
            if not isinstance(f, dict) or not f.get("path"):
                raise BackendError(422, "Each file needs a 'path' and 'content'")
            out.append({"path": str(f["path"]), "content": f.get("content") or ""})
        return out

    def _write_file(
        self, repo_id: str, branch: str, path: str, content: str, message: str
    ) -> dict:
        """Create or update a single file via Gitea's contents API."""
        api = f"{self._repo_path(repo_id)}/contents/{path}"
        content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        body = {"content": content_b64, "message": message, "branch": branch}

        # If the file already exists on this branch, we must PUT with its sha.
        existing = self._request("GET", api, params={"ref": branch}, ok=(200,), allow_404=True)
        if existing is not None and isinstance(existing, dict) and existing.get("sha"):
            body["sha"] = existing["sha"]
            return self._request("PUT", api, json_body=body, ok=(200, 201))
        return self._request("POST", api, json_body=body, ok=(200, 201))

    # ------------------------------------------------------------------
    # Docs
    # ------------------------------------------------------------------

    def create_readme(self, repo_id: str, readme: dict) -> dict:
        """Write a real README file to the repo's default branch."""
        if self._request("GET", self._repo_path(repo_id), allow_404=True) is None:
            raise BackendError(404, "Repository not found")

        repo = self._request("GET", self._repo_path(repo_id))
        branch = repo.get("default_branch") or "main"
        title = readme.get("title") or "README.md"
        content = readme.get("content") or ""
        self._write_file(repo_id, branch, title, content, f"docs: update {title}")
        return {
            "repo_id": repo_id,
            "title": title,
            "content": content,
            "updated_at": datetime.date.today().isoformat(),
        }

    # ------------------------------------------------------------------
    # Stats (derived from commit history; degrade gracefully)
    # ------------------------------------------------------------------

    def get_stats(self, repo_id: str) -> dict:
        # Confirm the repo exists (404s cleanly if not).
        self._request("GET", self._repo_path(repo_id))

        commits = self._request(
            "GET",
            f"{self._repo_path(repo_id)}/commits",
            params={"limit": 50, "stat": "true"},
        ) or []

        agg: dict = {}
        total_add = total_del = 0
        for c in commits:
            commit = c.get("commit") or {}
            c_author = commit.get("author") or {}
            g_author = c.get("author") or {}
            raw_login = g_author.get("login") or c_author.get("name") or "unknown"
            login = self._map_author_id(raw_login)
            name = c_author.get("name") or raw_login
            stats = c.get("stats") or {}
            a = agg.setdefault(
                login,
                {"author": name, "author_id": login, "commits": 0, "additions": 0, "deletions": 0},
            )
            a["commits"] += 1
            a["additions"] += stats.get("additions", 0)
            a["deletions"] += stats.get("deletions", 0)
            total_add += stats.get("additions", 0)
            total_del += stats.get("deletions", 0)

        contributors = list(agg.values())
        branches = self._request("GET", f"{self._repo_path(repo_id)}/branches") or []
        open_prs = self._request(
            "GET",
            f"{self._repo_path(repo_id)}/pulls",
            params={"state": "open", "limit": 50},
        ) or []

        return {
            "repo_id": repo_id,
            "contributors": contributors,
            "total_commits": sum(c["commits"] for c in contributors),
            "total_additions": total_add,
            "total_deletions": total_del,
            "active_branches": len(branches),
            "open_prs": len(open_prs),
        }
