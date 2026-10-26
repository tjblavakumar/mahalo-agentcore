import { describe, it, expect } from "vitest";
import { parseVizEnvelope } from "./vizEnvelope";

function reasonOf(raw: string): string {
  const r = parseVizEnvelope(raw);
  return r.ok ? "OK" : r.reason;
}

describe("parseVizEnvelope — happy paths", () => {
  it("accepts a line chart", () => {
    const r = parseVizEnvelope(
      JSON.stringify({
        type: "line",
        title: "Story points by sprint",
        xKey: "sprint",
        series: [{ name: "Completed", dataKey: "completed" }],
        data: [{ sprint: "S-21", completed: 34 }],
      })
    );
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.spec.type).toBe("line");
  });

  it("accepts an area chart", () => {
    const r = parseVizEnvelope(
      JSON.stringify({
        type: "area",
        title: "Cumulative flow",
        xKey: "day",
        series: [{ name: "Done", dataKey: "done" }],
        data: [{ day: "Mon", done: 3 }],
      })
    );
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.spec.type).toBe("area");
  });

  it("accepts a bar chart with multiple series", () => {
    const r = parseVizEnvelope(
      JSON.stringify({
        type: "bar",
        title: "Committed vs completed",
        xKey: "sprint",
        series: [
          { name: "Committed", dataKey: "committed" },
          { name: "Completed", dataKey: "completed" },
        ],
        data: [{ sprint: "S-21", committed: 40, completed: 34 }],
      })
    );
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.spec.type).toBe("bar");
  });

  it("accepts a table", () => {
    const r = parseVizEnvelope(
      JSON.stringify({
        type: "table",
        title: "My open PRs",
        columns: [
          { key: "repo", label: "Repository" },
          { key: "status", label: "Status" },
        ],
        rows: [{ repo: "payment-service", status: "open" }],
      })
    );
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.spec.type).toBe("table");
  });

  it("accepts an empty-rows table (no open PRs is legitimate)", () => {
    const r = parseVizEnvelope(
      JSON.stringify({
        type: "table",
        title: "My open PRs",
        columns: [{ key: "repo", label: "Repository" }],
        rows: [],
      })
    );
    expect(r.ok).toBe(true);
  });

  it("accepts null values in chart data rows", () => {
    const r = parseVizEnvelope(
      JSON.stringify({
        type: "line",
        title: "Gaps allowed",
        xKey: "x",
        series: [{ name: "Y", dataKey: "y" }],
        data: [{ x: "a", y: null }],
      })
    );
    expect(r.ok).toBe(true);
  });
});

describe("parseVizEnvelope — fence stripping", () => {
  it("strips a ```json fenced wrapper", () => {
    const inner = JSON.stringify({
      type: "bar",
      title: "Fenced",
      xKey: "k",
      series: [{ name: "V", dataKey: "v" }],
      data: [{ k: "a", v: 1 }],
    });
    const r = parseVizEnvelope("```json\n" + inner + "\n```");
    expect(r.ok).toBe(true);
  });

  it("strips a bare ``` fence", () => {
    const inner = JSON.stringify({
      type: "table",
      title: "Fenced table",
      columns: [{ key: "a", label: "A" }],
      rows: [{ a: "x" }],
    });
    const r = parseVizEnvelope("```\n" + inner + "\n```");
    expect(r.ok).toBe(true);
  });
});

describe("parseVizEnvelope — reject reasons", () => {
  it("not-json for non-JSON input", () => {
    expect(reasonOf("here is your chart: not json")).toBe("not-json");
  });

  it("unknown-type for a disallowed type", () => {
    expect(reasonOf(JSON.stringify({ type: "pie", title: "x" }))).toBe("unknown-type");
  });

  it("unknown-type for a non-object JSON value", () => {
    expect(reasonOf(JSON.stringify([1, 2, 3]))).toBe("unknown-type");
  });

  it("declined for the agent's {\"type\":\"none\"} clean decline", () => {
    expect(reasonOf(JSON.stringify({ type: "none" }))).toBe("declined");
  });

  it("missing-field for a blank title", () => {
    expect(
      reasonOf(
        JSON.stringify({
          type: "line",
          title: "   ",
          xKey: "x",
          series: [{ name: "Y", dataKey: "y" }],
          data: [{ x: "a", y: 1 }],
        })
      )
    ).toBe("missing-field");
  });

  it("missing-field when a series dataKey is absent from the first row", () => {
    expect(
      reasonOf(
        JSON.stringify({
          type: "bar",
          title: "Mismatch",
          xKey: "x",
          series: [{ name: "Y", dataKey: "missing" }],
          data: [{ x: "a", y: 1 }],
        })
      )
    ).toBe("missing-field");
  });

  it("empty-series for an empty series array", () => {
    expect(
      reasonOf(
        JSON.stringify({
          type: "line",
          title: "No series",
          xKey: "x",
          series: [],
          data: [{ x: "a" }],
        })
      )
    ).toBe("empty-series");
  });

  it("empty-data for an empty chart data array", () => {
    expect(
      reasonOf(
        JSON.stringify({
          type: "line",
          title: "No data",
          xKey: "x",
          series: [{ name: "Y", dataKey: "y" }],
          data: [],
        })
      )
    ).toBe("empty-data");
  });

  it("row-shape for a nested value in a data row", () => {
    expect(
      reasonOf(
        JSON.stringify({
          type: "line",
          title: "Nested",
          xKey: "x",
          series: [{ name: "Y", dataKey: "y" }],
          data: [{ x: "a", y: { nested: 1 } }],
        })
      )
    ).toBe("row-shape");
  });

  it("too-large for a chart with more than 100 data rows", () => {
    const data = Array.from({ length: 101 }, (_, i) => ({ x: `r${i}`, y: i }));
    expect(
      reasonOf(
        JSON.stringify({
          type: "line",
          title: "Too much",
          xKey: "x",
          series: [{ name: "Y", dataKey: "y" }],
          data,
        })
      )
    ).toBe("too-large");
  });
});

describe("parseVizEnvelope — boundaries", () => {
  it("accepts exactly 100 data rows", () => {
    const data = Array.from({ length: 100 }, (_, i) => ({ x: `r${i}`, y: i }));
    const r = parseVizEnvelope(
      JSON.stringify({
        type: "line",
        title: "At limit",
        xKey: "x",
        series: [{ name: "Y", dataKey: "y" }],
        data,
      })
    );
    expect(r.ok).toBe(true);
  });

  it("accepts exactly 6 series", () => {
    const series = Array.from({ length: 6 }, (_, i) => ({ name: `S${i}`, dataKey: `s${i}` }));
    const row: Record<string, number | string> = { x: "a" };
    series.forEach((s) => (row[s.dataKey] = 1));
    const r = parseVizEnvelope(
      JSON.stringify({ type: "bar", title: "Six", xKey: "x", series, data: [row] })
    );
    expect(r.ok).toBe(true);
  });

  it("rejects 7 series as too-large", () => {
    const series = Array.from({ length: 7 }, (_, i) => ({ name: `S${i}`, dataKey: `s${i}` }));
    const row: Record<string, number | string> = { x: "a" };
    series.forEach((s) => (row[s.dataKey] = 1));
    expect(
      reasonOf(JSON.stringify({ type: "bar", title: "Seven", xKey: "x", series, data: [row] }))
    ).toBe("too-large");
  });

  it("accepts exactly 200 table rows and rejects 201", () => {
    const columns = [{ key: "a", label: "A" }];
    const ok = parseVizEnvelope(
      JSON.stringify({
        type: "table",
        title: "200",
        columns,
        rows: Array.from({ length: 200 }, (_, i) => ({ a: i })),
      })
    );
    expect(ok.ok).toBe(true);
    expect(
      reasonOf(
        JSON.stringify({
          type: "table",
          title: "201",
          columns,
          rows: Array.from({ length: 201 }, (_, i) => ({ a: i })),
        })
      )
    ).toBe("too-large");
  });

  it("accepts exactly 12 columns and rejects 13", () => {
    const cols12 = Array.from({ length: 12 }, (_, i) => ({ key: `c${i}`, label: `C${i}` }));
    const ok = parseVizEnvelope(
      JSON.stringify({ type: "table", title: "12 cols", columns: cols12, rows: [] })
    );
    expect(ok.ok).toBe(true);
    const cols13 = Array.from({ length: 13 }, (_, i) => ({ key: `c${i}`, label: `C${i}` }));
    expect(
      reasonOf(JSON.stringify({ type: "table", title: "13 cols", columns: cols13, rows: [] }))
    ).toBe("too-large");
  });
});
