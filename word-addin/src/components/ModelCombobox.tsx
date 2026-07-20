/**
 * ModelCombobox — model picker, modeled on the web app's ModelPicker.svelte
 * (web/src/lib/lq-ai/components/ModelPicker.svelte), built as a Mantine
 * `Combobox` (search target + grouped options) rather than a flat
 * `Autocomplete` so the dropdown can section aliases from native
 * provider rows the way the web picker does — see ADR 0011's
 * transparency requirement that alias rows publish their resolved
 * target inline.
 *
 * Reads `modelsAtom` directly (populated by `services/modelClient.ts`'s
 * `modelClient.get()`, called from `services/bootstrap.ts`'s
 * `initializeApp()`) rather than taking the list as a prop — the only
 * thing the caller (`ModelBar.tsx`) still needs to supply is the current
 * selection + the select callback.
 */
import React, { useState } from "react";
import { Combobox, Input, InputBase, useCombobox } from "@mantine/core";
import { useAtomValue } from "jotai";
import { modelsAtom } from "@/store";
import {
  groupModels,
  aliasResolution,
  tierLabel,
  providerDisplayName,
  type ModelEntry,
} from "@/domain/models";

type ModelComboboxProps = {
  selectedId: string | null;
  onSelect: (id: string) => void;
};

/** "claude-opus-4-7" -> "Claude Opus 4.7", "smart" -> "Smart" — takes the
 *  last `/`-segment (drops the provider prefix), splits on `-`, title-cases
 *  non-numeric tokens, and joins consecutive numeric tokens with `.` so
 *  version numbers read as "4.7" rather than "4 7". */
function formatModelName(id: string): string {
  const last = id.split("/").pop();
  if (!last) return id;

  const tokens = last.split("-");
  const parts: string[] = [];
  let numBuffer: string[] = [];

  const flushNumBuffer = () => {
    if (numBuffer.length) {
      parts.push(numBuffer.join("."));
      numBuffer = [];
    }
  };

  for (const token of tokens) {
    if (/^\d+$/.test(token)) {
      numBuffer.push(token);
    } else {
      flushNumBuffer();
      parts.push(token.charAt(0).toUpperCase() + token.slice(1));
    }
  }
  flushNumBuffer();

  return parts.join(" ");
}

function matchesSearch(entry: ModelEntry, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return entry.id.toLowerCase().includes(q) || formatModelName(entry.id).toLowerCase().includes(q);
}

export const ModelCombobox: React.FC<ModelComboboxProps> = ({ selectedId, onSelect }) => {
  const models = useAtomValue(modelsAtom);
  const [search, setSearch] = useState("");
  const selectedEntry = models.data.find((entry) => entry.id === selectedId) ?? null;

  const combobox = useCombobox({
    onDropdownClose: () => {
      combobox.resetSelectedOption();
      setSearch("");
    },
  });

  const grouped = groupModels(models);
  const aliasOptions = grouped.aliases.filter((entry) => matchesSearch(entry, search));
  const nativeGroups = [...grouped.nativeByProvider.entries()]
    .map(
      ([provider, entries]) =>
        [provider, entries.filter((entry) => matchesSearch(entry, search))] as const
    )
    .filter(([, entries]) => entries.length > 0);
  const hasResults = aliasOptions.length > 0 || nativeGroups.length > 0;

  const renderOption = (entry: ModelEntry) => (
    <Combobox.Option value={entry.id} key={entry.id} active={entry.id === selectedId}>
      <div style={{ display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
          <span>{formatModelName(entry.id)}</span>
          {entry.routed_inference_tier && (
            <span style={{ fontSize: 10, opacity: 0.7 }}>
              {tierLabel(entry.routed_inference_tier)}
            </span>
          )}
        </div>
        {entry.lq_ai_resolves_to && (
          <span style={{ fontSize: 10, opacity: 0.7 }}>{aliasResolution(entry)}</span>
        )}
      </div>
    </Combobox.Option>
  );

  return (
    <Combobox
      store={combobox}
      shadow="md"
      data-testid="lq-ai-model-picker"
      onOptionSubmit={(value) => {
        onSelect(value);
        combobox.closeDropdown();
      }}
    >
      <Combobox.Target>
        <InputBase
          component="button"
          type="button"
          size="xs"
          pointer
          rightSection={<Combobox.Chevron />}
          onClick={() => combobox.toggleDropdown()}
        >
          {selectedEntry ? (
            formatModelName(selectedEntry.id)
          ) : (
            <Input.Placeholder>Select model</Input.Placeholder>
          )}
        </InputBase>
      </Combobox.Target>

      <Combobox.Dropdown>
        <Combobox.Search
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          placeholder="Search models"
        />
        <Combobox.Options mah={280} style={{ overflowY: "auto" }}>
          {!hasResults && <Combobox.Empty>No models found</Combobox.Empty>}
          {aliasOptions.length > 0 && (
            <Combobox.Group label="Aliases (defaults)">
              {aliasOptions.map(renderOption)}
            </Combobox.Group>
          )}
          {nativeGroups.map(([provider, entries]) => (
            <Combobox.Group label={providerDisplayName(provider)} key={provider}>
              {entries.map(renderOption)}
            </Combobox.Group>
          ))}
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
};
