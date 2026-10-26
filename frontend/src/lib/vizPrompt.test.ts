import { describe, it, expect } from "vitest";
import { buildVizPrompt } from "./vizPrompt";
import { PERSONAS } from "@/lib/personas";

const pm = PERSONAS.pm;
const dev = PERSONAS.dev;

describe("buildVizPrompt", () => {
  it("includes the persona context (label, role, developer_id)", () => {
    const out = buildVizPrompt("story points by sprint", pm);
    expect(out).toContain(pm.personaLabel);
    expect(out).toContain(pm.role);
    expect(out).toContain(pm.developerId);
  });

  it("states the strict single-JSON-object contract with no prose", () => {
    const out = buildVizPrompt("anything", dev);
    expect(out).toMatch(/EXACTLY ONE visualization/);
    expect(out).toMatch(/single minified JSON object/);
    expect(out).toMatch(/no prose/);
    expect(out).toMatch(/no code fences/);
  });

  it("includes both the chart and table shape lines", () => {
    const out = buildVizPrompt("x", dev);
    expect(out).toContain('"type":"line"|"area"|"bar"');
    expect(out).toContain('"type":"table"');
    expect(out).toContain('"series":[{"name":string,"dataKey":string}]');
    expect(out).toContain('"columns":[{"key":string,"label":string}]');
  });

  it("states the size limits", () => {
    const out = buildVizPrompt("x", dev);
    expect(out).toMatch(/at most 6 series, 100 data rows, 12 columns, 200 table rows/);
  });

  it("includes the {\"type\":\"none\"} decline clause", () => {
    const out = buildVizPrompt("x", dev);
    expect(out).toContain('{"type":"none"}');
  });

  it("embeds the raw user request verbatim", () => {
    const out = buildVizPrompt("open PRs by project", dev);
    expect(out).toContain("User request: open PRs by project");
  });

  it("adds a Projects clause when PM keys are supplied", () => {
    const out = buildVizPrompt("open PRs", pm, ["PAY", "AUTH"]);
    expect(out).toContain("Projects: PAY, AUTH");
  });

  it("omits the Projects clause when no keys are supplied", () => {
    const out = buildVizPrompt("open PRs", pm);
    expect(out).not.toMatch(/\nProjects:/);
  });

  it("de-duplicates and drops unknown project keys", () => {
    const out = buildVizPrompt("x", pm, ["pay", "PAY", "ZZZ"]);
    expect(out).toContain("Projects: PAY");
    expect(out).not.toContain("ZZZ");
    // PAY appears once in the Projects clause
    const clause = out.split("\n").find((l) => l.startsWith("Projects:"));
    expect(clause).toBe("Projects: PAY");
  });
});
