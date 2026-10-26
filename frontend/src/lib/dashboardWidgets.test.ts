import { describe, it, expect } from "vitest";
import type { Layout } from "react-grid-layout";
import type { SavedWidget, VizSpec } from "@/types/viz";
import {
  appendWidget,
  removeWidget,
  applyLayoutChange,
  toResponsiveLayouts,
  isLgLayoutUnchanged,
} from "./dashboardWidgets";

const barSpec: VizSpec = {
  type: "bar",
  title: "Health",
  xKey: "project",
  series: [{ name: "Health", dataKey: "health" }],
  data: [{ project: "PAY", health: 82 }],
};

function widget(id: string, layout: SavedWidget["layout"]): SavedWidget {
  return { id, spec: barSpec, layout };
}

describe("appendWidget", () => {
  it("places the first widget at origin with the default size", () => {
    const out = appendWidget([], barSpec);
    expect(out).toHaveLength(1);
    expect(out[0].layout).toEqual({ x: 0, y: 0, w: 6, h: 8 });
    expect(out[0].spec).toBe(barSpec);
  });

  it("assigns a unique id prefixed with w_", () => {
    const out = appendWidget([], barSpec);
    expect(out[0].id).toMatch(/^w_[0-9a-f]{8}$/);
    const two = appendWidget(out, barSpec);
    expect(two[1].id).not.toBe(two[0].id);
  });

  it("places a new widget below existing ones", () => {
    const existing = [widget("w_1", { x: 0, y: 0, w: 6, h: 8 })];
    const out = appendWidget(existing, barSpec);
    expect(out[1].layout.y).toBe(8);
    expect(out[1].layout.x).toBe(0);
  });
});

describe("removeWidget", () => {
  it("removes by id and leaves others intact", () => {
    const saved = [widget("w_1", { x: 0, y: 0, w: 6, h: 8 }), widget("w_2", { x: 6, y: 0, w: 6, h: 8 })];
    const out = removeWidget(saved, "w_1");
    expect(out.map((w) => w.id)).toEqual(["w_2"]);
  });

  it("is a no-op for an unknown id", () => {
    const saved = [widget("w_1", { x: 0, y: 0, w: 6, h: 8 })];
    expect(removeWidget(saved, "nope")).toHaveLength(1);
  });
});

describe("applyLayoutChange", () => {
  it("merges lg coords by i===id and preserves spec/id", () => {
    const saved = [widget("w_1", { x: 0, y: 0, w: 6, h: 8 })];
    const lg: Layout[] = [{ i: "w_1", x: 3, y: 2, w: 4, h: 10 }];
    const out = applyLayoutChange(saved, lg);
    expect(out[0].layout).toEqual({ x: 3, y: 2, w: 4, h: 10 });
    expect(out[0].id).toBe("w_1");
    expect(out[0].spec).toBe(barSpec);
  });

  it("leaves a widget untouched when no matching layout item exists", () => {
    const saved = [widget("w_1", { x: 0, y: 0, w: 6, h: 8 })];
    const out = applyLayoutChange(saved, [{ i: "other", x: 1, y: 1, w: 2, h: 2 }]);
    expect(out[0].layout).toEqual({ x: 0, y: 0, w: 6, h: 8 });
  });
});

describe("toResponsiveLayouts", () => {
  it("derives the five breakpoints from lg per the design math", () => {
    const saved = [widget("w_1", { x: 8, y: 0, w: 8, h: 8 })];
    const layouts = toResponsiveLayouts(saved);

    expect(layouts.lg).toEqual([{ i: "w_1", x: 8, y: 0, w: 8, h: 8 }]);
    // md === lg
    expect(layouts.md).toEqual(layouts.lg);
    // sm clamps w to 6
    expect(layouts.sm[0].w).toBe(6);
    expect(layouts.sm[0].x).toBe(8);
    // xs -> w 4, x 0
    expect(layouts.xs[0]).toEqual({ i: "w_1", x: 0, y: 0, w: 4, h: 8 });
    // xxs -> w 2, x 0
    expect(layouts.xxs[0]).toEqual({ i: "w_1", x: 0, y: 0, w: 2, h: 8 });
  });

  it("does not clamp sm width when it already fits in 6 cols", () => {
    const saved = [widget("w_1", { x: 0, y: 0, w: 4, h: 8 })];
    expect(toResponsiveLayouts(saved).sm[0].w).toBe(4);
  });
});

describe("isLgLayoutUnchanged", () => {
  it("returns true when coords match exactly", () => {
    const saved = [widget("w_1", { x: 0, y: 0, w: 6, h: 8 })];
    const lg: Layout[] = [{ i: "w_1", x: 0, y: 0, w: 6, h: 8 }];
    expect(isLgLayoutUnchanged(saved, lg)).toBe(true);
  });

  it("ignores order and extra layout fields", () => {
    const saved = [
      widget("w_1", { x: 0, y: 0, w: 6, h: 8 }),
      widget("w_2", { x: 6, y: 0, w: 6, h: 8 }),
    ];
    const lg: Layout[] = [
      { i: "w_2", x: 6, y: 0, w: 6, h: 8, moved: false },
      { i: "w_1", x: 0, y: 0, w: 6, h: 8, static: false },
    ];
    expect(isLgLayoutUnchanged(saved, lg)).toBe(true);
  });

  it("returns false when a coordinate differs", () => {
    const saved = [widget("w_1", { x: 0, y: 0, w: 6, h: 8 })];
    const lg: Layout[] = [{ i: "w_1", x: 1, y: 0, w: 6, h: 8 }];
    expect(isLgLayoutUnchanged(saved, lg)).toBe(false);
  });

  it("returns false when a widget has no matching layout item", () => {
    const saved = [widget("w_1", { x: 0, y: 0, w: 6, h: 8 })];
    expect(isLgLayoutUnchanged(saved, [])).toBe(false);
  });
});
