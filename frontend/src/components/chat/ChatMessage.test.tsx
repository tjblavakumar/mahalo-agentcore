// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import ChatMessage from "./ChatMessage";

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

async function render(content: string, role: "user" | "assistant" = "assistant") {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<ChatMessage role={role} content={content} />);
    await Promise.resolve();
  });
}

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  container?.remove();
});

describe("ChatMessage markdown", () => {
  it("badges whole table cells, strong and inline code only", async () => {
    await render(
      [
        "| Sev | Note |",
        "| --- | --- |",
        "| P1 | P1 outage in prod |",
        "| open | the ticket is still open |",
        "",
        "Status: **resolved** and `failed`, but open issues remain.",
      ].join("\n"),
    );
    const cells = Array.from(container.querySelectorAll("td"));
    expect(cells[0].querySelector("span")?.textContent).toBe("P1");
    expect(cells[1].querySelector("span")).toBeNull();
    expect(cells[2].querySelector("span")?.textContent).toBe("Open");
    expect(cells[3].querySelector("span")).toBeNull();
    const p = container.querySelector("p")!;
    expect(Array.from(p.querySelectorAll("span")).map((s) => s.textContent)).toEqual([
      "Resolved",
      "Failed",
    ]);
    expect(p.textContent).toContain("but open issues remain");
  });

  it("renders a fenced block with language label, highlighting and copy button", async () => {
    await render("```ts\nconst open = 1;\n```");
    const block = container.querySelector("pre")!;
    expect(block.textContent).toContain("const open = 1;");
    expect(block.querySelector(".hljs-keyword")).not.toBeNull();
    expect(container.textContent).toContain("ts");
    // Fenced code is never badged.
    expect(container.querySelector("pre span.rounded-full")).toBeNull();

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const btn = container.querySelector("button")!;
    expect(btn.getAttribute("aria-label")).toBe("Copy code to clipboard");
    await act(async () => {
      btn.click();
      await Promise.resolve();
    });
    expect(writeText).toHaveBeenCalledWith("const open = 1;\n");
    expect(btn.textContent).toBe("Copied");
  });

  it("styles blockquotes as callouts and inline code as a chip", async () => {
    await render("> Heads up\n\nUse `npm test` here.");
    expect(container.querySelector("blockquote")?.className).toContain("border-l-4");
    expect(container.querySelector("p code")?.className).toContain("bg-gray-100");
  });

  it("leaves user bubbles as plain text", async () => {
    await render("**P1** `open`", "user");
    expect(container.querySelector("span.rounded-full")).toBeNull();
    expect(container.textContent).toBe("**P1** `open`");
  });
});
