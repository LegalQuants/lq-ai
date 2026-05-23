"""Bridge persistence surface for Microsoft Teams tenant records — M3-D3.

The teams-bridge service runs the OAuth dance with Microsoft identity
platform (multi-tenant Azure AD app) then POSTs the resulting tenant
tuple here. Auth posture is identical to the Slack equivalent: shared
bearer token (LQ_AI_BRIDGE_TOKEN, reused per M3-D3 decision #2) via
the shared :func:`app.api.dependencies.require_bridge_auth` dep.

Decision M3-D3-2 (re-install semantics): upsert on ``tenant_id``.
Re-install in the same M365 tenant replaces ``tenant_name`` +
``installer_oid`` and revives ``deleted_at``. ``installed_at`` stays
at the original install time.

Decision M3-D3-3 (auth library): teams-bridge uses raw httpx against
Microsoft identity platform (no botbuilder SDK). This module knows
nothing about that — it just accepts the post-consent tenant tuple.

Unlike :mod:`app.api.integrations_slack`, no bot token is persisted
here: Microsoft Teams uses operator-supplied app-level bot
credentials (one ``MICROSOFT_APP_ID`` per deployment) not per-tenant
tokens. Per-user refresh tokens (when M4 lands on-behalf-of flows)
will likely add a separate ``teams_user_tokens`` table.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_bridge_auth
from app.db.session import get_db
from app.models.teams_tenant import TeamsTenant
from app.schemas.teams_tenant import TeamsTenantCreate, TeamsTenantResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/teams", tags=["integrations-teams"])


@router.post(
    "/tenants",
    response_model=TeamsTenantResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_bridge_auth)],
)
async def upsert_teams_tenant(
    body: TeamsTenantCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TeamsTenantResponse:
    """Persist (or upsert) the tenant record from the teams-bridge.

    Upserts on ``tenant_id``. On conflict:
      * ``tenant_name`` refreshed (operator may have renamed the org).
      * ``installer_oid`` refreshed (a different admin may be
        reinstalling).
      * ``deleted_at`` reset to NULL.
      * ``installed_at`` stays at the original install time.
    """

    existing = (
        await db.execute(select(TeamsTenant).where(TeamsTenant.tenant_id == body.tenant_id))
    ).scalar_one_or_none()

    if existing is None:
        tenant = TeamsTenant(
            tenant_id=body.tenant_id,
            tenant_name=body.tenant_name,
            installer_oid=body.installer_oid,
        )
        db.add(tenant)
    else:
        existing.tenant_name = body.tenant_name
        existing.installer_oid = body.installer_oid
        existing.deleted_at = None
        tenant = existing

    await db.commit()
    await db.refresh(tenant)
    return TeamsTenantResponse.model_validate(tenant)
