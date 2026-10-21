/**
 * Shared TypeScript types for the MAHALO chat frontend.
 */

export type UserRole = "product_manager" | "developer" | "executive";

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
