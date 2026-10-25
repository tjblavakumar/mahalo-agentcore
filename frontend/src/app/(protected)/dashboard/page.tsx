"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/services/api";
import { useAuth } from "@/contexts/AuthContext";
import { buildDashboardPrompt } from "@/lib/projects";
import DashboardView from "@/components/dashboard/DashboardView";
import type { ChatResponse } from "@/types";

export default function DashboardPage() {
  const { persona } = useAuth();
  const isPM = persona?.role === "product_manager";
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  // PM defaults to a SINGLE project so the first synthesis is fast. Synthesizing
  // all 5 projects fans out to ~23 agent tool calls and can approach the Lambda
  // timeout; the PM picks more projects and hits Regenerate deliberately. Dev/Exec
  // have no project selector and synthesize their (smaller) role view directly.
  const [selectedKeys, setSelectedKeys] = useState<string[]>(isPM ? ["PAY"] : []);
  // The dashboard owns its own session id, distinct from chat, so synthesis
  // does not pollute chat history. Starts null; the thin API normalizes the
  // returned id to a Runtime-valid value (>=33 chars), which is then reused.
  const [dashboardSessionId, setDashboardSessionId] = useState<string | null>(null);
  const didBuild = useRef(false);

  // persona.role / personaId are stable for a login session; a null persona is
  // only possible transiently before ProtectedRoute blocks render.
  const build = useCallback(async () => {
    if (!persona) return;
    setIsLoading(true);
    setErrorText(null);

    const result = await api.post<ChatResponse>(
      "/chat",
      {
        message: buildDashboardPrompt({
          role: persona.role,
          selectedProjectKeys: selectedKeys,
        }),
        session_id: dashboardSessionId,
        project_id: null,
      },
      persona.personaId
    );

    if (result.data) {
      if (!dashboardSessionId || result.data.session_id !== dashboardSessionId) {
        setDashboardSessionId(result.data.session_id);
      }
      setResult(result.data);
    } else {
      setErrorText(`Couldn't build your dashboard: ${result.error}`);
      console.error("Dashboard build failed:", result.error);
    }

    setIsLoading(false);
  }, [persona, selectedKeys, dashboardSessionId]);

  // Auto-build once on first mount. Set the latch BEFORE the async call so
  // React 19's dev double-invoke of effects skips the duplicate /chat call.
  useEffect(() => {
    if (didBuild.current) return;
    didBuild.current = true;
    void build();
    // Intentionally run once on mount; `build` changes with selection/session
    // but the latch guards re-runs. Regenerate calls `build` directly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleToggle(key: string) {
    setSelectedKeys((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  }

  if (!persona) {
    return null;
  }

  return (
    <DashboardView
      persona={persona}
      result={result}
      isLoading={isLoading}
      error={errorText}
      selectedKeys={selectedKeys}
      onToggle={handleToggle}
      onRegenerate={() => void build()}
    />
  );
}
