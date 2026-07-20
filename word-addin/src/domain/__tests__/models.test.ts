import { describe, expect, it } from "vitest";
import { groupModels, isChatModel, providerDisplayName, type ModelEntry } from "@/domain/models";

function alias(id: string, resolvesTo: string): ModelEntry {
  return {
    id,
    object: "model",
    created: 0,
    owned_by: "lq-ai-gateway",
    lq_ai_kind: "alias",
    routed_inference_tier: 4,
    lq_ai_resolves_to: resolvesTo,
  };
}

function native(id: string, providerType: string): ModelEntry {
  return {
    id,
    object: "model",
    created: 0,
    owned_by: `${providerType}-prod`,
    lq_ai_kind: "provider_native",
    routed_inference_tier: 4,
    provider_type: providerType,
  };
}

describe("isChatModel", () => {
  it("accepts a plain chat model", () => {
    expect(isChatModel(native("openai-prod/gpt-4o", "openai"))).toBe(true);
  });

  it.each([
    "openai-prod/text-embedding-3-small",
    "openai-prod/whisper-1",
    "openai-prod/tts-1",
    "openai-prod/tts-1-hd",
    "openai-prod/omni-moderation-latest",
    "openai-prod/gpt-4o-transcribe",
    "openai-prod/gpt-realtime",
    "openai-prod/gpt-image-1",
    "openai-prod/sora-2",
    "openai-prod/davinci-002",
    "openai-prod/babbage-002",
  ])("rejects non-chat catalog entry %s", (id) => {
    expect(isChatModel(native(id, "openai"))).toBe(false);
  });

  it("rejects an alias that resolves to a non-chat model", () => {
    expect(isChatModel(alias("embedding", "openai-prod/text-embedding-3-small"))).toBe(false);
  });

  it("accepts an alias that resolves to a chat model", () => {
    expect(isChatModel(alias("smart", "anthropic-prod/claude-opus-4-7"))).toBe(true);
  });
});

describe("groupModels", () => {
  it("drops non-chat entries and groups the rest by provider_type", () => {
    const list = {
      object: "list" as const,
      data: [
        alias("smart", "anthropic-prod/claude-opus-4-7"),
        alias("embedding", "openai-prod/text-embedding-3-small"),
        native("anthropic-prod/claude-opus-4-7", "anthropic"),
        native("openai-prod/gpt-4o", "openai"),
        native("openai-prod/whisper-1", "openai"),
      ],
    };

    const grouped = groupModels(list);

    expect(grouped.aliases.map((e) => e.id)).toEqual(["smart"]);
    expect([...grouped.nativeByProvider.keys()]).toEqual(["anthropic", "openai"]);
    expect(grouped.nativeByProvider.get("openai")?.map((e) => e.id)).toEqual([
      "openai-prod/gpt-4o",
    ]);
  });
});

describe("providerDisplayName", () => {
  it.each([
    ["anthropic", "Anthropic"],
    ["openai", "OpenAI"],
    ["ollama", "Ollama"],
  ])("maps known provider_type %s to %s", (key, expected) => {
    expect(providerDisplayName(key)).toBe(expected);
  });

  it("title-cases and strips an env suffix for unknown providers", () => {
    expect(providerDisplayName("mistral-prod")).toBe("Mistral");
    expect(providerDisplayName("some-other-provider")).toBe("Some Other Provider");
  });
});
