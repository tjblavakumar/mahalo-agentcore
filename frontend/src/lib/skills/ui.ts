/**
 * Pure helpers for the skill UI: the failure table of design section C and the
 * run summary line of section D. Rows key on `status` and `code`, never on
 * message text.
 */

import type { SkillRunInfo } from "./types";

export type FailureControl = "check_again" | "run_again" | null;

export interface SkillFailure {
  message: string;
  control: FailureControl;
  /** Show the project selector on the card (check bad_project). */
  showProjectSelector: boolean;
  /** The skill no longer exists: remove it from the page state and the picker. */
  removeSkill: boolean;
}

export interface FailureInput {
  status?: number;
  code?: string;
  error?: string | null;
}

const NOT_FOUND = "This skill no longer exists.";

function failure(
  message: string,
  control: FailureControl,
  extra: Partial<SkillFailure> = {}
): SkillFailure {
  return { message, control, showProjectSelector: false, removeSkill: false, ...extra };
}

/** A check that came back 200 with `status: "error"` and `error{type,message}`. */
export function describeCheckError(error: { type: string; message: string }): SkillFailure {
  if (error.type === "bad_skill") return failure(error.message, null);
  if (error.type === "bad_project") {
    return failure(error.message, "check_again", { showProjectSelector: true });
  }
  return failure(error.message, "check_again");
}

/** A failed HTTP response (4xx, 5xx, non-JSON body, or a thrown fetch). */
export function describeFailure(
  kind: "check" | "run",
  res: FailureInput,
  writesInvolved: boolean
): SkillFailure {
  const { status, code } = res;
  if (status === 404 && code === "skill_not_found") {
    return failure(NOT_FOUND, null, { removeSkill: true });
  }
  if (kind === "check") {
    if (status === 422 && !code) return failure("The skill or project is not valid.", null);
    return failure("The check could not be completed. Try again.", "check_again");
  }
  if (status === 409 && code === "skill_changed") {
    return failure("This skill changed after the check. Check it again.", "check_again");
  }
  if (status === 422 && !code) {
    return failure("The run request was not valid. Check it again.", "check_again");
  }
  if (writesInvolved) {
    return failure(
      "The run did not finish. Check the approval cards before retrying.",
      null
    );
  }
  return failure(
    "The run took longer than the limit or failed. Nothing was changed (this skill only reads). Try again.",
    "run_again"
  );
}

/** "JIRA_ROADMAP, PAY, 7 of 20 tool calls, 52 s[, waiting for approval]" */
export function formatRunSummary(info: SkillRunInfo, waitingForApproval: boolean): string {
  const parts = [
    info.name,
    info.project,
    `${info.tool_calls_used} of ${info.tool_call_budget} tool calls`,
    `${Math.round(info.elapsed_seconds)} s`,
  ];
  if (waitingForApproval) parts.push("waiting for approval");
  return parts.join(", ");
}

const SYSTEM_LABELS: Record<string, string> = {
  jira: "Jira",
  servicenow: "ServiceNow",
  github: "GitHub",
  confluence: "Confluence",
};

export function systemLabel(system: string): string {
  return SYSTEM_LABELS[system] ?? system;
}

export function joinWithAnd(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}
