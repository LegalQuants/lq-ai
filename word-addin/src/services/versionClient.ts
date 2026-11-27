/**
 * Add-in ↔ deployment version handshake network call (M3-B8) — see
 * `domain/version.ts` for the types + comparison logic this wraps.
 *
 * `App.tsx` calls `fetchVersionInfo()` once on mount, BEFORE the user has
 * signed in, and surfaces a non-compatible result as a dismissible,
 * non-autoclosing notification (`actions.showNotification`, `src/actions.ts`)
 * rather than blocking the UI — the add-in's bundle is always served by
 * this deployment, never independently installed, so the only realistic
 * cause of a mismatch is a stale cached bundle in Word's WebView, and
 * "refresh" is the fix. The version comparison runs against
 * `__ADDIN_VERSION__` — a string baked into the bundle by Vite's `define`
 * from `package.json` — so a tampered API response can't lie about the
 * installed version.
 *
 * Stays a plain exported function (not a `{get, ...}` client object):
 * `App.tsx` calls it once per mount with an explicit argument, it's not a
 * store-populating startup fetch like `skillClient.get()`/
 * `modelClient.get()`.
 */
import { getVersionApiV1WordAddinVersionGet } from "@/generated/sdk.gen";
import { classifyVersion, type VersionHandshakeResponse, type VersionInfo } from "@/domain/version";

/** Best-effort fetch of the version handshake. Never throws — the
 *  caller renders `status="unknown"` UI when the network call fails so
 *  an offline / misconfigured deployment doesn't lock the operator out
 *  of seeing the task pane at all. The generated client already
 *  swallows network/response failures into `error` rather than
 *  throwing (see `taskpane/auth.ts`'s `runRefresh` docstring for the
 *  same behavior verified against its source), so no try/catch is
 *  needed here either. */
export async function fetchVersionInfo(
  installedVersion: string = __ADDIN_VERSION__
): Promise<VersionInfo> {
  const { data, error, response } = await getVersionApiV1WordAddinVersionGet();
  if (error || !data) {
    return {
      status: "unknown",
      installed_version: installedVersion,
      handshake: null,
      error: response
        ? `Deployment returned ${response.status} ${response.statusText}.`
        : "Could not reach the deployment to check the add-in version.",
    };
  }
  const handshake = data as VersionHandshakeResponse;
  return {
    status: classifyVersion(installedVersion, handshake),
    installed_version: installedVersion,
    handshake,
    error: null,
  };
}
