"""Pydantic wire shapes for the teams-bridge persistence surface — M3-D3.

The teams-bridge service runs the OAuth dance with Microsoft identity
platform (multi-tenant Azure AD app) then POSTs the resulting tenant
tuple to ``POST /api/v1/integrations/teams/tenants`` on the api. This
module defines the request body (:class:`TeamsTenantCreate`) and the
response shape (:class:`TeamsTenantResponse`).

Unlike the Slack equivalent, no bot token travels here — Microsoft
Teams uses operator-supplied app-level bot credentials (one
``MICROSOFT_APP_ID`` per deployment) not per-tenant tokens.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TeamsTenantCreate(BaseModel):
    """Tenant record the teams-bridge POSTs after admin consent.

    Field shape matches what ``teams-bridge/app/oauth.py`` produces
    from the ``id_token`` claims (``tid`` for tenant_id, ``oid`` for
    installer) and the Microsoft Graph ``/organization`` lookup for
    the display name.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(
        ...,
        min_length=1,
        description="Microsoft tenant id (`tid` claim — the M365 directory GUID).",
    )
    tenant_name: str = Field(
        ...,
        min_length=1,
        description="Tenant display name at install time (from Graph /organization).",
    )
    installer_oid: str = Field(
        ...,
        min_length=1,
        description=(
            "M365 object id (`oid` claim) of the admin who completed consent. "
            "Audit only — does not grant LQ.AI permissions."
        ),
    )


class TeamsTenantResponse(BaseModel):
    """Persisted-tenant response. Mirrors :class:`SlackWorkspaceResponse`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: str
    tenant_name: str
    installer_oid: str
    installed_at: datetime
