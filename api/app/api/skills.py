"""Skills endpoints — Task C1 (filesystem loading) + Task D8 (user shadows).

Implements the read side of the skills surface and the fork operation:

* ``GET /api/v1/skills`` — list summaries. Merges filesystem-canonical
  built-ins with the caller's user-scope skills per ADR 0012; user
  shadows dedupe a built-in on slug collision.
* ``GET /api/v1/skills/{skill_name}`` — full skill detail. Tries the
  caller's user-scope row first (shadow path); falls through to the
  registry's built-in if no shadow exists.
* ``POST /api/v1/skills/{skill_name}/fork`` — copy a built-in's
  content into a fresh user-scope row owned by the caller (D8). The
  ``scope: team`` branch is rejected with a 400 pointing at D8.1.

The owner-scoped management surface for user skills (POST /user-skills,
PATCH, DELETE, list-mine) lives in
:mod:`app.api.user_skills` — that's where the "manage my skills" page
talks to. This module owns the merged picker view.

Auth: per ``app/api/__init__.py`` the skills router is mounted under
``Depends(get_active_user)``, so every handler here inherits the
B1 bearer-token check plus the B2 must-change-password gate.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.db.session import get_db
from app.errors import NotFound
from app.models.chat import Chat, Message
from app.models.user import User
from app.models.user_skill import UserSkill
from app.skills.connectors import resolve_available_connectors, unavailable_tool_usage
from app.skills.registry import MutableSkillRegistry
from app.skills.schema import (
    SkillFrontmatter,
    SkillInputs,
    extract_inputs,
    filter_summary_for_response,
)

router = APIRouter(prefix="/skills", tags=["skills"])


# ---------------------------------------------------------------------------
# Registry access
# ---------------------------------------------------------------------------


def _registry(request: Request) -> MutableSkillRegistry:
    """Return the live :class:`MutableSkillRegistry` from app state.

    The lifespan handler installs ``app.state.skill_registry``. If the
    handler is somehow exercised before that (e.g., a test that bypasses
    lifespan), surface a clear error rather than ``AttributeError``.
    """

    holder: MutableSkillRegistry | None = getattr(request.app.state, "skill_registry", None)
    if holder is None:
        from app.errors import InternalError

        raise InternalError(
            message="Skill registry is not initialised; the API process is "
            "not yet ready to serve skill queries.",
            details={"hint": "lifespan startup did not run"},
        )
    return holder


# ---------------------------------------------------------------------------
# Synthesizing Skill-shape payloads from user_skills rows
# ---------------------------------------------------------------------------
#
# Filesystem built-ins parse a real ``SKILL.md`` and produce a
# :class:`Skill` (or :class:`SkillSummary`). User-scope rows are
# structured DB data — we synthesize an equivalent payload so the
# wire shape is identical whichever source the row came from. The
# gateway-side parser doesn't need to know which source it's reading.


def _summary_from_user_skill(row: UserSkill) -> dict[str, Any]:
    """Return the ``SkillSummary`` shape for a user-scope row, with
    ``None``/empty optionals dropped per the existing summary contract.

    The ``scope`` is whatever the row carries (``user`` or ``team``)
    rather than hardcoded — D8.1b uses the same synthesizer for both
    scopes so the gateway's payload shape is consistent.
    """

    extra = dict(row.frontmatter_extra or {})
    summary: dict[str, Any] = {
        "name": row.slug,
        "version": row.version,
        "scope": row.scope,
        "title": row.display_name,
        "description": row.description,
        "tags": list(row.tags or []),
        "jurisdiction": extra.get("jurisdiction"),
        "minimum_inference_tier": extra.get("minimum_inference_tier"),
        "output_format": extra.get("output_format"),
    }
    return {k: v for k, v in summary.items() if v is not None and v != []}


def _skill_from_user_skill(row: UserSkill) -> dict[str, Any]:
    """Return the full ``Skill`` shape for a user-scope row.

    The ``content_yaml`` field is synthesized — we don't preserve a
    verbatim YAML block for user skills, so we re-emit one in the
    canonical shape (``name`` / ``description`` / ``lq_ai``) that the
    gateway's permissive parser already handles for filesystem skills.
    """

    import yaml  # local — only this synthesizer uses it

    lq_ai: dict[str, Any] = {"title": row.display_name, "version": row.version}
    if row.tags:
        lq_ai["tags"] = list(row.tags)
    for key, value in (row.frontmatter_extra or {}).items():
        if value is not None and key not in lq_ai:
            lq_ai[key] = value

    frontmatter = {
        "name": row.slug,
        "description": row.description,
        "lq_ai": lq_ai,
    }
    content_yaml = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)

    payload: dict[str, Any] = {
        # Wave D.2 — surface the row UUID so the skill detail page's
        # Versions tab can call the audit-history endpoint without a
        # second round-trip to resolve slug → id. Built-ins (resolved
        # via the registry path below) have no DB id and omit this key.
        "id": str(row.id),
        **_summary_from_user_skill(row),
        "content_yaml": content_yaml,
        "content_md": row.body,
        "reference_files": [],
        "example_files": [],
    }
    return payload


async def _load_user_shadow(db: AsyncSession, *, user_id: uuid.UUID, slug: str) -> UserSkill | None:
    """Return the caller's non-archived user-scope row for ``slug``, if any."""

    stmt = select(UserSkill).where(
        UserSkill.scope == "user",
        UserSkill.owner_user_id == user_id,
        UserSkill.slug == slug,
        UserSkill.archived_at.is_(None),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _load_team_shadow(db: AsyncSession, *, user_id: uuid.UUID, slug: str) -> UserSkill | None:
    """Return the newest non-archived team-scope row at ``slug`` the
    user has access to via team membership, if any (D8.1b).

    Resolution rule for multi-team conflicts: a user who belongs to
    two teams both of which define a team-scope skill at the same
    slug sees the row with the most recent ``updated_at``. The
    decision is per Kevin's design call recorded in handoff
    SESSION-HANDOFF-2026-05-10e § D8.1a. This deliberately does NOT
    take role into account — read access flows to every team member
    (admin OR member); mutate rights stay admin-only via the
    ``_load_mutable`` helper in :mod:`app.api.user_skills`.

    Returns ``None`` when no team-scope row exists at ``slug`` for
    any of the user's teams. The caller (the gateway-internal resolver)
    then falls through to the filesystem-canonical registry.
    """

    # Importing here keeps the skills.py → team.py edge optional —
    # the model module already imports without circularity but the
    # local import documents that this helper is the only consumer
    # of the join.
    from app.models.team import TeamMember

    stmt = (
        select(UserSkill)
        .join(TeamMember, TeamMember.team_id == UserSkill.owner_team_id)
        .where(
            UserSkill.scope == "team",
            UserSkill.slug == slug,
            UserSkill.archived_at.is_(None),
            TeamMember.user_id == user_id,
        )
        .order_by(UserSkill.updated_at.desc(), UserSkill.id.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _list_user_shadows(db: AsyncSession, *, user_id: uuid.UUID) -> list[UserSkill]:
    """All non-archived user-scope rows owned by ``user_id``."""

    stmt = (
        select(UserSkill)
        .where(
            UserSkill.scope == "user",
            UserSkill.owner_user_id == user_id,
            UserSkill.archived_at.is_(None),
        )
        .order_by(UserSkill.updated_at.desc(), UserSkill.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_skills(
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    scope: str = Query(default="all", pattern="^(builtin|user|team|all)$"),
    tag: str | None = Query(default=None),
) -> JSONResponse:
    """Return summaries for skills visible to the caller.

    Merging semantics (per ADR 0012):

    * ``scope=all`` (default) — caller's user-scope rows first, then
      built-ins. Dedup on slug: a user shadow hides the built-in of
      the same slug from this listing.
    * ``scope=user`` — caller's user-scope rows only.
    * ``scope=builtin`` — filesystem built-ins only (no shadow merge).
    * ``scope=team`` — empty list until D8.1 (team scope deferred).

    The ``tag`` filter applies to both layers; a built-in matches if
    its ``lq_ai.tags`` contains the tag, a user shadow matches if its
    ``tags`` column contains it.
    """

    if scope == "team":
        # Deferred to D8.1 per ADR 0012; honor the contract by returning
        # the empty set rather than 501 — clients can render "no team
        # skills yet" without checking for a status code.
        return JSONResponse(content=[])

    holder = _registry(request)
    registry = holder.current()

    user_rows: list[UserSkill] = []
    if scope in ("user", "all"):
        user_rows = await _list_user_shadows(db, user_id=user.id)
        if tag is not None:
            user_rows = [r for r in user_rows if tag in (r.tags or [])]

    user_summaries = [_summary_from_user_skill(r) for r in user_rows]
    shadowed_slugs = {r.slug for r in user_rows}

    if scope == "user":
        return JSONResponse(content=user_summaries)

    builtin_summaries = [
        filter_summary_for_response(s)
        for s in registry.list_summaries(tag=tag)
        if s.name not in shadowed_slugs
    ]

    if scope == "builtin":
        return JSONResponse(content=builtin_summaries)

    return JSONResponse(content=user_summaries + builtin_summaries)


# ---------------------------------------------------------------------------
# Autocomplete (Wave D.2 / Task 2.5)
# ---------------------------------------------------------------------------
#
# The chat composer needs a fast typeahead surface: type ``/``, see your
# slash-aliased skills first; type ``/nda``, see ``/nda``-prefixed
# aliases then ``nda``-prefixed slugs then titles that contain ``nda``.
# This is implementation logic the registry doesn't know about — built-ins
# have no ``slash_alias`` column — so we materialise a unified per-row
# dict and rank in-process. The merged catalogue is small (M1 corpus is
# ~10 built-ins plus a per-user handful of shadows), so an in-memory
# scan is the right call. If the corpus ever exceeds the thousands a DB
# fts index would be the right move (DE candidate).


class SkillAutocompleteItem(BaseModel):
    """One row in the autocomplete response.

    Mirrors the shape the chat composer needs: ``slug`` to dispatch,
    ``slash_alias`` to render the badge, ``title`` + ``description`` for
    the picker, ``scope`` so the UI can disambiguate (a user shadow's
    icon vs the built-in's icon, for example). ``icon`` is optional and
    rides ``frontmatter_extra``-style — present for built-ins that ship
    one, ``None`` otherwise.
    """

    slug: str
    slash_alias: str | None = None
    title: str
    description: str | None = None
    scope: str
    icon: str | None = None


class SkillAutocompleteResponse(BaseModel):
    """The envelope. Always present, even when ``results`` is empty —
    saves the frontend an existence check."""

    results: list[SkillAutocompleteItem]


def _rank_autocomplete_match(q: str, rows: list[dict]) -> list[dict]:
    """Score and sort merged-skill dicts against a non-empty query.

    Three signals (in descending priority):

    * prefix on ``slash_alias`` (matched against ``/`` + ``q``) — score 3
    * prefix on ``slug`` — score 2
    * substring match in ``title`` — score 1

    A row that matches more than one signal takes the highest. Ties keep
    the input order (Python's ``sorted`` is stable). Rows that do not
    match anything score 0 and stay at the tail — the caller is expected
    to filter them out before responding.
    """

    q_lower = q.lower()

    def score(r: dict) -> int:
        s = 0
        slash = r.get("slash_alias")
        if isinstance(slash, str) and slash.lower().startswith("/" + q_lower):
            s = max(s, 3)
        if r.get("slug", "").lower().startswith(q_lower):
            s = max(s, 2)
        title = r.get("title") or ""
        if q_lower and q_lower in title.lower():
            s = max(s, 1)
        return s

    return sorted(rows, key=score, reverse=True)


async def _list_merged_skills_for_user(
    request: Request,
    db: AsyncSession,
    *,
    user: User,
) -> list[dict[str, object]]:
    """Return the merged user + built-in catalog as plain dicts.

    Shadow semantics mirror ``GET /skills`` — a user-scope row at the
    same slug as a built-in hides the built-in from this listing.
    The wire shape carries the autocomplete-relevant fields only:
    ``slug``, ``slash_alias``, ``title``, ``description``, ``scope``,
    plus an optional ``icon`` for built-ins that ship one in their
    frontmatter.

    Team-scope merging is deferred to D8.1 — currently only user-scope
    shadows are layered onto the built-in catalog (matches the
    ``GET /skills`` default-scope contract).
    """

    user_rows = await _list_user_shadows(db, user_id=user.id)
    shadowed_slugs = {r.slug for r in user_rows}

    out: list[dict[str, object]] = []
    for row in user_rows:
        extra = dict(row.frontmatter_extra or {})
        out.append(
            {
                "slug": row.slug,
                "slash_alias": row.slash_alias,
                "title": row.display_name,
                "description": row.description,
                "scope": row.scope,
                "icon": extra.get("icon"),
            }
        )

    holder = _registry(request)
    registry = holder.current()
    for summary in registry.list_summaries():
        if summary.name in shadowed_slugs:
            continue
        out.append(
            {
                "slug": summary.name,
                # Built-ins have no slash_alias — that surface lives only on
                # DB-backed user/team skills (ADR 0012; Wave D.2 Task 2.4).
                "slash_alias": None,
                "title": summary.title,
                "description": summary.description,
                "scope": summary.scope,
                # ``icon`` rides extra frontmatter on built-ins; the
                # SkillSummary pydantic model is ``extra='allow'`` upstream
                # in SkillFrontmatter but the summary itself is locked-down
                # — read from ``model_extra`` if present, else None.
                "icon": (summary.model_extra or {}).get("icon")
                if hasattr(summary, "model_extra")
                else None,
            }
        )
    return out


async def _resolve_skill_for_user(
    request: Request,
    db: AsyncSession,
    *,
    user: User,
    slug: str | None = None,
    slash_alias: str | None = None,
) -> dict[str, object] | None:
    """Resolve a single skill from the caller's merged catalog.

    Used by the send-message handler's slash-fallback path (Wave D.2
    Task 2.7) — when a user types ``/foo ...`` and the frontend didn't
    pre-resolve, the backend retries here. Returns the same dict shape
    as :func:`_list_merged_skills_for_user` (``slug``, ``slash_alias``,
    ``title``, ``description``, ``scope``, ``icon``) or ``None`` if no
    row matches.

    Exactly one of ``slug`` / ``slash_alias`` should be provided; if both
    are given, the slug check wins (built-ins have no alias so a
    slug-match is the more authoritative signal).
    """

    if slug is None and slash_alias is None:
        return None
    rows = await _list_merged_skills_for_user(request, db, user=user)
    for r in rows:
        if slug is not None and r.get("slug") == slug:
            return r
        if slash_alias is not None and r.get("slash_alias") == slash_alias:
            return r
    return None


async def _recent_attached_skill_slugs(
    db: AsyncSession,
    *,
    user_id: object,  # uuid.UUID — typed at call site
    limit: int,
) -> list[str]:
    """Return the caller's N most-recently-used distinct skill slugs.

    Reads from ``messages.applied_skills`` (text[]) joined to the chat's
    owner. Skills are filesystem-canonical (ADR 0007) so this array column
    captures the canonical run history without a join table. The query
    unnests, groups by slug, and orders by the most-recent message
    ``created_at`` per slug.

    The result is **just slugs** — the caller maps them onto the merged
    catalog to recover the title/scope/etc. shape autocomplete needs.
    """

    skill_col = func.unnest(Message.applied_skills).label("slug")
    stmt = (
        select(skill_col, func.max(Message.created_at).label("last_used"))
        .join(Chat, Chat.id == Message.chat_id)
        .where(Chat.owner_id == user_id)
        .group_by(skill_col)
        .order_by(func.max(Message.created_at).desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [r[0] for r in rows if r[0]]


@router.get(
    "/autocomplete",
    response_model=SkillAutocompleteResponse,
    summary="Autocomplete skills by /alias / slug / title (Wave D.2)",
)
async def autocomplete_skills(
    request: Request,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    q: Annotated[str, Query(description="Substring to match. Empty = recents.")] = "",
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> SkillAutocompleteResponse:
    """Typeahead for the chat composer's skill picker.

    Two modes:

    * **Empty ``q``** — return the caller's most-recently-used skills
      (by ``messages.applied_skills``), capped at ``limit``. If the user
      has fewer recents than ``limit``, fill the tail with the
      alphabetical merged catalog (skipping anything already in the
      recents block). Brand-new users with no chat activity see the
      alphabetical fallback exclusively.
    * **Non-empty ``q``** — rank the merged catalog by the three signals
      in ``_rank_autocomplete_match`` (slash-alias prefix > slug prefix
      > title substring) and return up to ``limit`` non-zero matches.

    Shadowing: a user-scope row at the same slug as a built-in hides the
    built-in from results (ADR 0012). The ``scope`` field on each result
    lets the UI render the right affordance.

    Bounds: ``limit`` is hard-clamped via FastAPI's ``Query(ge=1, le=25)``
    — a request for ``limit=50`` returns 422 rather than silently
    truncating, which keeps the contract explicit for the frontend.
    """

    merged = await _list_merged_skills_for_user(request, db, user=user)

    if not q:
        recent_slugs = await _recent_attached_skill_slugs(db, user_id=user.id, limit=limit)
        recent_order = {slug: idx for idx, slug in enumerate(recent_slugs)}
        slug_to_row = {row["slug"]: row for row in merged}
        ordered: list[dict[str, object]] = [
            slug_to_row[slug] for slug in recent_slugs if slug in slug_to_row
        ]
        if len(ordered) < limit:
            tail = sorted(
                (row for row in merged if row["slug"] not in recent_order),
                key=lambda r: str(r["title"]).lower(),
            )
            ordered = ordered + tail
        return SkillAutocompleteResponse(
            results=[SkillAutocompleteItem(**row) for row in ordered[:limit]]  # type: ignore[arg-type]
        )

    ranked = _rank_autocomplete_match(q, merged)
    q_lower = q.lower()

    def matches(row: dict) -> bool:
        slash = row.get("slash_alias")
        if isinstance(slash, str) and slash.lower().startswith("/" + q_lower):
            return True
        if row.get("slug", "").lower().startswith(q_lower):
            return True
        title = row.get("title") or ""
        return q_lower in title.lower()

    filtered = [row for row in ranked if matches(row)]
    return SkillAutocompleteResponse(
        results=[SkillAutocompleteItem(**row) for row in filtered[:limit]]
    )


@router.get("/{skill_name}")
async def get_skill(
    request: Request,
    skill_name: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    """Return full skill detail using the D8.1b resolution stack.

    Resolution order (per ADR 0012 + D8.1b):

    1. The caller's non-archived user-scope shadow at this slug.
    2. The newest non-archived team-scope shadow at this slug owned
       by any team the caller is a member of.
    3. The filesystem-canonical built-in.

    404 if none of the three match. Member-of-team is sufficient for
    read; mutate rights stay admin-only at the management endpoints.
    """

    payload = await _resolve_full_skill_payload(
        request, db=db, user_id=user.id, skill_name=skill_name
    )
    return JSONResponse(content=payload)


async def _resolve_full_skill_payload(
    request: Request,
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    skill_name: str,
) -> dict[str, Any]:
    """Apply the D8.1b resolution stack and return the full Skill payload.

    Shared between ``GET /skills/{name}`` and ``GET /skills/{name}/contents``
    (which return the same shape — PRD §3.4 names the contents endpoint
    explicitly as the inspector backend; ``/skills/{name}`` already
    returns the same data, so contents is an alias the frontend can
    target by URL semantics).
    """

    shadow = await _load_user_shadow(db, user_id=user_id, slug=skill_name)
    if shadow is not None:
        return _skill_from_user_skill(shadow)

    team_shadow = await _load_team_shadow(db, user_id=user_id, slug=skill_name)
    if team_shadow is not None:
        return _skill_from_user_skill(team_shadow)

    holder = _registry(request)
    registry = holder.current()
    skill = registry.get_skill(skill_name)
    if skill is None:
        raise NotFound(
            message=f"Skill {skill_name!r} is not in the registry.",
            details={"skill_name": skill_name},
        )

    available = await resolve_available_connectors(request_id=request.headers.get("x-request-id"))
    skill.unavailable_tool_usage = unavailable_tool_usage(skill.tool_usage, available)

    raw = skill.model_dump()
    # Keep tool_usage and unavailable_tool_usage even when None/[] — both are
    # meaningful verdicts ([] = "all connectors available"; None = "unknown").
    # Preserve the existing None/empty-tags filtering for all other keys.
    return {
        k: v
        for k, v in raw.items()
        if k in {"tool_usage", "unavailable_tool_usage"}
        or (v is not None and not (isinstance(v, list) and len(v) == 0 and k in {"tags"}))
    }


@router.get(
    "/{skill_name}/contents",
    summary="Full skill contents for the skill inspector (PRD §3.4)",
)
async def get_skill_contents(
    request: Request,
    skill_name: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    """Return the full skill payload — SKILL.md + reference + example files.

    Same shape as ``GET /skills/{skill_name}`` (the user-facing read
    endpoint). PRD §3.4 names this endpoint explicitly as the contract
    the "view this skill" affordance + the skill inspector side panel
    target; exposing it under a distinct URL lets the frontend use URL
    semantics ("/contents") to signal inspection intent, even though
    the response body is the same as the base GET. Applies the same
    D8.1b resolution stack (user > team > built-in).
    """

    payload = await _resolve_full_skill_payload(
        request, db=db, user_id=user.id, skill_name=skill_name
    )
    return JSONResponse(content=payload)


@router.get(
    "/{skill_name}/inputs",
    response_model=SkillInputs,
    summary="Declared inputs (form schema) for the skill-input-form pattern",
)
async def get_skill_inputs(
    request: Request,
    skill_name: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SkillInputs:
    """Return the skill's declared inputs (required + optional).

    The PRD §3.4 skill-input-form pattern: skills declare inputs in
    their frontmatter so the UI can render a structured form rather
    than letting the model ask for missing context conversationally.
    Used by Enhance Prompt's "missing required input" surface and by
    any skill author who wants their skill to feel form-driven.

    Resolution mirrors ``GET /skills/{name}``: user > team > built-in.
    For user/team-scope rows the inputs live in ``frontmatter_extra``
    (under either the top-level ``inputs`` key or ``lq_ai.inputs``);
    for built-ins they ride the parsed SkillFrontmatter. Returns an
    empty (name-only) shape when the skill declares no inputs.
    """

    shadow = await _load_user_shadow(db, user_id=user.id, slug=skill_name)
    if shadow is not None:
        return _inputs_from_user_skill_row(shadow)

    team_shadow = await _load_team_shadow(db, user_id=user.id, slug=skill_name)
    if team_shadow is not None:
        return _inputs_from_user_skill_row(team_shadow)

    holder = _registry(request)
    registry = holder.current()
    record = registry.get(skill_name)
    if record is None:
        raise NotFound(
            message=f"Skill {skill_name!r} is not in the registry.",
            details={"skill_name": skill_name},
        )
    return extract_inputs(record.name, record.frontmatter)


def _inputs_from_user_skill_row(row: UserSkill) -> SkillInputs:
    """Build a SkillInputs from a user/team-scope DB row's frontmatter_extra.

    User-skill rows store extension keys in ``frontmatter_extra``;
    when the row carries ``inputs`` (either top-level or under
    ``lq_ai``) we surface it. Skills authored without inputs return
    an empty schema — same UX as built-ins without inputs.
    """

    extras = dict(row.frontmatter_extra or {})
    synthesized = {
        "name": row.slug,
        "description": row.description,
        "lq_ai": {k: v for k, v in extras.items() if k != "inputs"},
    }
    inputs_block = extras.get("inputs")
    if isinstance(inputs_block, dict):
        # Place at top level — extract_inputs checks top-level first,
        # so this gives author-supplied inputs visibility regardless of
        # whether the original SKILL.md nested them under lq_ai.
        synthesized["inputs"] = inputs_block

    try:
        frontmatter = SkillFrontmatter.model_validate(synthesized)
    except Exception:
        # Malformed extras — return empty rather than 500. The skill
        # still resolves through /skills/{name}; the inspector form
        # just won't render fields for it.
        return SkillInputs(name=row.slug)
    return extract_inputs(row.slug, frontmatter)


class SkillForkBody(BaseModel):
    """Request body for ``POST /api/v1/skills/{skill_name}/fork``.

    `extra="forbid"` rejects unknown fields with a 422 — so a typo like
    ``{"name": "x"}`` (instead of ``new_name``) surfaces as a clear
    validation error instead of silently falling back to the source
    slug and 409ing on a collision the user never asked for.
    """

    model_config = ConfigDict(extra="forbid")

    new_name: str | None = Field(
        default=None,
        description=(
            "Slug for the forked user-scope skill. Omit to shadow the "
            "source slug (same name; the user-scope copy wins on lookup)."
        ),
    )
    scope: Literal["user", "team"] = Field(
        default="user",
        description=(
            "Target scope. M1 only supports 'user'; 'team' returns 400 until D8.1 (ADR 0012)."
        ),
    )


@router.post("/{skill_name}/fork", status_code=status.HTTP_201_CREATED)
async def fork_skill(
    request: Request,
    skill_name: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: SkillForkBody | None = None,
) -> JSONResponse:
    """Fork a filesystem-canonical built-in into a new user-scope row.

    Mirrors the OpenAPI sketch's contract (``new_name`` + ``scope`` in
    the body). D8 only implements ``scope='user'``; ``scope='team'`` is
    rejected with a 400 pointing at D8.1.

    If ``new_name`` matches an existing user-scope slug for this user,
    409. If ``new_name`` is omitted or equals the source slug, the new
    row becomes a same-slug shadow — which is the expected "I want my
    own version of nda-review" UX.

    Unknown body fields (e.g., ``{"name": "..."}`` instead of
    ``{"new_name": "..."}``) are rejected with a 422 rather than
    silently dropped — see :class:`SkillForkBody`.
    """

    body = payload or SkillForkBody()
    scope = body.scope
    if scope == "team":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "team-scope skills are deferred to D8.1 (ADR 0012 §Out of scope). "
                "Use scope='user' to fork into your personal scope."
            ),
        )

    holder = _registry(request)
    registry = holder.current()
    source = registry.get_skill(skill_name)
    if source is None:
        raise NotFound(
            message=f"Skill {skill_name!r} is not in the registry.",
            details={"skill_name": skill_name},
        )

    # Local import to avoid circular: user_skills imports nothing from
    # skills, but we want to reuse its slug validator + tag normaliser
    # without duplicating the bounds constants.
    from app.api.user_skills import _validate_slug, _validate_tags

    new_slug = body.new_name or source.name
    new_slug = _validate_slug(new_slug)
    forked_tags = _validate_tags(list(source.tags or []))

    # Mirror the source's lq_ai extension keys onto frontmatter_extra so
    # the synthesized payload after the fork looks shape-identical to
    # the original. Tier-floor, jurisdiction, output_format, etc. all
    # carry through.
    frontmatter_extra: dict[str, Any] = {}
    if source.jurisdiction is not None:
        frontmatter_extra["jurisdiction"] = source.jurisdiction
    if source.minimum_inference_tier is not None:
        frontmatter_extra["minimum_inference_tier"] = source.minimum_inference_tier
    if source.output_format is not None:
        frontmatter_extra["output_format"] = source.output_format

    row = UserSkill(
        scope="user",
        owner_user_id=user.id,
        slug=new_slug,
        display_name=source.title,
        description=source.description or "",
        version=source.version or "1.0.0",
        tags=forked_tags,
        frontmatter_extra=frontmatter_extra,
        body=source.content_md,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a user skill named {new_slug!r} already exists for this user",
        ) from None

    await audit_action(
        db,
        user_id=user.id,
        action="user_skill.created",
        resource_type="user_skill",
        resource_id=str(row.id),
        request=request,
        details={
            "slug": new_slug,
            "version": row.version,
            "tags": forked_tags,
            "forked_from": skill_name,
        },
    )
    await db.commit()
    await db.refresh(row)

    return JSONResponse(content=_skill_from_user_skill(row), status_code=status.HTTP_201_CREATED)
