"""Internal service-to-service routes (gateway → backend).

Per ADR 0007 (Skill prompt assembly), the gateway needs to read skill
content from the backend's registry during prompt assembly. The
user-facing ``GET /api/v1/skills/{name}`` endpoint is gated by
``get_active_user`` (B1 bearer + B2 password-change gate) and is
inappropriate for service-to-service traffic — the gateway has no
user.

This module exposes a parallel ``GET /api/v1/internal/skills/{name}``
endpoint authenticated by the existing ``X-LQ-AI-Gateway-Key`` shared
secret. Trust-domain separation: user-facing endpoints stay under
user-token auth; internal endpoints stay under shared-secret auth.
The two never mix on a single route. The response shape is identical
to the user-facing endpoint so the gateway-side client can reuse the
same response model.

Scope (M1):

* ``GET /api/v1/internal/skills/{name}`` — full Skill detail. Same body
  as the user-facing route.
* No ``GET /api/v1/internal/skills`` (list) — the gateway never enumerates,
  it only fetches the specific skill names a request has attached.

Auth posture
------------

The header check is constant-time (``secrets.compare_digest``). A missing
or wrong key returns 401. The gateway-key is shared with the backend via
``LQ_AI_GATEWAY_KEY`` (already set on both services for the
backend → gateway direction; reused here in the reverse direction).

If the operator has not configured ``LQ_AI_GATEWAY_KEY`` (i.e., it is
the empty string), the route returns 500 with
``code=internal_error`` and a clear log line — accepting the call
unauthenticated would be a security hole. This matches the
``LQ_AI_GATEWAY_KEY`` is required posture documented in
``docker-compose.yml``.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.errors import InternalError, NotFound, Unauthorized
from app.models.organization_profile import OrganizationProfile
from app.models.user_skill import UserSkill
from app.skills.registry import MutableSkillRegistry

log = logging.getLogger(__name__)

# The same header name the backend → gateway direction uses (per
# docs/api/gateway-openapi.yaml securitySchemes); we reuse it for the
# reverse direction so operators only configure one secret.
GATEWAY_KEY_HEADER = "X-LQ-AI-Gateway-Key"

router = APIRouter(prefix="/internal", tags=["internal"])


def _verify_gateway_key(presented: str | None) -> None:
    """Constant-time check the presented gateway key against settings.

    Raises :class:`Unauthorized` (401) on missing or wrong key.
    Raises :class:`InternalError` (500) when the operator has not
    configured ``LQ_AI_GATEWAY_KEY`` — accepting traffic with no
    enforced secret would silently break the trust contract.
    """

    settings = get_settings()
    expected = settings.lq_ai_gateway_key
    if not expected:
        # Operator misconfiguration — refuse to accept service-to-service
        # traffic when the shared secret is unset rather than running
        # open. The log line is operator-actionable.
        log.error(
            "LQ_AI_GATEWAY_KEY is not set on the api/ service; refusing "
            "internal traffic. Set the env var and restart."
        )
        raise InternalError(
            message=(
                "Internal API authentication is not configured on the "
                "backend. Operator must set LQ_AI_GATEWAY_KEY."
            ),
        )
    if presented is None or not secrets.compare_digest(presented, expected):
        raise Unauthorized(
            message="Invalid or missing gateway key",
            details={"header": GATEWAY_KEY_HEADER},
        )


def _registry(request: Request) -> MutableSkillRegistry:
    """Return the live skill registry from app state.

    Mirrors the helper in ``app/api/skills.py``. Surfaces a clear
    InternalError (500) rather than ``AttributeError`` if lifespan
    didn't run.
    """

    holder: MutableSkillRegistry | None = getattr(request.app.state, "skill_registry", None)
    if holder is None:
        raise InternalError(
            message=(
                "Skill registry is not initialised; the API process is "
                "not yet ready to serve skill queries."
            ),
            details={"hint": "lifespan startup did not run"},
        )
    return holder


@router.get("/skills/{skill_name}")
async def get_skill_internal(
    request: Request,
    skill_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: uuid.UUID | None = Query(default=None),
    x_lq_ai_gateway_key: str | None = Header(default=None, alias=GATEWAY_KEY_HEADER),
) -> JSONResponse:
    """Return resolved skill detail for ``skill_name``.

    Same response shape as ``GET /api/v1/skills/{skill_name}`` — the
    full ``Skill`` from ``docs/api/backend-openapi.yaml``, with
    ``None``-valued optionals dropped for compactness. Auth is via
    ``X-LQ-AI-Gateway-Key`` (constant-time compare); 401 on bad key,
    404 on unknown skill name.

    Resolution order (ADR 0012 + D8.1b):

    1. ``user_id`` set + non-archived user-scope row for that user
       at this slug → return the user shadow.
    2. ``user_id`` set + non-archived team-scope row at this slug
       owned by any team that user belongs to → return the team
       shadow. Multi-team conflicts resolve to the row with the
       most recent ``updated_at``.
    3. Filesystem-canonical registry → return the built-in.
    4. 404 if none of the three match.

    The gateway calls this with the authenticated user's UUID during
    C2 prompt assembly so shadows actually shape the system prompt;
    callers that don't care about user-scope (e.g., admin tooling)
    omit ``user_id`` and get the registry view directly.

    Cache key strategy (D8.1b decision): the gateway-side cache stays
    keyed on ``(name, user_id)``. Team-membership changes are
    operator-mediated and rare; the existing 60s skill-cache TTL
    absorbs propagation lag without a per-membership signature in
    the key. Re-evaluate if team-membership churn becomes routine.
    """

    _verify_gateway_key(x_lq_ai_gateway_key)

    if user_id is not None:
        # The synthesizer and team-shadow loader live in skills.py — the
        # local imports keep the internal.py → skills.py edge implicit
        # to the resolver branch that actually needs them.
        from app.api.skills import _load_team_shadow, _skill_from_user_skill

        stmt = select(UserSkill).where(
            UserSkill.scope == "user",
            UserSkill.owner_user_id == user_id,
            UserSkill.slug == skill_name,
            UserSkill.archived_at.is_(None),
        )
        shadow = (await db.execute(stmt)).scalar_one_or_none()
        if shadow is not None:
            return JSONResponse(content=_skill_from_user_skill(shadow))

        team_shadow = await _load_team_shadow(db, user_id=user_id, slug=skill_name)
        if team_shadow is not None:
            return JSONResponse(content=_skill_from_user_skill(team_shadow))

    holder = _registry(request)
    registry = holder.current()
    skill = registry.get_skill(skill_name)
    if skill is None:
        raise NotFound(
            message=f"Skill {skill_name!r} is not in the registry.",
            details={"skill_name": skill_name},
        )

    raw = skill.model_dump()
    raw["reference_read_enabled"] = get_settings().skill_reference_read_enabled
    payload = {
        k: v
        for k, v in raw.items()
        if v is not None and not (isinstance(v, list) and len(v) == 0 and k in {"tags"})
    }
    return JSONResponse(content=payload)


# ---------------------------------------------------------------------------
# Organization Profile (D4-coverage)
# ---------------------------------------------------------------------------
#
# The Profile is a singleton (migration 0010) holding a Markdown body the
# gateway prepends to every skill's prompt unless the skill opts out via
# ``use_organization_profile: false`` in its frontmatter (PRD §3.12). We
# synthesize the Skill-shaped response on the fly so the gateway-side
# client can reuse its existing :class:`Skill` parser. When no row exists
# or its body is empty we return 404 — the gateway treats "no profile"
# the same way regardless of which kind of empty it sees.

# Synthetic frontmatter body. Mirrors the shape a real SKILL.md would
# carry (per docs/skill-authoring-guide.md) so the gateway's permissive
# YAML parse extracts the same keys it would from a filesystem skill.
# ``use_organization_profile: false`` is explicit so the assembler never
# tries to recursively prepend the Profile to itself.
_ORG_PROFILE_YAML = (
    "name: organization-profile\n"
    "description: The deployment's Organization Profile — org-wide voice, "
    "templates, and house style automatically prepended to every skill.\n"
    "lq_ai:\n"
    "  title: Organization Profile\n"
    "  version: v1\n"
    "  is_organization_profile: true\n"
    "  use_organization_profile: false\n"
)


@router.get("/organization-profile")
async def get_organization_profile_internal(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_lq_ai_gateway_key: str | None = Header(default=None, alias=GATEWAY_KEY_HEADER),
) -> JSONResponse:
    """Return the Organization Profile as a synthesized Skill payload.

    Auth is the same shared-secret as ``/internal/skills/{name}``. The
    response shape is a :class:`Skill`-compatible JSON body so the
    gateway can plug it into the assembler without a special-case
    parser. ``content_md`` carries the operator-edited Markdown body;
    ``content_yaml`` carries synthesized frontmatter declaring
    ``is_organization_profile: true`` so consumers can identify the
    Profile by metadata rather than name string.

    Returns 404 when no Profile row exists OR when its body is empty —
    the gateway treats both as "no profile to prepend" and the single
    error code keeps the branch simple.
    """

    _verify_gateway_key(x_lq_ai_gateway_key)

    stmt = select(OrganizationProfile).limit(1)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None or not row.content_md.strip():
        raise NotFound(
            message="No Organization Profile is set for this deployment.",
            details={"resource": "organization_profile"},
        )

    payload = {
        "name": "organization-profile",
        "version": "v1",
        "scope": "builtin",
        "title": "Organization Profile",
        "description": (
            "The deployment's Organization Profile — org-wide voice, "
            "templates, and house style automatically prepended to "
            "every skill."
        ),
        "content_yaml": _ORG_PROFILE_YAML,
        "content_md": row.content_md,
        "is_organization_profile": True,
        "use_organization_profile": False,
    }
    return JSONResponse(content=payload)


__all__ = ["GATEWAY_KEY_HEADER", "router"]
