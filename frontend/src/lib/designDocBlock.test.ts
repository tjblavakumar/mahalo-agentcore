import { describe, it, expect } from "vitest";
import { detectDocBlock } from "./designDocBlock";
import { detectSkillBlock } from "./skills/chatBlock";

const adr = "---\ndoc_type: adr\ntitle: Add crypto payments\n---\n# ADR\n\n## Status\nProposed\n";

describe("detectDocBlock", () => {
  it("names an ADR file from the title slug and keeps the text", () => {
    expect(detectDocBlock("markdown", adr)).toEqual({ filename: "ADR-add-crypto-payments.md", content: adr });
  });

  it("uses DESIGN and DESIGN-REVIEW prefixes, case-insensitive type and language", () => {
    expect(detectDocBlock("MD", "---\ndoc_type: Design\ntitle: Cart split\n---\nx\n")?.filename).toBe("DESIGN-cart-split.md");
    expect(detectDocBlock("md", "---\ndoc_type: design-review\ntitle: PAY-109\n---\nx\n")?.filename).toBe(
      "DESIGN-REVIEW-pay-109.md",
    );
  });

  it("accepts a colon inside the title", () => {
    expect(detectDocBlock("markdown", "---\ndoc_type: adr\ntitle: Payments: crypto\n---\nx\n")?.filename).toBe(
      "ADR-payments-crypto.md",
    );
  });

  it("falls back to untitled and caps the slug length", () => {
    expect(detectDocBlock("markdown", "---\ndoc_type: adr\n---\nx\n")?.filename).toBe("ADR-untitled.md");
    const long = detectDocBlock("markdown", `---\ndoc_type: adr\ntitle: ${"a".repeat(100)}\n---\nx\n`)!;
    expect(long.filename).toBe(`ADR-${"a".repeat(60)}.md`);
    expect(long.filename).toMatch(/^[A-Za-z0-9.-]+$/);
  });

  it("returns null for other languages, missing frontmatter or an unknown doc_type", () => {
    expect(detectDocBlock("python", adr)).toBeNull();
    expect(detectDocBlock(undefined, adr)).toBeNull();
    expect(detectDocBlock("markdown", "# Notes\n")).toBeNull();
    expect(detectDocBlock("markdown", "---\ndoc_type: adr\ntitle: x\n")).toBeNull();
    expect(detectDocBlock("markdown", "---\ndoc_type: memo\ntitle: x\n---\nx\n")).toBeNull();
    expect(detectDocBlock("markdown", "---\ntitle: x\n---\nx\n")).toBeNull();
  });

  it("classifies a block with a name key as a skill, never as a doc", () => {
    const text = "---\nname: my-skill\ndescription: d\ndoc_type: adr\ntitle: t\n---\nSteps\n";
    expect(detectSkillBlock("markdown", text)).not.toBeNull();
    expect(detectDocBlock("markdown", text)).toBeNull();
  });

  it("does not classify a normal design doc as a skill", () => {
    expect(detectSkillBlock("markdown", adr)).toBeNull();
  });
});
