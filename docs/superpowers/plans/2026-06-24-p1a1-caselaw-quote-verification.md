# P1-A1 — External caselaw quote-verification core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Character-verify the model's verbatim caselaw quotes against the opinion text already stored by the research service, and persist the verified results in a new `message_caselaw_citations` table.

**Architecture:** At chat finalize, derive the consulted CourtListener clusters from `LoopFinal.tool_sources`, load each consulted cluster's already-stored opinion plaintext, extract blockquote passages from the assistant answer, locate each verbatim in an opinion, run the **existing** citation cascade (`verify`, stages 1–2, `gateway=None` → deterministic, no LLM), and persist the verified rows. No new content store, no tool-loop or gateway change.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, pytest (host venv + throwaway `pgvector/pgvector:pg16`), ruff, mypy.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-24-p1a1-external-caselaw-quote-verification-design.md`. Pins: [ADR 0018](../../adr/0018-citation-ledger-and-fiduciary-grade-output.md) D2/D3.
- **Scope:** deterministic stages 1–2 only (`exact_match`/`tolerant_match`); **no gateway/LLM call** in this slice. Paraphrase judge = P1-B1/DE-280, out of scope.
- **Conservative posture:** never persist a row with `verified=true` without a passing cascade result; failures degrade to "no verified caselaw citations" and must not break the turn.
- **Transparency invariants (ADR 0016):** no new egress (reads already-stored text); the new table is a citation/content table (carries `source_text`), NOT an audit log — do **not** add it to the `test_transparency_invariants.py` audit-model scan.
- **Tests:** run via host venv against a throwaway pgvector (conftest auto-migrates); **never** host `alembic upgrade` against the dev DB. No `-m provider` needed (deterministic).
- **Gates (run all, locally):** `ruff format`, `ruff check`, `mypy` (api standard mode), `pytest`.
- **Security review:** this branch touches the citation surface → CODEOWNERS routes it to security review. No new egress path.
- **Migration discipline:** next revision is `0057`, `down_revision="0056"`. After it lands, rebuild `api` + `arq-worker` + `ingest-worker` together (do not apply host alembic to the dev stack).
- **Commits:** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## File Structure

- `api/app/models/message_caselaw_citation.py` — **new** ORM model `MessageCaselawCitation`.
- `api/alembic/versions/0057_message_caselaw_citations.py` — **new** migration.
- `api/app/models/__init__.py` — **modify**: register the new model.
- `api/app/citation/caselaw.py` — **new** module: blockquote extraction, opinion verification target, locator, candidate, and the verify-and-persist orchestrator.
- `api/app/api/chats.py` — **modify**: call the orchestrator at the two tool-loop finalize sites.
- `api/tests/citation/test_caselaw_extraction.py` — **new** unit tests (pure helpers).
- `api/tests/citation/test_caselaw_verify.py` — **new** unit tests (target/locator/verify).
- `api/tests/integration/test_caselaw_citations.py` — **new** integration test (DB + orchestrator).
- `docs/db-schema.md` — **modify**: document the new table.

---

### Task 1: `message_caselaw_citations` model + migration

**Files:**
- Create: `api/app/models/message_caselaw_citation.py`
- Create: `api/alembic/versions/0057_message_caselaw_citations.py`
- Modify: `api/app/models/__init__.py`
- Test: `api/tests/integration/test_caselaw_citations.py`

**Interfaces:**
- Produces: `MessageCaselawCitation` ORM model with columns `id, message_id, opinion_id, cluster_id, source_offset_start, source_offset_end, source_text, verified, verification_method, verification_confidence, partial, created_at`.

- [ ] **Step 1: Write the failing test** — `api/tests/integration/test_caselaw_citations.py`

```python
import uuid

import pytest
from sqlalchemy import select

from app.models.message_caselaw_citation import MessageCaselawCitation


@pytest.mark.asyncio
async def test_caselaw_citation_row_roundtrips(db_session, seeded_chat_message):
    """A verified caselaw-citation row persists and reads back."""
    message_id = seeded_chat_message  # fixture: an existing messages.id (assistant)
    row = MessageCaselawCitation(
        message_id=message_id,
        opinion_id=12345,
        cluster_id=999,
        source_offset_start=10,
        source_offset_end=42,
        source_text="the implied covenant of good faith",
        verified=True,
        verification_method="exact_match",
        verification_confidence=1.0,
        partial=False,
    )
    db_session.add(row)
    await db_session.flush()

    got = (
        await db_session.execute(
            select(MessageCaselawCitation).where(MessageCaselawCitation.message_id == message_id)
        )
    ).scalar_one()
    assert got.opinion_id == 12345
    assert got.verified is True
    assert got.verification_method == "exact_match"
    assert got.id is not None
```

> Use the integration conftest's `db_session` fixture (real Postgres, auto-migrated) and an existing assistant-message fixture. If no `seeded_chat_message` fixture exists, create one in this test file that inserts a user + chat + assistant `Message` and yields the message id (follow the pattern in `api/tests/integration/test_tool_call_confirmation.py`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/integration/test_caselaw_citations.py::test_caselaw_citation_row_roundtrips -v`
Expected: FAIL — `ModuleNotFoundError: app.models.message_caselaw_citation` (model not created yet).

- [ ] **Step 3: Create the model** — `api/app/models/message_caselaw_citation.py`

```python
"""message_caselaw_citations — quote-verified citations against external opinions.

One row per verbatim passage in an assistant turn that was character-verified
against a CourtListener opinion the turn consulted. Parallels ``message_citations``
(KB-document quote verification) but keys to ``opinion_id``/``cluster_id`` and
offsets into the opinion plaintext stored by the research service, with no
``file_id`` (external sources are not uploaded ``files``). P1-A1 / ADR 0018 D2.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class MessageCaselawCitation(Base):
    __tablename__ = "message_caselaw_citations"
    __table_args__ = (
        CheckConstraint(
            "source_offset_start >= 0",
            name="chk_message_caselaw_citations_offset_start_nonneg",
        ),
        CheckConstraint(
            "source_offset_end > source_offset_start",
            name="chk_message_caselaw_citations_offset_end_gt_start",
        ),
        CheckConstraint(
            "verification_method IS NULL OR verification_method IN "
            "('exact_match', 'tolerant_match')",
            name="chk_message_caselaw_citations_method_values",
        ),
        CheckConstraint(
            "verification_confidence IS NULL OR "
            "(verification_confidence >= 0 AND verification_confidence <= 1)",
            name="chk_message_caselaw_citations_confidence_range",
        ),
        CheckConstraint(
            "(verified = false) OR (verification_method IS NOT NULL)",
            name="chk_message_caselaw_citations_verified_has_method",
        ),
        Index("ix_message_caselaw_citations_message_id", "message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE", name="fk_message_caselaw_citations_message"),
        nullable=False,
    )
    opinion_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cluster_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_offset_start: Mapped[int] = mapped_column(Integer, nullable=False)
    source_offset_end: Mapped[int] = mapped_column(Integer, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    verification_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    partial: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
```

- [ ] **Step 4: Register the model** — add to `api/app/models/__init__.py`

Add an import line next to the other model imports (follow the existing alphabetical/grouped pattern), e.g.:

```python
from app.models.message_caselaw_citation import MessageCaselawCitation
```

…and add `"MessageCaselawCitation"` to the module's `__all__` if it maintains one.

- [ ] **Step 5: Create the migration** — `api/alembic/versions/0057_message_caselaw_citations.py`

```python
"""message_caselaw_citations — quote-verified citations against external opinions

Revision ID: 0057
Revises: 0056
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_caselaw_citations",
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
                "messages.id", ondelete="CASCADE", name="fk_message_caselaw_citations_message"
            ),
            nullable=False,
        ),
        sa.Column("opinion_id", sa.BigInteger(), nullable=False),
        sa.Column("cluster_id", sa.BigInteger(), nullable=False),
        sa.Column("source_offset_start", sa.Integer(), nullable=False),
        sa.Column("source_offset_end", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("verification_method", sa.Text(), nullable=True),
        sa.Column("verification_confidence", sa.Float(), nullable=True),
        sa.Column("partial", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_offset_start >= 0",
            name="chk_message_caselaw_citations_offset_start_nonneg",
        ),
        sa.CheckConstraint(
            "source_offset_end > source_offset_start",
            name="chk_message_caselaw_citations_offset_end_gt_start",
        ),
        sa.CheckConstraint(
            "verification_method IS NULL OR verification_method IN "
            "('exact_match', 'tolerant_match')",
            name="chk_message_caselaw_citations_method_values",
        ),
        sa.CheckConstraint(
            "verification_confidence IS NULL OR "
            "(verification_confidence >= 0 AND verification_confidence <= 1)",
            name="chk_message_caselaw_citations_confidence_range",
        ),
        sa.CheckConstraint(
            "(verified = false) OR (verification_method IS NOT NULL)",
            name="chk_message_caselaw_citations_verified_has_method",
        ),
    )
    op.create_index(
        "ix_message_caselaw_citations_message_id",
        "message_caselaw_citations",
        ["message_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_message_caselaw_citations_message_id", table_name="message_caselaw_citations"
    )
    op.drop_table("message_caselaw_citations")
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd api && pytest tests/integration/test_caselaw_citations.py::test_caselaw_citation_row_roundtrips -v`
Expected: PASS (conftest auto-migrates the throwaway pgvector, applying 0057).

- [ ] **Step 7: Lint + type-check the new files**

Run: `cd api && ruff format app/models/message_caselaw_citation.py alembic/versions/0057_message_caselaw_citations.py && ruff check app/models/message_caselaw_citation.py && mypy app/models/message_caselaw_citation.py`
Expected: all clean.

- [ ] **Step 8: Commit**

```bash
git add api/app/models/message_caselaw_citation.py api/alembic/versions/0057_message_caselaw_citations.py api/app/models/__init__.py api/tests/integration/test_caselaw_citations.py
git commit -s -m "feat(citation): message_caselaw_citations table + model (P1-A1)"
```

---

### Task 2: Blockquote passage extraction (pure)

**Files:**
- Create: `api/app/citation/caselaw.py`
- Test: `api/tests/citation/test_caselaw_extraction.py`

**Interfaces:**
- Produces: `extract_blockquote_passages(answer_text: str) -> list[str]` — the de-prefixed, stripped text of each markdown blockquote (consecutive `>` lines joined with a space), in document order, skipping empty results.

- [ ] **Step 1: Write the failing test** — `api/tests/citation/test_caselaw_extraction.py`

```python
from app.citation.caselaw import extract_blockquote_passages


def test_extracts_single_blockquote():
    answer = (
        "**Relevant passage:**\n"
        "> The implied covenant of good faith and fair dealing.\n"
        "\nHow this bears on the question: ...\n"
    )
    assert extract_blockquote_passages(answer) == [
        "The implied covenant of good faith and fair dealing."
    ]


def test_joins_consecutive_blockquote_lines():
    answer = "> first line\n> second line\n"
    assert extract_blockquote_passages(answer) == ["first line second line"]


def test_multiple_separate_blockquotes():
    answer = "> alpha\n\nsome prose\n\n> beta\n"
    assert extract_blockquote_passages(answer) == ["alpha", "beta"]


def test_no_blockquotes_returns_empty():
    assert extract_blockquote_passages("just prose, no quotes") == []


def test_strips_marker_and_extra_spaces():
    answer = ">   padded passage   \n"
    assert extract_blockquote_passages(answer) == ["padded passage"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/citation/test_caselaw_extraction.py -v`
Expected: FAIL — `ModuleNotFoundError: app.citation.caselaw`.

- [ ] **Step 3: Implement extraction** — `api/app/citation/caselaw.py`

```python
"""Caselaw quote verification (P1-A1).

Extracts blockquote passages from an assistant answer, locates each verbatim in
a consulted CourtListener opinion's stored plaintext, runs the existing citation
cascade (deterministic stages 1-2), and persists verified rows.
See docs/superpowers/specs/2026-06-24-p1a1-external-caselaw-quote-verification-design.md.
"""

from __future__ import annotations


def extract_blockquote_passages(answer_text: str) -> list[str]:
    """Return the text of each markdown blockquote in ``answer_text``.

    The case-law-research skill renders each cited passage as a markdown
    blockquote (``> ...``) under a "Relevant passage:" header. Consecutive
    blockquote lines are one passage (wrapped quote); a non-blockquote line
    ends the current passage.
    """
    passages: list[str] = []
    current: list[str] = []
    for line in answer_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(">"):
            current.append(stripped[1:].strip())
        elif current:
            joined = " ".join(p for p in current if p).strip()
            if joined:
                passages.append(joined)
            current = []
    if current:
        joined = " ".join(p for p in current if p).strip()
        if joined:
            passages.append(joined)
    return passages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && pytest tests/citation/test_caselaw_extraction.py -v`
Expected: PASS (all 5).

- [ ] **Step 5: Commit**

```bash
git add api/app/citation/caselaw.py api/tests/citation/test_caselaw_extraction.py
git commit -s -m "feat(citation): blockquote passage extraction for caselaw (P1-A1)"
```

---

### Task 3: Opinion verification target, locator, and candidate (pure)

**Files:**
- Modify: `api/app/citation/caselaw.py`
- Test: `api/tests/citation/test_caselaw_verify.py`

**Interfaces:**
- Consumes: `verify` and `VerificationResult` from `app.citation.verification`.
- Produces:
  - `_OpinionVerificationTarget` dataclass — `{id: uuid.UUID, normalized_content: str, was_ocrd: bool}` (satisfies the verifier's `_DocumentProtocol`).
  - `_CaselawCandidate` dataclass — `{source_offset_start: int, source_offset_end: int, source_text: str, source_document_id: uuid.UUID}` (satisfies `_CandidateProtocol`).
  - `opinion_target(opinion_id: int, text: str) -> _OpinionVerificationTarget`.
  - `locate_passage(passage: str, opinion_text: str) -> tuple[int, int] | None` — exact-substring offsets, or None.

- [ ] **Step 1: Write the failing test** — `api/tests/citation/test_caselaw_verify.py`

```python
import pytest

from app.citation.caselaw import (
    _CaselawCandidate,
    locate_passage,
    opinion_target,
)
from app.citation.verification import verify

OPINION = "Before the quote. The implied covenant of good faith applies here. After."


def test_locate_passage_found():
    loc = locate_passage("The implied covenant of good faith applies here.", OPINION)
    assert loc is not None
    start, end = loc
    assert OPINION[start:end] == "The implied covenant of good faith applies here."


def test_locate_passage_absent_returns_none():
    assert locate_passage("a sentence that is not in the opinion", OPINION) is None


@pytest.mark.asyncio
async def test_verify_exact_match_against_opinion():
    passage = "The implied covenant of good faith applies here."
    start, end = locate_passage(passage, OPINION)
    target = opinion_target(opinion_id=777, text=OPINION)
    candidate = _CaselawCandidate(
        source_offset_start=start,
        source_offset_end=end,
        source_text=passage,
        source_document_id=target.id,
    )
    result = await verify(candidate, target, gateway=None)
    assert result.verified is True
    assert result.method == "exact_match"


@pytest.mark.asyncio
async def test_invented_quote_not_verified():
    target = opinion_target(opinion_id=777, text=OPINION)
    candidate = _CaselawCandidate(
        source_offset_start=0,
        source_offset_end=5,
        source_text="WRONG",  # opinion[0:5] == "Befor", not "WRONG"
        source_document_id=target.id,
    )
    result = await verify(candidate, target, gateway=None)
    assert result.verified is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/citation/test_caselaw_verify.py -v`
Expected: FAIL — `ImportError: cannot import name '_CaselawCandidate'`.

- [ ] **Step 3: Implement the target, candidate, and locator** — append to `api/app/citation/caselaw.py`

```python
import uuid
from dataclasses import dataclass

# Stable namespace so a given opinion_id maps to a deterministic synthetic id.
_OPINION_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")


@dataclass(slots=True)
class _OpinionVerificationTarget:
    """Adapts a stored opinion to the verifier's document protocol (no DB row)."""

    id: uuid.UUID
    normalized_content: str
    was_ocrd: bool = False


@dataclass(slots=True)
class _CaselawCandidate:
    """A located quote span, shaped for the verifier's candidate protocol."""

    source_offset_start: int
    source_offset_end: int
    source_text: str
    source_document_id: uuid.UUID


def opinion_target(opinion_id: int, text: str) -> _OpinionVerificationTarget:
    return _OpinionVerificationTarget(
        id=uuid.uuid5(_OPINION_NS, str(opinion_id)),
        normalized_content=text,
        was_ocrd=False,
    )


def locate_passage(passage: str, opinion_text: str) -> tuple[int, int] | None:
    """Exact-substring offsets of ``passage`` in ``opinion_text``, or None.

    v1 locates verbatim spans only; the cascade confirms them as ``exact_match``.
    A whitespace-tolerant locator (feeding stage-2) is a noted follow-on.
    """
    needle = passage.strip()
    if not needle:
        return None
    idx = opinion_text.find(needle)
    if idx < 0:
        return None
    return idx, idx + len(needle)
```

> Move the `import uuid` / `from dataclasses import dataclass` lines to the top of the module with the other imports when you add them (ruff will flag otherwise).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && pytest tests/citation/test_caselaw_verify.py -v`
Expected: PASS (all 4).

- [ ] **Step 5: Lint + type-check**

Run: `cd api && ruff format app/citation/caselaw.py && ruff check app/citation/caselaw.py && mypy app/citation/caselaw.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add api/app/citation/caselaw.py api/tests/citation/test_caselaw_verify.py
git commit -s -m "feat(citation): opinion verify target + exact-substring locator (P1-A1)"
```

---

### Task 4: Verify-and-persist orchestrator + chat finalize wiring

**Files:**
- Modify: `api/app/citation/caselaw.py`
- Modify: `api/app/api/chats.py`
- Test: `api/tests/integration/test_caselaw_citations.py`

**Interfaces:**
- Consumes: `ToolSourceRecord` (`app.chat.tool_loop`), `ResearchOpinionMetadata` (`app.models.research`), `read_opinion` (`app.research.service`), `MessageCaselawCitation` (Task 1), the Task 2/3 helpers, `verify`.
- Produces: `async def verify_and_persist_caselaw_citations(db, *, message_id, assistant_text, tool_sources, load_opinion_text=...) -> int` — returns the number of verified rows persisted. `load_opinion_text` is an injectable `async (db, opinion_id) -> str` defaulting to the research-service reader (keeps the orchestrator unit-testable without object storage).

- [ ] **Step 1: Write the failing integration test** — append to `api/tests/integration/test_caselaw_citations.py`

```python
from app.chat.tool_loop import ToolSourceRecord
from app.citation.caselaw import verify_and_persist_caselaw_citations
from app.models.research import ResearchOpinionMetadata

_OPINION_TEXT = "Intro. The covenant of good faith is implied in every contract. End."


def _caselaw_source(cluster_id: int) -> ToolSourceRecord:
    return ToolSourceRecord(
        source_kind="caselaw",
        label=f"Cluster {cluster_id}",
        subtitle=None,
        url=None,
        external_ref=str(cluster_id),
        provider="courtlistener",
        tool="get_cluster",
    )


@pytest.mark.asyncio
async def test_verbatim_quote_persists_verified_row(db_session, seeded_chat_message):
    message_id = seeded_chat_message
    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=501, cluster_id=42, text_field_used="plain_text",
            storage_path="courtlistener/opinions/by-cluster/42/501", char_length=len(_OPINION_TEXT),
        )
    )
    await db_session.flush()

    async def fake_loader(db, opinion_id):
        return _OPINION_TEXT

    answer = "**Relevant passage:**\n> The covenant of good faith is implied in every contract.\n"
    n = await verify_and_persist_caselaw_citations(
        db_session, message_id=message_id, assistant_text=answer,
        tool_sources=[_caselaw_source(42)], load_opinion_text=fake_loader,
    )
    await db_session.flush()
    rows = (
        await db_session.execute(
            select(MessageCaselawCitation).where(MessageCaselawCitation.message_id == message_id)
        )
    ).scalars().all()
    assert n == 1
    assert len(rows) == 1
    assert rows[0].verified is True
    assert rows[0].verification_method == "exact_match"
    assert rows[0].opinion_id == 501


@pytest.mark.asyncio
async def test_invented_quote_persists_nothing(db_session, seeded_chat_message):
    message_id = seeded_chat_message
    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=502, cluster_id=43, text_field_used="plain_text",
            storage_path="p", char_length=len(_OPINION_TEXT),
        )
    )
    await db_session.flush()

    async def fake_loader(db, opinion_id):
        return _OPINION_TEXT

    answer = "> The court invented a rule that appears in no opinion whatsoever.\n"
    n = await verify_and_persist_caselaw_citations(
        db_session, message_id=message_id, assistant_text=answer,
        tool_sources=[_caselaw_source(43)], load_opinion_text=fake_loader,
    )
    assert n == 0


@pytest.mark.asyncio
async def test_storage_miss_is_skipped_not_fatal(db_session, seeded_chat_message):
    message_id = seeded_chat_message
    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=503, cluster_id=44, text_field_used=None, storage_path="gone", char_length=1
        )
    )
    await db_session.flush()

    async def boom_loader(db, opinion_id):
        raise RuntimeError("object storage unavailable")

    answer = "> The covenant of good faith is implied in every contract.\n"
    n = await verify_and_persist_caselaw_citations(
        db_session, message_id=message_id, assistant_text=answer,
        tool_sources=[_caselaw_source(44)], load_opinion_text=boom_loader,
    )
    assert n == 0  # skipped, no exception
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/integration/test_caselaw_citations.py -k "verbatim or invented or storage_miss" -v`
Expected: FAIL — `ImportError: cannot import name 'verify_and_persist_caselaw_citations'`.

- [ ] **Step 3: Implement the orchestrator** — append to `api/app/citation/caselaw.py`

```python
import logging
from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tool_loop import ToolSourceRecord
from app.citation.verification import verify
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.research import ResearchOpinionMetadata
from app.research.service import read_opinion

log = logging.getLogger(__name__)

_LoadOpinionText = Callable[[AsyncSession, int], Awaitable[str]]


async def _default_load_opinion_text(db: AsyncSession, opinion_id: int) -> str:
    return (await read_opinion(db, opinion_id=opinion_id))["text"]


async def verify_and_persist_caselaw_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    assistant_text: str,
    tool_sources: Sequence[ToolSourceRecord],
    load_opinion_text: _LoadOpinionText = _default_load_opinion_text,
) -> int:
    """Verify verbatim caselaw quotes in ``assistant_text`` and persist verified rows.

    Deterministic stages 1-2 only (``gateway=None``). Returns the row count.
    Never raises on a per-opinion failure (conservative posture): a load miss is
    logged and skipped, and the turn proceeds with whatever verified.
    """
    cluster_ids = {
        int(r.external_ref)
        for r in tool_sources
        if r.source_kind == "caselaw" and r.external_ref and r.external_ref.isdigit()
    }
    if not cluster_ids:
        return 0
    passages = extract_blockquote_passages(assistant_text)
    if not passages:
        return 0
    opinions = (
        (
            await db.execute(
                select(ResearchOpinionMetadata).where(
                    ResearchOpinionMetadata.cluster_id.in_(cluster_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    if not opinions:
        return 0

    # Read each consulted opinion's text once (skip unreadable).
    texts: list[tuple[ResearchOpinionMetadata, str]] = []
    for op in opinions:
        try:
            texts.append((op, await load_opinion_text(db, op.opinion_id)))
        except Exception as exc:  # storage miss / not-fetched — never fatal
            log.warning(
                "caselaw verify: could not load opinion %s: %r", op.opinion_id, exc
            )

    rows: list[MessageCaselawCitation] = []
    for passage in passages:
        for op, text in texts:
            loc = locate_passage(passage, text)
            if loc is None:
                continue
            start, end = loc
            target = opinion_target(op.opinion_id, text)
            candidate = _CaselawCandidate(
                source_offset_start=start,
                source_offset_end=end,
                source_text=passage,
                source_document_id=target.id,
            )
            result = await verify(candidate, target, gateway=None)
            if not result.verified:
                continue
            rows.append(
                MessageCaselawCitation(
                    message_id=message_id,
                    opinion_id=op.opinion_id,
                    cluster_id=op.cluster_id,
                    source_offset_start=start,
                    source_offset_end=end,
                    source_text=passage,
                    verified=True,
                    verification_method=result.method,
                    verification_confidence=result.confidence,
                    partial=result.partial,
                )
            )
            break  # one verified row per passage (first matching opinion wins)

    if rows:
        db.add_all(rows)
        await db.flush()
    return len(rows)
```

- [ ] **Step 4: Run the integration tests to verify they pass**

Run: `cd api && pytest tests/integration/test_caselaw_citations.py -v`
Expected: PASS (round-trip + verbatim + invented + storage-miss).

- [ ] **Step 5: Wire into the chat finalize paths** — `api/app/api/chats.py`

Add the import near the other citation imports at the top of the file:

```python
from app.citation.caselaw import verify_and_persist_caselaw_citations
```

There are two tool-loop finalize sites that persist real `tool_sources` (a `LoopFinal.tool_sources` list). Immediately **after** each `await _persist_message_tool_sources(...)` call that passes the loop's `tool_sources` (around lines 2874 and 3417), add a guarded caselaw step. At the ~2874 site (inside the `isinstance(outcome, LoopFinal)` block, `outcome` is the `LoopFinal`):

```python
            try:
                await verify_and_persist_caselaw_citations(
                    db,
                    message_id=assistant_message_id,
                    assistant_text=outcome.text,
                    tool_sources=outcome.tool_sources,
                )
            except Exception as caselaw_exc:  # never block the turn
                log.warning(
                    "caselaw citation verification failed: %r", caselaw_exc
                )
```

At the ~3417 site, mirror it using that block's variables — `assistant_text="".join(accumulated)` and `tool_sources=loop_outcome.tool_sources if isinstance(loop_outcome, LoopFinal) else []` (match the exact expression already passed to `_persist_message_tool_sources` there). Keep it inside the existing `if error_code is None:` guard.

> Use the file's existing logger (`log`); do not introduce a new one. Place the caselaw call after tool-sources persistence so provenance rows exist first.

- [ ] **Step 6: Run the chat-path tests + the new tests**

Run: `cd api && pytest tests/test_chat_tool_loop.py tests/chat -q && pytest tests/integration/test_caselaw_citations.py -q`
Expected: PASS, no regressions. (If the exact chat test module names differ, run `pytest tests -k "chat or caselaw" -q`.)

- [ ] **Step 7: Lint + type-check the modified files**

Run: `cd api && ruff format app/citation/caselaw.py app/api/chats.py && ruff check app/citation/caselaw.py app/api/chats.py && mypy app/citation/caselaw.py app/api/chats.py`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add api/app/citation/caselaw.py api/app/api/chats.py api/tests/integration/test_caselaw_citations.py
git commit -s -m "feat(citation): verify + persist caselaw quotes at chat finalize (P1-A1)"
```

---

### Task 5: Docs + full-suite gate

**Files:**
- Modify: `docs/db-schema.md`

- [ ] **Step 1: Document the new table** — add a `message_caselaw_citations` section to `docs/db-schema.md`

Place it next to the `message_tool_sources` / `message_citations` entries. Document every column from Task 1's model (types, nullability, FK `message_id → messages(id) ON DELETE CASCADE`, the CHECK constraints, the `ix_message_caselaw_citations_message_id` index), and a one-line purpose: "quote-verified citations against external CourtListener opinions (P1-A1); parallels `message_citations` but keyed to `opinion_id`/`cluster_id` with offsets into the stored opinion plaintext, no `file_id`."

- [ ] **Step 2: Run the transparency-invariant test (must stay green)**

Run: `cd api && pytest tests/test_transparency_invariants.py -v`
Expected: PASS. The new table is NOT an audit model, so it is not in the no-raw-payload scan — confirm the test still passes unchanged (do not add the table to that scan).

- [ ] **Step 3: Run the full api gate**

Run: `cd api && ruff format --check . && ruff check . && mypy app && pytest -q`
Expected: all green (no `-m provider`; deterministic). Coverage must not decrease.

- [ ] **Step 4: Commit**

```bash
git add docs/db-schema.md
git commit -s -m "docs(db-schema): document message_caselaw_citations (P1-A1)"
```

---

## Self-Review

**Spec coverage:**
- Component 1 (opinion verification target) → Task 3 (`opinion_target` / `_OpinionVerificationTarget`). ✓
- Component 2 (blockquote extraction + locate) → Task 2 (`extract_blockquote_passages`) + Task 3 (`locate_passage`). ✓
- Component 3 (verification stages 1–2, `gateway=None`) → Task 3 test + Task 4 orchestrator. ✓
- Component 4 (`message_caselaw_citations` table) → Task 1. ✓
- Component 5 (finalize hook) → Task 4 wiring. ✓
- Error handling (storage miss skip; no-quote → none; never break the turn) → Task 4 tests + guarded call. ✓
- Testing (unit + integration, no provider gating) → Tasks 2–4. ✓
- Invariants (no new egress; not an audit table) → Task 5 Step 2. ✓
- Acceptance criteria 1–4 → Task 4 integration tests + Task 5 gate. ✓

**Placeholder scan:** no TBD/TODO; every code step shows complete code; commands have expected output. The two chats.py wiring sites are identified by line + by the adjacent `_persist_message_tool_sources` call (line numbers are approximate — match the call expression, not the literal line).

**Type consistency:** `verification_method` values `'exact_match'`/`'tolerant_match'` match the model CHECK, the migration CHECK, and `verify_exact_match`'s returned method. `_CaselawCandidate` carries all four `_CandidateProtocol` fields (incl. `source_document_id`). `verify(..., gateway=None)` short-circuits to stages 1–2 per `verification.py`. `ToolSourceRecord.external_ref` holds `str(cluster_id)` for `source_kind="caselaw"`.
