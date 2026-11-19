// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import SkillCheckCard from "./SkillCheckCard";
import type { SkillCheck } from "@/lib/skills/types";
import { describeCheckError, describeFailure } from "@/lib/skills/ui";

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
  act(() => {
    root?.unmount();
  });
  container?.remove();
});

const baseCheck: SkillCheck = {
  summary: "Reports on the latest sprint.",
  steps: [
    { n: 1, text: "Read sprints", systems: ["jira"], tools: ["jira_get_sprint_info"], writes: false, est_calls: 1 },
  ],
  systems_needed: ["jira"],
  tools_needed: ["jira_get_sprint_info"],
  writes_involved: false,
  write_tools: [],
  gaps: [],
  required_arguments: [
    { name: "project", required: true, provided: true, allowed_values: ["PAY", "CART", "AUTH", "PROD", "ORD"] },
  ],
  estimated_tool_calls: 3,
  tool_call_budget: 20,
  likely_too_long: false,
  verdict: "can_do",
};

const noop = () => {};
const handlers = {
  onRun: noop,
  onCancel: noop,
  onCheckAgain: noop,
  onRunAgain: noop,
};

function button(label: string): HTMLButtonElement | undefined {
  return Array.from(container.querySelectorAll("button")).find((b) => b.textContent === label);
}

describe("SkillCheckCard verdicts", () => {
  it("shows a text verdict, steps, needs and an enabled Run for can_do", async () => {
    await render(
      <SkillCheckCard command="JIRA_SPRINT_REPORT" project="PAY" check={baseCheck} state="ready" {...handlers} />
    );
    const region = container.querySelector('[role="region"]')!;
    expect(region.getAttribute("aria-label")).toBe("Skill plan");
    expect(region.textContent).toContain("Can do");
    expect(region.textContent).toContain("Read sprints");
    expect(region.textContent).toContain("Needs: jira");
    expect(button("Run")!.disabled).toBe(false);
    expect(button("Cancel")).toBeDefined();
  });

  it("labels Run for can_do_with_changes and lists the gaps", async () => {
    const check: SkillCheck = {
      ...baseCheck,
      verdict: "can_do_with_changes",
      gaps: [
        {
          id: "g1", step: 4, kind: "unsupported_output", severity: "workable",
          description: "The skill asks for a PDF export.", workaround: "Show text in the chat.",
        },
      ],
    };
    await render(<SkillCheckCard command="X_Y" project="PAY" check={check} state="ready" {...handlers} />);
    expect(container.textContent).toContain("Can do with changes");
    expect(container.textContent).toContain("Workable");
    expect(container.textContent).toContain("Show text in the chat.");
    expect(button("Run with the changes above")!.disabled).toBe(false);
  });

  it("disables Run for cannot", async () => {
    const check: SkillCheck = {
      ...baseCheck,
      verdict: "cannot",
      gaps: [
        { id: "g1", step: null, kind: "missing_connection", severity: "blocked", description: "No Slack.", workaround: null },
      ],
    };
    await render(<SkillCheckCard command="X_Y" project="PAY" check={check} state="ready" {...handlers} />);
    expect(container.textContent).toContain("Cannot do");
    expect(container.textContent).toContain("Blocked");
    expect(button("Run")!.disabled).toBe(true);
  });

  it("requires a project choice before Run and then runs with it", async () => {
    const onRun = vi.fn();
    const check: SkillCheck = {
      ...baseCheck,
      required_arguments: [{ ...baseCheck.required_arguments[0], provided: false }],
    };
    await render(
      <SkillCheckCard command="X_Y" project={null} check={check} state="ready" {...handlers} onRun={onRun} />
    );
    expect(button("Run")!.disabled).toBe(true);
    const select = container.querySelector("select") as HTMLSelectElement;
    expect(select.options.length).toBe(6);
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
      setter.call(select, "CART");
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(button("Run")!.disabled).toBe(false);
    await act(async () => {
      button("Run")!.click();
    });
    expect(onRun).toHaveBeenCalledWith("CART");
  });

  it("shows the write notice and the too-long warning", async () => {
    const check: SkillCheck = {
      ...baseCheck,
      writes_involved: true,
      write_tools: ["jira_update_story"],
      likely_too_long: true,
      estimated_tool_calls: 22,
    };
    await render(<SkillCheckCard command="X_Y" project="PAY" check={check} state="ready" {...handlers} />);
    expect(container.textContent).toContain(
      "This skill may propose changes (jira_update_story). Each change will still ask for its own approval. Approving this plan does not approve any change."
    );
    expect(container.textContent).toContain("about 22 tool calls; the limit is 20");
  });

  it("renders skill text literally (script text is not executed or parsed)", async () => {
    const check: SkillCheck = {
      ...baseCheck,
      summary: "<script>window.__pwned = 1</script><img src=x onerror=alert(1)>",
    };
    await render(<SkillCheckCard command="X_Y" project="PAY" check={check} state="ready" {...handlers} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<script>window.__pwned = 1</script>");
  });

  it("View skill shows the content as plain text in a pre", async () => {
    const onViewSkill = vi.fn();
    await render(
      <SkillCheckCard
        command="X_Y" project="PAY" check={baseCheck} state="ready" {...handlers}
        skillContent={"![x](https://e/x.png) [a](https://e)"} onViewSkill={onViewSkill}
      />
    );
    const pre = container.querySelector("pre")!;
    expect(pre.textContent).toBe("![x](https://e/x.png) [a](https://e)");
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
  });

  it("replaces the buttons with Plan accepted or Cancelled", async () => {
    await render(<SkillCheckCard command="X_Y" project="PAY" check={baseCheck} state="accepted" {...handlers} />);
    expect(container.textContent).toContain("Plan accepted");
    expect(button("Run")).toBeUndefined();
    act(() => root.unmount());
    container.remove();
    await render(<SkillCheckCard command="X_Y" project="PAY" check={baseCheck} state="cancelled" {...handlers} />);
    expect(container.textContent).toContain("Cancelled. Nothing was run.");
    expect(button("Cancel")).toBeUndefined();
  });
});

// One case per row of the failure table (design section C).
describe("SkillCheckCard failure table", () => {
  async function renderFailure(failure: ReturnType<typeof describeFailure>, check: SkillCheck | null = null, project: string | null = "PAY") {
    const onCheckAgain = vi.fn();
    const onRunAgain = vi.fn();
    await render(
      <SkillCheckCard
        command="JIRA_ROADMAP" project={project} check={check} state="error" failure={failure}
        {...handlers} onCheckAgain={onCheckAgain} onRunAgain={onRunAgain}
      />
    );
    return { onCheckAgain, onRunAgain };
  }

  function expectNoRunOrCancel() {
    expect(button("Run")).toBeUndefined();
    expect(button("Cancel")).toBeUndefined();
  }

  it.each(["check_timeout", "check_empty", "check_invalid_output", "check_failed"])(
    "check error %s: message and Check again that resends",
    async (type) => {
      const { onCheckAgain } = await renderFailure(describeCheckError({ type, message: "The check took too long." }));
      expect(container.querySelector('[role="alert"]')!.textContent).toBe("The check took too long.");
      expectNoRunOrCancel();
      await act(async () => {
        button("Check again")!.click();
      });
      expect(onCheckAgain).toHaveBeenCalledWith("PAY");
    }
  );

  it("check bad_project: shows the selector and Check again needs a choice", async () => {
    const { onCheckAgain } = await renderFailure(
      describeCheckError({ type: "bad_project", message: "Pick a project." }), null, null
    );
    expect(container.querySelector("select")).not.toBeNull();
    expect(button("Check again")!.disabled).toBe(true);
    const select = container.querySelector("select") as HTMLSelectElement;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
      setter.call(select, "ORD");
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await act(async () => {
      button("Check again")!.click();
    });
    expect(onCheckAgain).toHaveBeenCalledWith("ORD");
  });

  it("check bad_skill: message, no controls", async () => {
    await renderFailure(describeCheckError({ type: "bad_skill", message: "The skill is not valid." }));
    expect(container.textContent).toContain("The skill is not valid.");
    expect(button("Check again")).toBeUndefined();
    expectNoRunOrCancel();
  });

  it("check 404: no longer exists, no controls", async () => {
    await renderFailure(describeFailure("check", { status: 404, code: "skill_not_found" }, false));
    expect(container.textContent).toContain("This skill no longer exists.");
    expect(button("Check again")).toBeUndefined();
  });

  it("check 422: not valid, no controls", async () => {
    await renderFailure(describeFailure("check", { status: 422 }, false));
    expect(container.textContent).toContain("The skill or project is not valid.");
    expect(button("Check again")).toBeUndefined();
  });

  it("check 502 and network error: Check again", async () => {
    await renderFailure(describeFailure("check", { status: 502 }, false));
    expect(container.textContent).toContain("The check could not be completed. Try again.");
    expect(button("Check again")).toBeDefined();
    act(() => root.unmount());
    container.remove();
    await renderFailure(describeFailure("check", {}, false));
    expect(button("Check again")).toBeDefined();
  });

  it("run 409 skill_changed: Check again", async () => {
    await renderFailure(describeFailure("run", { status: 409, code: "skill_changed" }, false), baseCheck);
    expect(container.textContent).toContain("This skill changed after the check. Check it again.");
    expect(button("Check again")).toBeDefined();
    expect(button("Run")).toBeUndefined();
  });

  it("run 404: no longer exists, no controls", async () => {
    await renderFailure(describeFailure("run", { status: 404, code: "skill_not_found" }, false), baseCheck);
    expect(container.textContent).toContain("This skill no longer exists.");
    expect(button("Check again")).toBeUndefined();
    expect(button("Run again")).toBeUndefined();
  });

  it("run 422: Check again", async () => {
    await renderFailure(describeFailure("run", { status: 422 }, false), baseCheck);
    expect(container.textContent).toContain("The run request was not valid. Check it again.");
    expect(button("Check again")).toBeDefined();
  });

  it("run 502 on a read-only skill: Run again resends", async () => {
    const { onRunAgain } = await renderFailure(describeFailure("run", { status: 502 }, false), baseCheck);
    expect(container.textContent).toContain("Nothing was changed (this skill only reads). Try again.");
    await act(async () => {
      button("Run again")!.click();
    });
    expect(onRunAgain).toHaveBeenCalledWith("PAY");
  });

  it("run failure on a write skill: approval-card message, no retry", async () => {
    await renderFailure(describeFailure("run", {}, true), { ...baseCheck, writes_involved: true, write_tools: ["jira_update_story"] });
    expect(container.textContent).toContain("The run did not finish. Check the approval cards before retrying.");
    expect(button("Run again")).toBeUndefined();
    expect(button("Check again")).toBeUndefined();
  });
});
