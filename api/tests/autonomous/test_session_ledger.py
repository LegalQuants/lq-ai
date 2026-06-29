"""TDD tests for build_session_ledger — WS-D PR2 Task 7.

Tests the integration bridge that manufactures a hidden chat+message,
splits structured citations by kind (kb vs caselaw), builds citation rows
via Tasks 5/6, runs assemble_ledger_entries + compute_and_record_gate, and
returns a gate verdict dict (or None when there is nothing to ledger).
"""

import pytest
from sqlalchemy import select

from app.autonomous.ledger_bridge import build_session_ledger
from app.models.autonomous import AutonomousSession
from app.models.chat import Chat
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.user import User
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate
from app.security import hash_password

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_build_session_ledger_creates_hidden_chat_entries_and_gate(
    db_session, kb_with_one_indexed_file
):
    from app.models.document import DocumentChunk

    chunk = (
        await db_session.execute(
            select(DocumentChunk).where(DocumentChunk.id == kb_with_one_indexed_file.chunk_id)
        )
    ).scalar_one()
    quote = chunk.content[:40]
    user = User(
        email="sl@x.com",
        hashed_password=hash_password("p"),
        role="member",
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    sess = AutonomousSession(user_id=user.id, trigger_kind="manual", params={"query": "q"})
    db_session.add(sess)
    await db_session.flush()

    verdict = await build_session_ledger(
        db_session,
        session=sess,
        work_product_text="Work product.",
        findings=[
            {
                "title": "T",
                "summary": "S",
                "severity": "info",
                "citations": [{"quote": quote, "source": 1}],
            }
        ],
        evidence=[
            {
                "n": 1,
                "kind": "kb",
                "ref": str(kb_with_one_indexed_file.chunk_id),
                "content": chunk.content,
                "display": "nda.pdf",
            }
        ],
        gateway=None,
    )
    assert verdict is not None and verdict["gate_status"] in {
        "fiduciary_grade",
        "supported_only",
        "flagged",
    }

    chat = (
        await db_session.execute(select(Chat).where(Chat.autonomous_session_id == sess.id))
    ).scalar_one()  # hidden chat manufactured
    entries = (
        (
            await db_session.execute(
                select(CitationLedgerEntry).where(CitationLedgerEntry.chat_id == chat.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) >= 1
    gate = (
        await db_session.execute(
            select(WorkProductFiduciaryGate).where(WorkProductFiduciaryGate.chat_id == chat.id)
        )
    ).scalar_one()
    assert gate.gate_status == verdict["gate_status"]


async def test_build_session_ledger_no_citations_returns_none(db_session):
    user = User(
        email="sl2@x.com",
        hashed_password=hash_password("p"),
        role="member",
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    sess = AutonomousSession(user_id=user.id, trigger_kind="manual", params={"query": "q"})
    db_session.add(sess)
    await db_session.flush()
    verdict = await build_session_ledger(
        db_session,
        session=sess,
        work_product_text="No citations.",
        findings=[{"title": "T", "summary": "S", "severity": "info", "citations": []}],
        evidence=[],
        gateway=None,
    )
    assert verdict is None  # nothing to ledger → no manufactured chat, no gate
    assert (
        await db_session.execute(select(Chat).where(Chat.autonomous_session_id == sess.id))
    ).scalar_one_or_none() is None
