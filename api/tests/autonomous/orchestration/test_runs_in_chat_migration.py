"""0070 and 0071 on a database that carries 0.8.0's orchestration rows.

Runs on a second disposable database, never the shared test database. Release
0.8.0 shipped 0067 and 0068, so these revisions must upgrade retained runs and
must refuse a downgrade that would drop what they added.
"""

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

ACTIVE = "'planning','awaiting_approval','queued','running','waiting_children','uncertain'"


def exercise(source_url: str) -> None:
    name = f"lq_ai_test_0070_{uuid4().hex[:10]}"
    base = source_url.replace("postgresql+asyncpg://", "postgresql://", 1).rsplit("/", 1)[0]
    admin = create_engine(f"{base}/postgres", isolation_level="AUTOCOMMIT")
    target = create_engine(f"{base}/{name}")
    config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[3] / "alembic"))
    old_url = os.environ.get("DATABASE_URL")
    owner, project, chat, retained, second, third, message = (uuid4() for _ in range(7))

    def root(db, session, plan, *, profile="model_demo_v1", status="planning", snapshot="'{}'"):  # type: ignore[no-untyped-def]
        db.execute(
            text(
                "INSERT INTO autonomous_sessions(id,user_id,project_id,trigger_kind) "
                "VALUES (:id,:owner,:project,'manual')"
            ),
            {"id": session, "owner": owner, "project": project},
        )
        db.execute(
            text(
                "INSERT INTO orchestration_roots"
                "(session_id,owner_id,project_id,plan_id,profile,planning_snapshot,status) "
                f"VALUES (:root,:owner,:project,:plan,:profile,{snapshot},:status)"
            ),
            {
                "root": session,
                "owner": owner,
                "project": project,
                "plan": plan,
                "profile": profile,
                "status": status,
            },
        )

    try:
        with admin.connect() as db:
            db.execute(text(f'CREATE DATABASE "{name}"'))
        os.environ["DATABASE_URL"] = f"{base}/{name}"
        # The schema 0.8.0 shipped, plus main's unreleased 0069.
        command.upgrade(config, "0069")
        with target.begin() as db:
            db.execute(
                text(
                    "INSERT INTO users(id,email,hashed_password) "
                    "VALUES (:id,'migration@example.com','unused')"
                ),
                {"id": owner},
            )
            db.execute(
                text(
                    "INSERT INTO projects(id,owner_id,name,slug) "
                    "VALUES (:id,:owner,'Migration','migration')"
                ),
                {"id": project, "owner": owner},
            )
            db.execute(
                text("INSERT INTO chats(id,owner_id,project_id) VALUES (:id,:owner,:project)"),
                {"id": chat, "owner": owner, "project": project},
            )
            # A retained 0.8.0 run that is uncertain, with its reservation held.
            root(db, retained, uuid4(), status="uncertain")
            db.execute(
                text(
                    "INSERT INTO orchestration_accounts(session_id,root_id,allocation_usd,reserved_usd) "
                    "VALUES (:id,:id,1,0.25)"
                ),
                {"id": retained},
            )
            db.execute(
                text(
                    "INSERT INTO orchestration_effects"
                    "(session_id,effect_key,request_hash,phase,intent,generation,status,reserved_usd) "
                    "VALUES (:id,'chat:plan:v1',:hash,'analysis','plan',1,'uncertain',0.25)"
                ),
                {"id": retained, "hash": "a" * 64},
            )
            db.execute(
                text(
                    "INSERT INTO messages(chat_id,role,kind,content) "
                    "VALUES (:chat,'user','user','Earlier turn')"
                ),
                {"chat": chat},
            )
        # 0.8.0 knows neither a run message nor a registry profile.
        with pytest.raises(DBAPIError), target.begin() as db:
            db.execute(
                text(
                    "INSERT INTO messages(chat_id,role,kind,content) VALUES (:c,'assistant','run','')"
                ),
                {"c": chat},
            )
        with pytest.raises(DBAPIError), target.begin() as db:
            root(db, second, uuid4(), profile="contract_qa_documents_v1", status="halted")

        command.upgrade(config, "0070")
        with target.begin() as db:
            # Existing rows are untouched and need no backfill.
            assert db.scalar(text("SELECT count(*) FROM messages WHERE kind='user'")) == 1
            assert (
                db.scalar(
                    text("SELECT status FROM orchestration_roots WHERE session_id=:id"),
                    {"id": retained},
                )
                == "uncertain"
            )
            # The retained run can be bound to a run message in its chat.
            db.execute(
                text(
                    "INSERT INTO messages(id,chat_id,role,kind,content,autonomous_session_id) "
                    "VALUES (:id,:chat,'assistant','run','',:session)"
                ),
                {"id": message, "chat": chat, "session": retained},
            )
            # A registry profile is accepted; it still needs its planning snapshot.
            root(db, second, uuid4(), profile="contract_qa_documents_v1", status="halted")
        for statement, params in (
            # One message per run.
            (
                "INSERT INTO messages(chat_id,role,kind,content,autonomous_session_id) "
                "VALUES (:chat,'assistant','run','',:session)",
                {"chat": chat, "session": retained},
            ),
            # Only a run message, and only an assistant one, carries the link.
            (
                "INSERT INTO messages(chat_id,role,kind,content,autonomous_session_id) "
                "VALUES (:chat,'assistant','ai','',:session)",
                {"chat": chat, "session": second},
            ),
            (
                "INSERT INTO messages(chat_id,role,kind,content,autonomous_session_id) "
                "VALUES (:chat,'user','run','',:session)",
                {"chat": chat, "session": second},
            ),
            ("UPDATE orchestration_roots SET profile='Not A Profile'", {}),
            ("UPDATE orchestration_roots SET profile=''", {}),
            (
                "UPDATE orchestration_roots SET planning_snapshot=NULL WHERE session_id=:id",
                {"id": second},
            ),
            # 0070 alone has no closed state.
            (
                "UPDATE orchestration_roots SET status='closed' WHERE session_id=:id",
                {"id": retained},
            ),
        ):
            with pytest.raises(DBAPIError), target.begin() as db:
                db.execute(text(statement), params)

        # Downgrade is refused while a run message or a registry profile is retained.
        with pytest.raises(DBAPIError, match="removing chat-hosted runs"):
            command.downgrade(config, "0069")
        with target.begin() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0070"
            db.execute(text("DELETE FROM messages WHERE id=:id"), {"id": message})
        with pytest.raises(DBAPIError, match="removing chat-hosted runs"):
            command.downgrade(config, "0069")
        with target.begin() as db:
            db.execute(text("DELETE FROM autonomous_sessions WHERE id=:id"), {"id": second})
        command.downgrade(config, "0069")
        with target.begin() as db:
            # The 0.8.0 run survived the round trip, with its reservation.
            assert (
                db.scalar(
                    text("SELECT reserved_usd FROM orchestration_accounts WHERE session_id=:id"),
                    {"id": retained},
                )
                == 0.25
            )
            assert (
                db.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns WHERE "
                        "table_name='messages' AND column_name='autonomous_session_id'"
                    )
                )
                == 0
            )

        command.upgrade(config, "0071")
        with target.begin() as db:
            db.execute(
                text(
                    "INSERT INTO messages(id,chat_id,role,kind,content,autonomous_session_id) "
                    "VALUES (:id,:chat,'assistant','run','',:session)"
                ),
                {"id": message, "chat": chat, "session": retained},
            )
        # A closed effect is a charge without an outcome; anything else is refused.
        for statement in (
            "UPDATE orchestration_effects SET status='closed'",
            "UPDATE orchestration_effects SET status='closed', charged_usd=0.25, completed_at=now(), result='{}'",
            "UPDATE orchestration_effects SET status='uncertain', charged_usd=0.25",
        ):
            with pytest.raises(DBAPIError), target.begin() as db:
                db.execute(text(statement))
        # The owner's single active-run allowance is held by the uncertain run.
        with pytest.raises(DBAPIError), target.begin() as db:
            root(db, third, uuid4())
        with target.begin() as db:
            db.execute(
                text(
                    "UPDATE orchestration_effects SET status='closed', charged_usd=reserved_usd, "
                    "completed_at=now()"
                )
            )
            db.execute(
                text(
                    "UPDATE orchestration_accounts SET spent_usd=spent_usd+reserved_usd, reserved_usd=0"
                )
            )
            # Closed while planning was uncertain: there is no plan revision.
            db.execute(
                text(
                    "UPDATE orchestration_roots SET status='closed', stop_reason='owner_closed' "
                    "WHERE session_id=:id"
                ),
                {"id": retained},
            )
            # Closing released the allowance, and the closed effect no longer blocks.
            root(db, third, uuid4())
            assert (
                db.scalar(
                    text(f"SELECT count(*) FROM orchestration_roots WHERE status IN ({ACTIVE})")
                )
                == 1
            )
        with pytest.raises(DBAPIError, match="removing closed runs"):
            command.downgrade(config, "0070")
        with target.begin() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0071"
            db.execute(text("DELETE FROM autonomous_sessions WHERE id=:id"), {"id": retained})
            # Deleting the session removed the run's records and cleared nothing else.
            assert db.scalar(text("SELECT count(*) FROM orchestration_effects")) == 0
            assert db.scalar(text("SELECT count(*) FROM messages WHERE kind='user'")) == 1
        command.downgrade(config, "0070")
        command.upgrade(config, "head")
        with target.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0071"
    finally:
        if old_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_url
        target.dispose()
        with admin.connect() as db:
            db.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


async def test_0070_0071_upgrade_a_release_database_and_refuse_a_lossy_downgrade(
    test_db_url: str,
) -> None:
    await asyncio.to_thread(exercise, test_db_url)
