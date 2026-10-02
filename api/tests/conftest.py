"""Pytest fixtures for the LQ.AI api/ tests.

Implements the test DB strategy locked in CONTRIBUTING.md:

- session-scoped fixture: creates a fresh per-run database, runs Alembic
  migrations against it once
- per-test fixture: opens a connection, BEGIN, yields an AsyncSession,
  ROLLBACK on teardown — so each test starts from the migrated baseline
  with no leakage from prior tests

Test database name pattern: lq_ai_test_<random_hex_8>. Created from a
connection to the default `postgres` database; dropped at session teardown.

Required env var: DATABASE_URL (asyncpg form, e.g.,
postgresql+asyncpg://user:pass@host:5432/db). The fixture derives the
admin URL by swapping the database name to `postgres`.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, SessionTransaction

API_DIR = Path(__file__).resolve().parent.parent


def _split_url(url: str) -> tuple[str, str]:
    """Split a SQLAlchemy URL into (prefix-without-db, db-name)."""
    base, dbname = url.rsplit("/", 1)
    return base, dbname


@pytest_asyncio.fixture(scope="session")
async def test_db_url() -> AsyncIterator[str]:
    """Create a fresh per-run test database; drop it at session teardown.

    Yields the asyncpg URL to the test database.
    """
    runtime_url = os.environ.get("DATABASE_URL")
    if not runtime_url:
        pytest.skip(
            "DATABASE_URL not set; skipping integration tests. "
            "Set DATABASE_URL=postgresql+asyncpg://... before running pytest."
        )

    base, _orig_db = _split_url(runtime_url)
    test_db = f"lq_ai_test_{secrets.token_hex(4)}"
    admin_url = f"{base}/postgres"
    test_url = f"{base}/{test_db}"

    # Create the test database
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{test_db}"'))
    await admin_engine.dispose()

    try:
        yield test_url
    finally:
        # Drop the test database. Force-disconnect any lingering sessions.
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": test_db},
            )
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db}"'))
        await admin_engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def test_engine(test_db_url: str) -> AsyncIterator[AsyncEngine]:
    """Run Alembic migrations against the test DB; yield an engine bound to it."""
    # Run migrations via Alembic. Alembic uses sync drivers internally;
    # convert the asyncpg URL to plain postgresql:// for the alembic command.
    sync_url = test_db_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    alembic_cfg = Config(str(API_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(API_DIR / "alembic"))

    # env.py reads DATABASE_URL from the environment; temporarily swap it
    # to point at the test database for this migration run.
    saved = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = sync_url
    try:
        # Alembic is sync — run in a thread to avoid blocking the event loop
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    finally:
        if saved is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = saved

    engine = create_async_engine(test_db_url, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Per-test ORM session with full transaction-rollback isolation.

    Pattern: open a connection, start an outer transaction, start a nested
    SAVEPOINT, bind the session to it. When the test calls session.rollback()
    (e.g., to recover from an IntegrityError raised by pytest.raises), the
    SAVEPOINT rolls back but the outer transaction stays alive — and a
    listener restarts the SAVEPOINT so the session can keep going. At
    teardown, the outer transaction is rolled back, undoing everything.

    This is SQLAlchemy's canonical "join an external transaction" recipe:
      https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites
    """
    from sqlalchemy import event

    async with test_engine.connect() as conn:
        outer = await conn.begin()
        await conn.begin_nested()  # Initial SAVEPOINT

        session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )

        @event.listens_for(session.sync_session, "after_transaction_end")
        def restart_savepoint(sess: Session, trans: SessionTransaction) -> None:
            # When the inner SAVEPOINT ends (either commit or rollback),
            # immediately start a new one so the session can keep working.
            if trans.nested and trans.parent is not None and not trans.parent.nested:
                assert conn.sync_connection is not None
                conn.sync_connection.begin_nested()

        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


@pytest_asyncio.fixture
async def db_connection(test_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Bare connection for tests that need raw SQL outside the ORM session."""
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()
