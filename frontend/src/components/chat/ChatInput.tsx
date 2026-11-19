"use client";

import { useState, useRef, useEffect, useId } from "react";
import SkillPicker, { optionId, type PickerRow } from "./SkillPicker";
import { applyOption, parseSlash, type SlashSkill } from "@/lib/skills/commands";
import { SKILL_PROJECTS } from "@/lib/skills/types";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled: boolean;
  /** Skill library for the "/" picker. Omitted: no picker. */
  skills?: SlashSkill[];
  /** The skill list failed to load: "/" messages are blocked with a notice. */
  skillsFailed?: boolean;
  onSkillCommand?: (name: string, project: string | null) => void;
  onOpenSkills?: () => void;
}

export default function ChatInput({
  onSend,
  disabled,
  skills = [],
  skillsFailed = false,
  onSkillCommand,
  onOpenSkills,
}: ChatInputProps) {
  const [message, setMessage] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const listId = useId();

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 120) + "px";
    }
  }, [message]);

  const slash = parseSlash(message, skills);
  // A closed list can be reopened with ArrowDown or Tab. For a complete
  // command without a project, the reopened list offers the project ids.
  const canReopen =
    slash.mode === "name" ||
    slash.mode === "project" ||
    (slash.mode === "ready" && slash.project === null);
  const [reopened, setReopened] = useState(false);
  const view =
    reopened && slash.mode === "ready" && slash.project === null
      ? { ...slash, mode: "project" as const, listOpen: true, options: [...SKILL_PROJECTS] }
      : slash;
  const listOpen = view.listOpen && !dismissed && view.options.length > 0;
  const safeIndex = Math.min(activeIndex, Math.max(view.options.length - 1, 0));

  const rows: PickerRow[] =
    view.mode === "name"
      ? view.options.map((name) => {
          const s = skills.find((k) => k.name === name);
          return { key: name, label: s ? `${name} - ${s.description}` : name };
        })
      : view.options.map((id) => ({ key: id, label: id }));

  const liveText = !listOpen
    ? ""
    : view.mode === "name"
      ? `${rows.length} ${rows.length === 1 ? "skill matches" : "skills match"}`
      : `${rows.length} ${rows.length === 1 ? "project" : "projects"}`;
  const statusText =
    view.mode === "name" && rows.length === 0 ? "No skills match" : liveText;

  function changeMessage(next: string) {
    setMessage(next);
    setActiveIndex(0);
    setDismissed(false);
    setReopened(false);
    setNotice(null);
  }

  function pick(key: string) {
    changeMessage(applyOption(message, view, key));
    textareaRef.current?.focus();
  }

  function submit() {
    if (!message.trim() || disabled) return;
    if (message.startsWith("/")) {
      if (skillsFailed) {
        setNotice("Skills could not be loaded. Try again.");
        return;
      }
      if (listOpen) {
        pick(view.options[safeIndex]);
        return;
      }
      if (slash.mode === "ready" && slash.skill) {
        onSkillCommand?.(slash.skill, slash.project ?? null);
        changeMessage("");
        return;
      }
      if (slash.mode === "project" && slash.skill) {
        // Row 4 with the list closed: send without a project.
        if (/^\/\S+[ \t]+$/.test(message)) {
          onSkillCommand?.(slash.skill, null);
          changeMessage("");
          return;
        }
        setNotice("Project must be one of PAY, CART, AUTH, PROD, ORD.");
        return;
      }
      setNotice(slash.error ?? "Type / to see the list of skills.");
      return;
    }
    onSend(message.trim());
    changeMessage("");
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    submit();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    const isSlash = message.startsWith("/") && !skillsFailed;
    if (isSlash) {
      if (listOpen) {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          const n = view.options.length;
          setActiveIndex((safeIndex + (e.key === "ArrowDown" ? 1 : n - 1)) % n);
          return;
        }
        if (e.key === "Tab") {
          e.preventDefault();
          pick(view.options[safeIndex]);
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setDismissed(true);
          return;
        }
      } else if ((e.key === "ArrowDown" || e.key === "Tab") && canReopen) {
        e.preventDefault();
        setDismissed(false);
        setReopened(true);
        setActiveIndex(0);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form onSubmit={handleSubmit} className="relative flex items-end gap-2">
      {listOpen && (
        <SkillPicker listId={listId} rows={rows} activeIndex={safeIndex} onPick={pick} />
      )}
      <div className="flex-1 flex flex-col">
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(e) => changeMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          rows={1}
          aria-label="Message"
          aria-autocomplete="list"
          aria-controls={listOpen ? listId : undefined}
          aria-activedescendant={listOpen ? optionId(listId, safeIndex) : undefined}
          placeholder="Ask about your projects, or type / to run a skill..."
          className="resize-none px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors text-gray-900 text-sm disabled:bg-gray-50 disabled:text-gray-400"
        />
        {(notice || (message.startsWith("/") && view.mode === "error" && view.error)) && (
          <p className="mt-1 text-xs text-red-600">{notice ?? view.error}</p>
        )}
        <span role="status" aria-live="polite" className="sr-only">
          {statusText}
        </span>
      </div>
      {onOpenSkills && (
        <button
          type="button"
          onClick={onOpenSkills}
          className="px-3 py-3 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50 transition-colors"
        >
          Skills
        </button>
      )}
      <button
        type="submit"
        disabled={disabled || !message.trim()}
        className="px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <svg
          className="w-5 h-5"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
          />
        </svg>
      </button>
    </form>
  );
}
