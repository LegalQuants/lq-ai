# Reference matter documents in a chat message (`@`-mention + multi-select picker) with verified citations

> **Type:** New feature.
> **Affected subsystem:** Web (chat UI), Backend (API).
> **Related:** Resolves Contract QA scoping open
> question (`docs/PRD.md` §3, "user-selected document set"); builds on §3.1 per-message file channel
> and §3.3 Citation Engine.

---

## Use case

Let a user **reference documents from the current matter inside a chat message** — by typing an
inline `@filename` mention **or** by picking files from a multi-select dropdown — and **ask
questions about those files**, getting back an answer with **verified citations that deep-link into
the referenced document(s)** via the doc panel.

Two entry interfaces, one destination:

- **Inline `@`-mention** — type `@`, a dropdown filters the matter's files as you type; selecting inserts a token.
- **Multi-select file picker** — a composer toolbar button opens a dropdown of the matter's files; check several, confirm.

Both feed the **same authoritative referenced-files set**, sent on the message, which drives
**file-scoped retrieval + citations**.

---

## Why this can't be met today

The rails exist but are disconnected. Concretely:

1. **The per-message file channel injects verbatim text and never produces citations.**
   Chat send accepts `file_ids`, but `_load_attached_file_contexts` pulls each file's full
   `Document.normalized_content` and `_format_attached_files_block` injects it verbatim as a system
   block (`api/app/api/chats.py:415`, `:1129`, `:1494-1505`). Citations are minted only from
   `retrieved_chunks`: `_persist_message_citations` early-returns on empty and is called at every
   site with `retrieved_chunks` only, never the attached-file contexts (`chats.py:2560`, `:2604`,
   call sites `:2934/:3187/:3530`). **So attaching a file today can make the model read it, but can
   never yield a citation.**

2. **Retrieval is KB-and-project-scoped only, with no per-file scope.**
   `_retrieve_kb_context_for_chat` returns `([],[])` unless `chat.project_id` is set **and** a KB is
   attached to that project (`chats.py:975`, gates `:1002-1007`). `hybrid_search` filters
   `kbf.kb_id = :kb_id AND f.ingestion_status = 'ready'` (`api/app/knowledge/retrieval.py:71`,
   `:190-201`) — there is no way to scope retrieval to a user-selected set of files.

3. **Only KB-attach embeds.** `enqueue_embed_job` fires on KB attach only
   (`api/app/api/knowledge_bases.py:518-532`); project-attached and loose-uploaded files are chunked
   but keep `embedding = NULL` (`api/app/knowledge/embed.py:266`) → invisible to vector search. A
   file a user wants to reference may have no embeddings.

4. **No file-list surface to populate a picker or `@`-dropdown.** Only `POST /api/v1/files`,
   `GET /api/v1/files/{id}`, `DELETE` exist — there is no `GET /api/v1/files` list route.
   (This is exactly what **DE-296** proposes to build.)

5. **No `@`-mention affordance and no composer file picker** exist in `web/`. The only "file
   picker" UIs are skill-input forms (`docs/PRD.md` §3.4/§3.9) and the tabular wizard (DE-296).

What *is* already shipped and reused unchanged: the **Citation Engine** (extract → verbatim/tolerant/
paraphrase/ensemble verify → persist) and its **side-panel deep-link viewer**
(`api/app/citation/*`, `GET /api/v1/documents/{id}/render?page&highlight`, `docs/PRD.md` §3.3
lines ~436-503). This feature's citations flow straight into that surface.

---

## Proposed approach

**Scope:** how a user-selected referenced-files set is *collected* in the composer and *grounded*
for retrieval + citations. Reuses the shipped Citation Engine, verification cascade, and doc-panel
viewer as-is.

### Backend

**New request field — `referenced_file_ids` (do not overload `file_ids`).**
Add an optional `referenced_file_ids: list[UUID]` to `MessageCreateRequest`
(`api/app/schemas/chats.py`), distinct from the existing verbatim `file_ids` channel. Semantics:
referenced files are **routed through retrieval as chunks** (citation-eligible), whereas `file_ids`
keeps its current verbatim-full-text behavior (small-doc, no citations). Cap with a new
`MESSAGE_REFERENCED_FILES_MAX` constant, mirroring `MESSAGE_FILE_IDS_MAX_LEN`.

*Fork surfaced (P10):* alternative is to change `file_ids` to be retrieval-grounded — rejected as a
breaking change to a shipped channel (#116/#117). See "Decisions to surface."

**Generalize retrieval to a file-id set.**
Extend `hybrid_search` (`api/app/knowledge/retrieval.py`) with an optional `file_ids` filter that
searches `document_chunks` scoped by `f.id = ANY(:file_ids)` directly (bypassing the `kbf` join), so
referenced files may span multiple KBs, project files, or loose uploads. Keep the existing
`kb_id` path intact. Retain the `ingestion_status='ready'` + `deleted_at IS NULL` guards. Reuse the
existing vector-cosine + FTS + `hybrid_alpha` combination — no new search path.

**Retrieval strategy for explicit references.**
Unlike KB-wide top-k, an explicitly-referenced file usually means "answer over *this* document." Use
a per-referenced-file budget (e.g. all chunks of a referenced file up to a token cap, query-ranked)
rather than a global top-k that could starve a referenced file of representation. Merge referenced-
file chunks with any KB-RAG chunks into the single `retrieved_chunks` set the Citation Engine
already consumes; enforce a total cap (extend `RAG_MAX_TOTAL_CHUNKS`).

**Wire referenced chunks into citations.**
Include the referenced-file chunks in `retrieved_chunks` at all three `_persist_message_citations`
call sites so extraction/verification/persistence runs over them unchanged. The system-prompt
retrieval-context block (`_format_retrieval_context_block`, `chats.py:1074`) already carries the
`"…verbatim…" (Source: [N])` instruction — referenced chunks join the same numbered set.

**Embedding of referenced-but-unembedded files.**
Referencing a file that has `embedding = NULL` (project-attached / loose upload) must either embed on
demand or be disallowed. *Fork surfaced (P10)* — see "Decisions to surface." Whichever path, an
un-embedded / still-`processing` referenced file **fails restrictive (P4)**: it is reported as
"preparing / not yet available," never silently dropped and never falling back to broad search.

**`GET /api/v1/files` (dependency on DE-296).**
The picker and `@`-dropdown need the list endpoint DE-296 specifies (cursor pagination,
`search`, optional `project_id`, `document_id` via LEFT JOIN `documents`, caller-owned + admin-all,
soft-deleted excluded). **Do not re-spec it here** — depend on DE-296; if DE-296 has not landed,
this feature delivers the endpoint to that spec (and DE-296 consumes it). Adding the route requires
the collision-guard updates: `IMPLEMENTED_ROUTES` (`api/tests/test_endpoints.py`) and the path
count + `EXPECTED_PATHS` in `api/tests/test_openapi.py`, plus the entry in
`docs/api/backend-openapi.yaml`.

**Audit (P3, P5).**
Record an `inference.message_referenced_files` audit row modeled on the existing
`inference.message_files_attached` — `referenced_file_ids`, requested/resolved/retrieved counts,
digests only, **never** content or the query text — flushed inside the caller's transaction.

### Frontend (`web/`, SvelteKit — no React)

- **Referenced-files state:** one authoritative, deduped set keyed by `file_id`, fed by both entry
  interfaces, sent as `referenced_file_ids`. Disable rows without a `document_id` ("Not yet parsed"),
  mirroring DE-296's picker.
- **Multi-select picker:** composer toolbar button → dropdown backed by `listFiles({ project_id?,
  search?, cursor? })` (`web/src/lib/lq-ai/api/files.ts`; reuse patterns from
  `MatterRailFiles.svelte`, `AttachedFilesPanel.svelte`, `PlaybookExecuteModal.svelte`).
- **`@`-mention:** composer decorator that opens the same filtered list on `@`, resolves selection to
  a `file_id` token, and syncs token add/remove with the referenced-files set.
- **Citations:** existing citation chips + side-panel deep-link viewer — no new UI; referenced-file
  citations render through the shipped surface.

### Tests & docs

- Backend: unit (schema/validation/cap), integration (`hybrid_search` file-id scope; referenced
  chunks reach `retrieved_chunks`; citations persist; authz; `ready`-gating; embed-on-reference path
  if chosen), OpenAPI-conformance for `GET /api/v1/files`.
- Frontend: `files.ts` unit tests; composer picker + `@`-mention; Cypress e2e (reference a file →
  ask → verified citation → deep-link opens viewer).
- Docs (part of the change per CLAUDE.md): PRD §3.1/§3.3 note the referenced-files channel; DB schema
  doc if a column/index is added; `backend-openapi.yaml`; an ADR for the `referenced_file_ids`-vs-
  `file_ids` decision and the file-id retrieval scope.

### Delivery (recommended phasing)

Backend is built once; the two entry interfaces layer on top.

1. **Phase 1 (MVP):** `referenced_file_ids` + file-id-scoped retrieval + citation wiring + **picker**
   UI (+ `GET /api/v1/files` if DE-296 hasn't landed). Restrict referenceable files to
   already-embedded (KB) files if embed-on-reference is deferred.
2. **Phase 2:** `@`-mention composer affordance (same backend).
3. **Phase 3 (optional):** embed-on-reference for project/loose files, if deferred from Phase 1.

---

## Acceptance criteria

- A user can reference one or more matter files in a chat message via **either** the multi-select
  picker **or** an inline `@`-mention; both produce the same `referenced_file_ids` set.
- Asking a question about referenced files returns an answer whose claims carry **verified**
  citations (Citation Engine cascade), and clicking a citation **deep-links into the doc panel** at
  the cited passage.
- Retrieval is scoped to the referenced files (spanning KBs / project files / loose uploads as
  applicable); un-`ready`/un-embedded referenced files are reported as "preparing," never silently
  dropped (**P4**).
- `referenced_file_ids` is capped (`MESSAGE_REFERENCED_FILES_MAX`); over-cap is rejected.
- The existing verbatim `file_ids` channel is unchanged (no regression).
- Audit row records counts/digests only, in-transaction (**P3/P5**); OpenAPI + PRD + schema updated
  in the same PR (**P10**).

---

## Decisions to surface (forks for the maintainer — not decided here, per P10)

1. **`referenced_file_ids` (new field) vs. repurposing `file_ids`.** Recommendation: **new field**
   (non-breaking; preserves verbatim-injection use-case). Confirm.
2. **Embedding of non-KB referenced files.** (a) **KB/embedded-only MVP** (simplest; picker offers
   only embedded files); (b) **embed-on-reference** with a "preparing" state (broadest; adds latency +
   a pending path to test). Recommendation: (a) for Phase 1, (b) as Phase 3.
3. **Picker scope — owner vs. matter.** Files owned by the user vs. files in the current
   matter/project (ties to DE-296's `project_id` filter and authz). Recommendation: **matter-scoped**
   when the chat has a project; owner-scoped fallback for projectless chats.
4. **Retrieval strategy for explicit references** — per-file all-chunks-up-to-budget vs. global
   top-k. Recommendation: per-file budget so a referenced file is never starved.
5. **Operator control (P8).** Inherit chat+KB enablement vs. a dedicated capability toggle.
   Recommendation: inherit; state it in the ADR.

---

## Guiding-principles compliance (summary)

- **P1** egress: reuses gateway embedding/generation; no new third-party egress. ✅
- **P2** closed set: referenced set is **UI-selected** and fed to retrieval — **not** a model-callable
  "fetch any file" tool. Keep it that way. ✅
- **P3** payloads: audit counts/digests only. ✅ (must follow)
- **P4** fail restrictive: unauthorized/out-of-matter/un-`ready`/un-embedded → omit or "preparing,"
  never error-open or broad-search fallback. ✅
- **P5** atomic audit: flush in caller transaction (existing pattern). ✅
- **P6** reuse: extend `hybrid_search` / reuse `extract_citations` + `verify`; no re-derivation. ✅
- **P7** irreversibility: read-only. n/a.
- **P8** operator control: decision #5 above.
- **P9** user owns data: **route referenced files through retrieval + the Anonymization Layer as
  grounding chunks**, not a verbatim full-text dump — verbatim is permitted only where citation
  grounding requires it. This is *why* the retrieval-grounded path (not the `file_ids` verbatim path)
  is the correct one. ✅
- **P10** contract-as-truth: OpenAPI/schema/ADR in-PR; forks above surfaced. ✅

The Citation Engine invariant (cite only *retrieved* chunks, verbatim-verified — `docs/PRD.md`
§3.3 / Appendix E) confirms the design: referenced files **must** enter `retrieved_chunks` for
citations to be mintable, so the verbatim-injection path can never yield compliant citations.

---

## Scoped out / explicitly not doing

- **Passive-KB citations bug (orthogonal — file separately).** "KB docs exist but a normal chat
  returns no citations" has two causes: (a) attached files never cite — **fixed** by this feature;
  (b) the chat is projectless or the KB isn't attached to the chat's project, so
  `_retrieve_kb_context_for_chat` short-circuits (`chats.py:1002-1007`) — **not** fixed here, because
  this feature is *explicit* reference. Recommend a **separate bug/DE** for (b) (auto-attach UX, a
  default/owner KB fallback, or clearer "attach KB to project" affordance).
- **Tabular wizard file selection** — owned by **DE-296**; this feature only *depends on* its
  `GET /api/v1/files`.
- **Changing KB-wide RAG behavior for un-referenced chats** — out of scope.
- **New doc-panel viewer** — already shipped (§3.3); reused unchanged.
- **Autonomous-layer file access** — out of scope.
- **Non-PDF citation highlight fidelity** — the viewer highlights via bbox for PDF (§3.3); text-only
  formats may support offset-based highlight only. Documented as a known limitation, not solved here.

---

## Alternatives considered

- **Overload `file_ids` to be retrieval-grounded** — rejected: breaking change to a shipped channel;
  loses the verbatim small-doc use-case.
- **Model-callable "fetch file by name" tool** — rejected: violates **P2** (open surface). Keep the
  set UI-selected.
- **`@`-mention only / picker only** — rejected as the end state; both are wanted. Phasing (picker
  first) is a *delivery* choice, not a scope cut.
- **Standalone `POST /knowledge-bases/{id}/query`** as the mechanism — rejected: it's a raw search
  API decoupled from chat, produces no message/citation persistence.

---

## Additional context

- Depends-on: **DE-296** (`GET /api/v1/files`, picker UX).
- Rides on shipped rails: per-message file channel (`docs/PRD.md` §3.1, `chats.py:337`-equivalent),
  Citation Engine + viewer (`docs/PRD.md` §3.3).
- Resolves for the chat surface the Contract QA open question: *"How does the skill scope a
  multi-document question? … user-selected document set is another [mechanism]."*
- Companion analysis: `docpicker.md` (scope, DE-296/PRD overlap, compliance).
