/**
 * Visualization envelope types for the custom dashboard (design §1.4).
 *
 * `VizSpec` is a discriminated union on `type`. These types are the single
 * definition shared by the validator (`lib/vizEnvelope.ts`), the renderers
 * (`components/dashboard/charts/*`), the grid helpers (`lib/dashboardWidgets.ts`)
 * and the API client, so there is no drift.
 */

/** A single flat data/row value. Nested objects/arrays are rejected by the validator. */
export type VizValue = string | number | null;

/** A flat data/table row: a map of string keys to scalar values. */
export type VizRow = Record<string, VizValue>;

/** One chart series drawn against the shared `xKey`. */
export interface VizSeries {
  name: string;
  dataKey: string;
}

/** One table column definition. */
export interface VizColumn {
  key: string;
  label: string;
}

export interface LineSpec {
  type: "line";
  title: string;
  xKey: string;
  series: VizSeries[];
  data: VizRow[];
}

export interface AreaSpec {
  type: "area";
  title: string;
  xKey: string;
  series: VizSeries[];
  data: VizRow[];
}

export interface BarSpec {
  type: "bar";
  title: string;
  xKey: string;
  series: VizSeries[];
  data: VizRow[];
  /** Opt-in: color each bar by category. Honored only for a single-series bar. */
  varyColors?: boolean;
  /**
   * Opt-in orientation. Defaults to `"vertical"` (categories on the x-axis,
   * value up the y-axis). `"horizontal"` lays the bars out sideways (categories
   * down the y-axis) — useful when category labels are long or numerous.
   */
  orientation?: "vertical" | "horizontal";
}

export interface PieSpec {
  type: "pie";
  title: string;
  /** The data-row key naming each slice (reuses the chart envelope's xKey). */
  xKey: string;
  /**
   * Exactly one series: its `dataKey` names the numeric value of each slice and
   * its `name` labels the measure. Each data row is one slice.
   */
  series: VizSeries[];
  data: VizRow[];
}

export interface TableSpec {
  type: "table";
  title: string;
  columns: VizColumn[];
  rows: VizRow[];
}

/** A chart spec: line, area, bar or pie (share the xKey/series/data shape). */
export type ChartSpec = LineSpec | AreaSpec | BarSpec | PieSpec;

/** Any renderable visualization spec. */
export type VizSpec = ChartSpec | TableSpec;

/**
 * A saved dashboard widget: a validated spec plus the stored `lg` (12-col)
 * grid layout. The four smaller breakpoints (md/sm/xs/xxs) are derived on load
 * (design §1.4 / §4), never stored.
 */
export interface SavedWidget {
  id: string;
  spec: VizSpec;
  layout: { x: number; y: number; w: number; h: number };
}
