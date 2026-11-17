import { describe, it, expect } from "vitest";
import { matchBadge } from "./badgeTokens";

describe("matchBadge", () => {
  it("maps severities to tones", () => {
    expect(matchBadge("P1")).toEqual({ label: "P1", tone: "red" });
    expect(matchBadge("P2")?.tone).toBe("orange");
    expect(matchBadge("P3")?.tone).toBe("yellow");
    expect(matchBadge("P4")?.tone).toBe("gray");
  });

  it("matches status tokens case-insensitively and trimmed", () => {
    expect(matchBadge("  DONE ")).toEqual({ label: "Done", tone: "green" });
    expect(matchBadge("In Progress")?.label).toBe("In progress");
    expect(matchBadge("in review")?.tone).toBe("purple");
    expect(matchBadge("rolled back")?.label).toBe("Rolled back");
    for (const t of ["todo", "open", "investigating", "resolved", "success", "failed"]) {
      expect(matchBadge(t)).not.toBeNull();
    }
  });

  it("does not badge a token inside a sentence", () => {
    expect(matchBadge("The ticket is still open")).toBeNull();
    expect(matchBadge("open issues")).toBeNull();
    expect(matchBadge("Deployment failed twice")).toBeNull();
  });

  it("does not badge P1 inside a longer cell", () => {
    expect(matchBadge("P1 outage")).toBeNull();
    expect(matchBadge("P1, P2")).toBeNull();
    expect(matchBadge("P10")).toBeNull();
  });

  it("returns null for empty and prototype-like input", () => {
    expect(matchBadge("")).toBeNull();
    expect(matchBadge("   ")).toBeNull();
    expect(matchBadge("constructor")).toBeNull();
  });
});
