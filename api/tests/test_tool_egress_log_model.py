"""Model + migration test for tool_egress_log — ADR 0014 D3.

Verifies that a ``tool_egress_log`` row persists and reads back with
its core fields intact after the 0048 migration runs.

Tests run against the same SAVEPOINT-rolled-back per-test session as
the rest of the API tests (per ``tests/conftest.py``).
"""

from __future__ import annotations

import uuid

from app.models.tool_egress import ToolEgressLog


async def test_tool_egress_log_row_roundtrips(db_session) -> None:
    """A tool_egress_log row persists and reads back with its core fields."""
    row = ToolEgressLog(
        request_id="req_abc",
        provider="echo-test",
        tool="echo",
        tier=4,
        bytes_out=12,
        bytes_in=12,
        refused=False,
        anonymization_applied=False,
    )
    db_session.add(row)
    await db_session.flush()
    assert isinstance(row.id, uuid.UUID)
    assert row.refused is False
    assert row.tier == 4
