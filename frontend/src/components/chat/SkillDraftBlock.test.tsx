// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

const putSkill = vi.fn();
vi.mock("@/services/api", () => ({
  getSkill: vi.fn(),
  putSkill: (...a: unknown[]) => putSkill(...a),
  deleteSkill: vi.fn(),
}));
const downloadSkillFile = vi.fn();
vi.mock("@/lib/skills/chatBlock", async (orig) => ({
  ...(await orig<typeof import("@/lib/skills/chatBlock")>()),
  downloadSkillFile: (...a: unknown[]) => downloadSkillFile(...a),
}));

import ChatMessage from "./ChatMessage";
import SkillLibraryPanel from "./SkillLibraryPanel";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
async function render(node: React.ReactElement) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(node);
    await Promise.resolve();
  });
}
afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  putSkill.mockReset();
  downloadSkillFile.mockReset();
});
function button(label: string): HTMLButtonElement | undefined {
  return Array.from(container.querySelectorAll("button")).find((b) => b.textContent === label);
}

const file =
  "---\nname: production-issues\ndescription: Table of open incidents by project.\n---\n\n# Production issues\n\n1. Read incidents.\n";
const answer = `Here is PRODUCTION_ISSUES_SKILL.md.\n\n\`\`\`\`markdown\n${file}\`\`\`\`\n\nDownload it.`;

describe("skill file block in a chat answer", () => {
  it("shows Download and Open in upload, and hands over the file", async () => {
    const onOpen = vi.fn();
    await render(<ChatMessage role="assistant" content={answer} onOpenSkillUpload={onOpen} />);
    expect(container.textContent).toContain("PRODUCTION_ISSUES_SKILL.md");
    expect(button("Copy")).toBeDefined();
    await act(async () => {
      button("Download")!.click();
    });
    expect(downloadSkillFile).toHaveBeenCalledWith({
      filename: "PRODUCTION_ISSUES_SKILL.md",
      content: file,
    });
    await act(async () => {
      button("Open in upload")!.click();
    });
    expect(onOpen).toHaveBeenCalledWith({ filename: "PRODUCTION_ISSUES_SKILL.md", content: file });
    expect(putSkill).not.toHaveBeenCalled();
  });

  it("omits Open in upload without a handler, and adds nothing to other code blocks", async () => {
    await render(<ChatMessage role="assistant" content={answer} />);
    expect(button("Download")).toBeDefined();
    expect(button("Open in upload")).toBeUndefined();
    act(() => root.unmount());
    container.remove();
    await render(<ChatMessage role="assistant" content={"```markdown\n# Notes\n```\n\n```python\nx = 1\n```"} onOpenSkillUpload={vi.fn()} />);
    expect(button("Download")).toBeUndefined();
    expect(button("Open in upload")).toBeUndefined();
  });
});

describe("SkillLibraryPanel with a draft from chat", () => {
  const props = { skills: [], onClose: vi.fn(), onChanged: vi.fn(), onCheckSkill: vi.fn() };

  it("shows the draft as a validated pending upload and saves nothing by itself", async () => {
    await render(
      <SkillLibraryPanel {...props} initialDraft={{ filename: "PRODUCTION_ISSUES_SKILL.md", content: file }} />,
    );
    expect(container.textContent).toContain("PRODUCTION_ISSUES_SKILL.md");
    expect(container.querySelector("pre")!.textContent).toContain("# Production issues");
    expect(button("Save")!.disabled).toBe(false);
    expect(putSkill).not.toHaveBeenCalled();
  });

  it("applies the existing validation and keeps Save disabled for an invalid draft", async () => {
    await render(
      <SkillLibraryPanel {...props} initialDraft={{ filename: "PRODUCTION_ISSUES_SKILL.md", content: "no frontmatter" }} />,
    );
    expect(container.textContent).toContain("File must start with --- frontmatter.");
    expect(button("Save")!.disabled).toBe(true);
  });

  it("saves only after the user presses Save", async () => {
    putSkill.mockResolvedValue({ data: { skill: {}, created: true, warnings: [] }, error: null, status: 200 });
    await render(
      <SkillLibraryPanel {...props} initialDraft={{ filename: "PRODUCTION_ISSUES_SKILL.md", content: file }} />,
    );
    await act(async () => {
      button("Save")!.click();
      await Promise.resolve();
    });
    expect(putSkill).toHaveBeenCalledOnce();
    expect(putSkill.mock.calls[0][0]).toBe("PRODUCTION_ISSUES");
  });

  it("has no pending upload without a draft", async () => {
    await render(<SkillLibraryPanel {...props} />);
    expect(button("Save")).toBeUndefined();
  });
});
