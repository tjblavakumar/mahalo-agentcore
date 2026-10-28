/**
 * Types for the ephemeral dashboard "Suggested for you" chart ideas (B1).
 *
 * A `ChartIdea` is idea *metadata only* — never chart data. It is produced by
 * the lightweight ideas `/chat` call (`buildIdeaPrompt` + `parseIdeaEnvelope`)
 * and, on click, turned into a real widget through the existing viz path. Ideas
 * are never persisted; only a built widget is.
 */

/** The idea chart types: the viz chart types plus `table`. */
export type IdeaChartType = "line" | "area" | "bar" | "table";

export interface ChartIdea {
  /** Short label, trimmed, clamped to <= 60 chars. */
  title: string;
  /** One line of "what it shows", trimmed, clamped to <= 120 chars. */
  description: string;
  /** Suggested chart type. */
  chartType: IdeaChartType;
  /** Subset of SEED_PROJECTS keys — de-duped, uppercased, known-only. May be []. */
  projects: string[];
  /** The single measure the idea concerns; trimmed, clamped to 60. May be "". */
  metric: string;
}
