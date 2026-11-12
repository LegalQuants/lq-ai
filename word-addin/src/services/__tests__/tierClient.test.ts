import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/generated/sdk.gen", () => ({
  getCurrentTierApiV1InferenceCurrentTierGet: vi.fn(),
}));

vi.mock("@/actions", () => ({ actions: { showNotification: vi.fn() } }));

import { getCurrentTierApiV1InferenceCurrentTierGet } from "@/generated/sdk.gen";
import { store, resetStoreForTests, currentTierAtom } from "@/store";
import { tierClient } from "@/services/tierClient";
import { actions } from "@/actions";
import type { CurrentTierResponse } from "@/generated/types.gen";

const TIER: CurrentTierResponse = {
  provider: "anthropic-prod",
  model: "claude-opus-4-7",
  routed_inference_tier: 4,
};

describe("tierClient", () => {
  beforeEach(() => {
    resetStoreForTests();
    vi.mocked(getCurrentTierApiV1InferenceCurrentTierGet).mockReset();
    vi.mocked(actions.showNotification).mockReset();
  });

  it("get() populates currentTierAtom on success", async () => {
    vi.mocked(getCurrentTierApiV1InferenceCurrentTierGet).mockResolvedValue({
      data: TIER,
      error: undefined,
    });

    await tierClient.get("anthropic-prod", "claude-opus-4-7");

    expect(getCurrentTierApiV1InferenceCurrentTierGet).toHaveBeenCalledWith({
      query: { provider: "anthropic-prod", model: "claude-opus-4-7" },
    });
    expect(store.get(currentTierAtom)).toEqual(TIER);
  });

  it("get() notifies instead of throwing on failure", async () => {
    vi.mocked(getCurrentTierApiV1InferenceCurrentTierGet).mockResolvedValue({
      data: undefined,
      error: {},
    });

    await tierClient.get("anthropic-prod", "claude-opus-4-7");

    expect(store.get(currentTierAtom)).toBeNull();
    expect(actions.showNotification).toHaveBeenCalledWith("Error loading inference tier");
  });
});
