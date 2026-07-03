# ADR 0022 — `referenced_file_ids`: file-scoped retrieved + cited grounding for chat

**Status:** Accepted and shipped (2026-07-02) — Phase 1, implemented on `feat/referenced-file-ids` (Tasks 1–4) and documented in this task (Task 5).

**Relates to:** [ADR 0016](0016-transparency-and-governance-invariants.md) (P2 closed-set/never-open-surface and P9 user-owns-their-data invariants, both load-bearing for this design), [ADR 0018](0018-citation-ledger-and-fiduciary-grade-output.md) (the citation cascade this feature feeds — unmodified). Realizes **PRD §3.1** (chat API surface) and **PRD §3.3** (Citation Engine retrieval sources).

---

## Context

Chat send (`POST /api/v1/chats/{id}/messages`) already had two document-context channels: `file_ids` (per-message, caller-owned files injected **verbatim** into the prompt, uncited — Donna's ephemeral-document channel) and project-wide KB retrieval (`hybrid_search` over every Knowledge Base attached to the chat's project, feeding the Citation Engine). Neither channel let a caller say "ground this turn specifically in *these* matter documents, and cite what you use." A user reviewing a specific exhibit or a specific prior draft had to either dump its full text via `file_ids` (no citations, no verification) or hope project-wide KB search happened to surface the right chunks.

referenced-files adds a third channel, `referenced_file_ids`: a caller-selected list of matter documents that are **retrieved and cited**, distinct from both `file_ids` (verbatim, uncited) and ordinary KB-wide RAG (implicit, whole-project).

This ADR records the design forks resolved while implementing referenced-files Phase 1 (Tasks 1–4: schema, retrieval primitive, validation, `send_message` wiring) and the two known limitations shipped as-is.

## Decisions

### D1 — A new field, not an overload of `file_ids` (item a)

`referenced_file_ids` is a **new** `MessageCreateRequest` field (cap 16, `MESSAGE_REFERENCED_FILES_MAX_LEN`), not a mode flag on `file_ids`.

Rationale: `file_ids` is contractually verbatim-and-uncited (PRD §3.1, Donna's channel — already distinct from the scalar-only `skill_inputs` channel per the existing schema docstrings) — existing callers depend on that semantic. Overloading it with a "retrieve instead of inject" flag would be a breaking, silent semantic change for every existing caller of `file_ids` and would conflate two genuinely different retrieval strategies (whole-file verbatim injection vs. file-scoped chunk retrieval) behind one wire shape. A new, additive field is non-breaking (omitted/empty is a back-compatible no-op, matching the `file_ids` precedent) and keeps each channel's contract simple and independently documentable. Rejected: a `mode` enum on `file_ids` entries — forks the validation and injection code paths internally anyway, with none of the wire-compatibility benefit.

### D2 — KB-only MVP + matter scope; embed-on-reference deferred to Phase 3 (item b)

`_validate_referenced_file_ids` requires each id to be (1) a caller-owned, non-deleted file, (2) `ingestion_status == 'ready'`, and (3) attached to a Knowledge Base that is itself attached to the chat's `project_id` (the matter). A projectless chat has no matter, so nothing is referenceable — it fails restrictive (404) rather than running a query that can never match. Any failing id — malformed, foreign, unknown, soft-deleted, not-yet-ready, or outside the matter's attached KBs — returns 404, id-probing-safe and message-identical to "not found" (mirrors `_validate_owned_file_ids`'s posture for `file_ids`).

This means a file must already be `ready` (fully ingested/embedded) to be referenceable — there is no "reference an arbitrary file and embed it on demand" path in Phase 1. That is intentionally deferred as **Phase 3 (embed-on-reference)**: eagerly (re-)triggering a file's embedding pipeline when it is first referenced, so a caller could reference a just-uploaded document before its normal ingestion completes. Phase 1 ships the narrower, already-ingested-only surface because it reuses the existing ingestion pipeline and KB-attachment model unchanged — no new ingestion trigger path, no new state machine. Phase 2 (an `@`-mention UI affordance for selecting referenced files while composing) is likewise deferred; Phase 1 is API-only.

### D3 — Referenced-file chunks flow through the existing skip-anonymization context block, not a verbatim dump (item c, P9)

Chunks retrieved via `hybrid_search_files` are merged into the turn's `retrieved_chunks` and rendered through the **same** `_format_retrieval_context_block` / skip-anonymization system message that ordinary KB-RAG chunks already use (`lq_ai_skip_anonymization=True` on that message) — not injected as a second verbatim block alongside `file_ids`' attached-files block.

Rationale: this is PRD/ADR 0016 **P9** ("public inbound text stays verbatim only because citation grounding requires it") applied directly — referenced-file content is retrieval-grounded, citation-bearing context, the same trust class as KB-RAG chunks, so it gets the same anonymization exemption and the same rendering path. It is explicitly **not** a verbatim dump of the referenced file's full text (that is what `file_ids` is for); only the retrieved chunks — the ones the model can cite — enter the prompt.

### D4 — A UI/caller-selected set, not a model-callable tool (item d, P2)

`referenced_file_ids` is set by the caller on the `MessageCreateRequest` before the turn is dispatched. The model cannot select or expand this set mid-turn; there is no tool-call surface (no `ToolIntent` member, no planner-visible action) that lets the model choose which files to reference.

Rationale: ADR 0016 **P2** ("the model... chooses among an operator-enabled allowlist; it can never reach beyond it... a new model-invokable capability is a new bounded, declared entry on an operator-controlled list, not a general-purpose hook"). File selection here is a **caller** decision (today: an API-level list; Phase 2 UI wraps it in an `@`-mention affordance), not a model decision — so it is deliberately kept off the closed-set tool-calling surface (ADR 0015) rather than added as a new governed tool intent. This also keeps the feature's blast radius small: no new grant in `PHASE_GRANTS`, no new audit-log tool-call shape, no new confirmation-gate surface.

### D5 — Merged-chunk cap raised 10→16 only when references are present (item e)

`_merge_retrieved_chunks` caps the merged (referenced + KB) chunk list at `MERGED_MAX_TOTAL_CHUNKS = 16` when `referenced_file_ids` is non-empty, and at the pre-existing `RAG_MAX_TOTAL_CHUNKS = 10` otherwise. Referenced chunks are capped at `REFERENCED_MAX_CHUNKS = 12` (round-robin interleaved across files, `REFERENCED_TOP_K_PER_FILE = 6` per file) and always take priority in the merge (referenced chunks first, then KB chunks not already present, deduped by `chunk_id`) — so ordinary KB retrieval retains at least 4 slots even when the referenced budget is maxed out.

Rationale: pure-KB-search turns (no references) are **byte-identical** to pre-referenced-files behavior — the cap only moves when the caller opts in to referenced files, so this is non-breaking for every existing caller. The 16/12/6 split was sized so a turn referencing several files still leaves headroom for project-wide KB context, rather than referenced files crowding it out entirely.

### D6 — Per-file retrieval alpha is the MIN of the file's matter-KB `hybrid_alpha` (item f, P8)

`_validate_referenced_file_ids` returns, alongside the validated id list, each file's retrieval alpha: `MIN(hybrid_alpha)` across every attached, matter-scoped Knowledge Base containing that file (one SELECT, `func.min` grouped by file id). `_retrieve_referenced_file_context` passes this alpha into `hybrid_search_files` per file (falling back to 0.5 only if a file is somehow missing from the map, which should not happen given the validation contract).

Rationale: `hybrid_alpha` is an existing **operator-tunable** per-KB setting (ADR 0016 P8 — operator visibility and control over every capability); referenced-file retrieval must honor that tuning rather than hardcoding a default, or an operator's deliberate alpha choice for a KB would silently stop applying the moment a caller references one of its files directly. MIN is the deterministic, conservative (vector-favoring) tie-break when a file sits in more than one attached KB with different alpha values — an arbitrary "pick one" or an average would be non-deterministic or not clearly traceable to an operator decision.

### D7 — KB-wide RAG still runs alongside explicit references (item g)

Referencing files does not disable or replace project-wide KB retrieval. Both `_retrieve_referenced_file_context` and the existing KB-wide `hybrid_search` loop run on every turn where the chat has attached KBs; their results are merged per D5, with referenced chunks prioritized.

Rationale: a caller referencing a specific exhibit does not thereby withdraw consent for the model to also draw on the rest of the matter's Knowledge Base — the two channels answer different questions ("ground in *these* documents specifically" vs. "search across everything") and are additive, not exclusive. Running both also means D5's cap-raise is the only wire-visible effect of referencing files on the merged set — no separate "referenced-only mode" to reason about.

## Consequences

- Chat send gains a third document-context channel (`referenced_file_ids` / `applied_referenced_file_ids`) alongside `file_ids` (verbatim) and implicit KB-wide RAG, each with a distinct, now-documented contract (PRD §3.1, §3.3; `docs/api/backend-openapi.yaml`).
- Audit gains `inference.message_referenced_files` (counts/ids only, per P3) and `inference.kb_chunks_retrieved` gains an additive `retrieved_count` field distinguishing "what the search returned" from "what was actually injected" (`chunk_count`/`chunk_ids`), so referenced-file contribution is traceable in the audit trail without payload exposure.
- Operators' existing `hybrid_alpha` tuning extends automatically to referenced-file retrieval (D6) with no new config surface.
- Two known limitations ship as-is in Phase 1 (item h):
  1. **Confirmation-gate resume path persists no chunk citations.** The tool-call confirmation-gate resume path (`resume_tool_call`'s SSE `complete` frame) unconditionally emits `"citations": []` and `"applied_referenced_file_ids": []`, regardless of whether the original turn referenced files or retrieved citable chunks — the resume path is a continuation frame that does not re-run retrieval or citation extraction. This is a **pre-existing** gap in the confirmation-gate resume path (it predates referenced-files and affects `file_ids`/KB citations identically), not something referenced-files introduces, but referenced-files inherits it for `applied_referenced_file_ids` too. Tracked as a separate DE to file (not filed as part of this ADR — the gap is orthogonal to the referenced-files design and belongs with the broader tool-loop resume-path work).
  2. **A validated referenced file can contribute zero chunks yet still echo as applied.** `applied_referenced_file_ids` echoes `effective_referenced_file_ids` — the full **validated** set — independent of whether `hybrid_search_files` actually returned any chunks for a given file (e.g., no chunk scored above the search's relevance floor for the turn's query). A file can therefore appear in `applied_referenced_file_ids` while contributing nothing to the model's context for that turn. This is not silent: the `inference.message_referenced_files` audit row's `chunk_count` (count of chunks actually retrieved/injected across all referenced files) exposes the gap between "validated as referenceable" and "actually retrieved," so an operator or auditor can distinguish the two from the audit trail even though the response echo alone cannot.

## Open questions

- **Phase 2 (`@`-mention UI).** The exact interaction design for selecting referenced files inline while composing — out of scope here; referenced-files's PRD §9 entry tracks it as deferred.
- **Phase 3 (embed-on-reference).** Whether/how referencing a not-yet-`ready` file should trigger or prioritize its ingestion, and the UX for a reference that resolves only after ingestion completes — deferred; needs its own design pass on the ingestion-trigger surface.
- **Resume-path citation persistence.** Whether to fix the confirmation-gate resume path's citation/echo gap as a targeted DE, or fold it into a broader tool-loop resume-path hardening pass — left to whichever DE is filed for it.
