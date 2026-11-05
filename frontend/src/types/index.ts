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

/**
 * One stage of the deterministic generate -> review pipeline, projected from the
 * Runtime reply (FEAT-001/FEAT-002). All fields are additive-optional so an old
 * client that ignores them keeps working, and `fallback` may serialize as
 * `null` (its server-side optional default) — treat it as optional.
 */
export interface Stage {
  stage: string;
  model_id: string;
  model_label: string;
  status: string;
  fallback?: boolean | null;
}

/** The who-reviewed-what summary projected onto the assistant message. */
export interface ReviewSummary {
  model_id: string;
  model_label: string;
  findings: string;
  status: string;
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
  /**
   * OPTIONAL additive fields from the multi-LLM pipeline (FEAT-002). `stages`
   * is the authoritative generate/review sequence; `review` is the review
   * sub-agent summary. Both are absent on a no-code turn and on old clients.
   */
  stages?: Stage[];
  review?: ReviewSummary;
}

/**
 * The per-persona model selection stored by the thin API's /model-config
 * endpoints (FEAT-002). `codeGeneration` is fixed to the code-gen id;
 * `codeReview` and `security` are constrained server-side to the review
 * allow-list (the server is the trust boundary, NFR-6).
 */
export interface ModelConfig {
  codeGeneration: string;
  codeReview: string;
  security: string;
}

/** Reply of POST /chat/approve. A chained write comes back as pending_approval. */
export interface ActionResult {
  success: boolean;
  message: string;
  session_id?: string;
  status?: string;
  proposal?: Proposal | null;
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
