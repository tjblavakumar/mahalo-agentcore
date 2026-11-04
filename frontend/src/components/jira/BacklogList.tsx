"use client";

import type { BacklogItem } from "@/lib/jira/backlog";
import StoryCard from "./StoryCard";

interface BacklogListProps {
  items: BacklogItem[];
  nameFor: (devId?: string | null) => string | undefined;
  highlightFor: (key: string) => "new" | "changed" | null;
  onOpen: (key: string) => void;
}

export default function BacklogList({ items, nameFor, highlightFor, onOpen }: BacklogListProps) {
  if (items.length === 0) {
    return (
      <div className="rounded-lg bg-white p-8 text-center text-gray-500 shadow">
        The backlog is empty.
      </div>
    );
  }
  return (
    <section aria-label="Backlog" className="rounded-lg bg-gray-100 p-3">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-600">
        Backlog · {items.length} {items.length === 1 ? "story" : "stories"}
      </h2>
      <div className="space-y-2">
        {items.map(({ story, plannedSprintName }) => (
          <StoryCard
            key={story.id}
            story={story}
            assigneeName={nameFor(story.assignee)}
            plannedTag={plannedSprintName}
            highlight={highlightFor(story.id)}
            onOpen={onOpen}
          />
        ))}
      </div>
    </section>
  );
}
