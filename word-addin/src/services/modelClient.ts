import { store, modelsAtom, selectedModelIdAtom } from "@/store";
import { actions } from "@/actions";
import { groupModels, defaultSelection, type ModelListResponse } from "@/domain/models";
import { listModelsApiV1ModelsGet } from "@/generated/sdk.gen";

/**
 * `GET /api/v1/models` — response comes back untyped (`unknown`) from the
 * generated client (the backend forwards the gateway's merged payload
 * verbatim, no declared `response_model`), so it's cast to
 * `domain/models.ts`'s hand-mirrored `ModelListResponse` — same caveat as
 * `skillClient.ts`'s catalog methods (see ../../CLAUDE.md's "Type fidelity
 * varies by endpoint").
 *
 * `get()` is called once from `services/bootstrap.ts`'s `initializeApp()`
 * after login — the model picker always needs the list, so there's no
 * lazy-load case to gate on mount.
 */
export const modelClient = {
  async get(): Promise<void> {
    const { data, error } = await listModelsApiV1ModelsGet();
    if (error || !data) {
      actions.showNotification(`Error Loading Models`);
      return;
    }
    const models = data as ModelListResponse;
    store.set(modelsAtom, models);

    const selected = defaultSelection(groupModels(models));
    store.set(selectedModelIdAtom, selected ? selected.id : null);
  },

  /** Selection from `ModelCombobox` — persists across turns until
   *  changed again (no per-message override UI). `id` is either an alias
   *  (`"smart"`) or a raw `provider/model` form; both are sendable
   *  verbatim as `MessageCreate.model`, so no translation happens here. */
  select(id: string): void {
    store.set(selectedModelIdAtom, id);
  },
};
