import { describe, it, expect } from "vitest";
import { diffStories, fingerprint, fingerprintMap } from "./diff";
import type { Story } from "./types";

function story(id: string, over: Partial<Story> = {}): Story {
  return {
    id,
    project_id: "CART",
    sprint_id: null,
    title: id,
    status: "todo",
    priority: "medium",
    story_points: 3,
    assignee: "dev-1",
    ...over,
  };
}

describe("fingerprint", () => {
  it("changes when a tracked field changes and ignores untracked ones", () => {
    const base = story("CART-1");
    expect(fingerprint({ ...base, description: "whatever" })).toBe(fingerprint(base));
    expect(fingerprint({ ...base, status: "done" })).not.toBe(fingerprint(base));
    expect(fingerprint({ ...base, assignee: "dev-2" })).not.toBe(fingerprint(base));
    expect(fingerprint({ ...base, sprint_id: "CART-S2" })).not.toBe(fingerprint(base));
    expect(fingerprint({ ...base, story_points: 5 })).not.toBe(fingerprint(base));
  });
});

describe("diffStories", () => {
  it("highlights nothing on the first poll", () => {
    const d = diffStories([story("CART-1")], null);
    expect(d.added.size).toBe(0);
    expect(d.changed.size).toBe(0);
  });

  it("detects added and changed keys", () => {
    const prev = fingerprintMap([story("CART-1"), story("CART-2", { status: "todo" })]);
    const now = [
      story("CART-1"), // unchanged
      story("CART-2", { status: "done" }), // changed
      story("CART-3"), // new
    ];
    const d = diffStories(now, prev);
    expect([...d.added]).toEqual(["CART-3"]);
    expect([...d.changed]).toEqual(["CART-2"]);
  });
});
