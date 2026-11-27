"""Cycle only the new migration on a separately created disposable database."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

API_DIR = Path(__file__).resolve().parents[1]


async def _event_schema(connection: AsyncConnection) -> dict[str, object]:
    def collect(sync_connection: Connection) -> dict[str, object]:
        inspector = inspect(sync_connection)
        return {
            "columns": [
                (column["name"], str(column["type"]), column["nullable"], column["default"])
                for column in inspector.get_columns("workspace_events")
            ],
            "indexes": inspector.get_indexes("workspace_events"),
            "checks": inspector.get_check_constraints("workspace_events"),
            "foreign_keys": inspector.get_foreign_keys("workspace_events"),
        }

    return await connection.run_sync(collect)


@pytest.mark.integration
async def test_workspace_event_migration_cycle_preserves_existing_data(
    test_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh base -> 0078 -> 0079 -> 0078 -> 0079, leaving old user data intact.

    The randomly named database is distinct from the shared test-engine database
    and from every configured developer database. No existing DB is downgraded.
    """
    prefix = test_db_url.rsplit("/", 1)[0]
    name = f"lq_ai_test_events_{uuid.uuid4().hex}"
    assert (
        name.startswith("lq_ai_test_events_") and name.removeprefix("lq_ai_test_events_").isalnum()
    )
    admin = create_async_engine(
        f"{prefix}/postgres", isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_async_engine(f"{prefix}/{name}", poolclass=NullPool)
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    user_id = uuid.uuid4()
    try:
        with monkeypatch.context() as env:
            env.setenv("DATABASE_URL", f"{prefix}/{name}")
            await asyncio.to_thread(command.upgrade, config, "0078")
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO users (id, email, hashed_password) VALUES (:id, :email, 'unused')"
                    ),
                    {"id": user_id, "email": f"migration-{user_id}@example.com"},
                )
            await asyncio.to_thread(command.upgrade, config, "0079")
            async with engine.connect() as connection:
                before = await _event_schema(connection)
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id}
                    )
                    == 1
                )
                assert await connection.scalar(text("SELECT count(*) FROM workspace_events")) == 0
            await asyncio.to_thread(command.downgrade, config, "0078")
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(text("SELECT to_regclass('workspace_events')")) is None
                )
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id}
                    )
                    == 1
                )
            await asyncio.to_thread(command.upgrade, config, "0079")
            async with engine.connect() as connection:
                assert await _event_schema(connection) == before
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id}
                    )
                    == 1
                )
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
