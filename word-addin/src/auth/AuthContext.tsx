/**
 * AuthContext — React context wrapping the add-in's session state.
 *
 * The task pane has two sign-in paths sharing one localStorage-backed
 * session (see ../taskpane/auth.ts, M3-B2):
 *
 *   1. OAuth dialog (SignInGate.tsx / ../taskpane/dialog.ts) — opens the
 *      deployment's hosted login page in an Office.js dialog and posts
 *      the JWT back via `messageParent`.
 *   2. Inline form (Login.tsx, this component's primary consumer) — posts
 *      directly to `POST /api/v1/auth/login` (docs/api/backend-openapi.yaml)
 *      from inside the task pane, no dialog.
 *
 * Both paths end by calling `storeSession()`, which writes to the same
 * localStorage key. This context is the single place that turns that
 * write into a React re-render: `login()` drives path 2 end-to-end;
 * `setSession()` is exposed so path 1 (which already has a session object
 * once the dialog resolves) can push it into context without duplicating
 * the fetch/parse logic here.
 *
 * `login()` calls the generated `loginApiV1AuthLoginPost` (see
 * `@/generated`) rather than raw `fetch` — `taskpane/auth.ts` configures
 * the generated client's base URL once at module load.
 */
import React, { createContext, useCallback, useContext, useMemo, useState } from "react";
import { getSession, logout as clearRemoteSession, storeSession, type AuthSession } from "@/taskpane/auth";
import { loginApiV1AuthLoginPost } from "@/generated/sdk.gen";

/** Tags which task-pane surface initiated the login call. Not yet part of
 *  the wire request — `LoginRequest` is `{email, password}` only per the
 *  OpenAPI sketch — kept so callers (task pane vs. the ribbon-command
 *  surface, if that ever needs its own sign-in) are future-distinguishable
 *  without a signature change. */
export type ClientContext = "taskpane" | "commands";

export interface AuthContextValue {
  session: AuthSession | null;
  user: AuthSession["user"] | null;
  isAuthenticated: boolean;
  login: (email: string, password: string, clientContext?: ClientContext) => Promise<AuthSession>;
  logout: () => Promise<void>;
  setSession: (session: AuthSession | null) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [session, setSessionState] = useState<AuthSession | null>(() => getSession());

  const setSession = useCallback((next: AuthSession | null) => {
    setSessionState(next);
  }, []);

  const login = useCallback(
    async (
      email: string,
      password: string,
      _clientContext: ClientContext = "taskpane"
    ): Promise<AuthSession> => {
      const { data, error, response } = await loginApiV1AuthLoginPost({body: { email, password }});

      if (response?.status === 423) {
        // MfaChallenge per the OpenAPI sketch — the add-in doesn't have an
        // MFA-code entry step yet, so surface a clear message rather than
        // a raw 423.
        throw new Error(
          "This account requires MFA. MFA sign-in isn't supported in the Word add-in yet — use the LQ.AI web app."
        );
      }
      if (response?.status === 401) {
        throw new Error("Incorrect email or password.");
      }
      if (error || !data) {
        throw new Error(`Sign-in failed (${response?.status ?? "unknown"}).`);
      }

      const next = storeSession(data);
      setSessionState(next);
      return next;
    },
    []
  );

  const logout = useCallback(async () => {
    await clearRemoteSession();
    setSessionState(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      user: session?.user ?? null,
      isAuthenticated: session !== null,
      login,
      logout,
      setSession,
    }),
    [session, login, logout, setSession]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth() must be called within an <AuthProvider>.");
  }
  return ctx;
}
