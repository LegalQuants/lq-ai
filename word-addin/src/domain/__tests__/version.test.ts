/**
 * Tests for `src/domain/version.ts` — the pure compare/classify helpers.
 * Network-call tests for `fetchVersionInfo` live in
 * `services/__tests__/versionClient.test.ts`.
 */
import { describe, expect, it } from "vitest";
import {
  classifyVersion,
  compareVersions,
  parseVersion,
  type VersionHandshakeResponse,
} from "@/domain/version";

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
