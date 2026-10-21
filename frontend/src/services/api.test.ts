import { describe, it, expect, vi, beforeEach } from "vitest";

// Capture the args aws.fetch is called with so we can assert the signed
// request carries the exact serialized body.
const fetchMock = vi.fn();

// Mock the in-browser SigV4 signer: AwsClient.fetch just records its args and
// returns a canned JSON response (no real signing, no network).
vi.mock("aws4fetch", () => ({
  AwsClient: class {
    fetch = fetchMock;
  },
}));

// Mock the Cognito credential provider so no live AWS call is made.
vi.mock("@aws-sdk/credential-providers", () => ({
  fromCognitoIdentityPool: () =>
    vi.fn(async () => ({
      accessKeyId: "AKIA_TEST",
      secretAccessKey: "secret",
      sessionToken: "token",
      expiration: new Date(Date.now() + 3_600_000),
    })),
}));

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe("api client (SigV4)", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("sends interrupt_id in the signed body on approve", async () => {
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
    // The serialized JSON body is passed into aws.fetch so the signature covers
    // the exact bytes sent; interrupt_id must be present in it.
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
});
