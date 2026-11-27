/**
 * Pure model-picker domain logic, mirrored from the web app's
 * `web/src/lib/lq-ai/api/models.ts` (types + `groupModels`/
 * `defaultSelection`) — word-addin has no shared package with `web/`,
 * so this is a deliberate mirror, not an import; keep in sync by field
 * name. The fetch itself lives in `services/modelClient.ts`; this file
 * is just the grouping/selection logic `modelClient.get()` uses to pick
 * a default and `ModelCombobox` (src/components/ModelCombobox.tsx) uses
 * to group the dropdown into alias/provider sections.
 */

/**
 * One row of `GET /api/v1/models`. `id` is either an alias (`"smart"`)
 * or a raw provider/model form (`"anthropic-prod/claude-haiku-4-5"`) —
 * either form is sendable verbatim as `MessageCreate.model`.
 */
export interface ModelEntry {
  id: string;
  object: "model";
  created: number;
  owned_by: string;
  lq_ai_kind: "alias" | "provider_native";
  /** Tier 1-5 the request would land at; omitted on aliases. */
  routed_inference_tier?: 1 | 2 | 3 | 4 | 5;
  /** Provider type (`anthropic`, `ollama`, ...) for grouping. */
  provider_type?: string;
  /** For aliases, the resolved `<provider>/<model>` form of the
   *  primary target — lets the picker render "smart →
   *  anthropic-prod/claude-opus-4-7" so aliases are convenience, not
   *  opacity. Omitted on provider-native rows. */
  lq_ai_resolves_to?: string;
  /** Number of fallback entries past the primary (alias only). */
  lq_ai_fallback_count?: number;
}

export interface ModelListResponse {
  object: "list";
  data: ModelEntry[];
}

/** Grouped view consumed by the picker. Aliases first; native rows
 *  grouped by provider name (alphabetical for stable ordering). */
export interface GroupedModels {
  aliases: ModelEntry[];
  /** Map of `<provider_name> -> entries` keyed by `provider_type`
   *  (falls back to `owned_by` when `provider_type` is absent). */
  nativeByProvider: Map<string, ModelEntry[]>;
}

/** `GET /api/v1/models` is a raw upstream catalog dump, not a curated
 *  chat-model list — it mixes chat completions in with embeddings,
 *  TTS, transcription, moderation, image, and realtime-audio endpoints
 *  that can't serve `MessageCreate.model`. There's no field marking
 *  modality, so this filters on id-shape instead. Applied to both the
 *  native id and (for aliases) the resolved target, since an alias
 *  like `"embedding"` can itself resolve to a non-chat model. */
const NON_CHAT_ID_PATTERNS: RegExp[] = [
  /embedding/i,
  /whisper/i,
  /transcribe/i,
  /moderation/i,
  /realtime/i,
  /(^|-)tts(-|$)/i,
  /(^|-)audio(-|$)/i,
  /(^|-)image(-|$)/i,
  /^dall-e/i,
  /^sora/i,
  /^davinci/i,
  /^babbage/i,
];

function looksNonChat(id: string): boolean {
  const last = id.split("/").pop() ?? id;
  return NON_CHAT_ID_PATTERNS.some((pattern) => pattern.test(last));
}

/** Whether an entry can serve `MessageCreate.model` — i.e. is a chat
 *  model, not an embedding/TTS/transcription/moderation/image/realtime
 *  endpoint swept up in the same catalog. */
export function isChatModel(entry: ModelEntry): boolean {
  if (looksNonChat(entry.id)) return false;
  if (entry.lq_ai_resolves_to && looksNonChat(entry.lq_ai_resolves_to)) return false;
  return true;
}

/** Known `provider_type` -> display name. Falls back to title-casing
 *  the key (and dropping a trailing `-prod`/`-local` environment
 *  suffix, e.g. `owned_by` "openai-prod" when `provider_type` is
 *  absent) for providers not in this list. */
const PROVIDER_DISPLAY_NAMES: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  ollama: "Ollama",
};

export function providerDisplayName(key: string): string {
  const known = PROVIDER_DISPLAY_NAMES[key.toLowerCase()];
  if (known) return known;
  const stripped = key.replace(/-(prod|local)$/i, "");
  return stripped
    .split(/[-_]/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/** Group a flat model list into `{aliases, nativeByProvider}`, dropping
 *  non-chat catalog entries (see `isChatModel`). Stable ordering:
 *  aliases preserve API order; native groups sort by provider key;
 *  entries within a native group sort by id. */
export function groupModels(list: ModelListResponse): GroupedModels {
  const aliases: ModelEntry[] = [];
  const native = new Map<string, ModelEntry[]>();
  for (const entry of list.data) {
    if (!isChatModel(entry)) continue;
    if (entry.lq_ai_kind === "alias") {
      aliases.push(entry);
      continue;
    }
    const key = entry.provider_type ?? entry.owned_by;
    const bucket = native.get(key);
    if (bucket) {
      bucket.push(entry);
    } else {
      native.set(key, [entry]);
    }
  }
  for (const entries of native.values()) {
    entries.sort((a, b) => a.id.localeCompare(b.id));
  }
  const sorted = new Map<string, ModelEntry[]>(
    [...native.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  );
  return { aliases, nativeByProvider: sorted };
}

/** Pick a sensible default selection from a grouped list. Priority:
 *  `smart` alias if present -> first alias -> first native row ->
 *  `null` if nothing is configured (the picker renders an empty state). */
export function defaultSelection(grouped: GroupedModels): ModelEntry | null {
  const smart = grouped.aliases.find((a) => a.id === "smart");
  if (smart) return smart;
  if (grouped.aliases.length > 0) return grouped.aliases[0];
  for (const entries of grouped.nativeByProvider.values()) {
    if (entries.length > 0) return entries[0];
  }
  return null;
}

/** "smart → anthropic-prod/claude-opus-4-7 (+2 fallbacks)" */
export function aliasResolution(entry: ModelEntry): string {
  if (!entry.lq_ai_resolves_to) return "";
  const fb = entry.lq_ai_fallback_count ?? 0;
  const fbHint = fb > 0 ? ` (+${fb} fallback${fb === 1 ? "" : "s"})` : "";
  return `→ ${entry.lq_ai_resolves_to}${fbHint}`;
}

export function tierLabel(tier?: number): string {
  return tier ? `T${tier}` : "";
}
