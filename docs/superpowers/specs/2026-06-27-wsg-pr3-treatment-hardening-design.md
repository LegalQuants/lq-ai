# WS-G PR3 — treatment hardening (DE-364 + DE-363) — design

**Date:** 2026-06-27
**Milestone:** Fiduciary-grade agentic legal work — Phase 2, WS-G (transparent validity/treatment layer).
**Closes:** the two committed WS-G follow-ups before Phase 2 closes — **DE-364** (per-cluster SAVEPOINT isolation) and **DE-363** (lazy-on-trace-open treatment fallback).
**ADR:** [0019](../../adr/0019-transparent-validity-treatment-layer.md) D2 (lazy fallback is part of the intended compute model).
**Builds on:** WS-G PR1 (#233, the `citation_treatment` graph signal + async `treatment_derivation_job`) and PR2 (#236, the judge pass in `derive_treatment_for_message`).
**Security-gated:** yes — `api/app/citation/**` + `api/app/api/chats.py`. Security/maintainer merges; mirror `origin/main → tucuxi` after.
**Migration:** none (no schema change). **Next migration stays 0063. Next DE = DE-368.**

---

## 1. What this delivers

Two small, independent hardening changes that close WS-G:

- **DE-364 — per-cluster SAVEPOINT isolation.** Make `derive_treatment_for_message`'s per-cluster non-fatal guarantee genuinely hold under **concurrent same-case citation**. Today, if two turns cite the same not-yet-cached case at once, both miss the cache and both INSERT a `citation_treatment` row; the second hits `uq_citation_treatment_cluster_id` → `IntegrityError`, which poisons the `AsyncSession` so the *remaining* clusters of a multi-cluster turn fail with `PendingRollbackError` and the whole turn's derivation is lost (non-crashing, DE-363-recoverable, but the invariant is narrower than the code claims).
- **DE-363 — lazy-on-trace-open fallback.** Wire the (already-existing, currently-unused) `enqueue_treatment_derivation_job` into the ledger read so that opening a trace whose treatment is missing or stale **best-effort re-enqueues** its derivation, instead of leaving the async-only path's gaps permanent. ADR 0019 D2 names this as part of the intended design; PR1's enqueue docstring already *claims* "re-derived on demand when the Ledger UI queries the signal" — this builds that wiring.

### In scope
- DE-364: a `begin_nested()` SAVEPOINT around the parent-insert path + catch-conflict-and-reuse.
- DE-363: a pure "which turns need (re)derivation?" helper, `_job_id` dedup on the enqueue, and the GET /ledger handler enqueue.
- Regression tests for both (concurrency isolation; lazy enqueue on null/stale, dedup, no-enqueue-when-fresh).

### Out of scope (deferred)
- A `treatment_pending` read-shape hint / "deriving…" UI state (the read shape stays unchanged; a UI slice can add it later if wanted).
- Synchronous on-read derivation (re-enqueue only is the conservative default; ADR 0019 D2 / PRD DE-363).
- Concurrent-judge-race hardening on a reused row (a turn that loses the parent insert skips its judge pass, so no two turns judge the same row in this design).
- Any schema change.

---

## 2. DE-364 — per-cluster SAVEPOINT isolation

### Problem (precise)
In `derive_treatment_for_message` (`api/app/citation/treatment.py`), the per-cluster loop selects an `existing` row by `cluster_id`; on `None` it INSERTs and `flush()`es. Two concurrent turns citing the same uncached case both see `existing is None` and both INSERT → the loser's `flush()` raises `IntegrityError` on `uq_citation_treatment_cluster_id`. The session enters pending-rollback; the loop's per-cluster `try/except` catches *this* cluster's error, but the session is now unusable, so every *subsequent* cluster's `flush()` raises `PendingRollbackError`. A multi-cluster turn loses all remaining derivations.

### Design
Wrap **only the parent-insert path** in a SAVEPOINT, and on conflict re-read + reuse the row the concurrent winner inserted:

```
if existing is None:
    try:
        async with db.begin_nested():          # SAVEPOINT
            row = CitationTreatment(...graph-only...)
            db.add(row)
            await db.flush()                    # may raise IntegrityError here
        treatment_row = row
        cluster_to_treatment[cluster_id] = row.id
    except IntegrityError:
        # A concurrent turn inserted this cluster first. Exiting the `async with
        # db.begin_nested()` block on the exception already rolled back TO the
        # savepoint, so the outer session is usable. Re-read and REUSE the
        # winner's row; link only, and SKIP this turn's judge pass.
        winner = (await db.execute(
            select(CitationTreatment).where(CitationTreatment.cluster_id == cluster_id)
        )).scalar_one()
        cluster_to_treatment[cluster_id] = winner.id
        continue                                # to next cluster; no judge pass this turn
else:
    ...existing refresh path (unchanged; an UPDATE by PK can't hit the unique constraint)...
```

- The `async with db.begin_nested()` block establishes a SAVEPOINT; if the `flush()` raises, the context manager rolls back **to the savepoint** on exit, leaving the outer session usable — this is exactly the isolation the per-cluster guarantee needs.
- On the caught `IntegrityError`, the case **is now cached** (the winner committed/flushed it), so re-reading by `cluster_id` returns the winner's row; we **reuse** it (the entry links to it) rather than skip — the more correct outcome (PRD DE-364). We `continue` past this turn's judge pass for that cluster: the winning turn runs (or already ran) the judge pass; two turns must not concurrently `_run_judge_pass` the same row (the delete-then-rewrite isn't concurrency-safe). The reused row's treatment surfaces on the next read (and DE-363 re-enqueues if it's still graph-only/stale).
- **Only the insert path is wrapped.** The refresh path updates an existing row by PK and cannot raise the unique-constraint conflict. The judge pass stays **outside** the savepoint — no nested transaction is held across the slow gateway calls.
- `from sqlalchemy.exc import IntegrityError` is added.

### Note on nested savepoints in tests
The test harness wraps each test in an outer SAVEPOINT for isolation. `begin_nested()` nests a further savepoint, which Postgres supports. The concurrency test forces the conflict by **pre-inserting a colliding `citation_treatment` row** for one cluster of a multi-cluster turn (simulating the concurrent winner), then runs `derive_treatment_for_message` and asserts the other clusters still derive + link and the colliding cluster reuses the pre-existing row. (A monkeypatched `flush`-raises-once is the fallback if pre-insertion doesn't reproduce the path.)

---

## 3. DE-363 — lazy-on-trace-open fallback

### Design
Three pieces, each independently testable:

**(a) A pure helper** — `message_ids_needing_treatment` (new, in `api/app/citation/ledger.py`):
```
async def message_ids_needing_treatment(
    db, *, chat_id, message_id=None, now, ttl_days=TREATMENT_TTL_DAYS
) -> set[uuid.UUID]:
    """Distinct message_ids of caselaw ledger entries whose treatment is missing or stale."""
```
Returns the distinct `message_id`s of `CitationLedgerEntry` rows where `source_kind='caselaw'` AND (`treatment_id IS NULL` OR the linked `citation_treatment.as_of < now - ttl_days`). Scoped to `chat_id` (and `message_id` when given). Pure DB, no egress — unit-testable in isolation. `TREATMENT_TTL_DAYS` is reused from `treatment.py`.

**(b) Dedup on the enqueue** — `enqueue_treatment_derivation_job` (`api/app/workers/queue.py`):
Pass `_job_id=f"treatment:{message_id}"` to `pool.enqueue_job(...)`. arq coalesces: a job with that id already queued/running makes a repeat enqueue a no-op (returns the existing job / None), so repeated trace-opens — and the finalize-path enqueue — don't storm the queue. Once a completed job's result expires, the id frees, so a weeks-later stale refresh enqueues again. Signature unchanged; the dedup is internal. (Both the finalize path and the lazy path call the same function and so coalesce.)

**(c) The handler enqueue** — `GET /api/v1/chats/{chat_id}/ledger` (`api/app/api/chats.py`):
After `resolve_ledger_entries(...)`, call `message_ids_needing_treatment(db, chat_id=..., message_id=..., now=<utc now>)` and, for each returned id, `await enqueue_treatment_derivation_job(mid)` — best-effort (the enqueue already swallows failures and returns bool). The HTTP response is **unchanged** (treatment stays `null`/stale this read; the *next* read reflects the derived signal). Re-enqueue only — no synchronous egress on the read path; the resolver stays pure.

### Why the handler, not the resolver
`resolve_ledger_entries` is documented "pure DB; no egress" and is reused beyond this endpoint. Enqueuing (a Redis/arq side effect) belongs in the request handler, after the pure resolve. The helper that *decides* what needs derivation is pure DB and lives next to the resolver; the *side effect* lives in the handler.

---

## 4. Data flow

```
GET /chats/{id}/ledger  (handler, chats.py)
  ├─ entries = resolve_ledger_entries(db, chat_id, message_id)        [pure, unchanged]
  ├─ need = message_ids_needing_treatment(db, chat_id, message_id, now)   [DE-363 pure]
  ├─ for mid in need: enqueue_treatment_derivation_job(mid)           [DE-363 best-effort,
  │                                                                     _job_id-coalesced]
  └─ return entries                                                   [shape unchanged]

treatment_derivation_job (arq worker)  →  run_treatment_derivation
  └─ derive_treatment_for_message  (per cluster):
       ├─ existing? fresh → reuse                                     [unchanged]
       ├─ insert path  →  async with begin_nested(): add + flush      [DE-364 SAVEPOINT]
       │     └─ IntegrityError → savepoint rollback → re-read winner  [DE-364 reuse + skip judge]
       ├─ refresh path → update (no savepoint needed)                 [unchanged]
       └─ judge pass (outside the savepoint, owned rows only)         [unchanged]
```

## 5. Error handling & invariants
- **Per-cluster non-fatal now genuinely holds** for concurrent multi-cluster turns: a same-case insert conflict isolates to its cluster (SAVEPOINT) and resolves to reuse, leaving the session usable for the rest.
- **Best-effort lazy enqueue:** a failed/again-failed enqueue is logged and ignored; the read still returns. `_job_id` prevents a retry storm.
- **No new egress on the read path** (re-enqueue only).
- **Treatment never gates the turn; derive-don't-assert and P3 unchanged** — neither change touches the gate, the rollup, or what is persisted.

## 6. Testing
- **DE-364 (integration, throwaway pg):** multi-cluster turn where one cluster's parent insert conflicts with a pre-inserted row → the other clusters derive + link; the conflicting cluster reuses the pre-existing row; the conflicting cluster's judge pass is skipped; no `PendingRollbackError`. Plus: single-cluster conflict → reuse + link (no loss).
- **DE-363 helper (unit/integration):** null treatment → id returned; fresh treatment → not returned; stale treatment (`as_of` beyond TTL) → returned; non-caselaw entries excluded; scoping by `chat_id`/`message_id`.
- **DE-363 enqueue dedup (unit):** `enqueue_treatment_derivation_job` passes `_job_id=f"treatment:{message_id}"` to the pool (assert via a stub pool).
- **DE-363 handler (integration):** GET /ledger with a null-treatment caselaw turn enqueues (mock pool); fresh → no enqueue; response shape unchanged.
- **CI gate (LESSON, twice-burned):** run `ruff format --check api scripts` **and** `ruff check api scripts` from the **repo root** (covers `api/alembic/`), `mypy app` whole-app, gateway equivalents, and both full suites — not per-file/`app tests`-only.

## 7. Decisions log
- **One PR** (WS-G PR3) for both DEs — both S-effort, both close WS-G, conceptually paired (DE-364's degradation is DE-363-recoverable); one security-review cycle. SDD keeps them as distinct task groups.
- **DE-364:** SAVEPOINT around the parent insert + **re-read-and-reuse** the concurrent winner's row (link, skip this turn's judge pass); judge pass stays outside the savepoint.
- **DE-363:** handler-level best-effort **re-enqueue only**, coalesced via arq `_job_id=f"treatment:{message_id}"`; pure decision helper next to the resolver; **read shape unchanged**.
- **No migration; no `treatment_pending` hint** (YAGNI — deferred to a UI slice).
