import { store, currentTierAtom } from "@/store";
import { actions } from "@/actions";
import { getCurrentTierApiV1InferenceCurrentTierGet } from "@/generated/sdk.gen";

/**
 * Inference Tier network calls (`/api/v1/inference/*`) — scoped to the
 * word-addin's own read of "what tier would my next request land at"
 * (PRD §3.13, DE-287 M3-B6's tier badge). Admin-only tier-policy/config
 * endpoints (`GET/PATCH /api/v1/admin/tier-policy`,
 * `GET /api/v1/inference/tier-config`,
 * `POST /api/v1/inference/override-tier-floor`) aren't wrapped here —
 * operator/admin surface, not part of the add-in's own UI.
 *
 * Stubbed ahead of the Tier badge's real UI — `Header.tsx`'s "Tier" pill
 * is currently inert and `Header` isn't even rendered by `App.tsx` yet
 * — same rationale as `playbookClient.ts`. Not self-invoked at module
 * load; call `tierClient.get()` once `Header` (or wherever the badge
 * ends up) actually mounts.
 */
export const tierClient = {
  /** `GET /api/v1/inference/current-tier?provider=...&model=...` —
   *  answers "what tier would a request to this specific provider/model
   *  land at," not a single global "current tier" — despite the atom's
   *  name, this must be re-called whenever the selected model changes
   *  (see `modelClient.ts`'s `selectedModelIdAtom`) to stay accurate. */
  async get(provider: string, model: string): Promise<void> {
    const { data, error } = await getCurrentTierApiV1InferenceCurrentTierGet({
      query: { provider, model },
    });
    if (error || !data) {
      actions.showNotification("Error loading inference tier");
      return;
    }
    store.set(currentTierAtom, data);
  },
};
