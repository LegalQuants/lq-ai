"""0068 backfills without extending authority; downgrade requires drained claims."""

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


def exercise_lease_migration(source_url: str) -> None:
    name = f"lq_ai_test_0068_{uuid4().hex[:10]}"
    base = source_url.replace("postgresql+asyncpg://", "postgresql://", 1).rsplit("/", 1)[0]
    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    target = create_engine(f"{base}/{name}")
    config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[3] / "alembic"))
    old_url = os.environ.get("DATABASE_URL")
    owner, session, project, plan_id, worker = (uuid4() for _ in range(5))
    try:
        with admin.connect() as db:
            db.execute(text(f'CREATE DATABASE "{name}"'))
        os.environ["DATABASE_URL"] = f"{base}/{name}"
        command.upgrade(config, "0067")
        with target.begin() as db:
            db.execute(
                text(
                    "INSERT INTO users(id,email,hashed_password) VALUES (:id,'lease-migration@example.com','unused')"
                ),
                {"id": owner},
            )
            db.execute(
                text(
                    "INSERT INTO projects(id,owner_id,name,slug) VALUES (:id,:owner,'Migration','lease-migration')"
                ),
                {"id": project, "owner": owner},
            )
            db.execute(
                text(
                    "INSERT INTO autonomous_sessions(id,user_id,project_id,trigger_kind) VALUES (:id,:owner,:project,'manual')"
                ),
                {"id": session, "owner": owner, "project": project},
            )
            db.execute(
                text(
                    "INSERT INTO orchestration_roots(session_id,owner_id,project_id,plan_id,current_revision,status) VALUES (:root,:owner,:project,:plan,1,'running')"
                ),
                {"root": session, "owner": owner, "project": project, "plan": plan_id},
            )
            db.execute(
                text(
                    "INSERT INTO orchestration_plans(root_id,revision,plan_hash,snapshot,status) VALUES (:root,1,:hash,'{}','proposed')"
                ),
                {"root": session, "hash": "a" * 64},
            )
            db.execute(
                text(
                    "INSERT INTO orchestration_accounts(session_id,root_id,allocation_usd,spent_usd,reserved_usd,generation,worker_id,lease_until) VALUES (:root,:root,5,1,2,3,:worker,clock_timestamp()+interval '30 seconds')"
                ),
                {"root": session, "worker": worker},
            )
            db.execute(
                text(
                    "INSERT INTO orchestration_effects(session_id,effect_key,request_hash,phase,intent,generation,status,reserved_usd,charged_usd,result,completed_at) VALUES (:root,'analysis:done',:hash,'analysis','run_skill',2,'completed',1,1,'{\"fixture\": true}',clock_timestamp())"
                ),
                {"root": session, "hash": "b" * 64},
            )
            db.execute(
                text(
                    "INSERT INTO orchestration_effects(session_id,effect_key,request_hash,phase,intent,generation,status,reserved_usd) VALUES (:root,'analysis:pending',:hash,'analysis','run_skill',3,'admitted',2)"
                ),
                {"root": session, "hash": "c" * 64},
            )
            before = db.execute(
                text(
                    "SELECT allocation_usd,spent_usd,reserved_usd,generation,worker_id,lease_until FROM orchestration_accounts"
                )
            ).one()
            receipts = db.execute(
                text("SELECT * FROM orchestration_effects ORDER BY effect_key")
            ).all()
        command.upgrade(config, "0068")
        with target.connect() as db:
            after = db.execute(
                text(
                    "SELECT allocation_usd,spent_usd,reserved_usd,generation,worker_id,lease_until,attempt_deadline FROM orchestration_accounts"
                )
            ).one()
            assert after[:-1] == before and after[-1] == before[-1]
            assert (
                db.execute(text("SELECT * FROM orchestration_effects ORDER BY effect_key")).all()
                == receipts
            )
        # SQL writers cannot leave partially owned accounts or exceed the limit.
        for mutation in (
            "attempt_deadline=NULL",
            "lease_until=attempt_deadline+interval '1 second'",
            "worker_id=NULL,lease_until=NULL",
        ):
            with (
                pytest.raises(DBAPIError, match="ck_orchestration_attempt_lease"),
                target.begin() as db,
            ):
                db.execute(text(f"UPDATE orchestration_accounts SET {mutation}"))
        with pytest.raises(DBAPIError, match="draining worker ownership"):
            command.downgrade(config, "0067")
        with target.begin() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0068"
            # Simulate recovery/drain: uncertain reservation survives the downgrade.
            db.execute(
                text("UPDATE orchestration_effects SET status='uncertain' WHERE status='admitted'")
            )
            db.execute(
                text(
                    "UPDATE orchestration_accounts SET worker_id=NULL,lease_until=NULL,attempt_deadline=NULL,generation=generation+1"
                )
            )
            drained = db.execute(
                text("SELECT * FROM orchestration_effects ORDER BY effect_key")
            ).all()
        command.downgrade(config, "0067")
        command.upgrade(config, "0068")
        with target.connect() as db:
            assert (
                db.execute(text("SELECT * FROM orchestration_effects ORDER BY effect_key")).all()
                == drained
            )
            account = db.execute(
                text(
                    "SELECT spent_usd,reserved_usd,generation,worker_id,lease_until,attempt_deadline FROM orchestration_accounts"
                )
            ).one()
            assert account == (1, 2, 4, None, None, None)
        command.downgrade(config, "0067")
    finally:
        if old_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_url
        target.dispose()
        with admin.connect() as db:
            db.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


async def test_0068_conservative_backfill_constraints_and_drained_roundtrip(test_db_url):
    await asyncio.to_thread(exercise_lease_migration, test_db_url)
