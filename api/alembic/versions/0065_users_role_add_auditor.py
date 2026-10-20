"""users.role — add 'auditor' to the RBAC CHECK constraint.

Widens ``chk_users_role_enum`` (migration 0017) from
('admin','member','viewer') to include 'auditor' — a read-only,
deployment-wide cross-user reviewer role (see the cross-user auditor spec).
No data migration: existing rows all satisfy the wider set.

Revision ID: 0065
Revises: 0064
"""

from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None

_OLD = "role IN ('admin', 'member', 'viewer')"
_NEW = "role IN ('admin', 'member', 'viewer', 'auditor')"


def upgrade() -> None:
    op.drop_constraint("chk_users_role_enum", "users", type_="check")
    op.create_check_constraint("chk_users_role_enum", "users", _NEW)


def downgrade() -> None:
    # Safe only if no 'auditor' rows exist; forward-only in practice.
    op.drop_constraint("chk_users_role_enum", "users", type_="check")
    op.create_check_constraint("chk_users_role_enum", "users", _OLD)
