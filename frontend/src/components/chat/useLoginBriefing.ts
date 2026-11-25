"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
 *
 * ``open()`` backs the "Quick Brief" button: it fetches a fresh briefing on
 * demand at any time, independent of the once-per-login state (it neither
 * reads nor changes it). On failure it sets ``error`` instead of a card.
 */
export function useLoginBriefing(personaId: PersonaId | undefined, loginId: string | null) {
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const onDemand = useRef<AbortController | null>(null);

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

  // Abort an on-demand fetch if the chat unmounts mid-request.
  useEffect(() => () => onDemand.current?.abort(), []);

  const open = useCallback(async () => {
    if (!personaId) return;
    onDemand.current?.abort();
    const controller = new AbortController();
    onDemand.current = controller;
    setLoading(true);
    setError(null);
    const res = await getBriefing(personaId, controller.signal);
    if (controller.signal.aborted) return;
    setLoading(false);
    if (isBriefing(res.data)) {
      setBriefing(res.data);
    } else {
      setError("The briefing is not available right now. Try again in a moment.");
    }
  }, [personaId]);

  const close = useCallback(() => {
    if (loginId) dismiss(loginId);
    setBriefing(null);
    setError(null);
  }, [loginId]);

  return { briefing, dismiss: close, open, loading, error };
}
