"""0069 up/down and non-lossy deletion behavior in a separate disposable DB."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


def exercise(source_url):
    name = f"lq_ai_test_0069_{uuid4().hex[:10]}"
    base = source_url.replace("postgresql+asyncpg://", "postgresql://", 1).rsplit("/", 1)[0]
    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    target = create_engine(f"{base}/{name}")
    config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[3] / "alembic"))
    old_url = os.environ.get("DATABASE_URL")
    owner, session = uuid4(), uuid4()
    try:
        with admin.connect() as db:
            db.execute(text(f'CREATE DATABASE "{name}"'))
        os.environ["DATABASE_URL"] = f"{base}/{name}"
        command.upgrade(config, "0068")
        with target.begin() as db:
            db.execute(
                text(
                    "INSERT INTO users(id,email,hashed_password) VALUES (:id,'checkpoint@example.com','unused')"
                ),
                {"id": owner},
            )
            db.execute(
                text(
                    "INSERT INTO autonomous_sessions(id,user_id,trigger_kind) VALUES (:id,:owner,'manual')"
                ),
                {"id": session, "owner": owner},
            )
        command.upgrade(config, "0069")
        command.downgrade(config, "0068")
        with target.connect() as db:
            assert (
                db.scalar(
                    text("SELECT count(*) FROM autonomous_sessions WHERE id=:id"), {"id": session}
                )
                == 1
            )
        command.upgrade(config, "0069")
        with target.begin() as db:
            db.execute(
                text(
                    "INSERT INTO orchestration_checkpoints.checkpoints(thread_id, checkpoint_id, checkpoint) VALUES (:thread, 'one', '{}')"
                ),
                {"thread": str(session)},
            )
            db.execute(
                text(
                    "INSERT INTO orchestration_checkpoints.checkpoint_blobs(thread_id, channel, version, blob) VALUES (:thread, 'session_id', 'one', 'x')"
                ),
                {"thread": str(session)},
            )
            db.execute(
                text(
                    "INSERT INTO orchestration_checkpoints.checkpoint_writes(thread_id, checkpoint_id, task_id, idx, channel, blob) VALUES (:thread, 'one', 'task', 0, 'session_id', 'x')"
                ),
                {"thread": str(session)},
            )
        with pytest.raises(DBAPIError, match="draining and exporting"):
            command.downgrade(config, "0068")
        with target.begin() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0069"
            db.execute(text("DELETE FROM users WHERE id=:id"), {"id": owner})
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                assert (
                    db.scalar(text(f"SELECT count(*) FROM orchestration_checkpoints.{table}")) == 0
                )
        command.downgrade(config, "0068")
        command.upgrade(config, "0069")
    finally:
        if old_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_url
        target.dispose()
        with admin.connect() as db:
            db.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


async def test_checkpoint_migration_roundtrip_and_user_deletion(test_db_url):
    await asyncio.to_thread(exercise, test_db_url)
