/**
 * "Since yesterday" login briefing: response types, grouping, time labels and the
 * once-per-login state. Pure helpers (storage is passed in) so they unit test
 * without a browser. The ranking itself lives in the thin API (`GET /briefing`).
 */

export type BriefingMode = "recent" | "topped_up" | "widened" | "snapshot";

export interface BriefingItem {
  id: string;
  kind: string;
  system: string;
  line: string;
  /** UTC `YYYY-MM-DDTHH:MM:SSZ`; for day-precision items it is a computed point in that day. */
  ts: string | null;
  precision: "minute" | "day";
  day_label: "today" | "yesterday" | null;
  ref: { type: string; id: string; url: string | null };
  count: number;
  tag: "earlier" | null;
}

export interface Briefing {
  persona: string;
  generated_at: string;
  mode: BriefingMode;
  headline: string;
  counts: { last_24h: number; earlier: number };
  top: BriefingItem[];
  items: BriefingItem[];
  earlier: BriefingItem[];
  snapshot: string[];
  unavailable: string[];
  labels: Record<string, string>;
}

export interface BriefingState {
  loginId: string;
  status: "shown" | "dismissed";
}

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export const LOGIN_ID_KEY = "mahalo_login_id";
export const BRIEFING_STATE_KEY = "mahalo_briefing";

/** Display order of the system groups in "More". */
export const SYSTEM_ORDER = ["Jira", "ServiceNow", "CI/CD", "Confluence", "Git"] as const;

/** A fresh id for one explicit login (written next to the persona in localStorage). */
export function newLoginId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c && typeof c.randomUUID === "function") {
    return c.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export function readState(storage: StorageLike = localStorage): BriefingState | null {
  try {
    const raw = storage.getItem(BRIEFING_STATE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<BriefingState> | null;
    if (
      parsed &&
      typeof parsed.loginId === "string" &&
      (parsed.status === "shown" || parsed.status === "dismissed")
    ) {
      return { loginId: parsed.loginId, status: parsed.status };
    }
  } catch {
    // corrupted value: treat as no record
  }
  return null;
}

export function writeState(state: BriefingState, storage: StorageLike = localStorage): void {
  try {
    storage.setItem(BRIEFING_STATE_KEY, JSON.stringify(state));
  } catch {
    // storage unavailable: the card simply is not remembered
  }
}

/** Fetch only for a known login that has no record yet (neither shown nor dismissed). */
export function shouldFetch(loginId: string | null, state: BriefingState | null): boolean {
  return Boolean(loginId) && state?.loginId !== loginId;
}

export function markShown(loginId: string, storage: StorageLike = localStorage): void {
  writeState({ loginId, status: "shown" }, storage);
}

export function dismiss(loginId: string, storage: StorageLike = localStorage): void {
  writeState({ loginId, status: "dismissed" }, storage);
}

export interface SystemGroup {
  system: string;
  items: BriefingItem[];
}

/** Group items by system in the fixed display order; unknown systems follow, alphabetically. */
export function groupBySystem(items: BriefingItem[]): SystemGroup[] {
  const map = new Map<string, BriefingItem[]>();
  for (const item of items) {
    const list = map.get(item.system);
    if (list) list.push(item);
    else map.set(item.system, [item]);
  }
  const known = SYSTEM_ORDER.filter((s) => map.has(s));
  const other = [...map.keys()]
    .filter((s) => !(SYSTEM_ORDER as readonly string[]).includes(s))
    .sort();
  return [...known, ...other].map((system) => ({ system, items: map.get(system)! }));
}

/** Relative time label for an item, measured against the server's `generated_at`. */
export function formatWhen(item: BriefingItem, generatedAt: string): string {
  if (!item.ts) return "";
  const now = Date.parse(generatedAt);
  const at = Date.parse(item.ts);
  if (Number.isNaN(now) || Number.isNaN(at)) return "";
  if (item.precision === "day") {
    if (item.day_label) return item.day_label;
    const days = Math.round(
      (Date.parse(generatedAt.slice(0, 10)) - Date.parse(item.ts.slice(0, 10))) / 86_400_000
    );
    return days <= 1 ? "yesterday" : `${days} days ago`;
  }
  const minutes = Math.floor(Math.max(0, now - at) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** Calendar date (UTC) of an item, used next to the "earlier" tag. */
export function formatDate(item: BriefingItem): string {
  return item.ts ? item.ts.slice(0, 10) : "";
}

/** Only https links are rendered as links. */
export function safeUrl(url: string | null | undefined): string | null {
  return typeof url === "string" && url.startsWith("https://") ? url : null;
}

/** Number shown in the "More (N)" toggle; zero (or snapshot mode) means no toggle. */
export function moreCount(b: Briefing): number {
  return b.mode === "snapshot" ? 0 : b.items.length + b.earlier.length;
}

/** Minimal shape check so a malformed 200 never reaches the card. */
export function isBriefing(value: unknown): value is Briefing {
  if (!value || typeof value !== "object") return false;
  const v = value as Partial<Briefing>;
  return (
    typeof v.headline === "string" &&
    typeof v.generated_at === "string" &&
    Array.isArray(v.top) &&
    Array.isArray(v.items) &&
    Array.isArray(v.earlier) &&
    Array.isArray(v.snapshot) &&
    Array.isArray(v.unavailable) &&
    !!v.counts &&
    !!v.labels
  );
}
