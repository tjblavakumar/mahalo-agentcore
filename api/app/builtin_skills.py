"""Packaged, read-only built-in skills (skills design, section A).

Loads and validates every ``*_SKILL.md`` in the skills directory once per cold
start (cached), with the same validator as uploads. A file that fails
validation is skipped with an ERROR log. The directory is ``MAHALO_SKILLS_DIR``
if set, else ``<api package parent>/skills`` (inside the Lambda asset), else
``<repo root>/skills`` (a checkout and the tests).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.skills import sha256_hex, validate_skill

logger = logging.getLogger(__name__)

_cache: dict[str, "BuiltinSkill"] | None = None


@dataclass(frozen=True)
class BuiltinSkill:
    name: str
    filename: str
    description: str
    content: str
    body: str
    content_sha256: str
    size_bytes: int


def _skills_dir() -> Path | None:
    """Resolve the skills directory; None when none exists."""
    if settings.skills_dir:
        candidates = [Path(settings.skills_dir)]
    else:
        here = Path(__file__).resolve()
        candidates = [here.parents[1] / "skills", here.parents[2] / "skills"]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def reset_cache() -> None:
    """Drop the cached built-ins (tests)."""
    global _cache
    _cache = None


def load_builtins() -> dict[str, BuiltinSkill]:
    """Return the validated built-in skills keyed by command name (cached)."""
    global _cache
    if _cache is not None:
        return _cache
    found: dict[str, BuiltinSkill] = {}
    directory = _skills_dir()
    if directory is None:
        logger.warning("No built-in skills directory found; only user skills are listed")
    else:
        for path in sorted(directory.glob("*_SKILL.md")):
            try:
                text = path.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                logger.exception("Built-in skill %s could not be read; skipped", path.name)
                continue
            result = validate_skill(path.name, text)
            if not result.ok or result.command_name is None:
                logger.error(
                    "Built-in skill %s failed validation (%s); skipped",
                    path.name,
                    ", ".join(result.rules),
                )
                continue
            found[result.command_name] = BuiltinSkill(
                name=result.command_name,
                filename=path.name,
                description=result.description or "",
                content=result.content,
                body=result.body,
                content_sha256=sha256_hex(result.content),
                size_bytes=len(result.content.encode("utf-8")),
            )
    _cache = found
    return found
