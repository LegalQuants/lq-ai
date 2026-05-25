"""Executor skeleton tests for the M4-A2 LangGraph phase machine.

Five contracts under test:

1. A session row drives the graph through all five phases in order
   (intake → analysis → drafting → ethics_review → delivery).

2. Each phase transition writes an ``autonomous_session.phase_transition``
   audit row — five rows per full run, in phase order.

3. The :func:`~app.autonomous.nodes.guarded_tool_call` stub raises
   :exc:`NotImplementedError`, proving no tool path bypasses the
   chokepoint-to-be (M4-A3).

4. :data:`~app.autonomous.enums.PHASE_GRANTS` contains exactly the
   grants specified in the M4-A2 task (pure unit test, no DB required).

5. A node returning ``{"error": ...}`` in LangGraph state results in
   ``status='failed'`` on the row (Critical-2 fix).

Tests run against the SAVEPOINT-rolled-back per-test session from
``tests/conftest.py``.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import PHASE_GRANTS, ToolIntent
from app.autonomous.executor import AutonomousExecutorError, run_autonomous_session
from app.autonomous.nodes import guarded_tool_call
from app.models.audit import AuditLog
from app.models.autonomous import AutonomousSession
from app.models.user import User
from app.schemas.autonomous import Phase
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


class _StubGateway:
    """Minimal gateway stub — no calls expected in the M4-A2 skeleton."""


# ---------------------------------------------------------------------------
# Unit tests (no DB)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_guarded_tool_call_stub_raises_not_implemented() -> None:
    """guarded_tool_call must raise NotImplementedError — M4-A3 replaces it."""
    with pytest.raises(NotImplementedError, match="guarded_tool_call lands in M4-A3"):
        guarded_tool_call("retrieve_chunks", document_id="some-id")


@pytest.mark.unit
def test_phase_grants_exact_membership() -> None:
    """PHASE_GRANTS must contain exactly the grants specified in the task."""
    assert PHASE_GRANTS[Phase.intake] == frozenset({ToolIntent.retrieve_chunks})

    assert PHASE_GRANTS[Phase.analysis] == frozenset(
        {
            ToolIntent.retrieve_chunks,
            ToolIntent.run_skill,
            ToolIntent.run_playbook,
        }
    )

    assert PHASE_GRANTS[Phase.drafting] == frozenset(
        {
            ToolIntent.run_skill,
            ToolIntent.emit_finding,
            ToolIntent.propose_memory,
        }
    )

    assert PHASE_GRANTS[Phase.ethics_review] == frozenset({ToolIntent.emit_finding})

    assert PHASE_GRANTS[Phase.delivery] == frozenset({ToolIntent.notify})


@pytest.mark.unit
def test_phase_grants_covers_all_phases() -> None:
    """Every Phase member has an entry in PHASE_GRANTS — no phase is uncovered."""
    for phase in Phase:
        assert phase in PHASE_GRANTS, f"Phase.{phase} missing from PHASE_GRANTS"


@pytest.mark.unit
def test_tool_intent_members() -> None:
    """ToolIntent has exactly the six members specified."""
    expected = {
        "retrieve_chunks",
        "run_skill",
        "run_playbook",
        "propose_memory",
        "emit_finding",
        "notify",
    }
    actual = {m.value for m in ToolIntent}
    assert actual == expected


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_executor_drives_all_five_phases(db_session: AsyncSession) -> None:
    """Happy-path: a session row drives the graph through all five phases.

    The commit-spy asserts that the delivery node COMMITS (Critical-1 fix).
    If you remove the ``await db.commit()`` from the delivery node, this test
    goes red because ``commit_call_count`` stays at 0.
    """
    user = await _make_user(db_session)
    session = AutonomousSession(user_id=user.id, trigger_kind="manual")
    db_session.add(session)
    await db_session.flush()

    gateway = _StubGateway()

    commit_call_count = 0
    _real_commit = db_session.commit

    async def _spy_commit() -> None:
        nonlocal commit_call_count
        commit_call_count += 1
        await _real_commit()

    with patch.object(db_session, "commit", side_effect=_spy_commit):
        await run_autonomous_session(
            db_session,
            session_id=session.id,
            gateway=gateway,  # type: ignore[arg-type]
        )

    await db_session.refresh(session)
    # Delivery node sets status = 'completed'.
    assert session.status == "completed"
    # Current phase is 'delivery' after the full run.
    assert session.current_phase == str(Phase.delivery)
    # completed_at must be populated on success (Important-4 fix).
    assert session.completed_at is not None, "completed_at must be set on successful run"
    # Commit must have been called at least once (Critical-1 fix).
    assert commit_call_count >= 1, (
        f"Expected db.commit() to be called at least once on success path, "
        f"got {commit_call_count} calls"
    )


@pytest.mark.integration
async def test_executor_writes_five_phase_transition_audit_rows(
    db_session: AsyncSession,
) -> None:
    """Each of the five phase transitions writes one audit row in phase order."""
    user = await _make_user(db_session)
    session = AutonomousSession(user_id=user.id, trigger_kind="manual")
    db_session.add(session)
    await db_session.flush()
    session_id_str = str(session.id)

    gateway = _StubGateway()

    await run_autonomous_session(
        db_session,
        session_id=session.id,
        gateway=gateway,  # type: ignore[arg-type]
    )

    # Query audit_log for all phase_transition rows for this session.
    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.phase_transition")
                .where(AuditLog.resource_id == session_id_str)
                .order_by(AuditLog.timestamp)
            )
        )
        .scalars()
        .all()
    )

    # Expect exactly 5 transition rows (one per phase).
    assert len(rows) == 5, f"Expected 5 audit rows, got {len(rows)}: {[r.details for r in rows]}"

    # Verify the phase order is preserved.
    expected_phases = [
        str(Phase.intake),
        str(Phase.analysis),
        str(Phase.drafting),
        str(Phase.ethics_review),
        str(Phase.delivery),
    ]
    actual_phases = [row.details["to_phase"] for row in rows]  # type: ignore[index]
    assert actual_phases == expected_phases, (
        f"Phase order mismatch: expected {expected_phases}, got {actual_phases}"
    )


@pytest.mark.integration
async def test_executor_audit_rows_carry_correct_resource_type(
    db_session: AsyncSession,
) -> None:
    """Audit rows have resource_type='autonomous_session'."""
    user = await _make_user(db_session)
    session = AutonomousSession(user_id=user.id, trigger_kind="schedule")
    db_session.add(session)
    await db_session.flush()

    gateway = _StubGateway()

    await run_autonomous_session(
        db_session,
        session_id=session.id,
        gateway=gateway,  # type: ignore[arg-type]
    )

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.phase_transition")
                .where(AuditLog.resource_id == str(session.id))
            )
        )
        .scalars()
        .all()
    )

    assert all(r.resource_type == "autonomous_session" for r in rows)
    assert all(r.user_id == user.id for r in rows)


@pytest.mark.integration
async def test_executor_raises_for_missing_session(db_session: AsyncSession) -> None:
    """AutonomousExecutorError raised when the session row does not exist."""
    missing_id = uuid.uuid4()
    gateway = _StubGateway()

    with pytest.raises(AutonomousExecutorError, match=str(missing_id)):
        await run_autonomous_session(
            db_session,
            session_id=missing_id,
            gateway=gateway,  # type: ignore[arg-type]
        )


@pytest.mark.integration
async def test_executor_persists_failed_status_on_mid_graph_error(
    db_session: AsyncSession,
) -> None:
    """An in-graph exception surfaces as status='failed' on the row."""
    user = await _make_user(db_session)
    session = AutonomousSession(user_id=user.id, trigger_kind="manual")
    db_session.add(session)
    await db_session.flush()

    # Monkey-patch the intake node factory to blow up mid-graph so we
    # can prove the executor catches and persists without re-raising.
    # We patch the name in executor's module namespace (where _build_graph
    # resolves it at call time) rather than in nodes, because the executor
    # module imports make_intake_node at load time.
    import app.autonomous.executor as executor_mod

    original_make_intake = executor_mod.make_intake_node

    def _exploding_intake(db):  # type: ignore[no-untyped-def]
        async def _node(state):  # type: ignore[no-untyped-def]
            raise RuntimeError("injected failure")

        return _node

    executor_mod.make_intake_node = _exploding_intake  # type: ignore[assignment]
    try:
        gateway = _StubGateway()
        # Should NOT raise — exception is caught and persisted.
        await run_autonomous_session(
            db_session,
            session_id=session.id,
            gateway=gateway,  # type: ignore[arg-type]
        )
    finally:
        executor_mod.make_intake_node = original_make_intake  # type: ignore[assignment]

    await db_session.refresh(session)
    assert session.status == "failed"
    assert session.error is not None
    assert "RuntimeError" in session.error


@pytest.mark.integration
async def test_executor_persists_failed_status_on_state_dict_error(
    db_session: AsyncSession,
) -> None:
    """Critical-2: when a node returns ``{"error": ...}`` into LangGraph state
    (without raising), the executor inspects the final state and persists
    ``status='failed'`` on the row.

    This path is distinct from the exception path: ``graph.ainvoke()``
    returns normally, so the ``except Exception`` handler never fires.
    Without the post-invoke error-state check the row stays at
    ``status='running'`` forever.
    """
    user = await _make_user(db_session)
    session = AutonomousSession(user_id=user.id, trigger_kind="manual")
    db_session.add(session)
    await db_session.flush()

    import app.autonomous.executor as executor_mod

    original_make_intake = executor_mod.make_intake_node

    def _error_state_intake(db):  # type: ignore[no-untyped-def]
        """Returns an error via state dict — does NOT raise."""

        async def _node(state):  # type: ignore[no-untyped-def]
            return {"error": "injected state-dict error"}

        return _node

    executor_mod.make_intake_node = _error_state_intake  # type: ignore[assignment]
    try:
        gateway = _StubGateway()
        # Should NOT raise — state-dict errors are handled by the executor.
        await run_autonomous_session(
            db_session,
            session_id=session.id,
            gateway=gateway,  # type: ignore[arg-type]
        )
    finally:
        executor_mod.make_intake_node = original_make_intake  # type: ignore[assignment]

    await db_session.refresh(session)
    assert session.status == "failed", (
        f"Expected status='failed' after state-dict error, got '{session.status}'"
    )
    assert session.error is not None
    assert "injected state-dict error" in session.error
    assert session.completed_at is not None, "completed_at must be set on the error state-dict path"
