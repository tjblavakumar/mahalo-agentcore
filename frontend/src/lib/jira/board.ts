/** Pure helpers for the Current Sprint board: grouping, progress, dates. */

import type { Board, ColumnKey, Story } from "./types";
import { COLUMN_ORDER } from "./types";

/** Group a flat story list into the four ordered status columns. */
export function groupByColumn(stories: Story[]): Record<ColumnKey, Story[]> {
  const columns: Record<ColumnKey, Story[]> = {
    todo: [],
    in_progress: [],
    in_review: [],
    done: [],
  };
  for (const story of stories) {
    if (COLUMN_ORDER.includes(story.status as ColumnKey)) {
      columns[story.status as ColumnKey].push(story);
    }
  }
  return columns;
}

/** Sprint progress as a 0..100 integer percentage (0 when there are no points). */
export function sprintProgressPct(completed: number | undefined, total: number | undefined): number {
  const c = completed ?? 0;
  const t = total ?? 0;
  if (t <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round((c / t) * 100)));
}

/**
 * Whole days remaining until `end_date` (inclusive of the end day), relative to
 * `now`. Negative days are clamped to 0. Dates are parsed as UTC calendar days.
 */
export function daysLeft(endDate: string, now: Date = new Date()): number {
  const end = Date.parse(`${endDate}T00:00:00Z`);
  if (Number.isNaN(end)) return 0;
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const diff = Math.ceil((end - today) / 86_400_000);
  return Math.max(0, diff);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Format an ISO date `YYYY-MM-DD` as e.g. "Aug 11". Returns "" for bad input. */
export function formatShortDate(iso: string): string {
  if (!iso || iso.length < 10) return "";
  const y = Number(iso.slice(0, 4));
  const m = Number(iso.slice(5, 7));
  const d = Number(iso.slice(8, 10));
  if (!m || m < 1 || m > 12 || !d) return "";
  void y;
  return `${MONTHS[m - 1]} ${d}`;
}

/** "Aug 11 – Aug 22" for a sprint window. */
export function formatDateRange(start: string, end: string): string {
  const a = formatShortDate(start);
  const b = formatShortDate(end);
  if (!a && !b) return "";
  return `${a} – ${b}`;
}

/** Count the stories across all columns of a board. */
export function boardStoryCount(board: Board): number {
  return COLUMN_ORDER.reduce((n, key) => n + (board.columns[key]?.length ?? 0), 0);
}
