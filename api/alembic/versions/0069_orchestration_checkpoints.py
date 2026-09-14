"""Isolated, session-owned LangGraph checkpoint schema for the demonstration.

Revision ID: 0069
Revises: 0068

Matches langgraph-checkpoint-postgres 3.1.2's ten migrations. The schema is
application-migrated, so API/worker dispatch never performs DDL. Generated UUID
references make session/user deletion cascade through every continuation row.
"""

from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA orchestration_checkpoints")
    op.execute(
        "CREATE TABLE orchestration_checkpoints.checkpoint_migrations (v INTEGER PRIMARY KEY)"
    )
    op.execute("""CREATE TABLE orchestration_checkpoints.checkpoints (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        parent_checkpoint_id TEXT,
        type TEXT,
        checkpoint JSONB NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}',
        session_id UUID GENERATED ALWAYS AS (thread_id::uuid) STORED
            REFERENCES public.autonomous_sessions(id) ON DELETE CASCADE,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
    )""")
    op.execute("""CREATE TABLE orchestration_checkpoints.checkpoint_blobs (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        channel TEXT NOT NULL,
        version TEXT NOT NULL,
        type TEXT,
        blob BYTEA,
        session_id UUID GENERATED ALWAYS AS (thread_id::uuid) STORED
            REFERENCES public.autonomous_sessions(id) ON DELETE CASCADE,
        PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
    )""")
    op.execute("""CREATE TABLE orchestration_checkpoints.checkpoint_writes (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        idx INTEGER NOT NULL,
        channel TEXT NOT NULL,
        type TEXT,
        blob BYTEA NOT NULL,
        task_path TEXT NOT NULL DEFAULT '',
        session_id UUID GENERATED ALWAYS AS (thread_id::uuid) STORED
            REFERENCES public.autonomous_sessions(id) ON DELETE CASCADE,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
    )""")
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        op.execute(
            f"CREATE INDEX {table}_thread_id_idx ON orchestration_checkpoints.{table}(thread_id)"
        )
        op.execute(
            f"CREATE INDEX {table}_session_id_idx ON orchestration_checkpoints.{table}(session_id)"
        )
    op.execute(
        "INSERT INTO orchestration_checkpoints.checkpoint_migrations SELECT generate_series(0, 9)"
    )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM orchestration_checkpoints.checkpoints)
           OR EXISTS (SELECT 1 FROM orchestration_checkpoints.checkpoint_blobs)
           OR EXISTS (SELECT 1 FROM orchestration_checkpoints.checkpoint_writes)
           OR EXISTS (SELECT 1 FROM orchestration_accounts WHERE worker_id IS NOT NULL)
        THEN RAISE EXCEPTION 'Checkpoint downgrade requires draining and exporting existing runs';
        END IF;
    END $$""")
    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints", "checkpoint_migrations"):
        op.execute(f"DROP TABLE orchestration_checkpoints.{table}")
    # Unexpected operator-owned objects or dependencies make downgrade refuse.
    op.execute("DROP SCHEMA orchestration_checkpoints")
