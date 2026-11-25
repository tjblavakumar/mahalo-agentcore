"use client";

import { useState } from "react";
import {
  formatDate,
  formatWhen,
  groupBySystem,
  moreCount,
  safeUrl,
  type Briefing,
  type BriefingItem,
} from "@/lib/briefing";

interface LoginBriefingProps {
  briefing: Briefing;
  onDismiss: () => void;
}

function ItemRow({ item, generatedAt }: { item: BriefingItem; generatedAt: string }) {
  const href = safeUrl(item.ref.url);
  const when = formatWhen(item, generatedAt);
  return (
    <li className="flex items-start gap-2 py-1 text-sm text-gray-800">
      <span className="mt-0.5 shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[11px] font-medium text-gray-600">
        {item.system}
      </span>
      <span className="min-w-0 flex-1">
        <span>{item.line}</span>{" "}
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono text-xs text-blue-600 hover:underline"
          >
            {item.ref.id}
          </a>
        ) : (
          <span className="font-mono text-xs text-gray-500">{item.ref.id}</span>
        )}
      </span>
      <span className="shrink-0 whitespace-nowrap text-xs text-gray-500">
        {item.tag === "earlier" ? (
          <>
            <span className="mr-1 rounded bg-amber-50 px-1 text-amber-700">earlier</span>
            {formatDate(item)}
          </>
        ) : (
          when
        )}
      </span>
    </li>
  );
}

function Groups({
  items,
  briefing,
}: {
  items: BriefingItem[];
  briefing: Briefing;
}) {
  return (
    <>
      {groupBySystem(items).map((group) => (
        <div key={group.system} className="mb-2" data-testid={`briefing-group-${group.system}`}>
          <div className="flex items-center gap-2 text-xs font-semibold text-gray-700">
            <span>{group.system}</span>
            {briefing.labels[group.system] && (
              <span className="rounded bg-gray-100 px-1.5 py-0.5 font-normal text-gray-500">
                {briefing.labels[group.system]}
              </span>
            )}
          </div>
          <ul>
            {group.items.map((item, i) => (
              <ItemRow key={`${item.id}-${i}`} item={item} generatedAt={briefing.generated_at} />
            ))}
          </ul>
        </div>
      ))}
    </>
  );
}

export default function LoginBriefing({ briefing, onDismiss }: LoginBriefingProps) {
  const [expanded, setExpanded] = useState(false);
  const more = moreCount(briefing);
  const shown = [...briefing.top, ...briefing.items, ...briefing.earlier];
  const systems = [...new Set(shown.map((i) => i.system))];
  const footerLabels =
    systems.length > 0
      ? systems.map((s) => `${s}: ${briefing.labels[s] ?? "Demo data"}`)
      : [`Jira, ServiceNow, Confluence: ${briefing.labels.Jira ?? "Demo data"}`];

  return (
    <section
      aria-label="Since yesterday"
      data-testid="login-briefing"
      className="mb-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-sm font-semibold text-gray-900">{briefing.headline}</h2>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss briefing"
          className="rounded px-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-700"
        >
          ×
        </button>
      </div>

      {briefing.mode === "snapshot" ? (
        <ul className="mt-2 list-disc pl-5 text-sm text-gray-800">
          {briefing.snapshot.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : (
        <ul className="mt-2" data-testid="briefing-top">
          {briefing.top.map((item, i) => (
            <ItemRow key={`${item.id}-${i}`} item={item} generatedAt={briefing.generated_at} />
          ))}
        </ul>
      )}

      {more > 0 && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="mt-2 text-sm font-medium text-blue-600 hover:underline"
        >
          {expanded ? "Less" : `More (${more})`}
        </button>
      )}

      {expanded && more > 0 && (
        <div className="mt-2 max-h-64 overflow-y-auto border-t border-gray-100 pt-2" data-testid="briefing-more">
          {briefing.items.length > 0 && <Groups items={briefing.items} briefing={briefing} />}
          {briefing.earlier.length > 0 && (
            <div data-testid="briefing-earlier">
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
                Earlier this week
              </div>
              <Groups items={briefing.earlier} briefing={briefing} />
            </div>
          )}
        </div>
      )}

      {briefing.unavailable.length > 0 && (
        <p className="mt-2 text-xs text-gray-500">
          {briefing.unavailable.join(", ")} data unavailable right now
        </p>
      )}
      <p className="mt-2 text-[11px] text-gray-400" data-testid="briefing-labels">
        {footerLabels.join(" · ")}
      </p>
    </section>
  );
}
