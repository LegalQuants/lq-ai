"""create slack_workspaces table — M3-D1

Persists Slack workspace records produced by the ``slack-bridge`` OAuth
install flow. The bridge service runs the OAuth dance with Slack, then
POSTs the resulting workspace tuple to
``POST /api/v1/integrations/slack/workspaces`` (this milestone's new
endpoint). The api persists the row with the bot token encrypted at
rest under :envvar:`LQ_AI_BRIDGE_MASTER_KEY` (separate from the
gateway's provider-key master key — different threat models).

Decision M3-D1-1 (encryption key): dedicated
:envvar:`LQ_AI_BRIDGE_MASTER_KEY`, not shared with the gateway.
Slack bot tokens enable bot impersonation; provider keys enable
inference routing. Different blast radii → different keys.

Decision M3-D1-2 (re-install semantics): the persistence endpoint
upserts on ``team_id`` (Slack rotates bot tokens on re-install). The
unique constraint here enforces "one live row per Slack workspace";
the endpoint's upsert path replaces ``bot_token_encrypted`` +
``installer_slack_user_id`` + ``scope`` + revives ``deleted_at`` if
the row was soft-deleted.

Schema
------

* ``id`` — UUID PK.
* ``team_id`` — Slack workspace id (T0123456...); unique. The natural
  key from Slack's side; what the upsert path conflicts on.
* ``team_name`` — Slack workspace display name. Snapshotted at install
  time; not auto-refreshed if the operator renames the workspace.
* ``bot_token_encrypted`` — bytea; Fernet-wrapped bot user OAuth token
  (``xoxb-...``). Decrypted in-memory only when the bridge needs to
  post a reply.
* ``bot_user_id`` — Slack user id of the bot user the install created
  (U0123456...). Used by the bridge to recognize self-mentions and
  attribute audit events to the bot rather than a human.
* ``installer_slack_user_id`` — Slack user id of the operator who
  clicked install. Audit-only — does not grant any LQ.AI permissions.
* ``scope`` — comma-separated scope list Slack returned (e.g.,
  ``"commands,chat:write"``). Stored verbatim so an operator can
  audit what the workspace consented to.
* ``installed_at`` — install timestamp (defaults to ``now()``).
* ``deleted_at`` — soft-delete; matches the
  ``playbooks.deleted_at`` posture from migration 0034. Upsert
  revives the row by setting back to NULL.

Indexes
-------

* ``team_id`` — covered by the unique constraint; no separate index.

Revision ID: 0037
Revises: 0036
Create Date: 2026-05-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slack_workspaces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("team_id", sa.Text(), nullable=False),
        sa.Column("team_name", sa.Text(), nullable=False),
        sa.Column("bot_token_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("bot_user_id", sa.Text(), nullable=False),
        sa.Column("installer_slack_user_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
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
        sa.UniqueConstraint("team_id", name="uq_slack_workspaces_team_id"),
    )


def downgrade() -> None:
    op.drop_table("slack_workspaces")
