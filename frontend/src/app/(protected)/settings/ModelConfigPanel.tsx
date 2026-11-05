"use client";

import { useEffect, useState } from "react";
import type { PersonaId } from "@/lib/personas";
import type { ModelConfig } from "@/types";
import { getModelConfig, putModelConfig } from "@/services/api";
import {
  CODE_GEN_OPTION,
  REVIEW_OPTIONS,
  DEFAULT_REVIEW_OPTION,
} from "@/lib/modelConfig";

/**
 * Per-persona model-selection card. Code generation is fixed to Sonnet 4.5 (the
 * select is disabled/read-only); Code review is user-selectable from the review
 * allow-list; Security is shown but marked "not yet active" (a future slice).
 * All options come from the client mirror of the server allow-list, which the
 * server re-validates on PUT (NFR-6).
 *
 * This is a client component: it loads via getModelConfig on mount and saves via
 * putModelConfig, both scoped to the active persona.
 */

interface ModelConfigPanelProps {
  personaId?: PersonaId;
}

const DEFAULT_CONFIG: ModelConfig = {
  codeGeneration: CODE_GEN_OPTION.id,
  codeReview: DEFAULT_REVIEW_OPTION.id,
  security: DEFAULT_REVIEW_OPTION.id,
};

export default function ModelConfigPanel({ personaId }: ModelConfigPanelProps) {
  const [config, setConfig] = useState<ModelConfig>(DEFAULT_CONFIG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getModelConfig(personaId).then((res) => {
      if (!active) return;
      setMessage(null);
      setError(null);
      if (res.data) {
        setConfig({
          // Code generation is always the fixed id regardless of what is stored.
          codeGeneration: CODE_GEN_OPTION.id,
          codeReview: res.data.codeReview ?? DEFAULT_REVIEW_OPTION.id,
          security: res.data.security ?? DEFAULT_REVIEW_OPTION.id,
        });
      } else if (res.error) {
        setError(res.error);
      }
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [personaId]);

  async function save() {
    setSaving(true);
    setMessage(null);
    setError(null);
    const res = await putModelConfig(
      { ...config, codeGeneration: CODE_GEN_OPTION.id },
      personaId,
    );
    setSaving(false);
    if (res.error || !res.data) {
      setError(res.error ?? "Save failed");
      return;
    }
    setMessage("Model configuration saved.");
  }

  return (
    <div className="mt-6 max-w-2xl rounded-lg bg-white p-6 shadow">
      <h2 className="text-lg font-semibold text-gray-900">Models per activity</h2>
      <p className="mt-2 text-sm text-gray-600">
        Choose which model vets your generated code. Settings are saved per persona.
      </p>

      <div className="mt-4 space-y-4">
        {/* Code generation: fixed, read-only. */}
        <div>
          <label
            htmlFor="model-code-generation"
            className="block text-sm font-medium text-gray-700"
          >
            Code generation
          </label>
          <select
            id="model-code-generation"
            value={config.codeGeneration}
            disabled
            aria-disabled="true"
            className="mt-1 block w-full rounded-md border border-gray-300 bg-gray-100 px-3 py-2 text-sm text-gray-600 disabled:cursor-not-allowed"
          >
            <option value={CODE_GEN_OPTION.id}>{CODE_GEN_OPTION.label}</option>
          </select>
          <p className="mt-1 text-xs text-gray-500">Fixed for this demo.</p>
        </div>

        {/* Code review: selectable from the allow-list. */}
        <div>
          <label
            htmlFor="model-code-review"
            className="block text-sm font-medium text-gray-700"
          >
            Code review
          </label>
          <select
            id="model-code-review"
            value={config.codeReview}
            disabled={loading}
            onChange={(e) =>
              setConfig((prev) => ({ ...prev, codeReview: e.target.value }))
            }
            className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 disabled:opacity-50"
          >
            {REVIEW_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        {/* Security: shown but not yet active. */}
        <div>
          <label
            htmlFor="model-security"
            className="block text-sm font-medium text-gray-700"
          >
            Security review{" "}
            <span className="ml-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
              not yet active
            </span>
          </label>
          <select
            id="model-security"
            value={config.security}
            disabled
            aria-disabled="true"
            className="mt-1 block w-full rounded-md border border-gray-300 bg-gray-100 px-3 py-2 text-sm text-gray-600 disabled:cursor-not-allowed"
          >
            {REVIEW_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <button
        type="button"
        onClick={save}
        disabled={loading || saving}
        className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {saving ? "Saving…" : "Save models"}
      </button>

      <div aria-live="polite">
        {error && (
          <p role="alert" className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">
            {error}
          </p>
        )}
        {message && (
          <p className="mt-4 rounded bg-green-50 p-3 text-sm text-green-700">{message}</p>
        )}
      </div>
    </div>
  );
}
