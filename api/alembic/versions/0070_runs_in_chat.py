"""Governed runs hosted in a chat thread, and registry profiles (ADR 0038 D1, D3).

Revision ID: 0070
Revises: 0069

Additive on a 0.8.0 database, which already carries the orchestration tables.

* ``messages.kind`` accepts ``run``. A run's reply is one assistant message of
  that kind, linked to the run's root autonomous session by the new nullable
  ``messages.autonomous_session_id``. ``chats.autonomous_session_id`` is not
  reused: it marks hidden, session-owned chats and removes them from chat lists.
* The link is unique per session and indexed only where set. Deleting the
  session leaves the message and clears the link.
* ``orchestration_roots.profile`` moves from an enumerated check to a pattern
  check. The application validates the value against its closed profile
  registry; the database keeps only the shape.

Downgrade refuses while a run message or a registry-only profile is retained,
matching 0067's refusal to drop retained orchestration records.
"""

from alembic import op

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE messages DROP CONSTRAINT chk_messages_kind;
        ALTER TABLE messages ADD CONSTRAINT chk_messages_kind
          CHECK (kind IN ('user', 'ai', 'refusal', 'system', 'run'));
        ALTER TABLE messages ADD COLUMN autonomous_session_id uuid
          CONSTRAINT fk_messages_autonomous_session_id
          REFERENCES autonomous_sessions(id) ON DELETE SET NULL;
        ALTER TABLE messages ADD CONSTRAINT chk_messages_run_binding
          CHECK (autonomous_session_id IS NULL OR (kind = 'run' AND role = 'assistant'));
        CREATE UNIQUE INDEX uq_messages_autonomous_session
          ON messages(autonomous_session_id) WHERE autonomous_session_id IS NOT NULL;

        ALTER TABLE orchestration_roots DROP CONSTRAINT orchestration_roots_profile_check;
        ALTER TABLE orchestration_roots ADD CONSTRAINT orchestration_roots_profile_check
          CHECK (profile ~ '^[a-z][a-z0-9_]{0,63}$');
        ALTER TABLE orchestration_roots DROP CONSTRAINT ck_orchestration_planning;
        ALTER TABLE orchestration_roots ADD CONSTRAINT ck_orchestration_planning CHECK (
          (profile = 'demonstration' AND planning_snapshot IS NULL AND current_revision IS NOT NULL)
          OR (profile <> 'demonstration' AND planning_snapshot IS NOT NULL
            AND jsonb_typeof(planning_snapshot) = 'object'
            AND (current_revision IS NOT NULL OR status IN
              ('planning','uncertain','halted','failed','expired'))));
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM messages
                     WHERE kind = 'run' OR autonomous_session_id IS NOT NULL)
             OR EXISTS (SELECT 1 FROM orchestration_roots
                        WHERE profile NOT IN ('demonstration', 'model_demo_v1'))
          THEN
            RAISE EXCEPTION '0070 downgrade requires removing chat-hosted runs and registry-profile runs first';
          END IF;
        END $$;
        ALTER TABLE orchestration_roots DROP CONSTRAINT ck_orchestration_planning;
        ALTER TABLE orchestration_roots ADD CONSTRAINT ck_orchestration_planning CHECK (
          (profile = 'demonstration' AND planning_snapshot IS NULL AND current_revision IS NOT NULL)
          OR (profile = 'model_demo_v1' AND planning_snapshot IS NOT NULL
            AND jsonb_typeof(planning_snapshot) = 'object'
            AND (current_revision IS NOT NULL OR status IN
              ('planning','uncertain','halted','failed','expired'))));
        ALTER TABLE orchestration_roots DROP CONSTRAINT orchestration_roots_profile_check;
        ALTER TABLE orchestration_roots ADD CONSTRAINT orchestration_roots_profile_check
          CHECK (profile IN ('demonstration','model_demo_v1'));
        DROP INDEX uq_messages_autonomous_session;
        ALTER TABLE messages DROP CONSTRAINT chk_messages_run_binding;
        ALTER TABLE messages DROP COLUMN autonomous_session_id;
        ALTER TABLE messages DROP CONSTRAINT chk_messages_kind;
        ALTER TABLE messages ADD CONSTRAINT chk_messages_kind
          CHECK (kind IN ('user', 'ai', 'refusal', 'system'));
    """)
