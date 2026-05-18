"""Unit tests for :mod:`app.routing_log`.

Tests focus on the writer-protocol invariant ("never raise") and on
the parameter-binding shape that the SQL writer hands to SQLAlchemy.
DB-backed integration coverage lives in ``test_routing_log_db.py``
(which only runs when ``DATABASE_URL`` points at a real Postgres).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routing_log import (
    InferenceRoutingLogRow,
    NullRoutingLogWriter,
    RecordingRoutingLogWriter,
    SQLRoutingLogWriter,
    _to_params,
)

# --- Row construction --------------------------------------------------------


@pytest.mark.unit
def test_routing_log_row_defaults_match_schema() -> None:
    """Default values mirror ``inference_routing_log`` server defaults."""

    row = InferenceRoutingLogRow(
        routed_provider="anthropic-prod",
        routed_model="claude-opus-4-7",
        routed_inference_tier=4,
    )
    assert row.requested_model is None
    assert row.user_id is None
    assert row.chat_id is None
    assert row.message_id is None
    assert row.tokens_in is None
    assert row.tokens_out is None
    assert row.cost_estimate is None
    assert row.latency_ms is None
    assert row.anonymization_applied is False
    assert row.refused is False
    assert row.refusal_reason is None
    assert row.request_id is None
    # timestamp default is timezone-aware UTC
    assert row.timestamp.tzinfo is not None


@pytest.mark.unit
def test_to_params_emits_all_columns() -> None:
    """The bind-parameter dict has exactly the columns the SQL INSERT wants."""

    row = InferenceRoutingLogRow(
        routed_provider="p",
        routed_model="m",
        routed_inference_tier=2,
        requested_model="alias",
        tokens_in=10,
        tokens_out=20,
        cost_estimate=Decimal("0.0250"),
        latency_ms=150,
        request_id="req_xyz",
    )
    params = _to_params(row)

    expected = {
        "timestamp",
        "user_id",
        "chat_id",
        "message_id",
        "requested_model",
        "routed_provider",
        "routed_model",
        "routed_inference_tier",
        "tokens_in",
        "tokens_out",
        "cost_estimate",
        "latency_ms",
        "anonymization_applied",
        "refused",
        "refusal_reason",
        "request_id",
        "purpose",
    }
    assert set(params.keys()) == expected
    assert params["routed_provider"] == "p"
    assert params["routed_model"] == "m"
    assert params["routed_inference_tier"] == 2
    assert params["cost_estimate"] == Decimal("0.0250")


# --- Recording writer (test helper for router tests) ------------------------


@pytest.mark.unit
async def test_recording_writer_captures_rows() -> None:
    writer = RecordingRoutingLogWriter()
    row = InferenceRoutingLogRow(
        routed_provider="p",
        routed_model="m",
        routed_inference_tier=4,
    )
    await writer.write(row)
    await writer.write(row)
    assert len(writer.rows) == 2
    assert writer.rows[0] is row


# --- Null writer -------------------------------------------------------------


@pytest.mark.unit
async def test_null_writer_accepts_rows_without_io() -> None:
    writer = NullRoutingLogWriter()
    row = InferenceRoutingLogRow(
        routed_provider="p",
        routed_model="m",
        routed_inference_tier=4,
    )
    # Should never raise; returns None.
    assert await writer.write(row) is None


# --- SQL writer: never-raise invariant --------------------------------------


@pytest.mark.unit
async def test_sql_writer_swallows_db_errors() -> None:
    """The audit log must not break the inference data path.

    We use a fake engine whose ``begin()`` raises; the writer should log
    and return without re-raising.
    """

    fake_engine = MagicMock()

    # ``async with engine.begin() as conn`` — make begin() raise.
    bad_cm = MagicMock()
    bad_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("postgres unreachable"))
    bad_cm.__aexit__ = AsyncMock(return_value=None)
    fake_engine.begin.return_value = bad_cm

    writer = SQLRoutingLogWriter(fake_engine)
    row = InferenceRoutingLogRow(
        routed_provider="p",
        routed_model="m",
        routed_inference_tier=4,
    )
    # Must not raise.
    await writer.write(row)


@pytest.mark.unit
async def test_sql_writer_calls_engine_with_bound_params() -> None:
    """The successful path passes the row's bind parameters to ``execute``."""

    conn = MagicMock()
    conn.execute = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    fake_engine = MagicMock()
    fake_engine.begin.return_value = cm

    writer = SQLRoutingLogWriter(fake_engine)
    row = InferenceRoutingLogRow(
        routed_provider="anthropic-prod",
        routed_model="claude-opus-4-7",
        routed_inference_tier=4,
        requested_model="smart",
        tokens_in=12,
        tokens_out=7,
        latency_ms=180,
        request_id="req_1",
    )
    await writer.write(row)

    conn.execute.assert_awaited_once()
    args, _kwargs = conn.execute.call_args
    # First positional arg is the SQL TextClause; second is the params dict.
    assert "INSERT INTO inference_routing_log" in str(args[0])
    bound = args[1]
    assert bound["routed_provider"] == "anthropic-prod"
    assert bound["routed_model"] == "claude-opus-4-7"
    assert bound["routed_inference_tier"] == 4
    assert bound["requested_model"] == "smart"
    assert bound["tokens_in"] == 12
    assert bound["tokens_out"] == 7
    assert bound["latency_ms"] == 180
    assert bound["request_id"] == "req_1"
    assert bound["refused"] is False


@pytest.mark.unit
def test_routing_log_row_uuid_fields_accept_uuids() -> None:
    """``user_id``, ``chat_id``, ``message_id`` accept ``uuid.UUID`` instances."""

    user_id = uuid.uuid4()
    chat_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    row = InferenceRoutingLogRow(
        routed_provider="p",
        routed_model="m",
        routed_inference_tier=1,
        user_id=user_id,
        chat_id=chat_id,
        message_id=msg_id,
    )
    params = _to_params(row)
    assert params["user_id"] == user_id
    assert params["chat_id"] == chat_id
    assert params["message_id"] == msg_id
