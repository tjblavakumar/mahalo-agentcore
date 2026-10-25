import { describe, it, expect } from "vitest";
import { SERVICES } from "./connections";

describe("SERVICES", () => {
  it("declares exactly the four connected services", () => {
    expect(SERVICES.map((s) => s.key)).toEqual(["jira", "confluence", "github", "servicenow"]);
    expect(SERVICES).toHaveLength(4);
  });

  it("gives every service a label, icon, and description", () => {
    for (const s of SERVICES) {
      expect(s.label.length).toBeGreaterThan(0);
      expect(s.icon.length).toBeGreaterThan(0);
      expect(s.description.length).toBeGreaterThan(0);
    }
  });
});
