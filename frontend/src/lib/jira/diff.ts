/**
 * Change detection between two poll snapshots. A story is "new" when its key is
 * absent from the previous snapshot; "changed" when its fingerprint
 * (status|assignee|points|priority|sprint|title) differs. Used to briefly
 * highlight cards after a refresh.
 */

import type { Story } from "./types";

/** Stable fingerprint of the fields a demo viewer cares about. */
export function fingerprint(story: Story): string {
  return [
    story.status,
    story.assignee ?? "",
    story.story_points,
    story.priority,
    story.sprint_id ?? "",
    story.title,
  ].join("|");
}

export interface StoryDiff {
  /** Keys present now but not before. */
  added: Set<string>;
  /** Keys present in both whose fingerprint changed. */
  changed: Set<string>;
}

export type Fingerprints = Record<string, string>;

/** Build the fingerprint map for a snapshot (key -> fingerprint). */
export function fingerprintMap(stories: Story[]): Fingerprints {
  const map: Fingerprints = {};
  for (const story of stories) {
    map[story.id] = fingerprint(story);
  }
  return map;
}

/**
 * Diff the current stories against the PREVIOUS fingerprint map. When `previous`
 * is null (first poll) nothing is highlighted.
 */
export function diffStories(stories: Story[], previous: Fingerprints | null): StoryDiff {
  const added = new Set<string>();
  const changed = new Set<string>();
  if (previous === null) {
    return { added, changed };
  }
  for (const story of stories) {
    const prev = previous[story.id];
    if (prev === undefined) {
      added.add(story.id);
    } else if (prev !== fingerprint(story)) {
      changed.add(story.id);
    }
  }
  return { added, changed };
}
