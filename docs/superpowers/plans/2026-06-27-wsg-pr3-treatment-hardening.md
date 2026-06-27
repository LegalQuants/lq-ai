# WS-G PR3 — Treatment Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two committed WS-G follow-ups — DE-364 (per-cluster SAVEPOINT isolation so a concurrent same-case insert conflict can't poison a multi-cluster turn) and DE-363 (lazy-on-trace-open fallback that re-enqueues treatment derivation when the ledger read finds it missing/stale).

**Architecture:** DE-364 wraps the parent-insert path of `derive_treatment_for_message` in a `begin_nested()` SAVEPOINT and, on `IntegrityError`, re-reads + reuses the concurrent winner's row (skipping this turn's judge pass for that cluster). DE-363 adds a pure "which turns need (re)derivation?" helper, gives the existing `enqueue_treatment_derivation_job` an arq `_job_id` for coalescing, and calls it best-effort from the `GET /chats/{id}/ledger` handler after the (unchanged, pure) resolver.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), arq, pytest, ruff, mypy.

## Global Constraints

- **Security-gated** (`api/app/citation/**`, `api/app/api/chats.py`): security/maintainer merges; mirror `origin/main → tucuxi` after. Claude does NOT self-merge.
- **No migration** (no schema change). Next migration stays `0063`; next DE = DE-368.
- **Invariants preserved:** treatment never gates the turn; derive-don't-assert + P3 untouched (no change to what is persisted, the rollup, or the gate).
- **DE-363 is re-enqueue only** — no synchronous egress on the read path; the read response shape is **unchanged** (treatment stays `null`/stale this read).
- **`resolve_ledger_entries` stays pure** (no egress side-effect) — the enqueue lives in the HTTP handler; the *decision* helper is pure DB.
- **DE-364 reuse-not-skip:** on a concurrent-insert conflict, link the entry to the winner's row (don't leave it underived); the conflicting turn **skips its own judge pass** for that cluster (two turns must never concurrently `_run_judge_pass` the same row).
- **Tests:** host venv + throwaway pgvector `lqai-test-pg` on `:55432`, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test` (conftest auto-migrates). Mocked gateway/pool → no `-m provider`. Use `api/.venv/bin/python`.
- **CI gate (LESSON, burned twice):** run from the **repo root** — `ruff format --check api scripts` AND `ruff check api scripts` (covers `api/alembic/`), `mypy app` whole-app; gateway equivalents; both full suites. Never the per-file / `app tests`-only scope.
- Commits: `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## File structure

| File | Responsibility | Task |
|---|---|---|
| `api/app/citation/treatment.py` | DE-364 SAVEPOINT + reuse in the insert path | 1 |
| `api/tests/citation/test_treatment_concurrency.py` | DE-364 isolation+reuse test (new) | 1 |
| `api/app/citation/ledger.py` | DE-363 pure `message_ids_needing_treatment` helper | 2 |
| `api/tests/citation/test_treatment_needed.py` | helper tests (new) | 2 |
| `api/app/workers/queue.py` | DE-363 `_job_id` dedup on the enqueue | 3 |
| `api/tests/...workers/...` | enqueue `_job_id` test | 3 |
| `api/app/api/chats.py` | DE-363 handler enqueue after resolve | 4 |
| `api/tests/integration/test_ledger_lazy_treatment.py` | handler enqueue test (new) | 4 |

---

### Task 1: DE-364 — SAVEPOINT isolation + reuse on concurrent insert

**Files:**
- Modify: `api/app/citation/treatment.py` (the insert branch in `derive_treatment_for_message`, currently ~lines 117-150; add `IntegrityError` import)
- Test: `api/tests/citation/test_treatment_concurrency.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: behavior change only — `derive_treatment_for_message` no longer poisons the session when one cluster's parent INSERT hits `uq_citation_treatment_cluster_id`; that cluster reuses the concurrent winner's row and skips its judge pass; signature unchanged.

- [ ] **Step 1: Write the failing test** (`api/tests/citation/test_treatment_concurrency.py`)

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.treatment import derive_treatment_for_message
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 27, tzinfo=UTC)


async def _seed_two_cluster_turn(db: AsyncSession) -> uuid.UUID:
    """An assistant turn citing two uncached cases: clusters 7001 and 7002."""
    user = User(email=f"c-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db.add(user)
    await db.flush()
    chat = Chat(owner_id=user.id, title="c")
    db.add(chat)
    await db.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x")
    db.add(msg)
    await db.flush()
    for cluster_id, opinion_id in ((7001, 8001), (7002, 8002)):
        cc = MessageCaselawCitation(
            message_id=msg.id, opinion_id=opinion_id, cluster_id=cluster_id,
            source_offset_start=0, source_offset_end=5, source_text="q",
            verified=True, verification_method="exact_match",
        )
        db.add(cc)
        await db.flush()
        db.add(CitationLedgerEntry(
            chat_id=chat.id, message_id=msg.id, source_kind="caselaw",
            message_caselaw_citation_id=cc.id, verification_status="exact_match",
        ))
        await db.flush()
    return msg.id


async def test_concurrent_insert_conflict_isolates_and_reuses(db_session: AsyncSession):
    """One cluster's parent INSERT conflicts with a concurrently-inserted row;
    the other cluster still derives + links, and the conflicting cluster reuses
    the winner's row instead of poisoning the session."""
    message_id = await _seed_two_cluster_turn(db_session)

    staged = {"done": False}

    async def fetch_staging_winner(opinion_id: int) -> dict:
        # Simulate a concurrent turn: when 7001 (opinion 8001) is being derived,
        # insert + flush the "winner" row for cluster 7001 AFTER our existing-check
        # (None) but BEFORE our own flush — so our INSERT hits the unique constraint.
        if opinion_id == 8001 and not staged["done"]:
            staged["done"] = True
            db_session.add(CitationTreatment(
                cluster_id=7001, opinion_id=8001, cited_by_count=99,
                citing_opinions=[], derived_method="citation_graph", as_of=_NOW,
            ))
            await db_session.flush()
        return {"cited_by_count": 5, "citing": []}

    # gateway=None → graph-only (no judge pass); isolates the DE-364 behavior.
    linked = await derive_treatment_for_message(
        db_session, message_id=message_id, now=_NOW, fetch_citing=fetch_staging_winner,
    )

    # Both caselaw entries are linked: 7002 to its freshly-derived row, 7001 to the winner.
    entries = (await db_session.execute(
        select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == message_id)
    )).scalars().all()
    assert len(entries) == 2
    assert all(e.treatment_id is not None for e in entries)  # NO cluster lost
    assert linked == 2

    # 7001's entry links to the winner row (cited_by_count=99 marks the winner).
    rows = {
        r.id: r for r in (await db_session.execute(select(CitationTreatment))).scalars().all()
    }
    cc_map = {
        c.id: c.cluster_id for c in (await db_session.execute(
            select(MessageCaselawCitation).where(MessageCaselawCitation.message_id == message_id)
        )).scalars().all()
    }
    by_cluster = {cc_map[e.message_caselaw_citation_id]: rows[e.treatment_id] for e in entries}
    assert by_cluster[7001].cited_by_count == 99   # reused the winner, did not overwrite
    assert by_cluster[7002].cited_by_count == 5    # derived normally
```

- [ ] **Step 2: Run it — expect failure** (the conflict poisons the session today)

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/citation/test_treatment_concurrency.py -v`
Expected: FAIL — today the second `flush()` raises `IntegrityError`/`PendingRollbackError`; the turn loses a cluster (an entry's `treatment_id` is `None`, or the call raises).

- [ ] **Step 3: Implement the SAVEPOINT + reuse.** In `treatment.py`, add the import:

```python
from sqlalchemy.exc import IntegrityError
```

Replace the insert branch (`if existing is None:` ... `treatment_row = row`) with:

```python
            if existing is None:
                row = CitationTreatment(
                    cluster_id=cluster_id,
                    opinion_id=opinion_id,
                    cited_by_count=int(payload.get("cited_by_count") or 0),
                    citing_opinions=persisted_citing,
                    derived_method="citation_graph",
                    as_of=now,
                )
                try:
                    async with db.begin_nested():  # SAVEPOINT around the conflict-prone insert
                        db.add(row)
                        await db.flush()
                except IntegrityError:
                    # A concurrent turn inserted this cluster between our existing-check
                    # and our flush. Exiting the begin_nested() block on the exception
                    # already rolled back TO the savepoint, so the session is usable.
                    # Re-read and REUSE the winner's row; link only, skip this turn's
                    # judge pass (the winner owns the row). DE-364.
                    winner = (
                        await db.execute(
                            select(CitationTreatment).where(
                                CitationTreatment.cluster_id == cluster_id
                            )
                        )
                    ).scalar_one_or_none()
                    if winner is not None:
                        cluster_to_treatment[cluster_id] = winner.id
                    else:
                        log.warning(
                            "treatment insert conflict but no winner row for cluster %s",
                            cluster_id,
                        )
                    continue  # next cluster; no judge pass for a reused/lost row
                cluster_to_treatment[cluster_id] = row.id
                treatment_row = row
            else:
```

(Leave the `else:` refresh branch and the judge-pass block below it unchanged. The `continue` lands inside the per-cluster `for` loop, correctly skipping the judge pass for the conflicting cluster.)

> GOTCHA: after a savepoint rollback the rolled-back `row` object may linger in the session's pending set. The `continue` means we never reference it again, and the next cluster's flush is what the test verifies. If Step 4 surfaces a stray-pending-object error on the *next* cluster's flush, add `db.expunge(row)` immediately before `continue`.

- [ ] **Step 4: Run it — expect pass**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/citation/test_treatment_concurrency.py tests/citation/test_treatment_derivation.py tests/citation/test_treatment_judge_pass.py -v`
Expected: PASS (new test + PR1/PR2 regressions).

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/citation/treatment.py api/tests/citation/test_treatment_concurrency.py
git commit -s -m "fix(citation): SAVEPOINT-isolate per-cluster treatment insert + reuse on conflict (DE-364)"
```

---

### Task 2: DE-363 — `message_ids_needing_treatment` helper

**Files:**
- Modify: `api/app/citation/ledger.py` (add the helper + the `TREATMENT_TTL_DAYS` import)
- Test: `api/tests/citation/test_treatment_needed.py` (new)

**Interfaces:**
- Produces: `async def message_ids_needing_treatment(db, *, chat_id: uuid.UUID, message_id: uuid.UUID | None, now: datetime, ttl_days: int = TREATMENT_TTL_DAYS) -> set[uuid.UUID]` — distinct `message_id`s of `source_kind='caselaw'` ledger entries whose `treatment_id IS NULL` OR whose linked `citation_treatment.as_of < now - ttl_days`. Pure DB.

- [ ] **Step 1: Write the failing tests** (`api/tests/citation/test_treatment_needed.py`)

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.ledger import message_ids_needing_treatment
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 27, tzinfo=UTC)


async def _entry(db, chat_id, *, source_kind, treatment_id=None, cc_id=None):
    msg = Message(chat_id=chat_id, role="assistant", kind="ai", content="x")
    db.add(msg)
    await db.flush()
    db.add(CitationLedgerEntry(
        chat_id=chat_id, message_id=msg.id, source_kind=source_kind,
        message_caselaw_citation_id=cc_id, treatment_id=treatment_id,
        verification_status="exact_match",
    ))
    await db.flush()
    return msg.id


@pytest.fixture
async def chat(db_session):
    user = User(email=f"n-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(user)
    await db_session.flush()
    c = Chat(owner_id=user.id, title="n")
    db_session.add(c)
    await db_session.flush()
    return c.id


async def _treatment(db, *, cluster_id, as_of):
    t = CitationTreatment(cluster_id=cluster_id, opinion_id=cluster_id, cited_by_count=0,
                          citing_opinions=[], derived_method="citation_graph", as_of=as_of)
    db.add(t)
    await db.flush()
    return t


async def test_null_treatment_caselaw_is_needed(db_session, chat):
    mid = await _entry(db_session, chat, source_kind="caselaw", treatment_id=None)
    out = await message_ids_needing_treatment(db_session, chat_id=chat, message_id=None, now=_NOW)
    assert mid in out


async def test_fresh_treatment_not_needed(db_session, chat):
    t = await _treatment(db_session, cluster_id=1, as_of=_NOW)
    mid = await _entry(db_session, chat, source_kind="caselaw", treatment_id=t.id)
    out = await message_ids_needing_treatment(db_session, chat_id=chat, message_id=None, now=_NOW)
    assert mid not in out


async def test_stale_treatment_is_needed(db_session, chat):
    t = await _treatment(db_session, cluster_id=2, as_of=_NOW - timedelta(days=31))
    mid = await _entry(db_session, chat, source_kind="caselaw", treatment_id=t.id)
    out = await message_ids_needing_treatment(db_session, chat_id=chat, message_id=None, now=_NOW)
    assert mid in out


async def test_non_caselaw_excluded(db_session, chat):
    mid = await _entry(db_session, chat, source_kind="document", treatment_id=None)
    out = await message_ids_needing_treatment(db_session, chat_id=chat, message_id=None, now=_NOW)
    assert mid not in out


async def test_message_id_scopes(db_session, chat):
    mid1 = await _entry(db_session, chat, source_kind="caselaw", treatment_id=None)
    mid2 = await _entry(db_session, chat, source_kind="caselaw", treatment_id=None)
    out = await message_ids_needing_treatment(db_session, chat_id=chat, message_id=mid1, now=_NOW)
    assert out == {mid1} and mid2 not in out
```

- [ ] **Step 2: Run — expect failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/citation/test_treatment_needed.py -v`
Expected: FAIL — `ImportError: cannot import name 'message_ids_needing_treatment'`.

- [ ] **Step 3: Implement the helper** in `api/app/citation/ledger.py`. Add imports near the top:

```python
from datetime import datetime, timedelta

from app.citation.treatment import TREATMENT_TTL_DAYS
```

> If importing from `app.citation.treatment` creates a circular import (treatment.py imports from ledger or vice-versa), define `TREATMENT_TTL_DAYS = 30` locally in `ledger.py` with a comment that it mirrors `treatment.TREATMENT_TTL_DAYS`. Check the import direction first; `treatment.py` does not import `ledger`, so the import should be safe.

Add the helper (place it next to `resolve_ledger_entries`):

```python
async def message_ids_needing_treatment(
    db: AsyncSession,
    *,
    chat_id: uuid.UUID,
    message_id: uuid.UUID | None,
    now: datetime,
    ttl_days: int = TREATMENT_TTL_DAYS,
) -> set[uuid.UUID]:
    """Distinct message_ids of caselaw ledger entries whose treatment is missing or stale.

    Pure DB (no egress). A caselaw entry needs (re)derivation when its
    ``treatment_id`` is NULL, or when the linked ``citation_treatment`` row's
    ``as_of`` is older than ``now - ttl_days``. Used by the GET /ledger handler
    to best-effort re-enqueue derivation (DE-363); never mutates.
    """
    cutoff = now - timedelta(days=ttl_days)
    stmt = (
        select(CitationLedgerEntry.message_id)
        .outerjoin(CitationTreatment, CitationLedgerEntry.treatment_id == CitationTreatment.id)
        .where(
            CitationLedgerEntry.chat_id == chat_id,
            CitationLedgerEntry.source_kind == "caselaw",
            or_(
                CitationLedgerEntry.treatment_id.is_(None),
                CitationTreatment.as_of < cutoff,
            ),
        )
    )
    if message_id is not None:
        stmt = stmt.where(CitationLedgerEntry.message_id == message_id)
    rows = (await db.execute(stmt)).scalars().all()
    return set(rows)
```

Ensure `or_` is imported from `sqlalchemy` (extend the existing `from sqlalchemy import ...` line). `CitationTreatment` is already imported in `ledger.py`.

- [ ] **Step 4: Run — expect pass**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/citation/test_treatment_needed.py -v`
Expected: PASS (5/5).

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/citation/ledger.py api/tests/citation/test_treatment_needed.py
git commit -s -m "feat(citation): message_ids_needing_treatment helper (DE-363)"
```

---

### Task 3: DE-363 — `_job_id` dedup on the enqueue

**Files:**
- Modify: `api/app/workers/queue.py` (`enqueue_treatment_derivation_job`)
- Test: locate the existing queue test module (e.g. `api/tests/.../test_queue*.py` or `api/tests/workers/...`); add the test there, or create `api/tests/workers/test_treatment_enqueue.py` if none exists.

**Interfaces:**
- Produces: `enqueue_treatment_derivation_job` passes `_job_id=f"treatment:{message_id}"` to `pool.enqueue_job(...)`. Signature + return type unchanged.

- [ ] **Step 1: Write the failing test.** A stub pool captures the `enqueue_job` kwargs.

```python
import uuid
import pytest
from app.workers import queue as q

pytestmark = pytest.mark.asyncio


async def test_enqueue_treatment_uses_dedup_job_id(monkeypatch):
    captured = {}

    class _Pool:
        async def enqueue_job(self, name, *args, **kwargs):
            captured["name"] = name
            captured["args"] = args
            captured["kwargs"] = kwargs
            return object()

    async def _fake_pool():
        return _Pool()

    monkeypatch.setattr(q, "_get_pool", _fake_pool)
    mid = uuid.uuid4()
    ok = await q.enqueue_treatment_derivation_job(mid)
    assert ok is True
    assert captured["name"] == q.TREATMENT_DERIVATION_JOB_NAME
    assert captured["args"] == (str(mid),)
    assert captured["kwargs"].get("_job_id") == f"treatment:{mid}"
```

> Match the real `_get_pool` name/location in `queue.py` (it is referenced by the existing enqueue functions). If the test module path differs, follow the convention of the nearest existing queue test.

- [ ] **Step 2: Run — expect failure**

Run: `cd api && .venv/bin/python -m pytest tests/workers/test_treatment_enqueue.py -v` (adjust path)
Expected: FAIL — `_job_id` missing from captured kwargs.

- [ ] **Step 3: Implement.** In `enqueue_treatment_derivation_job`, change the enqueue call:

```python
        await pool.enqueue_job(
            TREATMENT_DERIVATION_JOB_NAME,
            str(message_id),
            _job_id=f"treatment:{message_id}",
        )
```

Update the docstring line to note: "Coalesced via arq ``_job_id`` so the finalize-path and the lazy read-path (DE-363) enqueues for one turn de-duplicate."

- [ ] **Step 4: Run — expect pass**

Run: `cd api && .venv/bin/python -m pytest tests/workers/test_treatment_enqueue.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/workers/queue.py api/tests/workers/test_treatment_enqueue.py
git commit -s -m "feat(worker): coalesce treatment enqueue via arq _job_id (DE-363)"
```

---

### Task 4: DE-363 — handler enqueue from GET /ledger

**Files:**
- Modify: `api/app/api/chats.py` (`get_chat_ledger`, ~line 1789-1821)
- Test: `api/tests/integration/test_ledger_lazy_treatment.py` (new)

**Interfaces:**
- Consumes: `message_ids_needing_treatment` (Task 2); `enqueue_treatment_derivation_job` (already imported in `chats.py` at line 131).
- Produces: `get_chat_ledger` best-effort enqueues derivation for each needing-treatment message_id after resolving; response shape unchanged.

- [ ] **Step 1: Write the failing test** (`api/tests/integration/test_ledger_lazy_treatment.py`)

```python
from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_ledger_read_enqueues_for_null_treatment(
    async_client: AsyncClient, auth_headers, seed_caselaw_turn_null_treatment, monkeypatch
):
    """GET /ledger best-effort enqueues derivation for a caselaw turn whose
    treatment is not yet derived; the response shape is unchanged."""
    from app.api import chats as chats_mod

    enqueued: list[uuid.UUID] = []

    async def _spy(message_id):
        enqueued.append(message_id)
        return True

    monkeypatch.setattr(chats_mod, "enqueue_treatment_derivation_job", _spy)

    chat_id, message_id = seed_caselaw_turn_null_treatment
    resp = await async_client.get(f"/api/v1/chats/{chat_id}/ledger", headers=auth_headers)
    assert resp.status_code == 200
    assert message_id in enqueued
    body = resp.json()
    assert "entries" in body and "gates" in body  # shape unchanged
```

> This test depends on the project's existing auth/client fixtures (`async_client`, `auth_headers`) and a seed of a caselaw turn with a null-treatment ledger entry. Reuse the patterns in `api/tests/integration/test_citation_ledger.py` (which already exercises `GET /ledger`); build `seed_caselaw_turn_null_treatment` from that file's existing seeding, returning `(chat_id, message_id)`. If those fixtures have different names, match them. If wiring a full HTTP test against the existing harness proves heavy, an acceptable alternative is to call `get_chat_ledger(...)` directly with a stub `db`/`user` and assert the spy — but prefer the HTTP path to cover the real handler.

- [ ] **Step 2: Run — expect failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/integration/test_ledger_lazy_treatment.py -v`
Expected: FAIL — handler does not enqueue yet (`enqueued` empty).

- [ ] **Step 3: Implement.** In `get_chat_ledger` (`chats.py`), import the helper at the top with the other `app.citation.ledger` imports:

```python
from app.citation.ledger import (
    assemble_ledger_entries,
    message_ids_needing_treatment,
    resolve_ledger_entries,
)
```

After `entries = await resolve_ledger_entries(...)` and `gates = await resolve_gates(...)`, before the `return`, add the best-effort lazy enqueue:

```python
    # DE-363: lazy-on-trace-open fallback — best-effort re-enqueue derivation for
    # any caselaw turn whose treatment is missing/stale. Re-enqueue only (no
    # synchronous egress); the enqueue is coalesced by _job_id, and never blocks
    # the read. The response shape is unchanged — the derived signal appears on
    # the next read.
    try:
        needing = await message_ids_needing_treatment(
            db, chat_id=cid, message_id=mid, now=datetime.now(UTC)
        )
        for need_mid in needing:
            await enqueue_treatment_derivation_job(need_mid)
    except Exception as exc:  # never block the read on the fallback
        log.warning("lazy treatment enqueue failed: %r", exc)

    return {"chat_id": str(cid), "entries": entries, "gates": gates}
```

Ensure `datetime`/`UTC` are imported in `chats.py` (`from datetime import UTC, datetime` — check the existing imports; add only if missing). `log` is the module logger (already present).

- [ ] **Step 4: Run — expect pass + the existing ledger endpoint test**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/integration/test_ledger_lazy_treatment.py tests/integration/test_citation_ledger.py tests/integration/test_ledger_treatment_exposure.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/api/chats.py api/tests/integration/test_ledger_lazy_treatment.py
git commit -s -m "feat(api): lazy-on-trace-open treatment re-enqueue from GET /ledger (DE-363)"
```

---

## Final gate (before requesting review — the twice-burned CI LESSON)

- [ ] **api full gates at CI scope (repo root):**
```bash
cd /Users/kevinkeller/Code/lq-ai
api/.venv/bin/ruff check api scripts && api/.venv/bin/ruff format --check api scripts
cd api && .venv/bin/mypy app
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest -q
```
- [ ] **gateway full gates:** `cd gateway && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app --strict && .venv/bin/python -m pytest -q` (PR3 doesn't touch gateway; run to confirm no incidental break).
- [ ] **OpenAPI:** the `/ledger` response shape is unchanged (no schema edit needed); confirm `tests/test_openapi.py` still passes.
- [ ] **PRD bookkeeping:** mark DE-363 and DE-364 **Status: SHIPPED (WS-G PR3)** in `docs/PRD.md`.
- [ ] **Opus whole-branch review** (SDD final) — required; it has caught a real gate-passing defect on every slice this milestone.

## Plan self-review (completed)

- **Spec coverage:** DE-364 SAVEPOINT+reuse → Task 1; DE-363 helper → Task 2; `_job_id` dedup → Task 3; handler enqueue → Task 4. Out-of-scope items (no `treatment_pending`, no sync derivation, no migration) honored. Both invariants (treatment never gates; P3/derive-don't-assert untouched) hold — no task changes the gate, rollup, or persisted shape.
- **Placeholder scan:** complete code/commands throughout. The three "match the existing fixture/path" notes (Task 3 queue-test path, Task 4 auth fixtures, Task 2 circular-import check) are existing-code lookups with the asserted contract fixed — not placeholders.
- **Type consistency:** `message_ids_needing_treatment(db, *, chat_id, message_id, now, ttl_days) -> set[uuid.UUID]`, `enqueue_treatment_derivation_job(message_id) -> bool` with `_job_id=f"treatment:{message_id}"`, and the SAVEPOINT/`scalar_one_or_none()` reuse are consistent across Tasks 1-4.
