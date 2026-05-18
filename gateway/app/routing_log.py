"""``inference_routing_log`` writer.

The Tier-Derivation choke point per PRD §3.13 / §1.5.2 is the right
place to write the audit row: every routed request — successful or
failed — flows through here, so the log captures the operator's full
inference workload.

Schema authority: ``api/alembic/versions/0001_initial.py``. The writer
uses raw SQL (parameter-bound) rather than declarative models because
the gateway doesn't own this table — api/ does — and we don't want to
double-up ORM definitions across services. The schema is
forward-compatible with C3's ALTER TABLE that adds FK constraints to
``chats`` and ``messages``: those columns are nullable today and stay
nullable after C3.

Interface, not implementation
-----------------------------

The writer is split into a small protocol (:class:`RoutingLogWriter`)
plus two implementations:

* :class:`SQLRoutingLogWriter` — the real writer; persists via
  SQLAlchemy ``AsyncEngine``.
* :class:`NullRoutingLogWriter` — a no-op used when ``DATABASE_URL``
  is unset (e.g., in unit tests or in a degraded gateway with no DB).

The route handler depends on the protocol. Tests inject a
:class:`RecordingRoutingLogWriter` to assert exactly which fields the
router populated for each scenario without spinning up Postgres.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


__all__ = [
    "InferenceRoutingLogRow",
    "NullRoutingLogWriter",
    "RecordingRoutingLogWriter",
    "RoutingLogWriter",
    "SQLRoutingLogWriter",
]


@dataclass
class InferenceRoutingLogRow:
    """One row to be written into ``inference_routing_log``.

    Field names track the Alembic migration in
    ``api/alembic/versions/0001_initial.py`` exactly. Optional fields
    that the gateway can't yet populate (``user_id``, ``chat_id``,
    ``message_id``) are nullable here and in the schema; B5 fleshes
    out the user/chat plumbing.
    """

    routed_provider: str
    routed_model: str
    routed_inference_tier: int
    requested_model: str | None = None
    user_id: uuid.UUID | None = None
    chat_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_estimate: Decimal | None = None
    latency_ms: int | None = None
    anonymization_applied: bool = False
    refused: bool = False
    refusal_reason: str | None = None
    request_id: str | None = None
    # M2-E2: 'chat' | 'judge_paraphrase' | 'embedding'. Sourced from the
    # request's ``lq_ai_purpose`` extension field on chat paths, hardcoded
    # to ``'embedding'`` on embeddings paths. Lets per-model cost
    # calibration filter routing-log rows down to judge-call traffic.
    purpose: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


# Parameter-bound INSERT. ``id`` and DB-default columns are populated
# server-side via the migration's ``server_default``; we name the columns
# we set explicitly so a future ALTER (e.g., C3's FK additions) doesn't
# break this writer.
_INSERT_SQL = text(
    """
    INSERT INTO inference_routing_log (
        timestamp,
        user_id,
        chat_id,
        message_id,
        requested_model,
        routed_provider,
        routed_model,
        routed_inference_tier,
        tokens_in,
        tokens_out,
        cost_estimate,
        latency_ms,
        anonymization_applied,
        refused,
        refusal_reason,
        request_id,
        purpose
    ) VALUES (
        :timestamp,
        :user_id,
        :chat_id,
        :message_id,
        :requested_model,
        :routed_provider,
        :routed_model,
        :routed_inference_tier,
        :tokens_in,
        :tokens_out,
        :cost_estimate,
        :latency_ms,
        :anonymization_applied,
        :refused,
        :refusal_reason,
        :request_id,
        :purpose
    )
    """
)


@runtime_checkable
class RoutingLogWriter(Protocol):
    """Protocol the route handler depends on.

    Implementations promise: never raise out of :meth:`write` for a DB
    error — the inference data path takes priority over the audit log.
    Loggers / metrics are the right surface for "we tried to log and
    couldn't"; the request itself must not fail because Postgres is
    unreachable.
    """

    async def write(self, row: InferenceRoutingLogRow) -> None:
        """Persist (or attempt to persist) one routing-log row."""
        ...


class SQLRoutingLogWriter:
    """Real :class:`RoutingLogWriter` backed by SQLAlchemy ``AsyncEngine``."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def write(self, row: InferenceRoutingLogRow) -> None:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(_INSERT_SQL, _to_params(row))
        except Exception as exc:
            # Audit-log failures must not break the inference path. Log
            # loud (operators care about these) but don't propagate.
            logger.error(
                "failed to write inference_routing_log row: %s",
                exc,
                extra={"routing_log_row": row},
            )


class NullRoutingLogWriter:
    """No-op writer used when ``DATABASE_URL`` is unset.

    The gateway logs a warning at startup so the gap is visible; here
    we silently accept rows so the data-path code is uniform regardless
    of DB availability.
    """

    async def write(self, row: InferenceRoutingLogRow) -> None:
        return None


class RecordingRoutingLogWriter:
    """In-memory writer used in tests.

    Stores every row in :attr:`rows` so unit tests can assert exactly
    which fields the router populated. Like :class:`NullRoutingLogWriter`
    it never raises.
    """

    def __init__(self) -> None:
        self.rows: list[InferenceRoutingLogRow] = []

    async def write(self, row: InferenceRoutingLogRow) -> None:
        self.rows.append(row)


def _to_params(row: InferenceRoutingLogRow) -> dict[str, object]:
    """Convert a row dataclass into the SQL bind-parameter dict."""

    return {
        "timestamp": row.timestamp,
        "user_id": row.user_id,
        "chat_id": row.chat_id,
        "message_id": row.message_id,
        "requested_model": row.requested_model,
        "routed_provider": row.routed_provider,
        "routed_model": row.routed_model,
        "routed_inference_tier": row.routed_inference_tier,
        "tokens_in": row.tokens_in,
        "tokens_out": row.tokens_out,
        "cost_estimate": row.cost_estimate,
        "latency_ms": row.latency_ms,
        "anonymization_applied": row.anonymization_applied,
        "refused": row.refused,
        "refusal_reason": row.refusal_reason,
        "request_id": row.request_id,
        "purpose": row.purpose,
    }
