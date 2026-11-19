/**
 * Slash-command parsing for the chat input (skills design, E.1). Pure
 * functions, no React. The precedence table in the design maps one-to-one to
 * the branches of `parseSlash`.
 */

import { SKILL_PROJECTS } from "./types";

export type SlashMode = "none" | "name" | "project" | "ready" | "error";

export interface SlashSkill {
  name: string;
  description: string;
  builtin: boolean;
}

export interface SlashResult {
  mode: SlashMode;
  listOpen: boolean;
  /** Canonical skill name when the name token is a known skill. */
  skill?: string;
  /** Normalised project id, or null when none was typed (mode "ready"). */
  project?: string | null;
  error?: string;
  /** Picker rows: skill names in "name" mode, project ids in "project" mode. */
  options: string[];
}

export const MAX_PICKER_ROWS = 8;
const SLASH_RE = /^\/(\S*)(?:[ \t]+(\S+))?(?:[ \t]+(\S+))?([ \t]*)$/;

function noSkill(token: string): string {
  return `No skill named /${token}. Type / to see the list.`;
}

/** Skills whose command name starts with, or whose name or description contains, the text. */
export function matchSkills(skills: SlashSkill[], text: string): SlashSkill[] {
  const q = text.toLowerCase();
  return skills
    .filter(
      (s) =>
        !q ||
        s.name.toLowerCase().startsWith(q) ||
        s.name.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q)
    )
    .sort((a, b) => {
      if (a.builtin !== b.builtin) return a.builtin ? -1 : 1;
      return a.name.localeCompare(b.name);
    })
    .slice(0, MAX_PICKER_ROWS);
}

export function parseSlash(message: string, skills: SlashSkill[]): SlashResult {
  if (!message.startsWith("/")) return { mode: "none", listOpen: false, options: [] };

  const m = SLASH_RE.exec(message);
  if (!m) {
    return {
      mode: "error",
      listOpen: false,
      options: [],
      error: "A skill command must be on one line.",
    };
  }
  const [, nameToken, projectToken, extraToken, trailing] = m;

  // Row 1
  if (extraToken !== undefined) {
    return {
      mode: "error",
      listOpen: false,
      options: [],
      error: "A skill takes one project, for example /JIRA_ROADMAP PAY.",
    };
  }

  const known = skills.find((s) => s.name.toLowerCase() === nameToken.toLowerCase());
  const hasProject = projectToken !== undefined;

  if (!known) {
    // Row 2
    if (!hasProject && trailing === "") {
      const matches = matchSkills(skills, nameToken);
      return {
        mode: "name",
        listOpen: matches.length > 0,
        options: matches.map((s) => s.name),
        error: matches.length > 0 ? undefined : noSkill(nameToken),
      };
    }
    // Row 8
    return { mode: "error", listOpen: false, options: [], error: noSkill(nameToken) };
  }

  if (!hasProject) {
    // Row 3
    if (trailing === "") {
      return { mode: "ready", listOpen: false, skill: known.name, project: null, options: [] };
    }
    // Row 4
    return {
      mode: "project",
      listOpen: true,
      skill: known.name,
      project: null,
      options: [...SKILL_PROJECTS],
    };
  }

  const typed = projectToken.toUpperCase();
  // Row 5
  if ((SKILL_PROJECTS as readonly string[]).includes(typed)) {
    return { mode: "ready", listOpen: false, skill: known.name, project: typed, options: [] };
  }
  // Row 6
  const filtered = SKILL_PROJECTS.filter((p) => p.startsWith(typed));
  if (filtered.length > 0) {
    return {
      mode: "project",
      listOpen: true,
      skill: known.name,
      project: null,
      options: filtered,
    };
  }
  // Row 7
  return {
    mode: "error",
    listOpen: false,
    skill: known.name,
    options: [],
    error: "Project must be one of PAY, CART, AUTH, PROD, ORD.",
  };
}

/** The text that replaces the input when the user picks a row. */
export function applyOption(message: string, result: SlashResult, option: string): string {
  if (result.mode === "name") return `/${option} `;
  if (result.mode === "project" && result.skill) return `/${result.skill} ${option}`;
  return message;
}
