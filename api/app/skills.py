"""Skill validation and constants for the thin API (skills design, sections A, B).

One rule list, shared in shape with the browser and Runtime validators. This
module is the trust boundary for stored skills: ``validate_skill`` re-runs every
rule on the posted text. It imports no AWS or agent code.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# --- Shared constants (mirrored in agent/skills.py and the browser) ----------
SKILL_PROJECTS: tuple[str, ...] = ("PAY", "CART", "AUTH", "PROD", "ORD")
MAX_SKILL_BYTES = 16384
MAX_USER_SKILLS = 50
TOOL_CALL_BUDGET = 20
LIBRARY_ID = "common"

COMMAND_NAME_RE = re.compile(r"^[A-Z][A-Z0-9]{1,15}(_[A-Z0-9]{1,24}){1,5}$")
MAX_COMMAND_NAME_LEN = 64
FILENAME_SUFFIX = "_SKILL.md"
# Same pattern text as COMMAND_NAME_RE, for FastAPI ``Path(pattern=...)``.
COMMAND_NAME_PATTERN = COMMAND_NAME_RE.pattern

_NAME_FORMAT_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_KEY_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)[ \t]*:[ \t]*(.*)$")
# The single [SYSTEM] marker regex, applied per line (identical in the Runtime).
SYSTEM_MARKER_RE = re.compile(r"\s*\[system\]", re.IGNORECASE)
SKILL_DELIMITER = "<<<SKILL"
_KNOWN_KEYS = {"name", "description", "license", "compatibility"}
_BLOCK_INDICATORS = {">", ">-", "|", "|-"}
MAX_DESCRIPTION_CHARS = 1024
MAX_NAME_CHARS = 64

MESSAGES: dict[str, str] = {
    "filename": "File name must look like SYSTEM_WHAT_SKILL.md, for example JIRA_ROADMAP_SKILL.md.",
    "too_large": "Skill is larger than 16 KB.",
    "control_chars": "File contains control characters.",
    "frontmatter_missing": "File must start with --- frontmatter.",
    "frontmatter_unclosed": "Frontmatter is not closed with ---.",
    "name_missing": "Frontmatter needs a name.",
    "name_format": (
        "name must be lowercase letters, digits and single hyphens, "
        "not starting or ending with a hyphen (max 64)."
    ),
    "description_missing": "Frontmatter needs a description.",
    "description_too_long": "description is longer than 1024 characters.",
    "body_empty": "The skill has no instructions.",
    "forbidden_marker": "Text contains a reserved marker ([SYSTEM] or <<<SKILL).",
}


@dataclass
class ValidationResult:
    """Outcome of ``validate_skill``; ``errors`` is a list of ``{rule, message}``."""

    errors: list[dict] = field(default_factory=list)
    command_name: str | None = None
    content: str = ""
    name: str | None = None
    description: str | None = None
    body: str = ""
    ignored_keys: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def rules(self) -> list[str]:
        return [e["rule"] for e in self.errors]

    @property
    def warnings(self) -> list[str]:
        out = []
        for key in self.ignored_keys:
            if key == "allowed-tools":
                out.append("`allowed-tools` was ignored: a skill cannot grant tools.")
            else:
                out.append(f"`{key}` was ignored.")
        return out


def command_name_from_filename(filename: str) -> str | None:
    """Return the command name for a valid skill filename, else None."""
    if not isinstance(filename, str) or not filename.endswith(FILENAME_SUFFIX):
        return None
    name = filename[: -len(FILENAME_SUFFIX)]
    if len(name) > MAX_COMMAND_NAME_LEN or not COMMAND_NAME_RE.match(name):
        return None
    return name


def is_command_name(name: object) -> bool:
    return (
        isinstance(name, str)
        and len(name) <= MAX_COMMAND_NAME_LEN
        and COMMAND_NAME_RE.match(name) is not None
    )


def normalise_project(project: str) -> str | None:
    """Upper-case and check against the five ids; None when invalid."""
    value = project.strip().upper() if isinstance(project, str) else ""
    return value if value in SKILL_PROJECTS else None


def sha256_hex(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def normalise_content(content: str) -> str:
    """Remove a leading BOM and convert CRLF / lone CR to LF."""
    if content.startswith("\ufeff"):
        content = content[1:]
    return content.replace("\r\n", "\n").replace("\r", "\n")


def _has_control_chars(text: str) -> bool:
    return any((ord(c) < 0x20 and c not in "\t\n\r") or ord(c) == 0x7F for c in text)


def parse_frontmatter(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    """Parse the frontmatter subset: returns (values, ignored_keys).

    ``lines`` are the lines between the two ``---`` fences.
    """
    entries: dict[str, dict] = {}
    order: list[str] = []
    current: str | None = None
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        if line[0] in " \t" or line.startswith("- "):
            if current is not None:
                entries[current]["cont"].append(line.strip())
            continue
        match = _KEY_LINE_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key not in entries:
            order.append(key)
        entries[key] = {"value": value, "cont": []}  # duplicate: last one wins
        current = key
    values: dict[str, str] = {}
    for key in order:
        value, cont = entries[key]["value"], entries[key]["cont"]
        if value in _BLOCK_INDICATORS:
            value = ("\n" if value.startswith("|") else " ").join(cont).strip()
        else:
            value = " ".join([value, *cont] if value else cont).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    ignored = [k for k in order if k not in _KNOWN_KEYS]
    return values, ignored


def validate_skill(
    filename: str, content: str, expected_name: str | None = None
) -> ValidationResult:
    """Run the full rule list on a skill file; never raises.

    ``expected_name`` (the path name on PUT) adds a ``filename`` error when the
    filename does not equal ``{expected_name}_SKILL.md``.
    """
    result = ValidationResult()

    def add(rule: str, message: str | None = None) -> None:
        result.errors.append({"rule": rule, "message": message or MESSAGES[rule]})

    command = command_name_from_filename(filename)
    if command is None:
        add("filename")
    elif expected_name is not None and command != expected_name:
        add("filename", f"File name must be {expected_name}{FILENAME_SUFFIX}.")
        command = None
    result.command_name = command

    try:
        raw_size = len(content.encode("utf-8"))
    except UnicodeEncodeError:
        add("control_chars")
        return result
    if raw_size > MAX_SKILL_BYTES:
        add("too_large")

    text = normalise_content(content)
    result.content = text
    if _has_control_chars(text):
        add("control_chars")

    if SKILL_DELIMITER in text or any(SYSTEM_MARKER_RE.match(l) for l in text.split("\n")):
        add("forbidden_marker")

    lines = text.split("\n")
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or lines[start].rstrip() != "---":
        add("frontmatter_missing")
        return result
    end = None
    for i in range(start + 1, len(lines)):
        if lines[i].rstrip() == "---":
            end = i
            break
    if end is None:
        add("frontmatter_unclosed")
        return result

    values, ignored = parse_frontmatter(lines[start + 1 : end])
    result.ignored_keys = ignored
    name = values.get("name", "")
    description = values.get("description", "")
    result.name = name or None
    result.description = description or None
    result.body = "\n".join(lines[end + 1 :]).strip()

    if not name:
        add("name_missing")
    else:
        if (
            not _NAME_FORMAT_RE.match(name)
            or len(name) > MAX_NAME_CHARS
            or "--" in name
        ):
            add("name_format")
        if command is not None:
            expected = command.lower().replace("_", "-")
            if name != expected:
                add("name_mismatch", f"name must be {expected} for {command}{FILENAME_SUFFIX}.")
    if not description:
        add("description_missing")
    elif len(description) > MAX_DESCRIPTION_CHARS:
        add("description_too_long")
    if not result.body:
        add("body_empty")
    return result
