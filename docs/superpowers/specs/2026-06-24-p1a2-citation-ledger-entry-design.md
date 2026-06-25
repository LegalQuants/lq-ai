# P1-A2 — Citation Ledger entry table + assembly (design)

**Date:** 2026-06-24
**Milestone:** Fiduciary-grade agentic legal work — Phase 1 (WS-A)
**Branch:** `feat/fiduciary-p1a2-citation-ledger`
**Pins:** [ADR 0018](../../adr/0018-citation-ledger-and-fiduciary-grade-output.md) D1 (thin referencing table), D5 (no-raw-payload / tripwire), D6 (reserved treatment slot), D7 (granularity). Builds on **P1-A1** (`message_caselaw_citations`, merged in #218).
**Security review:** required (citation/audit-adjacent surface). No new egress.

## Problem

P1-A1 made external caselaw quotes character-verifiable. The chat-finalize path now persists three independent per-turn artifacts: `message_citations` (KB-document quote verification), `message_caselaw_citations` (caselaw quote verification — P1-A1), and `message_tool_sources` (retrieval provenance — "sources consulted"). They are **disconnected** — there is no single, matter-and-turn-scoped record that unifies "every source the turn brought into context and the verification status of each." That unified artifact is the Citation Ledger (ADR 0018 D1), and it is what makes one-click trace (P1-A3) and the fiduciary-grade gate (P1-B1) possible. P1-A2 builds the ledger table and the assembly that populates it; it does **not** build the read API, the gate, or the UI.

## Decisions (maintainer-approved 2026-06-24)

- **Three nullable FKs + `source_kind`** — the entry references exactly one of `message_citations` / `message_caselaw_citations` / `message_tool_sources` (a CHECK enforces exactly-one-non-null). This **reconciles ADR 0018 D1**, whose hypothetical `citable_source_id` is replaced by the concrete `message_caselaw_citation_id` (P1-A1 reused research-opinion storage + a caselaw-citation table instead of creating a `citable_source`). A short reconciliation note is appended to ADR 0018 D1.
- **One entry per underlying row, no dedup** — a consulted caselaw cluster (a `message_tool_sources` provenance row) and a verbatim quote from its opinion (a `message_caselaw_citations` row) are *distinct ledger facts*; both get entries (ADR D7: per-(turn, source)).
- **Defer DE-350** from P1-A2 — assembly is source-kind-agnostic over `message_tool_sources`, so generic-MCP entries flow into the ledger automatically once [DE-350](../../PRD.md#de-350) lands. **DE-350 is sequenced as the immediate next slice after P1-A2** (maintainer directive 2026-06-24).
- **Metadata-only entry** — the ledger holds no `source_text`; it references content by id. So it **is** added to the P3 no-raw-payload tripwire (ADR D5) — the opposite of `message_caselaw_citations`, which holds quoted text and stays out.

## Design

### Component 1 — `citation_ledger_entry` table (migration `0058`)

| Column | Type / notes |
|---|---|
| `id` | uuid pk, `gen_random_uuid()` |
| `project_id` | uuid, **nullable** (a chat may be matter-less) |
| `chat_id` | uuid, FK → `chats.id` ON DELETE CASCADE, not null |
| `message_id` | uuid, FK → `messages.id` ON DELETE CASCADE, not null (the assistant turn) |
| `source_kind` | text, not null — `'kb_document'` \| `'caselaw'` \| `'mcp'` (extensible) |
| `message_citation_id` | uuid, FK → `message_citations.id` ON DELETE CASCADE, **nullable** |
| `message_caselaw_citation_id` | uuid, FK → `message_caselaw_citations.id` ON DELETE CASCADE, **nullable** |
| `message_tool_source_id` | uuid, FK → `message_tool_sources.id` ON DELETE CASCADE, **nullable** |
| `verification_status` | text, not null — the citation's `verification_method` (`'exact_match'`/`'tolerant_match'`/…), or `'provenance'` for a consulted-but-not-quoted tool source |
| `confidence` | double precision, nullable — mirrored from the citation; null for provenance entries |
| `provider` | text, nullable — e.g. `'courtlistener'`; null for local KB documents |
| `retrieved_at` | timestamptz, nullable — the tool-source row's `created_at`; null for KB documents |
| `treatment_id` | uuid, **nullable, no FK** — reserved for WS-G derived treatment (ADR D6); always null in P1-A2 |
| `created_at` | timestamptz, not null, `now()` |

CHECK constraints:
- **exactly one source FK non-null** — `(message_citation_id IS NOT NULL)::int + (message_caselaw_citation_id IS NOT NULL)::int + (message_tool_source_id IS NOT NULL)::int = 1`.
- `confidence IS NULL OR (confidence >= 0 AND confidence <= 1)`.

Indexes: `chat_id`, `message_id`, `project_id`.

ADR 0018 D1 also sketched a `tier` column; **dropped** in v1 — `message_tool_sources` does not carry a tier, so it cannot be populated honestly. A follow-on if a tier source materializes.

### Component 2 — Assembly

`assemble_ledger_entries(db, *, project_id, chat_id, message_id) -> int` in a new module `api/app/citation/ledger.py`:

1. Query `message_citations`, `message_caselaw_citations`, and `message_tool_sources` for `message_id`.
2. Build one `CitationLedgerEntry` per row:
   - **`message_citations`** → `source_kind='kb_document'`, `message_citation_id` set, `verification_status = row.verification_method`, `confidence = float(row.verification_confidence)`, `provider=None`, `retrieved_at=None`.
   - **`message_caselaw_citations`** → `source_kind='caselaw'`, `message_caselaw_citation_id` set, `verification_status = row.verification_method`, `confidence = row.verification_confidence`, `provider='courtlistener'`, `retrieved_at = row.created_at`.
   - **`message_tool_sources`** → `source_kind = row.source_kind` (already `'caselaw'`; `'mcp'` once DE-350 lands), `message_tool_source_id` set, `verification_status='provenance'`, `confidence=None`, `provider = row.provider`, `retrieved_at = row.created_at`.
3. `add_all` + `flush`. Returns the entry count.

`message_citations.verification_confidence` is a `Decimal`; coerce to `float` for the ledger's `confidence`. Only **verified** `message_citations` / `message_caselaw_citations` rows exist (the persist steps drop unverified ones), so every citation-backed entry has a real method + confidence.

### Component 3 — Hook

A sibling call at chat finalize, **after** the citation/tool-source persist steps (so all rows exist), at **every** finalize site that persists citations — the streaming tool-loop site, the resume site, **and** the single-shot/non-tool site. (P1-A1 wired only the two tool-loop sites because only those produce caselaw sources; the ledger applies to KB-document chats too, so it must also cover the single-shot path where only `message_citations` rows exist.) The plan enumerates the exact sites in `api/app/api/chats.py`. Each call is guarded in `try/except` that logs and never re-raises (a ledger failure must not break the turn). The assembly reads `project_id` from the chat already in finalize scope. Because it simply maps whatever rows exist for the message, no per-site branching on source kind is needed.

### Component 4 — P3 tripwire (ADR 0018 D5)

Add `CitationLedgerEntry` to `api/tests/test_transparency_invariants.py`'s no-raw-payload model scan. The entry carries only ids, labels, a numeric confidence, provider, and timestamps — no content — so the scan must pass with it included, proving the ledger is a metadata index, not a content store.

## Error handling (conservative posture)

- Assembly is guarded at every finalize site — a failure logs and degrades to "no ledger this turn," never aborting the assistant turn/stream.
- A row with an unexpected shape is skipped, not fatal.
- No new egress, no gateway/LLM call — pure DB reads + writes.

## Testing

- **Integration (real Postgres):** a turn with (a) a `message_citations` row, (b) a `message_caselaw_citations` row, and (c) a `message_tool_sources` row → `assemble_ledger_entries` writes **three** entries with the correct `source_kind`, the correct single FK set, and the mirrored `verification_status`/`confidence`/`provider`/`retrieved_at`. Assert the exactly-one-FK CHECK rejects a 0-FK and a 2-FK insert. Assert a KB-only turn (only `message_citations`) yields one `kb_document` entry.
- **Transparency invariant:** `test_transparency_invariants.py` stays green with `CitationLedgerEntry` added to the scanned set.
- **No provider gating** (pure DB). Run via host venv + throwaway pgvector.
- Gates: `ruff format` + `ruff check` + `mypy app` + full `pytest` (coverage no-decrease).

## Acceptance criteria

1. `citation_ledger_entry` exists (migration `0058`) with the exactly-one-FK CHECK and the three nullable source FKs.
2. At chat finalize, every persisted `message_citations` / `message_caselaw_citations` / `message_tool_sources` row for the turn yields exactly one correctly-typed ledger entry.
3. `CitationLedgerEntry` is in the P3 tripwire scan and the test passes (proves metadata-only).
4. A ledger failure never breaks the turn. `ruff` + `mypy` clean; integration + invariant tests green.

## Out of scope / sequencing

- **DE-350** (generic-MCP provenance) — **the immediate next slice after P1-A2** (maintainer directive). Once it emits `source_kind='mcp'` rows on `message_tool_sources`, those flow into the ledger with no ledger change.
- Ledger **read API + one-click trace** → P1-A3. **Fiduciary-grade gate** → P1-B1. **UI** → P1-C1. **Treatment population** (`treatment_id`) → WS-G.
- ADR 0018 D1 gets a one-line reconciliation note (`citable_source_id` → `message_caselaw_citation_id`); the decision itself is unchanged.
