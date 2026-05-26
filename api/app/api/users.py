"""Users endpoints — Task B1 + D6.

`/users/me` (B1) returns the calling user's public profile.

D6 lands the GDPR Article 17 / 20 surface:

* `POST /api/v1/users/me/export` queues an export job; the worker
  builds a ZIP of the user's data and uploads it to MinIO. Returns
  202 with `{job_id, status}`.
* `GET  /api/v1/users/me/export/{job_id}` polls a job. When complete,
  returns a presigned download URL good for 24 hours.
* `POST /api/v1/users/me/delete` schedules account deletion: sets
  `deletion_scheduled_at = now() + grace_period_days`, revokes all
  active sessions, audit-logs the request. Idempotent — re-calling
  returns the existing schedule rather than pushing it back.
* `POST /api/v1/users/me/delete/cancel` clears a pending deletion
  during the grace period.

Hard delete itself happens in the daily worker cron
(`app.workers.user_deletion.hard_delete_due_users_job`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import UserPublic
from app.api.dependencies import ActiveUser, CurrentUser, get_active_user
from app.audit import audit_action
from app.config import get_settings
from app.db.session import get_db
from app.models.user import UserSession
from app.models.user_export import UserExportJob
from app.storage import presigned_get_url
from app.workers.queue import enqueue_user_export_job

router = APIRouter(prefix="/users", tags=["users"])

# Presigned download URL TTL for completed export bundles. 24 hours
# matches the brief and keeps the URL useful across timezone changes
# without leaving it valid long enough to be inadvertently shared.
_DOWNLOAD_URL_TTL_SECONDS = 24 * 3600


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ExportJobResponse(BaseModel):
    """Shared shape for POST /users/me/export and GET /users/me/export/{id}.

    The ``download_url`` is populated only when ``status == 'completed'``
    and the bundle has not yet expired.
    """

    job_id: str
    status: str
    download_url: str | None = None


class DeleteScheduledResponse(BaseModel):
    """Body for POST /users/me/delete (and the idempotent rerun)."""

    scheduled_deletion_at: datetime
    grace_period_days: int


# PRD §3.2 — Enhance Prompt reasoning visibility values.
ReasoningVisibility = Literal["always_show", "disclosure", "on_request"]

# PRD §3.2.1 + frontend spec §4.3 (Wave B v2) — personalization preference types.
# Defaults are the "brave choices": more visible, more orienting; veterans dial
# back via the Settings/Appearance page.
FeaturedTools = Literal["prominent", "inline"]
WorkspaceLayout = Literal["three_pane", "two_pane", "one_pane"]
TrustPills = Literal["labels", "dots"]
ProvenancePills = Literal["always", "collapsed"]


class UserPreferencesUpdate(BaseModel):
    """PATCH body for ``/users/me/preferences`` — all fields optional.

    Structured as a forward-compatible preferences object: future Wave A+
    preferences (e.g., default jurisdiction, default model) ride here
    rather than each getting its own endpoint.
    """

    reasoning_visibility: ReasoningVisibility | None = None
    # Wave B v2 personalization fields (frontend spec §4.3 / PRD §3.2.1)
    featured_tools: FeaturedTools | None = None
    workspace_layout: WorkspaceLayout | None = None
    trust_pills: TrustPills | None = None
    provenance_pills: ProvenancePills | None = None
    # M4-C2 — Autonomous Layer opt-in (off by default)
    autonomous_enabled: bool | None = None


class UserPreferencesResponse(BaseModel):
    """The preferences slice of the user profile.

    Mirror of the corresponding fields on ``UserPublic`` so the frontend
    can subscribe to preferences without watching the whole user object.
    """

    reasoning_visibility: ReasoningVisibility
    # Wave B v2 personalization fields (frontend spec §4.3 / PRD §3.2.1)
    featured_tools: FeaturedTools
    workspace_layout: WorkspaceLayout
    trust_pills: TrustPills
    provenance_pills: ProvenancePills
    # M4-C2 — Autonomous Layer opt-in (off by default)
    autonomous_enabled: bool


# ---------------------------------------------------------------------------
# /users/me
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=UserPublic,
    summary="Get current user",
)
async def get_me(user: CurrentUser) -> UserPublic:
    """GET /api/v1/users/me — return the calling user's public profile.

    Reachable while `must_change_password=true` so the client can read the
    flag and route to the change-password flow. Other authenticated
    endpoints are gated until the user clears it.
    """

    return UserPublic.from_user(user)


@router.get(
    "/me/preferences",
    response_model=UserPreferencesResponse,
    summary="Read the calling user's preferences (Wave A: reasoning_visibility)",
)
async def get_me_preferences(user: ActiveUser) -> UserPreferencesResponse:
    """GET /api/v1/users/me/preferences — preferences slice of the profile.

    Returns the same data ``GET /users/me`` does for the preferences
    fields; this dedicated endpoint exists so frontends can subscribe
    to preferences changes without re-fetching the whole user object.
    """

    return UserPreferencesResponse(
        reasoning_visibility=getattr(user, "reasoning_visibility", "disclosure"),
        featured_tools=getattr(user, "featured_tools", "prominent"),
        workspace_layout=getattr(user, "workspace_layout", "three_pane"),
        trust_pills=getattr(user, "trust_pills", "labels"),
        provenance_pills=getattr(user, "provenance_pills", "always"),
        autonomous_enabled=getattr(user, "autonomous_enabled", False),
    )


@router.patch(
    "/me/preferences",
    response_model=UserPreferencesResponse,
    summary="Update the calling user's preferences (partial)",
)
async def patch_me_preferences(
    payload: UserPreferencesUpdate,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserPreferencesResponse:
    """PATCH /api/v1/users/me/preferences — partial update.

    Only the fields the user actually supplies move. An idempotent
    PATCH (same value re-supplied) returns 200 without writing an
    audit row, matching the user_skills / saved_prompts pattern.
    Writes ``user.preferences_updated`` audit rows when anything
    actually changes, with details enumerating the changed fields and
    before/after values (so a privacy audit can reconstruct the
    preference history).
    """

    from app.models.user import User as UserORM  # local — only writer needs it

    # Reload to ensure we see the persisted row (the ActiveUser dependency
    # returns a refreshed instance, but we want explicit reload semantics
    # before mutating).
    row = await db.get(UserORM, user.id)
    if row is None:  # pragma: no cover — dependency would have already 401d
        raise HTTPException(status_code=404, detail="user not found")

    # Annotate `before`/`after` as `str` so mypy doesn't narrow them to
    # the first block's Literal type and then reject subsequent blocks.
    # The DB CHECK enforces the actual enum.
    changed: dict[str, dict[str, str]] = {}
    before: str
    after: str
    if payload.reasoning_visibility is not None:
        before = row.reasoning_visibility
        after = payload.reasoning_visibility
        if before != after:
            row.reasoning_visibility = after
            changed["reasoning_visibility"] = {"before": before, "after": after}

    if payload.featured_tools is not None:
        before = row.featured_tools
        after = payload.featured_tools
        if before != after:
            row.featured_tools = after
            changed["featured_tools"] = {"before": before, "after": after}

    if payload.workspace_layout is not None:
        before = row.workspace_layout
        after = payload.workspace_layout
        if before != after:
            row.workspace_layout = after
            changed["workspace_layout"] = {"before": before, "after": after}

    if payload.trust_pills is not None:
        before = row.trust_pills
        after = payload.trust_pills
        if before != after:
            row.trust_pills = after
            changed["trust_pills"] = {"before": before, "after": after}

    if payload.provenance_pills is not None:
        before = row.provenance_pills
        after = payload.provenance_pills
        if before != after:
            row.provenance_pills = after
            changed["provenance_pills"] = {"before": before, "after": after}

    if payload.autonomous_enabled is not None:
        before = str(row.autonomous_enabled)
        after = str(payload.autonomous_enabled)
        if before != after:
            row.autonomous_enabled = payload.autonomous_enabled
            changed["autonomous_enabled"] = {"before": before, "after": after}

    if not changed:
        return UserPreferencesResponse(
            reasoning_visibility=row.reasoning_visibility,
            featured_tools=row.featured_tools,
            workspace_layout=row.workspace_layout,
            trust_pills=row.trust_pills,
            provenance_pills=row.provenance_pills,
            autonomous_enabled=row.autonomous_enabled,
        )

    await audit_action(
        db,
        user_id=row.id,
        action="user.preferences_updated",
        resource_type="user",
        resource_id=str(row.id),
        request=request,
        details={"changes": changed},
    )
    await db.commit()
    await db.refresh(row)

    return UserPreferencesResponse(
        reasoning_visibility=row.reasoning_visibility,
        featured_tools=row.featured_tools,
        workspace_layout=row.workspace_layout,
        trust_pills=row.trust_pills,
        provenance_pills=row.provenance_pills,
        autonomous_enabled=row.autonomous_enabled,
    )


# ---------------------------------------------------------------------------
# /users/me/export — D6 GDPR Article 20
# ---------------------------------------------------------------------------


@router.post(
    "/me/export",
    response_model=ExportJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(get_active_user)],
    summary="Queue a per-user data export",
)
async def export_me(
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExportJobResponse:
    """POST /api/v1/users/me/export — async; returns a job id for polling.

    Inserts a `user_export_jobs` row with status='queued', enqueues the
    arq worker job, and returns 202. The worker runs the ZIP build +
    MinIO upload out-of-band.

    Re-calling while a queued/processing job exists is allowed —
    operators may want a fresh export after deleting some content.
    The two jobs run independently.
    """

    job = UserExportJob(user_id=user.id, status="queued")
    db.add(job)
    await db.flush()

    await audit_action(
        db,
        user_id=user.id,
        action="user.export_requested",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
        details={"job_id": str(job.id)},
    )
    await db.commit()

    await enqueue_user_export_job(job.id)

    return ExportJobResponse(job_id=str(job.id), status=job.status, download_url=None)


@router.get(
    "/me/export/{job_id}",
    response_model=ExportJobResponse,
    dependencies=[Depends(get_active_user)],
    summary="Poll a user-export job",
)
async def get_export_job(
    job_id: str,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExportJobResponse:
    """GET /api/v1/users/me/export/{job_id}.

    Returns 404 if the job doesn't exist or belongs to another user
    (don't leak existence cross-user). On a completed job, returns a
    presigned download URL valid for 24h. On a job whose bundle has
    expired (storage_key cleared by the GC cron), the response carries
    no URL and the status remains 'completed' for audit clarity — the
    caller can re-request export to get a fresh bundle.
    """

    try:
        job_uuid = uuid.UUID(job_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Export job not found"
        ) from None

    job = await db.get(UserExportJob, job_uuid)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export job not found")

    download_url: str | None = None
    if job.status == "completed" and job.storage_key:
        download_url = await presigned_get_url(
            storage_path=job.storage_key,
            expires_in_seconds=_DOWNLOAD_URL_TTL_SECONDS,
        )

    return ExportJobResponse(
        job_id=str(job.id),
        status=job.status,
        download_url=download_url,
    )


# ---------------------------------------------------------------------------
# /users/me/delete — D6 GDPR Article 17
# ---------------------------------------------------------------------------


@router.post(
    "/me/delete",
    response_model=DeleteScheduledResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(get_active_user)],
    summary="Schedule account deletion (GDPR Article 17)",
)
async def delete_me(
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DeleteScheduledResponse:
    """POST /api/v1/users/me/delete — soft-schedule with a grace period.

    Idempotent: if the user already has a pending deletion the existing
    schedule is returned. This prevents accidental "extension" of the
    grace period via repeated calls.

    Side-effects:

    1. ``deletion_scheduled_at = now() + gdpr_grace_period_days``.
    2. All of the user's active ``user_sessions`` are revoked. The user
       can still log in during the grace period (to call cancel) — the
       gate is on ``deleted_at``, not ``deletion_scheduled_at``.
    3. An ``audit_log`` row records the request.

    Login during the grace period is preserved so the user retains the
    ability to cancel; hard delete itself runs in the daily worker
    cron.
    """

    settings = get_settings()
    grace = settings.gdpr_grace_period_days

    if user.deletion_scheduled_at is not None:
        return DeleteScheduledResponse(
            scheduled_deletion_at=user.deletion_scheduled_at,
            grace_period_days=grace,
        )

    scheduled = _utcnow() + timedelta(days=grace)
    user.deletion_scheduled_at = scheduled

    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_utcnow())
    )

    await audit_action(
        db,
        user_id=user.id,
        action="user.deletion_scheduled",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
        details={
            "scheduled_deletion_at": scheduled.isoformat(),
            "grace_period_days": grace,
        },
    )
    await db.commit()

    return DeleteScheduledResponse(
        scheduled_deletion_at=scheduled,
        grace_period_days=grace,
    )


@router.post(
    "/me/delete/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(get_active_user)],
    summary="Cancel a pending account deletion",
)
async def cancel_delete_me(
    request: Request,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """POST /api/v1/users/me/delete/cancel — clear a pending schedule.

    Returns 400 if there is no pending deletion. The grace-period
    window itself is the only valid cancel surface — once the worker
    has hard-deleted the user, there is no row to recover.
    """

    if user.deletion_scheduled_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending deletion to cancel.",
        )

    user.deletion_scheduled_at = None
    await audit_action(
        db,
        user_id=user.id,
        action="user.deletion_cancelled",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
    )
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
