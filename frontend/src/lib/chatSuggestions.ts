/**
 * Pure helpers for building context-aware chat suggestion prompts.
 *
 * The chat empty-state shows a few "starter" prompts. Rather than hardcoding
 * them, we derive them from the current context:
 *   - the user's role (product_manager / developer / executive)
 *   - the project currently in scope (to inject real names / keys)
 *   - the systems the user has actually connected (Jira / Confluence / GitHub /
 *     ServiceNow)
 *
 * This module is intentionally free of React and side effects so it is trivial
 * to unit test and can be recomputed as pure derived state.
 */

import type { Project, UserRole } from "@/types";

/** Integration types that a suggestion may depend on. */
export type IntegrationType = "jira" | "confluence" | "github" | "servicenow";

/**
 * A suggestion template. `text` may contain placeholders that are filled from
 * the scoped project:
 *   - {projectName}  -> project.name
 *   - {jiraKey}      -> project.jira_project_key
 *   - {repo}         -> project.github_repo_name
 *   - {service}      -> project.servicenow_service_name
 *   - {space}        -> project.confluence_space_key
 */
export interface SuggestionTemplate {
  /** Template string, possibly containing placeholders. */
  text: string;
  /**
   * Connection types this suggestion needs. The template is only offered when
   * every listed type is present in the connected set. Omit for suggestions
   * that don't depend on any specific system.
   */
  requires?: IntegrationType[];
  /**
   * When true, the template references the scoped project and is skipped when
   * no project is in scope (or a referenced key is missing).
   */
  needsProject?: boolean;
}

/** Placeholder -> project field resolution used during interpolation. */
const PLACEHOLDER_FIELDS: Record<string, keyof Project> = {
  projectName: "name",
  jiraKey: "jira_project_key",
  repo: "github_repo_name",
  service: "servicenow_service_name",
  space: "confluence_space_key",
};

/**
 * Ordered template sets per role. Ordering is deterministic (no randomization)
 * so the default suggestions are stable across visits for the same context.
 */
export const ROLE_TEMPLATES: Record<UserRole, SuggestionTemplate[]> = {
  product_manager: [
    { text: "What is the current sprint status for {projectName}?", requires: ["jira"], needsProject: true },
    { text: "Summarize open blockers across {projectName}", requires: ["jira"], needsProject: true },
    { text: "What is the team velocity this sprint?", requires: ["jira"] },
    { text: "Which stories should we prioritize next sprint?", requires: ["jira"] },
    { text: "Summarize the latest documentation updates", requires: ["confluence"] },
    { text: "Are there any production incidents affecting {projectName}?", requires: ["servicenow"], needsProject: true },
    { text: "Give me a delivery status overview" },
  ],
  developer: [
    { text: "Show open pull requests for {repo}", requires: ["github"], needsProject: true },
    { text: "Show open pull requests", requires: ["github"] },
    { text: "What are my assigned issues in {jiraKey}?", requires: ["jira"], needsProject: true },
    { text: "What issues are assigned to me?", requires: ["jira"] },
    { text: "Any recent failed deployments for {service}?", requires: ["servicenow"], needsProject: true },
    { text: "Find the technical docs for {projectName}", requires: ["confluence"], needsProject: true },
    { text: "What changed in the latest release?", requires: ["github"] },
  ],
  executive: [
    { text: "Give me a high-level status of {projectName}", needsProject: true },
    { text: "What are the top risks and blockers right now?", requires: ["jira"] },
    { text: "Summarize delivery progress across all projects", requires: ["jira"] },
    { text: "Any active production incidents?", requires: ["servicenow"] },
    { text: "How is the team performing this quarter?", requires: ["jira"] },
    { text: "What are our compliance requirements?", requires: ["confluence"] },
  ],
};

/**
 * Static fallback suggestions used when a role has no qualifying templates
 * (e.g. minimal connections). Kept generic and free of placeholders.
 */
export const FALLBACK_SUGGESTIONS: string[] = [
  "What can you help me with?",
  "Give me a status overview of my projects",
];

export interface BuildSuggestionsInput {
  /** The current user's role. When undefined, developer templates are used. */
  role?: UserRole;
  /** The project currently in scope, if any. */
  project?: Project | null;
  /** Connection types the user has configured. */
  connectedTypes: IntegrationType[];
  /** Maximum number of suggestions to return. Defaults to 4. */
  limit?: number;
}

/** Returns true when every required type is present in the connected set. */
function hasRequiredConnections(
  template: SuggestionTemplate,
  connected: Set<IntegrationType>,
): boolean {
  if (!template.requires || template.requires.length === 0) return true;
  return template.requires.every((type) => connected.has(type));
}

/**
 * Interpolates placeholders from the scoped project. Returns null when the
 * template references the project but a required field is missing/empty, so the
 * caller can skip it rather than render a broken prompt.
 */
function interpolate(template: SuggestionTemplate, project: Project | null | undefined): string | null {
  const placeholders = [...template.text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]);
  if (placeholders.length === 0) {
    return template.text;
  }

  if (!project) return null;

  let text = template.text;
  for (const key of placeholders) {
    const field = PLACEHOLDER_FIELDS[key];
    const value = field ? project[field] : undefined;
    if (value === null || value === undefined || value === "") {
      // A referenced project field is missing -> drop this suggestion.
      return null;
    }
    text = text.replaceAll(`{${key}}`, String(value));
  }
  return text;
}

/**
 * Builds a deterministic, context-aware list of suggestion strings.
 *
 * Rules:
 *  - Pick the template set for the role (falling back to developer).
 *  - Drop templates whose required connections aren't all present.
 *  - Interpolate project placeholders; drop templates that reference a missing
 *    project or project field.
 *  - De-duplicate resulting strings, preserving order.
 *  - Cap at `limit` (default 4). Falls back to generic suggestions when none
 *    qualify.
 */
export function buildSuggestions({
  role,
  project,
  connectedTypes,
  limit = 4,
}: BuildSuggestionsInput): string[] {
  const templates = ROLE_TEMPLATES[role ?? "developer"] ?? ROLE_TEMPLATES.developer;
  const connected = new Set(connectedTypes);

  const result: string[] = [];
  const seen = new Set<string>();

  for (const template of templates) {
    if (result.length >= limit) break;
    if (!hasRequiredConnections(template, connected)) continue;

    const text = interpolate(template, project);
    if (text === null) continue;
    if (seen.has(text)) continue;

    seen.add(text);
    result.push(text);
  }

  if (result.length === 0) {
    return FALLBACK_SUGGESTIONS.slice(0, limit);
  }

  return result;
}
