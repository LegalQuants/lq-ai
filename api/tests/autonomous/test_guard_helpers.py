"""Unit + integration tests for M4-A3.1 guard helper primitives.

Covers three pieces added by the A3.1 sub-task:

1. Brake exception hierarchy (``AutonomousBrake`` and its three subclasses):
   pure unit tests — no DB required.

2. ``estimate_tool_cost`` (R4 cost wrapper in ``app.autonomous.cost``):
   unit tests that monkeypatch the underlying estimator.

3. ``autonomous_audit`` (closed-enum audit wrapper in ``app.autonomous.audit``):
   integration tests (DB required) + an assertion-error unit test for
   unknown event names.

Also confirms the existing ``run_phase_transition`` still passes after its
refactor onto ``autonomous_audit``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.user import User
from app.security import hash_password

# ---------------------------------------------------------------------------
# DB helpers (mirror the pattern from test_autonomous_models.py)
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_session(db: AsyncSession, *, user: User) -> AutonomousSession:
    sess = AutonomousSession(user_id=user.id, trigger_kind="manual")
    db.add(sess)
    await db.flush()
    return sess


# ===========================================================================
# Piece 1 — Brake exception hierarchy
# ===========================================================================


@pytest.mark.unit
def test_session_halted_attributes() -> None:
    """SessionHalted carries ``reason`` via ``.details`` and the right code."""
    from app.errors import CODE_AUTONOMOUS_HALTED, SessionHalted

    exc = SessionHalted("session halted externally", reason="external_halt")
    assert exc.effective_code == CODE_AUTONOMOUS_HALTED
    assert exc.details["reason"] == "external_halt"
    assert exc.message == "session halted externally"


@pytest.mark.unit
def test_session_halted_idle_timeout_reason() -> None:
    from app.errors import SessionHalted

    exc = SessionHalted("idle timeout", reason="idle_timeout")
    assert exc.details["reason"] == "idle_timeout"


@pytest.mark.unit
def test_tool_not_granted_attributes() -> None:
    """ToolNotGranted carries ``intent`` + ``phase`` via ``.details``."""
    from app.errors import CODE_AUTONOMOUS_TOOL_NOT_GRANTED, ToolNotGranted

    exc = ToolNotGranted(
        "tool not granted for phase",
        intent="run_skill",
        phase="intake",
    )
    assert exc.effective_code == CODE_AUTONOMOUS_TOOL_NOT_GRANTED
    assert exc.details["intent"] == "run_skill"
    assert exc.details["phase"] == "intake"


@pytest.mark.unit
def test_cost_cap_reached_attributes() -> None:
    """CostCapReached carries ``projected_usd`` via ``.details``."""
    from app.errors import CODE_AUTONOMOUS_COST_CAP_REACHED, CostCapReached

    exc = CostCapReached("cost cap exceeded", projected_usd=1.23)
    assert exc.effective_code == CODE_AUTONOMOUS_COST_CAP_REACHED
    assert exc.details["projected_usd"] == pytest.approx(1.23)


@pytest.mark.unit
def test_brake_hierarchy_inheritance() -> None:
    """All three subclasses are AutonomousBrake and LQAIError."""
    from app.errors import (
        AutonomousBrake,
        CostCapReached,
        LQAIError,
        SessionHalted,
        ToolNotGranted,
    )

    for cls in (SessionHalted, ToolNotGranted, CostCapReached):
        exc: LQAIError = cls("test")
        assert isinstance(exc, AutonomousBrake)
        assert isinstance(exc, LQAIError)


@pytest.mark.unit
def test_brake_exceptions_have_409_family_status() -> None:
    """AutonomousBrake subclasses default to 409 CONFLICT."""
    from fastapi import status

    from app.errors import CostCapReached, SessionHalted, ToolNotGranted

    for exc in (
        SessionHalted("x"),
        ToolNotGranted("x"),
        CostCapReached("x"),
    ):
        assert exc.effective_http_status == status.HTTP_409_CONFLICT


@pytest.mark.unit
def test_brake_code_constants_match_class_code() -> None:
    """Code constants on the module match the class-level ``code`` attributes."""
    from app.errors import (
        CODE_AUTONOMOUS_COST_CAP_REACHED,
        CODE_AUTONOMOUS_HALTED,
        CODE_AUTONOMOUS_TOOL_NOT_GRANTED,
        CostCapReached,
        SessionHalted,
        ToolNotGranted,
    )

    assert SessionHalted.code == CODE_AUTONOMOUS_HALTED
    assert ToolNotGranted.code == CODE_AUTONOMOUS_TOOL_NOT_GRANTED
    assert CostCapReached.code == CODE_AUTONOMOUS_COST_CAP_REACHED


@pytest.mark.unit
def test_brake_to_envelope_carries_details() -> None:
    """``to_envelope`` surfaces the structured details dict correctly."""
    from app.errors import SessionHalted

    exc = SessionHalted("halted for test", reason="external_halt")
    envelope = exc.to_envelope()
    assert envelope["detail"]["code"] == "autonomous_halted"
    assert envelope["detail"]["details"]["reason"] == "external_halt"


# ===========================================================================
# Piece 2 — estimate_tool_cost (R4 cost wrapper)
# ===========================================================================


@pytest.mark.unit
async def test_run_skill_delegates_to_estimator() -> None:
    """run_skill intent delegates to estimate_judge_call_cost_usd."""
    from app.autonomous.cost import estimate_tool_cost

    sentinel = Decimal("0.042")
    mock_estimator = AsyncMock(return_value=sentinel)

    with patch("app.autonomous.cost.estimate_judge_call_cost_usd", mock_estimator):
        result = await estimate_tool_cost(
            ToolIntent.run_skill,
            {"judge_model": "claude-haiku-4-5"},
            db=None,
        )

    mock_estimator.assert_called_once_with(None, judge_model="claude-haiku-4-5")
    assert result == sentinel


@pytest.mark.unit
async def test_run_playbook_delegates_to_estimator() -> None:
    """run_playbook intent also delegates to estimate_judge_call_cost_usd."""
    from app.autonomous.cost import estimate_tool_cost

    sentinel = Decimal("0.008")
    mock_estimator = AsyncMock(return_value=sentinel)

    with patch("app.autonomous.cost.estimate_judge_call_cost_usd", mock_estimator):
        result = await estimate_tool_cost(
            ToolIntent.run_playbook,
            {"model": "claude-sonnet-4-6"},
            db=None,
        )

    mock_estimator.assert_called_once_with(None, judge_model="claude-sonnet-4-6")
    assert result == sentinel


@pytest.mark.unit
async def test_run_skill_prefers_judge_model_over_model() -> None:
    """run_skill uses ``judge_model`` key when present; falls back to ``model``."""
    from app.autonomous.cost import estimate_tool_cost

    mock_estimator = AsyncMock(return_value=Decimal("0.005"))

    with patch("app.autonomous.cost.estimate_judge_call_cost_usd", mock_estimator):
        await estimate_tool_cost(
            ToolIntent.run_skill,
            {"judge_model": "claude-haiku-4-5", "model": "something-else"},
            db=None,
        )

    # Must prefer judge_model
    mock_estimator.assert_called_once_with(None, judge_model="claude-haiku-4-5")


@pytest.mark.unit
async def test_retrieve_chunks_returns_zero_no_estimator_call() -> None:
    """retrieve_chunks → Decimal("0"), estimator NOT called."""
    from app.autonomous.cost import estimate_tool_cost

    mock_estimator = AsyncMock(return_value=Decimal("9.99"))

    with patch("app.autonomous.cost.estimate_judge_call_cost_usd", mock_estimator):
        result = await estimate_tool_cost(ToolIntent.retrieve_chunks, {}, db=None)

    mock_estimator.assert_not_called()
    assert result == Decimal("0")


@pytest.mark.unit
async def test_propose_memory_returns_zero_no_estimator_call() -> None:
    from app.autonomous.cost import estimate_tool_cost

    mock_estimator = AsyncMock(return_value=Decimal("9.99"))
    with patch("app.autonomous.cost.estimate_judge_call_cost_usd", mock_estimator):
        result = await estimate_tool_cost(ToolIntent.propose_memory, {}, db=None)
    mock_estimator.assert_not_called()
    assert result == Decimal("0")


@pytest.mark.unit
async def test_emit_finding_returns_zero_no_estimator_call() -> None:
    from app.autonomous.cost import estimate_tool_cost

    mock_estimator = AsyncMock(return_value=Decimal("9.99"))
    with patch("app.autonomous.cost.estimate_judge_call_cost_usd", mock_estimator):
        result = await estimate_tool_cost(ToolIntent.emit_finding, {}, db=None)
    mock_estimator.assert_not_called()
    assert result == Decimal("0")


@pytest.mark.unit
async def test_notify_returns_zero_no_estimator_call() -> None:
    from app.autonomous.cost import estimate_tool_cost

    mock_estimator = AsyncMock(return_value=Decimal("9.99"))
    with patch("app.autonomous.cost.estimate_judge_call_cost_usd", mock_estimator):
        result = await estimate_tool_cost(ToolIntent.notify, {}, db=None)
    mock_estimator.assert_not_called()
    assert result == Decimal("0")


# ===========================================================================
# Piece 3 — autonomous_audit (closed-enum audit wrapper)
# ===========================================================================


@pytest.mark.unit
def test_undefined_event_raises_assertion_error() -> None:
    """Passing an event not in _ACTIONS raises AssertionError immediately.

    The assertion fires before any DB access, so we can use a simple
    namespace stub instead of a real ORM object.
    """
    import asyncio
    import types

    from app.autonomous.audit import autonomous_audit

    # Minimal stub — the assertion fires before any attribute is read.
    dummy_session = types.SimpleNamespace(user_id=uuid.uuid4(), id=uuid.uuid4())

    with pytest.raises(AssertionError, match="undefined autonomous audit action"):
        asyncio.get_event_loop().run_until_complete(
            autonomous_audit(None, dummy_session, "banana_split")  # type: ignore[arg-type]
        )


@pytest.mark.integration
async def test_valid_event_writes_audit_row(db_session: AsyncSession) -> None:
    """A valid event writes one audit_log row with the correct fields."""
    from app.autonomous.audit import autonomous_audit

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user)
    session_id_str = str(sess.id)

    await autonomous_audit(db_session, sess, "tool_call", tool="run_skill", phase="analysis")

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.tool_call")
                .where(AuditLog.resource_id == session_id_str)
            )
        )
        .scalars()
        .all()
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.resource_type == "autonomous_session"
    assert row.resource_id == session_id_str
    assert row.user_id == user.id
    assert row.details is not None
    assert row.details["tool"] == "run_skill"
    assert row.details["phase"] == "analysis"


@pytest.mark.integration
async def test_started_event_writes_correct_action(db_session: AsyncSession) -> None:
    """'started' event produces action='autonomous_session.started'."""
    from app.autonomous.audit import autonomous_audit

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user)

    await autonomous_audit(db_session, sess, "started")

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.started")
                .where(AuditLog.resource_id == str(sess.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].details is None  # no kwargs → None


@pytest.mark.integration
async def test_halted_event_with_details(db_session: AsyncSession) -> None:
    """'halted' event stores the details dict."""
    from app.autonomous.audit import autonomous_audit

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user)

    await autonomous_audit(db_session, sess, "halted", reason="cost_cap_reached")

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.halted")
                .where(AuditLog.resource_id == str(sess.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].details["reason"] == "cost_cap_reached"


@pytest.mark.integration
async def test_phases_run_phase_transition_uses_autonomous_audit(
    db_session: AsyncSession,
) -> None:
    """run_phase_transition now delegates to autonomous_audit — existing
    behavior is preserved: a phase_transition audit row is written with
    the correct action and to_phase details.
    """
    from app.autonomous.phases import run_phase_transition
    from app.schemas.autonomous import Phase

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user)

    await run_phase_transition(sess, Phase.analysis, db_session)

    assert sess.current_phase == str(Phase.analysis)

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.phase_transition")
                .where(AuditLog.resource_id == str(sess.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].details["to_phase"] == str(Phase.analysis)
    assert rows[0].resource_type == "autonomous_session"
    assert rows[0].user_id == user.id
