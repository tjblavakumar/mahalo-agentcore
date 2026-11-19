"use client";

import { useEffect, useState } from "react";
import { TYPICAL_RUN_SECONDS } from "@/lib/skills/types";
import { joinWithAnd, systemLabel } from "@/lib/skills/ui";

interface SkillRunStatusProps {
  command: string;
  project: string;
  /** Systems from the check result, for example ["jira", "servicenow"]. */
  systems: string[];
  typicalSeconds?: number | null;
}

/** Honest, coarse progress: what is running and how long it has taken. No step progress. */
export default function SkillRunStatus({
  command,
  project,
  systems,
  typicalSeconds = TYPICAL_RUN_SECONDS,
}: SkillRunStatusProps) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);

  const reading =
    systems.length > 0 ? `Reading ${joinWithAnd(systems.map(systemLabel))}.` : "Working.";
  const hint = typicalSeconds != null ? ` Usually about ${typicalSeconds} s.` : "";

  return (
    <div role="status" className="my-3 text-sm text-gray-600">
      Running {command} for {project}. {reading} {elapsed} s elapsed.{hint}
    </div>
  );
}
