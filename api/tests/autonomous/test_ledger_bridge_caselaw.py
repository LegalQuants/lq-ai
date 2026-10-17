"""TDD test suite for build_caselaw_citations — Task 6 (WS-D PR2).

Tests the caselaw half of the ledger bridge: given structured (quote, cluster_id)
citations produced by the autonomous planner, build verified MessageCaselawCitation
rows by reusing the character-fidelity verifier.

All tests run with gateway=None so only the deterministic exact-match / tolerant-match
stages fire (no LLM needed). ``load_opinion_text`` is stubbed to avoid object-storage
calls.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, Message
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.research import ResearchOpinionMetadata
from app.models.user import User
from app.security import hash_password

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# A phrase that appears verbatim in OPINION_TEXT so locate_passage succeeds
# and the exact-match stage in the verifier passes.
OPINION_TEXT = "The court holds that the assignment clause survives the change of control."


async def _msg(db: AsyncSession) -> Message:
    """Create a minimal User + Chat + Message; returns the Message."""
    import uuid

    user = User(
        email=f"cl-{uuid.uuid4().hex[:6]}@x.com",
        hashed_password=hash_password("p"),
        role="member",
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    chat = Chat(owner_id=user.id, title="t")
    db.add(chat)
    await db.flush()
    msg = Message(chat_id=chat.id, role="assistant", content="wp")
    db.add(msg)
    await db.flush()
    return msg


async def test_build_caselaw_citations_verifies(db_session: AsyncSession) -> None:
    """Exact-verbatim quote resolves cluster → opinion text → verified row."""
    from app.autonomous.ledger_bridge import build_caselaw_citations

    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=900, cluster_id=42, storage_path="x/900", char_length=len(OPINION_TEXT)
        )
    )
    await db_session.flush()
    msg = await _msg(db_session)

    async def fake_load(db: AsyncSession, *, opinion_id: int) -> dict:
        return {"text": OPINION_TEXT}

    n = await build_caselaw_citations(
        db_session,
        message_id=msg.id,
        citations=[("assignment clause survives the change of control", "42")],
        gateway=None,
        load_opinion_text=fake_load,
    )
    assert n == 1
    row = (
        await db_session.execute(
            select(MessageCaselawCitation).where(MessageCaselawCitation.message_id == msg.id)
        )
    ).scalar_one()
    assert row.cluster_id == 42
    assert row.opinion_id == 900
    assert row.verified is True
    assert row.verification_method is not None


async def test_build_caselaw_citations_unknown_cluster_skipped(
    db_session: AsyncSession,
) -> None:
    """No ResearchOpinionMetadata for the cited cluster → skip; returns 0."""
    from app.autonomous.ledger_bridge import build_caselaw_citations

    msg = await _msg(db_session)

    async def fake_load(db: AsyncSession, *, opinion_id: int) -> dict:
        return {"text": OPINION_TEXT}

    n = await build_caselaw_citations(
        db_session,
        message_id=msg.id,
        citations=[("assignment clause survives the change of control", "9999")],
        gateway=None,
        load_opinion_text=fake_load,
    )
    assert n == 0  # no metadata row for cluster 9999


async def test_build_caselaw_citations_locate_miss_skipped(
    db_session: AsyncSession,
) -> None:
    """Quote not found in opinion text → locate miss → skip; no row fabricated."""
    from app.autonomous.ledger_bridge import build_caselaw_citations

    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=901, cluster_id=43, storage_path="x/901", char_length=len(OPINION_TEXT)
        )
    )
    await db_session.flush()
    msg = await _msg(db_session)

    async def fake_load(db: AsyncSession, *, opinion_id: int) -> dict:
        return {"text": OPINION_TEXT}

    n = await build_caselaw_citations(
        db_session,
        message_id=msg.id,
        citations=[("this text does not appear anywhere in the opinion", "43")],
        gateway=None,
        load_opinion_text=fake_load,
    )
    assert n == 0


async def test_build_caselaw_citations_empty_quote_skipped(
    db_session: AsyncSession,
) -> None:
    """Empty-string quote is dropped by the guard before any DB lookup — no row."""
    from app.autonomous.ledger_bridge import build_caselaw_citations

    db_session.add(
        ResearchOpinionMetadata(
            opinion_id=902, cluster_id=44, storage_path="x/902", char_length=len(OPINION_TEXT)
        )
    )
    await db_session.flush()
    msg = await _msg(db_session)

    async def fake_load(db: AsyncSession, *, opinion_id: int) -> dict:
        return {"text": OPINION_TEXT}

    n = await build_caselaw_citations(
        db_session,
        message_id=msg.id,
        citations=[("   ", "44")],  # whitespace-only — guard fires
        gateway=None,
        load_opinion_text=fake_load,
    )
    assert n == 0
    rows = (
        (
            await db_session.execute(
                select(MessageCaselawCitation).where(MessageCaselawCitation.message_id == msg.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 0
