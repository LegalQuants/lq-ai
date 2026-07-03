# Referenced files in the chat composer — `@`-mention + multi-select picker (referenced-files Phase 2, frontend)

> **Type:** Frontend delivery of a shipped backend channel (referenced-files Phase 1, ADR 0022).
> **Affected subsystem:** Web (`web/src/lib/lq-ai/`) only. **No backend changes.**
> **Related:** referenced-files PRD §9 entry (Phase 2 deferred item), ADR 0022, spec
> `2026-07-02-chat-at-mention-file-retrieval-design.md` (parent design; this document narrows its
> frontend section to what Phase 1 actually shipped).

---

## Goal

Let a user reference matter documents in a chat message from the composer — via an inline
`@filename` mention or a multi-select file dropdown — so the message is sent with
`referenced_file_ids` and the answer comes back with verified, deep-linkable citations grounded in
those files. The backend channel (validation, file-scoped retrieval, citation wiring, audit, echo)
is fully shipped on `feat/referenced-files-referenced-file-ids`; this spec covers only the composer UX and
wire-up.

## Constraints inherited from the shipped backend (ADR 0022)

- KB-only MVP + matter scope: a referenceable file is caller-owned, `ready`, and in a Knowledge
  Base attached to the chat's project. Anything else 404s the whole send, id-probing-safe.
- Projectless chats can reference nothing (404). The UI must not offer the affordance there.
- Cap: `MESSAGE_REFERENCED_FILES_MAX_LEN = 16` ids per message (422 over-cap).
- Echo: validated ids return as `applied_referenced_file_ids` on the non-streaming response and the
  SSE `complete` frame. On success it always equals the requested set (validation is all-or-nothing).
- `GET /api/v1/files` (DE-296) does not exist. The referenceable set is reachable today via
  `GET /projects/{id}` → `attached_knowledge_base_ids` → `GET /knowledge-bases/{kb_id}/files`.

## Design

### One authoritative set

`ChatPanel.svelte` gains `referencedFiles: Map<string, ReferencedFile>` where
`ReferencedFile = { id, filename, ready }`. Both entry interfaces mutate this one map; it is
deduped by construction and capped at 16 (adds beyond the cap are rejected with a visible hint).
The set is:

- sent as `referenced_file_ids: [...referencedFiles.keys()]` on the message body when non-empty;
- cleared after a successful send (turn-scoped, like the backend channel);
- preserved on send failure so the user can adjust and retry;
- rendered as a chips row above the composer (`ReferencedFilesChips.svelte`), each chip removable.

### Referenceable-files loading (`src/lib/lq-ai/files/referenceable.ts`, new)

`loadReferenceableFiles(projectId)`:
`projectsApi.getProject(projectId)` → for each `attached_knowledge_base_ids`, call
`knowledgeBasesApi.listKnowledgeBaseFiles(kbId)` (`Promise.all`) → merge, dedupe by file id, sort
by filename. Every row carries `ready = (ingestion status === 'ready')`; non-ready rows render
disabled with a "Preparing…" badge — visible but never selectable (fail-restrictive made visible,
P4). A per-KB fetch failure degrades to the union of the KBs that did load, with a non-blocking
error note in the picker.

Fetched on first open of either affordance for the current chat's project; cached in component
state; refreshed on picker re-open. Client-side substring filtering (pure helper
`filterReferenceable(files, query)`) — no server autocomplete endpoint is added.

### Entry interface 1 — multi-select picker (`FilePickerDropdown.svelte`, new)

A composer toolbar button (document icon, beside the existing Attach-KB 📎, rendered only when the
chat has a project) opens a dropdown: search input on top (pattern: `SkillPicker`), checkbox rows
(pattern: `AttachKBModal`'s `Set` + checkbox rows), live-toggling `referencedFiles` directly — no
confirm step; the chips row reflects changes immediately. Empty states: "No knowledge bases
attached to this matter" / "No documents ready to reference" / no-search-hits.

### Entry interface 2 — inline `@`-mention (`MentionPopover.svelte`, new)

Clone of `SlashPopover.svelte` (same keyboard-nav, race-guard, five render states, pure exported
helpers), backed by the same loaded referenceable list with client-side filtering rather than a
server autocomplete.

- `detectMentionAt(text, caret)` — module-scope pure helper in `ChatPanel.svelte` mirroring
  `detectSlashAt`, but triggering on `@` at a word start **anywhere** in the text (start of text or
  preceded by whitespace; `a@b` never triggers). Returns `{ open, query, atIndex }`.
- Selection behavior: complete the mention inline — the partial `@query` becomes `@<filename>` in the composer, stays readable as part of the message, and rides into the sent `content` (so the case name is part of the retrieval query). The file is added to `referencedFiles`; the chips row remains the authoritative id set (removing a chip removes the reference, not the text).
- Coexistence with the slash popover: slash triggers only at line start with `/`; mention triggers
  on `@`; at most one popover is open (the most recent trigger wins, the other closes).

### Send / receive wiring

- `types.ts`: `MessageCreate.referenced_file_ids?: string[]`;
  `MessagePostResponse.applied_referenced_file_ids?: string[]`;
  `MessageCompleteFrame.applied_referenced_file_ids?: string[]`.
- `ChatPanel.sendMessage()`: include the field when the set is non-empty; on success clear the set.
  Stamp the sent user message (local model) with the referenced `{id, filename}` list so the user
  bubble shows a compact "Referenced: …" row.
- SSE `onComplete` (and the non-streaming path): read `applied_referenced_file_ids`; it is
  informational parity with `applied_file_ids` (on success it equals the request set — asserted in
  tests, not re-rendered separately).
- Send failure 404 (a file went un-ready / was detached between load and send): existing error
  surface shows the message; the set is preserved; the picker's refresh-on-open picks up the new
  state. No special-case UI.
- Citations: zero changes. Referenced-file citations arrive through the shipped
  `M2Citations` chips / ledger panel / deep-link viewer.

### Out of scope

- Phase 3 embed-on-reference (backend), any new backend route or autocomplete endpoint.
- Fixing `MatterRailFiles.openPicker()`'s call to the nonexistent `GET /files?owner_id=me`
  (405 today) — **pre-existing bug, file as a separate DE**.
- Wiring `AttachedFilesPanel`'s local-only chat attach into the verbatim `file_ids` channel
  (explicitly TBD-post-M1 in `files.ts`; unrelated channel).
- Rich contenteditable token pills in the composer.

## Testing

- **Vitest** (fork convention: pure module-scope helpers, no `@testing-library/svelte`):
  `detectMentionAt` (trigger positions, mid-word non-trigger, query extraction, caret edge cases);
  `filterReferenceable`; set add/remove/dedupe/cap-16 logic; the mention splice function;
  `MentionPopover` exported helpers (nextIndex/decideKeyAction parity with `SlashPopover`);
  merge/dedupe in `referenceable.ts` (multi-KB overlap, non-ready flagging, partial KB failure).
- **Cypress** (`web/cypress/e2e/referenced-files-referenced-files.cy.ts`, stubbed API): picker flow (open →
  search → check two files → chips appear → send → intercepted request body carries both ids →
  chips clear); mention flow (`@con` → popover → Enter → text spliced, chip added); disabled
  "Preparing…" row not selectable; no picker button on a projectless chat.
- Dev-stack check: the `web` container serves a static bundle — rebuild `web` to verify in the
  running stack.

## Documentation (same PR)

- PRD §9 referenced-files section: move Phase 2 from **Deferred** to shipped, describing both affordances.
- PRD §3.1: one line noting the composer affordances feeding `referenced_file_ids`.
- No OpenAPI change (no contract change), no new ADR (no new design fork; ADR 0022 already records
  the channel).

## Acceptance criteria

- With a project chat whose matter KBs contain ready files: both the picker and `@`-mention add
  files to one deduped chip set; a selected mention stays inline in the message text and in the sent content; sending produces a request with `referenced_file_ids`; the answer
  renders verified citations that deep-link into the referenced document(s) via the existing panel.
- Non-ready files are visible but not selectable ("Preparing…").
- Cap 16 enforced client-side (and the backend 422 is never triggerable through the UI).
- Projectless chats show neither affordance.
- Pure-helper unit tests and the Cypress spec pass; existing chat specs unaffected.
