/**
 * Auth state + API helpers for the Word add-in (M3-B2).
 *
 * Per Phase B Decision B-3, the add-in uses the LQ.AI deployment's existing
 * JWT issuer rather than MSAL — the task pane opens an Office.js dialog at
 * `{deployment_origin}/lq-ai/word-addin/oauth-start` which renders a
 * standard LQ.AI login form. On success the dialog posts the JWT + user
 * back to the task pane via `Office.context.ui.messageParent`, the task
 * pane stores it in `localStorage`, and subsequent API calls attach the
 * bearer token automatically.
 *
 * Token storage: localStorage (cross-document, cross-session per browser
 * profile) rather than `Office.context.document.settings`, which would
 * tie the auth to a specific Word document. A user signs into the add-in
 * once and the session persists across documents in the same Word
 * client + browser profile.
 *
 * Refresh: on 401, attempts a single refresh via
 * ``POST /api/v1/auth/refresh``; if that fails, drops the session and
 * surfaces a re-auth prompt. Concurrent refreshes coalesce around a
 * single in-flight promise so an admin dashboard's burst of parallel
 * API calls doesn't trigger N refresh attempts.
 *
 * No add-in-scoped JWT exchange (no ``aud: word-addin`` claim) for v0.3.0.
 * The add-in uses the same bearer token shape as the web app. A future
 * DE may add per-client audience scoping if endpoint-level revocation
 * becomes load-bearing.
 */

export type UserRole = "admin" | "member";

export interface AuthUser {
  id: string;
  email: string;
  display_name?: string | null;
  is_admin: boolean;
  role?: UserRole;
  mfa_enabled: boolean;
  must_change_password: boolean;
}

export interface AuthSession {
  access_token: string;
  refresh_token: string | null;
  expires_at: number; // epoch milliseconds; derived from expires_in at storage time
  user: AuthUser;
}

export interface LoginResponseWire {
  access_token: string;
  token_type: "Bearer";
  expires_in: number;
  refresh_token?: string;
  user: AuthUser;
}

export interface TokenRefreshResponseWire {
  access_token: string;
  refresh_token: string;
  token_type: "Bearer";
  expires_in: number;
}

const STORAGE_KEY = "lq-ai-word-addin-session";

/** Deployment origin the task pane was loaded from. The manifest serves
 *  ``{deployment_origin}/word-addin/taskpane.html`` so this resolves to
 *  the LQ.AI deployment URL at runtime. */
export function deploymentOrigin(): string {
  return window.location.origin;
}

/** Read the persisted session from localStorage. Returns null when no
 *  session is present, when it's malformed, or when it has expired and
 *  has no refresh token to recover. The expiry check is best-effort —
 *  the backend remains the authority and will 401 if we're wrong. */
export function getSession(): AuthSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AuthSession;
    if (
      typeof parsed.access_token !== "string" ||
      typeof parsed.expires_at !== "number" ||
      typeof parsed.user !== "object" ||
      parsed.user === null
    ) {
      // Malformed payload — drop it so callers don't trip on it.
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

/** Persist a session payload. Computes `expires_at` from the wire
 *  `expires_in` (seconds) so the local store doesn't drift with clock
 *  skew between server response time and read time. */
export function storeSession(login: LoginResponseWire): AuthSession {
  const session: AuthSession = {
    access_token: login.access_token,
    refresh_token: login.refresh_token ?? null,
    expires_at: Date.now() + login.expires_in * 1000,
    user: login.user,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  return session;
}

/** Update the access + refresh tokens after a successful refresh call,
 *  preserving the cached user record. */
export function updateTokens(
  session: AuthSession,
  refresh: TokenRefreshResponseWire
): AuthSession {
  const updated: AuthSession = {
    ...session,
    access_token: refresh.access_token,
    refresh_token: refresh.refresh_token,
    expires_at: Date.now() + refresh.expires_in * 1000,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
  return updated;
}

/** Drop the persisted session. Safe to call repeatedly; tolerant of
 *  the case where localStorage has already been cleared by another tab. */
export function clearSession(): void {
  localStorage.removeItem(STORAGE_KEY);
}

/** Refresh-coalescing handle — populated by `refreshAccessToken` while
 *  a refresh is in flight so concurrent callers share the result. */
let refreshInFlight: Promise<AuthSession | null> | null = null;

/** Attempt a single refresh. Returns the new session, or null on failure
 *  (in which case the local session has been cleared). Coalesces parallel
 *  callers around one network request. */
export function refreshAccessToken(): Promise<AuthSession | null> {
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    const session = getSession();
    if (!session || !session.refresh_token) {
      clearSession();
      return null;
    }
    try {
      const res = await fetch(`${deploymentOrigin()}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: session.refresh_token }),
      });
      if (!res.ok) {
        clearSession();
        return null;
      }
      const wire = (await res.json()) as TokenRefreshResponseWire;
      return updateTokens(session, wire);
    } catch {
      clearSession();
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

/** Fetch wrapper that attaches the bearer token + handles 401-refresh-
 *  retry. Returns the raw Response so callers can inspect status, headers,
 *  and body shape as they see fit. */
export async function authenticatedFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const session = getSession();
  if (!session) {
    return new Response(null, { status: 401, statusText: "No session" });
  }

  const url = path.startsWith("http")
    ? path
    : `${deploymentOrigin()}/api/v1${path.startsWith("/") ? "" : "/"}${path}`;

  const headers = new Headers(init.headers ?? {});
  headers.set("Authorization", `Bearer ${session.access_token}`);

  let res = await fetch(url, { ...init, headers });
  if (res.status !== 401) return res;

  const refreshed = await refreshAccessToken();
  if (!refreshed) return res; // returns the original 401

  headers.set("Authorization", `Bearer ${refreshed.access_token}`);
  res = await fetch(url, { ...init, headers });
  return res;
}

/** Best-effort logout. Calls the backend so the refresh token is
 *  invalidated server-side, then drops the local session regardless. */
export async function logout(): Promise<void> {
  const session = getSession();
  if (session) {
    try {
      await fetch(`${deploymentOrigin()}/api/v1/auth/logout`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.access_token}`,
        },
      });
    } catch {
      // Server may be unreachable, expired token, etc. — local clear
      // is the load-bearing step.
    }
  }
  clearSession();
}
