"""Admin intake-bridges surface — M3-D4.

Backs the SvelteKit admin page at ``/lq-ai/admin/intake-bridges``
(M3-D4 frontend). Operators see what's currently connected and can
soft-delete a bridge install (which causes the next OAuth re-install
flow on that workspace/tenant to revive the row with fresh
credentials per the M3-D1/M3-D3 upsert semantics).

Surface (M3 scope — plumbing only):

* ``GET    /api/v1/admin/intake-bridges`` — list connected
  Slack workspaces + Teams tenants (live, non-soft-deleted only).
* ``DELETE /api/v1/admin/intake-bridges/slack/{workspace_id}``
  — soft-delete a Slack workspace.
* ``DELETE /api/v1/admin/intake-bridges/teams/{tenant_id}``
  — soft-delete a Teams tenant.

The "configure quick-ask skill" dropdown UI and the ``/lq``
invocation audit-log surface land with DE-288's slash-command work;
no API endpoints for those are needed at v0.3.0 because there's no
slash-command behavior to configure yet.

Auth posture: every endpoint here stacks on ``ActiveUser`` (bearer +
must-change-password gate, mounted at the router level in
:mod:`app.api`) PLUS the ``AdminUser`` dependency at handler level.
Non-admin authenticated users see 403 with ``code="forbidden"``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AdminUser
from app.db.session import get_db
from app.errors import NotFound
from app.models.slack_workspace import SlackWorkspace
from app.models.teams_tenant import TeamsTenant
from app.schemas.intake_bridges import (
    IntakeBridgesList,
    SlackWorkspaceSummary,
    TeamsTenantSummary,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/intake-bridges", tags=["admin-intake-bridges"])


@router.get("", response_model=IntakeBridgesList)
async def list_intake_bridges(
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IntakeBridgesList:
    """Return live (non-soft-deleted) Slack workspaces + Teams tenants.

    Sorted by ``installed_at DESC`` within each section so the most
    recently connected bridge surfaces first.
    """

    slack_rows = (
        (
            await db.execute(
                select(SlackWorkspace)
                .where(SlackWorkspace.deleted_at.is_(None))
                .order_by(SlackWorkspace.installed_at.desc())
            )
        )
        .scalars()
        .all()
    )
    teams_rows = (
        (
            await db.execute(
                select(TeamsTenant)
                .where(TeamsTenant.deleted_at.is_(None))
                .order_by(TeamsTenant.installed_at.desc())
            )
        )
        .scalars()
        .all()
    )

    return IntakeBridgesList(
        slack_workspaces=[SlackWorkspaceSummary.model_validate(row) for row in slack_rows],
        teams_tenants=[TeamsTenantSummary.model_validate(row) for row in teams_rows],
    )


@router.delete(
    "/slack/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def soft_delete_slack_workspace(
    _admin: AdminUser,
    workspace_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Soft-delete a Slack workspace by api-side id.

    Sets ``deleted_at`` to now. The row stays in the DB so a re-install
    via the slack-bridge OAuth flow revives it in place (per the
    M3-D1 upsert semantics) rather than losing the install history.

    ``response_class=Response`` + explicit ``Response(status_code=204)``
    is the M3-C2 pattern — without it, FastAPI's default JSONResponse
    fails the import-time "204 must not have body" assertion and
    blows up the whole test suite at collection.
    """

    row = (
        await db.execute(select(SlackWorkspace).where(SlackWorkspace.id == workspace_id))
    ).scalar_one_or_none()
    if row is None or row.deleted_at is not None:
        raise NotFound(
            message="Slack workspace not found or already disconnected.",
            details={"workspace_id": str(workspace_id)},
        )
    row.deleted_at = datetime.now(tz=UTC)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/teams/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def soft_delete_teams_tenant(
    _admin: AdminUser,
    tenant_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Soft-delete a Teams tenant by api-side id.

    Same posture as ``soft_delete_slack_workspace`` — the row stays so
    a re-install via the teams-bridge OAuth flow revives it in place.
    """

    row = (
        await db.execute(select(TeamsTenant).where(TeamsTenant.id == tenant_id))
    ).scalar_one_or_none()
    if row is None or row.deleted_at is not None:
        raise NotFound(
            message="Teams tenant not found or already disconnected.",
            details={"tenant_id": str(tenant_id)},
        )
    row.deleted_at = datetime.now(tz=UTC)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
