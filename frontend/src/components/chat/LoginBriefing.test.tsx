// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { Briefing, BriefingItem } from "@/lib/briefing";
import LoginBriefing from "./LoginBriefing";
import { useLoginBriefing } from "./useLoginBriefing";

const getBriefingMock = vi.fn();
vi.mock("@/services/api", () => ({
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

function item(over: Partial<BriefingItem> = {}): BriefingItem {
  return {
    id: "PAY-109",
    kind: "assigned",
    system: "Jira",
    line: "PAY-109 assigned to you",
    ts: "2026-11-24T20:30:00Z",
    precision: "minute",
    day_label: null,
    ref: { type: "story", id: "PAY-109", url: null },
    count: 1,
    tag: null,
    ...over,
  };
}

const LABELS = {
  Jira: "Demo data",
  ServiceNow: "Demo data",
  Confluence: "Demo data",
  "CI/CD": "Seeded demo data. Not a live pipeline run.",
  Git: "Real Gitea. One admin user; the persona appears in PR and commit titles.",
};

function briefing(over: Partial<Briefing> = {}): Briefing {
  const top = [
    item({ id: "PAY-109" }),
    item({ id: "DEP-1011", system: "ServiceNow", line: "3 x Production deploy rolled back", ref: { type: "deployment", id: "DEP-1011", url: null } }),
    item({ id: "RUN-1", system: "CI/CD", line: "Pipeline failed", ref: { type: "run", id: "RUN-1", url: null } }),
    item({
      id: "payment-service#1",
      system: "Git",
      line: "PR #1 merged in payment-service",
      precision: "day",
      day_label: "yesterday",
      ref: { type: "pr", id: "payment-service#1", url: "https://git.example.test/p/1" },
    }),
    item({ id: "ENG-005", system: "Confluence", line: "Page updated: Design", precision: "day", day_label: "today", ref: { type: "page", id: "ENG-005", url: null } }),
  ];
  return {
    persona: "dev",
    generated_at: "2026-11-24T22:30:00Z",
    mode: "recent",
    headline: "Since yesterday",
    counts: { last_24h: 7, earlier: 1 },
    top,
    items: [...top, item({ id: "PAY-110", line: "PAY-110 moved to in_review" }), item({ id: "PAY-111", line: "PAY-111 moved to done" })],
    earlier: [item({ id: "DEP-1014", system: "ServiceNow", line: "Production deploy failed", tag: "earlier", ts: "2026-11-21T18:00:00Z" })],
    snapshot: [],
    unavailable: [],
    labels: LABELS,
    ...over,
  };
}

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

function click(el: Element | null) {
  if (!el) throw new Error("element not found");
  act(() => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function buttonByText(text: string): HTMLButtonElement | null {
  return (
    (Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.startsWith(text)) as
      | HTMLButtonElement
      | undefined) ?? null
  );
}

let storage: Storage;

beforeEach(() => {
  storage = makeStorageStub();
  vi.stubGlobal("localStorage", storage);
  getBriefingMock.mockReset();
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  container?.remove();
  vi.unstubAllGlobals();
});

describe("LoginBriefing card", () => {
  it("renders the top five with source chip, id and relative time", async () => {
    await render(<LoginBriefing briefing={briefing()} onDismiss={() => {}} />);
    const rows = container.querySelectorAll('[data-testid="briefing-top"] li');
    expect(rows).toHaveLength(5);
    expect(container.textContent).toContain("Since yesterday");
    expect(rows[0].textContent).toContain("Jira");
    expect(rows[0].textContent).toContain("PAY-109");
    expect(rows[0].textContent).toContain("2 h ago");
    expect(rows[3].textContent).toContain("yesterday");
  });

  it("links https PR ids only, in a new tab with noopener", async () => {
    const b = briefing();
    b.top[3].ref.url = "https://git.example.test/p/1";
    b.top[2].ref.url = "http://insecure.example.test/x";
    await render(<LoginBriefing briefing={b} onDismiss={() => {}} />);
    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("target")).toBe("_blank");
    expect(links[0].getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("More expands to the grouped list and Less collapses it", async () => {
    await render(<LoginBriefing briefing={briefing()} onDismiss={() => {}} />);
    expect(container.querySelector('[data-testid="briefing-more"]')).toBeNull();
    const more = buttonByText("More (");
    expect(more?.textContent).toBe("More (8)");
    click(more);
    const panel = container.querySelector('[data-testid="briefing-more"]');
    expect(panel).not.toBeNull();
    expect(container.querySelector('[data-testid="briefing-group-Jira"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="briefing-group-ServiceNow"]')?.textContent).toContain("Demo data");
    expect(container.querySelector('[data-testid="briefing-group-CI/CD"]')?.textContent).toContain(
      "Seeded demo data. Not a live pipeline run."
    );
    expect(container.querySelector('[data-testid="briefing-earlier"]')?.textContent).toContain("Earlier this week");
    expect(container.querySelector('[data-testid="briefing-earlier"]')?.textContent).toContain("2026-11-21");
    click(buttonByText("Less"));
    expect(container.querySelector('[data-testid="briefing-more"]')).toBeNull();
  });

  it("dismiss calls onDismiss", async () => {
    const onDismiss = vi.fn();
    await render(<LoginBriefing briefing={briefing()} onDismiss={onDismiss} />);
    click(container.querySelector('button[aria-label="Dismiss briefing"]'));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["recent", "Since yesterday"],
    ["topped_up", "Since yesterday: 2 new in the last 24 hours"],
    ["widened", "Nothing new in the last 24 hours. Most recent activity:"],
    ["snapshot", "Quiet since yesterday. Where things stand:"],
  ] as const)("renders the %s headline", async (mode, headline) => {
    const b =
      mode === "snapshot"
        ? briefing({ mode, headline, top: [], items: [], earlier: [], snapshot: ["2 stories assigned to you"] })
        : briefing({ mode, headline });
    await render(<LoginBriefing briefing={b} onDismiss={() => {}} />);
    expect(container.querySelector("h2")?.textContent).toBe(headline);
  });

  it("snapshot mode lists the lines and has no More toggle", async () => {
    const b = briefing({
      mode: "snapshot",
      headline: "Quiet since yesterday. Where things stand:",
      top: [],
      items: [],
      earlier: [],
      snapshot: ["3 stories assigned to you: PAY-109", "0 open incidents on your services"],
    });
    await render(<LoginBriefing briefing={b} onDismiss={() => {}} />);
    expect(container.textContent).toContain("3 stories assigned to you: PAY-109");
    expect(buttonByText("More")).toBeNull();
  });

  it("topped-up items show the earlier tag with a real date", async () => {
    const b = briefing({ mode: "topped_up", top: [item({ tag: "earlier", ts: "2026-11-21T18:00:00Z" })] });
    await render(<LoginBriefing briefing={b} onDismiss={() => {}} />);
    const row = container.querySelector('[data-testid="briefing-top"] li');
    expect(row?.textContent).toContain("earlier");
    expect(row?.textContent).toContain("2026-11-21");
  });

  it("shows the unavailable notice and the data labels", async () => {
    await render(<LoginBriefing briefing={briefing({ unavailable: ["Git"] })} onDismiss={() => {}} />);
    expect(container.textContent).toContain("Git data unavailable right now");
    const labels = container.querySelector('[data-testid="briefing-labels"]')?.textContent ?? "";
    expect(labels).toContain("Jira: Demo data");
    expect(labels).toContain("CI/CD: Seeded demo data. Not a live pipeline run.");
    expect(labels).toContain("Git: Real Gitea.");
  });
});

/** Harness: renders the card the way the chat page does, driven by the hook. */
function Harness({ loginId }: { loginId: string | null }) {
  const { briefing: b, dismiss } = useLoginBriefing("dev", loginId);
  return b ? <LoginBriefing briefing={b} onDismiss={dismiss} /> : <div data-testid="empty" />;
}

async function mountHarness(loginId: string | null) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<Harness loginId={loginId} />);
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function unmountHarness() {
  await act(async () => {
    root.unmount();
  });
  container.remove();
}

describe("once per login (useLoginBriefing)", () => {
  it("fetches, shows the card and records 'shown'", async () => {
    getBriefingMock.mockResolvedValue({ data: briefing(), error: null });
    await mountHarness("login-1");
    expect(getBriefingMock).toHaveBeenCalledTimes(1);
    expect(getBriefingMock.mock.calls[0][0]).toBe("dev");
    expect(container.querySelector('[data-testid="login-briefing"]')).not.toBeNull();
    expect(JSON.parse(storage.getItem("mahalo_briefing")!)).toEqual({ loginId: "login-1", status: "shown" });
  });

  it("does not return on a later mount in the same login", async () => {
    getBriefingMock.mockResolvedValue({ data: briefing(), error: null });
    await mountHarness("login-1");
    await unmountHarness();
    getBriefingMock.mockClear();
    await mountHarness("login-1");
    expect(getBriefingMock).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="login-briefing"]')).toBeNull();
  });

  it("dismiss hides the card and persists 'dismissed'; it stays hidden after a remount", async () => {
    getBriefingMock.mockResolvedValue({ data: briefing(), error: null });
    await mountHarness("login-1");
    click(container.querySelector('button[aria-label="Dismiss briefing"]'));
    expect(container.querySelector('[data-testid="login-briefing"]')).toBeNull();
    expect(JSON.parse(storage.getItem("mahalo_briefing")!)).toEqual({ loginId: "login-1", status: "dismissed" });
    await unmountHarness();
    getBriefingMock.mockClear();
    await mountHarness("login-1");
    expect(getBriefingMock).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="login-briefing"]')).toBeNull();
  });

  it("is shown again after a new login", async () => {
    getBriefingMock.mockResolvedValue({ data: briefing(), error: null });
    await mountHarness("login-1");
    click(container.querySelector('button[aria-label="Dismiss briefing"]'));
    await unmountHarness();
    getBriefingMock.mockClear();
    await mountHarness("login-2");
    expect(getBriefingMock).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[data-testid="login-briefing"]')).not.toBeNull();
  });

  it("a fetch error renders nothing and writes no state; the next mount retries", async () => {
    getBriefingMock.mockResolvedValue({ data: null, error: "Briefing unavailable", status: 502 });
    await mountHarness("login-1");
    expect(container.querySelector('[data-testid="login-briefing"]')).toBeNull();
    expect(storage.getItem("mahalo_briefing")).toBeNull();
    await unmountHarness();
    getBriefingMock.mockResolvedValue({ data: briefing(), error: null });
    await mountHarness("login-1");
    expect(container.querySelector('[data-testid="login-briefing"]')).not.toBeNull();
  });

  it("a malformed 200 renders nothing and writes no state", async () => {
    getBriefingMock.mockResolvedValue({ data: { hello: "world" }, error: null });
    await mountHarness("login-1");
    expect(container.querySelector('[data-testid="login-briefing"]')).toBeNull();
    expect(storage.getItem("mahalo_briefing")).toBeNull();
  });

  it("a restored session without a login id never fetches", async () => {
    await mountHarness(null);
    expect(getBriefingMock).not.toHaveBeenCalled();
  });

  it("aborts the request when unmounted", async () => {
    let signal: AbortSignal | undefined;
    getBriefingMock.mockImplementation((_p: string, s: AbortSignal) => {
      signal = s;
      return new Promise(() => {});
    });
    await mountHarness("login-1");
    expect(signal?.aborted).toBe(false);
    await unmountHarness();
    expect(signal?.aborted).toBe(true);
  });
});
