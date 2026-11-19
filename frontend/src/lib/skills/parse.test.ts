import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { commandNameFromFilename, isCommandName, validateSkill } from "./parse";

interface Case {
  id: string;
  filename: string;
  content: string;
  expect: {
    ok: boolean;
    rules: string[];
    name?: string;
    description?: string;
    ignored_keys?: string[];
  };
}

// The same vector file the Python validator runs (api/tests).
const cases: Case[] = JSON.parse(
  readFileSync(
    join(process.cwd(), "..", "api", "tests", "fixtures", "skill_validation_cases.json"),
    "utf-8"
  ).replace(/^\ufeff/, "")
);

describe("validateSkill (shared vectors)", () => {
  it("loads the vector file", () => {
    expect(cases.length).toBeGreaterThan(30);
  });

  for (const c of cases) {
    it(c.id, () => {
      const r = validateSkill(c.filename, c.content);
      expect(r.ok).toBe(c.expect.ok);
      expect([...new Set(r.rules)].sort()).toEqual([...c.expect.rules].sort());
      if (c.expect.name !== undefined) expect(r.name).toBe(c.expect.name);
      if (c.expect.description !== undefined) expect(r.description).toBe(c.expect.description);
      if (c.expect.ignored_keys !== undefined) {
        expect(r.ignoredKeys).toEqual(c.expect.ignored_keys);
      }
    });
  }
});

describe("command names", () => {
  it("accepts the built-in names and rejects bad ones", () => {
    expect(isCommandName("JIRA_ROADMAP")).toBe(true);
    expect(isCommandName("JIRA_SPRINT_REPORT")).toBe(true);
    expect(isCommandName("JIRA")).toBe(false);
    expect(isCommandName("jira_roadmap")).toBe(false);
    expect(commandNameFromFilename("JIRA_ROADMAP_SKILL.md")).toBe("JIRA_ROADMAP");
    expect(commandNameFromFilename("JIRA_ROADMAP.md")).toBeNull();
    expect(commandNameFromFilename("JIRA_SKILL.md")).toBeNull();
  });
});

describe("warnings", () => {
  it("explains an ignored allowed-tools key", () => {
    const r = validateSkill(
      "JIRA_ROADMAP_SKILL.md",
      "---\nname: jira-roadmap\ndescription: d\nallowed-tools: x\n---\nbody\n"
    );
    expect(r.warnings).toEqual(["`allowed-tools` was ignored: a skill cannot grant tools."]);
  });
});
