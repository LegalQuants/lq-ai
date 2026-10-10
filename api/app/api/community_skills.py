"""Admin review and pinned community installation into personal or team scope."""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AdminUser
from app.api.user_skills import (
    UserSkillCreate,
    UserSkillResponse,
    _is_team_admin,
    _to_response,
    _validate_frontmatter_extra,
    _validate_slug,
    _validate_tags,
)
from app.audit import audit_action
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.user_skill import UserSkill
from app.skills.community_installer import (
    SUBMODULE_HINT,
    CommunityCatalog,
    attestation_of,
    canonical_hash,
    display_title,
    forked_from_ref,
    install_fields_from_record,
    installation_snapshot,
    resolve_catalog_dir,
    scan_catalog,
)
from app.skills.loader import LoaderError, load_skill_folder
from app.skills.registry import SkillRecord

router = APIRouter(prefix="/admin/community-skills", tags=["admin-community-skills"])
Scope = Literal["user", "team"]


class CommunityCatalogSource(BaseModel):
    path: str
    sha: str | None = None
    repository: str | None = None
    metadata_source: str = "unknown"
    submodule_present: bool
    operator_hint: str | None = None


class CommunitySkillSummary(BaseModel):
    slug: str
    title: str
    description: str
    version: str
    author: str | None = None
    license: str | None = None
    tags: list[str] = Field(default_factory=list)
    jurisdiction: str | None = None
    attested_by: str | None = None
    installed: bool
    installed_for_me: bool
    body_preview: str


class CommunityCatalogResponse(BaseModel):
    items: list[CommunitySkillSummary]
    source: CommunityCatalogSource
    load_errors: list[str] = Field(default_factory=list)


class CommunitySkillDetail(CommunitySkillSummary):
    output_format: str | None = None
    minimum_inference_tier: int | None = None
    content_yaml: str
    content_md: str
    install_ref: str
    provenance: dict[str, Any]


class CommunitySkillInstall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope = "user"
    owner_team_id: uuid.UUID | None = None
    expected_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def _catalog(settings: Annotated[Settings, Depends(get_settings)]) -> CommunityCatalog:
    return scan_catalog(resolve_catalog_dir(settings))


async def _authorize_target(
    db: AsyncSession, *, user_id: uuid.UUID, scope: Scope, team_id: uuid.UUID | None
) -> None:
    if scope == "user":
        if team_id is not None:
            raise HTTPException(422, "owner_team_id must be null for personal installation")
    elif team_id is None:
        raise HTTPException(422, "Select a receiving team")
    elif not await _is_team_admin(db, team_id=team_id, user_id=user_id):
        # Match ordinary user/team skill permissions, including id-probing safety.
        raise HTTPException(404, "team not found")


async def _installed_slugs(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    slugs: list[str],
    scope: Scope = "user",
    team_id: uuid.UUID | None = None,
) -> set[str]:
    if not slugs:
        return set()
    owner = (
        UserSkill.owner_user_id == user_id
        if scope == "user"
        else UserSkill.owner_team_id == team_id
    )
    stmt = select(UserSkill.slug).where(
        UserSkill.scope == scope, owner, UserSkill.archived_at.is_(None), UserSkill.slug.in_(slugs)
    )
    return set((await db.execute(stmt)).scalars().all())


def _summary_from_record(
    record: SkillRecord, *, installed: bool, installed_for_me: bool
) -> CommunitySkillSummary:
    lq = record.frontmatter.lq_ai
    license_value = (record.frontmatter.model_extra or {}).get("license")
    return CommunitySkillSummary(
        slug=record.name,
        title=display_title(record),
        description=record.frontmatter.description,
        version=lq.version or "unversioned",
        author=lq.author,
        license=license_value if isinstance(license_value, str) else None,
        tags=list(lq.tags),
        jurisdiction=lq.jurisdiction,
        attested_by=attestation_of(record),
        installed=installed,
        installed_for_me=installed_for_me,
        body_preview=record.body.strip()[:280],
    )


def _load_record_or_error(catalog: CommunityCatalog, slug: str) -> SkillRecord:
    _validate_slug(slug)
    folder = catalog.path / slug
    if not folder.resolve().is_relative_to(catalog.path.resolve()) or not (
        folder / "SKILL.md"
    ).resolve().is_relative_to(catalog.path.resolve()):
        raise HTTPException(422, "Skill path leaves the configured catalog")
    if not (folder / "SKILL.md").is_file():
        raise HTTPException(404, f"community skill {slug!r} not found in the catalog")
    try:
        return load_skill_folder(folder, source="community")
    except LoaderError as exc:
        raise HTTPException(
            422, f"community skill {slug!r} has a malformed SKILL.md: {exc}"
        ) from None


def _validated_snapshot(record: SkillRecord, catalog: CommunityCatalog) -> dict[str, Any]:
    try:
        fields = UserSkillCreate(**install_fields_from_record(record))
    except ValidationError as exc:
        raise HTTPException(
            422,
            f"community skill {record.name!r} violates user-skill bounds: {exc.errors()[0]['msg']}",
        ) from None
    try:
        snapshot = installation_snapshot(record, catalog)
        content = snapshot["installed_content"]
        content["tags"] = _validate_tags(fields.tags)
        content["frontmatter_extra"] = _validate_frontmatter_extra(fields.frontmatter_extra)
        snapshot["content_hash"] = canonical_hash(content)
        snapshot.pop("review_hash")
        snapshot["review_hash"] = canonical_hash(
            {"snapshot": snapshot, "raw_yaml": record.raw_yaml}
        )
    except (ValueError, TypeError):
        raise HTTPException(422, "Skill metadata must contain valid JSON values") from None
    return snapshot


@router.get("", response_model=CommunityCatalogResponse)
async def list_community_skills(
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    catalog: Annotated[CommunityCatalog, Depends(_catalog)],
    scope: Scope = "user",
    owner_team_id: uuid.UUID | None = None,
) -> CommunityCatalogResponse:
    await _authorize_target(db, user_id=admin.id, scope=scope, team_id=owner_team_id)
    slugs = [r.name for r in catalog.records]
    personal = await _installed_slugs(db, user_id=admin.id, slugs=slugs)
    installed = (
        personal
        if scope == "user"
        else await _installed_slugs(
            db, user_id=admin.id, slugs=slugs, scope=scope, team_id=owner_team_id
        )
    )
    empty = not catalog.dir_present or (not catalog.records and not catalog.load_errors)
    return CommunityCatalogResponse(
        items=[
            _summary_from_record(
                r, installed=r.name in installed, installed_for_me=r.name in personal
            )
            for r in catalog.records
        ],
        source=CommunityCatalogSource(
            path=str(catalog.path),
            sha=catalog.sha,
            repository=catalog.repository,
            metadata_source=catalog.metadata_source,
            submodule_present=catalog.dir_present,
            operator_hint=SUBMODULE_HINT if empty else None,
        ),
        load_errors=list(catalog.load_errors),
    )


@router.get("/{slug}", response_model=CommunitySkillDetail)
async def get_community_skill(
    slug: str,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    catalog: Annotated[CommunityCatalog, Depends(_catalog)],
    scope: Scope = "user",
    owner_team_id: uuid.UUID | None = None,
) -> CommunitySkillDetail:
    await _authorize_target(db, user_id=admin.id, scope=scope, team_id=owner_team_id)
    record = _load_record_or_error(catalog, slug)
    personal = await _installed_slugs(db, user_id=admin.id, slugs=[record.name])
    installed = (
        personal
        if scope == "user"
        else await _installed_slugs(
            db, user_id=admin.id, slugs=[record.name], scope=scope, team_id=owner_team_id
        )
    )
    summary = _summary_from_record(
        record, installed=record.name in installed, installed_for_me=record.name in personal
    )
    return CommunitySkillDetail(
        **summary.model_dump(),
        output_format=record.frontmatter.lq_ai.output_format,
        minimum_inference_tier=record.frontmatter.lq_ai.minimum_inference_tier,
        content_yaml=record.raw_yaml,
        content_md=record.body,
        install_ref=forked_from_ref(record.name, catalog.sha, catalog.repository),
        provenance=_validated_snapshot(record, catalog),
    )


@router.post(
    "/{slug}/install", response_model=UserSkillResponse, status_code=status.HTTP_201_CREATED
)
async def install_community_skill(
    slug: str,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    catalog: Annotated[CommunityCatalog, Depends(_catalog)],
    install: CommunitySkillInstall,
) -> UserSkillResponse:
    await _authorize_target(
        db, user_id=admin.id, scope=install.scope, team_id=install.owner_team_id
    )
    record = _load_record_or_error(catalog, slug)
    snapshot = _validated_snapshot(record, catalog)
    if not hmac.compare_digest(snapshot["review_hash"], install.expected_review_hash):
        raise HTTPException(
            409, "Catalog changed since review. Review the skill again before installing."
        )
    conflict = f"a live skill named {record.name!r} already exists in the receiving scope — archive it first"
    if await _installed_slugs(
        db,
        user_id=admin.id,
        slugs=[record.name],
        scope=install.scope,
        team_id=install.owner_team_id,
    ):
        raise HTTPException(409, conflict)
    row_id = uuid.uuid4()
    snapshot["distribution"] = {
        "installed_by_user_id": str(admin.id),
        "installed_at": datetime.now(UTC).isoformat(),
        "scope": install.scope,
        "owner_team_id": str(install.owner_team_id) if install.owner_team_id else None,
        "skill_id": str(row_id),
    }
    row = UserSkill(
        id=row_id,
        scope=install.scope,
        owner_user_id=admin.id if install.scope == "user" else None,
        owner_team_id=install.owner_team_id,
        **snapshot["installed_content"],
        forked_from=forked_from_ref(record.name, catalog.sha, catalog.repository),
        installation_provenance=snapshot,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, conflict) from None
    await audit_action(
        db,
        user_id=admin.id,
        action="community_skill.installed",
        resource_type="user_skill",
        resource_id=str(row.id),
        request=request,
        details={
            "slug": row.slug,
            "version": row.version,
            "forked_from": row.forked_from,
            "source": snapshot["source"],
            "content_hash": snapshot["content_hash"],
            "hash_contract": snapshot["hash_contract"],
            "distribution": snapshot["distribution"],
        },
    )
    await db.commit()
    await db.refresh(row)
    return _to_response(row)
