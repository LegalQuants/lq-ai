"""Projects endpoints — Task C7 (Project service).

Surface (per ``docs/api/backend-openapi.yaml``):

* ``POST   /api/v1/projects``                          — create.
* ``GET    /api/v1/projects?archived=true|false``      — list (default
  excludes archived; ``archived=true`` returns archived only;
  ``archived=`` (absent) returns active only).
* ``GET    /api/v1/projects/{project_id}``             — fetch single
  including attached file ids and skill names.
* ``PATCH  /api/v1/projects/{project_id}``             — partial update
  (name, slug, description, context_md, privileged,
  minimum_inference_tier, archived).
* ``DELETE /api/v1/projects/{project_id}``             — soft-delete
  (set ``archived_at``); idempotent — already-archived returns 404.

* ``POST   /api/v1/projects/{project_id}/files``       — attach a file
  (body: ``{file_id}``).
* ``DELETE /api/v1/projects/{project_id}/files/{file_id}`` — detach.

* ``POST   /api/v1/projects/{project_id}/skills``      — attach a skill
  by name; validates the skill exists in the in-memory registry.
* ``DELETE /api/v1/projects/{project_id}/skills/{skill_name}`` — detach.

* ``POST   /api/v1/projects/{project_id}/knowledge-bases`` — attach a KB
  by id (body: ``{knowledge_base_id}``). Idempotent — re-attaching is a
  no-op 200. Owner-only on both project and KB.
* ``DELETE /api/v1/projects/{project_id}/knowledge-bases/{kb_id}`` — detach.
  Idempotent — detaching a non-attached KB returns 204.

All endpoints inherit the auth+gate from the router-level
``Depends(get_active_user)`` in ``app.api.__init__`` (B2 pattern). Each
handler also takes ``ActiveUser`` directly so the user object is
available for ``owner_id`` checks (FastAPI dedupes the dependency).

**Per-user isolation.** Projects are scoped to ``owner_id``. Cross-user
access returns 404, not 403, to avoid leaking existence (same posture
as C4 / files). File attachment requires the user to own *both* the
project AND the file. Skill attachment is registry-wide so any
authenticated user may attach any registered skill (skills are
filesystem-canonical per ADR 0004).

**Privileged constraint.** ``privileged=true`` requires
``minimum_inference_tier`` to be set. Enforced at three layers:
(1) the ``ProjectCreateRequest`` model rejects on create; (2) the PATCH
handler validates the merged state; (3) the DB CHECK constraint
``chk_projects_privileged_implies_tier`` is the safety net.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.authz.matters import (
    MatterAccess,
    matter_access,
    matter_access_map,
    matter_scope_filter,
    require_matter,
)
from app.config import get_settings
from app.db.session import get_db
from app.errors import Conflict, Forbidden, NotFound, ValidationError
from app.models.file import File as FileModel
from app.models.knowledge import KnowledgeBase
from app.models.project import Project, ProjectFile, ProjectSkill
from app.models.project_knowledge_base import ProjectKnowledgeBase
from app.models.project_member import ProjectMember
from app.models.user import User
from app.schemas.projects import (
    SLUG_RE,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    slugify,
)
from app.skills.registry import MutableSkillRegistry

router = APIRouter(prefix="/projects", tags=["projects"])
log = logging.getLogger(__name__)

# Wave D.2 Task 2.1 — slugs matching ``^__[a-z0-9-]+__$`` are reserved for
# system-managed matters (sandbox today; potentially other internal scopes
# later). User-supplied slugs in this family are rejected with 422 in the
# create handler. The sandbox-ensure endpoint (Task 2.2) constructs its
# slug internally and bypasses this check.
_RESERVED_SLUG_RE: re.Pattern[str] = re.compile(r"^__[a-z0-9-]+__$")


# ---------------------------------------------------------------------------
# Request bodies for attachment endpoints
# ---------------------------------------------------------------------------


class AttachFileRequest(BaseModel):
    """``POST /api/v1/projects/{id}/files`` body."""

    file_id: uuid.UUID


class AttachSkillRequest(BaseModel):
    """``POST /api/v1/projects/{id}/skills`` body."""

    skill_name: str = Field(min_length=1, max_length=200)


class AttachKnowledgeBaseRequest(BaseModel):
    """``POST /api/v1/projects/{id}/knowledge-bases`` body."""

    knowledge_base_id: uuid.UUID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_project_id(project_id: str) -> uuid.UUID:
    """Reject non-UUID project ids per the OpenAPI sketch's ``{project_id}: uuid``."""

    try:
        return uuid.UUID(project_id)
    except ValueError as exc:
        raise ValidationError(
            "project_id must be a UUID",
            details={"project_id": project_id},
        ) from exc


async def _load_visible_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    user: User,
    *,
    need: MatterAccess = "read",
    include_archived: bool = False,
) -> Project:
    """Load a matter the caller may act on at ``need``; 404 on miss / no access.

    Thin wrapper over :func:`app.authz.matters.require_matter`, kept so the
    call sites in this module read the way they did when the rule was
    ``owner_id == caller``. The rule itself now lives in one place, because
    a matter reaches its members too (migration 0067) and a predicate
    duplicated across nine handlers is a leak waiting for the one handler
    that forgets it.

    The no-access case still collapses into 404 deliberately — same posture
    as C4 (files) — so an id probe cannot distinguish "no such matter" from
    "not yours". Archived projects stay invisible by default; pass
    ``include_archived=True`` to surface them (used by the unarchive PATCH
    path so a caller can see and act on archived rows).
    """

    return await require_matter(
        db,
        project_id,
        user,
        need=need,
        include_archived=include_archived,
    )


async def _load_visible_file(
    db: AsyncSession,
    file_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> FileModel:
    """Load a file row scoped to the caller; 404 on miss / cross-user.

    Reuses the C4 file-visibility rule: the user must own the file and
    the file must not be soft-deleted.
    """

    stmt = select(FileModel).where(
        FileModel.id == file_id,
        FileModel.owner_id == owner_id,
        FileModel.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFound(
            f"File {file_id} not found.",
            details={"file_id": str(file_id)},
        )
    return row


async def _load_attached_file_ids(db: AsyncSession, project_id: uuid.UUID) -> list[uuid.UUID]:
    """Return file ids attached to a project, ordered by ``attached_at``."""

    stmt = (
        select(ProjectFile.file_id)
        .where(ProjectFile.project_id == project_id)
        .order_by(ProjectFile.attached_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _load_attached_skill_names(db: AsyncSession, project_id: uuid.UUID) -> list[str]:
    """Return skill names attached to a project, ordered by ``attached_at``."""

    stmt = (
        select(ProjectSkill.skill_name)
        .where(ProjectSkill.project_id == project_id)
        .order_by(ProjectSkill.attached_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _load_attached_kb_ids(db: AsyncSession, project_id: uuid.UUID) -> list[uuid.UUID]:
    """Return knowledge-base ids attached to a project, ordered by ``attached_at``."""

    stmt = (
        select(ProjectKnowledgeBase.knowledge_base_id)
        .where(ProjectKnowledgeBase.project_id == project_id)
        .order_by(ProjectKnowledgeBase.attached_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _serialize_project(
    db: AsyncSession,
    project: Project,
    user: User,
    *,
    access: tuple[MatterAccess, str] | None = None,
) -> ProjectResponse:
    """Build the ``ProjectResponse`` shape for a row.

    Extra round-trips: attached file ids, attached skill names, attached KB
    ids, and the caller's effective access. Cheap on the M1 footprint (a
    matter has a handful of attachments, not hundreds); a future
    optimisation could JOIN them in if it shows up in production.

    ``user`` is required rather than defaulted: ``caller_access`` is what
    the UI gates its affordances on, so a default would be a value that
    looks authoritative and is not. ``access`` lets a list endpoint hand in
    a pre-resolved answer from :func:`matter_access_map` so the listing
    costs one membership query rather than one per row.
    """

    file_ids = await _load_attached_file_ids(db, project.id)
    skill_names = await _load_attached_skill_names(db, project.id)
    kb_ids = await _load_attached_kb_ids(db, project.id)
    resolved_access, basis = access or await matter_access(db, project, user)
    return ProjectResponse(
        id=project.id,
        owner_id=project.owner_id,
        name=project.name,
        slug=project.slug,
        description=project.description,
        context_md=project.context_md,
        privileged=project.privileged,
        minimum_inference_tier=project.minimum_inference_tier,
        is_sandbox=project.is_sandbox,
        share_scope=project.share_scope,
        caller_access=resolved_access,
        caller_access_basis=basis,
        attached_file_ids=file_ids,
        attached_skill_names=skill_names,
        attached_knowledge_base_ids=kb_ids,
        archived_at=project.archived_at,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


async def _resolve_unique_slug(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    desired: str,
    exclude_project_id: uuid.UUID | None = None,
) -> str:
    """Return ``desired`` if free for the owner, else suffix with ``-2``, ``-3``, …

    ``exclude_project_id`` lets the PATCH path keep the project's own
    current slug without colliding with itself.
    """

    candidate = desired
    suffix = 2
    while True:
        stmt = select(Project.id).where(
            Project.owner_id == owner_id,
            Project.slug == candidate,
            Project.archived_at.is_(None),
        )
        if exclude_project_id is not None:
            stmt = stmt.where(Project.id != exclude_project_id)
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            return candidate
        # Trim to fit the slug-length cap when adding a suffix.
        from app.schemas.projects import SLUG_MAX_LEN

        suffix_str = f"-{suffix}"
        head = desired[: SLUG_MAX_LEN - len(suffix_str)]
        candidate = f"{head}{suffix_str}"
        suffix += 1


def _check_slug_not_reserved(slug: str) -> None:
    """Reject slugs matching the reserved ``__*__`` family with 422.

    Wave D.2 Task 2.1. The reservation is enforced on user-driven create
    paths only — system-managed scopes (e.g., the per-user try-it sandbox
    created by ``POST /projects/sandbox/ensure``) construct their slug
    internally and don't call this helper.

    Raises a plain :class:`fastapi.HTTPException` rather than an
    :class:`app.errors.LQAIError` subclass so the response body renders
    as the conventional ``{"detail": "<message>"}`` string shape that the
    Wave D.2 frontend wizard expects when surfacing the error inline.
    """

    if _RESERVED_SLUG_RE.match(slug):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Slug pattern '__*__' is reserved for system-managed matters; '{slug}' rejected."
            ),
        )


def _registry(request: Request) -> MutableSkillRegistry:
    """Return the live in-memory skill registry from app state.

    Mirrors the helper in :mod:`app.api.skills`. Surfaces a typed
    InternalError if the lifespan handler hasn't installed the registry
    (this is a wiring bug, not a user error).
    """

    holder: MutableSkillRegistry | None = getattr(request.app.state, "skill_registry", None)
    if holder is None:
        from app.errors import InternalError

        raise InternalError(
            message="Skill registry is not initialised; the API process is "
            "not yet ready to serve project skill attachments.",
            details={"hint": "lifespan startup did not run"},
        )
    return holder


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
    description=(
        "Create a new project owned by the caller. ``slug`` is generated "
        "from ``name`` if omitted; collisions with the caller's existing "
        "active projects are resolved with a numeric suffix (``-2``, "
        "``-3``, …). Returns the canonical ``Project`` shape."
    ),
)
async def create_project(
    payload: ProjectCreateRequest,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    # Wave D.2 Task 2.1 — reject the reserved ``__*__`` slug family before
    # we generate or resolve a slug. Only user-supplied slugs can land in
    # the reserved family; ``slugify`` itself never emits underscores.
    if payload.slug is not None:
        _check_slug_not_reserved(payload.slug)
    desired_slug = payload.slug or slugify(payload.name)
    final_slug = await _resolve_unique_slug(db, owner_id=user.id, desired=desired_slug)

    # An unset share_scope takes the deployment default. Upstream ships
    # ``personal`` (fail-restrictive, ADR 0016 P4); a firm where ambient
    # visibility is the working assumption sets ``org`` and treats an
    # ethical screen as the exception.
    share_scope = payload.share_scope or get_settings().lq_ai_matter_default_share_scope

    project = Project(
        owner_id=user.id,
        name=payload.name,
        slug=final_slug,
        description=payload.description,
        context_md=payload.context_md,
        privileged=payload.privileged,
        minimum_inference_tier=payload.minimum_inference_tier,
        share_scope=share_scope,
    )
    db.add(project)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        # Most likely cause is the partial UNIQUE index racing with a
        # parallel create; surface as 409. We re-derive the slug above
        # before flushing, so this is genuinely concurrent.
        raise Conflict(
            "Slug collision; another project with the same slug was "
            "created concurrently. Retry with a different slug.",
            details={"slug": final_slug},
        ) from exc

    # Seed the owner's lead row so the ownership path and the membership
    # path are identical from row one — the same shape migration 0067's
    # backfill gives every pre-existing matter.
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=user.id,
            role="lead",
            added_by_user_id=user.id,
        )
    )
    await db.flush()

    await db.commit()
    await db.refresh(project)

    log.info(
        "project created",
        extra={
            "event": "project_created",
            "user_id": str(user.id),
            "project_id": str(project.id),
            "slug": project.slug,
            "privileged": project.privileged,
        },
    )

    return await _serialize_project(db, project, user)


@router.get(
    "",
    summary="List the caller's projects",
    description=(
        "Returns the caller's active projects by default. "
        "``archived=true`` returns archived projects only; "
        "``archived=false`` is equivalent to omitting the parameter. "
        "Sandbox matters (``is_sandbox=true``) are excluded by default; "
        "pass ``include_sandbox=true`` to surface them alongside regular "
        "matters, or ``only_sandbox=true`` to return only sandboxes "
        "(Wave D.2 Task 2.3)."
    ),
    response_model=list[ProjectResponse],
)
async def list_projects(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    archived: bool | None = Query(
        default=None,
        description="When true, return only archived projects.",
    ),
    include_sandbox: Annotated[
        bool,
        Query(description="Include sandbox matters in results."),
    ] = False,
    only_sandbox: Annotated[
        bool,
        Query(description="Return only sandbox matters."),
    ] = False,
) -> list[ProjectResponse]:
    # Ownership, explicit membership, and firm-wide scope — minus anything
    # the caller is screened off. One filter, same rule as the fetch path.
    conditions: list[ColumnElement[bool]] = [matter_scope_filter(user)]
    if archived is True:
        conditions.append(Project.archived_at.is_not(None))
    else:
        # Default and ``archived=false`` both exclude archived rows.
        conditions.append(Project.archived_at.is_(None))

    # Wave D.2 Task 2.3 — sandbox filter. ``only_sandbox`` wins over
    # ``include_sandbox`` if both are passed (the more specific request).
    if only_sandbox:
        conditions.append(Project.is_sandbox.is_(True))
    elif not include_sandbox:
        conditions.append(Project.is_sandbox.is_(False))

    stmt = select(Project).where(*conditions).order_by(Project.created_at.desc())

    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    # One membership query for the whole page rather than one per row.
    access_by_id = await matter_access_map(db, rows, user)
    return [
        await _serialize_project(db, row, user, access=access_by_id.get(row.id)) for row in rows
    ]


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Fetch a single project (with attachments)",
)
async def get_project(
    project_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    pid = _validate_project_id(project_id)
    # Archived projects are visible to their owner via direct GET so
    # the client can render an "archived" detail page; the list endpoint
    # excludes them by default.
    project = await _load_visible_project(db, pid, user, include_archived=True)
    return await _serialize_project(db, project, user)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Partial update of a project",
)
async def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    pid = _validate_project_id(project_id)
    project = await _load_visible_project(db, pid, user, need="write", include_archived=True)

    update_fields = payload.model_dump(exclude_unset=True)

    # Editing a matter and *governing* one are different acts. A contributor
    # may rewrite the context and rename the matter; only a lead may change
    # who can see it (``share_scope``), un-mark it privileged, lower the
    # inference-tier floor, or archive it out from under the team. Those
    # four decide where the matter's contents may travel and who may follow
    # them there.
    governance_fields = {"privileged", "minimum_inference_tier", "share_scope", "archived"}
    requested_governance = governance_fields & update_fields.keys()
    if requested_governance:
        access, _basis = await matter_access(db, project, user)
        if access != "lead":
            raise Forbidden(
                message=(
                    "Changing a matter's privilege, tier floor, share scope, or "
                    "archived state requires lead access to the matter."
                ),
                details={
                    "project_id": str(project.id),
                    "fields": sorted(requested_governance),
                    "caller_access": access,
                },
            )

    if "name" in update_fields:
        project.name = update_fields["name"]

    if "slug" in update_fields:
        new_slug = update_fields["slug"]
        if new_slug is None:
            # Disallow clearing the slug — it must always be present.
            raise ValidationError(
                "slug cannot be cleared; supply a non-empty value or omit the field.",
            )
        if not SLUG_RE.match(new_slug):
            raise ValidationError(
                "slug must match the pattern lowercase-letters-digits-and-dashes.",
                details={"slug": new_slug},
            )
        if new_slug != project.slug:
            # Slugs are unique per *owner*, so a contributor renaming a
            # shared matter must be checked against the owner's namespace,
            # not their own.
            project.slug = await _resolve_unique_slug(
                db,
                owner_id=project.owner_id,
                desired=new_slug,
                exclude_project_id=project.id,
            )

    if "description" in update_fields:
        project.description = update_fields["description"]

    if "context_md" in update_fields:
        project.context_md = update_fields["context_md"]

    # Apply privileged / tier together so we can validate the merged
    # state. If the caller sets either, we re-check the cross-field rule
    # against the post-update values.
    privileged_set = "privileged" in update_fields
    tier_set = "minimum_inference_tier" in update_fields
    new_privileged = update_fields["privileged"] if privileged_set else project.privileged
    new_tier = (
        update_fields["minimum_inference_tier"] if tier_set else project.minimum_inference_tier
    )
    if new_privileged and new_tier is None:
        raise ValidationError(
            "minimum_inference_tier must be set when privileged=true.",
            details={"field": "minimum_inference_tier"},
        )
    if privileged_set:
        project.privileged = new_privileged
    if tier_set:
        project.minimum_inference_tier = new_tier

    if "share_scope" in update_fields:
        new_scope = update_fields["share_scope"]
        if new_scope is None:
            raise ValidationError(
                "share_scope cannot be cleared; supply a value or omit the field.",
            )
        # A sandbox matter is per-user scratch space; the DB CHECK refuses
        # anything but ``personal``, so fail here with a legible message
        # rather than as an opaque IntegrityError.
        if project.is_sandbox and new_scope != "personal":
            raise ValidationError(
                "A sandbox matter cannot be shared; it is per-user scratch space.",
                details={"project_id": str(project.id), "share_scope": new_scope},
            )
        project.share_scope = new_scope

    if "archived" in update_fields:
        # Map the boolean PATCH flag to ``archived_at`` semantics.
        from datetime import UTC, datetime

        archived = update_fields["archived"]
        if archived is True and project.archived_at is None:
            project.archived_at = datetime.now(tz=UTC)
        elif archived is False and project.archived_at is not None:
            # Unarchive: must not collide with an active project that
            # already holds the slug. Re-resolve to a free variant.
            project.slug = await _resolve_unique_slug(
                db,
                owner_id=project.owner_id,
                desired=project.slug,
                exclude_project_id=project.id,
            )
            project.archived_at = None

    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "Project update conflicted with current state.",
            details={"project_id": str(project.id)},
        ) from exc

    await db.refresh(project)

    log.info(
        "project updated",
        extra={
            "event": "project_updated",
            "user_id": str(user.id),
            "project_id": str(project.id),
            "fields": sorted(update_fields.keys()),
        },
    )

    return await _serialize_project(db, project, user)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a project",
    description=(
        "Sets ``archived_at`` on the row. Hard-delete is owned by D6. "
        "Idempotent: a second delete on an already-archived project "
        "returns 404."
    ),
    response_class=Response,
)
async def delete_project(
    project_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    pid = _validate_project_id(project_id)
    # NOT include_archived — already-archived returns 404 (idempotent
    # for clients that retry).
    project = await _load_visible_project(db, pid, user, need="lead", include_archived=False)

    from datetime import UTC, datetime

    project.archived_at = datetime.now(tz=UTC)
    await db.commit()

    log.info(
        "project archived",
        extra={
            "event": "project_archived",
            "user_id": str(user.id),
            "project_id": str(pid),
        },
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Sandbox endpoint (Wave D.2 Task 2.2)
# ---------------------------------------------------------------------------


@router.post(
    "/sandbox/ensure",
    response_model=ProjectResponse,
    summary="Find or create the caller's try-it sandbox matter (Wave D.2)",
    description=(
        "Idempotent find-or-create for the per-user *try-it sandbox* "
        "project. The sandbox is a system-managed matter (slug "
        "``__sandbox__``) used to scope skill try-it conversations that "
        "should not count toward billable matter activity. First call "
        "returns 201 with a fresh row; subsequent calls return 200 with "
        "the same row. After the sandbox is soft-deleted via the normal "
        "DELETE endpoint, the next ensure call recreates it. Concurrent "
        "callers see the same row — the per-owner-active partial unique "
        "index on ``slug`` plus ``ON CONFLICT DO NOTHING`` make this "
        "race-free."
    ),
)
async def ensure_sandbox(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> ProjectResponse:
    """Idempotent find-or-create of the per-user sandbox project."""

    # Fast path: look up an existing non-archived sandbox first. The
    # vast majority of calls hit this branch (the row is created once
    # per user and reused indefinitely).
    existing = await db.scalar(
        select(Project).where(
            Project.owner_id == user.id,
            Project.is_sandbox.is_(True),
            Project.archived_at.is_(None),
        )
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return await _serialize_project(db, existing, user)

    # Insert with ON CONFLICT DO NOTHING in case of concurrent ensures.
    # The unique partial index ``idx_projects_slug_owner_active`` on
    # ``(owner_id, slug) WHERE archived_at IS NULL`` (migration 0004)
    # is the arbiter — when two concurrent callers both reach this
    # INSERT, the second one's row is dropped and ``row`` comes back
    # ``None`` so we re-read the winner.
    stmt = (
        pg_insert(Project)
        .values(
            owner_id=user.id,
            name="Try-it sandbox",
            slug="__sandbox__",
            description=(
                "Auto-created sandbox for skill try-it. Conversations here are non-billable."
            ),
            privileged=False,
            minimum_inference_tier=None,
            is_sandbox=True,
        )
        .on_conflict_do_nothing(
            index_elements=["owner_id", "slug"],
            index_where=sql_text("archived_at IS NULL"),
        )
        .returning(Project)
    )
    row = await db.scalar(stmt)

    if row is None:
        # Another concurrent caller won the race; re-read the winner.
        row = await db.scalar(
            select(Project).where(
                Project.owner_id == user.id,
                Project.is_sandbox.is_(True),
                Project.archived_at.is_(None),
            )
        )
        await db.commit()
        response.status_code = status.HTTP_200_OK
    else:
        await db.commit()
        response.status_code = status.HTTP_201_CREATED

    # Invariant: post-insert (or post-race re-read) there's always a row.
    # If this assertion ever fires it means the unique-index covering
    # ``(owner_id, slug) WHERE archived_at IS NULL`` is missing/wrong.
    assert row is not None
    await db.refresh(row)
    log.info(
        "sandbox ensured",
        extra={
            "event": "project_sandbox_ensured",
            "user_id": str(user.id),
            "project_id": str(row.id),
            "created": response.status_code == status.HTTP_201_CREATED,
        },
    )
    return await _serialize_project(db, row, user)


# ---------------------------------------------------------------------------
# Attachment endpoints — files
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/files",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Attach a file to a project",
    description=(
        "Body: ``{file_id}``. The caller must own both the project and "
        "the file (cross-user → 404 on either side). Re-attaching an "
        "already-attached file returns 409."
    ),
    response_class=Response,
)
async def attach_file(
    project_id: str,
    payload: AttachFileRequest,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    pid = _validate_project_id(project_id)
    project = await _load_visible_project(db, pid, user, need="write")
    file_row = await _load_visible_file(db, payload.file_id, user.id)

    # Capture as plain UUIDs before the write — these are needed for
    # the conflict-error envelope and the structured log; after a
    # rollback the ORM expires its row attributes and dereferencing
    # them lazily would re-query the (now-rolled-back) session.
    project_uuid = project.id
    file_uuid = file_row.id

    join = ProjectFile(project_id=project_uuid, file_id=file_uuid)
    db.add(join)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # Composite-PK violation = already attached. 409 is the right
        # shape for an idempotency-violating attach (POST is not
        # idempotent; a separate DELETE removes the join).
        raise Conflict(
            "File is already attached to this project.",
            details={
                "project_id": str(project_uuid),
                "file_id": str(file_uuid),
            },
        ) from exc

    log.info(
        "project file attached",
        extra={
            "event": "project_file_attached",
            "user_id": str(user.id),
            "project_id": str(project_uuid),
            "file_id": str(file_uuid),
        },
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{project_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a file from a project",
    description=(
        "Idempotent: removing a file that is not attached returns 404. "
        "The file row itself is untouched (use DELETE /api/v1/files/{id} "
        "for the file)."
    ),
    response_class=Response,
)
async def detach_file(
    project_id: str,
    file_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    pid = _validate_project_id(project_id)
    try:
        fid = uuid.UUID(file_id)
    except ValueError as exc:
        raise ValidationError(
            "file_id must be a UUID",
            details={"file_id": file_id},
        ) from exc

    # Verify the project is visible to the caller before peeking at the
    # join — otherwise a cross-user request could distinguish "file
    # exists but not attached" from "project exists but not yours."
    await _load_visible_project(db, pid, user, need="write")

    stmt = select(ProjectFile).where(
        ProjectFile.project_id == pid,
        ProjectFile.file_id == fid,
    )
    result = await db.execute(stmt)
    join = result.scalar_one_or_none()
    if join is None:
        raise NotFound(
            "File is not attached to this project.",
            details={
                "project_id": str(pid),
                "file_id": str(fid),
            },
        )

    await db.delete(join)
    await db.commit()

    log.info(
        "project file detached",
        extra={
            "event": "project_file_detached",
            "user_id": str(user.id),
            "project_id": str(pid),
            "file_id": str(fid),
        },
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Attachment endpoints — skills
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/skills",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Attach a skill to a project",
    description=(
        "Body: ``{skill_name}``. The skill must exist in the in-memory "
        "registry (registry-wide; no per-user check). Re-attaching an "
        "already-attached skill returns 409."
    ),
    response_class=Response,
)
async def attach_skill(
    project_id: str,
    payload: AttachSkillRequest,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> Response:
    pid = _validate_project_id(project_id)
    project = await _load_visible_project(db, pid, user, need="write")

    holder = _registry(request)
    registry = holder.current()
    if registry.get(payload.skill_name) is None:
        raise NotFound(
            f"Skill {payload.skill_name!r} is not in the registry.",
            details={"skill_name": payload.skill_name},
        )

    # Capture as plain UUID before the write — see attach_file for
    # the rationale (post-rollback ORM lazy-load avoidance).
    project_uuid = project.id

    join = ProjectSkill(project_id=project_uuid, skill_name=payload.skill_name)
    db.add(join)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "Skill is already attached to this project.",
            details={
                "project_id": str(project_uuid),
                "skill_name": payload.skill_name,
            },
        ) from exc

    log.info(
        "project skill attached",
        extra={
            "event": "project_skill_attached",
            "user_id": str(user.id),
            "project_id": str(project_uuid),
            "skill_name": payload.skill_name,
        },
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{project_id}/skills/{skill_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a skill from a project",
    response_class=Response,
)
async def detach_skill(
    project_id: str,
    skill_name: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    pid = _validate_project_id(project_id)
    await _load_visible_project(db, pid, user, need="write")

    stmt = select(ProjectSkill).where(
        ProjectSkill.project_id == pid,
        ProjectSkill.skill_name == skill_name,
    )
    result = await db.execute(stmt)
    join = result.scalar_one_or_none()
    if join is None:
        raise NotFound(
            "Skill is not attached to this project.",
            details={
                "project_id": str(pid),
                "skill_name": skill_name,
            },
        )

    await db.delete(join)
    await db.commit()

    log.info(
        "project skill detached",
        extra={
            "event": "project_skill_detached",
            "user_id": str(user.id),
            "project_id": str(pid),
            "skill_name": skill_name,
        },
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Attachment endpoints — knowledge bases (Wave D.1 T3)
# ---------------------------------------------------------------------------


async def _load_visible_kb(
    db: AsyncSession,
    kb_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> KnowledgeBase:
    """Load a KB row scoped to the caller; 404 on miss / cross-user / archived.

    Same posture as ``_load_visible_file``: cross-user collapses to 404 to
    avoid leaking existence. Archived KBs are invisible.
    """

    stmt = select(KnowledgeBase).where(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.owner_id == owner_id,
        KnowledgeBase.archived_at.is_(None),
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise NotFound(
            f"Knowledge base {kb_id} not found.",
            details={"knowledge_base_id": str(kb_id)},
        )
    return row


@router.post(
    "/{project_id}/knowledge-bases",
    response_model=ProjectResponse,
    summary="Attach a knowledge base to a matter",
    description=(
        "Body: ``{knowledge_base_id}``. The caller must own both the "
        "project and the KB (cross-user → 404 on either side). "
        "Idempotent — re-attaching an already-attached KB returns 200 "
        "with the current project state. Audit action: "
        "``project.knowledge_base_attached``."
    ),
)
async def attach_knowledge_base(
    project_id: str,
    payload: AttachKnowledgeBaseRequest,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> ProjectResponse:
    pid = _validate_project_id(project_id)
    project = await _load_visible_project(db, pid, user, need="write")
    kb = await _load_visible_kb(db, payload.knowledge_base_id, user.id)

    # Capture as plain UUIDs before any write — see ``attach_file`` for
    # the post-rollback ORM lazy-load rationale.
    project_uuid = project.id
    kb_uuid = kb.id

    existing_stmt = select(ProjectKnowledgeBase).where(
        ProjectKnowledgeBase.project_id == project_uuid,
        ProjectKnowledgeBase.knowledge_base_id == kb_uuid,
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()

    if existing is None:
        join = ProjectKnowledgeBase(
            project_id=project_uuid,
            knowledge_base_id=kb_uuid,
            attached_by_user_id=user.id,
        )
        db.add(join)
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            # Race: another request created the same join between the
            # SELECT and INSERT. Idempotency means we treat this as
            # success — re-fetch and fall through.
            existing_stmt = select(ProjectKnowledgeBase).where(
                ProjectKnowledgeBase.project_id == project_uuid,
                ProjectKnowledgeBase.knowledge_base_id == kb_uuid,
            )
            if (await db.execute(existing_stmt)).scalar_one_or_none() is None:
                raise Conflict(
                    "Failed to attach knowledge base.",
                    details={
                        "project_id": str(project_uuid),
                        "knowledge_base_id": str(kb_uuid),
                    },
                ) from exc

        await audit_action(
            db,
            user_id=user.id,
            action="project.knowledge_base_attached",
            resource_type="project",
            resource_id=str(project_uuid),
            project=project,
            request=request,
            details={"knowledge_base_id": str(kb_uuid)},
        )
        await db.commit()

        log.info(
            "project kb attached",
            extra={
                "event": "project_kb_attached",
                "user_id": str(user.id),
                "project_id": str(project_uuid),
                "knowledge_base_id": str(kb_uuid),
            },
        )

    return await _serialize_project(db, project, user)


@router.delete(
    "/{project_id}/knowledge-bases/{kb_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a knowledge base from a matter",
    description=(
        "Idempotent — detaching a KB that is not attached returns 204. "
        "The KB row itself is untouched (use "
        "``DELETE /api/v1/knowledge-bases/{id}`` for the KB). "
        "Audit action: ``project.knowledge_base_detached`` (only "
        "written when a join row is actually removed)."
    ),
    response_class=Response,
)
async def detach_knowledge_base(
    project_id: str,
    kb_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> Response:
    pid = _validate_project_id(project_id)
    try:
        kid = uuid.UUID(kb_id)
    except ValueError as exc:
        raise ValidationError(
            "kb_id must be a UUID",
            details={"kb_id": kb_id},
        ) from exc

    # Verify the project is visible to the caller before peeking at the
    # join — otherwise cross-user could distinguish "kb exists but not
    # attached" from "project exists but not yours."
    project = await _load_visible_project(db, pid, user, need="write")

    stmt = select(ProjectKnowledgeBase).where(
        ProjectKnowledgeBase.project_id == pid,
        ProjectKnowledgeBase.knowledge_base_id == kid,
    )
    result = await db.execute(stmt)
    join = result.scalar_one_or_none()

    if join is not None:
        await db.delete(join)
        await audit_action(
            db,
            user_id=user.id,
            action="project.knowledge_base_detached",
            resource_type="project",
            resource_id=str(pid),
            project=project,
            request=request,
            details={"knowledge_base_id": str(kid)},
        )
        await db.commit()

        log.info(
            "project kb detached",
            extra={
                "event": "project_kb_detached",
                "user_id": str(user.id),
                "project_id": str(pid),
                "knowledge_base_id": str(kid),
            },
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = [
    "attach_file",
    "attach_knowledge_base",
    "attach_skill",
    "create_project",
    "delete_project",
    "detach_file",
    "detach_knowledge_base",
    "detach_skill",
    "ensure_sandbox",
    "get_project",
    "list_projects",
    "router",
    "update_project",
]
