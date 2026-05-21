/**
 * Office.js Dialog API helper for the add-in's OAuth flow (M3-B2).
 *
 * Office add-ins can't use a browser popup for OAuth because the task
 * pane runs inside a sandboxed iframe — instead Office exposes its own
 * dialog primitive at ``Office.context.ui.displayDialogAsync``. The
 * dialog opens in a separate Office-managed window; the page it loads
 * can call ``Office.context.ui.messageParent`` to post structured data
 * back to the task pane.
 *
 * Per Phase B Decision B-3, the add-in's OAuth dialog points at
 * ``{deployment_origin}/lq-ai/word-addin/oauth-start`` (a SvelteKit
 * route on the same deployment that renders an LQ.AI login form). On
 * successful login the dialog posts the access + refresh tokens back
 * to the task pane via `messageParent`. The task pane then closes the
 * dialog and persists the session.
 */

import type { LoginResponseWire } from "./auth";

/** Payload posted back by the OAuth dialog page on a successful login.
 *  Mirrors the backend's `LoginResponse` wire shape so the task pane
 *  can hand it directly to `storeSession()`. */
export type OAuthDialogSuccessMessage = {
  type: "oauth-success";
  login: LoginResponseWire;
};

/** Payload posted back when the user dismisses the dialog without
 *  signing in, or when an error happens inside the dialog page that
 *  the dialog itself can't recover from. */
export type OAuthDialogErrorMessage = {
  type: "oauth-error";
  reason: string;
};

export type OAuthDialogMessage =
  | OAuthDialogSuccessMessage
  | OAuthDialogErrorMessage;

export type OAuthDialogResult =
  | { status: "success"; login: LoginResponseWire }
  | { status: "error"; reason: string }
  | { status: "cancelled" };

/** Open the OAuth dialog and resolve with the user's outcome.
 *
 *  The promise resolves with `cancelled` when the user closes the
 *  dialog without signing in, `success` with the login response when
 *  the dialog posts back a valid payload, and `error` for any other
 *  failure (dialog API rejection, malformed payload, network error
 *  inside the dialog page that bubbles up via messageParent).
 *
 *  Office.js's dialog API is callback-based — this wrapper hides the
 *  callback shape so callers get a clean async/await contract.
 */
export function openOAuthDialog(): Promise<OAuthDialogResult> {
  const dialogUrl = `${window.location.origin}/lq-ai/word-addin/oauth-start`;

  return new Promise<OAuthDialogResult>((resolve) => {
    Office.context.ui.displayDialogAsync(
      dialogUrl,
      {
        width: 30, // Office sizes are percentages of the screen.
        height: 50,
        promptBeforeOpen: false,
      },
      (asyncResult) => {
        if (asyncResult.status === Office.AsyncResultStatus.Failed) {
          resolve({
            status: "error",
            reason:
              asyncResult.error?.message ??
              "Could not open the LQ.AI sign-in dialog.",
          });
          return;
        }

        const dialog = asyncResult.value;

        // Default outcome is "cancelled" — the dialog API fires
        // DialogEventReceived when the user closes the dialog window.
        let resolved = false;
        const resolveOnce = (result: OAuthDialogResult): void => {
          if (resolved) return;
          resolved = true;
          try {
            dialog.close();
          } catch {
            // The dialog may already be closed; closing twice is harmless.
          }
          resolve(result);
        };

        dialog.addEventHandler(
          Office.EventType.DialogMessageReceived,
          (event) => {
            // The Office SDK types `event` as one of two shapes
            // depending on the handler kind. The runtime payload for
            // DialogMessageReceived carries a `message` string.
            const message = (event as { message?: string }).message ?? "";
            try {
              const parsed = JSON.parse(message) as OAuthDialogMessage;
              if (parsed.type === "oauth-success") {
                resolveOnce({ status: "success", login: parsed.login });
              } else if (parsed.type === "oauth-error") {
                resolveOnce({ status: "error", reason: parsed.reason });
              } else {
                resolveOnce({
                  status: "error",
                  reason: "Unexpected dialog message payload.",
                });
              }
            } catch {
              resolveOnce({
                status: "error",
                reason: "Could not parse the dialog response.",
              });
            }
          }
        );

        dialog.addEventHandler(
          Office.EventType.DialogEventReceived,
          (event) => {
            // Office fires this when the dialog is closed without a
            // messageParent call (user clicked the X, page nav, etc.).
            // event.error 12006 is the documented "dialog closed"
            // code; other error codes are surfaced as errors so the
            // caller can render a helpful message.
            const evt = event as { error?: number };
            if (evt.error === 12006) {
              resolveOnce({ status: "cancelled" });
            } else if (typeof evt.error === "number" && evt.error !== 0) {
              resolveOnce({
                status: "error",
                reason: `Dialog closed unexpectedly (Office error ${evt.error}).`,
              });
            } else {
              resolveOnce({ status: "cancelled" });
            }
          }
        );
      }
    );
  });
}
