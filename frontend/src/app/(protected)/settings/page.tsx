"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/services/api";

interface SystemResult {
  ok: boolean;
  counts?: Record<string, number>;
  shift_days?: number | null;
  error?: string;
}

interface RefreshResponse {
  results: Record<string, SystemResult>;
  refreshed_at: string;
}

const SYSTEM_LABEL: Record<string, string> = {
  jira: "Jira",
  confluence: "Confluence",
  servicenow: "ServiceNow",
};

export default function SettingsPage() {
  const { persona } = useAuth();
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RefreshResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);

  // Dialog: focus Cancel on open, Esc closes.
  useEffect(() => {
    if (!confirming) return;
    cancelRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setConfirming(false);
    }
    document.addEventListener("keydown", onKey);
    const opener = openerRef.current;
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, [confirming]);

  async function refresh() {
    setConfirming(false);
    setRunning(true);
    setMessage(null);
    setResult(null);
    const res = await api.post<RefreshResponse>("/admin/refresh-demo-data", {}, persona?.personaId);
    setRunning(false);
    if (res.error || !res.data) {
      setMessage(res.error ?? "Refresh failed");
      return;
    }
    setResult(res.data);
  }

  return (
    <div className="p-8">
      <h1 className="text-3xl font-bold text-gray-900">Settings</h1>
      <p className="mt-1 text-gray-600">Demo data controls.</p>

      <div className="mt-6 max-w-2xl rounded-lg bg-white p-6 shadow">
        <h2 className="text-lg font-semibold text-gray-900">Refresh demo data</h2>
        <p className="mt-2 text-sm text-gray-600">
          Resets the Jira, Confluence and ServiceNow demo data to a fresh seed, with dates moved to
          today so the demo never looks stale. Stories and incidents created by the agent are removed.
          Saved dashboards and Gitea are not touched.
        </p>
        <button
          ref={openerRef}
          type="button"
          onClick={() => setConfirming(true)}
          disabled={running}
          className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {running ? "Refreshing…" : "Refresh demo data"}
        </button>

        <div aria-live="polite">
          {message && (
            <p role="alert" className="mt-4 rounded bg-red-50 p-3 text-sm text-red-700">
              {message}
            </p>
          )}
          {result && (
            <div className="mt-4">
              <ul className="space-y-2">
                {Object.entries(result.results).map(([system, r]) => (
                  <li key={system} className="rounded border border-gray-200 p-3 text-sm">
                    <span className="font-medium text-gray-900">
                      {r.ok ? "✅" : "❌"} {SYSTEM_LABEL[system] ?? system}
                    </span>
                    {r.ok ? (
                      <span className="ml-2 text-gray-600">
                        {Object.entries(r.counts ?? {})
                          .map(([k, n]) => `${n} ${k.toLowerCase()}`)
                          .join(", ")}
                      </span>
                    ) : (
                      <span className="ml-2 text-red-700">{r.error ?? "failed"}</span>
                    )}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-gray-500">
                Refreshed at {new Date(result.refreshed_at).toLocaleTimeString()}. Start a new chat now.
              </p>
            </div>
          )}
        </div>
      </div>

      {confirming && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="refresh-title"
            className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
          >
            <h2 id="refresh-title" className="text-lg font-semibold text-gray-900">
              Refresh demo data?
            </h2>
            <p className="mt-2 text-sm text-gray-700">
              This resets Jira, Confluence and ServiceNow to a fresh seed with dates moved to today. It
              DELETES any stories and incidents created by the agent. Start a NEW chat afterwards, since
              the old chat may mention removed items.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                ref={cancelRef}
                type="button"
                onClick={() => setConfirming(false)}
                className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={refresh}
                className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700"
              >
                Refresh now
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
