# P1-A1 — External caselaw quote-verification core (design)

**Date:** 2026-06-24
**Milestone:** Fiduciary-grade agentic legal work — Phase 1 (WS-A)
**Branch:** `feat/fiduciary-p1a1-caselaw-quote-verification`
**Pins:** [ADR 0018 — The Citation Ledger & fiduciary-grade output](../../adr/0018-citation-ledger-and-fiduciary-grade-output.md) (D2/D3); [mini-PRD §Phase 1 P1-A1](../../proposals/fiduciary-grade-agentic-legal-work.md).
**Security review:** required (citation surface; reads egress-derived content). No new egress path.

## Problem

Today LQ.AI quote-verifies only **KB-document** citations: `_persist_message_citations` (`api/app/api/chats.py`) runs the citation cascade (`extract_citations` → `verify`) over the assistant answer against the documents retrieved for that turn, and persists verified `MessageCitation` rows. **External caselaw citations are not quote-verified** — `message_tool_sources` records *which* cases a tool call consulted (retrieval provenance), explicitly not whether a quoted passage actually appears in the opinion (`docs/HONEST-STATE.md` §5.5).

ADR 0018 D2/D3 (maintainer decision 2026-06-24) require v1 fiduciary-grade to **character-verify external caselaw quotes too**. P1-A1 builds that core.

## Key grounding (verified against `main`, 2026-06-24)

- **Opinion text is already persisted.** `app/research/service.py::get_cluster` fetches each opinion, runs `html_to_text`, and `upload_bytes(...)` stores the **plaintext** body in object storage at `_opinion_storage_path(cluster_id, opinion_id)`; a `ResearchOpinionMetadata` row (`research_opinion_metadata`: PK `opinion_id`, `cluster_id`, `text_field_used`, `storage_path`, `char_length`) indexes it. `read_opinion` / `_read_body(storage_path)` read the plaintext back. **No new content store is needed** (the maintainer's chosen representation, 2026-06-24).
- **The cascade is reusable as-is.** `app/citation/verification.py::verify(candidate, document, *, gateway=None, ...)` needs only a `_DocumentProtocol` — `{id, normalized_content, was_ocrd}`. **Stages 1–2** (`verify_exact_match`, `verify_tolerant_match`) are **deterministic** (no gateway, no cost). Stages 3–4 (paraphrase/ensemble judge) require a gateway.
- **Citations attach at finalize.** On `LoopFinal`, `chats.py` calls `_persist_assistant_message` → `_persist_message_citations` → `_persist_message_tool_sources`. P1-A1 adds a sibling persist step here.

## Scope

**In P1-A1 (deterministic char-fidelity only):**
- Verify the model's **verbatim** caselaw quotes (cascade **stages 1–2**, `gateway=None`) against the already-stored opinion plaintext for the opinions consulted in the turn.
- Persist verified caselaw citations so they are queryable and traceable.

**Deferred (explicitly not P1-A1):**
- The **paraphrase/ensemble judge over opinions** (the "supported, not verbatim" tier) — that is costly long-opinion verification = **P1-B1 / [DE-280](../../PRD.md#de-280)**. Because P1-A1 is deterministic-only, **no cost ceiling is needed** (resolves an ADR 0018 open question).
- The `citation_ledger_entry` table (**P1-A2**), the ledger read API (**P1-A3**), the UI (**P1-C1**).

This scope decision (verbatim now, paraphrase later; new parallel citation table) was confirmed with the maintainer 2026-06-24.

## Design

### Component 1 — Opinion verification target (adapter)

A thin in-memory adapter that makes a stored opinion satisfy `verify()`'s `_DocumentProtocol` without persisting a `documents` row:

```python
@dataclass
class _OpinionVerificationTarget:
    id: uuid.UUID            # synthetic, derived deterministically from opinion_id
    normalized_content: str  # the plaintext read via _read_body(storage_path)
    was_ocrd: bool = False   # opinions are not OCR'd
```

Built from a `ResearchOpinionMetadata` row + `await _read_body(row.storage_path)`. The plaintext is stable (content-addressed by cluster/opinion), so offsets into it are durable for later trace (P1-A3).

### Component 2 — Caselaw quote extraction + location

For the opinions consulted in the turn, locate the answer's quoted spans within each opinion's plaintext:

- **Which opinions:** the `(opinion_id, cluster_id)` pairs the model read this turn — sourced from the turn's `get_cluster` / `read_opinion` tool results (the loop already caches these; P1-A1 captures the consulted set rather than re-fetching).
- **Identify candidate passages — verified against the actual skill, not assumed.** The `case-law-research` skill (`skills/case-law-research/SKILL.md`) renders each cited passage as a **markdown blockquote** (`> …`) under a `**Relevant passage:**` header, and explicitly permits **"Quoted _or closely paraphrased_ excerpt"** (lines 77, 84, 117). So P1-A1 extracts **blockquote spans** (and, secondarily, any quotation-mark-delimited spans) from the assistant answer as candidate passages. This is caselaw-specific extraction — it does **not** reuse `extract_citations`, which resolves KB `(Source: [N])` markers to retrieved chunks; caselaw passages carry no `[N]` marker pointing at an opinion.
- **Locate each candidate:** **v1 uses exact-substring location** — `opinion_text.find(passage)` — yielding `source_offset_start/end` into the matched opinion's plaintext, which the cascade then confirms as `exact_match`. (`verify()` still runs the full cascade over those offsets, so a whitespace-tolerant *locator* — finding approximate offsets for stage-2 to confirm — is a clean follow-on without changing this hook.) Attribution is **by which consulted opinion the span matches** (a verbatim span matches exactly one); the `### Case Name` header is an optional confirmation hint, not required for v1.
- **Consequence of the skill's "quote-or-paraphrase" convention:** a **verbatim** blockquote matches an opinion → verified (`exact`/`tolerant`). A **paraphrased** blockquote matches none under stages 1–2 → **no verified row** — honestly surfaced as unverified until **P1-B1** adds the opinion-scale paraphrase judge (DE-280). P1-A1 verifies the verbatim subset; it does not (and should not) claim to verify paraphrases. This is the conservative posture, expected — not a coverage gap to paper over.

### Component 3 — Verification

For each located span, build a lightweight candidate satisfying `verify()`'s `_CandidateProtocol` (`source_text`, `source_offset_start`, `source_offset_end` — **not** the full `CitationCandidate` dataclass, which carries a KB `source_file_id` caselaw has no value for), then `await verify(candidate, target, gateway=None)` → `VerificationResult` via stages 1–2 (`exact` / `tolerant`) or unverified. No LLM, no provider call.

### Component 4 — Persistence: `message_caselaw_citations` (new table)

A new parallel table (maintainer-chosen over polymorphizing `message_citations`, whose `source_file_id` is `NOT NULL → files`):

| Column | Notes |
|---|---|
| `id` (uuid pk) | |
| `message_id` (fk → messages, cascade) | the assistant turn |
| `opinion_id` (bigint) | → `research_opinion_metadata.opinion_id` (the citable source) |
| `cluster_id` (bigint) | for trace/grouping |
| `source_offset_start` / `source_offset_end` (int) | offsets into the opinion plaintext; CHECK `end > start >= 0` |
| `source_text` (text) | the quoted passage (content, like `message_citations.source_text`) |
| `verified` (bool) | true only when stage 1–2 passes |
| `verification_method` (text) | `exact` \| `tolerant` |
| `verification_confidence` (float) | from the cascade |
| `partial` (bool) | from the cascade |
| `created_at` (timestamptz) | |

Indexed on `message_id`. Mirrors `MessageCitation`'s verification fields so P1-A2's ledger entry can reference a caselaw citation the same way it references a `MessageCitation`.

### Component 5 — Hook

A sibling `_persist_caselaw_citations(db, message_id, assistant_text, consulted_opinions, ...)` called from the `LoopFinal` finalize path in `chats.py`, next to `_persist_message_citations` / `_persist_message_tool_sources`. No change to the tool-loop engine or the gateway.

## Error handling (conservative posture, PRD §1)

- **Opinion body unreadable** (storage miss / `_read_body` raises) → skip that opinion, log, leave its quotes unverified. **Never** record a citation as `verified=true` without a passing cascade result.
- **No quote located** in any consulted opinion → no caselaw citation row (honest absence, surfaced as "unverified" by the UI later).
- **Verification fails** → not persisted as verified (mirrors today's KB-citation behavior).
- The finalize path must not crash the turn if caselaw verification fails wholesale — it degrades to "no verified caselaw citations," like the existing citation step.

## Testing

- **Unit:** quote located + exact match → `verified, method=exact`; whitespace/case variation → `method=tolerant`; invented quote (absent from opinion) → not verified; storage miss → skipped, turn unaffected; no consulted opinions → no rows.
- **Integration (real Postgres):** exercises the new migration + `_persist_caselaw_citations` end to end; an answer quoting a stored opinion yields a verified `message_caselaw_citations` row; an invented quote yields none.
- **No provider gating** — deterministic stages 1–2 need no gateway, so tests run without `-m provider`.
- Run `ruff format` + `ruff check` + `mypy` (api standard mode) and the api suite via the host venv + throwaway pgvector (per project test-runner convention).

## Transparency invariants (ADR 0016)

- **P1 (egress):** no new outbound path — reads opinion text already stored by the research service.
- **P3 (no raw payloads in audit):** `message_caselaw_citations` is a **citation/content** table (carries `source_text`, exactly like `message_citations`), not an audit log — the P3 tripwire (`test_transparency_invariants.py`) is unaffected. P1-A2's *ledger index* (metadata-only) is what gets added to the tripwire scan, not this content table.
- **P6 (one governance/verification path):** reuses `verify()` unchanged; no second verifier.

## Acceptance criteria (from ADR 0018 / mini-PRD P1-A1)

1. A chat answer that quotes a consulted CourtListener opinion produces a **verified** `message_caselaw_citations` row (`exact`/`tolerant`).
2. An **invented** quote attributed to an opinion resolves to **not verified** (no verified row).
3. The opinion text used for verification is the already-stored body (retrievable for later trace) — no second copy, no ghost `files`/`documents` rows.
4. `ruff` + `mypy` clean; unit + integration green; no provider gating needed.

## Out of scope / follow-ons

- Paraphrase/ensemble verdicts over opinions → **P1-B1** (DE-280).
- `citation_ledger_entry` + assembly referencing these rows → **P1-A2** (+ DE-350 generic-MCP).
- Ledger read API + one-click trace → **P1-A3**. UI → **P1-C1**.
