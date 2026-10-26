/**
 * Pure builder for the strict-viz instruction injected into `/chat` (design §5.2).
 *
 * The thin API forwards `message` verbatim to the Runtime; there is no
 * server-side system-prompt hook, so the strict-output contract is composed
 * client-side here (mirroring how the old `buildDashboardPrompt` worked). No
 * DOM, no side effects — unit-tested under the `node` vitest env.
 */

import type { Persona } from "@/lib/personas";
import { SEED_PROJECTS } from "@/lib/projects";

/** Resolve selected keys to a `PAY, AUTH` clause: de-duplicated, uppercased, known keys only pass through by key. */
function resolveProjectKeys(projectKeys: string[]): string {
  const known = new Set(SEED_PROJECTS.map((p) => p.key));
  const seen = new Set<string>();
  const parts: string[] = [];
  for (const raw of projectKeys) {
    const key = raw.trim().toUpperCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    if (known.has(key)) parts.push(key);
  }
  return parts.join(", ");
}

/**
 * Build the `/chat` message for a dashboard viz request.
 *
 * @param userRequest the raw free-text the user typed
 * @param persona     the active persona (supplies label/role/developerId context)
 * @param projectKeys optional PM authoring aid — selected seed project keys
 */
export function buildVizPrompt(
  userRequest: string,
  persona: Persona,
  projectKeys?: string[]
): string {
  const projectClause = projectKeys && projectKeys.length > 0 ? resolveProjectKeys(projectKeys) : "";

  const lines = [
    `You are a dashboard visualization generator for ${persona.personaLabel} ` +
      `(${persona.role}, developer_id ${persona.developerId}). Convert the user's request ` +
      `into EXACTLY ONE visualization and reply with ONLY a single minified JSON object and ` +
      `nothing else — no prose, no explanation, no markdown, no code fences.`,
    `The JSON MUST match one of these shapes:`,
    `(1) a chart: {"type":"line"|"area"|"bar","title":string,"xKey":string,` +
      `"series":[{"name":string,"dataKey":string}],"data":[{...}]} where every data row object ` +
      `has the key named by xKey plus every series dataKey; or`,
    `(2) a table: {"type":"table","title":string,"columns":[{"key":string,"label":string}],` +
      `"rows":[{...}]}.`,
    `Use the connected systems (Jira, Confluence, GitHub/Gitea, ServiceNow) to get real values ` +
      `for this persona. Keep it to at most 6 series, 100 data rows, 12 columns, 200 table rows.`,
    `If the request cannot be expressed as one of these four visualizations, reply with ONLY ` +
      `{"type":"none"} and nothing else.`,
  ];

  if (projectClause) {
    lines.push(`Projects: ${projectClause}`);
  }

  lines.push(`User request: ${userRequest}`);

  return lines.join("\n");
}
