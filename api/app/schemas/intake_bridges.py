"""Pydantic wire shapes for the admin intake-bridges surface — M3-D4.

Used by ``GET /api/v1/admin/intake-bridges`` to surface what's
currently connected in the LQ.AI admin UI. The shapes are deliberately
section-split (slack_workspaces + teams_tenants) rather than a single
polymorphic list because the UI renders two distinct sections
(per [M3-D4 plan](../../docs/M3-IMPLEMENTATION-PLAN.md#task-m3-d4--bot-configuration-in-lqai-admin-ui))
and a section-split shape lets the client render directly without
discriminator-key gymnastics.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SlackWorkspaceSummary(BaseModel):
    """One live Slack workspace install for the admin list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    team_id: str
    team_name: str
    installer_slack_user_id: str
    installed_at: datetime


class TeamsTenantSummary(BaseModel):
    """One live Teams tenant install for the admin list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: str
    tenant_name: str
    installer_oid: str
    installed_at: datetime


class IntakeBridgesList(BaseModel):
    """Section-split response for the admin intake-bridges list."""

    slack_workspaces: list[SlackWorkspaceSummary]
    teams_tenants: list[TeamsTenantSummary]
