/**
 * Shapes returned by the mock Jira service (via the read-only `/view/jira/*`
 * proxy). Only the fields MahaloJira renders are typed; unknown extras are
 * tolerated.
 */

export type StoryStatus = "todo" | "in_progress" | "in_review" | "done";
export type Priority = "critical" | "high" | "medium" | "low";
export type SprintStatus = "planned" | "active" | "completed";
export type ColumnKey = "todo" | "in_progress" | "in_review" | "done";

export interface Developer {
  id: string;
  name: string;
  email: string;
}

export interface Comment {
  author: string;
  date: string;
  text: string;
}

export interface Story {
  id: string;
  project_id: string;
  sprint_id: string | null;
  title: string;
  description?: string;
  status: StoryStatus;
  priority: Priority;
  story_points: number;
  assignee?: string | null;
  assignee_details?: Developer | null;
  acceptance_criteria?: string[];
  comments?: Comment[];
}

export interface Sprint {
  id: string;
  project_id: string;
  name: string;
  status: SprintStatus;
  start_date: string;
  end_date: string;
  velocity: number | null;
  completed_points?: number;
  total_points?: number;
}

export interface Project {
  id: string;
  name: string;
  description?: string;
  lead?: string;
  status?: string;
}

export interface Board {
  /** null when the project has no active sprint (columns is then {}). */
  sprint: Sprint | null;
  columns: Partial<Record<ColumnKey, Story[]>>;
}

export const COLUMN_ORDER: ColumnKey[] = ["todo", "in_progress", "in_review", "done"];

export const COLUMN_LABEL: Record<ColumnKey, string> = {
  todo: "To Do",
  in_progress: "In Progress",
  in_review: "In Review",
  done: "Done",
};
