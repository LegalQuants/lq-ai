# P1-B1 — Deterministic fiduciary-grade gate (design)

**Date:** 2026-06-25
**Milestone:** Fiduciary-grade agentic legal work — Phase 1 (WS-B)
**Branch:** `feat/fiduciary-p1b1-fiduciary-gate`
**Pins:** [ADR 0018](../../adr/0018-citation-ledger-and-fiduciary-grade-output.md) D3 (fiduciary-grade is a computed gate), D5 (no-raw-payload / tripwire). Builds on **P1-A2** (`citation_ledger_entry` + assembly, #219) and **P1-A1** (#218).
**Security review:** required (citation/audit-adjacent surface; new metadata record on work product). **No new egress** — deterministic over already-persisted statuses.

## Problem

ADR 0018 D3 defines "fiduciary-grade" as a **computed gate**, not a label: a turn is fiduciary-grade iff every cited assertion resolves to a ledger entry whose `verification_status` is in the PASS set, with no FAIL entry left un-surfaced. The ledger exists (P1-A2) but nothing computes or records this verdict. P1-B1 computes the gate **deterministically over the per-turn ledger entries** and records it.

**Scope split (maintainer-approved 2026-06-25):** the DE-280 paraphrase judge over stored opinion text — which would let a caselaw quote that misses verbatim reach the SUPPORTED tier — adds gateway egress, R4 cost accounting, and a cost pre-flight. That is split out as **P1-B1b**. P1-B1 is **gate-only**: deterministic, no egress, no cost.

## Decisions (maintainer-approved 2026-06-25)

- **Split, gate-only.** P1-B1 classifies existing ledger statuses and records the verdict. The paraphrase judge + cost pre-flight → P1-B1b.
- **New `work_product_fiduciary_gate` table** (migration `0059`), 1:1-per-assistant-message — not new columns on `work_product_attribution` (which holds routing/attribution metadata, not verification). Matches the codebase's focused-per-artifact-table pattern; keeps the verdict + per-tier counts together.
- **Metadata-only → joins the P3 tripwire** (ADR D5). The gate row holds a status label, integer counts, and a numeric confidence — no content — so it is added to `test_transparency_invariants.py`'s scanned set, like `citation_ledger_entry`.

## The FAIL-detection reality (load-bearing — read before implementing)

ADR D3's FAIL set is `{unverified, failed}`, but the two quote pipelines persist failures **asymmetrically** today, and the P1-A2 assembler has a latent mislabel:

- **KB documents** (`message_citations`): a quote that fails every cascade stage **is persisted** with `verified=False, verification_method=None` (`app/citation/__init__.py`). So KB failures already reach the ledger — **but** the P1-A2 assembler writes `verification_status = c.verification_method or "verified"`, which mislabels an unverified KB citation as `"verified"`. **P1-B1 fixes this:** map `verified=False` → `verification_status="unverified"` (and `confidence=None`). Without the fix the gate would count a failed KB quote as PASS — the exact conservative-posture violation D3 forbids.
- **Caselaw** (`message_caselaw_citations`): `verify_and_persist_caselaw_citations` **drops** non-verified passages (`if not result.verified: continue`). So caselaw failures are invisible to the ledger today. Persisting caselaw FAIL attempts is **deferred to P1-B1b**, where the paraphrase judge runs and a "located but not verbatim, and not paraphrase-supported" passage becomes a genuine FAIL row. P1-B1 documents this as a known, scoped gap rather than over-flagging every unmatched blockquote (a blockquote may not be a caselaw quote at all).

**Net for P1-B1:** the gate flags FAIL for KB-document quotes (the dominant case) honestly once the assembler mislabel is fixed; caselaw-FAIL surfacing lands with the paraphrase work in B1b. This is stated plainly in the gate's docstring and the PR description — no overclaiming.

## Design

### Component 1 — Assembler mislabel fix (`api/app/citation/ledger.py`)

In `assemble_ledger_entries`, replace the `c.verification_method or "verified"` fallback for KB `message_citations` with: `verification_status = c.verification_method if c.verified else "unverified"`, and set `confidence = float(c.verification_confidence)` only when verified (else `None`). Same correction for the `message_caselaw_citations` branch for symmetry (today only verified rows reach it, so this is defensive). This makes the ledger's status field honest, which the gate and P1-A3's trace both depend on.

### Component 2 — `work_product_fiduciary_gate` table (migration `0059`)

| Column | Type / notes |
|---|---|
| `id` | uuid pk, `gen_random_uuid()` |
| `message_id` | uuid, FK → `messages.id` ON DELETE CASCADE, **not null, UNIQUE** (1:1 per assistant turn) |
| `chat_id` | uuid, FK → `chats.id` ON DELETE CASCADE, not null |
| `project_id` | uuid, FK → `projects.id` ON DELETE SET NULL, **nullable** (matter-less chats) |
| `gate_status` | text, not null — `'fiduciary_grade'` \| `'supported_only'` \| `'flagged'` |
| `pass_count` | integer, not null — entries in PASS `{exact_match, tolerant_match}` |
| `supported_count` | integer, not null — entries in SUPPORTED `{paraphrase_judge, ensemble_strict, ensemble_majority}` |
| `fail_count` | integer, not null — entries in FAIL `{unverified, failed}` |
| `total_assertions` | integer, not null — `pass + supported + fail` (provenance entries excluded) |
| `confidence` | double precision, nullable — aggregate over counted entries (see Component 3) |
| `created_at` | timestamptz, not null, `now()` |

CHECK: `confidence IS NULL OR (confidence >= 0 AND confidence <= 1)`; `pass_count >= 0` etc. Index on `chat_id`. Model `app/models/work_product_fiduciary_gate.py` (`WorkProductFiduciaryGate`).

`gate_status` derivation:
- `flagged` if `fail_count > 0` (a FAIL entry exists → not fiduciary-grade; D3 conservative posture).
- else `supported_only` if `supported_count > 0` (no FAIL, but some assertions are paraphrase/ensemble-supported, not verbatim).
- else `fiduciary_grade` (every counted assertion is verbatim PASS). A turn with **zero counted assertions** (e.g. a chit-chat turn with only provenance or nothing) → `fiduciary_grade` with `total_assertions=0` (vacuously true; the UI can render "no cited assertions" distinctly from "all verified").

### Component 3 — Gate computation (`api/app/citation/gate.py`)

```python
PASS_STATUSES = frozenset({"exact_match", "tolerant_match"})
SUPPORTED_STATUSES = frozenset({"paraphrase_judge", "ensemble_strict", "ensemble_majority"})
FAIL_STATUSES = frozenset({"unverified", "failed"})
# 'provenance' entries (tool sources, no quote) are NOT assertions — excluded.

async def compute_and_record_gate(db: AsyncSession, *, message_id: uuid.UUID) -> WorkProductFiduciaryGate | None:
```

1. Self-derive `chat_id` (from the message) and `project_id` (from the chat), mirroring `assemble_ledger_entries`. If the message has no chat (shouldn't happen at finalize), return `None`.
2. Load `CitationLedgerEntry` rows for `message_id`. Bucket each by `verification_status` into PASS / SUPPORTED / FAIL; ignore `provenance` and any unrecognized status (logged once — defends against a future status string slipping the gate).
3. `confidence` = the mean of the counted entries' non-null `confidence` values (PASS entries from exact match carry `1.0`; tolerant/paraphrase carry the cascade confidence). `None` when no counted entry has a confidence. (Mean, not min — the gate's confidence is a summary signal, not a worst-case bound; the per-entry detail is in P1-A3. Documented in the docstring.)
4. Derive `gate_status` (Component 2 rules), build the row, **upsert** on `message_id` (a re-finalize of the same turn replaces its gate — the gate is a current-verdict, not history; the ledger entries are the history-preserving record per ADR D7). Implement as delete-existing-then-insert or `ON CONFLICT (message_id) DO UPDATE`.
5. `add` + `flush` (never commit — rides the caller's transaction, P5). Return the row.

### Component 4 — Hook (`api/app/api/chats.py`)

Call `compute_and_record_gate(db, message_id=assistant_message_id)` at the **same three finalize sites** as `assemble_ledger_entries`, immediately **after** it (the gate reads the entries the assembler just wrote): the non-streaming tool-loop site (~2880), the non-streaming non-tool site (~3091/3103), and the streaming site (~3455). Each guarded in `try/except` that logs and never re-raises — a gate failure must not break the turn (conservative posture, matching the ledger hook).

### Component 5 — P3 tripwire (ADR 0018 D5)

Add `WorkProductFiduciaryGate` to `_AUDIT_MODELS` in `api/tests/test_transparency_invariants.py`. Its columns (`gate_status`, the `_count` integers, `confidence`, ids, timestamp) carry no content and do not trip `_implies_raw_content`, so the scan stays green — proving the gate is a metadata verdict, not a content store.

## Error handling (conservative posture)

- The gate hook is guarded at every finalize site — a failure logs and degrades to "no gate this turn," never aborting the turn/stream.
- An unrecognized `verification_status` is excluded from all buckets and logged (does not silently count as PASS).
- No egress, no gateway/LLM call — pure DB reads + a single upsert.

## Testing

- **Unit (classification, `gate.py`):** all-PASS turn → `fiduciary_grade`, counts correct, `confidence≈1.0`; mixed PASS+SUPPORTED, no FAIL → `supported_only`; any FAIL (an `unverified` entry) → `flagged`; `provenance` entries excluded from `total_assertions`; zero-assertion turn → `fiduciary_grade`, `total=0`; unknown status excluded + logged.
- **Integration (real Postgres, host venv + throwaway pgvector):** seed a turn's ledger entries across statuses → `compute_and_record_gate` writes one correctly-derived row; re-running upserts (no duplicate, `UNIQUE(message_id)` holds); the assembler fix is exercised — an unverified `message_citations` row produces an `unverified` ledger entry → `fail_count=1` → `flagged` (regression-locks the mislabel fix).
- **Transparency invariant:** `test_transparency_invariants.py` green with `WorkProductFiduciaryGate` in the scanned set.
- Gates: `ruff format` + `ruff check` + `mypy app` + full `pytest` (coverage no-decrease).

## Acceptance criteria

1. `work_product_fiduciary_gate` exists (migration `0059`), 1:1-unique on `message_id`, metadata-only.
2. At finalize, every assistant turn gets exactly one gate row whose `gate_status` follows D3 (`flagged` on any FAIL; `supported_only` when SUPPORTED-but-no-FAIL; `fiduciary_grade` otherwise), with correct per-tier counts and aggregate confidence; provenance entries are excluded from assertions.
3. The P1-A2 assembler mislabel is fixed — an unverified KB `message_citations` row lands as `verification_status="unverified"`, so the gate flags it (regression test locks this).
4. `WorkProductFiduciaryGate` is in the P3 tripwire scan and the test passes (proves metadata-only).
5. A gate failure never breaks the turn; no new egress. `ruff` + `mypy` clean; unit + integration + invariant tests green.

## Out of scope / sequencing

- **DE-280 paraphrase judge + cost pre-flight + caselaw-FAIL persistence** → **P1-B1b** (the SUPPORTED tier for caselaw, new egress, R4 cost, heavier security review). Filed in PRD §9.
- **Surfacing the gate in the read API** — P1-A3 ships its response as an object so B1 adds a `gates` key additively (whichever merges second wires it); the gate read shape is otherwise out of scope here.
- **UI** (P1-C1) renders the badge + verbatim-vs-supported distinction.
- **Operator tuning of the PASS set** — deferred per ADR D3 (not v1).
