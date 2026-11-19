// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi, beforeEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const getSkill = vi.fn();
const putSkill = vi.fn();
const deleteSkill = vi.fn();
vi.mock("@/services/api", () => ({
  getSkill: (...a: unknown[]) => getSkill(...a),
  putSkill: (...a: unknown[]) => putSkill(...a),
  deleteSkill: (...a: unknown[]) => deleteSkill(...a),
}));

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

beforeEach(() => {
  getSkill.mockReset();
  putSkill.mockReset();
  deleteSkill.mockReset();
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  container?.remove();
});

const summaries = [
  {
    name: "JIRA_ROADMAP", description: "Roadmap <b>bold</b>", builtin: true, size_bytes: 10,
    content_sha256: "a", updated_at: null, updated_by: null,
  },
  {
    name: "TEAM_STANDUP", description: "Standup", builtin: false, size_bytes: 10,
    content_sha256: "b", updated_at: "2026-01-01T00:00:00Z", updated_by: "pm",
  },
];

function button(label: string): HTMLButtonElement | undefined {
  return Array.from(container.querySelectorAll("button")).find((b) => b.textContent === label);
}

const goodSkill =
  "---\nname: team-standup\ndescription: Standup\n---\nList work.\n";

async function upload(filename: string, text: string) {
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  const file = new File([text], filename, { type: "text/markdown" });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  await act(async () => {
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 0));
  });
}

describe("SkillLibraryPanel", () => {
  const props = { skills: summaries, onClose: vi.fn(), onChanged: vi.fn(), onCheckSkill: vi.fn() };

  it("lists skills, tags built-ins and renders descriptions as text", async () => {
    await render(<SkillLibraryPanel {...props} />);
    expect(container.textContent).toContain("Built-in");
    expect(container.textContent).toContain("Roadmap <b>bold</b>");
    expect(container.querySelector("b")).toBeNull();
    // only user skills can be deleted
    expect(container.querySelectorAll("li").length).toBe(2);
    expect(button("Delete")).toBeDefined();
    expect(container.querySelectorAll("button").length).toBeGreaterThan(0);
  });

  it("shows a skill with a markdown image and link as plain text: no img, no a", async () => {
    getSkill.mockResolvedValue({
      data: { content: "![x](https://e/x.png)\n[a](https://e)" },
      error: null,
    });
    await render(<SkillLibraryPanel {...props} />);
    await act(async () => {
      button("View")!.click();
      await Promise.resolve();
    });
    const pre = container.querySelector("pre")!;
    expect(pre.textContent).toBe("![x](https://e/x.png)\n[a](https://e)");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
  });

  it("validates an upload, disables Save on errors and lists the messages", async () => {
    await render(<SkillLibraryPanel {...props} />);
    await upload("bad_name.md", goodSkill);
    expect(container.textContent).toContain("File name must look like SYSTEM_WHAT_SKILL.md");
    expect(button("Save")!.disabled).toBe(true);
  });

  it("saves a valid upload, refetches and offers Check this skill", async () => {
    putSkill.mockResolvedValue({ data: { skill: {}, created: true, warnings: [] }, error: null, status: 200 });
    const onChanged = vi.fn();
    const onCheckSkill = vi.fn();
    await render(<SkillLibraryPanel {...props} onChanged={onChanged} onCheckSkill={onCheckSkill} />);
    await upload("TEAM_STANDUP_SKILL.md", goodSkill);
    expect(button("Save")!.disabled).toBe(false);
    await act(async () => {
      button("Save")!.click();
      await Promise.resolve();
    });
    expect(putSkill).toHaveBeenCalledWith(
      "TEAM_STANDUP",
      { filename: "TEAM_STANDUP_SKILL.md", content: goodSkill, overwrite: false },
      undefined
    );
    expect(onChanged).toHaveBeenCalled();
    await act(async () => {
      button("Check this skill")!.click();
    });
    expect(onCheckSkill).toHaveBeenCalledWith("TEAM_STANDUP");
  });

  it("asks to replace on 409 exists and resends with overwrite", async () => {
    putSkill
      .mockResolvedValueOnce({ data: null, error: "exists", status: 409, code: "exists" })
      .mockResolvedValueOnce({ data: { skill: {}, created: false, warnings: [] }, error: null, status: 200 });
    await render(<SkillLibraryPanel {...props} />);
    await upload("TEAM_STANDUP_SKILL.md", goodSkill);
    await act(async () => {
      button("Save")!.click();
      await Promise.resolve();
    });
    expect(container.textContent).toContain("Replace the existing skill?");
    await act(async () => {
      button("Replace")!.click();
      await Promise.resolve();
    });
    expect(putSkill.mock.calls[1][1].overwrite).toBe(true);
  });

  it("deletes a user skill after a confirm", async () => {
    deleteSkill.mockResolvedValue({ data: { deleted: "TEAM_STANDUP" }, error: null, status: 200 });
    const onChanged = vi.fn();
    await render(<SkillLibraryPanel {...props} onChanged={onChanged} />);
    await act(async () => {
      button("Delete")!.click();
    });
    expect(deleteSkill).not.toHaveBeenCalled();
    await act(async () => {
      button("Confirm delete")!.click();
      await Promise.resolve();
    });
    expect(deleteSkill).toHaveBeenCalledWith("TEAM_STANDUP", undefined);
    expect(onChanged).toHaveBeenCalled();
  });
});

describe("skill components never inject HTML", () => {
  const dir = join(process.cwd(), "src", "components", "chat");
  for (const f of [
    "SkillPicker.tsx",
    "SkillCheckCard.tsx",
    "SkillRunStatus.tsx",
    "SkillLibraryPanel.tsx",
    "ChatInput.tsx",
  ]) {
    it(`${f} has no dangerouslySetInnerHTML, img or anchor`, () => {
      const src = readFileSync(join(dir, f), "utf-8");
      expect(src).not.toContain("dangerouslySetInnerHTML");
      expect(src).not.toMatch(/<img[\s>]/);
      expect(src).not.toMatch(/<a[\s>]/);
    });
  }
});
