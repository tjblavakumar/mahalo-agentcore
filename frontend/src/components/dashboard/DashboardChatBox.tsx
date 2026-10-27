"use client";

import { useState } from "react";
import { api } from "@/services/api";
import type { Persona } from "@/lib/personas";
import type { ChatResponse } from "@/types";
import type { VizSpec } from "@/types/viz";
import { parseVizEnvelope } from "@/lib/vizEnvelope";
import { buildVizPrompt } from "@/lib/vizPrompt";
import { SEED_PROJECTS } from "@/lib/projects";
import VizWidget from "@/components/dashboard/charts/VizWidget";

/** Fixed Q5 message shown for any unrenderable reply or /chat error (design §5.1). */
const Q5_MESSAGE =
  "I can only build charts and tables here. I couldn't turn that into a line, area, or bar " +
  "chart or a table. For general or text answers, use the Chat screen. Try asking for a metric " +
  "over a dimension, e.g. 'story points by sprint for PAY' or 'open PRs by project'.";

interface DashboardChatBoxProps {
  persona: Persona;
  /** Dashboard-local session id (reused across sends; updated via onSessionId). */
  sessionId: string | null;
  onSessionId: (id: string) => void;
  /** Add a validated spec to the dashboard (append + immediate save). */
  onAdd: (spec: VizSpec) => void;
}

/**
 * Chat box that authors dashboard widgets. It sends a strict-viz prompt to
 * `/chat`, validates the reply, and either shows a live preview with an
 * "Add to dashboard" button or the fixed Q5 message. Never renders prose.
 */
export default function DashboardChatBox({
  persona,
  sessionId,
  onSessionId,
  onAdd,
}: DashboardChatBoxProps) {
  const [text, setText] = useState("");
  // Default to every seed project selected, for every persona (design: all five
  // projects — PAY, CART, AUTH, PROD, ORD — scoped in on first load).
  const [selectedKeys, setSelectedKeys] = useState<string[]>(() =>
    SEED_PROJECTS.map((p) => p.key)
  );
  const [isSending, setIsSending] = useState(false);
  const [preview, setPreview] = useState<VizSpec | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  function toggleKey(key: string) {
    setSelectedKeys((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  }

  async function handleSend() {
    const request = text.trim();
    if (!request || isSending) return;

    setIsSending(true);
    setPreview(null);
    setMessage(null);

    const result = await api.post<ChatResponse>(
      "/chat",
      {
        message: buildVizPrompt(request, persona, selectedKeys),
        session_id: sessionId,
        project_id: null,
      },
      persona.personaId
    );

    if (!result.data) {
      console.warn("Dashboard /chat error:", result.error);
      setMessage(Q5_MESSAGE);
      setIsSending(false);
      return;
    }

    if (!sessionId || result.data.session_id !== sessionId) {
      onSessionId(result.data.session_id);
    }

    const parsed = parseVizEnvelope(result.data.response ?? "");
    if (parsed.ok) {
      setPreview(parsed.spec);
    } else {
      console.warn("Dashboard viz rejected:", parsed.reason);
      setMessage(Q5_MESSAGE);
    }

    setIsSending(false);
  }

  function handleAdd() {
    if (!preview) return;
    onAdd(preview);
    setPreview(null);
    setText("");
  }

  return (
    <div className="rounded-lg bg-white shadow border border-gray-200 p-4">
      <div className="mb-3">
        <p className="text-xs font-medium text-gray-600 mb-1.5">Scope to projects (optional)</p>
        <div className="flex flex-wrap gap-1.5">
          {SEED_PROJECTS.map((project) => {
            const isSelected = selectedKeys.includes(project.key);
            return (
              <button
                key={project.key}
                type="button"
                onClick={() => toggleKey(project.key)}
                aria-pressed={isSelected}
                className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                  isSelected
                    ? "bg-blue-600 border-blue-600 text-white"
                    : "bg-white border-gray-300 text-gray-700 hover:border-gray-400"
                }`}
              >
                {project.key}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex items-start gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSend();
            }
          }}
          rows={2}
          placeholder="Describe a chart or table to add… (e.g. 'story points by sprint for PAY')"
          className="flex-1 resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <button
          type="button"
          onClick={() => void handleSend()}
          disabled={isSending || text.trim().length === 0}
          className="shrink-0 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
        >
          {isSending ? "Generating…" : "Generate"}
        </button>
      </div>

      <p className="mt-2 text-xs text-gray-500">
        This box only creates charts and tables. Saved charts stay on your dashboard every time
        you log in. For text answers, use Chat.
      </p>

      {message && (
        <div className="mt-3 rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">
          {message}
        </div>
      )}

      {preview && (
        <div className="mt-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-medium text-gray-700">Preview: {preview.title}</p>
            <button
              type="button"
              onClick={handleAdd}
              className="rounded-lg bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 transition-colors"
            >
              Add to dashboard
            </button>
          </div>
          <div className="h-64 rounded-lg border border-gray-200 p-2">
            <VizWidget spec={preview} />
          </div>
        </div>
      )}
    </div>
  );
}
