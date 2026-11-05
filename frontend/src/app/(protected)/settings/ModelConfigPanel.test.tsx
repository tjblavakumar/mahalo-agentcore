// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  CODE_GEN_OPTION,
  REVIEW_OPTIONS,
  DEFAULT_REVIEW_OPTION,
} from "@/lib/modelConfig";

/**
 * Settings model dropdowns. We mock the api helpers so the panel's mount-load
 * and save paths run without a backend, on a real jsdom client root (mirrors
 * the AuthContext.test.tsx pattern).
 */

const getModelConfig = vi.fn();
const putModelConfig = vi.fn();

vi.mock("@/services/api", () => ({
  getModelConfig: (...args: unknown[]) => getModelConfig(...args),
  putModelConfig: (...args: unknown[]) => putModelConfig(...args),
}));

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

async function mountPanel(personaId = "dev") {
  const { default: ModelConfigPanel } = await import("./ModelConfigPanel");
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<ModelConfigPanel personaId={personaId as never} />);
    await Promise.resolve();
  });
}

beforeEach(() => {
  getModelConfig.mockReset();
  putModelConfig.mockReset();
  getModelConfig.mockResolvedValue({
    data: {
      codeGeneration: CODE_GEN_OPTION.id,
      codeReview: DEFAULT_REVIEW_OPTION.id,
      security: DEFAULT_REVIEW_OPTION.id,
    },
    error: null,
  });
  putModelConfig.mockResolvedValue({
    data: {
      codeGeneration: CODE_GEN_OPTION.id,
      codeReview: REVIEW_OPTIONS[2].id,
      security: DEFAULT_REVIEW_OPTION.id,
    },
    error: null,
  });
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  container?.remove();
  vi.restoreAllMocks();
});

function selects() {
  return {
    codeGen: container.querySelector<HTMLSelectElement>("#model-code-generation")!,
    codeReview: container.querySelector<HTMLSelectElement>("#model-code-review")!,
    security: container.querySelector<HTMLSelectElement>("#model-security")!,
  };
}

describe("ModelConfigPanel", () => {
  it("loads the active persona's config on mount", async () => {
    await mountPanel("exec");
    expect(getModelConfig).toHaveBeenCalledWith("exec");
  });

  it("renders three dropdowns", async () => {
    await mountPanel();
    const { codeGen, codeReview, security } = selects();
    expect(codeGen).toBeTruthy();
    expect(codeReview).toBeTruthy();
    expect(security).toBeTruthy();
  });

  it("code review options are exactly the review allow-list", async () => {
    await mountPanel();
    const { codeReview } = selects();
    const optionIds = Array.from(codeReview.options).map((o) => o.value);
    expect(optionIds).toEqual(REVIEW_OPTIONS.map((o) => o.id));
  });

  it("code generation select is disabled (read-only) and shows the fixed model", async () => {
    await mountPanel();
    const { codeGen } = selects();
    expect(codeGen.disabled).toBe(true);
    expect(codeGen.value).toBe(CODE_GEN_OPTION.id);
  });

  it("security shows the 'not yet active' marker", async () => {
    await mountPanel();
    expect(container.textContent).toContain("not yet active");
  });

  it("selecting a review model and saving calls putModelConfig with the chosen ids", async () => {
    await mountPanel("pm");
    const { codeReview } = selects();
    const chosen = REVIEW_OPTIONS[2].id;

    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLSelectElement.prototype,
        "value",
      )!.set!;
      setter.call(codeReview, chosen);
      codeReview.dispatchEvent(new Event("change", { bubbles: true }));
      await Promise.resolve();
    });

    const saveButton = Array.from(
      container.querySelectorAll("button"),
    ).find((b) => /save models/i.test(b.textContent ?? ""))!;

    await act(async () => {
      saveButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });

    expect(putModelConfig).toHaveBeenCalledTimes(1);
    const [sentConfig, sentPersona] = putModelConfig.mock.calls[0];
    expect(sentConfig.codeReview).toBe(chosen);
    expect(sentConfig.codeGeneration).toBe(CODE_GEN_OPTION.id);
    expect(sentPersona).toBe("pm");
  });
});
