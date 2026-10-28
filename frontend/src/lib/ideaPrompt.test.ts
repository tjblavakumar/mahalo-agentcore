import { describe, it, expect } from "vitest";
import { buildIdeaPrompt } from "./ideaPrompt";
import { PERSONAS } from "@/lib/personas";

const pm = PERSONAS.pm;
const dev = PERSONAS.dev;

describe("buildIdeaPrompt", () => {
  it("includes the persona context (label, role, developer_id)", () => {
    const out = buildIdeaPrompt(pm, []);
    expect(out).toContain(pm.personaLabel);
    expect(out).toContain(pm.role);
    expect(out).toContain(pm.developerId);
  });

  it("states the strict JSON / no-prose / no-fences contract", () => {
    const out = buildIdeaPrompt(dev, []);
    expect(out).toMatch(/single minified JSON object/);
    expect(out).toMatch(/no prose/);
    expect(out).toMatch(/no code fences/);
  });

  it("forbids data fetching and tool calls", () => {
    const out = buildIdeaPrompt(dev, []);
    expect(out).toMatch(/Do NOT fetch/);
    expect(out).toMatch(/Do NOT call any tools/);
    expect(out).toMatch(/Reply FAST/);
  });

  it("includes the exact ideas JSON shape line", () => {
    const out = buildIdeaPrompt(dev, []);
    expect(out).toContain(
      '{"ideas":[{"title":string,"description":string,"chartType":"line"|"area"|"bar"|"table","projects":[string],"metric":string}]}'
    );
  });

  it("requests between 3 and 5 ideas", () => {
    const out = buildIdeaPrompt(dev, []);
    expect(out).toContain("3 to 5");
  });

  it("includes the empty-ideas decline clause", () => {
    const out = buildIdeaPrompt(dev, []);
    expect(out).toContain('{"ideas":[]}');
  });

  it("adds a Projects clause when keys are supplied", () => {
    const out = buildIdeaPrompt(pm, ["PAY", "AUTH"]);
    expect(out).toContain("Projects: PAY, AUTH");
  });

  it("omits the Projects clause when no keys are supplied", () => {
    const out = buildIdeaPrompt(pm, []);
    expect(out).not.toMatch(/\nProjects:/);
  });

  it("de-duplicates and drops unknown project keys", () => {
    const out = buildIdeaPrompt(pm, ["pay", "PAY", "ZZZ"]);
    const clause = out.split("\n").find((l) => l.startsWith("Projects:"));
    expect(clause).toBe("Projects: PAY");
    expect(out).not.toContain("ZZZ");
  });
});
