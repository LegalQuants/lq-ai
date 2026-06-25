# P1-A2 — Citation Ledger entry table + assembly — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `citation_ledger_entry` table that unifies a turn's KB-document citations, caselaw citations, and tool-source provenance into one matter-and-turn-scoped record, and assemble it at chat finalize.

**Architecture:** A thin **referencing** table (ADR 0018 D1) with three nullable FKs (exactly one non-null per row) + a `source_kind` discriminator + mirrored verification status. A source-kind-agnostic assembler reads whatever citation/source rows exist for a message and writes one ledger entry per row, hooked (guarded) at every chat-finalize site. The entry holds no content (references only), so it joins the P3 no-raw-payload tripwire.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, pytest (host venv + throwaway `pgvector/pgvector:pg16`), ruff, mypy.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-24-p1a2-citation-ledger-entry-design.md`. Pins [ADR 0018](../../adr/0018-citation-ledger-and-fiduciary-grade-output.md) D1/D5/D6/D7.
- **Three nullable FKs + `source_kind`**, exactly-one-non-null CHECK; reserved `treatment_id` (nullable uuid, NO FK). No `tier` column (dropped — `message_tool_sources` can't populate it).
- **Metadata-only:** the ledger holds NO `source_text`/content — it references content by id. It MUST be added to `api/tests/test_transparency_invariants.py`'s `_AUDIT_MODELS` and that test MUST stay green.
- **Conservative posture:** a ledger-assembly failure logs and degrades to "no ledger this turn" — it must NEVER abort the assistant turn/stream. No new egress; pure DB.
- **Tests:** run via host venv against the throwaway pgvector (conftest auto-migrates); NEVER host `alembic upgrade`; never use port 15432. No `-m provider` (pure DB).
- **Migration discipline:** next revision is `0058`, `down_revision="0057"`.
- **Gates:** `ruff format`, `ruff check`, `mypy app` (standard mode), `pytest`. Coverage no-decrease.
- **Security review:** touches the citation/audit-adjacent surface → CODEOWNERS routes to security review.
- **Commits:** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Test DB env:** `cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest <args>`. If the throwaway container isn't running: `docker run -d --rm --name lqai-test-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=lqai_test -p 55432:5432 pgvector/pgvector:pg16`, then `docker exec lqai-test-pg psql -U postgres -d lqai_test -c "CREATE EXTENSION IF NOT EXISTS vector;"`.

## File Structure

- `api/app/models/citation_ledger_entry.py` — **new** ORM model `CitationLedgerEntry`.
- `api/alembic/versions/0058_citation_ledger_entry.py` — **new** migration.
- `api/app/models/__init__.py` — **modify**: register the model.
- `api/tests/test_transparency_invariants.py` — **modify**: add the model to `_AUDIT_MODELS`.
- `api/app/citation/ledger.py` — **new** module: `assemble_ledger_entries`.
- `api/app/api/chats.py` — **modify**: guarded assembler call at the three finalize branches.
- `api/tests/integration/test_citation_ledger.py` — **new** integration tests.
- `docs/db-schema.md` — **modify**: document the table.
- `docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md` — **modify**: D1 reconciliation note.

---

### Task 1: `citation_ledger_entry` model + migration + P3 tripwire

**Files:**
- Create: `api/app/models/citation_ledger_entry.py`
- Create: `api/alembic/versions/0058_citation_ledger_entry.py`
- Modify: `api/app/models/__init__.py`
- Modify: `api/tests/test_transparency_invariants.py`
- Test: `api/tests/integration/test_citation_ledger.py`

**Interfaces:**
- Produces: `CitationLedgerEntry` with columns `id, project_id, chat_id, message_id, source_kind, message_citation_id, message_caselaw_citation_id, message_tool_source_id, verification_status, confidence, provider, retrieved_at, treatment_id, created_at`.

- [ ] **Step 1: Write the failing test** — `api/tests/integration/test_citation_ledger.py`

```python
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.message_tool_source import MessageToolSource
from app.models.user import User

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_message(db_session):
    """Seed a user + chat + assistant message; yield the message id."""
    user = User(
        email=f"ledger-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role="member",
    )
    db_session.add(user)
    await db_session.flush()
    chat = Chat(user_id=user.id, title="ledger test")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="answer")
    db_session.add(msg)
    await db_session.flush()
    return msg.id


@pytest.mark.asyncio
async def test_ledger_entry_roundtrips(db_session, seeded_message):
    """A single-FK entry referencing a real tool-source row persists and reads back."""
    chat_id = (
        await db_session.execute(select(Message.chat_id).where(Message.id == seeded_message))
    ).scalar_one()
    source = MessageToolSource(
        message_id=seeded_message, source_kind="caselaw", label="Cluster 1",
        subtitle=None, url=None, external_ref="1", provider="courtlistener", tool="get_cluster",
    )
    db_session.add(source)
    await db_session.flush()
    entry = CitationLedgerEntry(
        chat_id=chat_id,
        message_id=seeded_message,
        source_kind="caselaw",
        message_tool_source_id=source.id,
        verification_status="provenance",
        provider="courtlistener",
    )
    db_session.add(entry)
    await db_session.flush()
    got = (
        await db_session.execute(
            select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == seeded_message)
        )
    ).scalar_one()
    assert got.message_tool_source_id == source.id
    assert got.message_citation_id is None
    assert got.verification_status == "provenance"
    assert got.treatment_id is None


@pytest.mark.asyncio
async def test_exactly_one_fk_check_rejects_zero_and_two(db_session, seeded_message):
    chat_id = (
        await db_session.execute(select(Message.chat_id).where(Message.id == seeded_message))
    ).scalar_one()
    # zero FKs -> CHECK violation
    db_session.add(
        CitationLedgerEntry(
            chat_id=chat_id, message_id=seeded_message,
            source_kind="kb_document", verification_status="exact_match",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
    # two FKs -> CHECK violation
    db_session.add(
        CitationLedgerEntry(
            chat_id=chat_id, message_id=seeded_message,
            source_kind="kb_document", verification_status="exact_match",
            message_citation_id=uuid.uuid4(), message_tool_source_id=uuid.uuid4(),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
```

> The first test is intentionally minimal (the model + a FK constraint); Task 2's tests exercise real referenced rows. If `Chat`/`Message`/`User` constructor kwargs differ on `main`, mirror the seeding in `api/tests/test_message_tool_sources.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_citation_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: app.models.citation_ledger_entry`.

- [ ] **Step 3: Create the model** — `api/app/models/citation_ledger_entry.py`

```python
"""citation_ledger_entry — the Citation Ledger (ADR 0018 D1).

One row per (assistant turn, source brought into context). A thin REFERENCING
record: it points at exactly one of message_citations / message_caselaw_citations
/ message_tool_sources by id (a CHECK enforces exactly-one-non-null) and mirrors
that source's verification status as a queryable label. It holds NO content
(source_text lives on the referenced row), so it is a metadata index and joins
the P3 no-raw-payload tripwire. ``treatment_id`` is reserved for the WS-G derived
treatment layer (ADR 0018 D6) and is always NULL in Phase 1.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CitationLedgerEntry(Base):
    __tablename__ = "citation_ledger_entry"
    __table_args__ = (
        CheckConstraint(
            "(message_citation_id IS NOT NULL)::int "
            "+ (message_caselaw_citation_id IS NOT NULL)::int "
            "+ (message_tool_source_id IS NOT NULL)::int = 1",
            name="chk_citation_ledger_entry_exactly_one_source",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="chk_citation_ledger_entry_confidence_range",
        ),
        Index("ix_citation_ledger_entry_chat_id", "chat_id"),
        Index("ix_citation_ledger_entry_message_id", "message_id"),
        Index("ix_citation_ledger_entry_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_citation_ledger_entry_project"),
        nullable=True,
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE", name="fk_citation_ledger_entry_chat"),
        nullable=False,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE", name="fk_citation_ledger_entry_message"),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    message_citation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "message_citations.id", ondelete="CASCADE", name="fk_citation_ledger_entry_msg_citation"
        ),
        nullable=True,
    )
    message_caselaw_citation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "message_caselaw_citations.id",
            ondelete="CASCADE",
            name="fk_citation_ledger_entry_caselaw_citation",
        ),
        nullable=True,
    )
    message_tool_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "message_tool_sources.id",
            ondelete="CASCADE",
            name="fk_citation_ledger_entry_tool_source",
        ),
        nullable=True,
    )
    verification_status: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    treatment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
```

> Verify the projects table name is `projects` before finalizing the `project_id` FK: `grep -n '__tablename__' api/app/models/project.py`. If it differs, use the actual name. (The model uses `projects.id`; adjust if needed.)

- [ ] **Step 4: Register the model** — add to `api/app/models/__init__.py`

```python
from app.models.citation_ledger_entry import CitationLedgerEntry
```

…and add `"CitationLedgerEntry"` to `__all__` if the module maintains one (follow the existing pattern/position).

- [ ] **Step 5: Create the migration** — `api/alembic/versions/0058_citation_ledger_entry.py`

```python
"""citation_ledger_entry — the Citation Ledger (ADR 0018 D1)

Revision ID: 0058
Revises: 0057
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "citation_ledger_entry",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE", name="fk_citation_ledger_entry_project"),
            nullable=True,
        ),
        sa.Column(
            "chat_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chats.id", ondelete="CASCADE", name="fk_citation_ledger_entry_chat"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE", name="fk_citation_ledger_entry_message"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column(
            "message_citation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "message_citations.id",
                ondelete="CASCADE",
                name="fk_citation_ledger_entry_msg_citation",
            ),
            nullable=True,
        ),
        sa.Column(
            "message_caselaw_citation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "message_caselaw_citations.id",
                ondelete="CASCADE",
                name="fk_citation_ledger_entry_caselaw_citation",
            ),
            nullable=True,
        ),
        sa.Column(
            "message_tool_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "message_tool_sources.id",
                ondelete="CASCADE",
                name="fk_citation_ledger_entry_tool_source",
            ),
            nullable=True,
        ),
        sa.Column("verification_status", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("treatment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(message_citation_id IS NOT NULL)::int "
            "+ (message_caselaw_citation_id IS NOT NULL)::int "
            "+ (message_tool_source_id IS NOT NULL)::int = 1",
            name="chk_citation_ledger_entry_exactly_one_source",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="chk_citation_ledger_entry_confidence_range",
        ),
    )
    op.create_index("ix_citation_ledger_entry_chat_id", "citation_ledger_entry", ["chat_id"])
    op.create_index("ix_citation_ledger_entry_message_id", "citation_ledger_entry", ["message_id"])
    op.create_index("ix_citation_ledger_entry_project_id", "citation_ledger_entry", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_citation_ledger_entry_project_id", table_name="citation_ledger_entry")
    op.drop_index("ix_citation_ledger_entry_message_id", table_name="citation_ledger_entry")
    op.drop_index("ix_citation_ledger_entry_chat_id", table_name="citation_ledger_entry")
    op.drop_table("citation_ledger_entry")
```

- [ ] **Step 6: Add the model to the P3 tripwire** — `api/tests/test_transparency_invariants.py`

Add the import next to the other audit-model imports (near lines 32–35):

```python
from app.models.citation_ledger_entry import CitationLedgerEntry
```

Add it to the `_AUDIT_MODELS` tuple (lines ~48–53):

```python
_AUDIT_MODELS: tuple[type, ...] = (
    ToolCallLog,
    AuditLog,
    ToolEgressLog,
    InferenceRoutingLog,
    CitationLedgerEntry,
)
```

> All ledger columns are metadata (`*_id`, `source_kind`, `verification_status`, `confidence`, `provider`, `retrieved_at`, `created_at`) — none is an exact denied term and none ends in a denied suffix (`message_citation_id` ends in `_id`, not `_message`), so the scan passes. This addition PROVES the ledger is metadata-only.

- [ ] **Step 7: Run tests + tripwire**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_citation_ledger.py tests/test_transparency_invariants.py -v`
Expected: PASS — round-trip + both CHECK-rejection tests + `test_audit_models_have_no_raw_payload_columns` green with the ledger included.

- [ ] **Step 8: Lint + type-check**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && .venv/bin/ruff format app/models/citation_ledger_entry.py alembic/versions/0058_citation_ledger_entry.py && .venv/bin/ruff check app/models/citation_ledger_entry.py alembic/versions/0058_citation_ledger_entry.py tests/test_transparency_invariants.py && .venv/bin/mypy app/models/citation_ledger_entry.py`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add api/app/models/citation_ledger_entry.py api/alembic/versions/0058_citation_ledger_entry.py api/app/models/__init__.py api/tests/test_transparency_invariants.py api/tests/integration/test_citation_ledger.py
git commit -s -m "feat(citation): citation_ledger_entry table + model + P3 tripwire (P1-A2)"
```

---

### Task 2: Ledger assembly

**Files:**
- Create: `api/app/citation/ledger.py`
- Test: `api/tests/integration/test_citation_ledger.py` (append)

**Interfaces:**
- Consumes: `CitationLedgerEntry`; `MessageCitation`, `MessageCaselawCitation`, `MessageToolSource`; `Chat`, `Message`.
- Produces: `async def assemble_ledger_entries(db, *, message_id) -> int` — self-derives `chat_id` (from the message) and `project_id` (from the chat); writes one ledger entry per citation/source row for the message; returns the count.

- [ ] **Step 1: Write the failing test** — append to `api/tests/integration/test_citation_ledger.py`

```python
from datetime import datetime, timezone

from app.citation.ledger import assemble_ledger_entries
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.message_tool_source import MessageToolSource
# MessageCitation lives in app.models.chat
from app.models.chat import MessageCitation


@pytest.mark.asyncio
async def test_assembles_one_entry_per_source_row(db_session, seeded_message):
    mid = seeded_message
    # A KB-document citation (verified) — needs a real source_file_id (files row).
    # Reuse the message_tool_sources + caselaw rows that DON'T need a file FK,
    # plus a caselaw citation, to exercise all three source kinds without a file.
    db_session.add(
        MessageCaselawCitation(
            message_id=mid, opinion_id=11, cluster_id=22,
            source_offset_start=0, source_offset_end=5, source_text="hello",
            verified=True, verification_method="exact_match", verification_confidence=1.0,
        )
    )
    db_session.add(
        MessageToolSource(
            message_id=mid, source_kind="caselaw", label="Cluster 22",
            subtitle=None, url=None, external_ref="22", provider="courtlistener", tool="get_cluster",
        )
    )
    await db_session.flush()

    n = await assemble_ledger_entries(db_session, message_id=mid)
    await db_session.flush()

    entries = (
        await db_session.execute(
            select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == mid)
        )
    ).scalars().all()
    assert n == 2
    kinds = {e.source_kind for e in entries}
    assert kinds == {"caselaw"}  # one from the caselaw citation, one from the tool source
    by_fk = {
        "caselaw_citation": [e for e in entries if e.message_caselaw_citation_id is not None],
        "tool_source": [e for e in entries if e.message_tool_source_id is not None],
    }
    assert len(by_fk["caselaw_citation"]) == 1
    assert by_fk["caselaw_citation"][0].verification_status == "exact_match"
    assert by_fk["caselaw_citation"][0].confidence == 1.0
    assert by_fk["caselaw_citation"][0].provider == "courtlistener"
    assert len(by_fk["tool_source"]) == 1
    assert by_fk["tool_source"][0].verification_status == "provenance"
    assert by_fk["tool_source"][0].confidence is None
    assert by_fk["tool_source"][0].provider == "courtlistener"
    assert by_fk["tool_source"][0].retrieved_at is not None


@pytest.mark.asyncio
async def test_no_sources_yields_no_entries(db_session, seeded_message):
    n = await assemble_ledger_entries(db_session, message_id=seeded_message)
    assert n == 0
```

> The KB-document path (`MessageCitation`, which needs a real `source_file_id` → `files`) is covered indirectly by the `kb_document` mapping in the implementation; seeding a full `files`+`documents` chain is heavy, so these tests exercise the caselaw + tool-source kinds. The kb_document mapping is asserted by reading code in review; if a fuller fixture exists for files, add a kb_document case.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_citation_ledger.py -k assembles -v`
Expected: FAIL — `ModuleNotFoundError: app.citation.ledger`.

- [ ] **Step 3: Implement the assembler** — `api/app/citation/ledger.py`

```python
"""Citation Ledger assembly (ADR 0018 D1).

Reads the three per-turn citation/source artifacts for an assistant message and
writes one ``CitationLedgerEntry`` per row — a thin referencing index. Source-kind
agnostic over ``message_tool_sources`` (so generic-MCP rows flow in once DE-350
lands). Holds no content; references by id.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, Message, MessageCitation
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.message_tool_source import MessageToolSource


async def assemble_ledger_entries(db: AsyncSession, *, message_id: uuid.UUID) -> int:
    """Write one ledger entry per citation/source row for ``message_id``.

    Self-derives ``chat_id`` (from the message) and ``project_id`` (from the chat).
    Returns the number of entries written. Pure DB; no egress.
    """
    chat_id = (
        await db.execute(select(Message.chat_id).where(Message.id == message_id))
    ).scalar_one_or_none()
    if chat_id is None:
        return 0
    project_id = (
        await db.execute(select(Chat.project_id).where(Chat.id == chat_id))
    ).scalar_one_or_none()

    entries: list[CitationLedgerEntry] = []

    doc_citations = (
        (await db.execute(select(MessageCitation).where(MessageCitation.message_id == message_id)))
        .scalars()
        .all()
    )
    for c in doc_citations:
        entries.append(
            CitationLedgerEntry(
                project_id=project_id,
                chat_id=chat_id,
                message_id=message_id,
                source_kind="kb_document",
                message_citation_id=c.id,
                verification_status=c.verification_method or "verified",
                confidence=float(c.verification_confidence)
                if c.verification_confidence is not None
                else None,
                provider=None,
                retrieved_at=None,
            )
        )

    caselaw_citations = (
        (
            await db.execute(
                select(MessageCaselawCitation).where(MessageCaselawCitation.message_id == message_id)
            )
        )
        .scalars()
        .all()
    )
    for cc in caselaw_citations:
        entries.append(
            CitationLedgerEntry(
                project_id=project_id,
                chat_id=chat_id,
                message_id=message_id,
                source_kind="caselaw",
                message_caselaw_citation_id=cc.id,
                verification_status=cc.verification_method or "verified",
                confidence=cc.verification_confidence,
                provider="courtlistener",
                retrieved_at=cc.created_at,
            )
        )

    tool_sources = (
        (
            await db.execute(
                select(MessageToolSource).where(MessageToolSource.message_id == message_id)
            )
        )
        .scalars()
        .all()
    )
    for ts in tool_sources:
        entries.append(
            CitationLedgerEntry(
                project_id=project_id,
                chat_id=chat_id,
                message_id=message_id,
                source_kind=ts.source_kind,
                message_tool_source_id=ts.id,
                verification_status="provenance",
                confidence=None,
                provider=ts.provider,
                retrieved_at=ts.created_at,
            )
        )

    if entries:
        db.add_all(entries)
        await db.flush()
    return len(entries)
```

> Confirm `MessageCitation` is importable from `app.models.chat` (it is defined there). If `app.models.__init__` re-exports it, importing from `app.models` is also fine — match the codebase's prevailing import style.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_citation_ledger.py -v`
Expected: PASS (all).

- [ ] **Step 5: Lint + type-check**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && .venv/bin/ruff format app/citation/ledger.py && .venv/bin/ruff check app/citation/ledger.py && .venv/bin/mypy app/citation/ledger.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add api/app/citation/ledger.py api/tests/integration/test_citation_ledger.py
git commit -s -m "feat(citation): citation ledger assembly (P1-A2)"
```

---

### Task 3: Wire the assembler into chat finalize

**Files:**
- Modify: `api/app/api/chats.py`

**Interfaces:**
- Consumes: `assemble_ledger_entries` (Task 2).

- [ ] **Step 1: Add the import** — near the other citation imports at the top of `api/app/api/chats.py` (next to `from app.citation.caselaw import verify_and_persist_caselaw_citations`)

```python
from app.citation.ledger import assemble_ledger_entries
```

- [ ] **Step 2: Wire the three finalize branches**

Find the finalize sites: `grep -n "verify_and_persist_caselaw_citations\|_persist_message_tool_sources(db, message_id=assistant_message_id, records=\[\])" api/app/api/chats.py`. There are three branches that persist a turn's citations/sources:
- **Two tool-loop branches** — each ends with `await verify_and_persist_caselaw_citations(...)` (the non-streaming `_non_streaming_response` site ~2879 and the streaming `_stream_response` site ~3446).
- **One single-shot branch** — ends with `await _persist_message_tool_sources(db, message_id=assistant_message_id, records=[])` (~3096).

After the LAST persist call in EACH of the three branches, add a guarded assembler call (use the file's existing `log` logger):

```python
            try:
                await assemble_ledger_entries(db, message_id=assistant_message_id)
            except Exception as ledger_exc:  # never block the turn
                log.warning("citation ledger assembly failed: %r", ledger_exc)
```

Match the indentation of the surrounding `await _persist_*` calls at each site. Place the caselaw call (where present) BEFORE the ledger call, so all source rows exist when the ledger assembles.

- [ ] **Step 3: Run the chat-path regression + ledger tests**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_chat_tool_loop_send.py tests/integration/test_chat_tool_call_resume.py tests/integration/test_citation_ledger.py -q`
Expected: PASS, no regressions.

- [ ] **Step 4: Lint + type-check**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && .venv/bin/ruff format app/api/chats.py && .venv/bin/ruff check app/api/chats.py && .venv/bin/mypy app/api/chats.py`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add api/app/api/chats.py
git commit -s -m "feat(citation): assemble the ledger at chat finalize (P1-A2)"
```

---

### Task 4: Docs + ADR reconciliation + full gate

**Files:**
- Modify: `docs/db-schema.md`
- Modify: `docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md`

- [ ] **Step 1: Document the table** — add a `citation_ledger_entry` section to `docs/db-schema.md`

Place it next to `message_citations` / `message_caselaw_citations` / `message_tool_sources`. Read `api/app/models/citation_ledger_entry.py` for the exact columns. Document: every column (type, nullability), the four FKs (`project_id`→projects, `chat_id`→chats, `message_id`→messages, and the three nullable source FKs, all ON DELETE CASCADE), both CHECK constraints (names + conditions), and the three indexes. Purpose line: "the Citation Ledger (ADR 0018 D1) — one thin referencing row per (turn, source), unifying KB-document citations, caselaw citations, and tool-source provenance; metadata-only (no content), in the P3 tripwire."

- [ ] **Step 2: Reconcile ADR 0018 D1** — append a short note under decision D1 in `docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md`

Add (immediately after the D1 table or its trailing paragraph):

```markdown
> **Reconciliation (P1-A2, 2026-06-24):** as built, the ledger references the three concrete per-turn artifacts via three nullable FKs — `message_citation_id`, `message_caselaw_citation_id`, `message_tool_source_id` (exactly one non-null). The earlier `citable_source_id` slot is realized as `message_caselaw_citation_id` (P1-A1 reused research-opinion storage + a caselaw-citation table rather than creating a standalone `citable_source`). The sketched `tier` column is deferred — `message_tool_sources` carries no tier to populate.
```

- [ ] **Step 3: Run the full gate**

Run: `cd /Users/kevinkeller/Code/lq-ai/api && .venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy app && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest -q`
Expected: all green (no `-m provider`). If a failure traces to this branch, fix it; if pre-existing/unrelated, report it clearly.

- [ ] **Step 4: Commit**

```bash
git add docs/db-schema.md docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md
git commit -s -m "docs: document citation_ledger_entry + reconcile ADR 0018 D1 (P1-A2)"
```

---

## Self-Review

**Spec coverage:**
- Component 1 (table, migration 0058, exactly-one-FK CHECK, reserved treatment_id, no tier) → Task 1. ✓
- Component 2 (source-kind-agnostic assembly, self-derived scope, per-row mapping) → Task 2. ✓
- Component 3 (guarded hook at every finalize site incl. single-shot) → Task 3. ✓
- Component 4 (P3 tripwire addition) → Task 1 Step 6. ✓
- Error handling (guarded, never breaks turn; no egress) → Task 3 guard + Task 2 pure-DB. ✓
- Testing (integration incl. CHECK rejections + per-source mapping; tripwire green) → Tasks 1–2. ✓
- Docs + ADR D1 reconciliation → Task 4. ✓
- Acceptance criteria 1–4 → Tasks 1–3 tests + Task 4 gate. ✓

**Placeholder scan:** none — every code step is complete; commands carry expected output. Line numbers for the chats.py sites are approximate and identified by adjacent call expressions (grep), not literals.

**Type consistency:** `assemble_ledger_entries(db, *, message_id) -> int` is consistent across Tasks 2–3. `verification_status` values are the citation's `verification_method` (`exact_match`/`tolerant_match`/…) or `provenance`. `confidence` is `float | None` (Decimal coerced via `float()` for KB doc; already float for caselaw; None for provenance). `CitationLedgerEntry` column names match between model (Task 1), migration (Task 1), assembler (Task 2), and tripwire (Task 1).
