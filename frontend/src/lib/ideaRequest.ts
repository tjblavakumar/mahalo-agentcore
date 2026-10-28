/**
 * Pure builder that turns a `ChartIdea` into the free-text request string handed
 * to `buildVizPrompt` at click time (design §4). Keeping this pure keeps the
 * click-to-build glue unit-testable.
 *
 * The FORMULA is authoritative (design D2):
 *   `${idea.metric || idea.title}${dimensionClause}${projectClause}${typeClause}`
 * where `dimensionClause` is "" (the metric/title already carries intent),
 * `projectClause` is ` for {keys}` (same de-dup/uppercase/SEED_PROJECTS resolution
 * as vizPrompt.ts, keys joined with ", ") when effectiveKeys resolves to >= 1 key
 * else "", and `typeClause` is ` as a table` for table else ` as a {chartType} chart`.
 */

import type { ChartIdea } from "@/types/idea";
import { SEED_PROJECTS } from "@/lib/projects";

/** Resolve keys: trim, uppercase, SEED_PROJECTS membership, de-dup — same rule as vizPrompt.ts. */
function resolveProjectKeys(projectKeys: string[]): string[] {
  const known = new Set(SEED_PROJECTS.map((p) => p.key));
  const seen = new Set<string>();
  const parts: string[] = [];
  for (const raw of projectKeys) {
    const key = raw.trim().toUpperCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    if (known.has(key)) parts.push(key);
  }
  return parts;
}

/**
 * Build the free-text request string for an idea, scoped to `effectiveKeys`.
 *
 * @param idea          the idea metadata
 * @param effectiveKeys the resolved project scope (same keys fed to buildVizPrompt)
 */
export function buildIdeaRequestText(idea: ChartIdea, effectiveKeys: string[]): string {
  const seed = idea.metric || idea.title;
  const dimensionClause = "";

  const keys = resolveProjectKeys(effectiveKeys);
  const projectClause = keys.length > 0 ? ` for ${keys.join(", ")}` : "";

  const typeClause =
    idea.chartType === "table" ? " as a table" : ` as a ${idea.chartType} chart`;

  return `${seed}${dimensionClause}${projectClause}${typeClause}`;
}
