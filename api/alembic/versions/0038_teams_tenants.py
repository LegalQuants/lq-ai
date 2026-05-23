"""create teams_tenants table — M3-D3

Persists Microsoft 365 tenant records produced by the ``teams-bridge``
OAuth install flow. Unlike Slack (which issues per-workspace bot
tokens), Microsoft Teams uses **app-level bot credentials** — the bot
authenticates to the Bot Framework with the operator's single
``MICROSOFT_APP_ID`` + ``MICROSOFT_APP_PASSWORD`` regardless of which
tenant it's running in. So there's no per-tenant bot token to encrypt;
this table only persists the identity-binding fields the admin UI
(M3-D4) needs to surface "the bot is installed in tenant X".

Decision M3-D3-1 (encryption key): reuse ``LQ_AI_BRIDGE_MASTER_KEY``
from M3-D1 — same bridge threat model. (And in this milestone we don't
actually encrypt anything for Teams; the column is left for future
per-user-refresh-token storage when M4 lands the on-behalf-of flow.)

Decision M3-D3-2 (re-install semantics): upsert on ``tenant_id``.
Re-install in the same M365 tenant replaces ``tenant_name`` +
``installer_oid`` and revives ``deleted_at``.

Decision M3-D3-4 (tenancy): the bridge runs as a multi-tenant
Microsoft identity platform app, so one Azure AD app registration can
host installs from any tenant. This table can carry rows for many
tenants concurrently.

Schema
------

* ``id`` — UUID PK.
* ``tenant_id`` — Microsoft tenant id (the M365 directory's GUID);
  unique. The natural key from Microsoft's side.
* ``tenant_name`` — display name at install time. Best-effort —
  Microsoft Graph returns the org's ``displayName`` field on the
  consent response. NOT auto-refreshed if the tenant is renamed.
* ``installer_oid`` — M365 ``oid`` claim of the admin who completed
  consent. Audit-only — does not grant LQ.AI permissions.
* ``installed_at`` — install timestamp (defaults to ``now()``).
* ``deleted_at`` — soft-delete; matches the
  ``slack_workspaces.deleted_at`` posture from migration 0037.

Revision ID: 0038
Revises: 0037
Create Date: 2026-05-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teams_tenants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("tenant_name", sa.Text(), nullable=False),
        sa.Column("installer_oid", sa.Text(), nullable=False),
        sa.Column(
            "installed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint("tenant_id", name="uq_teams_tenants_tenant_id"),
    )


def downgrade() -> None:
    op.drop_table("teams_tenants")
