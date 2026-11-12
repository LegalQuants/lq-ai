/**
 * Tests for `src/services/versionClient.ts`'s `fetchVersionInfo`. Pure
 * compare/classify helper tests live in `domain/__tests__/version.test.ts`.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/generated/sdk.gen", () => ({
  getVersionApiV1WordAddinVersionGet: vi.fn(),
}));

import { getVersionApiV1WordAddinVersionGet } from "@/generated/sdk.gen";
import { fetchVersionInfo } from "@/services/versionClient";
import type { VersionHandshakeResponse } from "@/domain/version";

const HANDSHAKE: VersionHandshakeResponse = {
  deployment_version: "0.3.0",
  addin_min_compatible_version: "0.3.0",
  addin_max_compatible_version: "0.3.99",
  taskpane_bundle_url: "https://test.example/word-addin/taskpane.html",
  taskpane_bundle_hash: null,
};

describe("fetchVersionInfo", () => {
  beforeEach(() => {
    vi.mocked(getVersionApiV1WordAddinVersionGet).mockReset();
  });

  it("returns 'compatible' on a happy-path handshake", async () => {
    vi.mocked(getVersionApiV1WordAddinVersionGet).mockResolvedValue({
      data: HANDSHAKE,
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as Awaited<ReturnType<typeof getVersionApiV1WordAddinVersionGet>>);

    const info = await fetchVersionInfo("0.3.0");

    expect(getVersionApiV1WordAddinVersionGet).toHaveBeenCalled();
    expect(info.status).toBe("compatible");
    expect(info.installed_version).toBe("0.3.0");
    expect(info.handshake).toEqual(HANDSHAKE);
    expect(info.error).toBeNull();
  });

  it("returns 'addin_outdated' when installed < min", async () => {
    vi.mocked(getVersionApiV1WordAddinVersionGet).mockResolvedValue({
      data: HANDSHAKE,
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as Awaited<ReturnType<typeof getVersionApiV1WordAddinVersionGet>>);

    const info = await fetchVersionInfo("0.2.0");
    expect(info.status).toBe("addin_outdated");
    expect(info.installed_version).toBe("0.2.0");
  });

  it("returns 'deployment_outdated' when installed > max", async () => {
    vi.mocked(getVersionApiV1WordAddinVersionGet).mockResolvedValue({
      data: HANDSHAKE,
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as Awaited<ReturnType<typeof getVersionApiV1WordAddinVersionGet>>);

    const info = await fetchVersionInfo("0.4.0");
    expect(info.status).toBe("deployment_outdated");
  });

  it("returns 'unknown' on HTTP/network error", async () => {
    vi.mocked(getVersionApiV1WordAddinVersionGet).mockResolvedValue({
      data: undefined,
      error: "server error",
      response: new Response(null, { status: 500, statusText: "Internal Server Error" }),
    } as Awaited<ReturnType<typeof getVersionApiV1WordAddinVersionGet>>);

    const info = await fetchVersionInfo("0.3.0");
    expect(info.status).toBe("unknown");
    expect(info.handshake).toBeNull();
    expect(info.error).toContain("500");
  });

  it("uses __ADDIN_VERSION__ as the default installed version", async () => {
    vi.mocked(getVersionApiV1WordAddinVersionGet).mockResolvedValue({
      data: HANDSHAKE,
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as Awaited<ReturnType<typeof getVersionApiV1WordAddinVersionGet>>);

    const info = await fetchVersionInfo();
    // vitest.config.ts pins __ADDIN_VERSION__ to the package.json
    // version field; we just check it's a non-empty semver-ish string
    // rather than coupling the test to the literal value (which moves
    // every release).
    expect(info.installed_version).toMatch(/^\d+\.\d+\.\d+/);
  });
});
