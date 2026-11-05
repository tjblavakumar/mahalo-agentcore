"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Stage, ReviewSummary } from "@/types";
import { trustLine } from "@/lib/stageProgress";

interface ChatMessageProps {
  role: "user" | "assistant";
  content: string;
  systemsQueried?: string[];
  /** Authoritative pipeline stages used to derive the who-did-what trust line. */
  stages?: Stage[];
  /** Review sub-agent summary (findings) for a code turn. */
  review?: ReviewSummary;
}

export default function ChatMessage({
  role,
  content,
  systemsQueried,
  stages,
  review,
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
          <div className="prose prose-sm max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-strong:text-gray-900 prose-li:text-gray-700">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
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
                td: ({ node, ...props }) => (
                  <td
                    className="border border-gray-300 px-3 py-1.5"
                    {...props}
                  />
                ),
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
