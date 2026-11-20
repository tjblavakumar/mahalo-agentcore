"use client";

import { Children, isValidElement, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
// Only a handful of common languages are registered (instead of lowlight's
// default 37) to keep the bundle small.
import bash from "highlight.js/lib/languages/bash";
import diff from "highlight.js/lib/languages/diff";
import java from "highlight.js/lib/languages/java";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import type { Stage, ReviewSummary } from "@/types";
import { trustLine } from "@/lib/stageProgress";
import { matchBadge, BADGE_CLASSES, type BadgeMatch } from "@/lib/badgeTokens";
import type { SkillFileBlock } from "@/lib/skills/chatBlock";
import CodeBlock from "./CodeBlock";

const HIGHLIGHT_LANGUAGES = {
  bash,
  diff,
  java,
  javascript,
  json,
  python,
  sql,
  typescript,
  xml,
  yaml,
};

const PROSE_CLASSES = [
  "prose prose-sm max-w-none leading-relaxed",
  "prose-headings:text-gray-900 prose-headings:font-semibold",
  "prose-h1:text-base prose-h1:mt-4 prose-h1:mb-2",
  "prose-h2:text-base prose-h2:mt-4 prose-h2:mb-2",
  "prose-h3:text-sm prose-h3:mt-3 prose-h3:mb-1.5",
  "prose-p:text-gray-700 prose-p:my-2",
  "prose-strong:text-gray-900",
  "prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-li:text-gray-700",
  "prose-ul:list-disc prose-ol:list-decimal prose-li:marker:text-gray-500",
  "prose-a:text-blue-600",
  "[&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
].join(" ");

/** Flatten React children to text; returns "" if any non-text node is present. */
function plainText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(plainText).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return plainText(node.props.children);
  }
  return "";
}

function Badge({ match }: { match: BadgeMatch }) {
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium leading-none ${BADGE_CLASSES[match.tone]}`}
    >
      {match.label}
    </span>
  );
}

/** Badge a table cell only when its entire content is a single plain-text token. */
function MaybeBadge({ children }: { children?: ReactNode }) {
  const onlyText = Children.toArray(children).every((c) => typeof c === "string");
  const badge = onlyText ? matchBadge(plainText(children)) : null;
  return badge ? <Badge match={badge} /> : <>{children}</>;
}

interface ChatMessageProps {
  role: "user" | "assistant";
  content: string;
  systemsQueried?: string[];
  /** Authoritative pipeline stages used to derive the who-did-what trust line. */
  stages?: Stage[];
  /** Review sub-agent summary (findings) for a code turn. */
  review?: ReviewSummary;
  /** Hand a skill file block from the answer to the skill library upload flow. */
  onOpenSkillUpload?: (block: SkillFileBlock) => void;
}

export default function ChatMessage({
  role,
  content,
  systemsQueried,
  stages,
  review,
  onOpenSkillUpload,
}: ChatMessageProps) {
  const isUser = role === "user";
  const line = isUser ? null : trustLine(stages);
  const hasFindings = !isUser && Boolean(review?.findings);

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-3 ${
          isUser
            ? "bg-blue-600 text-white"
            : "bg-white border border-gray-200 text-gray-800"
        }`}
      >
        {isUser ? (
          <p className="text-sm whitespace-pre-wrap">{content}</p>
        ) : (
          <div className={PROSE_CLASSES}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[[rehypeHighlight, { languages: HIGHLIGHT_LANGUAGES }]]}
              components={{
                // `node` is injected by react-markdown; drop it so it is not
                // spread onto the DOM element.
                table: ({ node, ...props }) => (
                  <div className="overflow-x-auto">
                    <table
                      className="border-collapse border border-gray-300"
                      {...props}
                    />
                  </div>
                ),
                th: ({ node, ...props }) => (
                  <th
                    className="border border-gray-300 px-3 py-1.5 text-left font-semibold"
                    {...props}
                  />
                ),
                td: ({ node, children, ...props }) => (
                  <td
                    className="border border-gray-300 px-3 py-1.5"
                    {...props}
                  >
                    <MaybeBadge>{children}</MaybeBadge>
                  </td>
                ),
                strong: ({ node, children, ...props }) => {
                  const badge = matchBadge(plainText(children));
                  return badge ? (
                    <Badge match={badge} />
                  ) : (
                    <strong {...props}>{children}</strong>
                  );
                },
                blockquote: ({ node, ...props }) => (
                  <blockquote
                    className="rounded-r-md border-l-4 border-blue-400 bg-blue-50 px-4 py-2 not-italic text-gray-800 [&>p]:my-1 [&>p]:before:content-none [&>p]:after:content-none"
                    {...props}
                  />
                ),
                // Fenced blocks: the <pre> wraps a <code>; render our own block
                // from the code element's props so the inner <code> below only
                // ever sees inline code.
                pre: ({ children }) => {
                  const child = Children.toArray(children)[0];
                  if (!isValidElement<{ className?: string; children?: ReactNode }>(child)) {
                    return <pre>{children}</pre>;
                  }
                  const lang = /language-([\w-]+)/.exec(child.props.className ?? "")?.[1];
                  return (
                    <CodeBlock
                      language={lang}
                      text={plainText(child.props.children)}
                      onOpenSkillUpload={onOpenSkillUpload}
                    >
                      {child.props.children}
                    </CodeBlock>
                  );
                },
                code: ({ node, children, ...props }) => {
                  const badge = matchBadge(plainText(children));
                  if (badge) return <Badge match={badge} />;
                  return (
                    <code
                      className="rounded bg-gray-100 px-1.5 py-0.5 text-[0.85em] font-mono font-normal text-gray-800 before:content-none after:content-none"
                      {...props}
                    >
                      {children}
                    </code>
                  );
                },
              }}
            >
              {content}
            </ReactMarkdown>
          </div>
        )}

        {!isUser && systemsQueried && systemsQueried.length > 0 && (
          <div className="flex gap-1.5 mt-2 pt-2 border-t border-gray-100">
            {systemsQueried.map((sys) => (
              <span
                key={sys}
                className="px-2 py-0.5 bg-gray-100 text-gray-500 text-xs rounded-full"
              >
                {sys}
              </span>
            ))}
          </div>
        )}

        {line && (
          <div className="mt-2 pt-2 border-t border-gray-100">
            <span className="px-2 py-0.5 bg-gray-100 text-gray-500 text-xs rounded-full">
              {line}
            </span>
          </div>
        )}

        {hasFindings && (
          <div className="mt-2 pt-2 border-t border-gray-100">
            <p className="text-xs font-medium text-gray-600">Review findings</p>
            <p className="mt-1 text-xs text-gray-500 whitespace-pre-wrap">
              {review!.findings}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
