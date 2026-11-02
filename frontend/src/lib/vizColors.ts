/**
 * Single source of truth for chart colors (design §1.2: colors come from the
 * frontend, never from the envelope). Pure module — no DOM.
 */

import type { VizSpec } from "@/types/viz";

/** 10 distinct colors; the first six are the original palette (order preserved). */
export const PALETTE = [
  "#2563eb", // blue-600
  "#16a34a", // green-600
  "#d97706", // amber-600
  "#dc2626", // red-600
  "#7c3aed", // violet-600
  "#0891b2", // cyan-600
  "#db2777", // pink-600
  "#4d7c0f", // lime-700
  "#ea580c", // orange-600
  "#475569", // slate-600
];

/** Color for index `i`, wrapping around the palette. */
export function colorAt(i: number): string {
  const n = PALETTE.length;
  return PALETTE[((i % n) + n) % n];
}

/** True only for a single-series bar spec that opted in with `varyColors: true`. */
export function shouldVaryColors(spec: VizSpec): boolean {
  return spec.type === "bar" && spec.varyColors === true && spec.series.length === 1;
}
