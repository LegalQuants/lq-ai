/**
 * Add-in ↔ deployment version handshake (M3-B8) — pure types + comparison
 * logic. The network call itself lives in `services/versionClient.ts`;
 * split the same way as every other `domain/`-vs-`services/` pair in this
 * codebase (see ../../CLAUDE.md).
 *
 * Version comparison is intentionally simple semver-ish: split on `.`,
 * parse each component as an int, compare lexicographically. The four
 * shipping cases:
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

export interface VersionHandshakeResponse {
  deployment_version: string;
  addin_min_compatible_version: string;
  addin_max_compatible_version: string;
  taskpane_bundle_url: string;
  taskpane_bundle_hash: string | null;
}

export type VersionStatus = "compatible" | "addin_outdated" | "deployment_outdated" | "unknown";

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
