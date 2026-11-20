// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { detectSkillBlock, downloadSkillFile } from "./chatBlock";
import { validateSkill } from "./parse";

const skill =
  "---\nname: production-issues\ndescription: Table of open incidents by project.\n---\n\n# Production issues\n\n1. Read incidents.\n";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("detectSkillBlock", () => {
  it("recognises a markdown block with frontmatter and derives the file name", () => {
    const block = detectSkillBlock("markdown", skill)!;
    expect(block.filename).toBe("PRODUCTION_ISSUES_SKILL.md");
    expect(block.content).toBe(skill);
    expect(validateSkill(block.filename, block.content).ok).toBe(true);
  });

  it("accepts the md info string, CRLF text and leading blank lines", () => {
    const block = detectSkillBlock("md", "\r\n" + skill.replace(/\n/g, "\r\n"))!;
    expect(block.filename).toBe("PRODUCTION_ISSUES_SKILL.md");
    expect(block.content).not.toContain("\r");
  });

  it("ignores other languages, no language, and markdown without a skill header", () => {
    expect(detectSkillBlock("python", skill)).toBeNull();
    expect(detectSkillBlock(undefined, skill)).toBeNull();
    expect(detectSkillBlock("markdown", "# Notes\n\n---\nname: x\n---\n")).toBeNull();
    expect(detectSkillBlock("markdown", "---\ndescription: d\n---\nbody")).toBeNull();
    expect(detectSkillBlock("markdown", "---\nname: x\nno closing fence")).toBeNull();
  });

  it("ignores a name that cannot make a valid file name", () => {
    expect(detectSkillBlock("markdown", "---\nname: x\ndescription: d\n---\nbody")).toBeNull();
    expect(detectSkillBlock("markdown", "---\nname: Bad Name!\ndescription: d\n---\nbody")).toBeNull();
  });
});

describe("downloadSkillFile", () => {
  it("saves the text as a .md file with the derived name", async () => {
    const created: Blob[] = [];
    URL.createObjectURL = vi.fn((b: Blob) => {
      created.push(b);
      return "blob:skill";
    });
    URL.revokeObjectURL = vi.fn();
    let name = "";
    let href = "";
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        name = this.download;
        href = this.href;
      });
    downloadSkillFile({ filename: "PRODUCTION_ISSUES_SKILL.md", content: skill });
    expect(click).toHaveBeenCalledOnce();
    expect(name).toBe("PRODUCTION_ISSUES_SKILL.md");
    expect(href).toBe("blob:skill");
    expect(await created[0].text()).toBe(skill);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:skill");
    expect(document.querySelector("a[download]")).toBeNull();
  });
});
