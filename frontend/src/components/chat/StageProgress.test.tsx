// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { Stage } from "@/types";
import StageProgress from "./StageProgress";
import { GENERATE_STAGE, REVIEW_STAGE } from "@/lib/stageProgress";

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

function generateStage(): Stage {
  return {
    stage: GENERATE_STAGE,
    model_id: "gen",
    model_label: "Claude Sonnet 4.5",
    status: "complete",
    fallback: null,
  };
}

function reviewStage(): Stage {
  return {
    stage: REVIEW_STAGE,
    model_id: "rev",
    model_label: "Nova Lite",
    status: "complete",
    fallback: false,
  };
}

describe("StageProgress", () => {
  it("renders the optimistic generate + review labels while pending", async () => {
    await render(
      <StageProgress
        genLabel="Claude Sonnet 4.5"
        reviewLabel="Nova Lite"
        advanceMs={100000}
      />,
    );
    expect(container.textContent).toContain("Generating with Claude Sonnet 4.5");
    expect(container.textContent).toContain("Reviewing with Nova Lite");
  });

  it("keeps both steps when the response reconciles with a review stage", async () => {
    await render(
      <StageProgress
        genLabel="Claude Sonnet 4.5"
        reviewLabel="Nova Lite"
        stages={[generateStage(), reviewStage()]}
      />,
    );
    expect(container.textContent).toContain("Generating with Claude Sonnet 4.5");
    expect(container.textContent).toContain("Reviewing with Nova Lite");
  });

  it("drops the review step when the response ran no review", async () => {
    await render(
      <StageProgress
        genLabel="Claude Sonnet 4.5"
        reviewLabel="Nova Lite"
        stages={[generateStage()]}
      />,
    );
    expect(container.textContent).toContain("Generating with Claude Sonnet 4.5");
    expect(container.textContent).not.toContain("Reviewing with Nova Lite");
  });
});
