import { describe, it, expect } from "vitest";
import { buildIdeaRequestText } from "./ideaRequest";
import type { ChartIdea } from "@/types/idea";

function idea(overrides: Partial<ChartIdea> = {}): ChartIdea {
  return {
    title: "Sprint velocity",
    description: "Story points completed per sprint",
    chartType: "bar",
    projects: [],
    metric: "story points",
    ...overrides,
  };
}

describe("buildIdeaRequestText", () => {
  it("leads with the metric when present", () => {
    const out = buildIdeaRequestText(idea({ metric: "story points" }), []);
    expect(out.startsWith("story points")).toBe(true);
  });

  it("falls back to the title when metric is empty", () => {
    const out = buildIdeaRequestText(idea({ metric: "" }), []);
    expect(out.startsWith("Sprint velocity")).toBe(true);
  });

  it("omits the project clause when no keys resolve", () => {
    const out = buildIdeaRequestText(idea(), []);
    expect(out).not.toContain(" for ");
  });

  it("adds a project clause joined with ', ' when keys resolve", () => {
    const out = buildIdeaRequestText(idea(), ["PAY", "AUTH"]);
    expect(out).toContain(" for PAY, AUTH");
  });

  it("de-dups / uppercases / drops unknown keys in the project clause", () => {
    const out = buildIdeaRequestText(idea(), ["pay", "PAY", "ZZZ", "auth"]);
    expect(out).toContain(" for PAY, AUTH");
    expect(out).not.toContain("ZZZ");
  });

  it("uses chart wording for non-table types", () => {
    const out = buildIdeaRequestText(idea({ chartType: "line" }), []);
    expect(out.endsWith(" as a line chart")).toBe(true);
  });

  it("uses table wording for the table type", () => {
    const out = buildIdeaRequestText(idea({ chartType: "table" }), []);
    expect(out.endsWith(" as a table")).toBe(true);
  });

  it("matches the exact formula for a known input", () => {
    const out = buildIdeaRequestText(
      idea({ metric: "open PRs", chartType: "bar" }),
      ["PAY", "AUTH"]
    );
    expect(out).toBe("open PRs for PAY, AUTH as a bar chart");
  });
});
