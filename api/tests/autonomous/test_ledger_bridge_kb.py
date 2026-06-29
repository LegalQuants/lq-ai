"""TDD test suite for build_kb_citations — Task 5 (WS-D PR2).

Tests the KB half of the ledger bridge: given structured (quote, chunk_id)
citations produced by the autonomous planner, build verified MessageCitation
rows by reusing the character-fidelity verifier.

Fixtures: kb_with_one_indexed_file from tests/autonomous/conftest.py.
Runs without a gateway (gateway=None) — the deterministic exact/tolerant
verification stages fire without an LLM.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.ledger_bridge import build_kb_citations
from app.models.chat import Chat, Message, MessageCitation
from app.models.document import DocumentChunk
from app.models.user import User
from app.security import hash_password

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _msg(db: AsyncSession, owner_id: object) -> Message:
    """Create a minimal Chat + Message owned by owner_id."""
    chat = Chat(owner_id=owner_id, title="t")
    db.add(chat)
    await db.flush()
    msg = Message(chat_id=chat.id, role="assistant", content="wp")
    db.add(msg)
    await db.flush()
    return msg


async def test_build_kb_citations_verifies_and_persists(
    db_session: AsyncSession,
    kb_with_one_indexed_file: object,
) -> None:
    """Exact-verbatim quote from chunk content produces one verified row."""
    from tests.autonomous.conftest import KbOneFile

    kb: KbOneFile = kb_with_one_indexed_file  # type: ignore[assignment]
    chunk = (
        await db_session.execute(select(DocumentChunk).where(DocumentChunk.id == kb.chunk_id))
    ).scalar_one()
    quote = chunk.content[:40]  # verbatim span — exact-match stage fires

    user = User(
        email="kb-bridge@x.com",
        hashed_password=hash_password("p"),
        role="member",
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    msg = await _msg(db_session, user.id)

    n = await build_kb_citations(
        db_session,
        message_id=msg.id,
        citations=[(quote, str(kb.chunk_id))],
        gateway=None,
    )

    assert n == 1
    rows = (
        (
            await db_session.execute(
                select(MessageCitation).where(MessageCitation.message_id == msg.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].verified is True
    assert rows[0].source_text == quote
    assert rows[0].verification_method is not None


async def test_build_kb_citations_drops_unverifiable(
    db_session: AsyncSession,
    kb_with_one_indexed_file: object,
) -> None:
    """Quote not found in chunk content is dropped — no row, no fabrication."""
    user = User(
        email="kb-bridge2@x.com",
        hashed_password=hash_password("p"),
        role="member",
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    msg = await _msg(db_session, user.id)

    from tests.autonomous.conftest import KbOneFile

    kb: KbOneFile = kb_with_one_indexed_file  # type: ignore[assignment]
    n = await build_kb_citations(
        db_session,
        message_id=msg.id,
        citations=[("text that does not appear anywhere", str(kb.chunk_id))],
        gateway=None,
    )

    assert n == 0  # honest: unverifiable quote dropped, no row
