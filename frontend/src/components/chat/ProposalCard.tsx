"use client";

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
}

export default function ProposalCard({
  proposal,
  onApprove,
  onReject,
  isLoading,
  result,
}: ProposalCardProps) {
  const systemIcons: Record<string, string> = {
    jira: "📋",
    confluence: "📄",
    github: "🐙",
  };

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
            {Object.entries(proposal.params).map(([key, value]) =>
              value ? (
                <p key={key} className="text-xs text-gray-600 font-mono">
                  {key}: {String(value)}
                </p>
              ) : null
            )}
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
