"use client";

import type { Priority, Story } from "@/lib/jira/types";

/** Original (non-branded) priority glyphs. */
export const PRIORITY_ICON: Record<Priority, { icon: string; label: string; color: string }> = {
  critical: { icon: "⏫", label: "Critical", color: "text-red-600" },
  high: { icon: "🔺", label: "High", color: "text-orange-600" },
  medium: { icon: "🔸", label: "Medium", color: "text-yellow-600" },
  low: { icon: "🔽", label: "Low", color: "text-sky-600" },
};

export function PriorityBadge({ priority }: { priority: Priority }) {
  const p = PRIORITY_ICON[priority] ?? { icon: "▫️", label: String(priority), color: "text-gray-500" };
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${p.color}`} title={`Priority: ${p.label}`}>
      <span aria-hidden="true">{p.icon}</span>
      <span className="sr-only">Priority: </span>
      {p.label}
    </span>
  );
}

interface StoryCardProps {
  story: Story;
  assigneeName?: string;
  plannedTag?: string | null;
  highlight?: "new" | "changed" | null;
  onOpen: (key: string) => void;
}

export default function StoryCard({ story, assigneeName, plannedTag, highlight, onOpen }: StoryCardProps) {
  const ring =
    highlight === "new"
      ? "ring-2 ring-green-400 bg-green-50"
      : highlight === "changed"
        ? "ring-2 ring-amber-400 bg-amber-50"
        : "bg-white";
  return (
    <button
      type="button"
      onClick={() => onOpen(story.id)}
      aria-label={`Open ${story.id}: ${story.title}`}
      className={`w-full text-left rounded-md border border-gray-200 p-3 shadow-sm transition-colors hover:border-blue-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${ring}`}
    >
      <p className="text-sm font-medium text-gray-900">{story.title}</p>
      {plannedTag && (
        <span className="mt-1 inline-block rounded bg-indigo-50 px-1.5 py-0.5 text-[11px] text-indigo-700">
          planned: {plannedTag}
        </span>
      )}
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="font-mono text-xs text-gray-500">{story.id}</span>
        <div className="flex items-center gap-2">
          <PriorityBadge priority={story.priority} />
          <span
            className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-semibold text-gray-700"
            title="Story points"
          >
            {story.story_points}
          </span>
        </div>
      </div>
      {assigneeName && <p className="mt-1 text-xs text-gray-500">👤 {assigneeName}</p>}
      {highlight && (
        <p className="mt-1 text-[11px] font-medium text-gray-600">{highlight === "new" ? "New" : "Updated"}</p>
      )}
    </button>
  );
}
