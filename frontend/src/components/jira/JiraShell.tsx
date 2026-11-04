"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/services/api";
import type { PersonaId } from "@/lib/personas";
import { deriveBacklog } from "@/lib/jira/backlog";
import { diffStories, fingerprintMap, type Fingerprints } from "@/lib/jira/diff";
import type { Board, Developer, Project, Sprint, Story } from "@/lib/jira/types";
import BacklogList from "./BacklogList";
import SprintBoard from "./SprintBoard";
import StoryPanel from "./StoryPanel";

const POLL_MS = 12_000;
const HIGHLIGHT_MS = 5_000;

type Tab = "sprint" | "backlog";

interface ProjectData {
  board: Board | null;
  sprints: Sprint[];
  stories: Story[];
  developers: Developer[];
}

function clock(d: Date): string {
  return d.toTimeString().slice(0, 8);
}

export default function JiraShell() {
  const { persona } = useAuth();
  const personaId = persona?.personaId;
  const params = useSearchParams();

  const [projects, setProjects] = useState<Project[] | null>(null);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(params.get("project"));
  const [storyKey, setStoryKey] = useState<string | null>(params.get("story"));
  const [tab, setTab] = useState<Tab>("sprint");

  useEffect(() => {
    let cancelled = false;
    api.get<{ projects: Project[] }>("/view/jira/projects", personaId).then((res) => {
      if (cancelled) return;
      if (res.error || !res.data) {
        setProjectsError(res.error ?? "Could not load projects");
        return;
      }
      setProjects(res.data.projects);
      setProjectId((cur) => (cur && res.data!.projects.some((p) => p.id === cur) ? cur : res.data!.projects[0]?.id ?? null));
    });
    return () => {
      cancelled = true;
    };
  }, [personaId]);

  const openStory = useCallback((key: string) => {
    setStoryKey(key);
    window.history.replaceState(null, "", `?project=${encodeURIComponent(projectId ?? "")}&story=${encodeURIComponent(key)}`);
  }, [projectId]);

  const closeStory = useCallback(() => {
    setStoryKey(null);
    window.history.replaceState(null, "", `?project=${encodeURIComponent(projectId ?? "")}`);
  }, [projectId]);

  return (
    <div className="p-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">MahaloJira</h1>
          <p className="mt-1 text-gray-600">Read-only view of the demo Jira data.</p>
        </div>
        {projects && projectId && (
          <label className="text-sm text-gray-700">
            <span className="mr-2">Project</span>
            <select
              value={projectId}
              onChange={(e) => {
                setProjectId(e.target.value);
                setStoryKey(null);
              }}
              className="rounded border border-gray-300 bg-white px-2 py-1"
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.id} · {p.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {projectsError && (
        <p role="alert" className="mt-6 rounded bg-red-50 p-3 text-sm text-red-700">
          Could not load projects: {projectsError}
        </p>
      )}
      {!projects && !projectsError && <p className="mt-6 text-gray-500">Loading projects…</p>}

      {projectId && (
        <ProjectView
          key={projectId}
          projectId={projectId}
          personaId={personaId}
          tab={tab}
          setTab={setTab}
          storyKey={storyKey}
          onOpen={openStory}
          onClose={closeStory}
        />
      )}
    </div>
  );
}

interface ProjectViewProps {
  projectId: string;
  personaId?: PersonaId;
  tab: Tab;
  setTab: (t: Tab) => void;
  storyKey: string | null;
  onOpen: (key: string) => void;
  onClose: () => void;
}

function ProjectView({ projectId, personaId, tab, setTab, storyKey, onOpen, onClose }: ProjectViewProps) {
  const [data, setData] = useState<ProjectData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [highlights, setHighlights] = useState<{ added: Set<string>; changed: Set<string> }>({
    added: new Set(),
    changed: new Set(),
  });
  const prevFingerprints = useRef<Fingerprints | null>(null);
  const clearTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    const base = `/view/jira`;
    const [board, sprints, stories, devs] = await Promise.all([
      api.get<Board>(`${base}/projects/${projectId}/board`, personaId),
      api.get<{ sprints: Sprint[] }>(`${base}/sprints/${projectId}`, personaId),
      api.get<{ stories: Story[] }>(`${base}/projects/${projectId}/stories`, personaId),
      api.get<{ developers: Developer[] }>(`${base}/developers`, personaId),
    ]);
    setIsRefreshing(false);

    const failure = sprints.error || stories.error || board.error || devs.error;
    if (failure || !sprints.data || !stories.data || !board.data || !devs.data) {
      setError(failure ?? "Unexpected empty response");
      return;
    }
    setError(null);

    const diff = diffStories(stories.data.stories, prevFingerprints.current);
    prevFingerprints.current = fingerprintMap(stories.data.stories);
    if (diff.added.size > 0 || diff.changed.size > 0) {
      setHighlights(diff);
      if (clearTimer.current) clearTimeout(clearTimer.current);
      clearTimer.current = setTimeout(
        () => setHighlights({ added: new Set(), changed: new Set() }),
        HIGHLIGHT_MS,
      );
    }
    setData({
      board: board.data,
      sprints: sprints.data.sprints,
      stories: stories.data.stories,
      developers: devs.data.developers,
    });
    setUpdatedAt(new Date());
  }, [projectId, personaId]);

  // Initial load + polling every POLL_MS, paused while the tab is hidden.
  useEffect(() => {
    // Deferred so no setState runs synchronously in the effect body.
    queueMicrotask(() => {
      load();
    });
    const id = setInterval(() => {
      if (!document.hidden) load();
    }, POLL_MS);
    function onVisible() {
      if (!document.hidden) load();
    }
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
      if (clearTimer.current) clearTimeout(clearTimer.current);
    };
  }, [load]);

  const nameFor = useCallback(
    (devId?: string | null) => (devId ? data?.developers.find((d) => d.id === devId)?.name : undefined),
    [data],
  );
  const highlightFor = useCallback(
    (key: string): "new" | "changed" | null =>
      highlights.added.has(key) ? "new" : highlights.changed.has(key) ? "changed" : null,
    [highlights],
  );

  const backlog = useMemo(() => (data ? deriveBacklog(data.stories, data.sprints) : []), [data]);
  const activeSprint = data?.sprints.find((s) => s.status === "active") ?? null;
  const previousVelocity = useMemo(() => {
    const done = (data?.sprints ?? []).filter((s) => s.status === "completed" && s.velocity !== null);
    done.sort((a, b) => b.end_date.localeCompare(a.end_date));
    return done[0]?.velocity ?? null;
  }, [data]);

  return (
    <div className="mt-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200">
        <div role="tablist" aria-label="MahaloJira views" className="flex gap-1">
          {(
            [
              ["sprint", "Current Sprint"],
              ["backlog", `Backlog${data ? ` (${backlog.length})` : ""}`],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              role="tab"
              type="button"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                tab === key ? "border-blue-600 text-blue-700" : "border-transparent text-gray-600 hover:text-gray-900"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 pb-2 text-xs text-gray-600" aria-live="polite">
          <span className="inline-flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${error ? "bg-red-500" : "bg-green-500"}`} aria-hidden="true" />
            {error ? "Offline" : "Live"}
            {updatedAt ? ` · updated ${clock(updatedAt)}` : ""}
          </span>
          <button
            type="button"
            onClick={() => {
              setIsRefreshing(true);
              load();
            }}
            disabled={isRefreshing}
            className="rounded border border-gray-300 bg-white px-2 py-1 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {isRefreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      <div className="mt-4" role="tabpanel">
        {error && (
          <p role="alert" className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700">
            Could not load Jira data: {error}
          </p>
        )}
        {!data && !error && <p className="text-gray-500">Loading…</p>}
        {data && data.board && tab === "sprint" && (
          <SprintBoard
            board={data.board}
            activeSprint={activeSprint}
            previousVelocity={previousVelocity}
            nameFor={nameFor}
            highlightFor={highlightFor}
            onOpen={onOpen}
          />
        )}
        {data && tab === "backlog" && (
          <BacklogList items={backlog} nameFor={nameFor} highlightFor={highlightFor} onOpen={onOpen} />
        )}
      </div>

      {storyKey && (
        <StoryPanel
          storyKey={storyKey}
          personaId={personaId}
          developers={data?.developers ?? []}
          sprints={data?.sprints ?? []}
          onClose={onClose}
        />
      )}
    </div>
  );
}
