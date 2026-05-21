/**
 * Tests for `src/taskpane/auth.ts`.
 *
 * Exercises token storage round-tripping, refresh coalescing, and the
 * `authenticatedFetch` 401-refresh-retry path. Office.js is not loaded
 * — the module under test only uses `window.location.origin` and
 * `fetch`, both of which jsdom provides.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  authenticatedFetch,
  clearSession,
  getSession,
  logout,
  refreshAccessToken,
  storeSession,
  updateTokens,
  type LoginResponseWire,
  type TokenRefreshResponseWire,
} from "../auth";

const LOGIN_FIXTURE: LoginResponseWire = {
  access_token: "access-1",
  token_type: "Bearer",
  expires_in: 3600,
  refresh_token: "refresh-1",
  user: {
    id: "11111111-1111-1111-1111-111111111111",
    email: "alice@example.com",
    display_name: "Alice",
    is_admin: false,
    role: "member",
    mfa_enabled: false,
    must_change_password: false,
  },
};

describe("session storage helpers", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-21T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("round-trips the session through localStorage", () => {
    const stored = storeSession(LOGIN_FIXTURE);
    expect(stored.access_token).toBe("access-1");
    expect(stored.refresh_token).toBe("refresh-1");
    expect(stored.user.email).toBe("alice@example.com");
    // expires_at derived from now + expires_in seconds.
    expect(stored.expires_at).toBe(Date.parse("2026-05-21T13:00:00Z"));

    const read = getSession();
    expect(read).toEqual(stored);
  });

  it("returns null when no session is stored", () => {
    expect(getSession()).toBeNull();
  });

  it("drops malformed payloads on read", () => {
    localStorage.setItem("lq-ai-word-addin-session", "not-json");
    expect(getSession()).toBeNull();

    localStorage.setItem(
      "lq-ai-word-addin-session",
      JSON.stringify({ access_token: "x" })
    );
    // Missing required fields → should be cleaned up + null returned.
    expect(getSession()).toBeNull();
    expect(localStorage.getItem("lq-ai-word-addin-session")).toBeNull();
  });

  it("updates only the token-related fields on refresh", () => {
    const stored = storeSession(LOGIN_FIXTURE);
    const refresh: TokenRefreshResponseWire = {
      access_token: "access-2",
      refresh_token: "refresh-2",
      token_type: "Bearer",
      expires_in: 7200,
    };
    const updated = updateTokens(stored, refresh);
    expect(updated.access_token).toBe("access-2");
    expect(updated.refresh_token).toBe("refresh-2");
    expect(updated.expires_at).toBe(Date.parse("2026-05-21T14:00:00Z"));
    // User record is preserved across refresh.
    expect(updated.user.email).toBe("alice@example.com");
  });

  it("clearSession removes the persisted payload", () => {
    storeSession(LOGIN_FIXTURE);
    expect(getSession()).not.toBeNull();
    clearSession();
    expect(getSession()).toBeNull();
  });
});

describe("refreshAccessToken", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("returns null when no session is present", async () => {
    const result = await refreshAccessToken();
    expect(result).toBeNull();
  });

  it("returns null + clears session when refresh_token is missing", async () => {
    storeSession({ ...LOGIN_FIXTURE, refresh_token: undefined });
    const result = await refreshAccessToken();
    expect(result).toBeNull();
    expect(getSession()).toBeNull();
  });

  it("on success: returns updated session with new tokens", async () => {
    storeSession(LOGIN_FIXTURE);
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: "access-2",
          refresh_token: "refresh-2",
          token_type: "Bearer",
          expires_in: 1800,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    const result = await refreshAccessToken();
    expect(result).not.toBeNull();
    expect(result!.access_token).toBe("access-2");
    expect(result!.refresh_token).toBe("refresh-2");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toContain("/api/v1/auth/refresh");
  });

  it("on backend error: clears session + returns null", async () => {
    storeSession(LOGIN_FIXTURE);
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response("nope", { status: 401 })
    );

    const result = await refreshAccessToken();
    expect(result).toBeNull();
    expect(getSession()).toBeNull();
  });

  it("on network error: clears session + returns null", async () => {
    storeSession(LOGIN_FIXTURE);
    vi.spyOn(global, "fetch").mockRejectedValue(new Error("network down"));

    const result = await refreshAccessToken();
    expect(result).toBeNull();
    expect(getSession()).toBeNull();
  });

  it("coalesces concurrent callers around a single fetch", async () => {
    storeSession(LOGIN_FIXTURE);
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: "access-2",
          refresh_token: "refresh-2",
          token_type: "Bearer",
          expires_in: 1800,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    const [a, b, c] = await Promise.all([
      refreshAccessToken(),
      refreshAccessToken(),
      refreshAccessToken(),
    ]);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(a?.access_token).toBe("access-2");
    expect(b?.access_token).toBe("access-2");
    expect(c?.access_token).toBe("access-2");
  });
});

describe("authenticatedFetch", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("returns 401 immediately when no session is stored", async () => {
    const res = await authenticatedFetch("/playbooks");
    expect(res.status).toBe(401);
  });

  it("attaches the bearer token + returns the response when status is not 401", async () => {
    storeSession(LOGIN_FIXTURE);
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const res = await authenticatedFetch("/playbooks");
    expect(res.status).toBe(200);
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer access-1");
  });

  it("retries once with refreshed token on 401", async () => {
    storeSession(LOGIN_FIXTURE);
    const fetchSpy = vi
      .spyOn(global, "fetch")
      // First call to the protected endpoint: 401.
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      // Refresh call: success.
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            access_token: "access-2",
            refresh_token: "refresh-2",
            token_type: "Bearer",
            expires_in: 1800,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
      // Retry: success.
      .mockResolvedValueOnce(
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );

    const res = await authenticatedFetch("/playbooks");
    expect(res.status).toBe(200);
    expect(fetchSpy).toHaveBeenCalledTimes(3);

    // Second call (the refresh) hits /auth/refresh.
    expect(fetchSpy.mock.calls[1][0]).toContain("/api/v1/auth/refresh");

    // Third call (the retry) carries the new bearer token.
    const retryInit = fetchSpy.mock.calls[2][1] as RequestInit;
    const retryHeaders = new Headers(retryInit.headers);
    expect(retryHeaders.get("Authorization")).toBe("Bearer access-2");
  });

  it("returns the original 401 if refresh fails", async () => {
    storeSession(LOGIN_FIXTURE);
    vi.spyOn(global, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 401 })); // refresh fails

    const res = await authenticatedFetch("/playbooks");
    expect(res.status).toBe(401);
    expect(getSession()).toBeNull();
  });
});

describe("logout", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("calls /auth/logout with bearer + clears the local session", async () => {
    storeSession(LOGIN_FIXTURE);
    const fetchSpy = vi
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));

    await logout();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toContain("/api/v1/auth/logout");
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer access-1");
    expect(getSession()).toBeNull();
  });

  it("clears the local session even if the backend errors", async () => {
    storeSession(LOGIN_FIXTURE);
    vi.spyOn(global, "fetch").mockRejectedValue(new Error("network down"));

    await logout();
    expect(getSession()).toBeNull();
  });

  it("is a no-op when no session is stored", async () => {
    const fetchSpy = vi.spyOn(global, "fetch");
    await logout();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
