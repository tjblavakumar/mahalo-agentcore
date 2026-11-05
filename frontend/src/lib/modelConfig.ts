/**
 * The client-side mirror of the server allow-list in `agent/model_config.py`
 * (and `api/app/models.py`). The thin API's Function URL is AuthType=NONE and
 * the server re-validates every id against this exact list (NFR-6), so this
 * array is a UI convenience only — it must stay in sync with the server ids by
 * hand. The friendly labels are frontend-only (the server stores plain ids).
 */

export interface ModelOption {
  id: string;
  label: string;
}

/** The fixed code-generation model (Sonnet 4.5); the dropdown is read-only. */
export const CODE_GEN_OPTION: ModelOption = {
  id: "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
  label: "Claude Sonnet 4.5",
};

/**
 * The review models the server will accept, with friendly labels. The ids match
 * `REVIEW_ALLOW_LIST` in agent/model_config.py / api/app/models.py exactly; the
 * first entry is the default review model (`DEFAULT_REVIEW_MODEL_ID`).
 */
export const REVIEW_OPTIONS: ModelOption[] = [
  { id: "us.amazon.nova-lite-v1:0", label: "Nova Lite (fast, low-cost)" },
  { id: "us.amazon.nova-micro-v1:0", label: "Nova Micro (fastest, cheapest)" },
  {
    id: "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    label: "Claude Haiku 4.5 (balanced)",
  },
];

/** The review model used when none is selected (mirrors DEFAULT_REVIEW_MODEL_ID). */
export const DEFAULT_REVIEW_OPTION: ModelOption = REVIEW_OPTIONS[0];

/** Return the friendly label for a known model id, or the id itself if unknown. */
export function modelLabel(modelId: string): string {
  if (modelId === CODE_GEN_OPTION.id) {
    return CODE_GEN_OPTION.label;
  }
  const match = REVIEW_OPTIONS.find((o) => o.id === modelId);
  return match ? match.label : modelId;
}
