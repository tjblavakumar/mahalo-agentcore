// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";

const downloadSkillFile = vi.fn();
vi.mock("@/lib/skills/chatBlock", async (orig) => ({
  ...(await orig<typeof import("@/lib/skills/chatBlock")>()),
  downloadSkillFile: (...a: unknown[]) => downloadSkillFile(...a),
}));

import ChatMessage from "./ChatMessage";

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
  downloadSkillFile.mockReset();
});

function button(label: string): HTMLButtonElement | undefined {
  return Array.from(container.querySelectorAll("button")).find((b) => b.textContent === label);
}

const adr = "---\ndoc_type: adr\ntitle: Add crypto payments\n---\n\n# ADR\n\n## Status\nProposed\n";
const skill = "---\nname: production-issues\ndescription: Table of open incidents.\n---\n\n# Steps\n";

describe("design document block in a chat answer", () => {
  it("shows the ADR file name and a Download button, but no Open in upload", async () => {
    await render(
      <ChatMessage role="assistant" content={`Here is the ADR.\n\n\`\`\`\`markdown\n${adr}\`\`\`\`\n`} onOpenSkillUpload={vi.fn()} />,
    );
    expect(container.textContent).toContain("ADR-add-crypto-payments.md");
    expect(button("Open in upload")).toBeUndefined();
    await act(async () => {
      button("Download")!.click();
    });
    expect(downloadSkillFile).toHaveBeenCalledOnce();
    const arg = downloadSkillFile.mock.calls[0][0] as { filename: string; content: string };
    expect(arg.filename).toBe("ADR-add-crypto-payments.md");
    expect(arg.content).toBe(adr);
  });

  it("keeps skill drafts as skills and leaves plain markdown without Download", async () => {
    await render(
      <ChatMessage role="assistant" content={`\`\`\`\`markdown\n${skill}\`\`\`\`\n`} onOpenSkillUpload={vi.fn()} />,
    );
    expect(container.textContent).toContain("PRODUCTION_ISSUES_SKILL.md");
    expect(button("Download")).toBeDefined();
    expect(button("Open in upload")).toBeDefined();
    act(() => root.unmount());
    container.remove();
    await render(<ChatMessage role="assistant" content={"```markdown\n# Notes\n```\n"} />);
    expect(button("Download")).toBeUndefined();
  });
});
