/**
 * Pure parser/validator for the lightweight ideas reply (design §3).
 *
 * `parseIdeaEnvelope(raw)` is intentionally MORE forgiving than
 * `parseVizEnvelope`: a malformed idea surface degrades to "fewer/zero ideas",
 * never to an error wall, because ideas are advisory. The rule is drop-bad-items,
 * not reject-whole-response (except when the top-level shape is unusable). Pure
 * string -> result, no DOM — the primary unit-test target.
 */

import type { ChartIdea, IdeaChartType } from "@/types/idea";
import { SEED_PROJECTS } from "@/lib/projects";
import { stripFence } from "@/lib/stripFence";

export type IdeaRejectReason = "not-json" | "no-ideas-field" | "empty";

export type IdeaParseResult =
  | { ok: true; ideas: ChartIdea[] } // 1..5 valid ideas (prompt requests 3-5; parser tolerates fewer)
  | { ok: false; reason: IdeaRejectReason };

// Field caps (design §2/§3).
const MAX_TITLE = 60;
const MAX_DESCRIPTION = 120;
const MAX_METRIC = 60;
const MAX_IDEAS = 5;

const CHART_TYPES: ReadonlySet<string> = new Set(["line", "area", "bar", "table"]);

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function clamp(value: string, max: number): string {
  return value.length > max ? value.slice(0, max) : value;
}

/** Resolve projects: array only, trim -> uppercase -> SEED_PROJECTS-only -> de-dup. */
function resolveProjects(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const known = new Set(SEED_PROJECTS.map((p) => p.key));
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of value) {
    if (typeof raw !== "string") continue;
    const key = raw.trim().toUpperCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    if (known.has(key)) out.push(key);
  }
  return out;
}

/** Validate + normalize one raw item; null if it must be dropped. */
function normalizeItem(raw: unknown): ChartIdea | null {
  if (!isPlainObject(raw)) return null;

  // title: required non-empty string after trim; clamp to 60.
  if (typeof raw.title !== "string") return null;
  const title = clamp(raw.title.trim(), MAX_TITLE);
  if (title.length === 0) return null;

  // description: required non-empty string after trim; clamp to 120.
  if (typeof raw.description !== "string") return null;
  const description = clamp(raw.description.trim(), MAX_DESCRIPTION);
  if (description.length === 0) return null;

  // chartType: required enum, case-insensitive.
  if (typeof raw.chartType !== "string") return null;
  const chartTypeLower = raw.chartType.trim().toLowerCase();
  if (!CHART_TYPES.has(chartTypeLower)) return null;
  const chartType = chartTypeLower as IdeaChartType;

  // projects: optional array -> resolved known keys; never drops the item.
  const projects = resolveProjects(raw.projects);

  // metric: optional string -> trim -> clamp 60; default "".
  const metric =
    typeof raw.metric === "string" ? clamp(raw.metric.trim(), MAX_METRIC) : "";

  return { title, description, chartType, projects, metric };
}

/**
 * Parse + validate a raw ideas reply into 1..5 ideas or a typed reject reason.
 * Any `ok:false` maps to the strip's quiet `empty` state (design §5/§8).
 */
export function parseIdeaEnvelope(raw: string): IdeaParseResult {
  const stripped = stripFence(raw);

  let parsed: unknown;
  try {
    parsed = JSON.parse(stripped);
  } catch {
    return { ok: false, reason: "not-json" };
  }

  // Accept {"ideas":[...]} or a lenient bare top-level array.
  let rawIdeas: unknown[];
  if (Array.isArray(parsed)) {
    rawIdeas = parsed;
  } else if (isPlainObject(parsed) && Array.isArray(parsed.ideas)) {
    rawIdeas = parsed.ideas;
  } else {
    return { ok: false, reason: "no-ideas-field" };
  }

  // Validate + normalize, dropping bad items.
  const normalized: ChartIdea[] = [];
  for (const item of rawIdeas) {
    const idea = normalizeItem(item);
    if (idea) normalized.push(idea);
  }

  // De-dup by normalized title (lowercased) + chartType.
  const seen = new Set<string>();
  const deduped: ChartIdea[] = [];
  for (const idea of normalized) {
    const key = `${idea.title.toLowerCase()}|${idea.chartType}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(idea);
  }

  const ideas = deduped.slice(0, MAX_IDEAS);
  if (ideas.length === 0) {
    return { ok: false, reason: "empty" };
  }
  return { ok: true, ideas };
}
