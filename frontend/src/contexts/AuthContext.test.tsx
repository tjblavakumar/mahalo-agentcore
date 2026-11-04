// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { AuthProvider, useAuth } from "./AuthContext";
import { PERSONAS, type Persona, type PersonaId } from "@/lib/personas";

/**
 * AuthContext persistence tests. Persona persistence lives in localStorage (not
 * sessionStorage) so a persona logged in on one tab is shared with a newly
 * opened tab (and survives a browser restart). This file opts into the jsdom
 * environment so the provider's restore effect + microtask run on a real client
 * root; the lib/node tests keep the default `node` env from vitest.config.ts.
 */

// Tell React this is an act()-aware test environment (silences the
// "not configured to support act(...)" warning when flushing effects).
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const STORAGE_KEY = "mahalo_persona";

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

let localStorageStub: Storage;
let sessionStorageStub: Storage;

beforeEach(() => {
  localStorageStub = makeStorageStub();
  sessionStorageStub = makeStorageStub();
  vi.stubGlobal("localStorage", localStorageStub);
  vi.stubGlobal("sessionStorage", sessionStorageStub);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Mount the provider on a real client root, run effects, and return the hook value. */
async function mountAuth(): Promise<{ auth: ReturnType<typeof useAuth> }> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  let captured: ReturnType<typeof useAuth> | null = null;
  function Capture() {
    captured = useAuth();
    return null;
  }
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <AuthProvider>
        <Capture />
      </AuthProvider>,
    );
    // Flush the restore microtask so its setIsLoading(false) settles in act().
    await Promise.resolve();
  });
  if (!captured) throw new Error("context was not captured");
  // `login`/`logout` are stable useCallback refs, so the captured value stays
  // usable across the re-renders those calls trigger.
  return { auth: captured };
}

/** Mount a fresh provider, flush its restore microtask, and return the restored persona. */
async function mountAndRestore(): Promise<Persona | null> {
  const { auth } = await mountAuth();
  return auth.persona;
}

describe("AuthContext persona persistence", () => {
  it("login writes the persona id to localStorage (not sessionStorage)", async () => {
    const { auth } = await mountAuth();
    let err: string | null = "unset";
    act(() => {
      err = auth.login("pm", "pm123");
    });
    expect(err).toBeNull();
    expect(localStorageStub.getItem(STORAGE_KEY)).toBe("pm");
    expect(sessionStorageStub.getItem(STORAGE_KEY)).toBeNull();
  });

  it("login rejects bad credentials and writes nothing", async () => {
    const { auth } = await mountAuth();
    let err: string | null = null;
    act(() => {
      err = auth.login("pm", "wrong");
    });
    expect(err).toBe("Invalid credentials");
    expect(localStorageStub.getItem(STORAGE_KEY)).toBeNull();
  });

  it("restoreSession reads the persona from localStorage and hydrates state", async () => {
    // A prior tab logged in: the persona id now lives in (shared) localStorage.
    const { auth } = await mountAuth();
    act(() => {
      expect(auth.login("exec", "exec123")).toBeNull();
    });
    expect(localStorageStub.getItem(STORAGE_KEY)).toBe("exec");

    // A newly opened tab shares the same localStorage but has empty per-tab
    // sessionStorage. A fresh provider restores the persona from localStorage.
    const localGet = vi.spyOn(localStorageStub, "getItem");
    const sessionGet = vi.spyOn(sessionStorageStub, "getItem");

    const persona = await mountAndRestore();

    expect(persona?.personaId).toBe("exec");
    expect(PERSONAS["exec" as PersonaId].personaId).toBe("exec");
    // The read source is localStorage; per-tab sessionStorage is never read.
    expect(localGet).toHaveBeenCalledWith(STORAGE_KEY);
    expect(sessionGet).not.toHaveBeenCalled();
  });

  it("logout clears the persona from localStorage", async () => {
    const { auth } = await mountAuth();
    act(() => {
      auth.login("dev", "dev123");
    });
    expect(localStorageStub.getItem(STORAGE_KEY)).toBe("dev");
    act(() => {
      auth.logout();
    });
    expect(localStorageStub.getItem(STORAGE_KEY)).toBeNull();
  });
});
