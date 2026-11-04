import { describe, it, expect } from "vitest";
import { deriveBacklog, priorityRank } from "./backlog";
import type { Priority, Sprint, Story } from "./types";

function story(id: string, sprint_id: string | null, priority: Priority = "medium"): Story {
  return {
    id,
    project_id: "PAY",
    sprint_id,
    title: id,
    status: "todo",
    priority,
    story_points: 3,
  };
}

const sprints: Sprint[] = [
  { id: "PAY-S1", project_id: "PAY", name: "Sprint 1", status: "completed", start_date: "", end_date: "", velocity: 34 },
  { id: "PAY-S2", project_id: "PAY", name: "Sprint 2", status: "active", start_date: "", end_date: "", velocity: null },
  { id: "PAY-S3", project_id: "PAY", name: "Sprint 3", status: "planned", start_date: "", end_date: "", velocity: null },
];

describe("priorityRank", () => {
  it("orders critical > high > medium > low, unknown last", () => {
    expect(priorityRank("critical")).toBeLessThan(priorityRank("high"));
    expect(priorityRank("high")).toBeLessThan(priorityRank("medium"));
    expect(priorityRank("medium")).toBeLessThan(priorityRank("low"));
    expect(priorityRank("bogus")).toBeGreaterThan(priorityRank("low"));
  });
});

describe("deriveBacklog", () => {
  it("includes null-sprint and planned-sprint stories, tags planned, hides completed and active", () => {
    const stories = [
      story("PAY-900", null),
      story("PAY-109", "PAY-S3"),
      story("PAY-105", "PAY-S2"), // active -> hidden
      story("PAY-101", "PAY-S1"), // completed -> hidden
      story("PAY-950", ""), // empty string -> backlog
      story("PAY-ORPHAN", "PAY-GONE"), // unresolved -> not backlog
    ];
    const items = deriveBacklog(stories, sprints);
    const ids = items.map((i) => i.story.id);
    expect(ids).toContain("PAY-900");
    expect(ids).toContain("PAY-950");
    expect(ids).toContain("PAY-109");
    expect(ids).not.toContain("PAY-105");
    expect(ids).not.toContain("PAY-101");
    expect(ids).not.toContain("PAY-ORPHAN");

    const planned = items.find((i) => i.story.id === "PAY-109");
    expect(planned?.plannedSprintName).toBe("Sprint 3");
    const loose = items.find((i) => i.story.id === "PAY-900");
    expect(loose?.plannedSprintName).toBeNull();
  });

  it("sorts by priority then key", () => {
    const stories = [
      story("PAY-300", null, "low"),
      story("PAY-100", null, "critical"),
      story("PAY-200", null, "critical"),
      story("PAY-250", null, "high"),
    ];
    const ids = deriveBacklog(stories, sprints).map((i) => i.story.id);
    expect(ids).toEqual(["PAY-100", "PAY-200", "PAY-250", "PAY-300"]);
  });
});
