"""Authority citations → ledger assembly + resolve + gate (WS-E PR1b).

Verifies:
- assemble_ledger_entries writes a CitationLedgerEntry for each
  MessageAuthorityCitation row (source_kind = content_kind, provider = source_type)
- an unverified authority citation produces gate_status == "flagged"
- resolve_ledger_entries returns a passage block with the source text
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.gate import compute_and_record_gate
from app.citation.ledger import assemble_ledger_entries, resolve_ledger_entries
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.message_authority_citation import (
    MessageAuthorityCitation,
)
from app.models.user import User

# ---------------------------------------------------------------------------
# Local helper — mirrors api/tests/citation/conftest.py `seeded` pattern
# ---------------------------------------------------------------------------


async def _message_and_chat(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Create minimal User → Chat → assistant Message; return (message_id, chat_id)."""
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db.add(user)
    await db.flush()
    chat = Chat(owner_id=user.id, title="t")
    db.add(chat)
    await db.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x")
    db.add(msg)
    await db.flush()
    return msg.id, chat.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assemble_creates_authority_ledger_entry(db_session: AsyncSession) -> None:
    mid, _cid = await _message_and_chat(db_session)
    db_session.add(
        MessageAuthorityCitation(
            message_id=mid,
            source_type="govinfo",
            external_ref="USCODE-2022-title15",
            content_kind="statute",
            source_offset_start=0,
            source_offset_end=10,
            source_text="Every cont",
            verified=True,
            verification_method="exact_match",
            verification_confidence=1.0,
            partial=False,
        )
    )
    await db_session.flush()
    await assemble_ledger_entries(db_session, message_id=mid)
    rows = (
        (
            await db_session.execute(
                select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == mid)
            )
        )
        .scalars()
        .all()
    )
    entry = next(r for r in rows if r.message_authority_citation_id is not None)
    # source_kind = content_kind (the ledger label); provider = source_type (the source)
    assert entry.source_kind == "statute"
    assert entry.verification_status == "exact_match"
    assert entry.provider == "govinfo"


@pytest.mark.asyncio
async def test_authority_unverified_flags_gate(db_session: AsyncSession) -> None:
    mid, _cid = await _message_and_chat(db_session)
    db_session.add(
        MessageAuthorityCitation(
            message_id=mid,
            source_type="govinfo",
            external_ref="USCODE-x",
            content_kind="statute",
            source_offset_start=0,
            source_offset_end=5,
            source_text="bogus",
            verified=False,
            verification_method=None,
            partial=False,
        )
    )
    await db_session.flush()
    await assemble_ledger_entries(db_session, message_id=mid)
    gate = await compute_and_record_gate(db_session, message_id=mid)
    # unverified → verification_status="unverified" → FAIL bucket → gate_status="flagged"
    assert gate is not None
    assert gate.gate_status == "flagged"


@pytest.mark.asyncio
async def test_resolve_returns_authority_passage(db_session: AsyncSession) -> None:
    mid, cid = await _message_and_chat(db_session)
    db_session.add(
        MessageAuthorityCitation(
            message_id=mid,
            source_type="govinfo",
            external_ref="USCODE-2022-title15",
            content_kind="statute",
            source_offset_start=0,
            source_offset_end=10,
            source_text="Every cont",
            verified=True,
            verification_method="exact_match",
            verification_confidence=1.0,
            partial=False,
        )
    )
    await db_session.flush()
    await assemble_ledger_entries(db_session, message_id=mid)
    resolved = await resolve_ledger_entries(db_session, chat_id=cid, message_id=mid)
    # source_kind on the outer dict is the content_kind ("statute")
    auth = [e for e in resolved if e.get("source_kind") in {"statute", "regulation"}]
    assert auth, "expected at least one authority entry in resolved output"
    assert "Every cont" in str(auth[0].get("source", {}))
