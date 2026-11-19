// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import ChatInput from "./ChatInput";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

const skills = [
  { name: "JIRA_ROADMAP", description: "Propose a roadmap", builtin: true },
  { name: "JIRA_SPRINT_REPORT", description: "Sprint report", builtin: true },
];

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
  act(() => {
    root?.unmount();
  });
  container?.remove();
});

const textarea = () => container.querySelector("textarea") as HTMLTextAreaElement;

async function type(text: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
    setter.call(textarea(), text);
    textarea().dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function key(k: string, init: KeyboardEventInit = {}) {
  await act(async () => {
    textarea().dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...init }));
  });
}

describe("ChatInput", () => {
  it("sends ordinary text unchanged and never opens the picker", async () => {
    const onSend = vi.fn();
    const onSkillCommand = vi.fn();
    await render(<ChatInput onSend={onSend} disabled={false} skills={skills} onSkillCommand={onSkillCommand} />);
    await type("hello there");
    expect(container.querySelector('[role="listbox"]')).toBeNull();
    await key("Enter");
    expect(onSend).toHaveBeenCalledWith("hello there");
    expect(onSkillCommand).not.toHaveBeenCalled();
  });

  it("opens the list on / and uses only allowed ARIA attributes with no role override", async () => {
    await render(<ChatInput onSend={vi.fn()} disabled={false} skills={skills} onSkillCommand={vi.fn()} />);
    expect(textarea().hasAttribute("role")).toBe(false);
    expect(textarea().hasAttribute("aria-expanded")).toBe(false);
    expect(textarea().getAttribute("aria-label")).toBe("Message");
    expect(textarea().getAttribute("aria-autocomplete")).toBe("list");
    expect(textarea().hasAttribute("aria-controls")).toBe(false);

    await type("/");
    const list = container.querySelector('[role="listbox"]') as HTMLElement;
    expect(list).not.toBeNull();
    expect(textarea().getAttribute("aria-controls")).toBe(list.id);
    const options = container.querySelectorAll('[role="option"]');
    expect(options.length).toBe(2);
    expect(textarea().getAttribute("aria-activedescendant")).toBe(options[0].id);
    expect(options[0].getAttribute("aria-selected")).toBe("true");
    expect(options[0].textContent).toBe("JIRA_ROADMAP - Propose a roadmap");
    expect(container.querySelector('[role="status"]')?.textContent).toBe("2 skills match");
    expect(textarea().hasAttribute("role")).toBe(false);
  });

  it("moves with the arrows (wrapping) and Enter inserts the active name", async () => {
    await render(<ChatInput onSend={vi.fn()} disabled={false} skills={skills} onSkillCommand={vi.fn()} />);
    await type("/");
    await key("ArrowDown");
    expect(textarea().getAttribute("aria-activedescendant")).toBe(
      container.querySelectorAll('[role="option"]')[1].id
    );
    await key("ArrowDown");
    expect(textarea().getAttribute("aria-activedescendant")).toBe(
      container.querySelectorAll('[role="option"]')[0].id
    );
    await key("ArrowUp");
    await key("Enter");
    expect(textarea().value).toBe("/JIRA_SPRINT_REPORT ");
    // project list is now open
    expect(container.querySelectorAll('[role="option"]').length).toBe(5);
  });

  it("Tab inserts, Escape closes and ArrowDown reopens", async () => {
    await render(<ChatInput onSend={vi.fn()} disabled={false} skills={skills} onSkillCommand={vi.fn()} />);
    await type("/JIRA_ROADMAP ");
    await key("Escape");
    expect(container.querySelector('[role="listbox"]')).toBeNull();
    await key("ArrowDown");
    expect(container.querySelector('[role="listbox"]')).not.toBeNull();
    await key("Tab");
    expect(textarea().value).toBe("/JIRA_ROADMAP PAY");
    expect(container.querySelector('[role="listbox"]')).toBeNull();
  });

  it("Enter on /NAME PROJECT sends the skill command", async () => {
    const onSkillCommand = vi.fn();
    const onSend = vi.fn();
    await render(<ChatInput onSend={onSend} disabled={false} skills={skills} onSkillCommand={onSkillCommand} />);
    await type("/jira_roadmap pay");
    await key("Enter");
    expect(onSkillCommand).toHaveBeenCalledWith("JIRA_ROADMAP", "PAY");
    expect(onSend).not.toHaveBeenCalled();
    expect(textarea().value).toBe("");
  });

  it("Enter on /NAME alone sends with a null project", async () => {
    const onSkillCommand = vi.fn();
    await render(<ChatInput onSend={vi.fn()} disabled={false} skills={skills} onSkillCommand={onSkillCommand} />);
    await type("/JIRA_ROADMAP");
    await key("Enter");
    expect(onSkillCommand).toHaveBeenCalledWith("JIRA_ROADMAP", null);
  });

  it("blocks an invalid project with a message and sends nothing", async () => {
    const onSkillCommand = vi.fn();
    const onSend = vi.fn();
    await render(<ChatInput onSend={onSend} disabled={false} skills={skills} onSkillCommand={onSkillCommand} />);
    await type("/JIRA_ROADMAP XYZ");
    await key("Enter");
    expect(onSkillCommand).not.toHaveBeenCalled();
    expect(onSend).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Project must be one of PAY, CART, AUTH, PROD, ORD.");
  });

  it("blocks / messages when the skill list failed to load", async () => {
    const onSend = vi.fn();
    await render(<ChatInput onSend={onSend} disabled={false} skills={[]} skillsFailed onSkillCommand={vi.fn()} />);
    await type("/JIRA_ROADMAP");
    await key("Enter");
    expect(onSend).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Skills could not be loaded. Try again.");
  });

  it("says when no skills match", async () => {
    await render(<ChatInput onSend={vi.fn()} disabled={false} skills={skills} onSkillCommand={vi.fn()} />);
    await type("/ZZZ");
    expect(container.querySelector('[role="listbox"]')).toBeNull();
    expect(container.querySelector('[role="status"]')?.textContent).toBe("No skills match");
  });
});
