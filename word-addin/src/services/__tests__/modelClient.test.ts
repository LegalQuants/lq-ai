import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/generated/sdk.gen", () => ({
  listModelsApiV1ModelsGet: vi.fn(),
}));

vi.mock("@/actions", () => ({ actions: { showNotification: vi.fn() } }));

import { listModelsApiV1ModelsGet } from "@/generated/sdk.gen";
import { store, resetStoreForTests, modelsAtom, selectedModelIdAtom } from "@/store";
import { modelClient } from "@/services/modelClient";
import { actions } from "@/actions";
import type { ModelListResponse } from "@/domain/models";

const MODELS: ModelListResponse = {
  object: "list",
  data: [
    {
      id: "smart",
      object: "model",
      created: 0,
      owned_by: "lq-ai",
      lq_ai_kind: "alias",
      routed_inference_tier: 4,
      lq_ai_resolves_to: "anthropic-prod/claude-opus-4-7",
    },
    {
      id: "anthropic-prod/claude-haiku-4-5",
      object: "model",
      created: 0,
      owned_by: "anthropic-prod",
      lq_ai_kind: "provider_native",
    },
  ],
};

describe("modelClient", () => {
  beforeEach(() => {
    resetStoreForTests();
    vi.mocked(listModelsApiV1ModelsGet).mockReset();
    vi.mocked(actions.showNotification).mockReset();
  });

  it("get() populates modelsAtom and defaults the selection to the smart alias", async () => {
    vi.mocked(listModelsApiV1ModelsGet).mockResolvedValue({ data: MODELS, error: undefined });

    await modelClient.get();

    expect(store.get(modelsAtom)).toEqual(MODELS);
    expect(store.get(selectedModelIdAtom)).toBe("smart");
  });

  it("get() notifies instead of throwing on failure", async () => {
    vi.mocked(listModelsApiV1ModelsGet).mockResolvedValue({
      data: undefined,
      error: { detail: [] },
    });

    await modelClient.get();

    expect(store.get(modelsAtom)).toEqual({ object: "list", data: [] });
    expect(actions.showNotification).toHaveBeenCalledWith("Error Loading Models");
  });

  it("get() defaults selection to null when no models are configured", async () => {
    vi.mocked(listModelsApiV1ModelsGet).mockResolvedValue({
      data: { object: "list", data: [] },
      error: undefined,
    });

    await modelClient.get();

    expect(store.get(selectedModelIdAtom)).toBeNull();
  });

  it("select() sets the selected model id", () => {
    modelClient.select("anthropic-prod/claude-haiku-4-5");
    expect(store.get(selectedModelIdAtom)).toBe("anthropic-prod/claude-haiku-4-5");
  });
});
