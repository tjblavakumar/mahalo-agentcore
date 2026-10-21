import { describe, it, expect } from "vitest";
import {
  buildSuggestions,
  FALLBACK_SUGGESTIONS,
  type IntegrationType,
} from "./chatSuggestions";
import type { Project } from "@/types";

const ALL: IntegrationType[] = ["jira", "confluence", "github", "servicenow"];

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 1,
    user_id: 1,
    name: "Checkout Cart",
    description: "",
    goal: "",
    project_type: "development",
    status: "active",
    jira_project_key: "CART",
    confluence_space_key: "CARTDOCS",
    github_repo_name: "cart-service",
    servicenow_service_name: "cart-service",
    generate_mock_data: false,
    is_active: true,
    is_selected: true,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("buildSuggestions", () => {
  it("selects templates for the given role", () => {
    const dev = buildSuggestions({ role: "developer", project: null, connectedTypes: ALL });
    const pm = buildSuggestions({ role: "product_manager", project: null, connectedTypes: ALL });
    // Developer set leads with PR-oriented prompts; PM set with sprint/status.
    expect(dev.some((s) => /pull requests/i.test(s))).toBe(true);
    expect(pm.some((s) => /sprint|velocity|blockers|priorit/i.test(s))).toBe(true);
  });

  it("defaults to developer templates when role is undefined", () => {
    const out = buildSuggestions({ role: undefined, project: null, connectedTypes: ["github"] });
    expect(out.some((s) => /pull requests/i.test(s))).toBe(true);
  });

  it("drops templates whose required connection is missing", () => {
    // No GitHub connected -> no PR suggestions for a developer.
    const out = buildSuggestions({
      role: "developer",
      project: null,
      connectedTypes: ["jira"],
    });
    expect(out.every((s) => !/pull requests/i.test(s))).toBe(true);
    // Jira-based suggestion should still be present.
    expect(out.some((s) => /assigned to me|issues/i.test(s))).toBe(true);
  });

  it("interpolates project placeholders when a project is scoped", () => {
    const out = buildSuggestions({
      role: "developer",
      project: makeProject(),
      connectedTypes: ["github"],
    });
    expect(out).toContain("Show open pull requests for cart-service");
  });

  it("skips project-referencing templates when no project is scoped", () => {
    const out = buildSuggestions({
      role: "developer",
      project: null,
      connectedTypes: ["github"],
    });
    // The {repo} template is skipped; the generic PR template remains.
    expect(out).toContain("Show open pull requests");
    expect(out.every((s) => !s.includes("{repo}"))).toBe(true);
  });

  it("skips a template when a referenced project field is empty", () => {
    const out = buildSuggestions({
      role: "developer",
      project: makeProject({ github_repo_name: null }),
      connectedTypes: ["github"],
    });
    expect(out.every((s) => !/pull requests for/i.test(s))).toBe(true);
    // Never emits a broken placeholder.
    expect(out.every((s) => !s.includes("{"))).toBe(true);
  });

  it("caps results at the limit", () => {
    const out = buildSuggestions({
      role: "product_manager",
      project: makeProject(),
      connectedTypes: ALL,
      limit: 3,
    });
    expect(out.length).toBe(3);
  });

  it("defaults the limit to 4", () => {
    const out = buildSuggestions({
      role: "product_manager",
      project: makeProject(),
      connectedTypes: ALL,
    });
    expect(out.length).toBeLessThanOrEqual(4);
    expect(out.length).toBeGreaterThan(0);
  });

  it("falls back to generic suggestions when nothing qualifies", () => {
    // Executive with no connections: templates that require systems are dropped,
    // but the project-only status template still needs a project. With neither,
    // we fall back.
    const out = buildSuggestions({
      role: "executive",
      project: null,
      connectedTypes: [],
    });
    expect(out).toEqual(FALLBACK_SUGGESTIONS.slice(0, 4));
  });

  it("does not produce duplicate strings", () => {
    const out = buildSuggestions({ role: "developer", project: makeProject(), connectedTypes: ALL });
    expect(new Set(out).size).toBe(out.length);
  });
});
