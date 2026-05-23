"""Bridge persistence surface for Slack workspace records — M3-D1.

The slack-bridge service runs the OAuth dance with Slack then POSTs the
resulting workspace tuple here. The bridge authenticates with a shared
bearer token (``LQ_AI_BRIDGE_TOKEN``) — NOT a user JWT, because the
bridge is a service-to-service caller with no user context.

The router is mounted WITHOUT the ``_active`` user gate (parallels
:mod:`app.api.internal` which is also a service-to-service surface).
Auth happens per-handler via :func:`require_bridge_auth`.

Decision M3-D1-2 (re-install semantics): the POST endpoint upserts on
``team_id``. Slack rotates bot tokens on re-install, so an existing
row's ``bot_token_encrypted`` + ``installer_slack_user_id`` + ``scope``
are replaced; a soft-deleted row (``deleted_at IS NOT NULL``) is
revived.

Decision M3-D1-1 (encryption key): the bot token is encrypted under
:envvar:`LQ_AI_BRIDGE_MASTER_KEY` (NOT the gateway's master key) before
persistence.

Decision M3-D1-3 (token storage): ``LQ_AI_BRIDGE_TOKEN`` lives in the
api's :class:`Settings` only — the gateway has no Slack-bridge role so
its secret surface stays minimal.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_bridge_auth
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.slack_workspace import SlackWorkspace
from app.schemas.slack_workspace import SlackWorkspaceCreate, SlackWorkspaceResponse
from app.security.encryption import BridgeTokenEncryptor

log = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/slack", tags=["integrations-slack"])


@router.post(
    "/workspaces",
    response_model=SlackWorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_bridge_auth)],
)
async def upsert_slack_workspace(
    body: SlackWorkspaceCreate,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SlackWorkspaceResponse:
    """Persist (or upsert) the workspace record from the bridge.

    Upserts on ``team_id``. On conflict:
      * ``team_name`` is refreshed from the request body (operator may
        have renamed the workspace in Slack).
      * ``bot_token_encrypted`` is replaced (Slack rotates tokens on
        re-install).
      * ``bot_user_id`` is refreshed (Slack may have issued a new bot
        user across the re-install).
      * ``installer_slack_user_id`` is refreshed (a different operator
        may be reinstalling).
      * ``scope`` is replaced (consent may have changed).
      * ``deleted_at`` is set back to NULL (re-install revives soft-
        deleted rows).
      * ``installed_at`` stays at the original install time; the
        re-install does not reset the audit timestamp. Operators can
        infer re-install activity from the bot-token ciphertext
        changing without the install timestamp moving.
    """

    encryptor = BridgeTokenEncryptor(master_key=settings.lq_ai_bridge_master_key or None)
    bot_token_encrypted = encryptor.encrypt(body.bot_token)

    existing = (
        await db.execute(select(SlackWorkspace).where(SlackWorkspace.team_id == body.team_id))
    ).scalar_one_or_none()

    if existing is None:
        workspace = SlackWorkspace(
            team_id=body.team_id,
            team_name=body.team_name,
            bot_token_encrypted=bot_token_encrypted,
            bot_user_id=body.bot_user_id,
            installer_slack_user_id=body.installer_slack_user_id,
            scope=body.scope,
        )
        db.add(workspace)
    else:
        existing.team_name = body.team_name
        existing.bot_token_encrypted = bot_token_encrypted
        existing.bot_user_id = body.bot_user_id
        existing.installer_slack_user_id = body.installer_slack_user_id
        existing.scope = body.scope
        existing.deleted_at = None
        workspace = existing

    await db.commit()
    await db.refresh(workspace)
    return SlackWorkspaceResponse.model_validate(workspace)
