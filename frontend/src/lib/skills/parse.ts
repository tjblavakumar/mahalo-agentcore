/**
 * Browser-side skill validator (skills design, section B). Same rule list and
 * semantics as api/app/skills.py; the shared vector file keeps them in step.
 * Fast feedback only: the API is the trust boundary.
 */

export const COMMAND_NAME_RE = /^[A-Z][A-Z0-9]{1,15}(_[A-Z0-9]{1,24}){1,5}$/;
export const MAX_COMMAND_NAME_LEN = 64;
export const FILENAME_SUFFIX = "_SKILL.md";
export const MAX_SKILL_BYTES = 16384;
export const MAX_DESCRIPTION_CHARS = 1024;
export const MAX_NAME_CHARS = 64;

const NAME_FORMAT_RE = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/;
const KEY_LINE_RE = /^([A-Za-z][A-Za-z0-9_-]*)[ \t]*:[ \t]*(.*)$/;
const SYSTEM_MARKER_RE = /^\s*\[system\]/i;
const SKILL_DELIMITER = "<<<SKILL";
const KNOWN_KEYS = new Set(["name", "description", "license", "compatibility"]);
const BLOCK_INDICATORS = new Set([">", ">-", "|", "|-"]);

export const RULE_MESSAGES: Record<string, string> = {
  filename: "File name must look like SYSTEM_WHAT_SKILL.md, for example JIRA_ROADMAP_SKILL.md.",
  too_large: "Skill is larger than 16 KB.",
  control_chars: "File contains control characters.",
  frontmatter_missing: "File must start with --- frontmatter.",
  frontmatter_unclosed: "Frontmatter is not closed with ---.",
  name_missing: "Frontmatter needs a name.",
  name_format:
    "name must be lowercase letters, digits and single hyphens, not starting or ending with a hyphen (max 64).",
  description_missing: "Frontmatter needs a description.",
  description_too_long: "description is longer than 1024 characters.",
  body_empty: "The skill has no instructions.",
  forbidden_marker: "Text contains a reserved marker ([SYSTEM] or <<<SKILL).",
};

export interface SkillRuleError {
  rule: string;
  message: string;
}

export interface SkillValidation {
  ok: boolean;
  errors: SkillRuleError[];
  rules: string[];
  commandName: string | null;
  content: string;
  name: string | null;
  description: string | null;
  body: string;
  ignoredKeys: string[];
  warnings: string[];
}

export function isCommandName(name: unknown): name is string {
  return (
    typeof name === "string" &&
    name.length <= MAX_COMMAND_NAME_LEN &&
    COMMAND_NAME_RE.test(name)
  );
}

export function commandNameFromFilename(filename: unknown): string | null {
  if (typeof filename !== "string" || !filename.endsWith(FILENAME_SUFFIX)) return null;
  const name = filename.slice(0, -FILENAME_SUFFIX.length);
  return isCommandName(name) ? name : null;
}

export function normaliseContent(content: string): string {
  let text = content;
  if (text.startsWith("\ufeff")) text = text.slice(1);
  return text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

function hasControlChars(text: string): boolean {
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if ((c < 0x20 && c !== 0x09 && c !== 0x0a && c !== 0x0d) || c === 0x7f) return true;
  }
  return false;
}

function hasLoneSurrogate(text: string): boolean {
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      const next = text.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        i++;
        continue;
      }
      return true;
    }
    if (c >= 0xdc00 && c <= 0xdfff) return true;
  }
  return false;
}

function utf8Length(text: string): number {
  return new TextEncoder().encode(text).length;
}

/** Parse the frontmatter subset: values plus the keys that are ignored. */
export function parseFrontmatter(lines: string[]): {
  values: Record<string, string>;
  ignoredKeys: string[];
} {
  const entries = new Map<string, { value: string; cont: string[] }>();
  const order: string[] = [];
  let current: string | null = null;
  for (const line of lines) {
    if (!line.trim() || line.startsWith("#")) continue;
    if (line[0] === " " || line[0] === "\t" || line.startsWith("- ")) {
      if (current !== null) entries.get(current)!.cont.push(line.trim());
      continue;
    }
    const match = KEY_LINE_RE.exec(line);
    if (!match) continue;
    const key = match[1];
    const value = match[2].trim();
    if (!entries.has(key)) order.push(key);
    entries.set(key, { value, cont: [] }); // duplicate: last one wins
    current = key;
  }
  const values: Record<string, string> = {};
  for (const key of order) {
    const { value: raw, cont } = entries.get(key)!;
    let value: string;
    if (BLOCK_INDICATORS.has(raw)) {
      value = cont.join(raw.startsWith("|") ? "\n" : " ").trim();
    } else {
      value = (raw ? [raw, ...cont] : cont).join(" ").trim();
    }
    if (value.length >= 2 && value[0] === value[value.length - 1] && (value[0] === "'" || value[0] === '"')) {
      value = value.slice(1, -1);
    }
    values[key] = value;
  }
  return { values, ignoredKeys: order.filter((k) => !KNOWN_KEYS.has(k)) };
}

function warningFor(key: string): string {
  return key === "allowed-tools"
    ? "`allowed-tools` was ignored: a skill cannot grant tools."
    : `\`${key}\` was ignored.`;
}

export function validateSkill(filename: string, content: string): SkillValidation {
  const errors: SkillRuleError[] = [];
  const add = (rule: string, message?: string) =>
    errors.push({ rule, message: message ?? RULE_MESSAGES[rule] });
  const result: SkillValidation = {
    ok: false,
    errors,
    rules: [],
    commandName: null,
    content: "",
    name: null,
    description: null,
    body: "",
    ignoredKeys: [],
    warnings: [],
  };
  const finish = (): SkillValidation => {
    result.rules = errors.map((e) => e.rule);
    result.ok = errors.length === 0;
    result.warnings = result.ignoredKeys.map(warningFor);
    return result;
  };

  const command = commandNameFromFilename(filename);
  if (command === null) add("filename");
  result.commandName = command;

  if (hasLoneSurrogate(content)) {
    add("control_chars");
    return finish();
  }
  if (utf8Length(content) > MAX_SKILL_BYTES) add("too_large");

  const text = normaliseContent(content);
  result.content = text;
  if (hasControlChars(text)) add("control_chars");

  const lines = text.split("\n");
  if (text.includes(SKILL_DELIMITER) || lines.some((l) => SYSTEM_MARKER_RE.test(l))) {
    add("forbidden_marker");
  }

  let start = 0;
  while (start < lines.length && !lines[start].trim()) start++;
  if (start >= lines.length || lines[start].trimEnd() !== "---") {
    add("frontmatter_missing");
    return finish();
  }
  let end = -1;
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i].trimEnd() === "---") {
      end = i;
      break;
    }
  }
  if (end === -1) {
    add("frontmatter_unclosed");
    return finish();
  }

  const { values, ignoredKeys } = parseFrontmatter(lines.slice(start + 1, end));
  result.ignoredKeys = ignoredKeys;
  const name = values["name"] ?? "";
  const description = values["description"] ?? "";
  result.name = name || null;
  result.description = description || null;
  result.body = lines.slice(end + 1).join("\n").trim();

  if (!name) {
    add("name_missing");
  } else {
    if (!NAME_FORMAT_RE.test(name) || name.length > MAX_NAME_CHARS || name.includes("--")) {
      add("name_format");
    }
    if (command !== null) {
      const expected = command.toLowerCase().replace(/_/g, "-");
      if (name !== expected) {
        add("name_mismatch", `name must be ${expected} for ${command}${FILENAME_SUFFIX}.`);
      }
    }
  }
  if (!description) add("description_missing");
  else if (Array.from(description).length > MAX_DESCRIPTION_CHARS) add("description_too_long");
  if (!result.body) add("body_empty");
  return finish();
}
