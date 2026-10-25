import { describe, it, expect } from "vitest";
import { SEED_PROJECTS, buildDashboardPrompt } from "./projects";

describe("SEED_PROJECTS", () => {
  it("declares exactly the five expected seed project keys", () => {
    expect(SEED_PROJECTS.map((p) => p.key)).toEqual(["PAY", "CART", "AUTH", "PROD", "ORD"]);
  });
});

describe("buildDashboardPrompt", () => {
  it("returns the developer template with no project clause", () => {
    const out = buildDashboardPrompt({ role: "developer" });
    expect(out).toMatch(/Developer dashboard/);
    expect(out).not.toMatch(/\([A-Z]+\)/); // no `(KEY)` project clause
  });

  it("returns the executive template and ignores selectedProjectKeys", () => {
    const withKeys = buildDashboardPrompt({
      role: "executive",
      selectedProjectKeys: ["PAY", "AUTH"],
    });
    const withoutKeys = buildDashboardPrompt({ role: "executive" });
    expect(withKeys).toBe(withoutKeys);
    expect(withKeys).toMatch(/portfolio/i);
    expect(withKeys).not.toMatch(/\(PAY\)/);
  });

  it("returns the 'all projects' PM variant when no keys are selected", () => {
    const out = buildDashboardPrompt({ role: "product_manager" });
    expect(out).toMatch(/across all of my projects/);
    expect(out).not.toMatch(/\(PAY\)/);
  });

  it("returns the 'all projects' PM variant for an empty selection", () => {
    const out = buildDashboardPrompt({ role: "product_manager", selectedProjectKeys: [] });
    expect(out).toMatch(/across all of my projects/);
  });

  it("injects selected project names and keys into the PM prompt", () => {
    const out = buildDashboardPrompt({
      role: "product_manager",
      selectedProjectKeys: ["PAY", "AUTH"],
    });
    expect(out).toContain("Payment Gateway (PAY)");
    expect(out).toContain("User Authentication (AUTH)");
    expect(out).toMatch(/dashboard for projects/);
  });

  it("de-duplicates keys and preserves order", () => {
    const out = buildDashboardPrompt({
      role: "product_manager",
      selectedProjectKeys: ["PAY", "PAY", "CART"],
    });
    const payIndex = out.indexOf("(PAY)");
    const cartIndex = out.indexOf("(CART)");
    expect(payIndex).toBeGreaterThan(-1);
    expect(cartIndex).toBeGreaterThan(-1);
    expect(payIndex).toBeLessThan(cartIndex);
    // PAY appears exactly once
    expect(out.split("(PAY)").length - 1).toBe(1);
  });

  it("passes unknown keys through as a bare uppercased token", () => {
    const out = buildDashboardPrompt({
      role: "product_manager",
      selectedProjectKeys: ["xyz"],
    });
    expect(out).toMatch(/dashboard for projects XYZ\./);
  });
});
