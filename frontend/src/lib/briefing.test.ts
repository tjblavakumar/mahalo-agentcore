import { describe, it, expect } from "vitest";
import {
  dismiss,
  formatDate,
  formatWhen,
  groupBySystem,
  isBriefing,
  markShown,
  moreCount,
  newLoginId,
  readState,
  safeUrl,
  shouldFetch,
  type Briefing,
  type BriefingItem,
} from "./briefing";

function storage() {
  const m = new Map<string, string>();
  return {
    getItem: (k: string) => (m.has(k) ? m.get(k)! : null),
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  };
}

function item(over: Partial<BriefingItem> = {}): BriefingItem {
  return {
    id: "PAY-109",
    kind: "assigned",
    system: "Jira",
    line: "PAY-109 assigned to you",
    ts: "2026-11-24T20:30:00Z",
    precision: "minute",
    day_label: null,
    ref: { type: "story", id: "PAY-109", url: null },
    count: 1,
    tag: null,
    ...over,
  };
}

describe("shouldFetch / state", () => {
  it("never fetches without a login id", () => {
    expect(shouldFetch(null, null)).toBe(false);
  });
  it("fetches for a new login with no record", () => {
    expect(shouldFetch("a", null)).toBe(true);
    expect(shouldFetch("b", { loginId: "a", status: "shown" })).toBe(true);
  });
  it("does not fetch again after shown or dismissed in the same login", () => {
    expect(shouldFetch("a", { loginId: "a", status: "shown" })).toBe(false);
    expect(shouldFetch("a", { loginId: "a", status: "dismissed" })).toBe(false);
  });
  it("markShown and dismiss persist and read back", () => {
    const s = storage();
    expect(readState(s)).toBeNull();
    markShown("a", s);
    expect(readState(s)).toEqual({ loginId: "a", status: "shown" });
    dismiss("a", s);
    expect(readState(s)).toEqual({ loginId: "a", status: "dismissed" });
  });
  it("after logout (state removed) and a re-login with a new id it fetches again", () => {
    const s = storage();
    dismiss("a", s);
    expect(shouldFetch("a", readState(s))).toBe(false);
    s.removeItem("mahalo_briefing");
    expect(shouldFetch(newLoginId(), readState(s))).toBe(true);
    // even without the removal, a different id is a new login
    dismiss("a", s);
    expect(shouldFetch("b", readState(s))).toBe(true);
  });
  it("ignores corrupted stored state", () => {
    const s = storage();
    s.setItem("mahalo_briefing", "{not json");
    expect(readState(s)).toBeNull();
    s.setItem("mahalo_briefing", JSON.stringify({ loginId: "a", status: "weird" }));
    expect(readState(s)).toBeNull();
  });
  it("newLoginId returns distinct ids", () => {
    expect(newLoginId()).not.toBe(newLoginId());
  });
});

describe("groupBySystem", () => {
  it("orders groups Jira, ServiceNow, CI/CD, Confluence, Git then others and keeps counts", () => {
    const items = [
      item({ id: "1", system: "Git" }),
      item({ id: "2", system: "Zeta" }),
      item({ id: "3", system: "Jira" }),
      item({ id: "4", system: "CI/CD" }),
      item({ id: "5", system: "Jira" }),
      item({ id: "6", system: "ServiceNow" }),
      item({ id: "7", system: "Confluence" }),
    ];
    const groups = groupBySystem(items);
    expect(groups.map((g) => g.system)).toEqual([
      "Jira",
      "ServiceNow",
      "CI/CD",
      "Confluence",
      "Git",
      "Zeta",
    ]);
    expect(groups[0].items.map((i) => i.id)).toEqual(["3", "5"]);
  });
});

describe("formatWhen / formatDate", () => {
  const gen = "2026-11-24T22:30:00Z";
  it("minute precision", () => {
    expect(formatWhen(item({ ts: "2026-11-24T22:29:30Z" }), gen)).toBe("just now");
    expect(formatWhen(item({ ts: "2026-11-24T22:00:00Z" }), gen)).toBe("30 min ago");
    expect(formatWhen(item({ ts: "2026-11-24T19:30:00Z" }), gen)).toBe("3 h ago");
    expect(formatWhen(item({ ts: "2026-11-21T22:30:00Z" }), gen)).toBe("3 days ago");
  });
  it("day precision uses the label, then the day difference", () => {
    expect(formatWhen(item({ precision: "day", day_label: "today" }), gen)).toBe("today");
    expect(formatWhen(item({ precision: "day", day_label: "yesterday", ts: "2026-11-23T23:59:59Z" }), gen)).toBe(
      "yesterday"
    );
    expect(formatWhen(item({ precision: "day", ts: "2026-11-21T23:59:59Z" }), gen)).toBe("3 days ago");
  });
  it("empty for a missing timestamp; formatDate gives the calendar date", () => {
    expect(formatWhen(item({ ts: null }), gen)).toBe("");
    expect(formatDate(item({ ts: "2026-11-21T18:00:00Z" }))).toBe("2026-11-21");
  });
});

describe("safeUrl / moreCount / isBriefing", () => {
  it("accepts only https links", () => {
    expect(safeUrl("https://git.example.test/x")).toBe("https://git.example.test/x");
    expect(safeUrl("http://git.example.test/x")).toBeNull();
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl(null)).toBeNull();
  });
  const base: Briefing = {
    persona: "dev",
    generated_at: "2026-11-24T22:30:00Z",
    mode: "recent",
    headline: "Since yesterday",
    counts: { last_24h: 2, earlier: 1 },
    top: [],
    items: [item(), item({ id: "x" })],
    earlier: [item({ id: "y" })],
    snapshot: [],
    unavailable: [],
    labels: {},
  };
  it("moreCount is items plus earlier and zero in snapshot mode", () => {
    expect(moreCount(base)).toBe(3);
    expect(moreCount({ ...base, mode: "snapshot", snapshot: ["a"] })).toBe(0);
  });
  it("isBriefing rejects malformed bodies", () => {
    expect(isBriefing(base)).toBe(true);
    expect(isBriefing({ headline: "x" })).toBe(false);
    expect(isBriefing(null)).toBe(false);
  });
});