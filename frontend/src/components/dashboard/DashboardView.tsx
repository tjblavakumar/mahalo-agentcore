"use client";

import ReactMarkdown from "react-markdown";
import type { Persona } from "@/lib/personas";
import type { ChatResponse } from "@/types";
import ProjectSelect from "@/components/dashboard/ProjectSelect";

interface DashboardViewProps {
  persona: Persona;
  result: ChatResponse | null;
  isLoading: boolean;
  error: string | null;
  selectedKeys: string[];
  onToggle: (key: string) => void;
  onRegenerate: () => void;
}

/** Blue scope pill text keyed off the current PM selection. */
function scopeLabel(role: Persona["role"], selectedKeys: string[]): string {
  if (role !== "product_manager") {
    return "All projects";
  }
  if (selectedKeys.length === 0) return "All projects";
  if (selectedKeys.length === 1) return `Project: ${selectedKeys[0]}`;
  return `Aggregating ${selectedKeys.length} projects`;
}

export default function DashboardView({
  persona,
  result,
  isLoading,
  error,
  selectedKeys,
  onToggle,
  onRegenerate,
}: DashboardViewProps) {
  const isPM = persona.role === "product_manager";
  const isEmpty = !result?.response || result.response.trim().length === 0;

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
          <p className="mt-1 text-gray-600">
            {persona.personaLabel} view, synthesized by the agent across your services.
          </p>
        </div>
        <button
          type="button"
          onClick={onRegenerate}
          disabled={isLoading}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
        >
          {isLoading ? "Synthesizing…" : "Regenerate"}
        </button>
      </div>

      {/* Scope pill */}
      <div className="mt-3">
        <span className="text-xs font-medium text-blue-700 bg-blue-50 px-3 py-1 rounded-full border border-blue-200">
          {scopeLabel(persona.role, selectedKeys)}
        </span>
      </div>

      {/* PM project selection */}
      {isPM && <ProjectSelect selectedKeys={selectedKeys} onToggle={onToggle} />}

      {/* Body */}
      <div className="mt-6">
        {error ? (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg p-4 text-sm">
            {error}
          </div>
        ) : isLoading ? (
          <div className="flex items-center gap-3 text-gray-500">
            <div className="flex gap-1.5">
              <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
              <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.1s]" />
              <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.2s]" />
            </div>
            <span className="text-sm">
              Synthesizing your dashboard… this can take up to a minute
            </span>
          </div>
        ) : isEmpty ? (
          <div className="bg-white rounded-lg shadow p-6 text-sm text-gray-500">
            The agent returned no content — try Regenerate.
          </div>
        ) : (
          <div className="bg-white rounded-lg shadow p-6">
            <div className="prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-strong:text-gray-900 prose-li:text-gray-700">
              <ReactMarkdown>{result!.response}</ReactMarkdown>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
