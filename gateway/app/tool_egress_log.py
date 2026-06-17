"""``tool_egress_log`` writer (ADR 0014 D3).

Same design as ``app.routing_log``: the gateway is the only component that
knows which tool provider was called, so the gateway writes the audit row —
raw parameter-bound SQL (the table is api-owned; we don't double-up ORM
models across services). Counts and types only, NEVER raw payloads.
``write()`` must never raise: the egress data path takes priority over audit.
Schema authority: ``api/alembic/versions/0048_tool_egress_log.py``.

Interface, not implementation
-----------------------------

The writer is split into a small protocol (:class:`ToolEgressLogWriter`)
plus two implementations:

* :class:`SQLToolEgressLogWriter` — the real writer; persists via
  SQLAlchemy ``AsyncEngine``.
* :class:`NullToolEgressLogWriter` — a no-op used when ``DATABASE_URL``
  is unset (e.g., in unit tests or in a degraded gateway with no DB).

The route handler depends on the protocol. Tests inject a
:class:`RecordingToolEgressLogWriter` to assert exactly which fields the
router populated for each scenario without spinning up Postgres.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


__all__ = [
    "NullToolEgressLogWriter",
    "RecordingToolEgressLogWriter",
    "SQLToolEgressLogWriter",
    "ToolEgressLogRow",
    "ToolEgressLogWriter",
]


@dataclass
class ToolEgressLogRow:
    """One row to be written into ``tool_egress_log``.

    Field names track the Alembic migration in
    ``api/alembic/versions/0048_tool_egress_log.py`` exactly. Optional fields
    are nullable here and in the schema. Counts and types only — never raw
    payloads.
    """

    provider: str
    tool: str
    tier: int
    request_id: str | None = None
    bytes_out: int | None = None
    bytes_in: int | None = None
    anonymization_applied: bool = False
    refused: bool = False
    refusal_reason: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


# Parameter-bound INSERT. ``id`` and DB-default columns are populated
# server-side via the migration's ``server_default``; we name the columns
# we set explicitly so a future ALTER doesn't break this writer.
_INSERT_SQL = text(
    """
    INSERT INTO tool_egress_log (
        timestamp, request_id, provider, tool, tier,
        bytes_out, bytes_in, anonymization_applied, refused, refusal_reason
    ) VALUES (
        :timestamp, :request_id, :provider, :tool, :tier,
        :bytes_out, :bytes_in, :anonymization_applied, :refused, :refusal_reason
    )
    """
)


@runtime_checkable
class ToolEgressLogWriter(Protocol):
    """Protocol the egress handler depends on.

    Implementations promise: never raise out of :meth:`write` for a DB
    error — the egress data path takes priority over the audit log.
    Loggers / metrics are the right surface for "we tried to log and
    couldn't"; the request itself must not fail because Postgres is
    unreachable.
    """

    async def write(self, row: ToolEgressLogRow) -> None:
        """Persist (or attempt to persist) one tool-egress-log row."""
        ...


class SQLToolEgressLogWriter:
    """Real :class:`ToolEgressLogWriter` backed by SQLAlchemy ``AsyncEngine``."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def write(self, row: ToolEgressLogRow) -> None:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(_INSERT_SQL, _to_params(row))
        except Exception as exc:
            # Audit-log failures must not break the egress path. Log
            # loud (operators care about these) but don't propagate.
            logger.error(
                "failed to write tool_egress_log row: %s",
                exc,
                extra={"tool_egress_log_row": row},
            )


class NullToolEgressLogWriter:
    """No-op writer used when ``DATABASE_URL`` is unset.

    The gateway logs a warning at startup so the gap is visible; here
    we silently accept rows so the data-path code is uniform regardless
    of DB availability.
    """

    async def write(self, row: ToolEgressLogRow) -> None:
        return None


class RecordingToolEgressLogWriter:
    """In-memory writer used in tests.

    Stores every row in :attr:`rows` so unit tests can assert exactly
    which fields the egress handler populated. Like
    :class:`NullToolEgressLogWriter` it never raises.
    """

    def __init__(self) -> None:
        self.rows: list[ToolEgressLogRow] = []

    async def write(self, row: ToolEgressLogRow) -> None:
        self.rows.append(row)


def _to_params(row: ToolEgressLogRow) -> dict[str, object]:
    """Convert a row dataclass into the SQL bind-parameter dict."""

    return {
        "timestamp": row.timestamp,
        "request_id": row.request_id,
        "provider": row.provider,
        "tool": row.tool,
        "tier": row.tier,
        "bytes_out": row.bytes_out,
        "bytes_in": row.bytes_in,
        "anonymization_applied": row.anonymization_applied,
        "refused": row.refused,
        "refusal_reason": row.refusal_reason,
    }
