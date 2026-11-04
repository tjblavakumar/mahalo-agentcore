import { describe, it, expect } from "vitest";
import {
  boardStoryCount,
  daysLeft,
  formatDateRange,
  formatShortDate,
  groupByColumn,
  sprintProgressPct,
} from "./board";
import type { Board, Story } from "./types";

function story(id: string, status: Story["status"]): Story {
  return {
    id,
    project_id: "PAY",
    sprint_id: "PAY-S2",
    title: id,
    status,
    priority: "medium",
    story_points: 3,
  };
}

describe("groupByColumn", () => {
  it("places each story in its status column, ignoring unknown statuses", () => {
    const cols = groupByColumn([
      story("A", "todo"),
      story("B", "in_progress"),
      story("C", "done"),
      story("D", "in_review"),
      { ...story("E", "todo"), status: "archived" as Story["status"] },
    ]);
    expect(cols.todo.map((s) => s.id)).toEqual(["A"]);
    expect(cols.in_progress.map((s) => s.id)).toEqual(["B"]);
    expect(cols.in_review.map((s) => s.id)).toEqual(["D"]);
    expect(cols.done.map((s) => s.id)).toEqual(["C"]);
  });
});

describe("sprintProgressPct", () => {
  it("computes a clamped integer percentage", () => {
    expect(sprintProgressPct(5, 34)).toBe(15);
    expect(sprintProgressPct(0, 34)).toBe(0);
    expect(sprintProgressPct(34, 34)).toBe(100);
    expect(sprintProgressPct(40, 34)).toBe(100);
  });
  it("returns 0 when there are no total points", () => {
    expect(sprintProgressPct(0, 0)).toBe(0);
    expect(sprintProgressPct(undefined, undefined)).toBe(0);
  });
});

describe("daysLeft", () => {
  it("counts whole days to the end date and clamps negatives to 0", () => {
    expect(daysLeft("2026-08-22", new Date("2026-08-19T10:00:00Z"))).toBe(3);
    expect(daysLeft("2026-08-22", new Date("2026-08-22T23:00:00Z"))).toBe(0);
    expect(daysLeft("2026-08-10", new Date("2026-08-19T00:00:00Z"))).toBe(0);
  });
  it("returns 0 for an unparseable date", () => {
    expect(daysLeft("not-a-date")).toBe(0);
  });
});

describe("date formatting", () => {
  it("formats a short date", () => {
    expect(formatShortDate("2026-08-11")).toBe("Aug 11");
    expect(formatShortDate("2027-01-06")).toBe("Jan 6");
    expect(formatShortDate("")).toBe("");
    expect(formatShortDate("2026-13-40")).toBe("");
  });
  it("formats a range", () => {
    expect(formatDateRange("2026-08-11", "2026-08-22")).toBe("Aug 11 – Aug 22");
  });
});

describe("boardStoryCount", () => {
  it("counts across all columns", () => {
    const board: Board = {
      sprint: {
        id: "PAY-S2",
        project_id: "PAY",
        name: "Sprint 2",
        status: "active",
        start_date: "2026-08-11",
        end_date: "2026-08-22",
        velocity: null,
      },
      columns: groupByColumn([story("A", "todo"), story("B", "done"), story("C", "done")]),
    };
    expect(boardStoryCount(board)).toBe(3);
  });
});
