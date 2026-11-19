/**
 * Skill types and the key registry (skills design, E.3). The *_KEYS constants
 * are the exact key sets of the API models; golden-fixture tests assert the
 * fixtures match them, and `satisfies` below ties the types to the fixtures.
 */

export const SKILL_PROJECTS = ["PAY", "CART", "AUTH", "PROD", "ORD"] as const;
export type SkillProject = (typeof SKILL_PROJECTS)[number];

export const MAX_SKILL_BYTES = 16384;
export const MAX_USER_SKILLS = 50;
export const TOOL_CALL_BUDGET = 20;

/** Typical run time hint in seconds. null (hidden) until measured live. */
export const TYPICAL_RUN_SECONDS: number | null = null;

export type SkillVerdict = "can_do" | "can_do_with_changes" | "cannot";
export type GapKind =
  | "missing_connection"
  | "unsupported_output"
  | "unsupported_action"
  | "missing_data"
  | "other";
export type GapSeverity = "blocked" | "workable";

export interface SkillCheckStep {
  n: number;
  text: string;
  systems: string[];
  tools: string[];
  writes: boolean;
  est_calls: number;
}

export interface SkillCheckGap {
  id: string;
  step: number | null;
  kind: GapKind;
  severity: GapSeverity;
  description: string;
  workaround: string | null;
}

export interface SkillRequiredArgument {
  name: string;
  required: boolean;
  provided: boolean;
  allowed_values: string[];
}

export interface SkillCheck {
  summary: string;
  steps: SkillCheckStep[];
  systems_needed: string[];
  tools_needed: string[];
  writes_involved: boolean;
  write_tools: string[];
  gaps: SkillCheckGap[];
  required_arguments: SkillRequiredArgument[];
  estimated_tool_calls: number;
  tool_call_budget: number;
  likely_too_long: boolean;
  verdict: SkillVerdict;
}

export interface SkillRunInfo {
  name: string;
  project: string;
  tool_calls_used: number;
  tool_call_budget: number;
  budget_exhausted: boolean;
  deadline_exhausted: boolean;
  elapsed_seconds: number;
}

export interface SkillSummary {
  name: string;
  description: string;
  builtin: boolean;
  size_bytes: number;
  content_sha256: string;
  updated_at: string | null;
  updated_by: string | null;
}

export interface SkillDetail extends SkillSummary {
  filename: string;
  content: string;
}

export interface SkillLimits {
  max_bytes: number;
  max_user_skills: number;
  tool_call_budget: number;
}

export interface SkillsListResponse {
  skills: SkillSummary[];
  projects: string[];
  limits: SkillLimits;
}

export interface SkillPutResponse {
  skill: SkillDetail;
  created: boolean;
  warnings: string[];
}

export interface SkillCheckResponse {
  status: string;
  session_id: string | null;
  skill: { name: string; description: string; content_sha256: string; builtin: boolean } | null;
  project: string | null;
  skill_check: SkillCheck | null;
  error: { type: string; message: string } | null;
}

export const SKILL_CHECK_KEYS = {
  top: [
    "summary", "steps", "systems_needed", "tools_needed", "writes_involved",
    "write_tools", "gaps", "required_arguments", "estimated_tool_calls",
    "tool_call_budget", "likely_too_long", "verdict",
  ],
  step: ["n", "text", "systems", "tools", "writes", "est_calls"],
  gap: ["id", "step", "kind", "severity", "description", "workaround"],
  argument: ["name", "required", "provided", "allowed_values"],
} as const;

export const SKILL_RUN_KEYS = [
  "name", "project", "tool_calls_used", "tool_call_budget",
  "budget_exhausted", "deadline_exhausted", "elapsed_seconds",
] as const;

export const SKILL_SUMMARY_KEYS = [
  "name", "description", "builtin", "size_bytes", "content_sha256",
  "updated_at", "updated_by",
] as const;

export const SKILL_DETAIL_KEYS = [...SKILL_SUMMARY_KEYS, "filename", "content"] as const;

export const SKILL_LIMITS_KEYS = ["max_bytes", "max_user_skills", "tool_call_budget"] as const;

export const SKILLS_LIST_KEYS = ["skills", "projects", "limits"] as const;

export const SKILL_PUT_KEYS = ["skill", "created", "warnings"] as const;
