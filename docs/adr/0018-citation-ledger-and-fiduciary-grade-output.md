# ADR 0018 — The Citation Ledger & fiduciary-grade output

**Status:** Accepted (2026-06-24) — maintainer-accepted; Phase 1 implementation PRs (P1-A1+) carry security review per CODEOWNERS (new content store derived from egress; citation/audit surface)
**Date:** 2026-06-24
**Owner:** Fiduciary-grade agentic legal work milestone (feature branch `feat/fiduciary-grade-phase1-spec`)
**Supersedes / relates to:** [ADR 0014](0014-gateway-egress-boundary-for-tool-providers.md) (where egress lives), [ADR 0015](0015-governed-tool-calling-model.md) (how a tool call is governed), [ADR 0016](0016-transparency-and-governance-invariants.md) (the binding invariants), and the [fiduciary-grade mini-PRD](../proposals/fiduciary-grade-agentic-legal-work.md) WS-A/WS-B/WS-C.

## Context

Thomson Reuters' next-generation CoCounsel leads on a **patent-pending citation ledger** that "tracks every source the agent brings into context and the specific passages it reads," traceable in one click, with verification "part of the system's architecture rather than an afterthought." A [codebase verification pass](../proposals/fiduciary-grade-agentic-legal-work.md#what-lqai-already-has-vs-what-is-net-new) (2026-06-24) confirmed LQ.AI already owns the *plumbing* CoCounsel describes, but not the *artifact*:

- **The citation cascade** (`api/app/citation/verification.py`: `verify_exact_match` → `verify_tolerant_match` → `verify_paraphrase` → `verify_ensemble`) with a reusable LLM-judge behind a Protocol, and char-precise offsets end-to-end (`MessageCitation.source_offset_start/end` into `documents.normalized_content`).
- **Retrieval provenance** for external sources — `MessageToolSource(source_kind, label, subtitle, url, external_ref, provider, tool, created_at)`, populated for case-law today (`extract_tool_sources` in `api/app/chat/tool_loop.py`), generic-MCP deferred ([DE-350](../PRD.md#de-350)).
- **Work-product attribution** (`WorkProductAttribution`, keyed 1:1 to an assistant message) and the **counts-not-payloads audit logs** (`tool_call_log`, `tool_egress_log`) enforced by the ADR 0016 P3 tripwire.
- **Web provenance primitives** — `ProvenancePill`, `ToolSourcesPanel`, `M2Citations` wired into `MessageBubble.svelte`.

What is missing is a **first-class, matter- and turn-scoped record** that unifies these into one inspectable, one-click-traceable artifact — and the one capability gap the pass surfaced: **external/caselaw citations are not character-verified today.** The cascade runs over *documents* (KB content with stored offsets); external sources are tracked as "sources consulted," explicitly *not* quote-verified (`docs/HONEST-STATE.md` §5.5). The maintainer's decision (2026-06-24) is that **v1 fiduciary-grade requires character-level quote-verification of external citations too** — not just retrieval provenance.

This ADR pins the ledger's data model, how external sources become quote-verifiable, what "fiduciary-grade" means as a gate, the one-click trace read model, retention, and the no-raw-payload guarantee. It is load-bearing for Phase 1 (WS-A/B/C) and reserves the slot Phase 2's validity layer (WS-G) populates.

## Decision drivers

1. **Transparency is the product (§1.3).** The ledger must be *demonstrable*, not asserted: one click from any cited assertion to the exact source and passage read, with its verification status visible. This is the axis on which an open, self-hosted ledger beats an opaque "trust us" claim.
2. **Reuse the substrate; do not fork it (ADR 0016 P6 — one governance path).** The ledger is an index over `message_citations`, `message_tool_sources`, `work_product`, and the cascade — not a parallel verification engine. Document citations and external citations must verify through the *same* cascade.
3. **No raw payloads in the index (ADR 0016 P3).** The ledger references content by id + offset; quoted text and source text live in the content layer, never duplicated into a provenance/index row.
4. **Conservative posture (PRD §1).** A claim whose citation cannot be verified is *flagged*, never silently emitted. "Fiduciary-grade" is a computed gate, not a marketing label.
5. **External sources must be quote-verifiable in v1** (maintainer decision 2026-06-24) — the harder, more faithful path, consistent with the conservative posture.
6. **Reserve for the validity layer (WS-G).** The ledger carries a treatment/validity slot the derived-treatment layer fills later; this ADR reserves it without pinning WS-G's methodology (its own ADR does that).

## Decisions

### D1 — The ledger is a thin **referencing** table, not a snapshot or a view

Introduce `citation_ledger_entry` — one row per *(assistant turn, source brought into context)*, accumulated per matter (`project_id`). It **references** the rows that already hold the truth rather than copying them:

| Column | Purpose |
|---|---|
| `id` (uuid pk) | entry identity |
| `project_id` (fk, nullable) | matter scope (a chat may be matter-less) |
| `chat_id` (fk) | conversation scope |
| `message_id` (fk) | the assistant turn that brought this source into context |
| `source_kind` (text) | `kb_document` \| `caselaw` \| `mcp` \| `kb_chunk` (mirrors/extends `MessageToolSource.source_kind`) |
| `message_citation_id` (fk, nullable) | → the verified quote, when the source produced a `MessageCitation` |
| `message_tool_source_id` (fk, nullable) | → the retrieval-provenance row, for external/tool sources |
| `citable_source_id` (fk, nullable) | → the materialized external source text (D2), when one was created |
| `verification_status` (enum) | mirrored from the cascade: `exact` \| `tolerant` \| `paraphrase` \| `ensemble` \| `unverified` \| `failed` (label only, **not** payload) |
| `confidence` (float, nullable) | mirrored cascade confidence (a number, not content) |
| `provider` / `tier` / `retrieved_at` | retrieval provenance (or null when the source is a local KB document) |
| `treatment_id` (fk, nullable) | **reserved** for WS-G derived treatment (D6); null until then |
| `created_at` | append time |

`verification_status`/`confidence` are mirrored onto the entry **for queryability** (so "is this draft fiduciary-grade?" is a cheap join, and the gate does not re-run the cascade). They are labels and numbers — counts/types, not raw passages — so the mirror does not violate P3. The actual quoted text stays in `MessageCitation.source_text` and the materialized source (D2); the entry never holds it.

*Rejected — read-model/view only:* no durable home for the reserved treatment slot, no re-run survival, and WS-G would have nowhere to write. *Rejected — denormalized snapshot:* duplicates content (P3 surface) and drifts from the source rows. The thin referencing table is the maintainer's selected option (2026-06-24).

> **Reconciliation (P1-A2, 2026-06-24):** as built, the ledger references the three concrete per-turn artifacts via three nullable FKs — `message_citation_id`, `message_caselaw_citation_id`, `message_tool_source_id` (exactly one non-null). The earlier `citable_source_id` slot is realized as `message_caselaw_citation_id` (P1-A1 reused research-opinion storage + a caselaw-citation table rather than creating a standalone `citable_source`). The sketched `tier` column is deferred — `message_tool_sources` carries no tier to populate.

### D2 — External sources become quote-verifiable by **materializing** their text as a citable source

To character-verify a quote drawn from an external authoritative source (a CourtListener/MCP opinion), the fetched source text is **materialized as a citable source** in the content layer — normalized text + char offsets — and **the existing cascade runs against it unchanged**. This keeps one verification path (P6): a quote from a KB document and a quote from a fetched opinion both verify by slicing stored `normalized_content[start:end]` and running exact → tolerant → paraphrase.

- **Where it lives:** a `citable_source` record (or `documents` extended with a provenance-bearing `source_kind`), holding the fetched opinion's normalized content + chunked offsets, scoped to the matter, marked non-anonymized public content (CourtListener already returns `skip_anonymization=True`). It is **content, not audit** — P3 (which governs the audit layer) is unaffected; the content layer legitimately holds content.
- **Why persist, not verify-in-memory:** one-click trace (D4) requires the text be retrievable *later*; re-fetching is non-deterministic (opinions/URLs change) and would make stored offsets dangle. Persistence makes the trace stable and the offsets durable.
- **Reuse, not reinvention:** this is the **shared substrate for [DE-279](../PRD.md#de-279) (citation resolution) and [DE-280](../PRD.md#de-280) (case-content accuracy)**. DE-280 already scopes "once a case citation resolves, the full opinion text is retrievable from CourtListener … the judge must reason over the whole opinion." WS-A's char-level quote verification is the exact/tolerant tier over that same materialized text; DE-280's content-accuracy judge is the paraphrase tier. The ledger is where all three (resolution, quote-fidelity, content-accuracy) land.

### D3 — "Fiduciary-grade" is a computed gate over ledger entries

A drafted answer / memo / clause is **fiduciary-grade iff every assertion's citation resolves to a ledger entry whose `verification_status` is in the PASS set, with no entry in the FAIL set left un-surfaced.**

- **PASS (verbatim-fidelity):** `exact`, `tolerant`. The quote is present char-for-char (within normalization tolerance) in the cited source.
- **SUPPORTED (labeled, not verbatim):** `paraphrase`, `ensemble`. Surfaced *distinctly* ("supported, not verbatim") — permitted in a fiduciary-grade draft only when explicitly labeled as paraphrase, never presented as a verbatim quote.
- **FAIL / unverifiable:** `unverified`, `failed`. **Flagged inline** ("unverified" chip), never silently emitted (conservative posture). A draft containing an un-surfaced FAIL entry is *not* fiduciary-grade.

The gate is computed at finalize, surfaced in WS-C, and recorded against the `work_product`. Exact thresholds reuse the cascade's existing `TOLERANT_MATCH_THRESHOLD` / aggregation rules (see [DE-281](../PRD.md#de-281)); operator tuning of the PASS set is a deferred enhancement, not v1.

### D4 — One-click trace read model

A new read surface returns, for a matter/turn, every ledger entry resolved to: source identity, the passage(s) read (char offsets into the document or materialized source), verification status + confidence, retrieval provenance, and (later) treatment. Proposed endpoint family under the chat resource — e.g. `GET /api/v1/chats/{chat_id}/ledger` (turn- or matter-scoped) and a per-entry trace — joining `message_citations` + `message_tool_sources` + `citable_source`. New routes follow P10: OpenAPI sketch updated, `IMPLEMENTED_ROUTES` extended, the pinned path count + `EXPECTED_PATHS` bumped (the api-suite collision guard).

### D5 — No-raw-payload guarantee (P3)

`citation_ledger_entry` carries **ids, offsets, status labels, confidence numbers, provenance metadata, and timestamps — never raw passages or tool payloads.** Quoted/source text lives only in the content layer (`MessageCitation.source_text`, the materialized `citable_source`). The ledger is a content-provenance *index*, not an audit log; as defense-in-depth it is **added to the `test_transparency_invariants.py` no-raw-payload tripwire's scanned set**, so a future content-bearing column on it fails CI at collection like the audit models do.

### D6 — Reserved treatment slot for the validity layer (WS-G)

`citation_ledger_entry.treatment_id` is a nullable FK to a future `citation_treatment` record. Until WS-G ships it is null. WS-G (its own ADR) populates derived treatment (followed / distinguished / criticized / questioned / overruled / superseded) with a confidence score, **labeled "derived, not editorial,"** linked to the citing cases it rests on. This ADR only reserves the slot and fixes that derived signals attach to ledger entries (so the trace view can show "this case is cited, here is its derived treatment, here is why").

### D7 — Granularity & retention

Entries are **per-(turn, source), accumulated per matter**, and are **history-preserving**: re-running a matter appends new turn-scoped entries rather than mutating old ones (the ledger is an audit-friendly record of what was consulted *when*). Materialized `citable_source` rows (D2) are cache-like and may be garbage-collected on a TTL, but are **pinned while any ledger entry references them**, so one-click trace never dangles. Everything matter-scoped is subject to P9 export/delete.

## Consequences

**Positive.** The ledger ships on proven plumbing (cascade, source-kind model, offsets, audit discipline, provenance pills) — most of Phase 1 is *materialization + surfacing*, not new verification science. External-source quote verification (D2) unifies WS-A with DE-279/DE-280 instead of forking them. The transparency posture becomes a visible product (D4) and the conservative posture becomes a hard gate (D3).

**Costs / risks.** (1) Materializing opinion text (D2) adds a content store and a retention/GC concern not present today — pinned-reference GC must be correct or traces dangle. (2) The verbatim-vs-supported distinction (D3) must be legible to a lawyer or the gate is theater. (3) R4's economic brake is a no-op for external tools today (`estimate_tool_cost` → `Decimal(0)`, [DE-344](../PRD.md#de-344)); materializing long opinions adds inference cost (the paraphrase/content judge over 10–50pp opinions) that v1 should bound with a pre-flight budget check, as DE-280 already notes. (4) Generic-MCP sources must gain provenance ([DE-350](../PRD.md#de-350)) before the ledger can claim "every tool-retrieved source."

**Invariants satisfied.** P1 (all source fetches go through the gateway), P3 (index references content, holds no payloads; tripwire-scanned per D5), P6 (one cascade, one governance path), P9 (matter-scoped export/delete), P10 (new endpoints land in the contract).

## Open questions (resolve in the Phase 1 plan)

- **`citable_source` vs. extending `documents`.** Whether materialized external sources are a new table or a `documents` row with a provenance-bearing `source_kind` + a "cache/ephemeral" flag. Trade-off: reuse of the chunking/offset/verify pipeline (favors `documents`) vs. keeping matter-scoped cache content out of the user's KB document list (favors a new table). Pin in WS-A task 1.
- **Pinned-reference GC.** The exact mechanism that keeps a materialized source alive while referenced and reclaims it when not (refcount vs. periodic sweep vs. retain-with-matter).
- **Gate surfacing granularity.** Whether the fiduciary-grade verdict is per-message, per-draft-artifact, or both, and how "supported, not verbatim" renders distinctly from "verbatim verified" in WS-C.
- **Cost ceiling for materialization.** The pre-flight budget shape for verifying quotes against long opinions (ties to DE-344/DE-280).
