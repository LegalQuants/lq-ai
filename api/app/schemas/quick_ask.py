"""Request/response schemas for the bridge quick-ask surface — DE-288.

``POST /api/v1/integrations/quick-ask`` is the bridge-bearer-authed
endpoint backing the ``/lq ask`` slash command on Slack and Teams.
The bridges are dumb normalizers: they forward platform identity
coordinates and the question; the api owns identity resolution
(fail-closed) and runs the turn through the normal chat-send path.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bound the question size defensively: Slack slash-command text tops
# out well below this, and the value flows into a chat turn whose
# content column is unbounded — the cap exists to keep a compromised
# bridge bearer from submitting book-length prompts.
QUESTION_MAX_LEN = 4000


class QuickAskRequest(BaseModel):
    """Body of ``POST /api/v1/integrations/quick-ask``.

    Identity coordinates differ per platform:

    * ``platform="slack"`` — requires ``platform_user_id`` (the stable
      Slack user id, e.g. ``U0…``) + ``team_ref`` (Slack ``team_id``).
      The api resolves the user's profile email itself via
      ``users.info`` with the workspace's stored bot token.
    * ``platform="teams"`` — requires ``email`` (resolved bridge-side
      from the Bot Connector conversation-member record) + ``team_ref``
      (the AAD ``tenant_id``).
    """

    model_config = ConfigDict(extra="forbid")

    platform: Literal["slack", "teams"]
    platform_user_id: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    team_ref: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=QUESTION_MAX_LEN)

    @model_validator(mode="after")
    def _platform_requires_identity(self) -> QuickAskRequest:
        if self.platform == "slack" and not (self.platform_user_id or "").strip():
            raise ValueError("platform_user_id is required when platform is 'slack'")
        if self.platform == "teams" and not (self.email or "").strip():
            raise ValueError("email is required when platform is 'teams'")
        return self


class QuickAskResponse(BaseModel):
    """Body returned to the bridge on a successful quick-ask."""

    answer_text: str
    chat_id: uuid.UUID
    chat_url: str | None = None
    """Deep link into the LQ.AI web UI (``{LQ_AI_WEB_PUBLIC_URL}/lq-ai/
    chats?id={chat_id}``). ``None`` when the operator has not set
    ``LQ_AI_WEB_PUBLIC_URL`` — the bridge then omits the link."""
