"""0067 round trips on a second disposable DB, never the shared test database."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


def exercise_migration(source_url: str) -> None:
    name = f"lq_ai_test_0067_{uuid4().hex[:10]}"
    base = source_url.replace("postgresql+asyncpg://", "postgresql://", 1).rsplit("/", 1)[0]
    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    target = create_engine(f"{base}/{name}")
    config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[3] / "alembic"))
    old_url = os.environ.get("DATABASE_URL")
    owner, session, project, child, plan_id = (uuid4() for _ in range(5))
    try:
        with admin.connect() as db:
            db.execute(text(f'CREATE DATABASE "{name}"'))
        os.environ["DATABASE_URL"] = f"{base}/{name}"
        command.upgrade(config, "0066")
        with target.begin() as db:
            db.execute(
                text(
                    "INSERT INTO users(id,email,hashed_password) VALUES (:id,'migration@example.com','unused')"
                ),
                {"id": owner},
            )
            db.execute(
                text(
                    "INSERT INTO projects(id,owner_id,name,slug) VALUES (:id,:owner,'Migration','migration')"
                ),
                {"id": project, "owner": owner},
            )
            db.execute(
                text(
                    "INSERT INTO autonomous_sessions(id,user_id,project_id,trigger_kind) VALUES (:id,:owner,:project,'manual')"
                ),
                {"id": session, "owner": owner, "project": project},
            )
        command.upgrade(config, "0067")
        with target.connect() as db:
            row = db.execute(
                text(
                    "SELECT root_session_id, delegation_depth FROM autonomous_sessions WHERE id=:id"
                ),
                {"id": session},
            ).one()
            assert row == (session, 0)
        command.downgrade(config, "0066")
        with target.connect() as db:
            assert (
                db.scalar(
                    text("SELECT count(*) FROM autonomous_sessions WHERE id=:id"), {"id": session}
                )
                == 1
            )
        command.upgrade(config, "0067")
        with target.begin() as db:
            db.execute(
                text(
                    "INSERT INTO autonomous_sessions(id,user_id,project_id,trigger_kind,parent_session_id,root_session_id,delegation_depth,child_order) VALUES (:id,:owner,:project,'manual',:root,:root,1,1)"
                ),
                {"id": child, "owner": owner, "project": project, "root": session},
            )
        with pytest.raises(DBAPIError, match="draining and exporting"):
            command.downgrade(config, "0066")
        with target.begin() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0067"
            db.execute(text("DELETE FROM autonomous_sessions WHERE id=:id"), {"id": child})
            db.execute(
                text(
                    "INSERT INTO orchestration_roots(session_id,owner_id,project_id,plan_id,current_revision,status) VALUES (:root,:owner,:project,:plan,1,'awaiting_approval')"
                ),
                {"root": session, "owner": owner, "project": project, "plan": plan_id},
            )
            db.execute(
                text(
                    "INSERT INTO orchestration_plans(root_id,revision,plan_hash,snapshot,status) VALUES (:root,1,:hash,'{}','proposed')"
                ),
                {"root": session, "hash": "a" * 64},
            )
        with pytest.raises(DBAPIError, match="draining and exporting"):
            command.downgrade(config, "0066")
        with target.begin() as db:
            db.execute(text("DELETE FROM autonomous_sessions WHERE id=:id"), {"id": session})
            assert db.scalar(text("SELECT count(*) FROM orchestration_roots")) == 0
            assert db.scalar(text("SELECT count(*) FROM orchestration_plans")) == 0
        command.downgrade(config, "0066")
    finally:
        if old_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_url
        target.dispose()
        with admin.connect() as db:
            db.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


async def test_0067_legacy_backfill_roundtrip_and_nonlossy_downgrade(test_db_url):
    await asyncio.to_thread(exercise_migration, test_db_url)
