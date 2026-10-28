import { describe, it, expect } from "vitest";
import { parseIdeaEnvelope } from "./ideaEnvelope";

function validItem(overrides: Record<string, unknown> = {}) {
  return {
    title: "Sprint velocity",
    description: "Story points completed per sprint",
    chartType: "bar",
    projects: ["PAY"],
    metric: "story points",
    ...overrides,
  };
}

describe("parseIdeaEnvelope", () => {
  it("rejects non-JSON with not-json", () => {
    const r = parseIdeaEnvelope("not json at all");
    expect(r).toEqual({ ok: false, reason: "not-json" });
  });

  it("strips a code fence before parsing", () => {
    const raw = "```json\n" + JSON.stringify({ ideas: [validItem()] }) + "\n```";
    const r = parseIdeaEnvelope(raw);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.ideas).toHaveLength(1);
  });

  it("accepts a bare top-level array as a lenient fallback", () => {
    const r = parseIdeaEnvelope(JSON.stringify([validItem()]));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.ideas).toHaveLength(1);
  });

  it("rejects a non-object without an ideas array (no-ideas-field)", () => {
    expect(parseIdeaEnvelope("42")).toEqual({ ok: false, reason: "no-ideas-field" });
    expect(parseIdeaEnvelope(JSON.stringify({ foo: 1 }))).toEqual({
      ok: false,
      reason: "no-ideas-field",
    });
  });

  it("maps an empty ideas array to empty", () => {
    expect(parseIdeaEnvelope(JSON.stringify({ ideas: [] }))).toEqual({
      ok: false,
      reason: "empty",
    });
  });

  it("drops an item missing title", () => {
    const r = parseIdeaEnvelope(
      JSON.stringify({ ideas: [validItem({ title: "" }), validItem({ title: "Keep" })] })
    );
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.ideas).toHaveLength(1);
      expect(r.ideas[0].title).toBe("Keep");
    }
  });

  it("drops an item missing description", () => {
    const r = parseIdeaEnvelope(
      JSON.stringify({ ideas: [validItem({ description: "" })] })
    );
    expect(r).toEqual({ ok: false, reason: "empty" });
  });

  it("drops an item with a bad chartType", () => {
    const r = parseIdeaEnvelope(
      JSON.stringify({ ideas: [validItem({ chartType: "pie" })] })
    );
    expect(r).toEqual({ ok: false, reason: "empty" });
  });

  it("accepts chartType case-insensitively and lowercases it", () => {
    const r = parseIdeaEnvelope(
      JSON.stringify({ ideas: [validItem({ chartType: "LINE" })] })
    );
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.ideas[0].chartType).toBe("line");
  });

  it("keeps valid items when some are invalid", () => {
    const r = parseIdeaEnvelope(
      JSON.stringify({
        ideas: [
          validItem({ title: "Good one" }),
          validItem({ chartType: "nope", title: "Bad" }),
        ],
      })
    );
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.ideas).toHaveLength(1);
      expect(r.ideas[0].title).toBe("Good one");
    }
  });

  it("filters unknown project keys to a known subset", () => {
    const r = parseIdeaEnvelope(
      JSON.stringify({ ideas: [validItem({ projects: ["pay", "ZZZ", "PAY"] })] })
    );
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.ideas[0].projects).toEqual(["PAY"]);
  });

  it("defaults projects to [] when not an array", () => {
    const r = parseIdeaEnvelope(
      JSON.stringify({ ideas: [validItem({ projects: "PAY" })] })
    );
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.ideas[0].projects).toEqual([]);
  });

  it("collapses duplicate ideas (same title + chartType)", () => {
    const r = parseIdeaEnvelope(
      JSON.stringify({
        ideas: [
          validItem({ title: "Velocity" }),
          validItem({ title: "  velocity " }),
        ],
      })
    );
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.ideas).toHaveLength(1);
  });

  it("caps the result at 5 ideas", () => {
    const ideas = Array.from({ length: 8 }, (_, i) =>
      validItem({ title: `Idea ${i}` })
    );
    const r = parseIdeaEnvelope(JSON.stringify({ ideas }));
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.ideas).toHaveLength(5);
  });

  it("clamps over-length title, description, and metric", () => {
    const r = parseIdeaEnvelope(
      JSON.stringify({
        ideas: [
          validItem({
            title: "t".repeat(100),
            description: "d".repeat(200),
            metric: "m".repeat(100),
          }),
        ],
      })
    );
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.ideas[0].title).toHaveLength(60);
      expect(r.ideas[0].description).toHaveLength(120);
      expect(r.ideas[0].metric).toHaveLength(60);
    }
  });

  it("defaults metric to '' when missing", () => {
    const r = parseIdeaEnvelope(
      JSON.stringify({ ideas: [validItem({ metric: undefined })] })
    );
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.ideas[0].metric).toBe("");
  });
});
