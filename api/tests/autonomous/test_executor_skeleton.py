"""Executor tests for the LangGraph phase machine + chokepoint invariant.

The nodes now do real work (M4-D2): analysis runs inference, drafting emits
findings through the chokepoint, ethics_review emits its own findings, and
delivery notifies and builds the receipt.  These tests pin the structural
contracts of the phase machine and the chokepoint, *not* the real-work content
itself — that is covered by the gateway-error / R4 / real-work test files.

The happy-path integration tests here use a **manual** session with no
``skill_ref`` configured.  That deliberately drives analysis down the
no-inference-target / unstructured-fallback path, so a bare ``_StubGateway``
(no ``chat_completion``) suffices: analysis makes no gateway call because no
inference target is configured, while drafting / ethics_review / delivery still
exercise the real ``emit_finding`` and ``notify`` chokepoint paths (which do not
touch the gateway).  This isolates the phase machine + the no-target path from
gateway behaviour; the gateway-call paths are exercised elsewhere.

Contracts under test:

1. A session row drives the graph through all five phases in order
   (intake → analysis → drafting → ethics_review → delivery).

2. Each phase transition writes an ``autonomous_session.phase_transition``
   audit row — five rows per full run, in phase order.

3. The real :func:`~app.autonomous.guard.guarded_tool_call` is importable
   from :mod:`app.autonomous.guard`; the old stub is removed from
   :mod:`app.autonomous.nodes`.

4. :data:`~app.autonomous.enums.PHASE_GRANTS` contains exactly the
   grants specified (pure unit test, no DB required).

5. A node returning ``{"error": ...}`` in LangGraph state results in
   ``status='failed'`` on the row (Critical-2 fix).

6. The chokepoint invariant: every ``autonomous_session.tool_call`` audit
   row carries a recognized ``ToolIntent`` value and a recognized outcome,
   proving no tool reaches the audit log except via ``guarded_tool_call``.

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
from app.autonomous.guard import guarded_tool_call
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
    """Minimal gateway stub with no ``chat_completion``.

    Sufficient for the manual-session happy path: with no ``skill_ref`` on the
    session, analysis takes the no-inference-target / unstructured-fallback path
    and never calls the gateway.  The remaining real-work paths exercised here
    (drafting / ethics_review ``emit_finding`` + delivery ``notify``) go through
    the chokepoint but do not touch the gateway, so this stub is enough.  Tests
    that need a real inference response use a richer fake elsewhere.
    """


# ---------------------------------------------------------------------------
# Unit tests (no DB)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_guarded_tool_call_importable_from_guard() -> None:
    """guarded_tool_call is the real implementation from app.autonomous.guard.

    A3.3b replaced the M4-A2 stub in nodes.py with an import of the real
    chokepoint from guard.py.  Verify the callable is importable and is a
    coroutine function (i.e. the real async implementation, not the old
    sync stub).
    """
    import inspect

    assert inspect.iscoroutinefunction(guarded_tool_call), (
        "guarded_tool_call must be an async coroutine function (the real A3.3b implementation)"
    )


@pytest.mark.unit
def test_phase_grants_exact_membership() -> None:
    """PHASE_GRANTS must contain exactly the grants specified in the task."""
    assert PHASE_GRANTS[Phase.intake] == frozenset({ToolIntent.retrieve_chunks})

    assert PHASE_GRANTS[Phase.analysis] == frozenset(
        {
            ToolIntent.retrieve_chunks,
            ToolIntent.run_skill,
            ToolIntent.run_playbook,
            # M4-B2: propose_precedent granted at analysis (patterns observed
            # while reading docs).
            ToolIntent.propose_precedent,
        }
    )

    assert PHASE_GRANTS[Phase.drafting] == frozenset(
        {
            ToolIntent.run_skill,
            ToolIntent.emit_finding,
            ToolIntent.propose_memory,
            # M4-B2: propose_precedent granted at drafting (patterns recognized
            # during synthesis).
            ToolIntent.propose_precedent,
            # Donna #8: emit_artifact granted at drafting ONLY (the memo is
            # synthesized work product).
            ToolIntent.emit_artifact,
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
    """ToolIntent has exactly the eight members specified (M4-B2 adds
    propose_precedent; Donna #8 adds emit_artifact)."""
    expected = {
        "retrieve_chunks",
        "run_skill",
        "run_playbook",
        "propose_memory",
        "propose_precedent",
        "emit_finding",
        "emit_artifact",
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

    def _exploding_intake(db, gateway=None):  # type: ignore[no-untyped-def]
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

    def _error_state_intake(db, gateway=None):  # type: ignore[no-untyped-def]
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


@pytest.mark.integration
async def test_no_tool_call_bypasses_chokepoint(db_session: AsyncSession) -> None:
    """Invariant: every ``tool_call`` audit row went through the chokepoint.

    A full manual session emits findings (drafting + ethics_review) and notifies
    (delivery) — each through :func:`~app.autonomous.guard.guarded_tool_call`.
    The chokepoint is the *only* code path that writes an
    ``autonomous_session.tool_call`` audit row, and it always stamps the row's
    ``details`` with a ``tool`` (a :class:`ToolIntent` value) and an ``outcome``.

    So if we query *all* ``tool_call`` rows for the session and every one carries
    a recognized ``ToolIntent`` + a recognized outcome, no tool reached the audit
    log except through the chokepoint — which is the invariant this file's name
    promises.
    """
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

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.tool_call")
                .where(AuditLog.resource_id == session_id_str)
                .order_by(AuditLog.timestamp)
            )
        )
        .scalars()
        .all()
    )

    # Not vacuously true: the session must produce at least one tool_call row.
    assert len(rows) >= 1, "expected at least one tool_call audit row for a full session"

    # Recognized intents: the full ToolIntent enum (the chokepoint only ever
    # stamps a valid ToolIntent value as details["tool"]).
    recognized_intents = {t.value for t in ToolIntent}

    # Recognized outcomes for an ``autonomous_session.tool_call`` row.  Sourced
    # from the only call sites that write a tool_call row in
    # app/autonomous/guard.py (grep: 'outcome=' inside guarded_tool_call):
    #   - "tool_not_granted"  (R6 grant rejection, line ~193)
    #   - "started"           (pre-dispatch marker, line ~225)
    #   - result.outcome      (post-dispatch, line ~245): ToolResult.outcome
    #     defaults to "success" and is set to "gateway_error" on the two
    #     inference-failure paths (lines ~790/819).
    # The cost_cap_reached / external_halt outcomes live on *other* audit
    # actions ("cost_cap_reached" / "halted"), not on tool_call rows, so they
    # are intentionally excluded from this set.
    recognized_outcomes = {"started", "success", "gateway_error", "tool_not_granted"}

    for row in rows:
        details = row.details
        assert details is not None, f"tool_call row {row.id} has no details"
        tool = details["tool"]
        outcome = details["outcome"]
        assert tool in recognized_intents, (
            f"tool_call row {row.id} carries unrecognized tool {tool!r}; "
            f"a tool_call row not produced by the chokepoint would not match a ToolIntent"
        )
        assert outcome in recognized_outcomes, (
            f"tool_call row {row.id} carries unrecognized outcome {outcome!r}; "
            f"expected one of {sorted(recognized_outcomes)}"
        )
