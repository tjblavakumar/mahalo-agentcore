// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { PERSONAS } from "@/lib/personas";
import ChatPage from "./page";

/**
 * The login briefing must never delay or block the chat screen: while the
 * briefing request is still pending the page renders, the suggestions work and
 * the chat input is usable.
 */
const getBriefingMock = vi.fn();
const apiPostMock = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    persona: PERSONAS.dev,
    loginId: "login-1",
    isLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));
vi.mock("@/services/api", () => ({
  api: { post: (...args: unknown[]) => apiPostMock(...args) },
  checkSkill: vi.fn(),
  getModelConfig: vi.fn().mockResolvedValue({ data: null, error: "none" }),
  listSkills: vi.fn().mockResolvedValue({ data: { skills: [] }, error: null }),
  runSkill: vi.fn(),
  getSkill: vi.fn(),
  getBriefing: (...args: unknown[]) => getBriefingMock(...args),
}));

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function makeStorageStub(): Storage {
  const store = new Map<string, string>();
  return {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    get length() {
      return store.size;
    },
    key: (i: number) => Array.from(store.keys())[i] ?? null,
  } as Storage;
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.stubGlobal("localStorage", makeStorageStub());
  Element.prototype.scrollIntoView = vi.fn();
  getBriefingMock.mockReset();
  apiPostMock.mockReset();
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  container?.remove();
  vi.unstubAllGlobals();
});

async function mount() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<ChatPage />);
    await Promise.resolve();
  });
}

describe("chat page with the login briefing", () => {
  it("renders the chat while getBriefing is still pending", async () => {
    getBriefingMock.mockReturnValue(new Promise(() => {})); // never settles
    await mount();
    expect(getBriefingMock).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("How can I help you today?");
    expect(container.querySelector("textarea, input")).not.toBeNull();
    expect(container.querySelector('[data-testid="login-briefing"]')).toBeNull();
    // A suggestion still works: it posts to /chat without waiting for the briefing.
    apiPostMock.mockReturnValue(new Promise(() => {}));
    const suggestion = container.querySelector(".grid button") as HTMLButtonElement | null;
    expect(suggestion).not.toBeNull();
    await act(async () => {
      suggestion!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    expect(apiPostMock).toHaveBeenCalledTimes(1);
    expect(apiPostMock.mock.calls[0][0]).toBe("/chat");
  });

  it("renders the chat and no card when the briefing request fails", async () => {
    getBriefingMock.mockResolvedValue({ data: null, error: "boom", status: 502 });
    await mount();
    expect(container.textContent).toContain("How can I help you today?");
    expect(container.querySelector('[data-testid="login-briefing"]')).toBeNull();
  });

  it("shows the card above the welcome block once the briefing arrives", async () => {
    getBriefingMock.mockResolvedValue({
      data: {
        persona: "dev",
        generated_at: "2026-11-24T22:30:00Z",
        mode: "snapshot",
        headline: "Quiet since yesterday. Where things stand:",
        counts: { last_24h: 0, earlier: 0 },
        top: [],
        items: [],
        earlier: [],
        snapshot: ["0 open incidents on your services"],
        unavailable: [],
        labels: { Jira: "Demo data" },
      },
      error: null,
    });
    await mount();
    await act(async () => {
      await Promise.resolve();
    });
    const card = container.querySelector('[data-testid="login-briefing"]');
    expect(card).not.toBeNull();
    expect(container.textContent).toContain("How can I help you today?");
    const order = card!.compareDocumentPosition(container.querySelector("h2.text-lg")!);
    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
