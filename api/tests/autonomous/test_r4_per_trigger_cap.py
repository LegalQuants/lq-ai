"""M4 Task 16 — R4 live-trips on a low per-trigger ``max_cost_usd``.

End-to-end verification of the production-shape spawn → run chain:

1. A :class:`~app.models.autonomous.AutonomousWatch` is created with
   ``max_cost_usd=Decimal("0.001")`` and ``skill_ref="alpha-test-skill"``.
2. :func:`~app.autonomous.watch_trigger.fire_watches_for_kb` spawns a
   session that inherits that cap (Task 5 wiring).
3. :func:`~app.autonomous.executor.run_autonomous_session` runs the graph.
   The analysis node assembles the skill prompt and reaches the
   ``run_skill`` chokepoint, where R4 (the economic brake) computes the
   PRE-CALL estimate. With ``DEFAULT_PER_JUDGE_USD == $0.005`` (cost.py)
   the projected total exceeds $0.001, so R4 latches ``cost_cap_reached``
   and raises :exc:`~app.errors.CostCapReached` BEFORE the gateway is
   ever awaited.

This complements the in-isolation brake unit tests (``test_brakes.py``):
those exercise ``guarded_tool_call`` directly with a mocked estimate;
this drives the real trigger → session → executor → R4 chain.

R4 is a PRE-CALL brake — the mock gateway's ``chat_completion`` is a
required arg but is never awaited (the estimate trips first). The test
asserts exactly that.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.executor import run_autonomous_session
from app.autonomous.watch_trigger import fire_watches_for_kb
from app.models.autonomous import AutonomousSession, AutonomousWatch
from app.models.user import User
from app.security import hash_password
from tests.autonomous.conftest import KbOneFile

# ``alpha-test-skill`` is the fixture skill installed into
# ``app.state.skill_registry`` by the ``_installed_skill_registry``
# fixture (conftest ``_FIXTURE_SKILL_REF``).  The watch's skill_ref must
# match so analysis-node prompt assembly resolves and the run reaches the
# run_skill chokepoint.
_FIXTURE_SKILL_REF = "alpha-test-skill"


async def _make_opted_in_user(db: AsyncSession) -> User:
    """Create a user with ``autonomous_enabled=True``.

    ``fire_watches_for_kb`` joins on ``User.autonomous_enabled.is_(True)``
    — a non-opted-in user's watch never fires.  Mirrors the proven helper
    in ``test_spawn_max_cost_usd.py``.
    """
    user = User(
        email=f"r4-cap-test-{uuid.uuid4().hex[:8]}@example.com",
        display_name="R4 Per-Trigger Cap Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.mark.integration
async def test_r4_trips_on_low_per_trigger_max_cost_usd(
    db_session: AsyncSession,
    kb_with_one_indexed_file: KbOneFile,
    _installed_skill_registry: None,
) -> None:
    """A watch with max_cost_usd=$0.001 → spawned session inherits it →
    analysis-node run_skill call's R4 brake latches cost_cap_reached →
    session halts → receipt terminal_reason == 'cost_cap_reached'.

    The mock gateway's chat_completion must NOT be awaited: R4 is a
    pre-call brake that trips on the estimate, before dispatch.
    """
    kb = kb_with_one_indexed_file
    opted_in_user = await _make_opted_in_user(db_session)

    watch = AutonomousWatch(
        user_id=opted_in_user.id,
        knowledge_base_id=kb.kb_id,
        enabled=True,
        skill_ref=_FIXTURE_SKILL_REF,
        max_cost_usd=Decimal("0.001"),
    )
    db_session.add(watch)
    await db_session.flush()

    # Fire the watch with a stub enqueue so it never hits real arq.
    enqueue = AsyncMock(return_value=True)
    count = await fire_watches_for_kb(
        db_session, kb_id=kb.kb_id, file_id=kb.file_id, enqueue=enqueue
    )
    assert count == 1, "the opted-in watch on this KB should have fired"

    # Locate the spawned session by its trigger linkage.
    session = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.trigger_ref == watch.id)
        )
    ).scalar_one()
    assert session.trigger_kind == "watch"
    assert session.max_cost_usd == Decimal("0.001"), "session must inherit the per-trigger cap"

    # Mock gateway: chat_completion is a required arg but R4 trips pre-call,
    # so it should never be awaited.  A realistic usage payload is provided
    # only so a (wrongly) reached dispatch wouldn't crash on attribute access.
    gateway = AsyncMock()
    gateway.chat_completion = AsyncMock(
        return_value=type(
            "R",
            (),
            {
                "choices": [type("C", (), {"message": type("M", (), {"content": "{}"})()})()],
                "usage": type("U", (), {"prompt_tokens": 5000, "completion_tokens": 2000})(),
            },
        )()
    )

    await run_autonomous_session(db_session, session_id=session.id, gateway=gateway)

    await db_session.refresh(session)
    assert session.cost_cap_reached is True
    assert session.halt_state == "halted"

    # R4 is a PRE-CALL brake: the estimate trips before dispatch, so the
    # gateway inference is never awaited.
    gateway.chat_completion.assert_not_awaited()


@pytest.mark.integration
async def test_r4_halt_populates_receipt_terminal_reason(
    db_session: AsyncSession,
    kb_with_one_indexed_file: KbOneFile,
    _installed_skill_registry: None,
) -> None:
    """A cost-cap-halted session's receipt should carry
    terminal_reason='cost_cap_reached'.

    The executor's `except AutonomousBrake` handler now calls build_receipt on
    the halted path (the chokepoint already flushed the terminal audit row, so
    terminal_reason derives correctly). This pins design §10's intended
    brake-halted receipt behavior. The gap documented at Task 16 is now closed.
    """
    kb = kb_with_one_indexed_file
    opted_in_user = await _make_opted_in_user(db_session)

    watch = AutonomousWatch(
        user_id=opted_in_user.id,
        knowledge_base_id=kb.kb_id,
        enabled=True,
        skill_ref=_FIXTURE_SKILL_REF,
        max_cost_usd=Decimal("0.001"),
    )
    db_session.add(watch)
    await db_session.flush()

    enqueue = AsyncMock(return_value=True)
    await fire_watches_for_kb(db_session, kb_id=kb.kb_id, file_id=kb.file_id, enqueue=enqueue)

    session = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.trigger_ref == watch.id)
        )
    ).scalar_one()

    gateway = AsyncMock()
    gateway.chat_completion = AsyncMock(
        return_value=type(
            "R",
            (),
            {
                "choices": [type("C", (), {"message": type("M", (), {"content": "{}"})()})()],
                "usage": type("U", (), {"prompt_tokens": 5000, "completion_tokens": 2000})(),
            },
        )()
    )

    await run_autonomous_session(db_session, session_id=session.id, gateway=gateway)
    await db_session.refresh(session)

    receipt = session.result
    assert receipt is not None
    assert receipt["terminal_reason"] == "cost_cap_reached"
