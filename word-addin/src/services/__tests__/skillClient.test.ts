import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/generated/sdk.gen", () => ({
  listSkillsApiV1SkillsGet: vi.fn(),
  autocompleteSkillsApiV1SkillsAutocompleteGet: vi.fn(),
  getSkillApiV1SkillsSkillNameGet: vi.fn(),
  getSkillContentsApiV1SkillsSkillNameContentsGet: vi.fn(),
  getSkillInputsApiV1SkillsSkillNameInputsGet: vi.fn(),
  forkSkillApiV1SkillsSkillNameForkPost: vi.fn(),
  listUserSkillsApiV1UserSkillsGet: vi.fn(),
  createUserSkillApiV1UserSkillsPost: vi.fn(),
  updateUserSkillApiV1UserSkillsSkillIdPatch: vi.fn(),
  deleteUserSkillApiV1UserSkillsSkillIdDelete: vi.fn(),
  listUserSkillVersionsApiV1UserSkillsSkillIdVersionsGet: vi.fn(),
}));

vi.mock("@/actions", () => ({ actions: { showNotification: vi.fn() } }));

import {
  listSkillsApiV1SkillsGet,
  autocompleteSkillsApiV1SkillsAutocompleteGet,
  getSkillApiV1SkillsSkillNameGet,
  forkSkillApiV1SkillsSkillNameForkPost,
  listUserSkillsApiV1UserSkillsGet,
  createUserSkillApiV1UserSkillsPost,
  updateUserSkillApiV1UserSkillsSkillIdPatch,
  deleteUserSkillApiV1UserSkillsSkillIdDelete,
} from "@/generated/sdk.gen";
import {
  store,
  resetStoreForTests,
  skillsAtom,
  selectedSkillNamesAtom,
  selectedSkillsAtom,
  userSkillsAtom,
} from "@/store";
import { skillClient, userSkillClient } from "@/services/skillClient";
import { actions } from "@/actions";
import type { SkillSummary } from "@/domain/types";
import type { UserSkillResponse } from "@/generated/types.gen";

const SKILLS: SkillSummary[] = [
  { name: "nda-review", version: "1.0.0", scope: "builtin", title: "NDA Review" },
  { name: "msa-review", version: "1.0.0", scope: "builtin", title: "MSA Review" },
];

const USER_SKILL: UserSkillResponse = {
  id: "skill-1",
  scope: "user",
  slug: "my-nda-review",
  display_name: "My NDA Review",
  description: "A forked copy",
  version: "1.0.0",
  body: "...",
  created_at: "2026-07-15T00:00:00Z",
  updated_at: "2026-07-15T00:00:00Z",
};

describe("skillClient", () => {
  beforeEach(() => {
    resetStoreForTests();
    vi.mocked(listSkillsApiV1SkillsGet).mockReset();
    vi.mocked(autocompleteSkillsApiV1SkillsAutocompleteGet).mockReset();
    vi.mocked(getSkillApiV1SkillsSkillNameGet).mockReset();
    vi.mocked(forkSkillApiV1SkillsSkillNameForkPost).mockReset();
    vi.mocked(listUserSkillsApiV1UserSkillsGet).mockReset();
    vi.mocked(actions.showNotification).mockReset();
  });

  it("get() populates skillsAtom on success", async () => {
    vi.mocked(listSkillsApiV1SkillsGet).mockResolvedValue({ data: SKILLS, error: undefined });

    await skillClient.get();

    expect(listSkillsApiV1SkillsGet).toHaveBeenCalled();
    expect(store.get(skillsAtom)).toEqual(SKILLS);
  });

  it("get() notifies instead of throwing on failure", async () => {
    vi.mocked(listSkillsApiV1SkillsGet).mockResolvedValue({
      data: undefined,
      error: { detail: [] },
    });

    await skillClient.get();

    expect(store.get(skillsAtom)).toEqual([]);
    expect(actions.showNotification).toHaveBeenCalledWith("Error Loading Skills", false);
  });

  it("getOne() returns the fetched skill to the caller", async () => {
    vi.mocked(getSkillApiV1SkillsSkillNameGet).mockResolvedValue({
      data: SKILLS[0],
      error: undefined,
    });

    const result = await skillClient.getOne("nda-review");

    expect(getSkillApiV1SkillsSkillNameGet).toHaveBeenCalledWith({
      path: { skill_name: "nda-review" },
    });
    expect(result).toEqual(SKILLS[0]);
  });

  it("autocomplete() returns the search results to the caller", async () => {
    const results = [{ slug: "nda-review", title: "NDA Review", scope: "builtin" as const }];
    vi.mocked(autocompleteSkillsApiV1SkillsAutocompleteGet).mockResolvedValue({
      data: { results },
      error: undefined,
    });

    const result = await skillClient.autocomplete("nda");

    expect(autocompleteSkillsApiV1SkillsAutocompleteGet).toHaveBeenCalledWith({
      query: { q: "nda", limit: undefined },
    });
    expect(result).toEqual(results);
  });

  it("fork() refreshes both the catalog and the user-skills list on success", async () => {
    vi.mocked(forkSkillApiV1SkillsSkillNameForkPost).mockResolvedValue({
      data: undefined,
      error: undefined,
    });
    vi.mocked(listSkillsApiV1SkillsGet).mockResolvedValue({ data: SKILLS, error: undefined });
    vi.mocked(listUserSkillsApiV1UserSkillsGet).mockResolvedValue({
      data: [USER_SKILL],
      error: undefined,
    });

    await skillClient.fork("nda-review", "my-nda-review");

    expect(forkSkillApiV1SkillsSkillNameForkPost).toHaveBeenCalledWith({
      path: { skill_name: "nda-review" },
      body: { new_name: "my-nda-review", scope: "user" },
    });
    expect(store.get(skillsAtom)).toEqual(SKILLS);
    expect(store.get(userSkillsAtom)).toEqual([USER_SKILL]);
  });

  it("fork() notifies without refreshing on failure", async () => {
    vi.mocked(forkSkillApiV1SkillsSkillNameForkPost).mockResolvedValue({
      data: undefined,
      error: { detail: [] },
    });

    await skillClient.fork("nda-review");

    expect(listSkillsApiV1SkillsGet).not.toHaveBeenCalled();
    expect(actions.showNotification).toHaveBeenCalledWith('Error forking "nda-review"');
  });

  it("toggleSelected attaches then detaches a skill name", () => {
    skillClient.toggleSelected("nda-review");
    expect(store.get(selectedSkillNamesAtom)).toEqual(["nda-review"]);

    skillClient.toggleSelected("nda-review");
    expect(store.get(selectedSkillNamesAtom)).toEqual([]);
  });

  it("selectedSkillsAtom derives full SkillSummary objects for selected names", async () => {
    vi.mocked(listSkillsApiV1SkillsGet).mockResolvedValue({ data: SKILLS, error: undefined });
    await skillClient.get();

    skillClient.toggleSelected("msa-review");
    expect(store.get(selectedSkillsAtom)).toEqual([SKILLS[1]]);
  });

  it("clearSelected empties the selection", () => {
    skillClient.toggleSelected("nda-review");
    skillClient.toggleSelected("msa-review");
    skillClient.clearSelected();
    expect(store.get(selectedSkillNamesAtom)).toEqual([]);
  });
});

describe("userSkillClient", () => {
  beforeEach(() => {
    resetStoreForTests();
    vi.mocked(listUserSkillsApiV1UserSkillsGet).mockReset();
    vi.mocked(createUserSkillApiV1UserSkillsPost).mockReset();
    vi.mocked(updateUserSkillApiV1UserSkillsSkillIdPatch).mockReset();
    vi.mocked(deleteUserSkillApiV1UserSkillsSkillIdDelete).mockReset();
    vi.mocked(actions.showNotification).mockReset();
  });

  it("get() populates userSkillsAtom", async () => {
    vi.mocked(listUserSkillsApiV1UserSkillsGet).mockResolvedValue({
      data: [USER_SKILL],
      error: undefined,
    });

    await userSkillClient.get();

    expect(store.get(userSkillsAtom)).toEqual([USER_SKILL]);
  });

  it("create() appends the new skill without refetching the list", async () => {
    vi.mocked(createUserSkillApiV1UserSkillsPost).mockResolvedValue({
      data: USER_SKILL,
      error: undefined,
    });

    await userSkillClient.create({
      slug: "my-nda-review",
      display_name: "My NDA Review",
      description: "A forked copy",
      body: "...",
    });

    expect(store.get(userSkillsAtom)).toEqual([USER_SKILL]);
    expect(listUserSkillsApiV1UserSkillsGet).not.toHaveBeenCalled();
  });

  it("update() replaces the matching skill in place", async () => {
    store.set(userSkillsAtom, [USER_SKILL]);
    const updated = { ...USER_SKILL, display_name: "Renamed" };
    vi.mocked(updateUserSkillApiV1UserSkillsSkillIdPatch).mockResolvedValue({
      data: updated,
      error: undefined,
    });

    await userSkillClient.update("skill-1", { display_name: "Renamed" });

    expect(store.get(userSkillsAtom)).toEqual([updated]);
  });

  it("delete() removes the skill from userSkillsAtom", async () => {
    store.set(userSkillsAtom, [USER_SKILL]);
    vi.mocked(deleteUserSkillApiV1UserSkillsSkillIdDelete).mockResolvedValue({
      data: undefined,
      error: undefined,
    });

    await userSkillClient.delete("skill-1");

    expect(store.get(userSkillsAtom)).toEqual([]);
  });
});
