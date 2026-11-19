import { describe, it, expect } from "vitest";
import { applyOption, matchSkills, parseSlash, type SlashSkill } from "./commands";

const skills: SlashSkill[] = [
  { name: "JIRA_ROADMAP", description: "Propose a two-sprint roadmap", builtin: true },
  { name: "JIRA_SPRINT_REPORT", description: "Sprint report", builtin: true },
  { name: "TEAM_STANDUP", description: "Summarise yesterday's work", builtin: false },
];

describe("parseSlash precedence table", () => {
  it("is mode none for text that does not start with /", () => {
    expect(parseSlash("hello /JIRA_ROADMAP", skills).mode).toBe("none");
  });

  it("row 1: third token is an error", () => {
    const r = parseSlash("/JIRA_ROADMAP PAY X", skills);
    expect(r.mode).toBe("error");
    expect(r.listOpen).toBe(false);
    expect(r.error).toContain("one project");
  });

  it("row 2: partial name opens the list", () => {
    const r = parseSlash("/JIRA", skills);
    expect(r.mode).toBe("name");
    expect(r.listOpen).toBe(true);
    expect(r.options).toEqual(["JIRA_ROADMAP", "JIRA_SPRINT_REPORT"]);
  });

  it("row 2: / alone lists all skills, built-ins first", () => {
    const r = parseSlash("/", skills);
    expect(r.mode).toBe("name");
    expect(r.options).toEqual(["JIRA_ROADMAP", "JIRA_SPRINT_REPORT", "TEAM_STANDUP"]);
  });

  it("row 2: no match keeps the list closed and carries the message", () => {
    const r = parseSlash("/ZZZ", skills);
    expect(r.mode).toBe("name");
    expect(r.listOpen).toBe(false);
    expect(r.error).toBe("No skill named /ZZZ. Type / to see the list.");
  });

  it("row 3: a known name is ready with a null project and a closed list", () => {
    const r = parseSlash("/JIRA_ROADMAP", skills);
    expect(r).toMatchObject({ mode: "ready", listOpen: false, skill: "JIRA_ROADMAP", project: null });
  });

  it("row 4: trailing space opens the five project ids", () => {
    const r = parseSlash("/JIRA_ROADMAP ", skills);
    expect(r.mode).toBe("project");
    expect(r.listOpen).toBe(true);
    expect(r.options).toEqual(["PAY", "CART", "AUTH", "PROD", "ORD"]);
  });

  it("row 5: a full project id is ready with the list closed", () => {
    const r = parseSlash("/JIRA_ROADMAP PAY", skills);
    expect(r).toMatchObject({ mode: "ready", listOpen: false, project: "PAY" });
  });

  it("row 6: a project prefix filters the ids", () => {
    const r = parseSlash("/JIRA_ROADMAP PA", skills);
    expect(r.mode).toBe("project");
    expect(r.listOpen).toBe(true);
    expect(r.options).toEqual(["PAY"]);
  });

  it("row 7: an unknown project is an error", () => {
    const r = parseSlash("/JIRA_ROADMAP XYZ", skills);
    expect(r.mode).toBe("error");
    expect(r.error).toBe("Project must be one of PAY, CART, AUTH, PROD, ORD.");
  });

  it("row 8: unknown name with a project or trailing space is an error", () => {
    expect(parseSlash("/NOPE PAY", skills)).toMatchObject({
      mode: "error",
      error: "No skill named /NOPE. Type / to see the list.",
    });
    expect(parseSlash("/NOPE ", skills).mode).toBe("error");
  });
});

describe("parseSlash extra cases", () => {
  it("accepts a lower-case command and project, normalising the project", () => {
    expect(parseSlash("/jira_roadmap pay", skills)).toMatchObject({
      mode: "ready",
      skill: "JIRA_ROADMAP",
      project: "PAY",
    });
  });

  it("accepts multiple spaces and a tab between tokens", () => {
    expect(parseSlash("/JIRA_ROADMAP   PAY", skills).project).toBe("PAY");
    expect(parseSlash("/JIRA_ROADMAP\tPAY", skills).project).toBe("PAY");
  });

  it("rejects a newline", () => {
    const r = parseSlash("/JIRA_ROADMAP\nPAY", skills);
    expect(r.mode).toBe("error");
    expect(r.error).toBe("A skill command must be on one line.");
  });
});

describe("matchSkills and applyOption", () => {
  it("matches on description text too and caps at 8", () => {
    expect(matchSkills(skills, "yesterday").map((s) => s.name)).toEqual(["TEAM_STANDUP"]);
    const many = Array.from({ length: 12 }, (_, i) => ({
      name: `AAA_S${i}`,
      description: "",
      builtin: false,
    }));
    expect(matchSkills(many, "").length).toBe(8);
  });

  it("builds the replacement text", () => {
    expect(applyOption("/JI", parseSlash("/JI", skills), "JIRA_ROADMAP")).toBe("/JIRA_ROADMAP ");
    expect(applyOption("/JIRA_ROADMAP ", parseSlash("/JIRA_ROADMAP ", skills), "CART")).toBe(
      "/JIRA_ROADMAP CART"
    );
  });
});
