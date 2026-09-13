"""Private run tree, approval, admission, budget and effect records (ADR 0035).

Revision ID: 0067
Revises: 0066

No public routes or workers are enabled. Downgrade refuses when orchestration
records exist: drain/export first; never silently erase receipts or flatten an
executed tree. Legacy-only databases can upgrade/downgrade without data loss.
"""

from alembic import op

revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE autonomous_sessions
          ADD COLUMN parent_session_id uuid REFERENCES autonomous_sessions(id) ON DELETE CASCADE,
          ADD COLUMN root_session_id uuid,
          ADD COLUMN delegation_depth integer NOT NULL DEFAULT 0,
          ADD COLUMN child_order integer;
        UPDATE autonomous_sessions SET root_session_id = id;
        ALTER TABLE autonomous_sessions ALTER COLUMN root_session_id SET NOT NULL;
        -- Add the deferred self-FK after backfill, so its pending trigger events
        -- cannot block subsequent ALTER TABLE statements on populated databases.
        ALTER TABLE autonomous_sessions ADD CONSTRAINT fk_autonomous_session_root
          FOREIGN KEY (root_session_id) REFERENCES autonomous_sessions(id)
          ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;
        ALTER TABLE autonomous_sessions ADD CONSTRAINT ck_autonomous_tree_shape CHECK (
          (parent_session_id IS NULL AND root_session_id = id AND delegation_depth = 0 AND child_order IS NULL)
          OR (parent_session_id IS NOT NULL AND parent_session_id = root_session_id AND parent_session_id <> id
              AND delegation_depth = 1 AND child_order BETWEEN 1 AND 4 AND child_order IS NOT NULL)
        );
        CREATE INDEX ix_autonomous_session_parent ON autonomous_sessions(parent_session_id) WHERE parent_session_id IS NOT NULL;
        CREATE INDEX ix_autonomous_session_root ON autonomous_sessions(root_session_id);

        CREATE TABLE orchestration_roots (
          session_id uuid PRIMARY KEY REFERENCES autonomous_sessions(id) ON DELETE CASCADE,
          owner_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
          plan_id uuid NOT NULL UNIQUE,
          current_revision integer NOT NULL CHECK (current_revision > 0),
          admitted_revision integer CHECK (admitted_revision = current_revision),
          status text NOT NULL CHECK (status IN ('awaiting_approval','queued','running','waiting_children','uncertain','halted','completed','failed','rejected','expired')),
          stop_reason text,
          created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX uq_orchestration_active_owner ON orchestration_roots(owner_id)
          WHERE status IN ('awaiting_approval','queued','running','waiting_children','uncertain');

        CREATE TABLE orchestration_plans (
          root_id uuid NOT NULL REFERENCES orchestration_roots(session_id) ON DELETE CASCADE,
          revision integer NOT NULL CHECK (revision > 0),
          plan_hash text NOT NULL CHECK (plan_hash ~ '^[0-9a-f]{64}$'),
          snapshot jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
          status text NOT NULL CHECK (status IN ('proposed','approved','rejected','superseded')),
          approval jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (root_id, revision),
          CHECK (status <> 'approved' OR approval IS NOT NULL),
          CHECK (status NOT IN ('proposed','rejected') OR approval IS NULL)
        );
        ALTER TABLE orchestration_roots ADD CONSTRAINT fk_orchestration_current_plan
          FOREIGN KEY (session_id, current_revision) REFERENCES orchestration_plans(root_id, revision)
          DEFERRABLE INITIALLY DEFERRED;

        CREATE TABLE orchestration_admissions (
          session_id uuid PRIMARY KEY REFERENCES autonomous_sessions(id) ON DELETE CASCADE,
          root_id uuid NOT NULL REFERENCES orchestration_roots(session_id) ON DELETE CASCADE,
          revision integer NOT NULL,
          dispatch_id uuid NOT NULL,
          child_order integer NOT NULL CHECK (child_order BETWEEN 1 AND 4),
          created_at timestamptz NOT NULL DEFAULT now(),
          FOREIGN KEY (root_id, revision) REFERENCES orchestration_plans(root_id, revision) ON DELETE CASCADE,
          UNIQUE (root_id, revision, dispatch_id), UNIQUE (root_id, revision, child_order)
        );
        CREATE TABLE orchestration_accounts (
          session_id uuid PRIMARY KEY REFERENCES autonomous_sessions(id) ON DELETE CASCADE,
          root_id uuid NOT NULL REFERENCES orchestration_roots(session_id) ON DELETE CASCADE,
          allocation_usd numeric(10,4) NOT NULL CHECK (allocation_usd >= 0),
          spent_usd numeric(14,4) NOT NULL DEFAULT 0 CHECK (spent_usd >= 0),
          reserved_usd numeric(14,4) NOT NULL DEFAULT 0 CHECK (reserved_usd >= 0),
          generation bigint NOT NULL DEFAULT 0 CHECK (generation >= 0),
          worker_id uuid, lease_until timestamptz,
          CHECK ((worker_id IS NULL) = (lease_until IS NULL))
        );
        CREATE INDEX ix_orchestration_accounts_root ON orchestration_accounts(root_id);
        CREATE TABLE orchestration_effects (
          session_id uuid NOT NULL REFERENCES orchestration_accounts(session_id) ON DELETE CASCADE,
          effect_key text NOT NULL CHECK (effect_key ~ '^[a-z][a-z0-9_.:-]{0,127}$'),
          request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
          phase text NOT NULL CHECK (phase IN ('intake','analysis','drafting','ethics_review','delivery')),
          intent text NOT NULL,
          generation bigint NOT NULL CHECK (generation > 0),
          status text NOT NULL CHECK (status IN ('admitted','completed','uncertain')),
          reserved_usd numeric(10,4) NOT NULL CHECK (reserved_usd >= 0),
          charged_usd numeric(14,4) CHECK (charged_usd >= 0),
          result jsonb,
          created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
          PRIMARY KEY (session_id, effect_key),
          CHECK ((status = 'completed' AND charged_usd IS NOT NULL AND result IS NOT NULL AND completed_at IS NOT NULL)
            OR (status <> 'completed' AND charged_usd IS NULL AND result IS NULL AND completed_at IS NULL)),
          CHECK (result IS NULL OR jsonb_typeof(result) = 'object')
        );
        CREATE UNIQUE INDEX uq_orchestration_one_inflight ON orchestration_effects(session_id)
          WHERE status IN ('admitted','uncertain');
    """)
    op.execute("""
        CREATE FUNCTION enforce_autonomous_tree() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_row autonomous_sessions%ROWTYPE;
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF (OLD.parent_session_id, OLD.root_session_id, OLD.delegation_depth, OLD.child_order)
               IS DISTINCT FROM (NEW.parent_session_id, NEW.root_session_id, NEW.delegation_depth, NEW.child_order) THEN
              RAISE EXCEPTION 'autonomous tree identity is immutable' USING ERRCODE = '23514';
            END IF;
            IF (OLD.user_id, OLD.project_id) IS DISTINCT FROM (NEW.user_id, NEW.project_id)
              AND (OLD.parent_session_id IS NOT NULL OR EXISTS (
                SELECT 1 FROM autonomous_sessions WHERE parent_session_id = OLD.id
              ) OR EXISTS (SELECT 1 FROM orchestration_roots WHERE session_id = OLD.id)) THEN
              RAISE EXCEPTION 'orchestrated ownership and project are immutable' USING ERRCODE = '23514';
            END IF;
            -- Identity/scope cannot change on an existing child. Re-locking
            -- its parent for an ordinary phase/cost update would hold a parent
            -- row lock across the legacy executor's subsequent provider I/O.
            RETURN NEW;
          END IF;
          IF NEW.parent_session_id IS NULL THEN
            IF TG_OP = 'INSERT' AND NEW.root_session_id IS NULL THEN NEW.root_session_id := NEW.id; END IF;
          ELSE
            SELECT * INTO parent_row FROM autonomous_sessions WHERE id = NEW.parent_session_id FOR SHARE;
            IF NOT FOUND OR parent_row.parent_session_id IS NOT NULL
              OR parent_row.user_id <> NEW.user_id OR parent_row.project_id IS DISTINCT FROM NEW.project_id THEN
              RAISE EXCEPTION 'invalid autonomous parent scope' USING ERRCODE = '23514';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER autonomous_tree_identity BEFORE INSERT OR UPDATE ON autonomous_sessions
          FOR EACH ROW EXECUTE FUNCTION enforce_autonomous_tree();
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM orchestration_roots) OR EXISTS (
            SELECT 1 FROM autonomous_sessions WHERE parent_session_id IS NOT NULL
          ) THEN
            RAISE EXCEPTION '0067 downgrade requires draining and exporting orchestration records first';
          END IF;
        END $$;
        DROP TRIGGER autonomous_tree_identity ON autonomous_sessions;
        DROP FUNCTION enforce_autonomous_tree();
        DROP TABLE orchestration_effects;
        DROP TABLE orchestration_accounts;
        DROP TABLE orchestration_admissions;
        ALTER TABLE orchestration_roots DROP CONSTRAINT fk_orchestration_current_plan;
        DROP TABLE orchestration_plans;
        DROP TABLE orchestration_roots;
        ALTER TABLE autonomous_sessions DROP CONSTRAINT ck_autonomous_tree_shape,
          DROP COLUMN child_order, DROP COLUMN delegation_depth,
          DROP COLUMN root_session_id, DROP COLUMN parent_session_id;
    """)
