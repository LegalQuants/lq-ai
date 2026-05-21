/**
 * Add-in ↔ deployment version handshake (M3-B8).
 *
 * The task pane calls `fetchVersionInfo()` on mount, BEFORE the user
 * has signed in. The result determines whether the rest of the UI
 * (SignInGate, authenticated tab strip) should render or whether the
 * task pane needs to surface an `UpdateNeededOverlay` instead. The
 * version comparison runs against `__ADDIN_VERSION__` — a string
 * baked into the bundle by webpack's `DefinePlugin` from
 * `package.json` — so a tampered API response can't lie about the
 * installed version.
 *
 * Version comparison is intentionally simple semver-ish: we split on
 * `.`, parse each component as an int, and compare lexicographically.
 * The four shipping cases:
 *
 *   - installed < min            → status: "addin_outdated"
 *                                  (operator needs to update the
 *                                  manifest catalog)
 *   - installed > max            → status: "deployment_outdated"
 *                                  (operator needs to update the
 *                                  deployment)
 *   - installed within range     → status: "compatible"
 *   - handshake failed entirely  → status: "unknown"
 *                                  (best-effort: the add-in continues
 *                                  to render so an offline operator
 *                                  isn't blocked, but the soft warning
 *                                  surfaces so they know we couldn't
 *                                  check)
 */

import { deploymentOrigin } from "./auth";

export interface VersionHandshakeResponse {
  deployment_version: string;
  addin_min_compatible_version: string;
  addin_max_compatible_version: string;
  taskpane_bundle_url: string;
  taskpane_bundle_hash: string | null;
}

export type VersionStatus =
  | "compatible"
  | "addin_outdated"
  | "deployment_outdated"
  | "unknown";

export interface VersionInfo {
  status: VersionStatus;
  /** The version baked into the loaded bundle — `__ADDIN_VERSION__`. */
  installed_version: string;
  /** The handshake response, when the request succeeded. Null on
   *  network / parse failure (status will be `"unknown"`). */
  handshake: VersionHandshakeResponse | null;
  /** When `status` is "unknown", a short human-readable reason. */
  error: string | null;
}

/** Parse a dotted version string into a tuple of integers. Non-numeric
 *  segments (e.g. "-dev") are treated as 0 — the project tags every
 *  ship as `X.Y.Z` so this is a defensive default, not a meaningful
 *  semver pre-release ordering. */
export function parseVersion(value: string): number[] {
  return value.split(".").map((segment) => {
    const match = segment.match(/^(\d+)/);
    return match ? Number.parseInt(match[1], 10) : 0;
  });
}

/** Lexicographic compare. Returns negative if `a < b`, positive if
 *  `a > b`, zero if equal. Missing segments are treated as zero so
 *  "0.3" sorts before "0.3.1". */
export function compareVersions(a: string, b: string): number {
  const av = parseVersion(a);
  const bv = parseVersion(b);
  const len = Math.max(av.length, bv.length);
  for (let i = 0; i < len; i += 1) {
    const ai = av[i] ?? 0;
    const bi = bv[i] ?? 0;
    if (ai < bi) return -1;
    if (ai > bi) return 1;
  }
  return 0;
}

/** Classify the installed version against the deployment's range. */
export function classifyVersion(
  installed: string,
  handshake: VersionHandshakeResponse
): VersionStatus {
  if (compareVersions(installed, handshake.addin_min_compatible_version) < 0) {
    return "addin_outdated";
  }
  if (compareVersions(installed, handshake.addin_max_compatible_version) > 0) {
    return "deployment_outdated";
  }
  return "compatible";
}

/** Best-effort fetch of the version handshake. Never throws — the
 *  caller renders `status="unknown"` UI when the network call fails
 *  so an offline / misconfigured deployment doesn't lock the operator
 *  out of seeing the task pane at all. */
export async function fetchVersionInfo(
  installedVersion: string = __ADDIN_VERSION__
): Promise<VersionInfo> {
  try {
    const res = await fetch(`${deploymentOrigin()}/api/v1/word-addin/version`, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) {
      return {
        status: "unknown",
        installed_version: installedVersion,
        handshake: null,
        error: `Deployment returned ${res.status} ${res.statusText}.`,
      };
    }
    const handshake = (await res.json()) as VersionHandshakeResponse;
    return {
      status: classifyVersion(installedVersion, handshake),
      installed_version: installedVersion,
      handshake,
      error: null,
    };
  } catch (err) {
    return {
      status: "unknown",
      installed_version: installedVersion,
      handshake: null,
      error:
        err instanceof Error
          ? err.message
          : "Could not reach the deployment to check the add-in version.",
    };
  }
}
