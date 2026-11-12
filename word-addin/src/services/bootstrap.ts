import { skillClient } from "@/services/skillClient";
import { modelClient } from "@/services/modelClient";

/**
 * Startup data load — call once, after a session is confirmed to exist
 * (see `App.tsx`'s `useEffect` gated on `useAuth()`'s `session`), not at
 * module-import time.
 *
 * This replaces the old pattern of each client self-invoking its own
 * `get()` at the bottom of its file (`void skillClient.get()`). That
 * fired once, at module-import time — which happens regardless of
 * whether a session exists yet, since the module graph loads before
 * React even renders the sign-in gate. A pre-login fire 401s (the
 * generated-client auth interceptor in `taskpane/auth.ts` correctly
 * attaches no header when there's no session) and, being a one-shot
 * call, never retries — so a user who logs in *after* that first
 * silent failure would see an empty skills/models list for the rest of
 * the session with no way to recover short of a full reload. Calling
 * `initializeApp()` explicitly once `session` is truthy fixes both the
 * ordering and the never-retries problem in one place.
 *
 * Parallel, not sequential (mirrors the web app's `ChatPanel.svelte`
 * `loadShell()` precedent) — these are independent resources, no
 * reason to serialize them.
 *
 * Add future startup-load clients here (e.g. a future `playbookClient.get()`
 * once the Playbooks tab has a real UI) rather than scattering more
 * self-invoking `void x.get()` lines across services/*.ts.
 */
export async function initializeApp(): Promise<void> {
  await Promise.all([skillClient.get(), modelClient.get()]);
}
