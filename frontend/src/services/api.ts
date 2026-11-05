/**
 * API client for communicating with the MAHALO thin API.
 *
 * The thin-API Lambda Function URL is AuthType=NONE (demo posture, Task 7c): the
 * browser calls it directly with a plain `fetch`, no AWS credentials and no
 * SigV4 signing. The active persona is asserted via the `X-Mahalo-Persona`
 * header, which the thin API maps to {developer_id, role} in `api/app/auth.py`.
 */

import type { PersonaId } from "@/lib/personas";
import type { ModelConfig } from "@/types";

// Default is the thin-API Lambda Function URL convention
// (https://<id>.lambda-url.<region>.on.aws). Injected at build time via
// NEXT_PUBLIC_API_URL (see .env.example); no live backend is hardcoded.
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  "https://<function-id>.lambda-url.us-east-1.on.aws";

interface ApiResponse<T> {
  data: T | null;
  error: string | null;
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
        normalizeErrorMessage(errorData.detail) ||
        normalizeErrorMessage(errorData.message) ||
        `Request failed with status ${response.status}`;

      return {
        data: null,
        error: errorMessage,
      };
    }

    const data = await response.json();
    return { data, error: null };
  } catch (err) {
    return {
      data: null,
      error: err instanceof Error ? err.message : "An unknown error occurred",
    };
  }
}

export const api = {
  get: <T>(endpoint: string, personaId?: PersonaId) =>
    request<T>(endpoint, { method: "GET" }, personaId),
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

export type { ApiResponse };
export { API_BASE_URL };
