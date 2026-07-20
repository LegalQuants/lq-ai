/**
 * Tests for `services/apiClient.ts`. Mocks `authenticatedFetch` (the
 * transport primitive this module wraps) rather than `global.fetch`
 * directly — `authenticatedFetch` already has its own test coverage in
 * `taskpane/__tests__/auth.test.ts`.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/taskpane/auth", () => ({
  authenticatedFetch: vi.fn(),
}));

import { authenticatedFetch } from "@/taskpane/auth";
import { apiRequest, apiStreamRequest, ApiError } from "@/services/apiClient";

const mockedFetch = vi.mocked(authenticatedFetch);

describe("apiRequest", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it("returns parsed JSON on success", async () => {
    mockedFetch.mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    const result = await apiRequest<{ ok: boolean }>("/skills");
    expect(result).toEqual({ ok: true });
  });

  it("returns undefined on 204", async () => {
    mockedFetch.mockResolvedValue(new Response(null, { status: 204 }));
    const result = await apiRequest("/chats/1");
    expect(result).toBeUndefined();
  });

  it("throws ApiError with the string detail on failure", async () => {
    mockedFetch.mockResolvedValue(
      new Response(JSON.stringify({ detail: "not found" }), { status: 404 })
    );
    await expect(apiRequest("/skills/missing")).rejects.toMatchObject({
      status: 404,
      message: "not found",
    });
  });

  it("throws ApiError with the structured detail on failure", async () => {
    mockedFetch.mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "locked", message: "MFA required" } }), {
        status: 423,
      })
    );
    await expect(apiRequest("/auth/login")).rejects.toMatchObject({
      status: 423,
      code: "locked",
      message: "MFA required",
    });
  });

  it("falls back to a generic message when the error body isn't JSON", async () => {
    mockedFetch.mockResolvedValue(new Response("not json", { status: 500 }));
    await expect(apiRequest("/skills")).rejects.toMatchObject({
      status: 500,
      message: "Request failed (500)",
    });
  });
});

describe("apiStreamRequest", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it("returns the raw response on success", async () => {
    const res = new Response("data: {}\n\n", { status: 200 });
    mockedFetch.mockResolvedValue(res);
    const result = await apiStreamRequest("/chats/1/messages");
    expect(result).toBe(res);
  });

  it("throws ApiError on a pre-stream failure", async () => {
    mockedFetch.mockResolvedValue(new Response(null, { status: 401 }));
    await expect(apiStreamRequest("/chats/1/messages")).rejects.toBeInstanceOf(ApiError);
  });
});
