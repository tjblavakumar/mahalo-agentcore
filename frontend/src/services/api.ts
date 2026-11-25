/**
 * API client for communicating with the MAHALO thin API.
 *
 * The thin-API Lambda Function URL is AuthType=NONE (demo posture, Task 7c): the
 * browser calls it directly with a plain `fetch`, no AWS credentials and no
 * SigV4 signing. The active persona is asserted via the `X-Mahalo-Persona`
 * header, which the thin API maps to {developer_id, role} in `api/app/auth.py`.
 */

import type { PersonaId } from "@/lib/personas";
import type { ChatResponse, ModelConfig } from "@/types";
import type { Briefing } from "@/lib/briefing";
import type {
  SkillCheckResponse,
  SkillDetail,
  SkillPutResponse,
  SkillsListResponse,
} from "@/lib/skills/types";

// Default is the thin-API Lambda Function URL convention
// (https://<id>.lambda-url.<region>.on.aws). Injected at build time via
// NEXT_PUBLIC_API_URL (see .env.example); no live backend is hardcoded.
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://<function-id>.lambda-url.us-east-1.on.aws";

interface ApiResponse<T> {
  data: T | null;
  error: string | null;
  /** HTTP status; undefined when fetch itself threw (network error). */
  status?: number;
  /** `detail.code` of a skills-router error body, when detail is an object. */
  code?: string;
}

function normalizeErrorMessage(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  if (Array.isArray(value)) {
    return value
      .map((item) => normalizeErrorMessage(item))
      .filter(Boolean)
      .join("; ");
  }

  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const candidate = record.msg ?? record.message ?? record.detail;
    if (candidate) {
      return normalizeErrorMessage(candidate);
    }

    try {
      return JSON.stringify(value);
    } catch {
      return "Request failed";
    }
  }

  return "Request failed";
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {},
  personaId?: PersonaId
): Promise<ApiResponse<T>> {
  try {
    const url = `${API_BASE_URL}${endpoint}`;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(personaId ? { "X-Mahalo-Persona": personaId } : {}),
      ...((options.headers as Record<string, string>) || {}),
    };

    const response = await fetch(url, {
      method: options.method,
      headers,
      body: options.body,
      signal: options.signal,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const errorMessage =
        (errorData.detail != null && normalizeErrorMessage(errorData.detail)) ||
        (errorData.message != null && normalizeErrorMessage(errorData.message)) ||
        `Request failed with status ${response.status}`;

      const detail = errorData.detail;
      const code =
        detail && typeof detail === "object" && !Array.isArray(detail) && typeof detail.code === "string"
          ? (detail.code as string)
          : undefined;

      return {
        data: null,
        error: errorMessage,
        status: response.status,
        ...(code ? { code } : {}),
      };
    }

    const data = await response.json();
    return { data, error: null, status: response.status };
  } catch (err) {
    return {
      data: null,
      error: err instanceof Error ? err.message : "An unknown error occurred",
    };
  }
}

export const api = {
  get: <T>(endpoint: string, personaId?: PersonaId, signal?: AbortSignal) =>
    request<T>(endpoint, { method: "GET", signal }, personaId),
  post: <T>(endpoint: string, body: unknown, personaId?: PersonaId, signal?: AbortSignal) =>
    request<T>(endpoint, { method: "POST", body: JSON.stringify(body), signal }, personaId),
  put: <T>(endpoint: string, body: unknown, personaId?: PersonaId) =>
    request<T>(endpoint, { method: "PUT", body: JSON.stringify(body) }, personaId),
  delete: <T>(endpoint: string, personaId?: PersonaId) =>
    request<T>(endpoint, { method: "DELETE" }, personaId),
};

/**
 * Per-persona model-config helpers against the thin API's /model-config router
 * (FEAT-002). The persona is asserted via the X-Mahalo-Persona header; the
 * server derives the persona key and enforces the allow-list, so a GET for a
 * persona with no stored item returns the documented defaults.
 */
export function getModelConfig(personaId?: PersonaId) {
  return api.get<ModelConfig>("/model-config", personaId);
}

export function putModelConfig(config: ModelConfig, personaId?: PersonaId) {
  return api.put<ModelConfig>("/model-config", config, personaId);
}

/**
 * Skills helpers against the thin API's /skills router. Failures carry
 * `status` and `code` (see ApiResponse) so callers key on those, not on text.
 */
export function listSkills(personaId?: PersonaId) {
  return api.get<SkillsListResponse>("/skills", personaId);
}

export function getSkill(name: string, personaId?: PersonaId) {
  return api.get<SkillDetail>(`/skills/${encodeURIComponent(name)}`, personaId);
}

export function putSkill(
  name: string,
  body: { filename: string; content: string; overwrite?: boolean },
  personaId?: PersonaId
) {
  return api.put<SkillPutResponse>(`/skills/${encodeURIComponent(name)}`, body, personaId);
}

export function deleteSkill(name: string, personaId?: PersonaId) {
  return api.delete<{ deleted: string }>(`/skills/${encodeURIComponent(name)}`, personaId);
}

export function checkSkill(
  body: { name: string; project: string | null; session_id?: string | null },
  personaId?: PersonaId
) {
  return api.post<SkillCheckResponse>("/skills/check", body, personaId);
}

export function runSkill(
  body: {
    name: string;
    project: string;
    content_sha256: string;
    consented: true;
    session_id?: string | null;
  },
  personaId?: PersonaId
) {
  return api.post<ChatResponse>("/skills/run", body, personaId);
}

/** The briefing is optional UI: give up after 8 s (2 s after the server's own deadline). */
export const BRIEFING_TIMEOUT_MS = 8000;

/**
 * "Since yesterday" login briefing (read-only `GET /briefing`). Aborts after
 * BRIEFING_TIMEOUT_MS or when the caller's signal aborts; the result then has
 * `data: null`, which callers treat as "show nothing".
 */
export function getBriefing(personaId?: PersonaId, signal?: AbortSignal) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), BRIEFING_TIMEOUT_MS);
  const onAbort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener("abort", onAbort);
  return api.get<Briefing>("/briefing", personaId, controller.signal).finally(() => {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  });
}

export type { ApiResponse };
export { API_BASE_URL };
