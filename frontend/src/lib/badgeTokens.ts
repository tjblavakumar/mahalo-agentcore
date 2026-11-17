/**
 * Pure matcher for severity / status badges in chat answers.
 *
 * Conservative on purpose: a token is badged only when the WHOLE text handed in
 * (a table cell, an inline code span or a strong span) is exactly that token,
 * ignoring case and surrounding whitespace. Words inside sentences never match.
 */

export type BadgeTone =
  | "red"
  | "orange"
  | "yellow"
  | "gray"
  | "green"
  | "blue"
  | "purple";

export interface BadgeMatch {
  /** Canonical display label, e.g. "P1" or "In progress". */
  label: string;
  tone: BadgeTone;
}

const TOKENS: Record<string, BadgeMatch> = {
  p1: { label: "P1", tone: "red" },
  p2: { label: "P2", tone: "orange" },
  p3: { label: "P3", tone: "yellow" },
  p4: { label: "P4", tone: "gray" },
  done: { label: "Done", tone: "green" },
  "in progress": { label: "In progress", tone: "blue" },
  "in review": { label: "In review", tone: "purple" },
  todo: { label: "Todo", tone: "gray" },
  open: { label: "Open", tone: "blue" },
  investigating: { label: "Investigating", tone: "orange" },
  resolved: { label: "Resolved", tone: "green" },
  success: { label: "Success", tone: "green" },
  failed: { label: "Failed", tone: "red" },
  "rolled back": { label: "Rolled back", tone: "orange" },
};

export function matchBadge(text: string): BadgeMatch | null {
  const key = text.trim().toLowerCase();
  // Object.hasOwn avoids prototype keys such as "constructor".
  return Object.hasOwn(TOKENS, key) ? TOKENS[key] : null;
}

export const BADGE_CLASSES: Record<BadgeTone, string> = {
  red: "bg-red-100 text-red-800 border-red-200",
  orange: "bg-orange-100 text-orange-800 border-orange-200",
  yellow: "bg-yellow-100 text-yellow-800 border-yellow-200",
  gray: "bg-gray-100 text-gray-700 border-gray-200",
  green: "bg-green-100 text-green-800 border-green-200",
  blue: "bg-blue-100 text-blue-800 border-blue-200",
  purple: "bg-purple-100 text-purple-800 border-purple-200",
};
