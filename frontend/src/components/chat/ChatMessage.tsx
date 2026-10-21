"use client";

import ReactMarkdown from "react-markdown";

interface ChatMessageProps {
  role: "user" | "assistant";
  content: string;
  systemsQueried?: string[];
}

export default function ChatMessage({ role, content, systemsQueried }: ChatMessageProps) {
  const isUser = role === "user";

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
            <ReactMarkdown>{content}</ReactMarkdown>
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
      </div>
    </div>
  );
}
