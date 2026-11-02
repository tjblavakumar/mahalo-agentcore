import { describe, expect, it } from "vitest";
import { classifyParam } from "./proposalParams";

describe("classifyParam", () => {
  it("detects files with line counts", () => {
    const v = classifyParam([
      { path: "a.py", content: "x\ny\nz" },
      { path: "b.py", content: "one" },
    ]);
    expect(v).toEqual({
      kind: "files",
      files: [
        { path: "a.py", content: "x\ny\nz", lineCount: 3 },
        { path: "b.py", content: "one", lineCount: 1 },
      ],
    });
  });

  it("treats empty content as zero lines", () => {
    const v = classifyParam([{ path: "empty.txt", content: "" }]);
    expect(v).toEqual({
      kind: "files",
      files: [{ path: "empty.txt", content: "", lineCount: 0 }],
    });
  });

  it("falls back to json for mixed or invalid arrays", () => {
    expect(classifyParam([{ path: "a", content: "b" }, "str"]).kind).toBe("json");
    expect(classifyParam([{ path: "a" }]).kind).toBe("json");
    expect(classifyParam([{ path: 1, content: "b" }]).kind).toBe("json");
    expect(classifyParam([]).kind).toBe("json");
  });

  it("pretty prints plain objects as json", () => {
    expect(classifyParam({ a: 1 })).toEqual({
      kind: "json",
      text: '{\n  "a": 1\n}',
    });
  });

  it("renders primitives as text", () => {
    expect(classifyParam("hi")).toEqual({ kind: "text", text: "hi" });
    expect(classifyParam(5)).toEqual({ kind: "text", text: "5" });
    expect(classifyParam(true)).toEqual({ kind: "text", text: "true" });
  });
});
