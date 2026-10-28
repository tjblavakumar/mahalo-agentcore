/**
 * Pure builder for the lightweight ideas `/chat` message (design §1).
 *
 * The thin API forwards `message` verbatim to the Runtime; there is no
 * server-side system-prompt hook, so the strict-output contract is composed
 * client-side here (mirroring `buildVizPrompt`). This message asks for idea
 * *metadata only* and forbids data fetching / tool calls — steering, not a hard
 * guarantee (see design headline "Accepted tradeoff on requirement (1)"). No
 * DOM, no side effects — unit-tested under the `node` vitest env.
 */

import type { Persona } from "@/lib/personas";
import { SEED_PROJECTS } from "@/lib/projects";

/** The literal count clause requested of the model. */
const COUNT_CLAUSE = "3 to 5";

/** Resolve selected keys to a `PAY, AUTH` clause: trim, uppercase, SEED_PROJECTS membership, de-dup. */
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
 * Build the lightweight ideas `/chat` message for a persona + selected projects.
 *
 * @param persona     the active persona (supplies label/role/developerId context)
 * @param projectKeys the currently selected seed project keys
 */
export function buildIdeaPrompt(persona: Persona, projectKeys: string[]): string {
  const projectClause = resolveProjectKeys(projectKeys);

  const lines = [
    `You are a dashboard idea generator for ${persona.personaLabel} ` +
      `(${persona.role}, developer_id ${persona.developerId}).`,
    `Suggest ${COUNT_CLAUSE} chart or table IDEAS that would be useful on this persona's dashboard.`,
    `Do NOT fetch, query, or compute any data. Do NOT call any tools. Propose ideas only, from your ` +
      `knowledge of what this persona cares about for the listed projects. Reply FAST.`,
    `Reply with ONLY a single minified JSON object and nothing else — no prose, no explanation, no ` +
      `markdown, no code fences.`,
    `The JSON MUST be exactly: {"ideas":[{"title":string,"description":string,"chartType":"line"|"area"|"bar"|"table","projects":[string],"metric":string}]}`,
    `Rules: title is a short label (<= 60 chars); description is one line of at most 120 chars saying ` +
      `what the chart shows; chartType is one of line, area, bar, table; projects is a subset of the ` +
      `listed project keys (may be empty for a cross-project idea); metric names the single measure the ` +
      `idea concerns (e.g. "story points", "open PRs", "deployment count"). Provide between 3 and 5 ideas.`,
    `Each idea must describe a metric over a dimension that could later be drawn as that chart type.`,
    `Do NOT include any chart data, rows, series, or numbers — ideas are metadata only.`,
    `If you cannot suggest ideas, reply with ONLY {"ideas":[]} and nothing else.`,
  ];

  if (projectClause) {
    lines.push(`Projects: ${projectClause}`);
  }

  return lines.join("\n");
}
