/**
 * Smart BI Agent — API Client Tests
 *
 * Covers:
 *   - Bearer token injection
 *   - 401 interception + automatic token refresh + retry
 *   - Error envelope parsing
 *   - 204 no-content handling
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ApiRequestError, bindAuthFunctions, api } from "@/lib/api";

// ─── Mock fetch globally ─────────────────────────────────────────────────────

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

// ─── Helpers ─────────────────────────────────────────────────────────────────

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "content-type": "application/json", ...headers }),
    json: () => Promise.resolve(body),
    blob: () => Promise.resolve(new Blob()),
  } as unknown as Response;
}

// ─── Setup ───────────────────────────────────────────────────────────────────

let mockToken: string | null = "test-access-token";
const mockRefresh = vi.fn().mockResolvedValue(true);
const mockLogout = vi.fn();

beforeEach(() => {
  mockToken = "test-access-token";
  fetchMock.mockReset();
  mockRefresh.mockReset().mockResolvedValue(true);
  mockLogout.mockReset();

  bindAuthFunctions({
    getToken: () => mockToken,
    getPreTotpToken: () => null,
    refresh: mockRefresh,
    logout: mockLogout,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ─── Tests ───────────────────────────────────────────────────────────────────

describe("api.get", () => {
  it("injects Bearer token in Authorization header", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    await api.get("/connections/");

    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/connections/");
    expect(opts.headers.Authorization).toBe("Bearer test-access-token");
  });

  it("omits Authorization header when no token", async () => {
    mockToken = null;
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    await api.get("/health");

    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.headers.Authorization).toBeUndefined();
  });

  it("always includes credentials: include for cookie refresh", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}));

    await api.get("/anything");

    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.credentials).toBe("include");
  });
});

describe("401 auto-retry", () => {
  it("refreshes token and retries on 401", async () => {
    // First call → 401
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, { error: { code: "UNAUTHORIZED", message: "Expired" } })
    );
    // After refresh → success
    mockToken = "new-token";
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { data: "ok" }));

    const result = await api.get<{ data: string }>("/schema/");

    expect(mockRefresh).toHaveBeenCalledOnce();
    expect(result.data).toBe("ok");
    // Second call should use new token
    const [, retryOpts] = fetchMock.mock.calls[1];
    expect(retryOpts.headers.Authorization).toBe("Bearer new-token");
  });

  it("calls logout when refresh fails", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, { error: { code: "UNAUTHORIZED", message: "Bad" } })
    );
    mockRefresh.mockResolvedValueOnce(false);

    await expect(api.get("/protected")).rejects.toThrow(ApiRequestError);
    expect(mockLogout).toHaveBeenCalledOnce();
  });

  it("does not retry infinitely (skipRetry on second attempt)", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(401, { error: { code: "UNAUTHORIZED", message: "Bad" } })
    );
    mockRefresh.mockResolvedValue(true);

    await expect(api.get("/loop")).rejects.toThrow(ApiRequestError);

    // Should have called fetch exactly 2 times (original + 1 retry)
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("error parsing", () => {
  it("parses structured error envelope", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(422, {
        error: {
          code: "VALIDATION_ERROR",
          message: "Invalid email format",
          fields: [{ field: "email", issue: "not a valid email" }],
        },
      })
    );

    try {
      await api.post("/auth/register", { email: "bad" });
      expect.fail("Should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiRequestError);
      const apiErr = err as ApiRequestError;
      expect(apiErr.code).toBe("VALIDATION_ERROR");
      expect(apiErr.status).toBe(422);
      expect(apiErr.fields).toHaveLength(1);
    }
  });

  it("handles non-JSON error responses", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 502,
      headers: new Headers(),
      json: () => Promise.reject(new Error("not json")),
    } as unknown as Response);

    await expect(api.get("/bad-gateway")).rejects.toThrow(/502/);
  });
});

describe("204 no-content", () => {
  it("returns undefined for 204 responses", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 204,
      headers: new Headers({ "content-length": "0" }),
      json: () => Promise.reject(new Error("no body")),
    } as unknown as Response);

    const result = await api.delete("/users/123");
    expect(result).toBeUndefined();
  });
});

describe("api.post", () => {
  it("sends JSON body with correct content-type", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(201, { id: "abc" }));

    await api.post("/connections/", { host: "db.example.com", port: 5432 });

    const [, opts] = fetchMock.mock.calls[0];
    expect(opts.method).toBe("POST");
    expect(opts.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(opts.body)).toEqual({ host: "db.example.com", port: 5432 });
  });
});
