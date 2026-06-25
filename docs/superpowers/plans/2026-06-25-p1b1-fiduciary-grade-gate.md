# P1-B1 — Deterministic fiduciary-grade gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute a per-turn fiduciary-grade verdict (ADR 0018 D3) deterministically over the turn's citation-ledger entries — PASS `{exact_match, tolerant_match}` / SUPPORTED `{paraphrase_judge, ensemble_*}` / FAIL `{unverified, failed}` — record it on a new 1:1 `work_product_fiduciary_gate` table, hook it at finalize, and surface it in the A3 `/ledger` endpoint.

**Architecture:** A new metadata-only table + model; a pure-DB gate module (`app/citation/gate.py`) that buckets ledger entries by `verification_status` and upserts a verdict; a one-line assembler mislabel fix so unverified KB citations are honest; the gate hooked at the three finalize sites alongside `assemble_ledger_entries`; and a `gates` key added to the merged A3 `/ledger` response. No egress; deterministic.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic (migration 0059), pytest (`integration` marker) against a throwaway pgvector.

## Global Constraints

- **No new egress** — pure DB reads + writes; no gateway/LLM call. The DE-280 paraphrase judge is P1-B1b, out of scope here.
- **Gate row is metadata-only** — status label + integer counts + a numeric confidence + ids + timestamp; **no content**. It joins the `test_transparency_invariants.py` P3 tripwire (`_AUDIT_MODELS`).
- **Status sets (exact strings):** PASS = `{"exact_match", "tolerant_match"}`; SUPPORTED = `{"paraphrase_judge", "ensemble_strict", "ensemble_majority"}`; FAIL = `{"unverified", "failed"}`. `"provenance"` entries (tool sources, no quote) are **not** assertions — excluded from all counts.
- **`gate_status` derivation:** `flagged` if `fail_count > 0`; else `supported_only` if `supported_count > 0`; else `fiduciary_grade` (zero-assertion turn → `fiduciary_grade`, `total_assertions=0`, vacuously true).
- **`confidence`** = mean of counted entries' non-null `confidence` values; `None` if none.
- **1:1 per assistant message** — `work_product_fiduciary_gate.message_id` is `UNIQUE`; re-finalize **upserts** (delete-then-insert) the verdict (current-verdict, not history; the ledger entries are the history-preserving record per ADR D7).
- **Conservative posture** — the gate hook is guarded at every finalize site (`try/except … log`, never re-raise); an unrecognized `verification_status` is excluded from buckets and logged, never silently counted as PASS.
- **Assembler mislabel fix** — `assemble_ledger_entries` currently writes `verification_status = c.verification_method or "verified"` for KB `message_citations`; an unverified row (`verified=False`, `verification_method=None`) is thus mislabeled `"verified"`. Fix to `c.verification_method if c.verified else "unverified"` (confidence `None` when unverified). Same defensive correction on the caselaw branch.
- **Migration discipline:** new revision `0059`, `down_revision="0058"`. NEVER run host `alembic upgrade` against the dev DB; the conftest auto-migrates the throwaway pgvector to `head`. Register the new model in `app/models/__init__.py` (else alembic/metadata won't see it).
- **P5 (atomic audit):** the gate helper **flushes, never commits** — it rides the caller's transaction.
- **Tests:** host venv + throwaway pgvector (`DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test`). Run `ruff format` + `ruff check` + `mypy app` + `pytest` (coverage no-decrease). No `-m provider`.
- **Security review (CODEOWNERS):** citation/audit surface — do not self-merge.
- **Commits:** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: `work_product_fiduciary_gate` table + model + migration 0059 + P3 tripwire

**Files:**
- Create: `api/app/models/work_product_fiduciary_gate.py`
- Modify: `api/app/models/__init__.py` (register the model)
- Create: `api/alembic/versions/0059_work_product_fiduciary_gate.py`
- Modify: `api/tests/test_transparency_invariants.py` (add to `_AUDIT_MODELS`)
- Test: `api/tests/integration/test_work_product_fiduciary_gate.py` (new)

**Interfaces:**
- Produces: `WorkProductFiduciaryGate` ORM model — columns `id, message_id (unique), chat_id, project_id, gate_status, pass_count, supported_count, fail_count, total_assertions, confidence, created_at`. Used by Task 2's gate module.

- [ ] **Step 1: Write the failing test**

Create `api/tests/integration/test_work_product_fiduciary_gate.py`:

```python
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.chat import Chat, Message
from app.models.user import User
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_message(db_session):
    user = User(
        email=f"gate-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role="member",
    )
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="gate test")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="answer")
    db_session.add(msg)
    await db_session.flush()
    return chat.id, msg.id


@pytest.mark.asyncio
async def test_gate_row_roundtrips(db_session, seeded_message):
    chat_id, mid = seeded_message
    db_session.add(
        WorkProductFiduciaryGate(
            message_id=mid,
            chat_id=chat_id,
            gate_status="fiduciary_grade",
            pass_count=2,
            supported_count=0,
            fail_count=0,
            total_assertions=2,
            confidence=0.97,
        )
    )
    await db_session.flush()
    got = (
        await db_session.execute(
            select(WorkProductFiduciaryGate).where(WorkProductFiduciaryGate.message_id == mid)
        )
    ).scalar_one()
    assert got.gate_status == "fiduciary_grade"
    assert got.total_assertions == 2
    assert got.confidence == 0.97


@pytest.mark.asyncio
async def test_message_id_unique(db_session, seeded_message):
    chat_id, mid = seeded_message
    for _ in range(2):
        db_session.add(
            WorkProductFiduciaryGate(
                message_id=mid,
                chat_id=chat_id,
                gate_status="flagged",
                pass_count=0,
                supported_count=0,
                fail_count=1,
                total_assertions=1,
                confidence=None,
            )
        )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_confidence_range_check(db_session, seeded_message):
    chat_id, mid = seeded_message
    db_session.add(
        WorkProductFiduciaryGate(
            message_id=mid,
            chat_id=chat_id,
            gate_status="fiduciary_grade",
            pass_count=1,
            supported_count=0,
            fail_count=0,
            total_assertions=1,
            confidence=1.5,  # out of [0,1]
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_work_product_fiduciary_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: app.models.work_product_fiduciary_gate` (and the conftest migration won't have the table until the migration exists).

- [ ] **Step 3: Create the model**

Create `api/app/models/work_product_fiduciary_gate.py`:

```python
"""work_product_fiduciary_gate — the per-turn fiduciary-grade verdict (ADR 0018 D3).

One row per assistant turn (UNIQUE on message_id): the computed gate verdict
(``fiduciary_grade`` | ``supported_only`` | ``flagged``) plus per-tier counts and
an aggregate confidence, derived deterministically from the turn's
``citation_ledger_entry`` rows. Metadata-only — a status label, integer counts,
and a numeric confidence; it holds NO content, so it joins the P3 no-raw-payload
tripwire. The history-preserving record is the ledger; this verdict is upserted
(current-verdict) on re-finalize.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class WorkProductFiduciaryGate(Base):
    __tablename__ = "work_product_fiduciary_gate"
    __table_args__ = (
        CheckConstraint(
            "gate_status IN ('fiduciary_grade', 'supported_only', 'flagged')",
            name="chk_work_product_fiduciary_gate_status_values",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="chk_work_product_fiduciary_gate_confidence_range",
        ),
        CheckConstraint(
            "pass_count >= 0 AND supported_count >= 0 AND fail_count >= 0 "
            "AND total_assertions >= 0",
            name="chk_work_product_fiduciary_gate_counts_nonneg",
        ),
        Index("ix_work_product_fiduciary_gate_chat_id", "chat_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "messages.id", ondelete="CASCADE", name="fk_work_product_fiduciary_gate_message"
        ),
        nullable=False,
        unique=True,
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE", name="fk_work_product_fiduciary_gate_chat"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "projects.id", ondelete="SET NULL", name="fk_work_product_fiduciary_gate_project"
        ),
        nullable=True,
    )
    gate_status: Mapped[str] = mapped_column(Text, nullable=False)
    pass_count: Mapped[int] = mapped_column(Integer, nullable=False)
    supported_count: Mapped[int] = mapped_column(Integer, nullable=False)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_assertions: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
```

Add to `api/app/models/__init__.py` (next to the `work_product` import, line ~49):

```python
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate
```

If `__init__.py` has an `__all__`, add `"WorkProductFiduciaryGate"` to it.

- [ ] **Step 4: Create the migration**

Create `api/alembic/versions/0059_work_product_fiduciary_gate.py` (mirror `0058`'s style):

```python
"""work_product_fiduciary_gate — fiduciary-grade verdict (ADR 0018 D3)

Revision ID: 0059
Revises: 0058
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_product_fiduciary_gate",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "messages.id",
                ondelete="CASCADE",
                name="fk_work_product_fiduciary_gate_message",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "chat_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "chats.id", ondelete="CASCADE", name="fk_work_product_fiduciary_gate_chat"
            ),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "projects.id",
                ondelete="SET NULL",
                name="fk_work_product_fiduciary_gate_project",
            ),
            nullable=True,
        ),
        sa.Column("gate_status", sa.Text(), nullable=False),
        sa.Column("pass_count", sa.Integer(), nullable=False),
        sa.Column("supported_count", sa.Integer(), nullable=False),
        sa.Column("fail_count", sa.Integer(), nullable=False),
        sa.Column("total_assertions", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "gate_status IN ('fiduciary_grade', 'supported_only', 'flagged')",
            name="chk_work_product_fiduciary_gate_status_values",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="chk_work_product_fiduciary_gate_confidence_range",
        ),
        sa.CheckConstraint(
            "pass_count >= 0 AND supported_count >= 0 AND fail_count >= 0 "
            "AND total_assertions >= 0",
            name="chk_work_product_fiduciary_gate_counts_nonneg",
        ),
    )
    op.create_index(
        "ix_work_product_fiduciary_gate_chat_id",
        "work_product_fiduciary_gate",
        ["chat_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_work_product_fiduciary_gate_chat_id", table_name="work_product_fiduciary_gate"
    )
    op.drop_table("work_product_fiduciary_gate")
```

- [ ] **Step 5: Add to the P3 tripwire**

In `api/tests/test_transparency_invariants.py`, add the import and the model to `_AUDIT_MODELS`:

```python
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate
```

```python
_AUDIT_MODELS: tuple[type, ...] = (
    ToolCallLog,
    AuditLog,
    ToolEgressLog,
    InferenceRoutingLog,
    CitationLedgerEntry,
    WorkProductFiduciaryGate,
)
```

- [ ] **Step 6: Run the tests**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_work_product_fiduciary_gate.py tests/test_transparency_invariants.py -v`
Expected: all PASS (roundtrip, unique, confidence-range; tripwire green with the new model — its column names `gate_status`/`*_count`/`total_assertions`/`confidence` do not trip `_implies_raw_content`).

- [ ] **Step 7: Lint + type-check, then commit**

```bash
cd api && .venv/bin/ruff format app/models/work_product_fiduciary_gate.py alembic/versions/0059_work_product_fiduciary_gate.py tests/integration/test_work_product_fiduciary_gate.py && .venv/bin/ruff check app/models tests/integration/test_work_product_fiduciary_gate.py && .venv/bin/mypy app/models/work_product_fiduciary_gate.py
```

```bash
git add api/app/models/work_product_fiduciary_gate.py api/app/models/__init__.py api/alembic/versions/0059_work_product_fiduciary_gate.py api/tests/test_transparency_invariants.py api/tests/integration/test_work_product_fiduciary_gate.py
git commit -s -m "feat(citation): work_product_fiduciary_gate table (P1-B1)

The per-turn fiduciary-grade verdict (ADR 0018 D3): 1:1-per-message,
metadata-only (status label + per-tier counts + aggregate confidence),
migration 0059. Joins the P3 no-raw-payload tripwire.

Refs ADR 0018 D3/D5.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Gate computation `compute_and_record_gate` + assembler mislabel fix

**Files:**
- Create: `api/app/citation/gate.py`
- Modify: `api/app/citation/ledger.py` (assembler mislabel fix in `assemble_ledger_entries`)
- Test: `api/tests/integration/test_fiduciary_gate.py` (new)

**Interfaces:**
- Consumes: `WorkProductFiduciaryGate` (Task 1); `CitationLedgerEntry`, `Chat`, `Message` models.
- Produces: `async def compute_and_record_gate(db: AsyncSession, *, message_id: uuid.UUID) -> WorkProductFiduciaryGate | None` and module constants `PASS_STATUSES`, `SUPPORTED_STATUSES`, `FAIL_STATUSES` — used by Task 3's hook. Also `async def resolve_gates(db: AsyncSession, *, chat_id: uuid.UUID, message_id: uuid.UUID | None = None) -> list[dict[str, Any]]` for Task 3's endpoint wiring.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/integration/test_fiduciary_gate.py`:

```python
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.citation.gate import compute_and_record_gate, resolve_gates
from app.citation.ledger import assemble_ledger_entries
from app.models.chat import Chat, Message, MessageCitation
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.file import File as FileModel
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded(db_session):
    user = User(
        email=f"g-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="member"
    )
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="gate")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="a")
    db_session.add(msg)
    await db_session.flush()
    return user, chat, msg


async def _seed_entry(db_session, chat, msg, status, conf, *, opinion_id):
    """Create an FK-valid caselaw-citation-backed ledger entry whose
    verification_status is overridden to ``status`` (the entry's status is what
    the gate reads — it need not equal the citation's real method)."""
    cc = MessageCaselawCitation(
        message_id=msg.id,
        opinion_id=opinion_id,
        cluster_id=opinion_id,
        source_offset_start=0,
        source_offset_end=3,
        source_text="abc",
        verified=True,
        verification_method="exact_match",
        verification_confidence=1.0,
    )
    db_session.add(cc)
    await db_session.flush()
    db_session.add(
        CitationLedgerEntry(
            chat_id=chat.id,
            message_id=msg.id,
            source_kind="caselaw",
            message_caselaw_citation_id=cc.id,
            verification_status=status,
            confidence=conf,
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_all_pass_is_fiduciary_grade(db_session, seeded):
    user, chat, msg = seeded
    # Seed ledger entries directly via real caselaw-citation rows so FKs resolve.
    for status, conf in [("exact_match", 1.0), ("tolerant_match", 0.95)]:
        cc = MessageCaselawCitation(
            message_id=msg.id,
            opinion_id=1,
            cluster_id=1,
            source_offset_start=0,
            source_offset_end=3,
            source_text="abc",
            verified=True,
            verification_method=status,
            verification_confidence=conf,
        )
        db_session.add(cc)
        await db_session.flush()
        db_session.add(
            CitationLedgerEntry(
                chat_id=chat.id,
                message_id=msg.id,
                source_kind="caselaw",
                message_caselaw_citation_id=cc.id,
                verification_status=status,
                confidence=conf,
            )
        )
    await db_session.flush()

    gate = await compute_and_record_gate(db_session, message_id=msg.id)
    assert gate is not None
    assert gate.gate_status == "fiduciary_grade"
    assert gate.pass_count == 2
    assert gate.supported_count == 0
    assert gate.fail_count == 0
    assert gate.total_assertions == 2
    assert abs(gate.confidence - 0.975) < 1e-6
```

> **Implementer note:** the `CitationLedgerEntry` exactly-one-FK CHECK means every fabricated entry needs a real backing row, so use the `_seed_entry` helper above (a `MessageCaselawCitation` + a ledger entry referencing it with an overridden `verification_status`) for every status case — vary `opinion_id` per call to keep rows distinct. `test_all_pass_is_fiduciary_grade` above shows the inline pattern; the remaining tests can call `_seed_entry` directly. For the `provenance` case create a real `MessageToolSource` + an entry referencing it via `message_tool_source_id` (see `tests/integration/test_citation_ledger.py` for that shape).

The full test set the implementer must produce (using `_seed_entry` / the provenance shape):
- `test_all_pass_is_fiduciary_grade` — two PASS entries → `fiduciary_grade`, counts (2,0,0,2), confidence ≈ 0.975.
- `test_supported_only_when_paraphrase_no_fail` — one `tolerant_match` + one `paraphrase_judge`, no FAIL → `supported_only`, counts (1,1,0,2).
- `test_any_fail_is_flagged` — one `exact_match` + one `unverified` → `flagged`, counts (1,0,1,2), confidence = mean of non-null (the `unverified` entry has confidence `None`, so confidence = 1.0).
- `test_provenance_excluded` — one `exact_match` (PASS) + one `provenance` entry (via a real `MessageToolSource`) → `total_assertions == 1`, `pass_count == 1`, provenance not counted.
- `test_zero_assertions_is_fiduciary_grade` — only a `provenance` entry (or none) → `fiduciary_grade`, `total_assertions == 0`, confidence `None`.
- `test_unknown_status_excluded` — an entry with `verification_status="weird"` + one `exact_match` → counted total is 1, the unknown is excluded (assert `total_assertions == 1`).
- `test_upsert_replaces` — call `compute_and_record_gate` twice; assert exactly one row for the message and the second call's verdict wins (change the entries between calls).
- `test_resolve_gates_shapes` — after recording, `resolve_gates(db, chat_id=chat.id)` returns a list with one dict carrying `message_id, gate_status, pass_count, supported_count, fail_count, total_assertions, confidence, created_at`; `message_id` filter narrows.
- `test_assembler_marks_unverified_kb_citation` — seed a `message_citations` row with `verified=False, verification_method=None` (needs a real `File` row: kwargs `owner_id, filename, mime_type, size_bytes, hash_sha256, storage_path`), run `assemble_ledger_entries`, assert the resulting ledger entry has `verification_status == "unverified"` and `confidence is None` (regression-locks the mislabel fix), then `compute_and_record_gate` → `fail_count == 1`, `gate_status == "flagged"`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_fiduciary_gate.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_and_record_gate'` / `resolve_gates`.

- [ ] **Step 3: Implement the assembler mislabel fix**

In `api/app/citation/ledger.py`, in `assemble_ledger_entries`, replace the KB `message_citations` branch's status/confidence:

```python
    for c in doc_citations:
        entries.append(
            CitationLedgerEntry(
                project_id=project_id,
                chat_id=chat_id,
                message_id=message_id,
                source_kind="kb_document",
                message_citation_id=c.id,
                verification_status=c.verification_method if c.verified else "unverified",
                confidence=(
                    float(c.verification_confidence)
                    if (c.verified and c.verification_confidence is not None)
                    else None
                ),
                provider=None,
                retrieved_at=None,
            )
        )
```

And the caselaw branch (defensive symmetry — today only verified rows reach it):

```python
            verification_status=cc.verification_method if cc.verified else "unverified",
            confidence=cc.verification_confidence if cc.verified else None,
```

- [ ] **Step 4: Implement the gate module**

Create `api/app/citation/gate.py`:

```python
"""Fiduciary-grade gate computation (ADR 0018 D3).

Deterministically buckets a turn's ``citation_ledger_entry`` rows into PASS /
SUPPORTED / FAIL by their mirrored ``verification_status`` and records one
``work_product_fiduciary_gate`` verdict per assistant message. Pure DB; no egress.
Provenance-only entries (tool sources, no quote) are not assertions and are
excluded from the counts.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate

log = logging.getLogger(__name__)

PASS_STATUSES: frozenset[str] = frozenset({"exact_match", "tolerant_match"})
SUPPORTED_STATUSES: frozenset[str] = frozenset(
    {"paraphrase_judge", "ensemble_strict", "ensemble_majority"}
)
FAIL_STATUSES: frozenset[str] = frozenset({"unverified", "failed"})
_PROVENANCE = "provenance"


async def compute_and_record_gate(
    db: AsyncSession, *, message_id: uuid.UUID
) -> WorkProductFiduciaryGate | None:
    """Compute the fiduciary-grade verdict for ``message_id`` and upsert it.

    Returns the recorded row, or ``None`` if the message has no chat (should not
    happen at finalize). Flushes, never commits (rides the caller's transaction).
    """
    chat_id = (
        await db.execute(select(Message.chat_id).where(Message.id == message_id))
    ).scalar_one_or_none()
    if chat_id is None:
        return None
    project_id = (
        await db.execute(select(Chat.project_id).where(Chat.id == chat_id))
    ).scalar_one_or_none()

    entries = (
        (
            await db.execute(
                select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == message_id)
            )
        )
        .scalars()
        .all()
    )

    pass_count = supported_count = fail_count = 0
    confidences: list[float] = []
    for e in entries:
        status = e.verification_status
        if status == _PROVENANCE:
            continue
        if status in PASS_STATUSES:
            pass_count += 1
        elif status in SUPPORTED_STATUSES:
            supported_count += 1
        elif status in FAIL_STATUSES:
            fail_count += 1
        else:
            log.warning(
                "fiduciary gate: unrecognized verification_status %r on entry %s; excluded",
                status,
                e.id,
            )
            continue
        if e.confidence is not None:
            confidences.append(e.confidence)

    total = pass_count + supported_count + fail_count
    if fail_count > 0:
        gate_status = "flagged"
    elif supported_count > 0:
        gate_status = "supported_only"
    else:
        gate_status = "fiduciary_grade"
    confidence = sum(confidences) / len(confidences) if confidences else None

    # Upsert: a re-finalize replaces the current verdict (the ledger is the history).
    await db.execute(
        delete(WorkProductFiduciaryGate).where(
            WorkProductFiduciaryGate.message_id == message_id
        )
    )
    row = WorkProductFiduciaryGate(
        message_id=message_id,
        chat_id=chat_id,
        project_id=project_id,
        gate_status=gate_status,
        pass_count=pass_count,
        supported_count=supported_count,
        fail_count=fail_count,
        total_assertions=total,
        confidence=confidence,
    )
    db.add(row)
    await db.flush()
    return row


async def resolve_gates(
    db: AsyncSession, *, chat_id: uuid.UUID, message_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """Return the fiduciary-grade verdict(s) for a chat (optionally one turn)."""
    stmt = select(WorkProductFiduciaryGate).where(WorkProductFiduciaryGate.chat_id == chat_id)
    if message_id is not None:
        stmt = stmt.where(WorkProductFiduciaryGate.message_id == message_id)
    stmt = stmt.order_by(WorkProductFiduciaryGate.created_at, WorkProductFiduciaryGate.id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "message_id": str(g.message_id),
            "gate_status": g.gate_status,
            "pass_count": g.pass_count,
            "supported_count": g.supported_count,
            "fail_count": g.fail_count,
            "total_assertions": g.total_assertions,
            "confidence": g.confidence,
            "created_at": g.created_at.isoformat(),
        }
        for g in rows
    ]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_fiduciary_gate.py -v`
Expected: all PASS (every classification case, the upsert, `resolve_gates`, and the assembler-mislabel regression).

- [ ] **Step 6: Lint + type-check, then commit**

```bash
cd api && .venv/bin/ruff format app/citation/gate.py app/citation/ledger.py tests/integration/test_fiduciary_gate.py && .venv/bin/ruff check app/citation tests/integration/test_fiduciary_gate.py && .venv/bin/mypy app/citation/gate.py app/citation/ledger.py
```

```bash
git add api/app/citation/gate.py api/app/citation/ledger.py api/tests/integration/test_fiduciary_gate.py
git commit -s -m "feat(citation): deterministic fiduciary-grade gate computation (P1-B1)

compute_and_record_gate buckets a turn's ledger entries into
PASS/SUPPORTED/FAIL and upserts the verdict + per-tier counts +
aggregate confidence (ADR 0018 D3). Provenance entries excluded.
Fixes the assemble_ledger_entries mislabel so unverified KB citations
land as 'unverified' (were 'verified'), making FAIL honest. Pure DB.

Refs ADR 0018 D3.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Hook at the three finalize sites + wire `gates` into the `/ledger` endpoint

**Files:**
- Modify: `api/app/api/chats.py` (3 finalize hooks + endpoint `gates` key + import)
- Modify: `docs/api/backend-openapi.yaml` (add `gates` to the ledger 200 response)
- Test: `api/tests/integration/test_ledger_endpoint.py` (extend — gate appears in response) and `api/tests/integration/test_fiduciary_gate.py` (the hook is exercised end-to-end via an existing chat-send test if cheap, else a focused finalize test)

**Interfaces:**
- Consumes: `compute_and_record_gate`, `resolve_gates` (Task 2).
- Produces: the `/ledger` endpoint response gains a top-level `gates` key.

- [ ] **Step 1: Write the failing test**

Extend `api/tests/integration/test_ledger_endpoint.py` — in the existing `seeded` fixture the turn already has a `message_citations` row and assembled ledger entries; after `assemble_ledger_entries`, also call the gate, then assert the endpoint surfaces it. Add:

```python
from app.citation.gate import compute_and_record_gate  # add to imports


@pytest.mark.asyncio
async def test_ledger_includes_gate(client, db_session, seeded):
    user, chat, msg = seeded
    await compute_and_record_gate(db_session, message_id=msg.id)
    await db_session.flush()
    r = await client.get(f"/api/v1/chats/{chat.id}/ledger", headers=_auth(user))
    assert r.status_code == 200
    body = r.json()
    assert "gates" in body
    assert len(body["gates"]) == 1
    g = body["gates"][0]
    assert g["message_id"] == str(msg.id)
    # the seeded turn has one exact_match KB citation -> fiduciary_grade
    assert g["gate_status"] == "fiduciary_grade"
    assert g["pass_count"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_ledger_endpoint.py::test_ledger_includes_gate -v`
Expected: FAIL — `KeyError: 'gates'` / `assert "gates" in body`.

- [ ] **Step 3: Wire `gates` into the endpoint**

In `api/app/api/chats.py`, extend the gate import (add to the existing `app.citation.ledger` import line or a new line):

```python
from app.citation.gate import compute_and_record_gate, resolve_gates
```

In `get_chat_ledger`, change the return to include `gates`:

```python
    entries = await resolve_ledger_entries(db, chat_id=cid, message_id=mid)
    gates = await resolve_gates(db, chat_id=cid, message_id=mid)
    return {"chat_id": str(cid), "entries": entries, "gates": gates}
```

- [ ] **Step 4: Add the finalize hooks**

At **each** of the three sites where `assemble_ledger_entries(db, message_id=assistant_message_id)` is called (in `_send_message`'s non-streaming tool-loop path ~line 2927, the non-tool path ~line 3141, and the streaming path ~line 3504), add the gate call **immediately after** the assembler's `try/except`, in its own guard. Pattern (apply at all three, matching each site's existing indentation and the variable name used for the assistant message id at that site):

```python
                try:
                    await compute_and_record_gate(db, message_id=assistant_message_id)
                except Exception as gate_exc:  # never break the turn (conservative posture)
                    log.warning("fiduciary gate computation failed: %r", gate_exc)
```

> **Implementer note:** confirm the assistant-message-id variable name at each site (the assembler call shows it — reuse the same identifier). Do not change the assembler call; add the gate call as a sibling guard right after it.

- [ ] **Step 5: Update the OpenAPI sketch**

In `docs/api/backend-openapi.yaml`, in the `/api/v1/chats/{chat_id}/ledger` `200` response schema (added in P1-A3), add a `gates` property next to `entries`:

```yaml
                  gates:
                    type: array
                    description: Per-turn fiduciary-grade verdicts (ADR 0018 D3).
                    items:
                      type: object
                      properties:
                        message_id: {type: string, format: uuid}
                        gate_status: {type: string, enum: [fiduciary_grade, supported_only, flagged]}
                        pass_count: {type: integer}
                        supported_count: {type: integer}
                        fail_count: {type: integer}
                        total_assertions: {type: integer}
                        confidence: {type: number, nullable: true}
                        created_at: {type: string, format: date-time}
```

(No path-count change — the `/ledger` path already exists; this only extends its response body. `test_openapi.py` count stays 135.)

- [ ] **Step 6: Run the endpoint + gate tests**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_ledger_endpoint.py tests/integration/test_fiduciary_gate.py tests/test_openapi.py -v`
Expected: all PASS (the new `gates` assertion; count still 135).

- [ ] **Step 7: Full gate**

Run: `cd api && .venv/bin/ruff format app tests && .venv/bin/ruff check app tests && .venv/bin/mypy app && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest -q`
Expected: ruff + mypy clean; full suite green (no decrease).

- [ ] **Step 8: Commit**

```bash
git add api/app/api/chats.py docs/api/backend-openapi.yaml api/tests/integration/test_ledger_endpoint.py api/tests/integration/test_fiduciary_gate.py
git commit -s -m "feat(citation): hook fiduciary gate at finalize + surface in /ledger (P1-B1)

compute_and_record_gate runs at all three chat-finalize sites
(guarded, never breaks the turn); GET /chats/{id}/ledger now returns
a gates[] array of per-turn verdicts alongside entries (additive, the
A3 response object reserved for this). OpenAPI sketch extended.

Refs ADR 0018 D3/D4.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- D3 gate computation (PASS/SUPPORTED/FAIL, derivation, confidence-as-mean, zero-assertion case) → Task 2 `compute_and_record_gate` + tests. ✓
- New 1:1 metadata table + migration 0059 + P3 tripwire → Task 1. ✓
- Assembler mislabel fix (unverified KB → `"unverified"`) + regression test → Task 2. ✓
- Hook at 3 finalize sites, guarded → Task 3. ✓
- `gates` surfaced in the merged A3 `/ledger` response → Task 3 (`resolve_gates`). ✓
- No egress; flush-not-commit (P5) → Task 2 (`db.flush()` only). ✓
- Caselaw-FAIL persistence + paraphrase tier explicitly **out of scope** (B1b) → not in any task. ✓

**Placeholder scan:** Task 2 Step 1 gives one fully-worked FK-valid test (`test_all_pass_is_fiduciary_grade`) plus an `_seed_entry` helper and an enumerated list of the remaining tests with exact expected values (counts, statuses, confidence) — guided construction over a real helper, not a silent TODO. All other steps carry complete code. No "TBD"/"implement later". ✓

**Type consistency:** `compute_and_record_gate(db, *, message_id) -> WorkProductFiduciaryGate | None` and `resolve_gates(db, *, chat_id, message_id=None) -> list[dict]` are defined in Task 2 and consumed identically in Task 3. `WorkProductFiduciaryGate` columns defined in Task 1 match the model fields set in Task 2 and read in `resolve_gates`. Status strings (`exact_match`, `tolerant_match`, `paraphrase_judge`, `ensemble_strict`, `ensemble_majority`, `unverified`, `failed`, `provenance`) are consistent with the cascade's `method` values and the ledger assembler. ✓

**Note for executor:** the cascade's real method strings are `exact_match`, `tolerant_match`, `paraphrase_judge`, `ensemble_strict`, `ensemble_majority` (`api/app/citation/verification.py`). If any differ at implementation time, align the `*_STATUSES` frozensets to the actual values and say so — the gate is only honest if its buckets match what the cascade writes.
