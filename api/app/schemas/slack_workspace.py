"""Pydantic wire shapes for the slack-bridge persistence surface — M3-D1.

The slack-bridge service runs the OAuth dance with Slack and POSTs the
resulting workspace tuple to
``POST /api/v1/integrations/slack/workspaces`` on the api. This module
defines the request body (:class:`SlackWorkspaceCreate`) and the
response shape (:class:`SlackWorkspaceResponse`). The bot token is
plaintext on the wire (the request travels over the trusted in-cluster
network with a bearer token) and encrypted before persistence.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SlackWorkspaceCreate(BaseModel):
    """Workspace record the slack-bridge POSTs after OAuth completes.

    Field shape matches what ``slack-bridge/app/oauth.py`` produces from
    Slack's ``oauth.v2.access`` response (see lines 184-191 in that
    file). Renames here would break the bridge → api contract.
    """

    model_config = ConfigDict(extra="forbid")

    team_id: str = Field(..., min_length=1, description="Slack workspace id (T0...).")
    team_name: str = Field(..., min_length=1, description="Workspace display name at install time.")
    bot_token: str = Field(
        ...,
        min_length=1,
        description=(
            "The xoxb- bot user OAuth token Slack returned. Plaintext on the wire; "
            "encrypted under LQ_AI_BRIDGE_MASTER_KEY before persistence."
        ),
    )
    bot_user_id: str = Field(..., min_length=1, description="Slack user id of the bot user.")
    installer_slack_user_id: str = Field(
        ...,
        min_length=1,
        description="Slack user id of the operator who completed install (audit only).",
    )
    scope: str = Field(
        ...,
        min_length=1,
        description="Comma-separated scope list Slack returned (e.g. 'commands,chat:write').",
    )


class SlackWorkspaceResponse(BaseModel):
    """Persisted-workspace response. Bot token deliberately omitted.

    The bridge does not need the ciphertext echoed back; the response
    exists so the bridge can log the api-side workspace id for
    correlation and confirm the upsert path it took.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    team_id: str
    team_name: str
    bot_user_id: str
    installer_slack_user_id: str
    scope: str
    installed_at: datetime
