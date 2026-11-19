import { describe, it, expect } from "vitest";
import { describeCheckError, describeFailure, formatRunSummary } from "./ui";

describe("describeCheckError", () => {
  it.each(["check_timeout", "check_empty", "check_invalid_output", "check_failed"])(
    "%s offers Check again with the server message",
    (type) => {
      expect(describeCheckError({ type, message: "msg" })).toMatchObject({
        message: "msg",
        control: "check_again",
        showProjectSelector: false,
      });
    }
  );
  it("bad_project shows the selector", () => {
    expect(describeCheckError({ type: "bad_project", message: "m" })).toMatchObject({
      control: "check_again",
      showProjectSelector: true,
    });
  });
  it("bad_skill has no control", () => {
    expect(describeCheckError({ type: "bad_skill", message: "m" }).control).toBeNull();
  });
});

describe("describeFailure", () => {
  it("check 404 removes the skill", () => {
    expect(describeFailure("check", { status: 404, code: "skill_not_found" }, false)).toMatchObject({
      message: "This skill no longer exists.",
      control: null,
      removeSkill: true,
    });
  });
  it("check 422 without a code", () => {
    expect(describeFailure("check", { status: 422 }, false)).toMatchObject({
      message: "The skill or project is not valid.",
      control: null,
    });
  });
  it.each([502, undefined, 500])("check %s is the network row", (status) => {
    expect(describeFailure("check", { status }, false)).toMatchObject({
      message: "The check could not be completed. Try again.",
      control: "check_again",
    });
  });
  it("run 409 skill_changed", () => {
    expect(describeFailure("run", { status: 409, code: "skill_changed" }, false)).toMatchObject({
      message: "This skill changed after the check. Check it again.",
      control: "check_again",
    });
  });
  it("run 404", () => {
    expect(describeFailure("run", { status: 404, code: "skill_not_found" }, true).removeSkill).toBe(true);
  });
  it("run 422", () => {
    expect(describeFailure("run", { status: 422 }, false)).toMatchObject({
      message: "The run request was not valid. Check it again.",
      control: "check_again",
    });
  });
  it("run 502 read-only skill offers Run again", () => {
    expect(describeFailure("run", { status: 502 }, false)).toMatchObject({
      message:
        "The run took longer than the limit or failed. Nothing was changed (this skill only reads). Try again.",
      control: "run_again",
    });
  });
  it("run network error on a write skill has no retry", () => {
    expect(describeFailure("run", {}, true)).toMatchObject({
      message: "The run did not finish. Check the approval cards before retrying.",
      control: null,
    });
  });
});

describe("formatRunSummary", () => {
  const info = {
    name: "JIRA_ROADMAP",
    project: "PAY",
    tool_calls_used: 7,
    tool_call_budget: 20,
    budget_exhausted: false,
    deadline_exhausted: false,
    elapsed_seconds: 52.4,
  };
  it("formats the line", () => {
    expect(formatRunSummary(info, false)).toBe("JIRA_ROADMAP, PAY, 7 of 20 tool calls, 52 s");
  });
  it("adds waiting for approval", () => {
    expect(formatRunSummary(info, true)).toBe(
      "JIRA_ROADMAP, PAY, 7 of 20 tool calls, 52 s, waiting for approval"
    );
  });
});
