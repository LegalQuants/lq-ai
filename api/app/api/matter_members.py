"""Matter membership endpoints — who is on a matter, and in what capacity.

A matter is a ``projects`` row (ADR 0020 D3), so this is the roster surface
for ``project_members`` (migration 0067). PRD §3.11 named
``POST /api/v1/projects/{id}/share`` and listed ``share_scope`` in the
Project data model; §3.11's M1 status recorded share-with-group as
deferred. This module lands that surface, shaped as a roster rather than a
one-shot share call so the answer to "who was on this matter, and who put
them there" is a table, not an inference from an event log.

Structurally this mirrors :mod:`app.api.teams` — same response shape, same
``_list_members`` join, same "audit row in the same transaction as the
state change" convention. The mirroring is deliberate: a reviewer who
knows the team surface already knows this one, and a future
``project_teams`` join slots in without a second vocabulary.

Two differences from teams, both load-bearing:

* **Leads manage their own matters.** Team membership is operator-admin
  only; matter membership is managed by the matter's leads (and by
  operator-admins). A firm's partners staff their own matters without
  filing a ticket.
* **``blocked`` is a role.** Adding someone at ``blocked`` erects an
  ethical screen: :func:`app.authz.matters.matter_access` evaluates it
  before every allow, so it overrides firm-wide scope and operator-admin
  alike. The endpoints call it *screened* in prose because that is the
  term of art a lawyer will recognise.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.authz.matters import matter_access, require_matter
from app.db.session import get_db
from app.models.project import Project
from app.models.project_member import MEMBER_ROLES, ProjectMember
from app.models.user import User

router = APIRouter(prefix="/projects", tags=["projects", "matters"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class MatterMemberResponse(BaseModel):
    """One row of a matter's roster."""

    user_id: uuid.UUID
    email: str
    display_name: str | None = None
    role: str
    is_owner: bool = False
    added_by_user_id: uuid.UUID
    created_at: datetime


class MatterMemberAdd(BaseModel):
    user_id: uuid.UUID
    role: str = "contributor"


class MatterMemberRoleUpdate(BaseModel):
    role: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_role(role: str) -> str:
    if role not in MEMBER_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"role must be one of {sorted(MEMBER_ROLES)}",
        )
    return role


async def _require_manage(
    db: AsyncSession,
    project_id: uuid.UUID,
    user: User,
) -> Project:
    """Load the matter and assert the caller may change its roster.

    Leads manage their own matters; operator-admins manage any matter they
    are not screened off. ``require_matter(need="lead")`` covers both — an
    admin who is not a lead resolves to ``read`` and gets the 403, which is
    correct: staffing a matter is the leads' call, and an operator who
    needs to intervene can make themselves a lead and leave that act in the
    audit log rather than acting invisibly.
    """
    return await require_matter(db, project_id, user, need="lead", include_archived=True)


async def _list_members(db: AsyncSession, project: Project) -> list[MatterMemberResponse]:
    """Join ``project_members`` → ``users`` so each row carries display info."""

    stmt = (
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project.id)
        .order_by(ProjectMember.created_at.asc(), User.email.asc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        MatterMemberResponse(
            user_id=member.id,
            email=member.email,
            display_name=member.display_name,
            role=membership.role,
            is_owner=member.id == project.owner_id,
            added_by_user_id=membership.added_by_user_id,
            created_at=membership.created_at,
        )
        for membership, member in rows
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/members",
    response_model=list[MatterMemberResponse],
    summary="List the people on a matter",
)
async def list_members(
    project_id: uuid.UUID,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[MatterMemberResponse]:
    """Anyone who can read the matter can see who else is on it.

    Withholding the roster from readers would make the collaboration
    surface unusable — you cannot see who authored the thread you are
    reading — and it protects nothing, since those people's work product
    is already visible to the same caller.
    """
    project = await require_matter(db, project_id, user, include_archived=True)
    return await _list_members(db, project)


@router.post(
    "/{project_id}/members",
    response_model=MatterMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add someone to a matter (or screen them off it)",
)
async def add_member(
    project_id: uuid.UUID,
    payload: MatterMemberAdd,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MatterMemberResponse:
    """Add a roster row. ``role='blocked'`` erects an ethical screen.

    A screen is stored as an ordinary membership row so the roster answers
    both halves of the question a conflicts check asks: who may see this
    matter, and who explicitly may not.
    """
    project = await _require_manage(db, project_id, user)
    role = _validate_role(payload.role)

    target = await db.get(User, payload.user_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    if target.id == project.owner_id and role != "lead":
        # The owner's access does not flow from their roster row (the
        # resolver short-circuits on ownership), so a demotion here would
        # be a row that lies about who can do what.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the matter owner is always lead; transfer ownership to change this",
        )

    membership = ProjectMember(
        project_id=project.id,
        user_id=target.id,
        role=role,
        added_by_user_id=user.id,
    )
    db.add(membership)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that person already has a role on this matter",
        ) from None

    await audit_action(
        db,
        user_id=user.id,
        action="matter.member_added",
        resource_type="project",
        resource_id=str(project.id),
        request=request,
        project=project,
        details={
            "user_id": str(target.id),
            "user_email": target.email,
            "role": role,
        },
    )
    await db.commit()
    await db.refresh(membership)

    return MatterMemberResponse(
        user_id=target.id,
        email=target.email,
        display_name=target.display_name,
        role=membership.role,
        is_owner=target.id == project.owner_id,
        added_by_user_id=membership.added_by_user_id,
        created_at=membership.created_at,
    )


@router.patch(
    "/{project_id}/members/{user_id}",
    response_model=MatterMemberResponse,
    summary="Change someone's role on a matter",
)
async def update_member_role(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MatterMemberRoleUpdate,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MatterMemberResponse:
    """Move a roster row between roles, including to and from ``blocked``.

    The audit row carries before/after so "when was this person screened
    off, and by whom" is answerable from the log alone — the same
    before/after convention ``team.member_role_updated`` uses.
    """
    project = await _require_manage(db, project_id, user)
    role = _validate_role(payload.role)

    membership = (
        await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membership not found")

    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    if user_id == project.owner_id and role != "lead":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the matter owner is always lead; transfer ownership to change this",
        )

    before_role = membership.role
    if before_role == role:
        return MatterMemberResponse(
            user_id=target.id,
            email=target.email,
            display_name=target.display_name,
            role=membership.role,
            is_owner=target.id == project.owner_id,
            added_by_user_id=membership.added_by_user_id,
            created_at=membership.created_at,
        )

    membership.role = role

    await audit_action(
        db,
        user_id=user.id,
        action="matter.member_role_updated",
        resource_type="project",
        resource_id=str(project.id),
        request=request,
        project=project,
        details={
            "user_id": str(target.id),
            "user_email": target.email,
            "before": {"role": before_role},
            "after": {"role": role},
        },
    )
    await db.commit()
    await db.refresh(membership)

    return MatterMemberResponse(
        user_id=target.id,
        email=target.email,
        display_name=target.display_name,
        role=membership.role,
        is_owner=target.id == project.owner_id,
        added_by_user_id=membership.added_by_user_id,
        created_at=membership.created_at,
    )


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Remove someone from a matter",
)
async def remove_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Drop a roster row.

    Removing a ``blocked`` row *lifts a screen* — it is the one deletion
    here that widens access, so the audit row records the role the person
    held at removal rather than just the fact of it.

    The owner's row cannot be removed: their access does not depend on it,
    so deleting it would only make the roster lie.
    """
    project = await _require_manage(db, project_id, user)

    if user_id == project.owner_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the matter owner cannot be removed; transfer ownership instead",
        )

    membership = (
        await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membership not found")

    role_at_removal = membership.role
    target = await db.get(User, user_id)
    await db.delete(membership)

    await audit_action(
        db,
        user_id=user.id,
        action="matter.member_removed",
        resource_type="project",
        resource_id=str(project.id),
        request=request,
        project=project,
        details={
            "user_id": str(user_id),
            "user_email": target.email if target is not None else None,
            "role_at_removal": role_at_removal,
            "lifted_screen": role_at_removal == "blocked",
        },
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{project_id}/access",
    summary="What the caller may do on this matter, and why",
)
async def get_caller_access(
    project_id: uuid.UUID,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Resolve the caller's own access.

    ``ProjectResponse`` already carries ``caller_access``, so the UI rarely
    needs this; it exists for clients that hold only a matter id (a
    deep-link, a bridge) and want to decide what to render before fetching
    the matter itself.
    """
    project = await require_matter(db, project_id, user, include_archived=True)
    access, basis = await matter_access(db, project, user)
    return {"project_id": str(project.id), "caller_access": access, "basis": basis}
