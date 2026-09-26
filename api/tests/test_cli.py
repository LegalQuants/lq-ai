"""Tests for the operational CLI (`python -m app.cli`).

The reset-admin-password subcommand is the B2 deferred-item we landed in
this task. It's an asyncio entry point that uses its own engine to talk
to the same database the API uses; here we verify the happy path and
the error branches against the test DB.

The CLI builds its own engine via `create_async_engine(settings.database_url)`,
so we point `DATABASE_URL` at the per-run test database and let the
function execute end-to-end. We don't go through the SAVEPOINT-rolled
session — the CLI commits, and the test database is dropped at session
teardown anyway.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.cli import _reset_admin_password
from app.config import get_settings
from app.models.user import User, UserSession
from app.security import hash_password, verify_password


@pytest_asyncio.fixture
async def cli_db_url(test_db_url: str, test_engine: AsyncEngine) -> AsyncIterator[str]:
    """Point the CLI's settings at the test DB by overriding env + cache.

    Depends on `test_engine` so Alembic migrations run before the CLI talks
    to the DB; without it the `users` table wouldn't exist yet.

    The CLI calls `get_settings()` which reads `DATABASE_URL` from env at
    instantiation; we set it before invocation and restore after.
    """
    saved = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_db_url
    get_settings.cache_clear()
    try:
        yield test_db_url
    finally:
        if saved is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = saved
        get_settings.cache_clear()


async def _seed_admin(test_db_url: str, email: str, plaintext: str) -> None:
    """Insert an admin row using a separate session (not the CLI's)."""
    engine = create_async_engine(test_db_url, future=True)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as s:
            s.add(
                User(
                    email=email,
                    hashed_password=hash_password(plaintext),
                    is_admin=True,
                    mfa_enabled=False,
                    must_change_password=False,
                )
            )
            await s.commit()
    finally:
        await engine.dispose()


async def _cleanup_users(test_db_url: str) -> None:
    """Wipe users between CLI tests so they don't pollute each other.

    The CLI commits, so we must clean up explicitly — the per-test
    SAVEPOINT rollback fixture doesn't help here.
    """
    engine = create_async_engine(test_db_url, future=True, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("DELETE FROM user_sessions"))
            await conn.execute(text("DELETE FROM users"))
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_reset_admin_password_happy_path(
    cli_db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reset against the single existing admin: returns 0, prints new password, sets flag."""
    email = f"admin-{uuid.uuid4().hex[:8]}@lq.ai"
    await _seed_admin(cli_db_url, email, "OldOldOldOldOld!")
    try:
        rc = await _reset_admin_password(email=None)
        assert rc == 0
        captured = capsys.readouterr().out
        assert email in captured
        assert "must_change_password is now true" in captured

        # Verify state in DB.
        engine = create_async_engine(cli_db_url, future=True)
        factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as s:
            row = (await s.execute(select(User).where(User.email == email))).scalar_one()
            assert row.must_change_password is True
            # Old password no longer verifies.
            assert verify_password("OldOldOldOldOld!", row.hashed_password) is False
        await engine.dispose()
    finally:
        await _cleanup_users(cli_db_url)


@pytest.mark.integration
async def test_reset_admin_password_no_admin_exists_returns_2(
    cli_db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """No admin in DB → exit code 2 with a clear message."""
    await _cleanup_users(cli_db_url)
    rc = await _reset_admin_password(email=None)
    assert rc == 2
    err = capsys.readouterr().err
    assert "no admin user exists" in err


@pytest.mark.integration
async def test_reset_admin_password_with_explicit_email_for_missing_user_returns_2(
    cli_db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """--email pointing at a nonexistent user → exit code 2."""
    await _cleanup_users(cli_db_url)
    rc = await _reset_admin_password(email="missing@example.com")
    assert rc == 2
    err = capsys.readouterr().err
    assert "no user found" in err


@pytest.mark.integration
async def test_reset_admin_password_multiple_admins_requires_email(
    cli_db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two admins → exit code 2 with a list and a request for --email."""
    e1 = f"a1-{uuid.uuid4().hex[:8]}@lq.ai"
    e2 = f"a2-{uuid.uuid4().hex[:8]}@lq.ai"
    await _seed_admin(cli_db_url, e1, "PasswordOne1234!")
    await _seed_admin(cli_db_url, e2, "PasswordTwo1234!")
    try:
        rc = await _reset_admin_password(email=None)
        assert rc == 2
        err = capsys.readouterr().err
        assert "multiple admin users" in err
        assert e1 in err and e2 in err
    finally:
        await _cleanup_users(cli_db_url)


@pytest.mark.integration
async def test_reset_admin_password_with_explicit_password_sets_it(
    cli_db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """--password sets the supplied value (not a generated one) and does not echo it."""
    email = f"admin-{uuid.uuid4().hex[:8]}@lq.ai"
    await _seed_admin(cli_db_url, email, "OldOldOldOldOld!")
    supplied = "FixtureSeedPw2026!"
    try:
        rc = await _reset_admin_password(email=email, password=supplied)
        assert rc == 0

        # Don't echo the supplied password into stdout.
        captured = capsys.readouterr().out
        assert supplied not in captured
        assert "supplied value" in captured

        # The supplied value verifies; the old one does not.
        engine = create_async_engine(cli_db_url, future=True)
        factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as s:
            row = (await s.execute(select(User).where(User.email == email))).scalar_one()
            assert verify_password(supplied, row.hashed_password) is True
            assert verify_password("OldOldOldOldOld!", row.hashed_password) is False
            # Default still forces a change.
            assert row.must_change_password is True
        await engine.dispose()
    finally:
        await _cleanup_users(cli_db_url)


@pytest.mark.integration
async def test_reset_admin_password_no_force_change_leaves_flag_false(
    cli_db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """--password + --no-force-change produces a login-ready fixture state."""
    email = f"admin-{uuid.uuid4().hex[:8]}@lq.ai"
    await _seed_admin(cli_db_url, email, "OldOldOldOldOld!")
    supplied = "FixtureSeedPw2026!"
    try:
        rc = await _reset_admin_password(email=email, password=supplied, force_change=False)
        assert rc == 0

        captured = capsys.readouterr().out
        assert "must_change_password is now false" in captured

        engine = create_async_engine(cli_db_url, future=True)
        factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as s:
            row = (await s.execute(select(User).where(User.email == email))).scalar_one()
            assert row.must_change_password is False
            assert verify_password(supplied, row.hashed_password) is True
        await engine.dispose()
    finally:
        await _cleanup_users(cli_db_url)


@pytest.mark.integration
async def test_reset_admin_password_rejects_short_explicit_password(
    cli_db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """--password shorter than password_min_length returns 2 without touching state."""
    email = f"admin-{uuid.uuid4().hex[:8]}@lq.ai"
    await _seed_admin(cli_db_url, email, "OldOldOldOldOld!")
    try:
        rc = await _reset_admin_password(email=email, password="short")
        assert rc == 2
        err = capsys.readouterr().err
        assert "shorter than the configured minimum" in err

        # Old password still works — DB was not touched.
        engine = create_async_engine(cli_db_url, future=True)
        factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as s:
            row = (await s.execute(select(User).where(User.email == email))).scalar_one()
            assert verify_password("OldOldOldOldOld!", row.hashed_password) is True
        await engine.dispose()
    finally:
        await _cleanup_users(cli_db_url)


@pytest.mark.integration
async def test_reset_admin_password_revokes_active_sessions(cli_db_url: str) -> None:
    """Reset revokes any active sessions for the targeted user."""
    email = f"admin-{uuid.uuid4().hex[:8]}@lq.ai"
    await _seed_admin(cli_db_url, email, "OldPasswordABCDE!")

    # Insert an active session row by hand.
    engine = create_async_engine(cli_db_url, future=True)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as s:
            from datetime import UTC, datetime, timedelta

            user = (await s.execute(select(User).where(User.email == email))).scalar_one()
            now = datetime.now(tz=UTC)
            s.add(
                UserSession(
                    user_id=user.id,
                    refresh_token_hash="dummy-hash",
                    expires_at=now + timedelta(days=7),
                    absolute_expires_at=now + timedelta(hours=8),
                    last_active_at=now,
                )
            )
            await s.commit()

        rc = await _reset_admin_password(email=email)
        assert rc == 0

        async with factory() as s:
            sessions = (
                (await s.execute(select(UserSession).where(UserSession.user_id == user.id)))
                .scalars()
                .all()
            )
            assert len(sessions) == 1
            assert sessions[0].revoked_at is not None
    finally:
        await engine.dispose()
        await _cleanup_users(cli_db_url)


@pytest.mark.integration
async def test_reset_admin_password_bumps_token_epoch(cli_db_url: str) -> None:
    """Reset is the compromise-recovery path: outstanding access tokens must die
    too, not just refresh sessions (pen-test finding jwt#F-B)."""
    email = f"admin-{uuid.uuid4().hex[:8]}@lq.ai"
    await _seed_admin(cli_db_url, email, "OldPasswordABCDE!")

    engine = create_async_engine(cli_db_url, future=True)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as s:
            before = (
                await s.execute(select(User.token_epoch).where(User.email == email))
            ).scalar_one()

        assert await _reset_admin_password(email=email) == 0

        async with factory() as s:
            after = (
                await s.execute(select(User.token_epoch).where(User.email == email))
            ).scalar_one()
        assert after == before + 1
    finally:
        await engine.dispose()
        await _cleanup_users(cli_db_url)
