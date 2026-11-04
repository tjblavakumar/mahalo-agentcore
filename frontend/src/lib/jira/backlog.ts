/**
 * Backlog derivation: every story NOT in the active sprint and NOT in a
 * completed sprint. That means `sprint_id` is null/empty, OR it belongs to a
 * sprint whose status is `planned`. Completed-sprint stories are history and
 * are hidden. Sorted by priority (critical > high > medium > low), then key.
 */

import type { Priority, Sprint, Story } from "./types";

const PRIORITY_RANK: Record<Priority, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

/** Numeric rank for a priority (lower sorts first); unknown priorities sort last. */
export function priorityRank(priority: string): number {
  return PRIORITY_RANK[priority as Priority] ?? 99;
}

export interface BacklogItem {
  story: Story;
  /** The planned sprint's name when the story sits in a planned sprint, else null. */
  plannedSprintName: string | null;
}

/** Derive and sort the backlog from all project stories + sprints. */
export function deriveBacklog(stories: Story[], sprints: Sprint[]): BacklogItem[] {
  const byId = new Map(sprints.map((s) => [s.id, s]));
  const items: BacklogItem[] = [];

  for (const story of stories) {
    const sid = story.sprint_id;
    if (!sid) {
      items.push({ story, plannedSprintName: null });
      continue;
    }
    const sprint = byId.get(sid);
    // A sprint_id that resolves to a planned sprint -> backlog with a tag.
    // Active/completed (or an id that no longer resolves) -> not backlog.
    if (sprint && sprint.status === "planned") {
      items.push({ story, plannedSprintName: sprint.name });
    }
  }

  items.sort((a, b) => {
    const pr = priorityRank(a.story.priority) - priorityRank(b.story.priority);
    if (pr !== 0) return pr;
    return a.story.id.localeCompare(b.story.id);
  });
  return items;
}
