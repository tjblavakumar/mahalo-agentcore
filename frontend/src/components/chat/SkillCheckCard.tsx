"use client";

import { useState } from "react";
import type { SkillCheck, SkillVerdict } from "@/lib/skills/types";
import { SKILL_PROJECTS } from "@/lib/skills/types";
import type { SkillFailure } from "@/lib/skills/ui";

export type SkillCardState = "ready" | "accepted" | "cancelled" | "error";

interface SkillCheckCardProps {
  command: string;
  project: string | null;
  check: SkillCheck | null;
  state: SkillCardState;
  failure?: SkillFailure;
  /** Full skill text for "View skill"; null until loaded. */
  skillContent?: string | null;
  onViewSkill?: () => void;
  onRun: (project: string) => void;
  onCancel: () => void;
  onCheckAgain: (project: string | null) => void;
  onRunAgain: (project: string) => void;
}

const VERDICT_LABEL: Record<SkillVerdict, string> = {
  can_do: "Can do",
  can_do_with_changes: "Can do with changes",
  cannot: "Cannot do",
};

export default function SkillCheckCard({
  command,
  project,
  check,
  state,
  failure,
  skillContent,
  onViewSkill,
  onRun,
  onCancel,
  onCheckAgain,
  onRunAgain,
}: SkillCheckCardProps) {
  const [chosen, setChosen] = useState<string>(project ?? "");
  const projectArg = check?.required_arguments.find((a) => a.name === "project");
  const needsProject = Boolean(projectArg && !projectArg.provided) || failure?.showProjectSelector;
  const effectiveProject = project ?? (chosen || null);
  const allowed =
    projectArg && projectArg.allowed_values.length > 0
      ? projectArg.allowed_values
      : [...SKILL_PROJECTS];
  const verdict = check?.verdict;
  const runLabel = verdict === "can_do_with_changes" ? "Run with the changes above" : "Run";
  const runDisabled = verdict === "cannot" || (needsProject && !effectiveProject);

  return (
    <section
      role="region"
      aria-label="Skill plan"
      className="my-3 max-w-3xl rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-800"
    >
      <header className="flex flex-wrap items-center gap-2">
        <span className="font-mono font-semibold">/{command}</span>
        {effectiveProject && <span className="text-gray-500">{effectiveProject}</span>}
        {verdict && (
          <span className="rounded border border-gray-300 bg-gray-50 px-2 py-0.5 text-xs font-medium">
            {VERDICT_LABEL[verdict]}
          </span>
        )}
      </header>
      {/* announces the verdict politely when the card appears */}
      <div role="status" aria-live="polite" className="sr-only">
        {verdict ? `Skill check result: ${VERDICT_LABEL[verdict]}` : ""}
      </div>

      {check && (
        <>
          <p className="mt-2">{check.summary}</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5">
            {check.steps.map((s) => (
              <li key={s.n}>
                {s.text}
                {s.tools.length > 0 && (
                  <span className="text-gray-500"> ({s.tools.join(", ")})</span>
                )}
              </li>
            ))}
          </ol>
          <p className="mt-2 text-gray-600">
            Needs: {check.systems_needed.join(", ") || "no systems"}
            {check.tools_needed.length > 0 && ` (${check.tools_needed.join(", ")})`}
          </p>

          {check.writes_involved && (
            <p className="mt-2 rounded border border-amber-300 bg-amber-50 p-2">
              This skill may propose changes ({check.write_tools.join(", ")}). Each change will
              still ask for its own approval. Approving this plan does not approve any change.
            </p>
          )}

          {check.gaps.length > 0 && (
            <table className="mt-2 w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-gray-200 text-xs text-gray-500">
                  <th className="py-1 pr-2">Severity</th>
                  <th className="py-1 pr-2">What</th>
                  <th className="py-1">Workaround</th>
                </tr>
              </thead>
              <tbody>
                {check.gaps.map((g) => (
                  <tr key={g.id} className="border-b border-gray-100 align-top">
                    <td className="py-1 pr-2 font-medium">
                      {g.severity === "blocked" ? "Blocked" : "Workable"}
                    </td>
                    <td className="py-1 pr-2">{g.description}</td>
                    <td className="py-1">{g.workaround ?? "None"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {check.likely_too_long && (
            <p className="mt-2 rounded border border-amber-300 bg-amber-50 p-2">
              This may be too long for one turn (about {check.estimated_tool_calls} tool calls;
              the limit is {check.tool_call_budget}). The run will stop at the limit and say what
              was not done.
            </p>
          )}
        </>
      )}

      {needsProject && (state === "ready" || state === "error") && (
        <label className="mt-2 block">
          <span className="mr-2">Project</span>
          <select
            value={chosen}
            onChange={(e) => setChosen(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1"
          >
            <option value="">Choose a project</option>
            {allowed.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
      )}

      {state === "error" && failure && (
        <p role="alert" className="mt-2 text-red-700">
          {failure.message}
        </p>
      )}
      {state === "accepted" && <p className="mt-2 text-gray-600">Plan accepted</p>}
      {state === "cancelled" && (
        <p className="mt-2 text-gray-600">Cancelled. Nothing was run.</p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {state === "ready" && check && (
          <>
            <button
              type="button"
              disabled={runDisabled}
              onClick={() => effectiveProject && onRun(effectiveProject)}
              className="rounded bg-blue-600 px-3 py-1.5 text-white disabled:opacity-50"
            >
              {runLabel}
            </button>
            <button
              type="button"
              onClick={onCancel}
              className="rounded border border-gray-300 px-3 py-1.5"
            >
              Cancel
            </button>
          </>
        )}
        {state === "error" && failure?.control === "check_again" && (
          <button
            type="button"
            disabled={Boolean(failure.showProjectSelector) && !effectiveProject}
            onClick={() => onCheckAgain(effectiveProject)}
            className="rounded border border-gray-300 px-3 py-1.5"
          >
            Check again
          </button>
        )}
        {state === "error" && failure?.control === "run_again" && (
          <button
            type="button"
            disabled={!effectiveProject}
            onClick={() => effectiveProject && onRunAgain(effectiveProject)}
            className="rounded border border-gray-300 px-3 py-1.5"
          >
            Run again
          </button>
        )}
      </div>

      {check && (
        <details
          className="mt-2"
          onToggle={(e) => {
            if ((e.currentTarget as HTMLDetailsElement).open) onViewSkill?.();
          }}
        >
          <summary className="cursor-pointer text-gray-600">View skill</summary>
          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs">
            {skillContent ?? "Loading..."}
          </pre>
        </details>
      )}
    </section>
  );
}
