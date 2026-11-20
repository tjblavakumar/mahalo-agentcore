"use client";

import { useRef, useState } from "react";
import type { PersonaId } from "@/lib/personas";
import { validateSkill, type SkillValidation } from "@/lib/skills/parse";
import type { SkillSummary } from "@/lib/skills/types";
import { deleteSkill, getSkill, putSkill } from "@/services/api";

interface SkillLibraryPanelProps {
  skills: SkillSummary[];
  personaId?: PersonaId;
  onClose: () => void;
  /** Called after a successful save or delete so the page re-fetches GET /skills. */
  onChanged: () => void;
  /** Open the check card for a skill (used after a save). */
  onCheckSkill: (name: string) => void;
  /** A skill drafted in chat: shown as the pending upload (validated, not saved). */
  initialDraft?: { filename: string; content: string };
}

interface Pending {
  filename: string;
  validation: SkillValidation;
}

/**
 * Library list, upload and delete. Skill text is untrusted: names and
 * descriptions are React text children and full skills are plain text in a
 * <pre>, never rendered as markdown or HTML.
 */
export default function SkillLibraryPanel({
  skills,
  personaId,
  onClose,
  onChanged,
  onCheckSkill,
  initialDraft,
}: SkillLibraryPanelProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState<Pending | null>(() =>
    initialDraft
      ? { filename: initialDraft.filename, validation: validateSkill(initialDraft.filename, initialDraft.content) }
      : null,
  );
  const [replaceAsk, setReplaceAsk] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [savedName, setSavedName] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [viewing, setViewing] = useState<{ name: string; content: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const text = await file.text();
    setPending({ filename: file.name, validation: validateSkill(file.name, text) });
    setReplaceAsk(false);
    setSavedName(null);
    setMessage(null);
  }

  async function save(overwrite: boolean) {
    if (!pending || !pending.validation.ok || !pending.validation.commandName) return;
    const name = pending.validation.commandName;
    setSaving(true);
    setMessage(null);
    const res = await putSkill(
      name,
      { filename: pending.filename, content: pending.validation.content, overwrite },
      personaId
    );
    setSaving(false);
    if (res.data) {
      setSavedName(name);
      setPending(null);
      setReplaceAsk(false);
      onChanged();
      return;
    }
    if (res.status === 409 && res.code === "exists") {
      setReplaceAsk(true);
      return;
    }
    setMessage(res.error ?? "The skill could not be saved.");
  }

  async function view(name: string) {
    if (viewing?.name === name) {
      setViewing(null);
      return;
    }
    const res = await getSkill(name, personaId);
    if (res.data) setViewing({ name, content: res.data.content });
    else setMessage(res.error ?? "The skill could not be loaded.");
  }

  async function remove(name: string) {
    setConfirmDelete(null);
    const res = await deleteSkill(name, personaId);
    if (res.error && res.status !== 404) {
      setMessage(res.error);
      return;
    }
    if (viewing?.name === name) setViewing(null);
    onChanged();
  }

  return (
    <aside
      role="dialog"
      aria-label="Skill library"
      className="fixed inset-y-0 right-0 z-20 w-full max-w-md overflow-y-auto border-l border-gray-200 bg-white p-4 text-sm shadow-xl"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">Skills</h2>
        <button type="button" onClick={onClose} className="rounded border border-gray-300 px-2 py-1">
          Close
        </button>
      </div>

      <ul className="mt-3 space-y-2">
        {skills.length === 0 && <li className="text-gray-500">No skills yet.</li>}
        {skills.map((s) => (
          <li key={s.name} className="rounded border border-gray-200 p-2">
            <div className="flex items-center gap-2">
              <span className="font-mono font-medium">{s.name}</span>
              {s.builtin && (
                <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs">Built-in</span>
              )}
            </div>
            <p className="text-gray-600">{s.description}</p>
            <div className="mt-1 flex gap-2">
              <button type="button" onClick={() => view(s.name)} className="text-blue-700 underline">
                {viewing?.name === s.name ? "Hide" : "View"}
              </button>
              {!s.builtin &&
                (confirmDelete === s.name ? (
                  <>
                    <button type="button" onClick={() => remove(s.name)} className="text-red-700 underline">
                      Confirm delete
                    </button>
                    <button type="button" onClick={() => setConfirmDelete(null)} className="underline">
                      Keep
                    </button>
                  </>
                ) : (
                  <button type="button" onClick={() => setConfirmDelete(s.name)} className="text-red-700 underline">
                    Delete
                  </button>
                ))}
            </div>
            {viewing?.name === s.name && (
              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs">
                {viewing.content}
              </pre>
            )}
          </li>
        ))}
      </ul>

      <div className="mt-4">
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="rounded bg-blue-600 px-3 py-1.5 text-white"
        >
          Upload skill
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".md,text/markdown"
          onChange={handleFile}
          aria-label="Skill file"
          className="hidden"
        />
      </div>

      {pending && (
        <div className="mt-3 rounded border border-gray-200 p-2">
          <p className="font-mono">{pending.filename}</p>
          {pending.validation.errors.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-red-700">
              {pending.validation.errors.map((er, i) => (
                <li key={`${er.rule}-${i}`}>{er.message}</li>
              ))}
            </ul>
          )}
          {pending.validation.warnings.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-amber-700">
              {pending.validation.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 text-xs">
            {pending.validation.content}
          </pre>
          {replaceAsk ? (
            <div className="mt-2 flex items-center gap-2">
              <span>Replace the existing skill?</span>
              <button type="button" onClick={() => save(true)} className="rounded bg-blue-600 px-2 py-1 text-white">
                Replace
              </button>
              <button type="button" onClick={() => setReplaceAsk(false)} className="rounded border border-gray-300 px-2 py-1">
                Keep existing
              </button>
            </div>
          ) : (
            <button
              type="button"
              disabled={!pending.validation.ok || saving}
              onClick={() => save(false)}
              className="mt-2 rounded bg-blue-600 px-3 py-1.5 text-white disabled:opacity-50"
            >
              Save
            </button>
          )}
        </div>
      )}

      {savedName && (
        <div className="mt-3 flex items-center gap-2">
          <span>Saved {savedName}.</span>
          <button type="button" onClick={() => onCheckSkill(savedName)} className="rounded border border-gray-300 px-2 py-1">
            Check this skill
          </button>
        </div>
      )}
      {message && (
        <p role="alert" className="mt-3 text-red-700">
          {message}
        </p>
      )}
    </aside>
  );
}
