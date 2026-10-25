/**
 * Shared TypeScript types for the MAHALO chat frontend.
 */

export type UserRole = "product_manager" | "developer" | "executive";

/**
 * The shared `/chat` wire types, used by both the chat page and the agent-driven
 * dashboard so there is a single definition (no silent drift between pages).
 */
export interface Proposal {
  action: string;
  system: string;
  params: Record<string, unknown>;
  description: string;
  interrupt_id?: string;
}

export interface ChatResponse {
  response: string;
  proposal: Proposal | null;
  /**
   * OPTIONAL: matches the chat page's shape. The deployed thin API does not
   * project this field today (its ChatResponse model strips extras), so it is
   * always undefined at runtime. Kept optional only so the shared type is one
   * definition; the dashboard does not render it.
   */
  systems_queried?: string[];
  status: string;
  session_id: string;
}

export interface Project {
  id: number;
  user_id: number;
  name: string;
  description: string;
  goal: string;
  project_type: "development" | "maintenance" | "experiment" | "research" | "other";
  status: string;
  jira_project_key: string | null;
  confluence_space_key: string | null;
  github_repo_name: string | null;
  servicenow_service_name: string | null;
  generate_mock_data: boolean;
  is_active: boolean;
  is_selected: boolean;
  created_at: string;
}
