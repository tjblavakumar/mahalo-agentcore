"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { detectSkillBlock, downloadSkillFile, type SkillFileBlock } from "@/lib/skills/chatBlock";

interface CodeBlockProps {
  /** Language from the fence (```ts), when present. */
  language?: string;
  /** Raw source, used for the clipboard. */
  text: string;
  /** Rendered (syntax highlighted) children. */
  children: ReactNode;
  /** When set, a skill file block gets an "Open in upload" action. */
  onOpenSkillUpload?: (block: SkillFileBlock) => void;
}

export default function CodeBlock({ language, text, children, onOpenSkillUpload }: CodeBlockProps) {
  const skillFile = detectSkillBlock(language, text);
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard unavailable (insecure context / denied): leave the label alone.
    }
  }

  return (
    <div className="not-prose my-3 overflow-hidden rounded-lg border border-gray-700 bg-gray-900">
      <div className="flex items-center justify-between border-b border-gray-700 bg-gray-800 px-3 py-1">
        <span className="text-xs font-mono text-gray-400">{skillFile ? skillFile.filename : (language ?? "")}</span>
        <div className="flex items-center gap-1">
          {skillFile && (
            <button
              type="button"
              onClick={() => downloadSkillFile(skillFile)}
              aria-label={`Download ${skillFile.filename}`}
              className="rounded px-2 py-0.5 text-xs text-gray-300 hover:bg-gray-700 hover:text-white"
            >
              Download
            </button>
          )}
          {skillFile && onOpenSkillUpload && (
            <button
              type="button"
              onClick={() => onOpenSkillUpload(skillFile)}
              className="rounded px-2 py-0.5 text-xs text-gray-300 hover:bg-gray-700 hover:text-white"
            >
              Open in upload
            </button>
          )}
        <button
          type="button"
          onClick={handleCopy}
          aria-label={copied ? "Copied to clipboard" : "Copy code to clipboard"}
          className="rounded px-2 py-0.5 text-xs text-gray-300 hover:bg-gray-700 hover:text-white"
        >
          {copied ? "Copied" : "Copy"}
        </button>
        </div>
      </div>
      <pre className="overflow-x-auto p-3 text-xs leading-relaxed text-gray-100">
        <code className="hljs font-mono">{children}</code>
      </pre>
    </div>
  );
}
