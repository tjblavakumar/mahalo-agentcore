"use client";

import type { SavedWidget } from "@/types/viz";
import VizWidget from "@/components/dashboard/charts/VizWidget";

interface WidgetCardProps {
  widget: SavedWidget;
  onDelete: (id: string) => void;
}

/**
 * Card chrome for one grid widget: a header with the title, a drag handle
 * (`.widget-drag-handle`, matched by the grid's `draggableHandle`) and a delete
 * control, and a body that renders the chart/table (design §4).
 */
export default function WidgetCard({ widget, onDelete }: WidgetCardProps) {
  return (
    <div className="flex h-full flex-col rounded-lg bg-white shadow border border-gray-200 overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-gray-100 bg-gray-50">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="widget-drag-handle cursor-move text-gray-400 hover:text-gray-600 select-none"
            aria-label="Drag widget"
            title="Drag to reposition"
          >
            ⠿
          </span>
          <h3 className="truncate text-sm font-medium text-gray-800">{widget.spec.title}</h3>
        </div>
        <button
          type="button"
          onClick={() => onDelete(widget.id)}
          aria-label="Delete widget"
          title="Delete widget"
          className="shrink-0 rounded px-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
        >
          ✕
        </button>
      </div>
      <div className="flex-1 min-h-0 p-2">
        <VizWidget spec={widget.spec} />
      </div>
    </div>
  );
}
