"""Regression: delivery_node must write a 'completed' audit row.

The 2026-05-27 fresh-install acceptance showed completed autonomous
sessions reporting ``terminal_reason=None`` on their receipt.
:func:`app.autonomous.receipt.build_receipt` derives ``terminal_reason``
from a terminal audit row, but ``delivery_node`` only set
``session.status='completed'`` without ever auditing the completion.
This test pins the fix: the ``autonomous_session.completed`` row is
written BEFORE ``build_receipt`` so the receipt's ``terminal_reason``
populates to ``"completed"``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.nodes import make_delivery_node
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession


@pytest.mark.integration
async def test_delivery_writes_completed_audit_row_so_receipt_terminal_reason_populates(
    db_session: AsyncSession,
    running_session_at_delivery: AutonomousSession,
    mock_gateway: object,
) -> None:
    """delivery_node writes autonomous_session.completed before build_receipt
    so the receipt's terminal_reason is 'completed' (was None — the bug)."""
    node = make_delivery_node(db_session, mock_gateway)
    state = {"session_id": running_session_at_delivery.id, "findings": []}
    await node(state)

    rows = (
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
    assert len(rows) == 1

    await db_session.refresh(running_session_at_delivery)
    receipt = running_session_at_delivery.result
    assert receipt is not None
    assert receipt["terminal_reason"] == "completed"
