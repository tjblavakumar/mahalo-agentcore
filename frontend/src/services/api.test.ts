import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Capture the args fetch is called with so we can assert the request carries the
// exact serialized body and the persona header.
const fetchMock = vi.fn();

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe("api client (plain fetch)", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends interrupt_id in the body on approve", async () => {
    const { api } = await import("./api");
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, message: "done" }));

    const result = await api.post("/chat/approve", {
      session_id: "sess-1",
      interrupt_id: "int-42",
      approved: true,
    });

    expect(result.error).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/chat\/approve$/);
    const sentBody = JSON.parse(options.body as string);
    expect(sentBody.interrupt_id).toBe("int-42");
    expect(sentBody.approved).toBe(true);
    expect(options.headers["Content-Type"]).toBe("application/json");
  });

  it("treats a /chat response without systems_queried as valid", async () => {
    const { api } = await import("./api");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        response: "hello",
        proposal: null,
        status: "complete",
        session_id: "sess-1",
      })
    );

    const result = await api.post<{ systems_queried?: string[]; status: string }>("/chat", {
      message: "hi",
      session_id: null,
      project_id: null,
    });

    expect(result.error).toBeNull();
    expect(result.data?.status).toBe("complete");
    expect(result.data?.systems_queried).toBeUndefined();
  });

  it("sends the X-Mahalo-Persona header when a personaId is passed", async () => {
    const { api } = await import("./api");
    fetchMock.mockResolvedValueOnce(jsonResponse({ response: "ok", status: "complete" }));

    await api.post("/chat", { message: "hi" }, "exec");

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers["X-Mahalo-Persona"]).toBe("exec");
  });

  it("omits the X-Mahalo-Persona header when no personaId is passed", async () => {
    const { api } = await import("./api");
    fetchMock.mockResolvedValueOnce(jsonResponse({ response: "ok", status: "complete" }));

    await api.post("/chat", { message: "hi" });

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers["X-Mahalo-Persona"]).toBeUndefined();
  });

  it("passes status through on success", async () => {
    const { api } = await import("./api");
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: 1 }, true, 200));
    const result = await api.get("/skills");
    expect(result.status).toBe(200);
    expect(result.code).toBeUndefined();
  });

  it("passes status and detail.code through on a skills error", async () => {
    const { api } = await import("./api");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: { code: "skill_changed", message: "changed" } }, false, 409)
    );
    const result = await api.post("/skills/run", {});
    expect(result.data).toBeNull();
    expect(result.status).toBe(409);
    expect(result.code).toBe("skill_changed");
    expect(result.error).toBe("changed");
  });

  it("sets status but no code on a request-validation 422", async () => {
    const { api } = await import("./api");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: [{ msg: "bad project" }] }, false, 422)
    );
    const result = await api.post("/skills/check", {});
    expect(result.status).toBe(422);
    expect(result.code).toBeUndefined();
  });

  it("sets status on a non-JSON failure and leaves it undefined on a thrown fetch", async () => {
    const { api } = await import("./api");
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error("not json");
      },
    } as unknown as Response);
    const failed = await api.get("/skills");
    expect(failed.status).toBe(502);
    expect(failed.error).toBe("Request failed with status 502");

    fetchMock.mockRejectedValueOnce(new Error("network down"));
    const thrown = await api.get("/skills");
    expect(thrown.status).toBeUndefined();
    expect(thrown.error).toBe("network down");
  });
});

describe("getBriefing", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("GETs /briefing with the persona header and an abort signal", async () => {
    const { getBriefing } = await import("./api");
    fetchMock.mockResolvedValueOnce(jsonResponse({ headline: "Since yesterday" }));
    const res = await getBriefing("arch");
    expect(res.data).toEqual({ headline: "Since yesterday" });
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/briefing$/);
    expect(options.method).toBe("GET");
    expect(options.headers["X-Mahalo-Persona"]).toBe("arch");
    expect(options.signal).toBeInstanceOf(AbortSignal);
  });

  it("aborts at 8 s and returns no data", async () => {
    const { getBriefing, BRIEFING_TIMEOUT_MS } = await import("./api");
    expect(BRIEFING_TIMEOUT_MS).toBe(8000);
    fetchMock.mockImplementationOnce(
      (_url: string, options: RequestInit) =>
        new Promise((_resolve, reject) => {
          options.signal?.addEventListener("abort", () => reject(new Error("aborted")));
        })
    );
    const pending = getBriefing("dev");
    await vi.advanceTimersByTimeAsync(7999);
    let settled = false;
    void pending.then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(2);
    const res = await pending;
    expect(res.data).toBeNull();
    expect(res.error).toBe("aborted");
  });

  it("aborts when the caller's signal aborts", async () => {
    const { getBriefing } = await import("./api");
    fetchMock.mockImplementationOnce(
      (_url: string, options: RequestInit) =>
        new Promise((_resolve, reject) => {
          options.signal?.addEventListener("abort", () => reject(new Error("caller aborted")));
        })
    );
    const caller = new AbortController();
    const pending = getBriefing("dev", caller.signal);
    caller.abort();
    const res = await pending;
    expect(res.data).toBeNull();
    expect(res.error).toBe("caller aborted");
  });
});
