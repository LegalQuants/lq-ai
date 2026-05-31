"""DE-325 — ``build_receipt_safe`` hardens the two ``build_receipt`` call sites.

A receipt-build failure must not crash the autonomous worker nor leave the
session row non-terminal. Both call sites (delivery_node completed-path and the
executor ``AutonomousBrake`` halted-path) set the terminal status FIRST, then
build the receipt — so the receipt build is best-effort. These tests force
``build_receipt`` to raise and assert the terminal status still persists.

The wrapper resolves ``build_receipt`` by name in ``app.autonomous.receipt`` at
call time, so patching ``app.autonomous.receipt.build_receipt`` is the correct
target regardless of which caller (nodes/executor) invoked the wrapper.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.nodes import make_delivery_node
from app.autonomous.receipt import build_receipt, build_receipt_safe
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession


@pytest.mark.integration
async def test_delivery_node_survives_build_receipt_failure(
    db_session: AsyncSession,
    running_session_at_delivery: AutonomousSession,
    mock_gateway: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """delivery_node must NOT raise when build_receipt fails; the session is
    still completed, result is None, and the 'completed' audit row survives.

    The completed audit row is written BEFORE build_receipt, so it must persist
    even when receipt assembly blows up."""

    async def _boom(*args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("forced build_receipt failure")

    # Patch where build_receipt is looked up — build_receipt_safe resolves the
    # name in app.autonomous.receipt at call time.
    monkeypatch.setattr("app.autonomous.receipt.build_receipt", _boom)

    node = make_delivery_node(db_session, mock_gateway)
    state = {"session_id": running_session_at_delivery.id, "findings": []}

    # Must not raise.
    await node(state)

    await db_session.refresh(running_session_at_delivery)
    assert running_session_at_delivery.status == "completed"
    assert running_session_at_delivery.result is None

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


@pytest.mark.integration
async def test_build_receipt_safe_returns_none_on_failure(
    db_session: AsyncSession,
    running_session_at_delivery: AutonomousSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_receipt_safe returns None and does not raise when build_receipt
    raises."""

    async def _boom(*args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("forced build_receipt failure")

    monkeypatch.setattr("app.autonomous.receipt.build_receipt", _boom)

    result = await build_receipt_safe(running_session_at_delivery, db_session)
    assert result is None


@pytest.mark.integration
async def test_build_receipt_safe_returns_same_dict_on_success(
    db_session: AsyncSession,
    running_session_at_delivery: AutonomousSession,
) -> None:
    """On the happy path build_receipt_safe returns exactly what build_receipt
    returns."""
    expected = await build_receipt(running_session_at_delivery, db_session)
    actual = await build_receipt_safe(running_session_at_delivery, db_session)
    assert actual == expected
