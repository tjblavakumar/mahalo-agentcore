"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/services/api";
import type { PersonaId } from "@/lib/personas";
import { COLUMN_LABEL, type Developer, type Sprint, type Story } from "@/lib/jira/types";
import { PriorityBadge } from "./StoryCard";

interface StoryPanelProps {
  storyKey: string;
  personaId?: PersonaId;
  developers: Developer[];
  sprints: Sprint[];
  onClose: () => void;
}

export default function StoryPanel({ storyKey, personaId, developers, sprints, onClose }: StoryPanelProps) {
  const [loaded, setLoaded] = useState<{ key: string; story: Story | null; error: string | null } | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  // Load the story (includes assignee_details).
  useEffect(() => {
    let cancelled = false;
    api.get<Story>(`/view/jira/stories/${encodeURIComponent(storyKey)}`, personaId).then((res) => {
      if (!cancelled) setLoaded({ key: storyKey, story: res.data, error: res.error });
    });
    return () => {
      cancelled = true;
    };
  }, [storyKey, personaId]);

  // Focus the close button on open, restore focus to the opener on close; Esc closes.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [onClose]);

  const current = loaded && loaded.key === storyKey ? loaded : null;
  const story = current?.story ?? null;
  const sprint = story?.sprint_id ? sprints.find((s) => s.id === story.sprint_id) : undefined;
  const nameOf = (id: string) => developers.find((d) => d.id === id)?.name ?? id;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} aria-hidden="true" />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={`Story ${storyKey}`}
        className="relative z-50 h-full w-full max-w-xl overflow-y-auto bg-white p-6 shadow-xl"
      >
        <div className="flex items-start justify-between gap-4">
          <p className="font-mono text-sm text-gray-500">{storyKey}</p>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close story panel"
            className="rounded px-2 py-1 text-gray-600 hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            ✕
          </button>
        </div>

        {!current && <p className="mt-6 text-gray-500">Loading story…</p>}
        {current?.error && (
          <p role="alert" className="mt-6 rounded bg-red-50 p-3 text-sm text-red-700">
            Could not load this story: {current.error}
          </p>
        )}

        {story && (
          <div className="mt-2">
            <h2 className="text-xl font-semibold text-gray-900">{story.title}</h2>
            <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-xs uppercase text-gray-500">Status</dt>
                <dd className="text-gray-900">{COLUMN_LABEL[story.status] ?? story.status}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-gray-500">Priority</dt>
                <dd>
                  <PriorityBadge priority={story.priority} />
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-gray-500">Story points</dt>
                <dd className="text-gray-900">{story.story_points}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-gray-500">Sprint</dt>
                <dd className="text-gray-900">
                  {sprint ? `${sprint.name} (${sprint.status})` : story.sprint_id ? story.sprint_id : "Backlog"}
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-xs uppercase text-gray-500">Assignee</dt>
                <dd className="text-gray-900">
                  {story.assignee_details
                    ? `${story.assignee_details.name} · ${story.assignee_details.email}`
                    : story.assignee
                      ? nameOf(story.assignee)
                      : "Unassigned"}
                </dd>
              </div>
            </dl>

            <h3 className="mt-6 text-sm font-semibold text-gray-900">Description</h3>
            <p className="mt-1 whitespace-pre-wrap text-sm text-gray-700">
              {story.description || "No description."}
            </p>

            <h3 className="mt-6 text-sm font-semibold text-gray-900">Acceptance criteria</h3>
            {story.acceptance_criteria && story.acceptance_criteria.length > 0 ? (
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-gray-700">
                {story.acceptance_criteria.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-gray-500">None recorded.</p>
            )}

            <h3 className="mt-6 text-sm font-semibold text-gray-900">Comments</h3>
            {story.comments && story.comments.length > 0 ? (
              <ul className="mt-1 space-y-3">
                {story.comments.map((c, i) => (
                  <li key={i} className="rounded bg-gray-50 p-3 text-sm">
                    <p className="text-xs text-gray-500">
                      {nameOf(c.author)} · {c.date}
                    </p>
                    <p className="mt-1 text-gray-800">{c.text}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-gray-500">No comments.</p>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}
