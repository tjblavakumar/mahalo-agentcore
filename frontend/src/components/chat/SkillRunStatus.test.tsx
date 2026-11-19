// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import SkillRunStatus from "./SkillRunStatus";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  container?.remove();
  vi.useRealTimers();
});

async function render(node: React.ReactElement) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(node);
  });
}

describe("SkillRunStatus", () => {
  it("names the command, project and systems, counts seconds and hides the typical time", async () => {
    vi.useFakeTimers();
    await render(<SkillRunStatus command="JIRA_ROADMAP" project="PAY" systems={["jira", "servicenow"]} />);
    const el = container.querySelector('[role="status"]')!;
    expect(el.textContent).toBe("Running JIRA_ROADMAP for PAY. Reading Jira and ServiceNow. 0 s elapsed.");
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    expect(el.textContent).toContain("3 s elapsed");
    expect(el.textContent).not.toContain("Usually");
  });

  it("shows a typical time only when one is given", async () => {
    await render(<SkillRunStatus command="A_B" project="PAY" systems={[]} typicalSeconds={45} />);
    expect(container.textContent).toContain("Working.");
    expect(container.textContent).toContain("Usually about 45 s.");
  });
});
