"""TDD tests for build_session_ledger — WS-D PR2 Task 7.

Tests the integration bridge that manufactures a hidden chat+message,
splits structured citations by kind (kb vs caselaw), builds citation rows
via Tasks 5/6, runs assemble_ledger_entries + compute_and_record_gate, and
returns a gate verdict dict (or None when there is nothing to ledger).

Also covers the delivery-node SAVEPOINT isolation (PR2 regression test):
delivery_node wraps build_session_ledger in ``async with db.begin_nested()``
so a bridge flush-failure rolls back ONLY the manufactured rows and leaves
the terminal session status + audit row commiteable.
"""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.ledger_bridge import build_session_ledger
from app.autonomous.nodes import make_delivery_node
from app.autonomous.state import AutonomousSessionState
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.chat import Chat
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.user import User
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate
from app.security import hash_password
from tests.autonomous.conftest import KbOneFile

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_build_session_ledger_creates_hidden_chat_entries_and_gate(
    db_session: AsyncSession, kb_with_one_indexed_file: KbOneFile
) -> None:
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


async def test_build_session_ledger_no_citations_returns_none(db_session: AsyncSession) -> None:
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


# ---------------------------------------------------------------------------
# PR2 regression: SAVEPOINT isolation in delivery_node
# ---------------------------------------------------------------------------


async def test_delivery_node_savepoint_isolates_bridge_failure(
    db_session: AsyncSession,
    running_session_at_delivery: AutonomousSession,
    mock_gateway: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bridge flush inside the SAVEPOINT must not poison the terminal commit.

    The delivery_node wraps build_session_ledger in
    ``async with db.begin_nested()`` (SAVEPOINT).  This test injects a stub
    that does a REAL DB WRITE (Chat row) then raises, proving that:

    (a) session.status == "completed"  — terminal commit went through
    (b) the autonomous_session.completed audit row exists  — same
    (c) NO Chat row with autonomous_session_id == session.id  — the
        SAVEPOINT rolled the stub's partial write back
    (d) session.result is set (receipt present, no fiduciary_gate key)

    This is the PR1-C1 surface: the savepoint must prevent a bridge error
    from orphaning rows AND from poisoning the outer terminal commit.
    """

    async def boom(
        db: AsyncSession,
        *,
        session: AutonomousSession,
        work_product_text: str,
        findings: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        gateway: Any,
        judge_model: str = "fast",
    ) -> dict[str, Any] | None:
        """Partial write then raise — exercises the SAVEPOINT rollback path."""
        db.add(
            Chat(
                owner_id=session.user_id,
                title="partial",
                autonomous_session_id=session.id,
            )
        )
        await db.flush()  # real write inside the savepoint
        raise RuntimeError("bridge boom")

    monkeypatch.setattr("app.autonomous.ledger_bridge.build_session_ledger", boom)

    # Build analysis_content so delivery_node's `if findings and evidence and
    # work_product` guard is True and the bridge block is entered.
    analysis_content = (
        "```json\n"
        + json.dumps(
            {
                "findings": [
                    {
                        "title": "Test finding",
                        "summary": "S",
                        "severity": "info",
                        "citations": [{"quote": "some quote text", "source": 1}],
                    }
                ],
                "suggested_memories": [],
                "suggested_precedents": [],
                "privilege_concerns": [],
                "scope_concerns": [],
            }
        )
        + "\n```"
    )

    state: AutonomousSessionState = {
        "session_id": str(running_session_at_delivery.id),
        "findings": [],
        "analysis_content": analysis_content,
        "analysis_evidence": [
            {
                "n": 1,
                "kind": "kb",
                "ref": str(uuid.uuid4()),
                "content": "some evidence text",
                "display": "doc.pdf",
            }
        ],
    }

    node = make_delivery_node(db_session, mock_gateway)
    await node(state)

    # (a) Session reached 'completed' despite the bridge failure.
    await db_session.refresh(running_session_at_delivery)
    assert running_session_at_delivery.status == "completed"

    # (b) The terminal audit row was committed.
    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.resource_type == "autonomous_session")
                .where(AuditLog.resource_id == str(running_session_at_delivery.id))
                .where(AuditLog.action == "autonomous_session.completed")
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1, "terminal audit row must exist"

    # (c) No orphaned Chat row — the SAVEPOINT rolled back the stub's flush.
    orphan_chat = (
        await db_session.execute(
            select(Chat).where(Chat.autonomous_session_id == running_session_at_delivery.id)
        )
    ).scalar_one_or_none()
    assert orphan_chat is None, "SAVEPOINT must have rolled back the stub's Chat row"

    # (d) Receipt is set (delivery committed its terminal payload).
    result = running_session_at_delivery.result
    assert result is not None, "session.result must be set after delivery"
    assert "fiduciary_gate" not in result, "bridge failed → no gate in receipt"
