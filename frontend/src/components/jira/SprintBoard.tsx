"use client";

import { daysLeft, formatDateRange, sprintProgressPct } from "@/lib/jira/board";
import { COLUMN_LABEL, COLUMN_ORDER, type Board, type Sprint } from "@/lib/jira/types";
import StoryCard from "./StoryCard";

interface SprintBoardProps {
  board: Board;
  /** Active sprint with completed/total points (from GET /sprints/{project}). */
  activeSprint: Sprint | null;
  previousVelocity: number | null;
  nameFor: (devId?: string | null) => string | undefined;
  highlightFor: (key: string) => "new" | "changed" | null;
  onOpen: (key: string) => void;
}

export default function SprintBoard({
  board,
  activeSprint,
  previousVelocity,
  nameFor,
  highlightFor,
  onOpen,
}: SprintBoardProps) {
  const sprint = board.sprint;
  if (!sprint) {
    return (
      <div className="rounded-lg bg-white p-8 text-center text-gray-500 shadow">
        This project has no active sprint. See the Backlog tab.
      </div>
    );
  }
  const completed = activeSprint?.completed_points ?? 0;
  const total = activeSprint?.total_points ?? 0;
  const pct = sprintProgressPct(completed, total);

  return (
    <div>
      <div className="mb-4 rounded-lg bg-white p-4 shadow">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold text-gray-900">{sprint.name}</h2>
          <p className="text-sm text-gray-600">
            {formatDateRange(sprint.start_date, sprint.end_date)} · {daysLeft(sprint.end_date)} days left
          </p>
        </div>
        <div className="mt-3">
          <div className="mb-1 flex justify-between text-xs text-gray-600">
            <span>
              {completed} of {total} points done
            </span>
            <span>{pct}%</span>
          </div>
          <div
            role="progressbar"
            aria-label="Sprint points completed"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            className="h-2 w-full overflow-hidden rounded-full bg-gray-200"
          >
            <div className="h-full bg-green-500" style={{ width: `${pct}%` }} />
          </div>
        </div>
        {previousVelocity !== null && (
          <p className="mt-2 text-xs text-gray-500">Previous sprint velocity: {previousVelocity}</p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {COLUMN_ORDER.map((key) => {
          const stories = board.columns[key] ?? [];
          return (
            <section
              key={key}
              aria-label={`${COLUMN_LABEL[key]} column`}
              className="rounded-lg bg-gray-100 p-3"
            >
              <h3 className="mb-3 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-gray-600">
                <span>{COLUMN_LABEL[key]}</span>
                <span className="rounded-full bg-gray-200 px-2 py-0.5">{stories.length}</span>
              </h3>
              <div className="space-y-2">
                {stories.length === 0 ? (
                  <p className="py-4 text-center text-xs text-gray-400">No stories</p>
                ) : (
                  stories.map((s) => (
                    <StoryCard
                      key={s.id}
                      story={s}
                      assigneeName={nameFor(s.assignee)}
                      highlight={highlightFor(s.id)}
                      onOpen={onOpen}
                    />
                  ))
                )}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
