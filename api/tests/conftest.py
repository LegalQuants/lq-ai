"""Pytest fixtures for the LQ.AI api/ tests.

Implements the test DB strategy locked in CONTRIBUTING.md:

- session-scoped fixture: creates a fresh per-run database, runs Alembic
  migrations against it once
- per-test fixture: opens a connection, BEGIN, yields an AsyncSession,
  ROLLBACK on teardown — so each test starts from the migrated baseline
  with no leakage from prior tests
- after migrating, a copy of the migrated database is kept as a template, so
  a test whose code commits through its own engine and reads global state
  can take a fresh database of its own (``isolated_db_url``)
- arq's pool creation fails at once (``_arq_unreachable``): no Redis runs in
  the test environment, and arq's retries otherwise cost ~5 s per enqueue
- bcrypt hashes at its minimum cost (``BCRYPT_ROUNDS=4``) unless the
  environment sets one: at the production default each hash takes ~0.2 s

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
from typing import TYPE_CHECKING, NoReturn

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

# The suite hashes passwords, refresh tokens and MFA recovery codes thousands
# of times (an MFA enrollment alone hashes ten codes), and at the production
# cost of 12 each bcrypt hash or check takes ~0.2 s. Cost 4 is bcrypt's
# minimum. Verification follows whatever cost a hash was minted with, so the
# code under test is the same; only the work factor differs, as the
# ``bcrypt_rounds`` setting allows for CI. Set before any test imports
# ``app.config``, so the cached settings see it.
os.environ.setdefault("BCRYPT_ROUNDS", "4")


def _split_url(url: str) -> tuple[str, str]:
    """Split a SQLAlchemy URL into (prefix-without-db, db-name)."""
    base, dbname = url.rsplit("/", 1)
    return base, dbname


async def _create_database(base: str, name: str, template: str | None = None) -> None:
    """Create ``name`` on the server at ``base``, optionally copied from ``template``."""
    admin_engine = create_async_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            clause = f' TEMPLATE "{template}"' if template else ""
            await conn.execute(text(f'CREATE DATABASE "{name}"{clause}'))
    finally:
        await admin_engine.dispose()


async def _drop_database(base: str, name: str) -> None:
    """Drop ``name``, force-disconnecting any lingering sessions first."""
    admin_engine = create_async_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": name},
            )
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        await admin_engine.dispose()


@pytest.fixture(autouse=True)
def _arq_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make arq's pool creation fail at once instead of retrying for ~5 s.

    No Redis runs in the test environment, locally or in CI's API job. arq's
    ``create_pool`` defaults to five connection retries a second apart, and
    ``app.workers.queue`` keeps a pool only once one connects, so every
    enqueue in a test waited about five seconds before the helper logged its
    warning and returned False. Raising the same error at once keeps that
    failure path and drops the wait. A test that needs a working pool patches
    ``app.workers.queue._get_pool`` / ``_get_m3a6_pool`` or the enqueue helper,
    as before; those patches sit above this one.
    """
    import arq
    from redis.exceptions import ConnectionError as RedisConnectionError

    async def _refuse(*_args: object, **_kwargs: object) -> NoReturn:
        raise RedisConnectionError("arq has no Redis in the test environment")

    monkeypatch.setattr(arq, "create_pool", _refuse)


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

    await _create_database(base, test_db)
    try:
        yield f"{base}/{test_db}"
    finally:
        await _drop_database(base, test_db)


@pytest_asyncio.fixture(scope="session")
async def pristine_db_name(test_db_url: str) -> AsyncIterator[str]:
    """Run Alembic migrations against the test DB, then keep a copy as a template.

    The copy is taken before anything else connects (Alembic's engine uses
    ``NullPool``), because Postgres refuses ``CREATE DATABASE ... TEMPLATE``
    while the template has sessions. Yields the copy's database name.
    """
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

    base, test_db = _split_url(test_db_url)
    pristine = f"{test_db}_pristine"
    await _create_database(base, pristine, template=test_db)
    try:
        yield pristine
    finally:
        await _drop_database(base, pristine)


@pytest_asyncio.fixture(scope="session")
async def test_engine(test_db_url: str, pristine_db_name: str) -> AsyncIterator[AsyncEngine]:
    """Yield an engine bound to the migrated test DB (migrations ran in ``pristine_db_name``)."""
    engine = create_async_engine(test_db_url, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def isolated_db_url(test_db_url: str, pristine_db_name: str) -> AsyncIterator[str]:
    """A freshly migrated database of this test's own, dropped afterwards.

    For code under test that commits through its own engine and reads global
    state ("how many admins exist?"). Rows that other tests on the same xdist
    worker committed to the shared test DB cannot reach it, and nothing it
    commits reaches them. Copying the template takes well under a second.
    """
    base, _ = _split_url(test_db_url)
    name = f"lq_ai_iso_{secrets.token_hex(4)}"
    await _create_database(base, name, template=pristine_db_name)
    try:
        yield f"{base}/{name}"
    finally:
        await _drop_database(base, name)


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
