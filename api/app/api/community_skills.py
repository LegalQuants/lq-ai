"""Admin community-skill installer surface — roadmap 3.8 (DE-263, ADR 0027).

Backs the SvelteKit admin page at ``/lq-ai/admin/community-skills``.
Operators browse the community catalog served FROM THE LOCAL SUBMODULE
checkout (``skills/community/skills/`` — never a network fetch, per
ADR 0027 and the single-outbound-client invariant), read the full
SKILL.md (transparency principle: the work product is reviewable before
install), and install a skill as an editable DB-backed copy.

Surface:

* ``GET  /api/v1/admin/community-skills`` — catalog list. Re-scans the
  submodule per request; an absent/empty submodule returns 200 with an
  empty list + operator hint (ADR 0027 §3). Per-skill parse failures
  are surfaced in ``load_errors`` so broken corpus entries are visible.
* ``GET  /api/v1/admin/community-skills/{slug}`` — full detail incl.
  ``content_md`` / ``content_yaml``. 404 unknown slug; 422 when the
  folder exists but its SKILL.md is malformed (the error text says why).
* ``POST /api/v1/admin/community-skills/{slug}/install`` — persist a
  ``user_skills`` row (ADR 0012 semantics) owned by the installing
  admin, validated through :class:`app.api.user_skills.UserSkillCreate`
  so malformed content gets the same 422s a hand-authored skill would.
  Writes ``forked_from = "lq-skills:<slug>@<sha>"`` (sha degrades to
  ``"unknown"``) and a ``community_skill.installed`` audit row in the
  same transaction. 409 when the caller already has a live row at the
  slug.

Auth posture: mounted under ``ActiveUser`` at the include site (bearer +
must-change-password gates), PLUS the handler-level ``AdminUser``
dependency — non-admin authenticated users get 403 on every endpoint.

Attestation honesty: community skills are attested at their source repo
(lq-skills PR process). ``attested_by`` surfaces only what the SKILL.md
frontmatter declares; ``null`` renders as "none declared", never as
attested (ADR 0027 §5).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AdminUser
from app.api.user_skills import UserSkillCreate, UserSkillResponse, _to_response, _validate_slug
from app.audit import audit_action
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.user_skill import UserSkill
from app.skills.community_installer import (
    SUBMODULE_HINT,
    CommunityCatalog,
    attestation_of,
    display_title,
    forked_from_ref,
    install_fields_from_record,
    resolve_catalog_dir,
    scan_catalog,
)
from app.skills.loader import LoaderError, load_skill_folder
from app.skills.registry import SkillRecord

router = APIRouter(prefix="/admin/community-skills", tags=["admin-community-skills"])

_BODY_PREVIEW_CHARS = 280


# ---------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------


class CommunityCatalogSource(BaseModel):
    """Where the catalog came from — stated so staleness is visible."""

    path: str
    """Filesystem path the scan looked at (shown even when absent)."""

    sha: str | None = None
    """Submodule HEAD commit resolved by file-reads of git plumbing;
    ``null`` when unresolvable (surfaced as "unknown" in the UI)."""

    submodule_present: bool
    operator_hint: str | None = None
    """Set when the catalog is absent/empty — names the
    ``git submodule update --init`` remedy."""


class CommunitySkillSummary(BaseModel):
    """One catalog entry — the list view."""

    slug: str
    title: str
    description: str
    version: str
    author: str | None = None
    tags: list[str] = Field(default_factory=list)
    jurisdiction: str | None = None
    attested_by: str | None = None
    """Verbatim frontmatter declaration; ``null`` == none declared in
    SKILL.md. Displayed, never synthesized."""

    installed: bool
    """Whether the CALLING admin already has a live user-scope row at
    this slug (which is exactly the condition that makes install 409)."""

    body_preview: str


class CommunityCatalogResponse(BaseModel):
    items: list[CommunitySkillSummary]
    source: CommunityCatalogSource
    load_errors: list[str] = Field(default_factory=list)
    """Per-skill parse failures from the scan, verbatim — broken corpus
    entries are visible to the operator, not silently dropped."""


class CommunitySkillDetail(CommunitySkillSummary):
    """Full SKILL.md view — the install-confirm surface."""

    output_format: str | None = None
    minimum_inference_tier: int | None = None
    content_yaml: str
    content_md: str
    install_ref: str
    """The ``forked_from`` provenance string an install would write now."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _catalog(settings: Annotated[Settings, Depends(get_settings)]) -> CommunityCatalog:
    """Per-request re-scan of the community corpus (ADR 0027)."""

    return scan_catalog(resolve_catalog_dir(settings))


async def _installed_slugs(db: AsyncSession, *, user_id: Any, slugs: list[str]) -> set[str]:
    """The caller's live user-scope slugs among ``slugs``."""

    if not slugs:
        return set()
    stmt = select(UserSkill.slug).where(
        UserSkill.scope == "user",
        UserSkill.owner_user_id == user_id,
        UserSkill.archived_at.is_(None),
        UserSkill.slug.in_(slugs),
    )
    return set((await db.execute(stmt)).scalars().all())


def _summary_from_record(record: SkillRecord, *, installed: bool) -> CommunitySkillSummary:
    lq = record.frontmatter.lq_ai
    body = record.body.strip()
    return CommunitySkillSummary(
        slug=record.name,
        title=display_title(record),
        description=record.frontmatter.description,
        version=lq.version or "unversioned",
        author=lq.author,
        tags=list(lq.tags),
        jurisdiction=lq.jurisdiction,
        attested_by=attestation_of(record),
        installed=installed,
        body_preview=body[:_BODY_PREVIEW_CHARS],
    )


def _load_record_or_error(catalog: CommunityCatalog, slug: str) -> SkillRecord:
    """Load one community skill by slug; 404 unknown, 422 malformed.

    The slug is validated against the user-skill slug shape FIRST so a
    path-shaped value (``../…``) can never reach the filesystem join.
    A folder that exists but fails to parse gets a 422 carrying the
    loader's error text — the admin sees *why* the skill is broken
    instead of a bare not-found.
    """

    _validate_slug(slug)
    folder = catalog.path / slug
    if not (folder / "SKILL.md").is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"community skill {slug!r} not found in the catalog",
        )
    try:
        return load_skill_folder(folder, source="community")
    except LoaderError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"community skill {slug!r} has a malformed SKILL.md: {exc}",
        ) from None


def _source_info(catalog: CommunityCatalog) -> CommunityCatalogSource:
    empty = not catalog.dir_present or (not catalog.records and not catalog.load_errors)
    return CommunityCatalogSource(
        path=str(catalog.path),
        sha=catalog.sha,
        submodule_present=catalog.dir_present,
        operator_hint=SUBMODULE_HINT if empty else None,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=CommunityCatalogResponse,
    summary="List the community skill catalog from the local submodule (DE-263)",
    responses={403: {"description": "Authenticated but not an admin"}},
)
async def list_community_skills(
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    catalog: Annotated[CommunityCatalog, Depends(_catalog)],
) -> CommunityCatalogResponse:
    """GET /api/v1/admin/community-skills — the catalog list.

    An absent submodule is 200-with-hint, not an error: fresh clones
    without ``--recurse-submodules`` must not break the admin UI.
    """

    installed = await _installed_slugs(
        db, user_id=admin.id, slugs=[r.name for r in catalog.records]
    )
    return CommunityCatalogResponse(
        items=[
            _summary_from_record(record, installed=record.name in installed)
            for record in catalog.records
        ],
        source=_source_info(catalog),
        load_errors=list(catalog.load_errors),
    )


@router.get(
    "/{slug}",
    response_model=CommunitySkillDetail,
    summary="Full SKILL.md detail for one community skill (DE-263)",
    responses={
        403: {"description": "Authenticated but not an admin"},
        404: {"description": "Unknown community skill slug"},
        422: {"description": "SKILL.md exists but is malformed"},
    },
)
async def get_community_skill(
    slug: str,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    catalog: Annotated[CommunityCatalog, Depends(_catalog)],
) -> CommunitySkillDetail:
    """GET /api/v1/admin/community-skills/{slug} — the install-confirm view.

    Returns the full body + raw frontmatter so the operator reviews the
    actual work product before installing (transparency principle).
    """

    record = _load_record_or_error(catalog, slug)
    installed = await _installed_slugs(db, user_id=admin.id, slugs=[record.name])
    summary = _summary_from_record(record, installed=record.name in installed)
    lq = record.frontmatter.lq_ai
    return CommunitySkillDetail(
        **summary.model_dump(),
        output_format=lq.output_format,
        minimum_inference_tier=lq.minimum_inference_tier,
        content_yaml=record.raw_yaml,
        content_md=record.body,
        install_ref=forked_from_ref(record.name, catalog.sha),
    )


@router.post(
    "/{slug}/install",
    response_model=UserSkillResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Install a community skill as an editable user-scope copy (DE-263)",
    responses={
        403: {"description": "Authenticated but not an admin"},
        404: {"description": "Unknown community skill slug"},
        409: {"description": "Caller already has a live user skill at this slug"},
        422: {"description": "SKILL.md malformed or violates user-skill bounds"},
    },
)
async def install_community_skill(
    slug: str,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    catalog: Annotated[CommunityCatalog, Depends(_catalog)],
) -> UserSkillResponse:
    """POST /api/v1/admin/community-skills/{slug}/install.

    The installed copy is a fork (ADR 0012): a user-scope row owned by
    the INSTALLING ADMIN, editable and archivable like any user skill;
    it does not auto-update when the submodule moves. Provenance lives
    in ``forked_from`` + the audit row.

    409 semantics: ``user_skills`` uniqueness is per-owner among
    non-archived rows, so "already installed" is exactly "the caller
    has a live user-scope row at this slug" — including a hand-authored
    one, which install must not clobber. Archiving the row frees the
    slug for re-install (that is the honest re-install path).
    """

    record = _load_record_or_error(catalog, slug)

    # Reuse the ADR 0012 validation path verbatim so a community skill
    # whose parsed fields violate the user-skill bounds is rejected with
    # the same 422 shape a hand-authored skill would get.
    try:
        payload = UserSkillCreate(
            **install_fields_from_record(record),
            forked_from=forked_from_ref(record.name, catalog.sha),
        )
    except ValidationError as exc:
        # Surface the first error the way the loader does — a one-line
        # "this is what's wrong" signal, not the full Pydantic dump.
        errors = exc.errors()
        if errors:
            loc = ".".join(str(p) for p in errors[0].get("loc", ()))
            msg = str(errors[0].get("msg", exc))
        else:  # pragma: no cover — ValidationError always carries errors
            loc, msg = "", str(exc)
        raise HTTPException(
            status_code=422,
            detail=f"community skill {slug!r} violates user-skill bounds: {loc} — {msg}",
        ) from None

    if await _installed_slugs(db, user_id=admin.id, slugs=[record.name]):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"a live user skill named {record.name!r} already exists for you — "
                "archive it first to re-install from the community catalog"
            ),
        )

    row = UserSkill(
        scope="user",
        owner_user_id=admin.id,
        slug=payload.slug,
        display_name=payload.display_name.strip(),
        description=payload.description.strip(),
        version=payload.version.strip(),
        tags=payload.tags,
        frontmatter_extra=payload.frontmatter_extra,
        body=payload.body,
        forked_from=payload.forked_from,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        # Backstop for a concurrent create between the pre-check and the
        # flush — same partial unique index, same honest answer.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a live user skill named {record.name!r} already exists for you",
        ) from None

    audit_details: dict[str, Any] = {
        "slug": record.name,
        "version": payload.version,
        "forked_from": payload.forked_from,
        "source_sha": catalog.sha or "unknown",
        "catalog_path": str(catalog.path),
    }
    attested_by = attestation_of(record)
    if attested_by is not None:
        audit_details["attested_by"] = attested_by

    await audit_action(
        db,
        user_id=admin.id,
        action="community_skill.installed",
        resource_type="user_skill",
        resource_id=str(row.id),
        request=request,
        details=audit_details,
    )
    await db.commit()
    await db.refresh(row)

    return _to_response(row)
