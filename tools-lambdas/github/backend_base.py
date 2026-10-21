"""Common backend interface for the GitHub adapter (ported from mahalo-dock).

The adapter exposes a single, stable GitHub contract (see ``routes.py``). Behind
that contract, requests are dispatched to one of two interchangeable backends
chosen by ``GITHUB_MODE``:

- ``mock``  — the DynamoDB-backed in-memory JSON store (default; offline-friendly).
- ``real``  — backed by a self-hosted Gitea instance (``gitea_backend.py``).

The mock path does not use this interface (it is the frozen ``build_router``
store path); the Gitea adapter implements this interface so ``build_gitea_router``
can delegate each route to it. Methods return plain dicts/lists already shaped
like MAHALO's existing GitHub responses; they raise :class:`BackendError` for
anything the HTTP layer should translate into an error status code.

Ported verbatim from ``mahalo-dock/mock-services/github/backend_base.py`` (the
``abc``/typing shape is unchanged; only this module docstring is adapted to the
tools-lambdas layout).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class BackendError(Exception):
    """Raised by a backend to signal an HTTP-translatable error.

    ``status`` is the HTTP status code the route should return; ``detail`` is the
    human-readable message. This keeps backends free of web-framework imports.
    """

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class GithubBackend(ABC):
    """Interface implemented by the Gitea-backed adapter."""

    # --- Repos ---

    @abstractmethod
    def create_repo(self, repo: dict) -> dict:
        """Create a repository. Returns the created repo record."""

    @abstractmethod
    def list_repos(self) -> dict:
        """Return ``{"repos": [...]}``."""

    @abstractmethod
    def get_repo(self, repo_id: str) -> dict:
        """Return a single repo record, or raise BackendError(404)."""

    # --- Branches ---

    @abstractmethod
    def list_branches(self, repo_id: str) -> dict:
        """Return ``{"branches": [...]}`` or raise BackendError(404)."""

    @abstractmethod
    def create_branch(self, repo_id: str, name: str, from_branch: str) -> dict:
        """Create a branch. Returns the created branch record."""

    # --- Pull requests ---

    @abstractmethod
    def list_all_pulls(
        self,
        status: Optional[str] = None,
        author_id: Optional[str] = None,
        repo_id: Optional[str] = None,
    ) -> dict:
        """Return ``{"pull_requests": [...], "total": n}`` across all repos."""

    @abstractmethod
    def list_pulls(
        self,
        repo_id: str,
        status: Optional[str] = None,
        author_id: Optional[str] = None,
    ) -> dict:
        """Return ``{"pull_requests": [...], "total": n}`` for one repo."""

    @abstractmethod
    def get_pull(self, repo_id: str, pr_number: int) -> dict:
        """Return a single PR record, or raise BackendError(404)."""

    @abstractmethod
    def create_pull(self, repo_id: str, request: dict) -> dict:
        """Create a pull request. Returns the created PR record."""

    # --- Commits ---

    @abstractmethod
    def list_commits(
        self,
        repo_id: str,
        branch: Optional[str] = None,
        author: Optional[str] = None,
    ) -> dict:
        """Return ``{"commits": [...], "total": n}``."""

    @abstractmethod
    def create_commit(self, repo_id: str, request: dict) -> dict:
        """Record/create a commit. Returns the created commit record."""

    # --- Docs ---

    @abstractmethod
    def create_readme(self, repo_id: str, readme: dict) -> dict:
        """Create/update a README. Returns the doc record."""

    # --- Stats ---

    @abstractmethod
    def get_stats(self, repo_id: str) -> dict:
        """Return repository statistics, or raise BackendError(404)."""
