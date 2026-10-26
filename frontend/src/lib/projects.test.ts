import { describe, it, expect } from "vitest";
import { SEED_PROJECTS } from "./projects";

describe("SEED_PROJECTS", () => {
  it("declares exactly the five expected seed project keys", () => {
    expect(SEED_PROJECTS.map((p) => p.key)).toEqual(["PAY", "CART", "AUTH", "PROD", "ORD"]);
  });

  it("gives each project a non-empty human-readable name", () => {
    for (const project of SEED_PROJECTS) {
      expect(project.name.trim().length).toBeGreaterThan(0);
    }
  });
});
