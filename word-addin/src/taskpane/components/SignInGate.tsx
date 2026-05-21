/**
 * Sign-in gate component.
 *
 * Renders the unauthenticated state of the task pane: a brief explanation
 * of what the add-in needs to do, a primary "Sign in" button that opens
 * the Office.js OAuth dialog (per Decision B-3, the dialog points at the
 * LQ.AI deployment's existing login form rather than MSAL/WAM), and an
 * inline error banner if the dialog returned an error result.
 *
 * Wired into `App.tsx`: when `getSession()` returns null, `App` renders
 * this component instead of the tab strip + content area. After a
 * successful sign-in `App` re-evaluates the session and re-renders into
 * the authenticated layout.
 */
import React, { useState } from "react";
import { openOAuthDialog } from "../dialog";
import type { AuthSession } from "../auth";
import { storeSession } from "../auth";

type SignInGateProps = {
  onSignedIn: (session: AuthSession) => void;
};

export const SignInGate: React.FC<SignInGateProps> = ({ onSignedIn }) => {
  const [opening, setOpening] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSignIn(): Promise<void> {
    setOpening(true);
    setErrorMessage(null);
    try {
      const result = await openOAuthDialog();
      if (result.status === "success") {
        const session = storeSession(result.login);
        onSignedIn(session);
      } else if (result.status === "error") {
        setErrorMessage(result.reason);
      }
      // Cancelled is silent — the user closed the dialog deliberately,
      // no need to surface a banner.
    } finally {
      setOpening(false);
    }
  }

  const deploymentHost = (() => {
    try {
      return new URL(window.location.origin).host;
    } catch {
      return "this deployment";
    }
  })();

  return (
    <section className="lq-signin">
      <h2 className="lq-signin-title">Sign in to LQ.AI</h2>
      <p className="lq-signin-body">
        The add-in needs to authenticate against <strong>{deploymentHost}</strong>{" "}
        before it can run against your documents. Click <em>Sign in</em> below to
        open the LQ.AI sign-in window; once you authenticate we&apos;ll close the
        window and bring you back to the task pane.
      </p>
      <button
        type="button"
        className="lq-signin-button"
        onClick={handleSignIn}
        disabled={opening}
      >
        {opening ? "Opening sign-in window…" : "Sign in"}
      </button>
      {errorMessage && (
        <p className="lq-signin-error" role="alert">
          {errorMessage}
        </p>
      )}
      <p className="lq-signin-footnote">
        Don&apos;t have an account on this deployment? Ask your LQ.AI admin to
        invite you, or use the same email address you use to sign in to the
        LQ.AI web app.
      </p>
    </section>
  );
};
