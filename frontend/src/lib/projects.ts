/**
 * Static seed project list + the pure dashboard prompt-builder.
 *
 * The agent-driven dashboard reuses the deployed `/chat` endpoint: instead of a
 * widget grid, it sends a persona-tailored "build my dashboard" prompt and
 * renders the synthesized markdown. This module holds the (pure, side-effect
 * free, unit-testable) logic that turns a persona + selected project keys into
 * that prompt string.
 */

import type { UserRole } from "@/types";

export interface SeedProject {
  key: string; // Jira/GitHub/ServiceNow project key
  name: string; // human-readable name
}

/**
 * The five cross-service-aligned seed projects (from tools-lambdas seed data).
 * Confluence spaces are topic-keyed rather than per-project, so they are not
 * mapped here.
 */
export const SEED_PROJECTS: SeedProject[] = [
  { key: "PAY", name: "Payment Gateway" },
  { key: "CART", name: "Shopping Cart" },
  { key: "AUTH", name: "User Authentication" },
  { key: "PROD", name: "Product Catalog" },
  { key: "ORD", name: "Order Management" },
];

export interface DashboardPromptInput {
  role: UserRole; // product_manager | developer | executive
  selectedProjectKeys?: string[]; // only consulted for product_manager
}

const PM_ALL_PROJECTS_PROMPT =
  "You are my product delivery assistant. Build a Product Manager dashboard across all of my " +
  "projects. Working across Jira, Confluence, GitHub and ServiceNow, summarize overall sprint " +
  "status and progress, the top open blockers and risks, team velocity, notable recent " +
  "documentation changes, and any production incidents. Use clear Markdown with section headings " +
  "and concise bullet points. Start with a one-paragraph delivery summary.";

const DEVELOPER_PROMPT =
  "You are my engineering assistant. Build a Developer dashboard for me. Working across Jira, " +
  "GitHub and ServiceNow, summarize my assigned issues and their status, my open pull requests " +
  "and review requests, recent commits and the latest release, and any production incidents or " +
  "failed deployments that affect my work. Use clear Markdown with section headings and concise " +
  "bullet points. Start with a one-paragraph summary of what needs my attention today.";

const EXECUTIVE_PROMPT =
  "You are my executive assistant. Build an Executive portfolio dashboard. Working across Jira, " +
  "Confluence, GitHub and ServiceNow, give a portfolio health roll-up across all projects: " +
  "overall delivery status and momentum, top risks and blockers, notable incidents, and delivery " +
  "trends this quarter. Use clear Markdown with section headings and concise bullet points. Start " +
  "with a one-paragraph portfolio health summary.";

/**
 * Resolves selected keys to `Name (KEY)` clauses: de-duplicated preserving
 * order, known keys use their seed name, unknown keys pass through as a bare
 * uppercased `KEY` (so a future "type a key" affordance still works).
 */
function resolveProjectClause(selectedProjectKeys: string[]): string {
  const byKey = new Map(SEED_PROJECTS.map((p) => [p.key, p.name]));
  const seen = new Set<string>();
  const parts: string[] = [];

  for (const raw of selectedProjectKeys) {
    const key = raw.trim().toUpperCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const name = byKey.get(key);
    parts.push(name ? `${name} (${key})` : key);
  }

  return parts.join(", ");
}

/** Pure: (role [, selected PM project keys]) -> the "build my dashboard" prompt. */
export function buildDashboardPrompt(input: DashboardPromptInput): string {
  if (input.role === "developer") {
    return DEVELOPER_PROMPT;
  }

  if (input.role === "executive") {
    return EXECUTIVE_PROMPT;
  }

  // product_manager
  const clause = resolveProjectClause(input.selectedProjectKeys ?? []);
  if (!clause) {
    return PM_ALL_PROJECTS_PROMPT;
  }

  return (
    `You are my product delivery assistant. Build a Product Manager dashboard for projects ` +
    `${clause}. Working across Jira, Confluence, GitHub and ServiceNow, summarize for each ` +
    `project: current sprint status and progress, open blockers and risks, team velocity, ` +
    `notable recent documentation changes, and any production incidents. Use clear Markdown with ` +
    `a short section heading per project and concise bullet points. Start with a one-paragraph ` +
    `executive summary across the selected projects.`
  );
}
