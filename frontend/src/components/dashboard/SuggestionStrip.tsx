"use client";

import { useEffect, useState } from "react";
import { api } from "@/services/api";
import type { Persona } from "@/lib/personas";
import type { ChatResponse } from "@/types";
import type { ChartIdea } from "@/types/idea";
import { buildIdeaPrompt } from "@/lib/ideaPrompt";
import { parseIdeaEnvelope } from "@/lib/ideaEnvelope";

/** Client abort backstop (design §5). Stops the browser wait, not the server turn. */
const IDEA_TIMEOUT_MS = 12000;

type StripStatus = "loading" | "ready" | "empty";

/** Result contract for a click-to-build (design D1): resolves, never rejects. */
export type BuildIdeaResult = { ok: true } | { ok: false; error: string };

interface SuggestionStripProps {
  persona: Persona;
  /** Currently selected seed-project keys (drives idea scope). */
  selectedKeys: string[];
  /** Build an idea into a real widget via the existing viz path. Never rejects. */
  onBuildIdea: (idea: ChartIdea) => Promise<BuildIdeaResult>;
}

/** Stable per-idea key for React lists + build/error tracking. */
function ideaKey(idea: ChartIdea): string {
  return `${idea.title.toLowerCase()}|${idea.chartType}`;
}

/**
 * Ephemeral "Suggested for you" strip. Fetches 3-5 lightweight chart IDEAS on
 * mount (and on persona / selected-keys / refresh change), renders them as
 * compact cards, and builds a real widget on click through the existing viz
 * path. Never persisted, never blocks the dashboard render; any failure collapses
 * quietly to an empty state with a Refresh button (design §5).
 */
export default function SuggestionStrip({
  persona,
  selectedKeys,
  onBuildIdea,
}: SuggestionStripProps) {
  const [status, setStatus] = useState<StripStatus>("loading");
  const [ideas, setIdeas] = useState<ChartIdea[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [buildingKey, setBuildingKey] = useState<string | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [errorText, setErrorText] = useState<string | null>(null);

  // Value-stable dependency: fetch only re-fires when the selected set changes.
  const keysSig = selectedKeys.join(",");

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), IDEA_TIMEOUT_MS);
    let ignore = false;

    void (async () => {
      const result = await api.post<ChatResponse>(
        "/chat",
        {
          message: buildIdeaPrompt(persona, selectedKeys),
          session_id: null,
          project_id: null,
        },
        persona.personaId,
        controller.signal
      );
      if (ignore) return;

      if (!result.data) {
        console.warn("Ideas /chat error:", result.error);
        setIdeas([]);
        setStatus("empty");
        return;
      }

      const parsed = parseIdeaEnvelope(result.data.response ?? "");
      if (parsed.ok) {
        setIdeas(parsed.ideas);
        setStatus("ready");
      } else {
        console.warn("Ideas rejected:", parsed.reason);
        setIdeas([]);
        setStatus("empty");
      }
    })();

    return () => {
      ignore = true;
      clearTimeout(timer);
      controller.abort();
    };
    // keysSig is the value-stable signature of selectedKeys (not the array ref).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [persona.personaId, keysSig, reloadKey]);

  function refresh() {
    setErrorKey(null);
    setErrorText(null);
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }

  function removeIdea(key: string) {
    setIdeas((prev) => {
      const next = prev.filter((i) => ideaKey(i) !== key);
      if (next.length === 0) setStatus("empty");
      return next;
    });
  }

  async function handleAddIdea(idea: ChartIdea) {
    const key = ideaKey(idea);
    setBuildingKey(key);
    setErrorKey(null);
    setErrorText(null);

    const outcome = await onBuildIdea(idea);

    setBuildingKey(null);
    if (outcome.ok) {
      removeIdea(key);
    } else {
      setErrorKey(key);
      setErrorText(outcome.error);
    }
  }

  if (status === "loading") {
    return (
      <div className="rounded-lg bg-white shadow border border-gray-200 p-4">
        <p className="text-sm font-medium text-gray-700 mb-3">Suggested for you</p>
        <div className="flex items-center gap-3 text-gray-500">
          <div className="flex gap-1.5">
            <div className="h-2 w-2 animate-bounce rounded-full bg-gray-400" />
            <div className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:0.1s]" />
            <div className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:0.2s]" />
          </div>
          <span className="text-sm">Finding ideas for you…</span>
        </div>
      </div>
    );
  }

  if (status === "empty") {
    return (
      <div className="text-right">
        <button
          type="button"
          onClick={refresh}
          className="text-xs text-gray-500 hover:text-gray-700 underline underline-offset-2"
        >
          Refresh suggestions
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-lg bg-white shadow border border-gray-200 p-4">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm font-medium text-gray-700">Suggested for you</p>
        <button
          type="button"
          onClick={refresh}
          className="text-xs text-gray-500 hover:text-gray-700 underline underline-offset-2"
        >
          Refresh
        </button>
      </div>

      <div className="flex flex-wrap gap-3">
        {ideas.map((idea) => {
          const key = ideaKey(idea);
          const isBuilding = buildingKey === key;
          const showError = errorKey === key && errorText;
          return (
            <div
              key={key}
              className="w-64 shrink-0 rounded-lg border border-gray-200 p-3"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-sm font-medium text-gray-900">{idea.title}</p>
                <button
                  type="button"
                  onClick={() => removeIdea(key)}
                  aria-label={`Dismiss ${idea.title}`}
                  className="shrink-0 text-gray-400 hover:text-gray-600"
                >
                  ×
                </button>
              </div>

              <div className="mt-1.5">
                <span className="inline-block rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-600">
                  {idea.chartType}
                </span>
              </div>

              <p className="mt-1.5 truncate text-xs text-gray-600" title={idea.description}>
                {idea.description}
              </p>

              {idea.projects.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {idea.projects.map((p) => (
                    <span
                      key={p}
                      className="rounded-full border border-gray-300 px-1.5 py-0.5 text-[10px] text-gray-600"
                    >
                      {p}
                    </span>
                  ))}
                </div>
              )}

              <button
                type="button"
                onClick={() => void handleAddIdea(idea)}
                disabled={isBuilding}
                className="mt-2.5 w-full rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
              >
                {isBuilding ? "Building…" : "Add"}
              </button>

              {showError && (
                <p className="mt-2 text-[11px] text-amber-700">{errorText}</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
