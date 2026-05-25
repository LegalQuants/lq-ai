"""Brake tests for the guarded_tool_call chokepoint — M4-A3.3a (DE-293).

TDD acceptance bar: these tests define R4/R5/R6 behaviour.  They are
written FIRST and must be RED against the absence of ``guard.py``, then
GREEN after the implementation lands.

Brake coverage
--------------
R4  economic   — :exc:`~app.errors.CostCapReached` when projected cost
                 would exceed ``max_cost_usd``.
R5  temporal   — :exc:`~app.errors.SessionHalted` when ``halt_state ==
                 'halt_requested'`` on the pre-call refresh.
R6  contextual — :exc:`~app.errors.ToolNotGranted` when the intent is
                 not in the phase-grant set for the current phase.

Success paths
-------------
* ``propose_memory`` in Phase.drafting → autonomous_memory row written,
  ToolResult.cost_usd == 0, last_activity_at advanced, two tool_call
  audit rows (started, success).
* ``notify`` in Phase.delivery → autonomous_notifications row written.
* ``emit_finding`` in Phase.drafting → finding echoed as data, no DB row.

Exhaustiveness sanity
---------------------
* Every Phase is a key in PHASE_GRANTS.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import PHASE_GRANTS, Phase, ToolIntent
from app.models.audit import AuditLog
from app.models.autonomous import (
    AutonomousMemory,
    AutonomousNotification,
    AutonomousSession,
)
from app.models.user import User
from app.security import hash_password

# ---------------------------------------------------------------------------
# Helpers
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


async def _make_session(
    db: AsyncSession,
    *,
    user: User,
    current_phase: str = "intake",
    halt_state: str = "running",
    max_cost_usd: Decimal | None = None,
    cost_total_usd: Decimal = Decimal("0"),
) -> AutonomousSession:
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="manual",
        current_phase=current_phase,
        halt_state=halt_state,
        max_cost_usd=max_cost_usd,
        cost_total_usd=cost_total_usd,
    )
    db.add(sess)
    await db.flush()
    await db.refresh(sess)
    return sess


class _StubGateway:
    """No-op gateway — local-intent + brake paths never call it."""


# ---------------------------------------------------------------------------
# Unit — exhaustiveness sanity
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_phase_grants_covers_all_phases() -> None:
    """Every Phase member is a key in PHASE_GRANTS — no phase can KeyError."""
    for phase in Phase:
        assert phase in PHASE_GRANTS, f"Phase.{phase!r} missing from PHASE_GRANTS"


# ---------------------------------------------------------------------------
# R4 — economic brake (cost cap)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_r4_cost_cap_raises_and_latches(db_session: AsyncSession) -> None:
    """R4: CostCapReached raised when projected cost exceeds the cap.

    Monkeypatches estimate_tool_cost (as imported in guard.py's namespace)
    to return a value that exceeds the cap. Verifies:
    - CostCapReached is raised.
    - session.cost_cap_reached is True.
    - session.halt_state == 'halted'.
    - A cost_cap_reached audit row exists.
    - cost_total_usd is UNCHANGED (dispatch was not reached).
    """
    from app.errors import CostCapReached

    user = await _make_user(db_session)
    sess = await _make_session(
        db_session,
        user=user,
        current_phase="analysis",
        max_cost_usd=Decimal("0.10"),
        cost_total_usd=Decimal("0.09"),
    )
    original_cost_total = sess.cost_total_usd
    gateway = _StubGateway()

    # estimate_tool_cost would return 0.05, pushing projected to 0.14 > 0.10
    mock_estimate = AsyncMock(return_value=Decimal("0.05"))

    from app.autonomous import guard as guard_mod

    with (
        patch.object(guard_mod, "estimate_tool_cost", mock_estimate),
        pytest.raises(CostCapReached) as exc_info,
    ):
        await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.run_skill,
            {"judge_model": "claude-haiku-4-5"},
            db_session,
            gateway,
        )

    exc = exc_info.value
    assert "projected_usd" in exc.details
    assert exc.details["projected_usd"] == pytest.approx(0.14)

    await db_session.refresh(sess)
    assert sess.cost_cap_reached is True
    assert sess.halt_state == "halted"
    # dispatch was NOT reached — cost_total_usd unchanged
    assert sess.cost_total_usd == original_cost_total

    # cost_cap_reached audit row must exist
    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.cost_cap_reached")
                .where(AuditLog.resource_id == str(sess.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].details is not None
    assert rows[0].details["projected_usd"] == pytest.approx(0.14)


@pytest.mark.integration
async def test_r4_no_cap_never_trips(db_session: AsyncSession) -> None:
    """R4: when max_cost_usd is None the cap check never fires.

    A session without a cap runs propose_memory (zero cost) without issue
    even when a non-zero estimate is mocked — the cap comparison is gated
    on max_cost_usd is not None.
    """
    from app.autonomous.guard import ToolResult, guarded_tool_call

    user = await _make_user(db_session)
    sess = await _make_session(
        db_session,
        user=user,
        current_phase="drafting",
        max_cost_usd=None,
    )
    gateway = _StubGateway()

    result = await guarded_tool_call(
        sess,
        ToolIntent.propose_memory,
        {"category": "drafting_preference", "content": "No cap test."},
        db_session,
        gateway,
    )
    assert isinstance(result, ToolResult)
    assert result.cost_usd == Decimal("0")


# ---------------------------------------------------------------------------
# R5 — temporal brake (external halt)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_r5_external_halt_raises_session_halted(db_session: AsyncSession) -> None:
    """R5: SessionHalted raised when halt_state == 'halt_requested' on refresh.

    Sets halt_state = 'halt_requested' and flushes so the db.refresh inside
    guarded_tool_call re-reads it within the same transaction.  Verifies:
    - SessionHalted raised with reason='external_halt'.
    - session.halt_state == 'halted' after the call.
    - A halted audit row exists with reason='external_halt'.
    """
    from app.errors import SessionHalted

    user = await _make_user(db_session)
    sess = await _make_session(
        db_session,
        user=user,
        current_phase="analysis",
        halt_state="running",
    )
    gateway = _StubGateway()

    # Simulate an external halt arriving: set halt_state and flush so
    # the db.refresh inside guarded_tool_call sees the updated value.
    sess.halt_state = "halt_requested"
    await db_session.flush()

    with pytest.raises(SessionHalted) as exc_info:
        from app.autonomous import guard as guard_mod

        await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.retrieve_chunks,
            {"document_id": "doc-abc"},
            db_session,
            gateway,
        )

    exc = exc_info.value
    assert exc.details["reason"] == "external_halt"

    await db_session.refresh(sess)
    assert sess.halt_state == "halted"

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
    assert rows[0].details is not None
    assert rows[0].details["reason"] == "external_halt"


@pytest.mark.integration
async def test_r5_running_state_passes_through(db_session: AsyncSession) -> None:
    """R5: a session with halt_state='running' is not halted by R5."""
    from app.autonomous.guard import ToolResult, guarded_tool_call

    user = await _make_user(db_session)
    sess = await _make_session(
        db_session,
        user=user,
        current_phase="drafting",
        halt_state="running",
    )
    gateway = _StubGateway()

    result = await guarded_tool_call(
        sess,
        ToolIntent.emit_finding,
        {"finding": {"flag": "ok"}},
        db_session,
        gateway,
    )
    assert isinstance(result, ToolResult)


# ---------------------------------------------------------------------------
# R6 — contextual brake (phase grant)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_r6_intent_not_granted_raises_tool_not_granted(
    db_session: AsyncSession,
) -> None:
    """R6: ToolNotGranted raised when intent is not in the phase-grant set.

    Uses Phase.ethics_review + ToolIntent.retrieve_chunks (not in the grant
    for ethics_review — only emit_finding is). Verifies:
    - ToolNotGranted raised with intent and phase in .details.
    - A tool_call audit row with outcome='tool_not_granted' exists.
    - _dispatch was NOT reached (no DB rows created, cost unchanged).
    """
    from app.errors import ToolNotGranted

    user = await _make_user(db_session)
    sess = await _make_session(
        db_session,
        user=user,
        current_phase="ethics_review",
        halt_state="running",
    )
    gateway = _StubGateway()

    with pytest.raises(ToolNotGranted) as exc_info:
        from app.autonomous import guard as guard_mod

        await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.retrieve_chunks,
            {"document_id": "doc-abc"},
            db_session,
            gateway,
        )

    exc = exc_info.value
    assert exc.details["intent"] == "retrieve_chunks"
    assert exc.details["phase"] == "ethics_review"

    # One tool_call audit row with outcome='tool_not_granted'
    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.tool_call")
                .where(AuditLog.resource_id == str(sess.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].details is not None
    assert rows[0].details["outcome"] == "tool_not_granted"

    # cost unchanged
    await db_session.refresh(sess)
    assert sess.cost_total_usd == Decimal("0")


@pytest.mark.integration
async def test_r6_granted_intent_passes_through(db_session: AsyncSession) -> None:
    """R6: an intent that IS in the phase-grant set passes through."""
    from app.autonomous.guard import ToolResult, guarded_tool_call

    user = await _make_user(db_session)
    sess = await _make_session(
        db_session,
        user=user,
        current_phase="ethics_review",
        halt_state="running",
    )
    gateway = _StubGateway()

    result = await guarded_tool_call(
        sess,
        ToolIntent.emit_finding,
        {"finding": {"flag": "privilege_sensitive"}},
        db_session,
        gateway,
    )
    assert isinstance(result, ToolResult)
    assert result.data == {"flag": "privilege_sensitive"}


# ---------------------------------------------------------------------------
# Success path — propose_memory (Phase.drafting)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_success_propose_memory_writes_row_and_audits(
    db_session: AsyncSession,
) -> None:
    """propose_memory in Phase.drafting: DB row written, two audit rows, cost 0.

    Verifies:
    - A proposed autonomous_memory row is written with correct fields.
    - ToolResult.cost_usd == 0.
    - session.last_activity_at advanced (>= before the call).
    - Two tool_call audit rows: outcome='started' then outcome='success'.
    - cost_total_usd unchanged (zero cost).
    """
    from app.autonomous.guard import ToolResult, guarded_tool_call

    user = await _make_user(db_session)
    before_call = datetime.now(UTC)
    sess = await _make_session(
        db_session,
        user=user,
        current_phase="drafting",
        halt_state="running",
    )
    gateway = _StubGateway()

    result = await guarded_tool_call(
        sess,
        ToolIntent.propose_memory,
        {"category": "drafting_preference", "content": "User prefers Delaware governing law."},
        db_session,
        gateway,
    )

    assert isinstance(result, ToolResult)
    assert result.cost_usd == Decimal("0")
    assert "memory_id" in (result.data or {})

    # autonomous_memory row written
    mem_rows = (
        (
            await db_session.execute(
                select(AutonomousMemory)
                .where(AutonomousMemory.user_id == user.id)
                .where(AutonomousMemory.state == "proposed")
            )
        )
        .scalars()
        .all()
    )
    assert len(mem_rows) == 1
    mem = mem_rows[0]
    assert mem.category == "drafting_preference"
    assert mem.content == "User prefers Delaware governing law."
    assert mem.source_session_id == sess.id

    # last_activity_at advanced
    await db_session.refresh(sess)
    assert sess.last_activity_at >= before_call

    # two tool_call audit rows: started then success
    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.tool_call")
                .where(AuditLog.resource_id == str(sess.id))
                .order_by(AuditLog.timestamp)
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 2
    outcomes = [r.details["outcome"] for r in audit_rows]  # type: ignore[index]
    assert outcomes == ["started", "success"]

    # cost_total_usd unchanged
    assert sess.cost_total_usd == Decimal("0")


# ---------------------------------------------------------------------------
# Success path — notify (Phase.delivery)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_success_notify_writes_notification_row(db_session: AsyncSession) -> None:
    """notify in Phase.delivery: autonomous_notifications row written.

    Verifies:
    - ToolResult.cost_usd == 0 and data carries notification_id.
    - An in-app autonomous_notifications row exists with correct fields.
    """
    from app.autonomous.guard import ToolResult, guarded_tool_call

    user = await _make_user(db_session)
    sess = await _make_session(
        db_session,
        user=user,
        current_phase="delivery",
        halt_state="running",
    )
    gateway = _StubGateway()

    result = await guarded_tool_call(
        sess,
        ToolIntent.notify,
        {"title": "Review complete", "body": "2 findings flagged.", "payload": {"count": 2}},
        db_session,
        gateway,
    )

    assert isinstance(result, ToolResult)
    assert result.cost_usd == Decimal("0")
    assert "notification_id" in (result.data or {})

    notif_rows = (
        (
            await db_session.execute(
                select(AutonomousNotification)
                .where(AutonomousNotification.user_id == user.id)
                .where(AutonomousNotification.session_id == sess.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(notif_rows) == 1
    notif = notif_rows[0]
    assert notif.channel == "in_app"
    assert notif.title == "Review complete"
    assert notif.body == "2 findings flagged."
    assert notif.payload == {"count": 2}


# ---------------------------------------------------------------------------
# Success path — emit_finding (Phase.drafting)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_success_emit_finding_returns_data_no_db_row(
    db_session: AsyncSession,
) -> None:
    """emit_finding: the finding dict is echoed as data; no DB row written."""
    from app.autonomous.guard import ToolResult, guarded_tool_call

    user = await _make_user(db_session)
    sess = await _make_session(
        db_session,
        user=user,
        current_phase="drafting",
        halt_state="running",
    )
    gateway = _StubGateway()

    finding = {"clause": "limitation_of_liability", "severity": "high"}
    result = await guarded_tool_call(
        sess,
        ToolIntent.emit_finding,
        {"finding": finding},
        db_session,
        gateway,
    )

    assert isinstance(result, ToolResult)
    assert result.cost_usd == Decimal("0")
    assert result.data == finding

    # No autonomous_memory rows should have been written
    mem_rows = (
        (
            await db_session.execute(
                select(AutonomousMemory).where(AutonomousMemory.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(mem_rows) == 0


# ---------------------------------------------------------------------------
# Brake ordering: R5 fires before R6 fires before R4
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_r5_fires_before_r6(db_session: AsyncSession) -> None:
    """R5 (temporal) fires before R6 (contextual): halt_requested in wrong phase."""
    from app.errors import SessionHalted

    user = await _make_user(db_session)
    # ethics_review + retrieve_chunks would trip R6, but halt_requested trips R5 first
    sess = await _make_session(
        db_session,
        user=user,
        current_phase="ethics_review",
        halt_state="halt_requested",
    )
    await db_session.flush()
    gateway = _StubGateway()

    from app.autonomous import guard as guard_mod

    with pytest.raises(SessionHalted):
        await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.retrieve_chunks,
            {},
            db_session,
            gateway,
        )


@pytest.mark.integration
async def test_r6_fires_before_r4(db_session: AsyncSession) -> None:
    """R6 (contextual) fires before R4 (economic): wrong phase + over-budget."""
    from app.errors import ToolNotGranted

    user = await _make_user(db_session)
    # ethics_review + retrieve_chunks: R6 trips; R4 would also trip with cost mock
    sess = await _make_session(
        db_session,
        user=user,
        current_phase="ethics_review",
        halt_state="running",
        max_cost_usd=Decimal("0.01"),
        cost_total_usd=Decimal("0.009"),
    )
    gateway = _StubGateway()

    mock_estimate = AsyncMock(return_value=Decimal("0.05"))

    from app.autonomous import guard as guard_mod

    with (
        patch.object(guard_mod, "estimate_tool_cost", mock_estimate),
        pytest.raises(ToolNotGranted),
    ):
        await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.retrieve_chunks,  # not granted in ethics_review
            {"judge_model": "claude-haiku-4-5"},
            db_session,
            gateway,
        )


class _RaisingGateway:
    """Gateway whose chat_completion always raises a transport error."""

    async def chat_completion(self, request: object) -> object:
        from app.errors import GatewayTimeout

        raise GatewayTimeout("gateway did not respond")


@pytest.mark.integration
async def test_gateway_error_audited_as_gateway_error_not_success(
    db_session: AsyncSession,
) -> None:
    """An inference call that hits a gateway transport error is charged the R4
    estimate but audited with ``outcome="gateway_error"`` — never ``"success"``.

    Guards the transparency contract: the audit trail must not record a failed
    inference as a success.
    """
    from app.autonomous import guard as guard_mod
    from app.autonomous.guard import ToolResult

    user = await _make_user(db_session)
    sess = await _make_session(
        db_session,
        user=user,
        current_phase="analysis",  # grants run_skill
        halt_state="running",
        max_cost_usd=None,  # no cap → R4 never trips; the call reaches dispatch
        cost_total_usd=Decimal("0"),
    )
    gateway = _RaisingGateway()
    mock_estimate = AsyncMock(return_value=Decimal("0.02"))

    with patch.object(guard_mod, "estimate_tool_cost", mock_estimate):
        result = await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.run_skill,
            {"model": "smart", "messages": [{"role": "user", "content": "hi"}]},
            db_session,
            gateway,
        )

    # The call was attempted: charged the estimate, but outcome is honest.
    assert isinstance(result, ToolResult)
    assert result.outcome == "gateway_error"
    assert result.cost_usd == Decimal("0.02")
    assert sess.cost_total_usd == Decimal("0.02")

    # The success-side audit row records gateway_error, not success.
    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.tool_call")
                .where(AuditLog.resource_id == str(sess.id))
                .order_by(AuditLog.timestamp)
            )
        )
        .scalars()
        .all()
    )
    outcomes = [r.details["outcome"] for r in audit_rows]  # type: ignore[index]
    assert outcomes == ["started", "gateway_error"]
    assert "success" not in outcomes
