"""Matter (project) access control — the single resolver.

A matter is a ``projects`` row (ADR 0020 D3 — no separate ``Matter``
model). Access to one is decided here and nowhere else.

Evaluation order, most-binding first::

    1. a ``project_members`` row with role='blocked'  -> none  (absolute)
    2. the caller owns the project                    -> lead
    3. an explicit ``project_members`` row            -> lead/write/read
    4. share_scope='org'                              -> read
    5. otherwise                                      -> none

Four properties of that order are load-bearing:

**Denial is absolute, and it beats ``is_admin``.** An ethical screen an
operator-admin can walk through is not a screen, and in a small firm the
operator-admin is usually also a practising lawyer. Step 1 runs before
every allow.

**There is no operator-admin bypass, and no ``auditor`` branch.** Before
membership existed, ``is_admin`` did *not* let anyone read another user's
matter — the matter loaders were plain owner checks. Adding such a branch
here would be a silent widening of cross-user access smuggled in under a
collaboration feature, and an unaudited one at that. The deployment-wide
``auditor`` role (lq-ai #266) keeps working exactly as before on the
ledger and receipt surfaces, which resolve access their own way through
``_load_chat_for_reader``. An unscreened admin may explicitly grant roster access using the
management endpoints, with an intervention reason and an audit row.

**Org scope grants READ only.** Contributing to a matter always requires
an explicit membership row, so the roster remains a truthful answer to
"who worked this matter" — the question that matters for privilege and
for conflicts, months later, when nobody remembers.

**A denied caller gets 404, not 403.** This preserves the existence-safe
posture the matter surface already documents (``projects.py``'s
``_load_visible_project``): a cross-user probe must not be able to
distinguish "no such matter" from "not yours". 403 is reserved for a
caller who demonstrably already knows the matter exists because they can
read it, and is merely asking for more than their role allows.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Literal

from sqlalchemy import ColumnElement, Select, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import Forbidden, NotFound, ValidationError
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User

MatterAccess = Literal["none", "read", "write", "lead"]
"""Effective access level, ordered by :data:`_ACCESS_RANK`."""

_ACCESS_RANK: dict[str, int] = {"none": 0, "read": 1, "write": 2, "lead": 3}

#: Membership role -> the access level it confers. ``blocked`` is handled
#: separately (it is a denial, not a level) and so is deliberately absent.
_ROLE_ACCESS: dict[str, MatterAccess] = {
    "lead": "lead",
    "contributor": "write",
    "reader": "read",
}

BLOCKED_ROLE = "blocked"


def _at_least(have: MatterAccess, need: MatterAccess) -> bool:
    return _ACCESS_RANK[have] >= _ACCESS_RANK[need]


async def matter_access(
    db: AsyncSession,
    project: Project,
    user: User,
) -> tuple[MatterAccess, str]:
    """Resolve ``user``'s effective access to ``project``.

    Returns ``(level, basis)`` where ``basis`` names the rule that decided
    it — ``blocked`` / ``owner`` / ``member`` / ``org`` / ``no_grant``.
    Callers surface the basis in audit rows and in ``ProjectResponse`` so a
    reviewer — and the UI — can see *why* access exists, not just that it
    does.
    """
    membership = (
        await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    return resolve_access(project, user, membership)


def resolve_access(
    project: Project,
    user: User,
    membership_role: str | None,
) -> tuple[MatterAccess, str]:
    """The rule itself, given a project, a caller, and their roster row.

    Split out so the single-row path (:func:`matter_access`) and the batch
    path (:func:`matter_access_map`) cannot drift: there is one ordering of
    the rules and both call it.
    """
    # 1. An explicit screen denies before anything else is considered.
    if membership_role == BLOCKED_ROLE:
        return "none", "blocked"

    # 2. The owner is always lead. The 0074 backfill also writes an explicit
    #    lead row, so this is normally belt-and-braces — but it keeps a
    #    project whose membership row was deleted by hand from becoming
    #    unreachable by its own owner.
    read_only = getattr(user, "role", "member") in {"viewer", "auditor"}
    if project.owner_id == user.id:
        return ("read" if read_only else "lead"), "owner"

    # 3. An explicit grant.
    if membership_role is not None:
        granted = _ROLE_ACCESS.get(membership_role)
        if granted is not None:
            return ("read" if read_only else granted), "member"

    # 4. Ambient firm-wide read. Deliberately the last rule: there is no
    #    operator-admin fallthrough below it.
    if project.share_scope == "org":
        return "read", "org"

    return "none", "no_grant"


async def matter_access_map(
    db: AsyncSession,
    projects: Sequence[Project],
    user: User,
) -> dict[uuid.UUID, tuple[MatterAccess, str]]:
    """Resolve ``user``'s access to many matters in one round-trip.

    :func:`matter_access` issues one membership query per call, which is
    fine for a fetch and wasteful for a list. Same rules, same order — the
    ordering lives in :func:`resolve_access` and both paths call it.
    """
    if not projects:
        return {}

    rows = (
        await db.execute(
            select(ProjectMember.project_id, ProjectMember.role).where(
                ProjectMember.project_id.in_([p.id for p in projects]),
                ProjectMember.user_id == user.id,
            )
        )
    ).all()
    roles: dict[uuid.UUID, str] = {row.project_id: row.role for row in rows}
    return {p.id: resolve_access(p, user, roles.get(p.id)) for p in projects}


async def require_matter(
    db: AsyncSession,
    project_id: uuid.UUID,
    user: User,
    *,
    need: MatterAccess = "read",
    include_archived: bool = False,
) -> Project:
    """Load a matter and assert ``user`` holds at least ``need`` on it.

    Raises :class:`app.errors.NotFound` when the matter does not exist, is
    archived (unless ``include_archived``), or the caller has no access at
    all — the three collapse into one 404 so an id probe learns nothing.

    Raises :class:`app.errors.Forbidden` only when the caller *can* read
    the matter but is asking for more than their role allows. At that
    point 403 leaks nothing they could not already see, and a bare 404
    would be actively misleading in the UI.
    """
    stmt = select(Project).where(Project.id == project_id).execution_options(populate_existing=True)
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))

    project = (await db.execute(stmt)).scalar_one_or_none()
    if project is None:
        raise NotFound(
            f"Project {project_id} not found.",
            details={"project_id": str(project_id)},
        )

    level, basis = await matter_access(db, project, user)
    if level == "none":
        raise NotFound(
            f"Project {project_id} not found.",
            details={"project_id": str(project_id)},
        )
    if not _at_least(level, need):
        raise Forbidden(
            message=(f"This action requires {need!r} access to the matter; you have {level!r}."),
            details={
                "project_id": str(project_id),
                "required_access": need,
                "caller_access": level,
                "basis": basis,
            },
        )
    return project


def visible_project_ids(user: User, *, need: MatterAccess = "read") -> Select[tuple[uuid.UUID]]:
    """Subquery of project ids ``user`` reaches through an explicit grant.

    Ownership and ``share_scope='org'`` are handled by
    :func:`matter_scope_filter`; this covers only ``project_members`` rows,
    and never returns a project the caller is blocked on.
    """
    roles = [r for r, level in _ROLE_ACCESS.items() if _at_least(level, need)]
    return select(ProjectMember.project_id).where(
        ProjectMember.user_id == user.id,
        ProjectMember.role.in_(roles),
    )


def blocked_project_ids(user: User) -> Select[tuple[uuid.UUID]]:
    """Subquery of project ids ``user`` is explicitly screened off."""
    return select(ProjectMember.project_id).where(
        ProjectMember.user_id == user.id,
        ProjectMember.role == BLOCKED_ROLE,
    )


def matter_scope_filter(user: User, *, need: MatterAccess = "read") -> ColumnElement[bool]:
    """WHERE clause selecting the matters ``user`` reaches at ``need``.

    The list-endpoint counterpart to :func:`require_matter`, expressed as
    SQL so a listing and a fetch cannot drift apart. Blocked matters are
    subtracted last, mirroring the resolver's rule that denial wins.
    """
    reachable: list[ColumnElement[bool]] = [
        Project.owner_id == user.id,
        Project.id.in_(visible_project_ids(user, need=need)),
    ]
    if need == "read":
        # Ambient firm-wide scope grants read and nothing more.
        reachable.append(Project.share_scope == "org")

    return or_(*reachable) & Project.id.not_in(blocked_project_ids(user))


async def require_matter_management(db: AsyncSession, project_id: uuid.UUID, user: User) -> Project:
    """Owners/leads or unscreened admins may manage policy, not read content."""
    project = (
        await db.execute(select(Project).where(Project.id == project_id).with_for_update())
    ).scalar_one_or_none()
    if project is None:
        raise NotFound("Matter not found.")
    access, basis = await matter_access(db, project, user)
    if basis == "blocked":
        raise NotFound("Matter not found.")
    if access == "none" and not user.is_admin:
        raise NotFound("Matter not found.")
    if access != "lead" and not user.is_admin:
        raise Forbidden("Matter management requires lead or administrator authority.")
    if project.is_sandbox:
        raise ValidationError("Sandbox matters cannot have their roster or ownership changed.")
    return project


def denied_file_ids(user_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """An explicit screen follows a file's direct scope and attachment links."""
    from app.models.file import File
    from app.models.knowledge import KnowledgeBaseFile
    from app.models.project import ProjectFile

    blocked = select(ProjectMember.project_id).where(
        ProjectMember.user_id == user_id, ProjectMember.role == BLOCKED_ROLE
    )
    attached = select(ProjectFile.file_id).where(ProjectFile.project_id.in_(blocked))
    kb_sources = select(KnowledgeBaseFile.file_id).where(
        KnowledgeBaseFile.kb_id.in_(denied_kb_ids(user_id))
    )
    return select(File.id).where(
        or_(File.project_id.in_(blocked), File.id.in_(attached), File.id.in_(kb_sources))
    )


def denied_kb_ids(user_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """Screens follow both KB scope and matter-to-KB attachment links."""
    from app.models.knowledge import KnowledgeBase
    from app.models.project_knowledge_base import ProjectKnowledgeBase

    blocked = select(ProjectMember.project_id).where(
        ProjectMember.user_id == user_id, ProjectMember.role == BLOCKED_ROLE
    )
    attached = select(ProjectKnowledgeBase.knowledge_base_id).where(
        ProjectKnowledgeBase.project_id.in_(blocked)
    )
    return select(KnowledgeBase.id).where(
        or_(KnowledgeBase.project_id.in_(blocked), KnowledgeBase.id.in_(attached))
    )


async def require_resource_write(
    db: AsyncSession,
    user: User,
    direct_project_id: uuid.UUID | None,
    linked_projects: Select[tuple[uuid.UUID]],
) -> None:
    """A resource edit must satisfy every matter whose contents it changes."""
    ids = set((await db.scalars(linked_projects)).all())
    if direct_project_id is not None:
        ids.add(direct_project_id)
    for project_id in sorted(ids, key=str):
        await require_matter(db, project_id, user, need="write", include_archived=True)


def file_matter_ids(file_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """All matters affected by a file, including KB source membership."""
    from app.models.file import File
    from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
    from app.models.project import ProjectFile
    from app.models.project_knowledge_base import ProjectKnowledgeBase

    scopes = union(
        select(File.project_id).where(File.id == file_id, File.project_id.is_not(None)),
        select(ProjectFile.project_id).where(ProjectFile.file_id == file_id),
        select(KnowledgeBase.project_id)
        .join(KnowledgeBaseFile, KnowledgeBaseFile.kb_id == KnowledgeBase.id)
        .where(KnowledgeBaseFile.file_id == file_id, KnowledgeBase.project_id.is_not(None)),
        select(ProjectKnowledgeBase.project_id)
        .join(KnowledgeBaseFile, KnowledgeBaseFile.kb_id == ProjectKnowledgeBase.knowledge_base_id)
        .where(KnowledgeBaseFile.file_id == file_id),
    ).subquery()
    return select(scopes.c.project_id)


async def require_document_matter_access(
    db: AsyncSession,
    document_ids: Sequence[uuid.UUID],
    user: User | None,
    *,
    need: MatterAccess = "read",
) -> None:
    """Guard document workflows and their derived results, without an admin bypass.

    Ownership/existence checks stay with each caller. Historical results whose
    source documents were removed retain their existing read policy. Every live
    source carries all of its direct, attachment and KB matter restrictions.
    """
    from app.models.document import Document

    file_ids = (
        await db.scalars(select(Document.file_id).where(Document.id.in_(document_ids)))
    ).all()
    ids: set[uuid.UUID] = set()
    for file_id in file_ids:
        ids.update((await db.scalars(file_matter_ids(file_id))).all())
    if ids and (user is None or user.deleted_at is not None):
        raise NotFound("Document not found.")
    for project_id in sorted(ids, key=str):
        assert user is not None
        await require_matter(db, project_id, user, need=need, include_archived=True)


def readable_autonomous_session_ids(user: User) -> Select[tuple[uuid.UUID]]:
    """Matter authorization follows a session into memory, precedents and notices."""
    from app.models.autonomous import AutonomousSession

    return select(AutonomousSession.id).where(
        AutonomousSession.project_id.is_(None)
        | AutonomousSession.project_id.in_(select(Project.id).where(matter_scope_filter(user)))
    )


async def require_autonomous_source(
    db: AsyncSession, source_session_id: uuid.UUID | None, user_id: uuid.UUID
) -> None:
    if source_session_id is None:
        return
    from app.models.autonomous import AutonomousSession

    source = await db.get(AutonomousSession, source_session_id)
    user = await db.get(User, user_id)
    if source is None or user is None:
        raise NotFound("Autonomous source not found.")
    if source.project_id is not None:
        await require_matter(db, source.project_id, user, include_archived=True)
