/**
 * Static seed project list.
 *
 * The custom dashboard authors charts/tables through the chat box
 * (`buildVizPrompt`), so the old prose "build my dashboard" prompt builder has
 * been removed. `SEED_PROJECTS` is retained as the single source of project
 * keys — used by the PM project-chip authoring aid in `DashboardChatBox`.
 */

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
