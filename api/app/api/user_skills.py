"""User-skill management endpoints — Task D8 (ADR 0012).

CRUD surface for the caller's user-scope skills. These rows shadow
filesystem-canonical built-ins on slug collision when resolved for
the owning user's chats; other users continue to see the built-in.
See ``docs/adr/0012-db-backed-user-skills.md`` for the full design.

The read-side merge — listing built-ins + user shadows together for
the skill picker — lives in ``api/app/api/skills.py``. The
``POST /api/v1/skills/{slug}/fork`` operation likewise lives in that
module because the URL form ``/skills/<built-in slug>/fork`` reads
better as "fork this specific built-in" than a generic
``/user-skills`` write.

This router is mounted under ``ActiveUser`` at the include site, so
every handler inherits the B1 bearer-token check + the B2 must-change-
password gate. Cross-user reads/writes are blocked by filtering on
``owner_user_id`` in addition to the gate (defense in depth, matches
the chats / projects / saved_prompts pattern).

Audit logging follows the D3-coverage convention from 2026-05-10c —
every state-changing path writes an ``audit_log`` row. The
``user_skill.created`` / ``user_skill.updated`` / ``user_skill.deleted``
actions ride the same single-transaction commit as the row change.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.team import Team, TeamMember
from app.models.user import User
from app.models.user_skill import UserSkill
from app.skills.schema import LQAIFrontmatter

router = APIRouter(prefix="/user-skills", tags=["user-skills"])


# ---------------------------------------------------------------------------
# Validation bounds
# ---------------------------------------------------------------------------

# Slug shape mirrors the filesystem skill folder-naming convention:
# lowercase ASCII letters, digits, and hyphens; must start and end with
# an alphanumeric. 80 chars is generous against the ~20-char names in
# the starter corpus and short enough to fit comfortably in UI chips.
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,78}[a-z0-9])?$")

# Slash-alias shape: leading slash, then 1-32 lowercase alphanumerics or
# hyphens. Mirrors the DB-layer ``chk_user_skills_slash_alias_format``
# CHECK constraint added in migration 0023. Matched at the Pydantic layer
# so the API rejects malformed aliases with a 422 before they hit the DB.
_SLASH_ALIAS_RE = re.compile(r"^/[a-z0-9-]{1,32}$")

_NAME_MAX = 200
_DESCRIPTION_MAX = 2_000
_VERSION_MAX = 50
_TAG_MAX = 50
_MAX_TAGS = 20
# Skill bodies are markdown system-prompt chunks. Filesystem skills
# typically run 1-30KB; 200KB is the ceiling that catches accidental
# whole-document pastes without rejecting any reasonable authoring.
_BODY_MAX = 200_000
# Arbitrary ``lq_ai:`` extension keys (jurisdiction, output_format, etc.)
# land in this JSONB column. 16KB is plenty for the corpus reality and
# rejects pathological payloads.
_FRONTMATTER_EXTRA_MAX_BYTES = 16_384


# ---------------------------------------------------------------------------
# Shared field validators
# ---------------------------------------------------------------------------


def _validate_slash_alias_value(v: str | None) -> str | None:
    """Module-level slash_alias validator reused by UserSkillCreate and UserSkillUpdate.

    Called from ``@field_validator("slash_alias")`` in both Pydantic models so
    the body is not duplicated. Behaviour is identical in both callers: ``None``
    passes through; a non-matching value raises ``ValueError`` with a descriptive
    message; a matching value is returned unchanged.
    """
    if v is None:
        return None
    if not _SLASH_ALIAS_RE.match(v):
        raise ValueError(
            "slash_alias must match ^/[a-z0-9-]{1,32}$ "
            "(leading slash, then 1-32 lowercase alphanumerics or hyphens)"
        )
    return v


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class UserSkillResponse(BaseModel):
    """Full row view — what the management UI consumes.

    Distinct from the ``Skill`` shape returned by the merged picker
    endpoint (``GET /api/v1/skills/{slug}``) because this view is
    designed for *editing*: every column is here, no synthesis,
    nothing dropped for compactness.

    Exactly one of ``owner_user_id`` / ``owner_team_id`` is set — the
    DB's ``ck_user_skills_scope_owner_consistency`` CHECK enforces
    this. The matching slot is ``None``.
    """

    id: uuid.UUID
    scope: str
    owner_user_id: uuid.UUID | None = None
    owner_team_id: uuid.UUID | None = None
    slug: str
    display_name: str
    description: str
    version: str
    tags: list[str] = Field(default_factory=list)
    frontmatter_extra: dict[str, Any] = Field(default_factory=dict)
    body: str
    slash_alias: str | None = None
    forked_from: str | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserSkillCreate(BaseModel):
    """POST body. Required fields mirror the minimum needed to render
    a Skill-shaped payload to the gateway during prompt assembly.

    ``scope`` defaults to ``'user'`` (the D8 path). ``scope='team'``
    requires ``owner_team_id`` and the caller must be a team-admin
    member of that team (gated at the handler). ``owner_team_id`` is
    rejected when ``scope='user'`` so accidental hybrid rows can't be
    constructed via the API.
    """

    slug: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=_NAME_MAX)
    description: str = Field(min_length=1, max_length=_DESCRIPTION_MAX)
    body: str = Field(min_length=1, max_length=_BODY_MAX)
    version: str = Field(default="1.0.0", min_length=1, max_length=_VERSION_MAX)
    tags: list[str] = Field(default_factory=list, max_length=_MAX_TAGS)
    frontmatter_extra: dict[str, Any] = Field(default_factory=dict)
    scope: str = Field(default="user", pattern=r"^(user|team)$")
    owner_team_id: uuid.UUID | None = None
    slash_alias: str | None = Field(
        default=None,
        description="Optional /slug invocation alias; ^/[a-z0-9-]{1,32}$.",
    )
    forked_from: str | None = Field(
        default=None,
        description="Documentary slug of the source skill if forked. Write-once.",
    )
    source_message_id: str | None = Field(
        default=None,
        description=(
            "Capture metadata: source AI message id when this skill was distilled "
            "from chat. Documentary only — not persisted as a column; rides the "
            "create-time audit-log row."
        ),
    )

    @field_validator("slash_alias")
    @classmethod
    def _validate_slash_alias(cls, v: str | None) -> str | None:
        return _validate_slash_alias_value(v)


class UserSkillUpdate(BaseModel):
    """PATCH body. Every field is optional; only the supplied keys move.

    ``forked_from`` and ``source_message_id`` are intentionally absent —
    they are write-once at create time so the documentary lineage cannot
    be rewritten after creation. The audit log carries the actual lineage
    record per ADR 0012 §5.
    """

    display_name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    description: str | None = Field(default=None, min_length=1, max_length=_DESCRIPTION_MAX)
    body: str | None = Field(default=None, min_length=1, max_length=_BODY_MAX)
    version: str | None = Field(default=None, min_length=1, max_length=_VERSION_MAX)
    tags: list[str] | None = Field(default=None, max_length=_MAX_TAGS)
    frontmatter_extra: dict[str, Any] | None = None
    slash_alias: str | None = Field(
        default=None,
        description="Optional /slug invocation alias; ^/[a-z0-9-]{1,32}$.",
    )

    @field_validator("slash_alias")
    @classmethod
    def _validate_slash_alias(cls, v: str | None) -> str | None:
        return _validate_slash_alias_value(v)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_slug(slug: str) -> str:
    if not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=422,
            detail=(
                "slug must be lowercase alphanumeric with hyphens, "
                "starting and ending with an alphanumeric, max 80 chars"
            ),
        )
    return slug


def _validate_tags(tags: list[str]) -> list[str]:
    """Normalise + validate tags. Dedupes preserving first-seen order."""

    seen: set[str] = set()
    out: list[str] = []
    for raw in tags:
        if not isinstance(raw, str):
            raise HTTPException(status_code=422, detail="tag values must be strings")
        tag = raw.strip()
        if not tag:
            raise HTTPException(status_code=422, detail="tag values must be non-empty")
        if len(tag) > _TAG_MAX:
            raise HTTPException(
                status_code=422,
                detail=f"tag values must be at most {_TAG_MAX} characters",
            )
        if tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


# The ``lq_ai:`` keys that participate in table-mode authoring (DE-297).
# When any of them appear in ``frontmatter_extra``, that subset is
# re-validated through :class:`app.skills.schema.LQAIFrontmatter` — the
# SAME model the built-in loader parses SKILL.md frontmatter with — so a
# user-authored table skill can never persist a shape the built-in path
# would reject (zero columns, blank query, tier outside 1-5, …).
# Restricted to this subset (rather than validating the whole dict) so
# unrelated free-form extension keys keep their documented
# "arbitrary JSON" contract.
_TABLE_MODE_EXTRA_KEYS = frozenset(
    {"output_format", "columns", "minimum_inference_tier", "ensemble_verification"}
)


def _validate_frontmatter_extra(extra: dict[str, Any]) -> dict[str, Any]:
    """Reject pathologically large extension blobs and invalid table specs.

    Keys/values are arbitrary JSON; the guards at this layer are:

    * a serialized-size ceiling so a runaway client can't burn a JSONB
      page on a single row (the Pydantic ``dict[str, Any]`` typing
      already rejects non-dict bodies); and
    * DE-297 table-mode parity — when the extra block carries any of
      the ``lq_ai`` authoring keys (``output_format`` / ``columns`` /
      ``minimum_inference_tier`` / ``ensemble_verification``), that
      subset must validate through the same ``LQAIFrontmatter`` schema
      the filesystem loader applies to built-ins. This is what makes a
      user-authored ``output_format: table`` skill runnable by the
      Tabular workflow instead of a stored-but-broken row.
    """

    import json  # local — only this validator needs it

    encoded = json.dumps(extra, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > _FRONTMATTER_EXTRA_MAX_BYTES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"frontmatter_extra exceeds the {_FRONTMATTER_EXTRA_MAX_BYTES}-byte "
                "serialized ceiling for a single user skill"
            ),
        )

    table_subset = {k: v for k, v in extra.items() if k in _TABLE_MODE_EXTRA_KEYS}
    if table_subset:
        try:
            LQAIFrontmatter.model_validate(table_subset)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(part) for part in err['loc']) or 'frontmatter_extra'}: {err['msg']}"
                for err in exc.errors()
            )
            raise HTTPException(
                status_code=422,
                detail=f"frontmatter_extra is not a valid skill spec: {problems}",
            ) from None
    return extra


def _to_response(row: UserSkill) -> UserSkillResponse:
    return UserSkillResponse(
        id=row.id,
        scope=row.scope,
        owner_user_id=row.owner_user_id,
        owner_team_id=row.owner_team_id,
        slug=row.slug,
        display_name=row.display_name,
        description=row.description,
        version=row.version,
        tags=list(row.tags or []),
        frontmatter_extra=dict(row.frontmatter_extra or {}),
        body=row.body,
        slash_alias=row.slash_alias,
        forked_from=row.forked_from,
        archived_at=row.archived_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _is_team_admin(db: AsyncSession, *, team_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Return whether ``user_id`` is an ``admin``-role member of ``team_id``.

    Mutate rights on team-scope skills require the team-admin role per
    D8.1b. Non-admin members can attach the skill in chats but cannot
    create / edit / archive it.
    """

    stmt = select(TeamMember).where(
        TeamMember.team_id == team_id,
        TeamMember.user_id == user_id,
        TeamMember.role == "admin",
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def _load_mutable(
    db: AsyncSession,
    *,
    skill_id: uuid.UUID,
    user_id: uuid.UUID,
    include_archived: bool = False,
) -> UserSkill:
    """Fetch a user/team-skill row by id; 404 if missing OR caller cannot mutate.

    For ``scope='user'`` rows the caller must be ``owner_user_id``.
    For ``scope='team'`` rows the caller must be a team-admin member
    of ``owner_team_id``. Otherwise 404 — conflating "no such id"
    with "exists but not yours" matches the privacy posture in
    saved_prompts / chats / projects so id-probing can't enumerate
    other users' or other teams' rows.
    """

    stmt = select(UserSkill).where(UserSkill.id == skill_id)
    if not include_archived:
        stmt = stmt.where(UserSkill.archived_at.is_(None))
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user skill not found")

    if row.scope == "user":
        if row.owner_user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="user skill not found"
            )
    elif row.scope == "team":
        if row.owner_team_id is None or not await _is_team_admin(
            db, team_id=row.owner_team_id, user_id=user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="user skill not found"
            )
    else:  # pragma: no cover — CHECK constraint blocks other values
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user skill not found")
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[UserSkillResponse],
    summary="List the caller's editable skills (user-scope by default; team-scope via ?scope)",
)
async def list_user_skills(
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    scope: str = Query(default="user", pattern="^(user|team|all)$"),
) -> list[UserSkillResponse]:
    """GET /api/v1/user-skills — non-archived rows the caller can edit.

    Scope filter (D8.1c — defaults to ``user`` for back-compat):

    * ``user`` — the caller's user-scope rows only (the D8 behavior).
    * ``team`` — team-scope rows from any team where the caller is an
      admin. Members can read team skills in the chat picker but can't
      mutate, so the management list returns admin-only rows.
    * ``all`` — both, sorted together by ``updated_at DESC, id DESC``.

    Sort: ``updated_at DESC`` then ``id DESC`` for deterministic tie-
    breaking (mirrors the saved_prompts convention).
    """

    rows: list[UserSkill] = []

    if scope in ("user", "all"):
        stmt = (
            select(UserSkill)
            .where(
                UserSkill.scope == "user",
                UserSkill.owner_user_id == user.id,
                UserSkill.archived_at.is_(None),
            )
            .order_by(UserSkill.updated_at.desc(), UserSkill.id.desc())
        )
        rows.extend((await db.execute(stmt)).scalars().all())

    if scope in ("team", "all"):
        # Join through team_members filtered on role='admin' so the management
        # list only includes rows the caller can actually mutate. Members
        # see team skills through the merged picker at GET /skills, not here.
        stmt = (
            select(UserSkill)
            .join(TeamMember, TeamMember.team_id == UserSkill.owner_team_id)
            .where(
                UserSkill.scope == "team",
                UserSkill.archived_at.is_(None),
                TeamMember.user_id == user.id,
                TeamMember.role == "admin",
            )
            .order_by(UserSkill.updated_at.desc(), UserSkill.id.desc())
        )
        rows.extend((await db.execute(stmt)).scalars().all())

    if scope == "all":
        rows.sort(
            key=lambda r: (r.updated_at, str(r.id)),
            reverse=True,
        )

    return [_to_response(r) for r in rows]


@router.get(
    "/{skill_id}",
    response_model=UserSkillResponse,
    summary="Fetch a single user/team-scope skill (owner or team-admin)",
    responses={404: {"description": "User skill not found"}},
)
async def get_user_skill(
    skill_id: uuid.UUID,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserSkillResponse:
    """Owner-only for user-scope; team-admin-only for team-scope rows.

    Non-admin team members read team skills through the merged picker
    (``GET /api/v1/skills/{slug}``), not through this management
    endpoint — same posture as filesystem built-ins.
    """

    row = await _load_mutable(db, skill_id=skill_id, user_id=user.id)
    return _to_response(row)


@router.post(
    "",
    response_model=UserSkillResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user- or team-scope skill",
    responses={
        404: {"description": "Team referenced by owner_team_id not found"},
        409: {"description": "Slug already exists in this scope"},
        422: {"description": "scope / owner_team_id combination invalid"},
    },
)
async def create_user_skill(
    payload: UserSkillCreate,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserSkillResponse:
    """POST /api/v1/user-skills — create a fresh user- or team-scope skill.

    Scope branches:

    * ``scope='user'`` (default) — owned by the caller. Slug collision with
      a filesystem built-in is **allowed** (the shadow case per ADR 0012).
      Slug collision with the caller's own non-archived user-scope skills
      returns 409.
    * ``scope='team'`` — owned by ``owner_team_id``. Caller must be a
      team-admin member of that team or 404 (id-probing-safe — same
      privacy posture as cross-user reads). Slug collision within the
      team's non-archived rows returns 409. Slug collision with a
      built-in OR with any user-scope row is permitted (shadowing semantics
      cascade per D8.1b resolver: user > team > built-in).

    422 fires when ``scope`` and ``owner_team_id`` are inconsistent
    (team scope missing the team id, user scope carrying a team id).
    """

    slug = _validate_slug(payload.slug)
    tags = _validate_tags(payload.tags)
    frontmatter_extra = _validate_frontmatter_extra(payload.frontmatter_extra)
    slash_alias = payload.slash_alias  # already regex-validated at the Pydantic layer
    forked_from = payload.forked_from
    source_message_id = payload.source_message_id

    if payload.scope == "user":
        if payload.owner_team_id is not None:
            raise HTTPException(
                status_code=422,
                detail="owner_team_id must be null when scope='user'",
            )
        row = UserSkill(
            scope="user",
            owner_user_id=user.id,
            slug=slug,
            display_name=payload.display_name.strip(),
            description=payload.description.strip(),
            version=payload.version.strip(),
            tags=tags,
            frontmatter_extra=frontmatter_extra,
            body=payload.body,
            slash_alias=slash_alias,
            forked_from=forked_from,
        )
        audit_details: dict[str, Any] = {
            "slug": slug,
            "version": payload.version.strip(),
            "tags": tags,
            "scope": "user",
        }
    else:  # scope == "team" (pattern validator restricts the alternatives)
        if payload.owner_team_id is None:
            raise HTTPException(
                status_code=422,
                detail="owner_team_id is required when scope='team'",
            )
        team = await db.get(Team, payload.owner_team_id)
        if team is None or not await _is_team_admin(
            db, team_id=payload.owner_team_id, user_id=user.id
        ):
            # 404 for both "no such team" and "you're not a team-admin" —
            # id-probing-safe, same posture as cross-user user-skill reads.
            raise HTTPException(status_code=404, detail="team not found")
        row = UserSkill(
            scope="team",
            owner_team_id=payload.owner_team_id,
            slug=slug,
            display_name=payload.display_name.strip(),
            description=payload.description.strip(),
            version=payload.version.strip(),
            tags=tags,
            frontmatter_extra=frontmatter_extra,
            body=payload.body,
            slash_alias=slash_alias,
            forked_from=forked_from,
        )
        audit_details = {
            "slug": slug,
            "version": payload.version.strip(),
            "tags": tags,
            "scope": "team",
            "team_id": str(payload.owner_team_id),
            "team_slug": team.slug,
        }

    # Documentary capture metadata lands in the audit-log row instead of a
    # dedicated column. Keeps the row schema tight and preserves the
    # forensic trail per ADR 0012 §5.
    if slash_alias is not None:
        audit_details["slash_alias"] = slash_alias
    if forked_from is not None:
        audit_details["forked_from"] = forked_from
    if source_message_id is not None:
        audit_details["source_message_id"] = source_message_id

    db.add(row)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        # The two partial unique indexes that can fire here:
        #   idx_user_skills_slash_alias_owner_active / _team_active
        #   ix_user_skills_owner_slug_active (the existing slug index)
        # Disambiguate via the error text so the right 4xx surfaces.
        err_text = str(getattr(e, "orig", e)).lower()
        if "slash_alias" in err_text:
            raise HTTPException(
                status_code=422,
                detail=(f"slash_alias {slash_alias!r} is already used by another of your skills."),
            ) from None
        owner_label = "team" if payload.scope == "team" else "user"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a user skill named {slug!r} already exists for this {owner_label}",
        ) from None

    await audit_action(
        db,
        user_id=user.id,
        action="user_skill.created",
        resource_type="user_skill",
        resource_id=str(row.id),
        request=request,
        details=audit_details,
    )
    await db.commit()
    await db.refresh(row)

    return _to_response(row)


@router.patch(
    "/{skill_id}",
    response_model=UserSkillResponse,
    summary="Update a user-scope skill (partial; owner-only)",
    responses={404: {"description": "User skill not found"}},
)
async def update_user_skill(
    skill_id: uuid.UUID,
    payload: UserSkillUpdate,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserSkillResponse:
    """PATCH /api/v1/user-skills/{id} — partial update.

    The audit row's ``details.version_before`` / ``version_after`` make
    the *fact* of edits forensically traceable per ADR 0012 §5; the
    *content* of prior versions is not preserved (no history table in
    D8). An idempotent PATCH with no actual changes returns the current
    row without writing an audit row.
    """

    row = await _load_mutable(db, skill_id=skill_id, user_id=user.id)

    changed: dict[str, Any] = {}
    version_before: str | None = None
    if payload.display_name is not None:
        new_value = payload.display_name.strip()
        if new_value != row.display_name:
            row.display_name = new_value
            changed["display_name"] = new_value
    if payload.description is not None:
        new_value = payload.description.strip()
        if new_value != row.description:
            row.description = new_value
            changed["description"] = new_value
    if payload.body is not None and payload.body != row.body:
        row.body = payload.body
        changed["body_length"] = len(payload.body)
    if payload.version is not None:
        new_value = payload.version.strip()
        if new_value != row.version:
            version_before = row.version
            row.version = new_value
            changed["version"] = new_value
    if payload.tags is not None:
        new_tags = _validate_tags(payload.tags)
        if new_tags != list(row.tags or []):
            row.tags = new_tags
            changed["tags"] = new_tags
    if payload.frontmatter_extra is not None:
        new_extra = _validate_frontmatter_extra(payload.frontmatter_extra)
        if new_extra != dict(row.frontmatter_extra or {}):
            row.frontmatter_extra = new_extra
            changed["frontmatter_extra"] = new_extra
    if payload.slash_alias is not None and payload.slash_alias != row.slash_alias:
        # Pydantic already enforces the ``^/[a-z0-9-]{1,32}$`` shape.
        row.slash_alias = payload.slash_alias
        changed["slash_alias"] = payload.slash_alias

    if not changed:
        return _to_response(row)

    details: dict[str, Any] = {
        "slug": row.slug,
        "scope": row.scope,
        "changed_fields": sorted(changed.keys()),
    }
    if row.scope == "team" and row.owner_team_id is not None:
        details["team_id"] = str(row.owner_team_id)
    if version_before is not None:
        details["version_before"] = version_before
        details["version_after"] = row.version

    await audit_action(
        db,
        user_id=user.id,
        action="user_skill.updated",
        resource_type="user_skill",
        resource_id=str(row.id),
        request=request,
        details=details,
    )
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        err_text = str(getattr(e, "orig", e)).lower()
        if "slash_alias" in err_text:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"slash_alias {payload.slash_alias!r} is already used by "
                    "another of your skills."
                ),
            ) from None
        raise
    await db.refresh(row)

    return _to_response(row)


class UserSkillVersionItem(BaseModel):
    """One audit-log row, projected onto the version-history view.

    The ``details`` blob is the raw JSONB column from ``audit_log`` —
    callers consuming this endpoint already trust the action vocabulary
    so re-shaping per action would only add coupling. ``version`` is
    surfaced as a top-level convenience because every create / update
    row carries it and the timeline UI hangs the version pill off it.
    """

    timestamp: datetime
    actor_user_id: uuid.UUID | None = None
    actor_email: str | None = None
    action: str
    version: str | None = None
    details: dict[str, Any] | None = None


class UserSkillVersionsResponse(BaseModel):
    """Wrapper so future cursors / counts can land without a breaking change."""

    items: list[UserSkillVersionItem]


@router.get(
    "/{skill_id}/versions",
    response_model=UserSkillVersionsResponse,
    summary="Audit-log view of edits for this user-skill (Wave D.2)",
    responses={404: {"description": "User skill not found"}},
)
async def list_user_skill_versions(
    skill_id: uuid.UUID,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> UserSkillVersionsResponse:
    """GET /api/v1/user-skills/{id}/versions — most-recent-first audit feed.

    Returns the ``audit_log`` rows for ``resource_type='user_skill'``
    keyed by this skill id. ``user_skill.created`` lands last in the
    list because the result is ordered ``timestamp DESC`` — the timeline
    UI renders top-down, newest at the top.

    Access posture mirrors the mutable surface: user-scope rows are
    visible only to the owner; team-scope rows only to team-admins.
    Non-admin team members read the merged skill via ``GET /skills/{slug}``
    but the audit feed is part of the management surface, not the
    consumption surface, so the read gate is the mutate gate. 404 for
    "no such id" and "exists but not yours" alike (id-probing-safe;
    matches the load-mutable convention elsewhere in this router).

    ``include_archived=True`` because a freshly-archived skill's
    timeline still needs to render for the management UI; ``_load_mutable``
    handles the auth check uniformly across active and archived rows.
    """

    # Reuse the mutable-access gate: read access to the audit timeline
    # is the same as write access to the row (the timeline reveals
    # body deltas via changed-field hints + version transitions).
    await _load_mutable(db, skill_id=skill_id, user_id=user.id, include_archived=True)

    # SELECT both AuditLog (the row) and User.email (the actor handle) in
    # one query; ``db.scalars`` would only return the first entity, so we
    # use ``db.execute(...).all()`` to get Row tuples accessible by
    # attribute (Row.AuditLog, Row.email).
    stmt = (
        select(AuditLog, User.email)
        .outerjoin(User, AuditLog.user_id == User.id)
        .where(
            AuditLog.resource_type == "user_skill",
            AuditLog.resource_id == str(skill_id),
        )
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    items = [
        UserSkillVersionItem(
            timestamp=row.AuditLog.timestamp,
            actor_user_id=row.AuditLog.user_id,
            actor_email=row.email,
            action=row.AuditLog.action,
            version=(row.AuditLog.details or {}).get("version")
            or (row.AuditLog.details or {}).get("version_after"),
            details=row.AuditLog.details,
        )
        for row in rows
    ]
    return UserSkillVersionsResponse(items=items)


@router.delete(
    "/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a user-scope skill (owner-only)",
    responses={
        404: {"description": "User skill not found"},
        410: {"description": "User skill is already archived"},
    },
)
async def delete_user_skill(
    skill_id: uuid.UUID,
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """DELETE /api/v1/user-skills/{id} — soft-delete via ``archived_at``.

    Archived rows free the slug for a new user skill at the same slug.
    The audit log preserves the row's identity so deletion is traceable
    even after the slug has been reused.
    """

    row = await _load_mutable(db, skill_id=skill_id, user_id=user.id, include_archived=True)
    if row.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="user skill is already archived",
        )

    row.archived_at = datetime.now(UTC)

    delete_details: dict[str, Any] = {
        "slug": row.slug,
        "version": row.version,
        "scope": row.scope,
    }
    if row.scope == "team" and row.owner_team_id is not None:
        delete_details["team_id"] = str(row.owner_team_id)

    await audit_action(
        db,
        user_id=user.id,
        action="user_skill.deleted",
        resource_type="user_skill",
        resource_id=str(row.id),
        request=request,
        details=delete_details,
    )
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
