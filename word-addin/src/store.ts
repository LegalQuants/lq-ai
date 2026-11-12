/**
 * The Jotai store for the Word add-in.
 *
 * Providerless: `getDefaultStore()` is the same store instance every
 * un-provided `useAtom`/`useAtomValue` hook reads from, so action
 * functions can `store.set`/`store.get` directly without a `<Provider>`
 * wrapping `<App />` in taskpane.tsx. This fits a single-React-root task
 * pane that never remounts mid-session — there's no reset-on-remount use
 * case a Provider boundary would buy us.
 *
 * `resetStoreForTests()` exists because that same singleton-ness means
 * tests in the same Vitest worker share state across cases unless reset
 * — call it in `beforeEach`, mirroring `auth.test.ts`'s
 * `localStorage.clear()` pattern. Import atoms directly here (rather
 * than each domain exporting its own reset helper) so there's exactly
 * one place that has to stay in sync with "what atoms exist."
 */
import { atom, getDefaultStore, PrimitiveAtom } from "jotai";

import { SkillSummary } from "@/domain/types";
import type { ModelListResponse } from "@/domain/models";
import { toDocumentChatMessage, type DocumentChatTurn } from "@/domain/documentChat";
import type {
  CurrentTierResponse,
  Playbook,
  UserSkillResponse,
  UserSkillVersionItem,
} from "@/generated/types.gen";

export const store = getDefaultStore();

/* #region Atoms */

export const composerDraftAtom = atom<string>("");
export const stickyEnabledAtom = atom<boolean>(false);
export const stickyDirtyAtom = atom<boolean>(false);

// Document-grounded chat — POST /word-addin/document-chat (see
// services/documentChatClient.ts). This is the add-in's only chat
// surface (the persisted-chat client/atoms were removed — document
// state lives in the open Word document, not a server-side
// conversation record; see api/app/api/word_addin.py's module
// docstring for the stateless-by-design rationale). No chat_id, no
// persisted history — this list lives only for the task pane's session.
export const documentChatTurnsAtom = atom<DocumentChatTurn[]>([]);
export const documentChatUIMessagesAtom = atom((get) =>
  get(documentChatTurnsAtom).map(toDocumentChatMessage)
);
export const documentChatSendingAtom = atom<boolean>(false);

//Skills
export const skillsAtom = atom<SkillSummary[]>([]);

/** Names, not full `SkillSummary` objects — serializes straight into
 *  `MessageCreate.attached_skills` at send time, and survives
 *  `skillsAtom` being refreshed/replaced. */
export const selectedSkillNamesAtom = atom<string[]>([]);

export const selectedSkillsAtom = atom((get) => {
  const names = get(selectedSkillNamesAtom);
  return get(skillsAtom).filter((s) => names.includes(s.name));
});

//User-authored skills — a distinct resource from the catalog above
// (`/api/v1/user-skills`, see services/skillClient.ts's `userSkillClient`).
export const userSkillsAtom = atom<UserSkillResponse[]>([]);
export const userSkillVersionsAtom = atom<UserSkillVersionItem[]>([]);

//Models — populated by services/modelClient.ts's `modelClient.get()`,
// self-invoked at module load.
export const modelsAtom = atom<ModelListResponse>({ object: "list", data: [] });
export const selectedModelIdAtom = atom<string | null>(null);

//Playbooks — populated by services/playbookClient.ts's `playbookClient.get()`.
// Not self-invoked (no consumer yet — see the client's own docstring).
export const playbooksAtom = atom<Playbook[]>([]);

//Inference tier — populated by services/tierClient.ts's `tierClient.get()`.
// Not self-invoked (no consumer yet — Header.tsx's tier pill is inert
// and Header isn't currently rendered by App.tsx).
export const currentTierAtom = atom<CurrentTierResponse | null>(null);

/* #endregion */

export function resetStoreForTests(): void {
  store.set(skillsAtom, []);
  store.set(selectedSkillNamesAtom, []);
  store.set(userSkillsAtom, []);
  store.set(userSkillVersionsAtom, []);

  store.set(composerDraftAtom, "");
  store.set(stickyEnabledAtom, false);
  store.set(stickyDirtyAtom, false);
  store.set(modelsAtom, { object: "list", data: [] });
  store.set(selectedModelIdAtom, null);
  store.set(playbooksAtom, []);
  store.set(currentTierAtom, null);
  store.set(documentChatTurnsAtom, []);
  store.set(documentChatSendingAtom, false);
}

/* #region  CreateField Atom */

// The Field Atom selects a slice of a larger atom and allows atomic writes,
// which then propgates to components and rerenders as necessary.

// Overload with a defaultValue narrows away `undefined` for optional Root fields,
// so consumers of e.g. shortcutsAtom don't each need their own fallback.
export function createFieldAtom<Root, K extends keyof Root>(
  rootAtom: PrimitiveAtom<Root>,
  key: K,
  defaultValue: NonNullable<Root[K]>
): PrimitiveAtom<NonNullable<Root[K]>>;
export function createFieldAtom<Root, K extends keyof Root>(
  rootAtom: PrimitiveAtom<Root>,
  key: K
): PrimitiveAtom<Root[K]>;
export function createFieldAtom<Root, K extends keyof Root>(
  rootAtom: PrimitiveAtom<Root>,
  key: K,
  defaultValue?: NonNullable<Root[K]>
) {
  return atom(
    (get) => get(rootAtom)[key] ?? defaultValue,
    (get, set, update: Root[K] | ((prev: Root[K]) => Root[K])) => {
      const rootPrev = get(rootAtom);
      const prev = (rootPrev[key] ?? defaultValue) as Root[K];
      const next =
        typeof update === "function" ? (update as (p: Root[K]) => Root[K])(prev) : update;

      if (Object.is(prev, next)) return;
      set(rootAtom, { ...rootPrev, [key]: next });
    }
  );
}

/* #endregion */
