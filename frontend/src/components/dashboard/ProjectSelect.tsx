"use client";

import { SEED_PROJECTS } from "@/lib/projects";

interface ProjectSelectProps {
  /** Currently selected project keys (owned by the Dashboard page). */
  selectedKeys: string[];
  /** Toggle a project key on/off. */
  onToggle: (key: string) => void;
}

/**
 * PM-only multi-select of seed project keys, rendered as a chip set (no dropdown
 * library). Selection state lives on the Dashboard page; this is presentational.
 */
export default function ProjectSelect({ selectedKeys, onToggle }: ProjectSelectProps) {
  const selected = new Set(selectedKeys);

  return (
    <div className="mt-4">
      <p className="text-sm font-medium text-gray-700 mb-2">Projects to synthesize</p>
      <div className="flex flex-wrap gap-2">
        {SEED_PROJECTS.map((project) => {
          const isSelected = selected.has(project.key);
          return (
            <button
              key={project.key}
              type="button"
              onClick={() => onToggle(project.key)}
              aria-pressed={isSelected}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-sm transition-colors ${
                isSelected
                  ? "bg-blue-600 border-blue-600 text-white"
                  : "bg-white border-gray-300 text-gray-700 hover:border-gray-400"
              }`}
            >
              <span className="font-medium">{project.key}</span>
              <span className={isSelected ? "text-blue-100" : "text-gray-500"}>
                {project.name}
              </span>
            </button>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-gray-500">
        No selection synthesizes all projects. Use Regenerate to apply changes.
      </p>
    </div>
  );
}
