"use client";

import { classifyParam } from "@/lib/proposalParams";

interface Proposal {
  action: string;
  system: string;
  params: Record<string, unknown>;
  description: string;
  interrupt_id?: string;
}

interface ProposalCardProps {
  proposal: Proposal;
  onApprove: () => void;
  onReject: () => void;
  isLoading: boolean;
  result?: { success: boolean; message: string } | null;
  /** Per-file one-liners from `review.file_summaries`, matched by path. */
  fileSummaries?: { path: string; summary: string }[];
}

const COMMIT_CONTEXT_KEYS = ["repo_id", "branch", "message"];

export default function ProposalCard({
  proposal,
  onApprove,
  onReject,
  isLoading,
  result,
  fileSummaries,
}: ProposalCardProps) {
  const systemIcons: Record<string, string> = {
    jira: "📋",
    confluence: "📄",
    github: "🐙",
  };

  const hasFiles = Object.values(proposal.params).some(
    (v) => Boolean(v) && classifyParam(v).kind === "files",
  );
  const paramText = (k: string) => {
    const v = proposal.params[k];
    return typeof v === "string" && v ? v : null;
  };
  const repo = paramText("repo_id");
  const branch = paramText("branch");
  const commitMessage = paramText("message");
  const summaryFor = (path: string) =>
    fileSummaries?.find((s) => s.path === path)?.summary || null;
  // The "What it does" column only appears once the review has supplied at
  // least one summary for these files; otherwise it would be a column of dashes.
  const hasAnySummary = (files: { path: string }[]) =>
    files.some((f) => summaryFor(f.path) !== null);

  if (result) {
    return (
      <div
        className={`rounded-lg border p-4 mb-4 ${
          result.success
            ? "bg-green-50 border-green-200"
            : "bg-red-50 border-red-200"
        }`}
      >
        <p
          className={`text-sm font-medium ${
            result.success ? "text-green-700" : "text-red-700"
          }`}
        >
          {result.message}
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 mb-4">
      <div className="flex items-start gap-3">
        <span className="text-2xl">{systemIcons[proposal.system] || "⚡"}</span>
        <div className="flex-1">
          <h4 className="text-sm font-semibold text-amber-900">
            Proposed Action
          </h4>
          <p className="text-sm text-amber-800 mt-1">{proposal.description}</p>

          <div className="mt-2 bg-white/60 rounded p-2">
            <p className="text-xs text-gray-600 font-mono">
              System: {proposal.system} | Action: {proposal.action}
            </p>
            {hasFiles && (
              <div className="mt-1 text-xs text-gray-600 font-mono">
                {repo && <p>Repo: {repo}</p>}
                {branch && <p>Branch: {branch}</p>}
                {commitMessage && <p>Commit message: {commitMessage}</p>}
              </div>
            )}
            {Object.entries(proposal.params).map(([key, value]) => {
              if (!value) return null;
              if (hasFiles && COMMIT_CONTEXT_KEYS.includes(key)) return null;
              const view = classifyParam(value);
              if (view.kind === "text") {
                return (
                  <p key={key} className="text-xs text-gray-600 font-mono">
                    {key}: {view.text}
                  </p>
                );
              }
              if (view.kind === "json") {
                return (
                  <div key={key} className="mt-1">
                    <p className="text-xs text-gray-600 font-mono">{key}:</p>
                    <pre className="text-xs text-gray-800 font-mono bg-white rounded border border-gray-200 p-2 overflow-x-auto max-h-96 overflow-y-auto">
                      {view.text}
                    </pre>
                  </div>
                );
              }
              const showSummary = hasAnySummary(view.files);
              return (
                <div key={key} className="mt-2">
                  <p className="text-xs text-gray-600 font-mono">{key}:</p>
                  <div className="mt-1 overflow-x-auto">
                    <table className="w-full border-collapse text-xs">
                      <thead>
                        <tr className="text-left text-gray-600">
                          <th className="border border-gray-200 px-2 py-1 font-semibold">
                            File path
                          </th>
                          <th className="border border-gray-200 px-2 py-1 font-semibold">
                            Lines
                          </th>
                          {showSummary && (
                            <th className="border border-gray-200 px-2 py-1 font-semibold">
                              What it does
                            </th>
                          )}
                        </tr>
                      </thead>
                      <tbody>
                        {view.files.map((file, i) => {
                          const summary = summaryFor(file.path);
                          return (
                            <tr key={`${file.path}-${i}`} className="align-top">
                              <td className="border border-gray-200 px-2 py-1 font-mono text-gray-800 break-all">
                                {file.path}
                              </td>
                              <td className="border border-gray-200 px-2 py-1 text-gray-700">
                                {file.lineCount}
                              </td>
                              {showSummary && (
                                <td className="border border-gray-200 px-2 py-1 text-gray-700">
                                  {summary ?? (
                                    <span className="text-gray-400">—</span>
                                  )}
                                </td>
                              )}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  {view.files.map((file, i) => (
                    <details key={`code-${file.path}-${i}`} className="mt-1">
                      <summary className="text-xs text-gray-700 font-mono cursor-pointer">
                        View code: {file.path}
                      </summary>
                      <pre className="text-xs text-gray-800 font-mono bg-white rounded border border-gray-200 p-2 overflow-x-auto max-h-96 overflow-y-auto">
                        {file.content}
                      </pre>
                    </details>
                  ))}
                </div>
              );
            })}
          </div>

          <div className="flex gap-2 mt-3">
            <button
              onClick={onApprove}
              disabled={isLoading}
              className="px-3 py-1.5 bg-green-600 text-white text-xs font-medium rounded-lg hover:bg-green-700 transition-colors disabled:opacity-50"
            >
              {isLoading ? "Executing..." : "Approve"}
            </button>
            <button
              onClick={onReject}
              disabled={isLoading}
              className="px-3 py-1.5 bg-red-100 text-red-700 text-xs font-medium rounded-lg hover:bg-red-200 transition-colors border border-red-200 disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
