"""add deleted_at to playbooks — M3-A6 Phase 2 (CRUD soft delete)

The M3-A6 Phase 2 CRUD surface adds ``DELETE /api/v1/playbooks/{id}`` as
a soft delete (matching the ``files`` table pattern from Task C4 — see
``docs/adr/0005-file-storage-soft-delete-and-key-scheme.md``). Soft
delete is the right call here because:

* ``playbook_executions.playbook_id`` is ``ON DELETE CASCADE`` — a hard
  delete would also drop the execution history, which is audit-relevant
  (operators need to see "what playbook produced this result, even if
  the playbook has since been removed"). Soft delete keeps the row
  around so historical executions still resolve to a playbook record.
* It matches the visibility-after-delete posture already used for
  ``files`` (delete then list never shows the row again — for
  ``playbooks`` this means GET / list / execute all filter
  ``deleted_at IS NULL``).

No partial index is added: the ``playbooks`` table is bounded (a few
dozen rows in practice — built-ins plus user-created), so the cost of
a full-table scan with a ``deleted_at IS NULL`` filter is negligible.
If the table grows by orders of magnitude in the future, the index
can land in a follow-on migration.

Revision ID: 0034
Revises: 0033
Create Date: 2026-05-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "playbooks",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("playbooks", "deleted_at")
