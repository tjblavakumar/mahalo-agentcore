import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import ChartRenderer from "./ChartRenderer";
import type { ChartSpec } from "@/types/viz";

/**
 * ChartRenderer smoke tests. The vitest env is `node` (no jsdom), so we render
 * to static markup via react-dom/server: the goal is "renders without throwing"
 * and that recharts' ResponsiveContainer wrapper is emitted for every chart
 * type (vertical bar, horizontal bar, line, area, pie).
 */

function render(spec: ChartSpec): string {
  return renderToStaticMarkup(<ChartRenderer spec={spec} />);
}

const chartBase = {
  title: "t",
  xKey: "project",
  series: [{ name: "Stories", dataKey: "count" }],
  data: [
    { project: "PAY", count: 3 },
    { project: "AUTH", count: 5 },
  ],
};

describe("ChartRenderer", () => {
  it("renders a vertical bar chart (default orientation) without throwing", () => {
    const html = render({ type: "bar", ...chartBase });
    expect(html).toContain("recharts-responsive-container");
  });

  it("renders an explicit vertical bar chart without throwing", () => {
    const html = render({ type: "bar", ...chartBase, orientation: "vertical" });
    expect(html).toContain("recharts-responsive-container");
  });

  it("renders a varyColors single-series bar without throwing", () => {
    const html = render({ type: "bar", ...chartBase, varyColors: true });
    expect(html).toContain("recharts-responsive-container");
  });

  it("renders a horizontal bar chart without throwing", () => {
    const html = render({ type: "bar", ...chartBase, orientation: "horizontal" });
    expect(html).toContain("recharts-responsive-container");
  });

  it("renders a line chart without throwing", () => {
    const html = render({ type: "line", ...chartBase });
    expect(html).toContain("recharts-responsive-container");
  });

  it("renders an area chart without throwing", () => {
    const html = render({ type: "area", ...chartBase });
    expect(html).toContain("recharts-responsive-container");
  });

  it("renders a pie chart without throwing", () => {
    const html = render({
      type: "pie",
      title: "Issue composition",
      xKey: "type",
      series: [{ name: "Count", dataKey: "count" }],
      data: [
        { type: "Bug", count: 7 },
        { type: "Story", count: 12 },
      ],
    });
    expect(html).toContain("recharts-responsive-container");
  });
});
