/**
 * Pure validator for the strict JSON visualization envelope (design §1.3).
 *
 * `parseVizEnvelope(raw)` is the single enforcement point: rendering code never
 * sees an invalid spec. It is 100% string -> result logic (no DOM), so it is the
 * primary unit-test target under the `node` vitest env.
 */

import type {
  VizSpec,
  ChartSpec,
  TableSpec,
  VizSeries,
  VizColumn,
  VizRow,
  VizValue,
} from "@/types/viz";
import { stripFence } from "@/lib/stripFence";

export type VizRejectReason =
  | "not-json"
  | "unknown-type"
  | "missing-field"
  | "empty-series"
  | "empty-data"
  | "row-shape"
  | "too-large"
  // Distinct developer-log signal for the agent's explicit {"type":"none"}
  // decline (design §14 item 3). The user-facing Q5 message is identical.
  | "declined";

export type VizParseResult =
  | { ok: true; spec: VizSpec }
  | { ok: false; reason: VizRejectReason };

// Size ceilings (design §1.3 rule 6).
const MAX_SERIES = 6;
const MAX_DATA_ROWS = 100;
const MAX_COLUMNS = 12;
const MAX_TABLE_ROWS = 200;

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isScalar(value: unknown): value is VizValue {
  return value === null || typeof value === "string" || typeof value === "number";
}

/** Every value in a row must be a scalar (string|number|null); nested -> row-shape. */
function isFlatRow(value: unknown): value is VizRow {
  if (!isPlainObject(value)) return false;
  return Object.values(value).every(isScalar);
}

function fail(reason: VizRejectReason): VizParseResult {
  return { ok: false, reason };
}

function validateChart(obj: Record<string, unknown>, type: "line" | "area" | "bar"): VizParseResult {
  const { title, xKey, series, data } = obj;

  if (!isNonEmptyString(title)) return fail("missing-field");
  if (!isNonEmptyString(xKey)) return fail("missing-field");

  if (!Array.isArray(series)) return fail("missing-field");
  if (series.length === 0) return fail("empty-series");
  if (series.length > MAX_SERIES) return fail("too-large");
  for (const s of series) {
    if (!isPlainObject(s) || !isNonEmptyString(s.name) || !isNonEmptyString(s.dataKey)) {
      return fail("missing-field");
    }
  }

  if (!Array.isArray(data)) return fail("missing-field");
  if (data.length === 0) return fail("empty-data");
  if (data.length > MAX_DATA_ROWS) return fail("too-large");
  for (const row of data) {
    if (!isFlatRow(row)) return fail("row-shape");
  }

  // xKey + every series dataKey must appear on the first data row.
  const first = data[0] as VizRow;
  if (!(xKey in first)) return fail("missing-field");
  for (const s of series as VizSeries[]) {
    if (!(s.dataKey in first)) return fail("missing-field");
  }

  const spec: ChartSpec = {
    type,
    title: title as string,
    xKey: xKey as string,
    series: (series as VizSeries[]).map((s) => ({ name: s.name, dataKey: s.dataKey })),
    data: data as VizRow[],
  };
  return { ok: true, spec };
}

function validateTable(obj: Record<string, unknown>): VizParseResult {
  const { title, columns, rows } = obj;

  if (!isNonEmptyString(title)) return fail("missing-field");

  if (!Array.isArray(columns)) return fail("missing-field");
  if (columns.length === 0) return fail("missing-field");
  if (columns.length > MAX_COLUMNS) return fail("too-large");
  for (const c of columns) {
    if (!isPlainObject(c) || !isNonEmptyString(c.key) || !isNonEmptyString(c.label)) {
      return fail("missing-field");
    }
  }

  if (!Array.isArray(rows)) return fail("missing-field");
  // An empty table is valid ("no open PRs" is a legitimate answer).
  if (rows.length > MAX_TABLE_ROWS) return fail("too-large");
  for (const row of rows) {
    if (!isFlatRow(row)) return fail("row-shape");
  }

  const spec: TableSpec = {
    type: "table",
    title: title as string,
    columns: (columns as VizColumn[]).map((c) => ({ key: c.key, label: c.label })),
    rows: rows as VizRow[],
  };
  return { ok: true, spec };
}

/**
 * Parse + validate a raw agent reply into a VizSpec or a typed reject reason.
 * Any `ok:false` triggers the Q5 message in the UI (design §5.1).
 */
export function parseVizEnvelope(raw: string): VizParseResult {
  const stripped = stripFence(raw);

  let parsed: unknown;
  try {
    parsed = JSON.parse(stripped);
  } catch {
    return fail("not-json");
  }

  if (!isPlainObject(parsed)) return fail("unknown-type");

  const type = parsed.type;
  // The agent's explicit clean decline (design §5.2 / §14 item 3).
  if (type === "none") return fail("declined");
  if (type === "table") {
    return validateTable(parsed);
  }
  if (type === "line" || type === "area" || type === "bar") {
    return validateChart(parsed, type);
  }
  return fail("unknown-type");
}
