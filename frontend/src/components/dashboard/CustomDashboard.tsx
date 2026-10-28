"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Layout } from "react-grid-layout";
import { api } from "@/services/api";
import type { Persona } from "@/lib/personas";
import type { SavedWidget, VizSpec } from "@/types/viz";
import type { ChartIdea } from "@/types/idea";
import type { ChatResponse } from "@/types";
import {
  appendWidget,
  removeWidget,
  applyLayoutChange,
  isLgLayoutUnchanged,
} from "@/lib/dashboardWidgets";
import { SEED_PROJECTS } from "@/lib/projects";
import { buildVizPrompt } from "@/lib/vizPrompt";
import { parseVizEnvelope } from "@/lib/vizEnvelope";
import { buildIdeaRequestText } from "@/lib/ideaRequest";
import { Q5_MESSAGE } from "@/lib/q5Message";
import DashboardGrid from "@/components/dashboard/DashboardGrid";
import DashboardChatBox from "@/components/dashboard/DashboardChatBox";
import SuggestionStrip, {
  type BuildIdeaResult,
} from "@/components/dashboard/SuggestionStrip";

interface WidgetsResponse {
  widgets: SavedWidget[];
}

type SaveState = "idle" | "saving" | "saved";

interface CustomDashboardProps {
  persona: Persona;
}

const AUTOSAVE_DEBOUNCE_MS = 500;

/**
 * Top-level dashboard: loads saved widgets from GET /dashboard/widgets on mount,
 * owns widget state, and persists changes via PUT (debounced for move/resize,
 * immediate for add/delete) per design §4/§7.
 */
export default function CustomDashboard({ persona }: CustomDashboardProps) {
  const [widgets, setWidgets] = useState<SavedWidget[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveFailed, setSaveFailed] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  // Lifted here (from DashboardChatBox) so the chat box and the suggestion strip
  // agree on the same project scope (design §11). Defaults to all five seeds.
  const [selectedKeys, setSelectedKeys] = useState<string[]>(() =>
    SEED_PROJECTS.map((p) => p.key)
  );

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const didLoad = useRef(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    const result = await api.get<WidgetsResponse>("/dashboard/widgets", persona.personaId);
    if (result.data) {
      setWidgets(result.data.widgets ?? []);
    } else {
      setLoadError(result.error ?? "Couldn't load your dashboard.");
    }
    setIsLoading(false);
  }, [persona.personaId]);

  useEffect(() => {
    if (didLoad.current) return;
    didLoad.current = true;
    void load();
  }, [load]);

  const persist = useCallback(
    async (next: SavedWidget[]) => {
      setSaveState("saving");
      setSaveFailed(false);
      const result = await api.put<WidgetsResponse>(
        "/dashboard/widgets",
        { widgets: next },
        persona.personaId
      );
      if (result.data) {
        setSaveState("saved");
      } else {
        setSaveFailed(true);
        setSaveState("idle");
        console.warn("Dashboard save failed:", result.error);
      }
    },
    [persona.personaId]
  );

  const handleAdd = useCallback(
    (spec: VizSpec) => {
      setWidgets((prev) => {
        const next = appendWidget(prev, spec);
        void persist(next);
        return next;
      });
    },
    [persist]
  );

  // Single click-to-build routine shared by the suggestion strip (design §6/D1).
  // Reuses the EXISTING viz path (buildVizPrompt -> /chat -> parseVizEnvelope ->
  // handleAdd); introduces no second envelope/validator/persistence path.
  // Resolves a result object and never rejects.
  const onBuildIdea = useCallback(
    async (idea: ChartIdea): Promise<BuildIdeaResult> => {
      // One scope used for BOTH the prose request and the structured viz arg.
      const effectiveKeys = idea.projects.length > 0 ? idea.projects : selectedKeys;
      const request = buildIdeaRequestText(idea, effectiveKeys);
      const message = buildVizPrompt(request, persona, effectiveKeys);

      const result = await api.post<ChatResponse>(
        "/chat",
        { message, session_id: sessionId, project_id: null },
        persona.personaId
      );

      if (!result.data) {
        console.warn("Idea build /chat error:", result.error);
        return { ok: false, error: Q5_MESSAGE };
      }

      if (!sessionId || result.data.session_id !== sessionId) {
        setSessionId(result.data.session_id);
      }

      const parsed = parseVizEnvelope(result.data.response ?? "");
      if (!parsed.ok) {
        console.warn("Idea build viz rejected:", parsed.reason);
        return { ok: false, error: Q5_MESSAGE };
      }

      handleAdd(parsed.spec);
      return { ok: true };
    },
    [persona, selectedKeys, sessionId, handleAdd]
  );

  const handleDelete = useCallback(
    (id: string) => {
      setWidgets((prev) => {
        const next = removeWidget(prev, id);
        void persist(next);
        return next;
      });
    },
    [persist]
  );

  const handleLgLayoutChange = useCallback(
    (lgLayout: Layout[]) => {
      setWidgets((prev) => {
        // Skip spurious saves when the merged lg coords are unchanged (§14 item 2).
        if (isLgLayoutUnchanged(prev, lgLayout)) return prev;
        const next = applyLayoutChange(prev, lgLayout);
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => void persist(next), AUTOSAVE_DEBOUNCE_MS);
        return next;
      });
    },
    [persist]
  );

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  return (
    <div className="p-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
          <p className="mt-1 text-gray-600">
            {persona.personaLabel} view. Build and arrange your own charts and tables.
          </p>
        </div>
        <div className="shrink-0 text-sm text-gray-500" aria-live="polite">
          {saveFailed ? (
            <span className="text-red-600">Save failed — will retry on next change</span>
          ) : saveState === "saving" ? (
            "Saving…"
          ) : saveState === "saved" ? (
            "Saved"
          ) : null}
        </div>
      </div>

      <div className="mt-6">
        <DashboardChatBox
          persona={persona}
          sessionId={sessionId}
          onSessionId={setSessionId}
          onAdd={handleAdd}
          selectedKeys={selectedKeys}
          onSelectedKeysChange={setSelectedKeys}
        />
      </div>

      <div className="mt-6">
        <SuggestionStrip
          persona={persona}
          selectedKeys={selectedKeys}
          onBuildIdea={onBuildIdea}
        />
      </div>

      <div className="mt-6">
        {loadError ? (
          <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-sm text-red-700">
            <p>{loadError}</p>
            <button
              type="button"
              onClick={() => void load()}
              className="mt-2 rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 transition-colors"
            >
              Retry
            </button>
          </div>
        ) : isLoading ? (
          <div className="flex items-center gap-3 text-gray-500">
            <div className="flex gap-1.5">
              <div className="h-2 w-2 animate-bounce rounded-full bg-gray-400" />
              <div className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:0.1s]" />
              <div className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:0.2s]" />
            </div>
            <span className="text-sm">Loading your dashboard…</span>
          </div>
        ) : widgets.length === 0 ? (
          <div className="rounded-lg bg-white shadow border border-gray-200 p-8 text-center text-sm text-gray-500">
            No charts yet. Describe one in the box above to get started.
          </div>
        ) : (
          <DashboardGrid
            widgets={widgets}
            onLgLayoutChange={handleLgLayoutChange}
            onDeleteWidget={handleDelete}
          />
        )}
      </div>
    </div>
  );
}
