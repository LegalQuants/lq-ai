import {
  store,
  skillsAtom,
  selectedSkillNamesAtom,
  userSkillsAtom,
  userSkillVersionsAtom,
} from "@/store";
import { actions } from "@/actions";
import type { SkillSummary } from "@/domain/types";
import {
  listSkillsApiV1SkillsGet,
  autocompleteSkillsApiV1SkillsAutocompleteGet,
  getSkillApiV1SkillsSkillNameGet,
  getSkillContentsApiV1SkillsSkillNameContentsGet,
  getSkillInputsApiV1SkillsSkillNameInputsGet,
  forkSkillApiV1SkillsSkillNameForkPost,
  listUserSkillsApiV1UserSkillsGet,
  createUserSkillApiV1UserSkillsPost,
  updateUserSkillApiV1UserSkillsSkillIdPatch,
  deleteUserSkillApiV1UserSkillsSkillIdDelete,
  listUserSkillVersionsApiV1UserSkillsSkillIdVersionsGet,
} from "@/generated/sdk.gen";
import type {
  SkillAutocompleteItem,
  SkillInputs,
  UserSkillCreate,
  UserSkillUpdate,
} from "@/generated/types.gen";

/**
 * Skill-catalog network calls (`GET/POST /api/v1/skills*`) — read-mostly:
 * browse, inspect, and fork built-in/team skills into a user-owned copy.
 * Distinct from `userSkillClient` below (`/api/v1/user-skills`), which
 * owns full CRUD over skills the user authored directly — see its own
 * docstring.
 *
 * Response bodies for list/get-one/contents/fork come back untyped
 * (`unknown`) from the generated client — those handlers forward domain
 * dicts without a declared `response_model` — so those are cast to this
 * codebase's own `SkillSummary` (domain/types.ts), same caveat as
 * documented in ../../CLAUDE.md's "Type fidelity varies by endpoint".
 *
 * Selection (`toggleSelected`/`clearSelected`) is a flat "currently
 * applied" list (`selectedSkillNamesAtom`), resent on every turn until
 * removed — no sticky/non-sticky distinction.
 */
export const skillClient = {
  /** `GET /api/v1/skills` — default scope surfaces built-in, user, and
   *  team skills together, matching the composer's skill picker. Called
   *  once from `services/bootstrap.ts`'s `initializeApp()` after login;
   *  call again to refresh (e.g. after a fork changes what's available). */
  async get(): Promise<void> {
    const { data, error } = await listSkillsApiV1SkillsGet();
    if (error || !data) {
      actions.showNotification(`Error Loading Skills`);
      return;
    }
    store.set(skillsAtom, data as SkillSummary[]);
  },

  /** `GET /api/v1/skills/{skill_name}` — single skill detail. Returned
   *  directly to the caller, not cached in the store — a global atom
   *  for a single on-demand lookup would be a "last write wins" race the
   *  moment two callers looked up different skills concurrently. Hold it
   *  in local component state if you need to render it. */
  async getOne(name: string): Promise<SkillSummary | undefined> {
    const { data, error } = await getSkillApiV1SkillsSkillNameGet({
      path: { skill_name: name },
    });
    if (error || !data) {
      actions.showNotification(`Error loading skill "${name}"`);
      return undefined;
    }
    return data as SkillSummary;
  },

  /** `GET /api/v1/skills/autocomplete` — substring search over slug/title;
   *  empty `q` returns recents per the endpoint's own doc comment.
   *  Returned directly, not stored (see `getOne`'s docstring). */
  async autocomplete(q = "", limit?: number): Promise<SkillAutocompleteItem[] | undefined> {
    const { data, error } = await autocompleteSkillsApiV1SkillsAutocompleteGet({
      query: { q, limit },
    });
    if (error || !data) {
      actions.showNotification("Error searching skills");
      return undefined;
    }
    return data.results;
  },

  /** `GET /api/v1/skills/{skill_name}/contents` — the skill's raw
   *  Markdown body (SKILL.md), e.g. for a future "view source"
   *  affordance. Returned directly, not stored (see `getOne`'s
   *  docstring). */
  async contents(name: string): Promise<string | undefined> {
    const { data, error } = await getSkillContentsApiV1SkillsSkillNameContentsGet({
      path: { skill_name: name },
    });
    if (error || !data) {
      actions.showNotification(`Error loading contents for "${name}"`);
      return undefined;
    }
    return data as string;
  },

  /** `GET /api/v1/skills/{skill_name}/inputs` — the skill's declared
   *  frontmatter input schema, for a future input-binding form. Returned
   *  directly, not stored (see `getOne`'s docstring). */
  async inputs(name: string): Promise<SkillInputs | undefined> {
    const { data, error } = await getSkillInputsApiV1SkillsSkillNameInputsGet({
      path: { skill_name: name },
    });
    if (error || !data) {
      actions.showNotification(`Error loading inputs for "${name}"`);
      return undefined;
    }
    return data;
  },

  /** `POST /api/v1/skills/{skill_name}/fork` — clones a built-in/team
   *  skill into a user-owned editable copy. Omit `newName` to shadow the
   *  source slug (same name; the user-scope copy wins on lookup). M1
   *  only supports `scope: "user"` — `"team"` 400s until ADR 0012's
   *  D8.1 lands (per the endpoint's own doc comment). Refreshes both the
   *  catalog and the user-skills list on success, since a fork changes
   *  both. */
  async fork(name: string, newName?: string, scope: "user" | "team" = "user"): Promise<void> {
    const { error } = await forkSkillApiV1SkillsSkillNameForkPost({
      path: { skill_name: name },
      body: { new_name: newName, scope },
    });
    if (error) {
      actions.showNotification(`Error forking "${name}"`);
      return;
    }
    await Promise.all([skillClient.get(), userSkillClient.get()]);
  },

  toggleSelected(name: string): void {
    store.set(selectedSkillNamesAtom, (prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]
    );
  },

  clearSelected(): void {
    store.set(selectedSkillNamesAtom, []);
  },
};

/**
 * User-authored skill CRUD (`/api/v1/user-skills`) — a distinct resource
 * from the catalog above: skills the signed-in user wrote or forked
 * directly, with full ownership (create/update/delete + version
 * history). Unlike `skillClient`, every response here is properly typed
 * (`UserSkillResponse`) — these handlers declare a real `response_model`.
 *
 * No word-addin UI calls this yet — there's no skill-authoring flow in
 * the task pane. Wired up ahead of that per CLAUDE.md's "preferred
 * implementation going forward" note (use the generated functions), not
 * because something currently renders it — so `get()` is *not*
 * self-invoked at module load the way `skillClient.get()` is; call it
 * explicitly wherever a user-skills UI ends up.
 */
export const userSkillClient = {
  /** `GET /api/v1/user-skills`. */
  async get(): Promise<void> {
    const { data, error } = await listUserSkillsApiV1UserSkillsGet();
    if (error || !data) {
      actions.showNotification("Error loading your skills");
      return;
    }
    store.set(userSkillsAtom, data);
  },

  /** `POST /api/v1/user-skills`. Appends the new skill to
   *  `userSkillsAtom` on success rather than refetching the whole list. */
  async create(body: UserSkillCreate): Promise<void> {
    const { data, error } = await createUserSkillApiV1UserSkillsPost({ body });
    if (error || !data) {
      actions.showNotification("Error creating skill");
      return;
    }
    store.set(userSkillsAtom, (prev) => [...prev, data]);
  },

  /** `PATCH /api/v1/user-skills/{skill_id}`. */
  async update(id: string, body: UserSkillUpdate): Promise<void> {
    const { data, error } = await updateUserSkillApiV1UserSkillsSkillIdPatch({
      path: { skill_id: id },
      body,
    });
    if (error || !data) {
      actions.showNotification("Error updating skill");
      return;
    }
    store.set(userSkillsAtom, (prev) => prev.map((s) => (s.id === id ? data : s)));
  },

  /** `DELETE /api/v1/user-skills/{skill_id}` — `204 No Content`. */
  async delete(id: string): Promise<void> {
    const { error } = await deleteUserSkillApiV1UserSkillsSkillIdDelete({
      path: { skill_id: id },
    });
    if (error) {
      actions.showNotification("Error deleting skill");
      return;
    }
    store.set(userSkillsAtom, (prev) => prev.filter((s) => s.id !== id));
  },

  /** `GET /api/v1/user-skills/{skill_id}/versions`. */
  async versions(id: string): Promise<void> {
    const { data, error } = await listUserSkillVersionsApiV1UserSkillsSkillIdVersionsGet({
      path: { skill_id: id },
    });
    if (error || !data) {
      actions.showNotification("Error loading skill versions");
      return;
    }
    store.set(userSkillVersionsAtom, data.items);
  },
};
