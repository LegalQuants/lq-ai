/**
 * Tests for `src/taskpane/version.ts`.
 *
 * Exercises the semver-ish compare helpers + the classifier + the
 * `fetchVersionInfo` happy-path / failure-path branches. The compile-
 * time `__ADDIN_VERSION__` global is injected via vitest's `define`
 * config (see `vitest.config.ts`) so the version module's default
 * parameter resolves without a runtime stub.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  classifyVersion,
  compareVersions,
  fetchVersionInfo,
  parseVersion,
  type VersionHandshakeResponse,
} from "../version";

const HANDSHAKE: VersionHandshakeResponse = {
  deployment_version: "0.3.0",
  addin_min_compatible_version: "0.3.0",
  addin_max_compatible_version: "0.3.99",
  taskpane_bundle_url: "https://test.example/word-addin/taskpane.html",
  taskpane_bundle_hash: null,
};

describe("parseVersion", () => {
  it("parses simple semver-like strings", () => {
    expect(parseVersion("0.3.0")).toEqual([0, 3, 0]);
    expect(parseVersion("1.10.99")).toEqual([1, 10, 99]);
  });

  it("treats non-numeric trailing segments as zero", () => {
    expect(parseVersion("0.3.0-dev")).toEqual([0, 3, 0]);
    expect(parseVersion("0.3.0-rc.1")).toEqual([0, 3, 0]);
  });

  it("handles short strings gracefully", () => {
    expect(parseVersion("0.3")).toEqual([0, 3]);
    expect(parseVersion("1")).toEqual([1]);
  });
});

describe("compareVersions", () => {
  it("returns 0 for equal versions", () => {
    expect(compareVersions("0.3.0", "0.3.0")).toBe(0);
  });

  it("returns negative when a < b", () => {
    expect(compareVersions("0.2.99", "0.3.0")).toBeLessThan(0);
    expect(compareVersions("0.3.0", "0.3.1")).toBeLessThan(0);
  });

  it("returns positive when a > b", () => {
    expect(compareVersions("0.4.0", "0.3.99")).toBeGreaterThan(0);
    expect(compareVersions("1.0.0", "0.99.99")).toBeGreaterThan(0);
  });

  it("treats missing trailing segments as zero", () => {
    expect(compareVersions("0.3", "0.3.0")).toBe(0);
    expect(compareVersions("0.3", "0.3.1")).toBeLessThan(0);
  });
});

describe("classifyVersion", () => {
  it("returns 'compatible' for in-range versions", () => {
    expect(classifyVersion("0.3.0", HANDSHAKE)).toBe("compatible");
    expect(classifyVersion("0.3.5", HANDSHAKE)).toBe("compatible");
    expect(classifyVersion("0.3.99", HANDSHAKE)).toBe("compatible");
  });

  it("returns 'addin_outdated' when below min", () => {
    expect(classifyVersion("0.2.99", HANDSHAKE)).toBe("addin_outdated");
    expect(classifyVersion("0.1.0", HANDSHAKE)).toBe("addin_outdated");
  });

  it("returns 'deployment_outdated' when above max", () => {
    expect(classifyVersion("0.4.0", HANDSHAKE)).toBe("deployment_outdated");
    expect(classifyVersion("1.0.0", HANDSHAKE)).toBe("deployment_outdated");
  });
});

describe("fetchVersionInfo", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns 'compatible' on a happy-path handshake", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify(HANDSHAKE), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const info = await fetchVersionInfo("0.3.0");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toContain("/api/v1/word-addin/version");
    expect(info.status).toBe("compatible");
    expect(info.installed_version).toBe("0.3.0");
    expect(info.handshake).toEqual(HANDSHAKE);
    expect(info.error).toBeNull();
  });

  it("returns 'addin_outdated' when installed < min", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify(HANDSHAKE), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const info = await fetchVersionInfo("0.2.0");
    expect(info.status).toBe("addin_outdated");
    expect(info.installed_version).toBe("0.2.0");
  });

  it("returns 'deployment_outdated' when installed > max", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify(HANDSHAKE), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const info = await fetchVersionInfo("0.4.0");
    expect(info.status).toBe("deployment_outdated");
  });

  it("returns 'unknown' on HTTP error", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response("nope", { status: 500, statusText: "Internal Server Error" })
    );

    const info = await fetchVersionInfo("0.3.0");
    expect(info.status).toBe("unknown");
    expect(info.handshake).toBeNull();
    expect(info.error).toContain("500");
  });

  it("returns 'unknown' on network error", async () => {
    vi.spyOn(global, "fetch").mockRejectedValue(new Error("offline"));

    const info = await fetchVersionInfo("0.3.0");
    expect(info.status).toBe("unknown");
    expect(info.handshake).toBeNull();
    expect(info.error).toBe("offline");
  });

  it("uses __ADDIN_VERSION__ as the default installed version", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify(HANDSHAKE), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const info = await fetchVersionInfo();
    // vitest.config.ts pins __ADDIN_VERSION__ to the package.json
    // version field; we just check it's a non-empty semver-ish string
    // rather than coupling the test to the literal value (which moves
    // every release).
    expect(info.installed_version).toMatch(/^\d+\.\d+\.\d+/);
  });
});
