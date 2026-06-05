"""Chokepoint persistence tests for the emit_finding handler — Task 1.

The ``emit_finding`` chokepoint persists one ``autonomous_findings`` row
per finding (the run's core work-product), in addition to the existing
transient state echo. Covers:

- Happy path: a complete finding dict persists severity/title/content
  verbatim against the emitting session, and the result echoes the
  finding plus the new ``finding_id``.
- Defensive path: a finding dict missing ``summary``/``title``/
  ``severity`` persists with the defaults ("(untitled)" / "" / "info")
  rather than crashing on the non-null DB columns.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import PHASE_GRANTS, ToolIntent
from app.autonomous.guard import guarded_tool_call
from app.models.autonomous import AutonomousFinding, AutonomousSession
from app.models.user import User
from app.security import hash_password


class _StubGateway:
    """emit_finding is local/zero-cost; the gateway is never touched."""


def _granting_phase() -> str:
    """A phase whose grant set includes emit_finding (e.g. ethics_review)."""
    phase = next(
        (p for p, grants in PHASE_GRANTS.items() if ToolIntent.emit_finding in grants),
        None,
    )
    assert phase is not None, "emit_finding must be granted in at least one phase"
    return str(phase)


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"find-test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_session(db: AsyncSession, *, user: User) -> AutonomousSession:
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="manual",
        status="running",
        halt_state="running",
        current_phase=_granting_phase(),
    )
    db.add(sess)
    await db.flush()
    await db.refresh(sess)
    return sess


@pytest.mark.integration
async def test_emit_finding_persists_row(db_session: AsyncSession) -> None:
    """A complete finding persists severity/title/content for the session."""
    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user)

    result = await guarded_tool_call(
        sess,
        ToolIntent.emit_finding,
        {"finding": {"title": "T", "summary": "S", "severity": "warn"}},
        db_session,
        _StubGateway(),
    )

    rows = (
        (
            await db_session.execute(
                select(AutonomousFinding).where(AutonomousFinding.session_id == sess.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.session_id == sess.id
    assert row.severity == "warn"
    assert row.title == "T"
    assert row.content == "S"

    # The chokepoint echoes the finding plus the new row id.
    assert result.data["title"] == "T"
    assert result.data["finding_id"] == str(row.id)


@pytest.mark.integration
async def test_emit_finding_defensive_defaults(db_session: AsyncSession) -> None:
    """A finding missing every key persists with defaults, no crash."""
    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user)

    result = await guarded_tool_call(
        sess,
        ToolIntent.emit_finding,
        {"finding": {}},
        db_session,
        _StubGateway(),
    )

    row = (
        await db_session.execute(
            select(AutonomousFinding).where(AutonomousFinding.session_id == sess.id)
        )
    ).scalar_one()
    assert row.severity == "info"
    assert row.title == "(untitled)"
    assert row.content == ""
    assert result.data["finding_id"] == str(row.id)


@pytest.mark.integration
async def test_finding_cascade_deletes_with_session(db_session: AsyncSession) -> None:
    """Deleting the owning session cascades and removes its findings."""
    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user)
    session_id = sess.id

    await guarded_tool_call(
        sess,
        ToolIntent.emit_finding,
        {"finding": {"title": "T", "summary": "S", "severity": "warn"}},
        db_session,
        _StubGateway(),
    )

    # Sanity: the finding is present before the cascade.
    before = (
        (
            await db_session.execute(
                select(AutonomousFinding).where(AutonomousFinding.session_id == session_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(before) == 1

    # Delete the owning session in the same session so the DB cascade fires.
    await db_session.delete(sess)
    await db_session.commit()

    after = (
        (
            await db_session.execute(
                select(AutonomousFinding).where(AutonomousFinding.session_id == session_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(after) == 0


@pytest.mark.integration
async def test_findings_do_not_dedup(db_session: AsyncSession) -> None:
    """Two emitted findings persist as two rows — findings never upsert."""
    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user)

    await guarded_tool_call(
        sess,
        ToolIntent.emit_finding,
        {"finding": {"title": "First", "summary": "S1", "severity": "warn"}},
        db_session,
        _StubGateway(),
    )
    await guarded_tool_call(
        sess,
        ToolIntent.emit_finding,
        {"finding": {"title": "Second", "summary": "S2", "severity": "critical"}},
        db_session,
        _StubGateway(),
    )

    rows = (
        (
            await db_session.execute(
                select(AutonomousFinding).where(AutonomousFinding.session_id == sess.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {r.title for r in rows} == {"First", "Second"}
