"use client";

interface ContextPanelProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  content: string;
  type: "story" | "document" | "pr";
}

export default function ContextPanel({
  isOpen,
  onClose,
  title,
  content,
  type,
}: ContextPanelProps) {
  if (!isOpen) return null;

  const typeIcons = { story: "📋", document: "📄", pr: "🔀" };
  const typeColors = {
    story: "border-blue-200 bg-blue-50",
    document: "border-purple-200 bg-purple-50",
    pr: "border-green-200 bg-green-50",
  };

  return (
    <div className="w-96 border-l border-gray-200 bg-white overflow-y-auto">
      <div className="sticky top-0 bg-white border-b border-gray-200 p-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span>{typeIcons[type]}</span>
          <h3 className="font-semibold text-gray-900 text-sm truncate">
            {title}
          </h3>
        </div>
        <button
          onClick={onClose}
          className="p-1 hover:bg-gray-100 rounded transition-colors"
        >
          <svg
            className="w-5 h-5 text-gray-500"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>

      <div className={`m-4 p-4 rounded-lg border ${typeColors[type]}`}>
        <pre className="text-xs text-gray-700 whitespace-pre-wrap font-mono">
          {content}
        </pre>
      </div>
    </div>
  );
}
