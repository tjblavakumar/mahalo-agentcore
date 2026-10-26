/**
 * Pure widget-list + layout helpers (design §4, §7). No DOM, no side effects
 * (except crypto.randomUUID for id generation), so they carry the tested logic
 * under the `node` vitest env.
 */

import type { Layout, Layouts } from "react-grid-layout";
import type { SavedWidget, VizSpec } from "@/types/viz";
import { COLS, DEFAULT_WIDGET_W, DEFAULT_WIDGET_H } from "@/lib/dashboardGridConfig";

/** Stable short id: `w_` + an 8-char slice of a UUID. */
function newWidgetId(): string {
  return "w_" + crypto.randomUUID().replace(/-/g, "").slice(0, 8);
}

/**
 * Find the next free `lg` row for a new widget of width `w`: place it at x:0 on
 * the row below everything currently placed (simple, deterministic, and the
 * grid's vertical compaction tidies it afterwards).
 */
function nextFreeSlot(saved: SavedWidget[]): { x: number; y: number } {
  if (saved.length === 0) return { x: 0, y: 0 };
  const maxBottom = saved.reduce((max, w) => Math.max(max, w.layout.y + w.layout.h), 0);
  return { x: 0, y: maxBottom };
}

/** Append a new widget for `spec` at the next free slot with the default size. */
export function appendWidget(saved: SavedWidget[], spec: VizSpec): SavedWidget[] {
  const { x, y } = nextFreeSlot(saved);
  const widget: SavedWidget = {
    id: newWidgetId(),
    spec,
    layout: { x, y, w: DEFAULT_WIDGET_W, h: DEFAULT_WIDGET_H },
  };
  return [...saved, widget];
}

/** Remove the widget with the given id. */
export function removeWidget(saved: SavedWidget[], id: string): SavedWidget[] {
  return saved.filter((w) => w.id !== id);
}

/**
 * Merge an `lg` `Layout[]` (from `allLayouts.lg`) back into the widget set by
 * `Layout.i === SavedWidget.id`, copying `{x,y,w,h}` and preserving `spec`/`id`.
 * Widgets with no matching layout item keep their previous layout (defensive).
 */
export function applyLayoutChange(saved: SavedWidget[], lgLayout: Layout[]): SavedWidget[] {
  const byId = new Map(lgLayout.map((l) => [l.i, l]));
  return saved.map((w) => {
    const l = byId.get(w.id);
    if (!l) return w;
    return { ...w, layout: { x: l.x, y: l.y, w: l.w, h: l.h } };
  });
}

/**
 * Derive the five-breakpoint responsive `Layouts` from the stored `lg` layouts
 * (design §4): `lg === md`; `sm` clamps `w` to COLS.sm (6); `xs` -> w=COLS.xs
 * (4), x=0; `xxs` -> w=COLS.xxs (2), x=0.
 */
export function toResponsiveLayouts(saved: SavedWidget[]): Layouts {
  const lg: Layout[] = saved.map((w) => ({ i: w.id, ...w.layout }));
  return {
    lg,
    md: lg.map((it) => ({ ...it })),
    sm: lg.map((it) => ({ ...it, w: Math.min(it.w, COLS.sm) })),
    xs: lg.map((it) => ({ ...it, w: COLS.xs, x: 0 })),
    xxs: lg.map((it) => ({ ...it, w: COLS.xxs, x: 0 })),
  };
}

/**
 * True when the merged `lg` `{x,y,w,h}` set (keyed by widget id) is unchanged
 * from `saved`. Used to skip spurious autosaves from post-mount relayouts
 * (design §14 item 2). Only coordinates are compared; order is irrelevant.
 */
export function isLgLayoutUnchanged(saved: SavedWidget[], lgLayout: Layout[]): boolean {
  const byId = new Map(lgLayout.map((l) => [l.i, l]));
  // Every saved widget must have a matching layout item with identical coords.
  for (const w of saved) {
    const l = byId.get(w.id);
    if (!l) return false;
    if (l.x !== w.layout.x || l.y !== w.layout.y || l.w !== w.layout.w || l.h !== w.layout.h) {
      return false;
    }
  }
  return true;
}
