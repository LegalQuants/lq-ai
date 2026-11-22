"""Slack identity input never accepts an LQ.AI user override or email."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SlackLinkStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team_id: str = Field(pattern=r"^T[A-Z0-9]{1,63}$")
    slack_user_id: str = Field(pattern=r"^[UW][A-Z0-9]{1,63}$")


class SlackLinkToken(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")


class SlackLinkStarted(BaseModel):
    url: str
    expires_at: datetime


class SlackLinkPreview(BaseModel):
    team_id: str
    team_name: str
    slack_user_id: str
    expires_at: datetime


class SlackAccountResponse(BaseModel):
    id: uuid.UUID
    team_id: str
    team_name: str
    slack_user_id: str
    created_at: datetime
