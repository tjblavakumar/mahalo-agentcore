"use client";

import { useCallback, useEffect, useState } from "react";
import type { PersonaId } from "@/lib/personas";
import { getBriefing } from "@/services/api";
import {
  dismiss,
  isBriefing,
  markShown,
  readState,
  shouldFetch,
  type Briefing,
} from "@/lib/briefing";

/**
 * Loads the login briefing once per login, after first paint and without
 * blocking anything else. A failed or malformed response shows nothing and
 * writes no state, so the next chat mount may retry (a fetch happens only on
 * mount, so this cannot loop).
 */
export function useLoginBriefing(personaId: PersonaId | undefined, loginId: string | null) {
  const [briefing, setBriefing] = useState<Briefing | null>(null);

  useEffect(() => {
    if (!personaId || !loginId) return;
    if (!shouldFetch(loginId, readState())) return;
    const controller = new AbortController();
    let active = true;
    void getBriefing(personaId, controller.signal).then((res) => {
      if (!active || !isBriefing(res.data)) return;
      markShown(loginId);
      setBriefing(res.data);
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, [personaId, loginId]);

  const close = useCallback(() => {
    if (loginId) dismiss(loginId);
    setBriefing(null);
  }, [loginId]);

  return { briefing, dismiss: close };
}
