"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Responsive, WidthProvider, type Layout, type Layouts } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import type { SavedWidget } from "@/types/viz";
import { toResponsiveLayouts } from "@/lib/dashboardWidgets";
import {
  BREAKPOINTS,
  COLS,
  ROW_HEIGHT,
  GRID_MARGIN,
  CONTAINER_PADDING,
} from "@/lib/dashboardGridConfig";
import WidgetCard from "@/components/dashboard/WidgetCard";

const ResponsiveGridLayout = WidthProvider(Responsive);

interface DashboardGridProps {
  widgets: SavedWidget[];
  /** Called with the `lg` layout array on a real (post-mount) layout change. */
  onLgLayoutChange: (lgLayout: Layout[]) => void;
  onDeleteWidget: (id: string) => void;
}

/**
 * react-grid-layout wrapper, SSR-safe under static export (design §2/§4):
 * - `mounted` flips true only after a post-mount microtask, so browser-API
 *   reads (`useCSSTransforms`) never run during the build-time prerender.
 * - `readyRef` guards the initial pre-mount `onLayoutChange` so the default
 *   layout is never auto-saved on load.
 */
export default function DashboardGrid({
  widgets,
  onLgLayoutChange,
  onDeleteWidget,
}: DashboardGridProps) {
  const [mounted, setMounted] = useState(false);
  const readyRef = useRef(false);

  useEffect(() => {
    queueMicrotask(() => {
      readyRef.current = true;
      setMounted(true);
    });
  }, []);

  const layouts: Layouts = useMemo(() => toResponsiveLayouts(widgets), [widgets]);

  function handleLayoutChange(_current: Layout[], allLayouts: Layouts) {
    // Skip the initial pre-mount event; only real user drag/resize fires after.
    if (!readyRef.current) return;
    onLgLayoutChange(allLayouts.lg ?? []);
  }

  return (
    <ResponsiveGridLayout
      className="layout"
      layouts={layouts}
      breakpoints={BREAKPOINTS}
      cols={COLS}
      rowHeight={ROW_HEIGHT}
      margin={GRID_MARGIN}
      containerPadding={CONTAINER_PADDING}
      compactType="vertical"
      draggableHandle=".widget-drag-handle"
      useCSSTransforms={mounted}
      onLayoutChange={handleLayoutChange}
    >
      {widgets.map((w) => (
        <div key={w.id}>
          <WidgetCard widget={w} onDelete={onDeleteWidget} />
        </div>
      ))}
    </ResponsiveGridLayout>
  );
}
