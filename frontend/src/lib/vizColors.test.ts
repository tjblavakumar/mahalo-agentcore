import { describe, it, expect } from "vitest";
import { PALETTE, colorAt, shouldVaryColors } from "./vizColors";
import type { VizSpec } from "@/types/viz";

const base = {
  title: "t",
  xKey: "x",
  series: [{ name: "A", dataKey: "a" }],
  data: [{ x: "p", a: 1 }],
};

describe("vizColors", () => {
  it("has 10 distinct colors, original six first", () => {
    expect(PALETTE).toHaveLength(10);
    expect(new Set(PALETTE).size).toBe(10);
    expect(PALETTE.slice(0, 6)).toEqual([
      "#2563eb",
      "#16a34a",
      "#d97706",
      "#dc2626",
      "#7c3aed",
      "#0891b2",
    ]);
  });

  it("colorAt wraps around", () => {
    expect(colorAt(0)).toBe(PALETTE[0]);
    expect(colorAt(10)).toBe(PALETTE[0]);
    expect(colorAt(13)).toBe(PALETTE[3]);
  });

  it("shouldVaryColors is true only for single-series bar with varyColors true", () => {
    expect(shouldVaryColors({ type: "bar", ...base, varyColors: true })).toBe(true);
    expect(shouldVaryColors({ type: "bar", ...base })).toBe(false);
    expect(shouldVaryColors({ type: "bar", ...base, varyColors: false })).toBe(false);
    expect(
      shouldVaryColors({
        type: "bar",
        ...base,
        series: [...base.series, { name: "B", dataKey: "b" }],
        varyColors: true,
      })
    ).toBe(false);
    expect(shouldVaryColors({ type: "line", ...base })).toBe(false);
    const table: VizSpec = { type: "table", title: "t", columns: [], rows: [] };
    expect(shouldVaryColors(table)).toBe(false);
  });
});
