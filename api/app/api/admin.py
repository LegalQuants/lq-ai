"""Admin endpoints — backend proxy + ``is_admin`` gate (D0.5).

Surface (current):

* ``GET    /api/v1/admin/aliases``           — list aliases (D0.5)
* ``GET    /api/v1/admin/aliases/{name}``    — single alias (D0.5)
* ``POST   /api/v1/admin/aliases``           — create alias (D0.5)
* ``PATCH  /api/v1/admin/aliases/{name}``    — update alias (D0.5)
* ``DELETE /api/v1/admin/aliases/{name}``    — remove alias (D0.5)
* ``GET    /api/v1/admin/provider-keys``     — list provider-key status (Donna #7)
* ``POST   /api/v1/admin/provider-keys``     — set/replace runtime key (Donna #7)
* ``PATCH  /api/v1/admin/provider-keys/{p}`` — rotate runtime key (Donna #7)
* ``DELETE /api/v1/admin/provider-keys/{p}`` — revoke runtime key (Donna #7)
* ``GET    /api/v1/admin/config``            — sanitized gateway config (D0.5)
* ``GET    /api/v1/admin/audit-log``         — 501 (D3 wires real impl)
* ``GET    /api/v1/admin/tier-policy``       — 501 (D1)
* ``PATCH  /api/v1/admin/tier-policy``       — 501 (D1)

Auth posture: every admin endpoint stacks on top of the existing
``ActiveUser`` (bearer + must-change-password gate) AND the new
``AdminUser`` dependency that requires ``user.is_admin == True``.
Non-admin authenticated users see 403 with ``code = "forbidden"``.

The alias-CRUD endpoints proxy the gateway's ``/admin/v1/aliases``
surface. The backend is the only entity that holds the gateway-key,
so users can only mutate aliases through this router. The
:class:`GatewayClient` adds the gateway-key header on every call and
translates structured errors from the gateway via ADR 0003 — the
backend's typed exceptions surface as the canonical ``{"detail": ...}``
envelope through the global exception handler in :mod:`app.main`.
"""

from __future__ import annotations

import uuid as _uuid_mod
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, Select, Text, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AdminUser
from app.clients.gateway import GatewayClient, get_gateway_client
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.document import Document as DocumentORM
from app.models.file import File as FileORM
from app.models.user import User as UserORM

router = APIRouter(prefix="/admin", tags=["admin"])

_D1 = "D1 — Tier-floor enforcement (refusals)"


# ---------------------------------------------------------------------------
# D3 — /admin/audit-log read endpoint with privilege/tier/date filtering.
# ---------------------------------------------------------------------------


class AuditLogEntry(BaseModel):
    """Wire shape for one audit_log row in the read endpoint response."""

    id: str
    timestamp: datetime
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    privilege_marked: bool
    privilege_basis: str | None
    routed_inference_tier: int | None
    routed_provider: str | None
    ip_address: str | None
    user_agent: str | None
    request_id: str | None
    details: dict[str, Any] | None


class AuditLogPage(BaseModel):
    """Paginated response for ``GET /api/v1/admin/audit-log``."""

    items: list[AuditLogEntry]
    next_cursor: str | None = None


# Default page size; matches the C3 chats listing pattern. Operators
# with heavy audit-log volumes can adjust via the ``limit`` query param
# up to AUDIT_LOG_PAGE_MAX.
AUDIT_LOG_PAGE_DEFAULT = 50
AUDIT_LOG_PAGE_MAX = 500


@router.get(
    "/audit-log",
    response_model=AuditLogPage,
    summary="List audit-log entries with privilege / tier filters (D3)",
)
async def get_audit_log(
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    privilege_marked: Annotated[
        bool | None,
        Query(
            description=(
                "Filter to entries with the given privilege flag. Omit to "
                "return both privileged and non-privileged rows."
            ),
        ),
    ] = None,
    routed_inference_tier: Annotated[
        int | None,
        Query(
            ge=1,
            le=5,
            description=(
                "Filter to entries with the given routed inference tier "
                "(1-5). Omit to return all tiers (and non-inference entries)."
            ),
        ),
    ] = None,
    action: Annotated[
        str | None,
        Query(description="Exact-match filter on ``action`` (e.g., ``chat.message_sent``)."),
    ] = None,
    user_id: Annotated[
        str | None,
        Query(description="Filter to entries authored by the given user (UUID string)."),
    ] = None,
    since: Annotated[
        datetime | None,
        Query(description="ISO-8601 timestamp; only entries at or after this time."),
    ] = None,
    until: Annotated[
        datetime | None,
        Query(description="ISO-8601 timestamp; only entries at or before this time."),
    ] = None,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=AUDIT_LOG_PAGE_MAX,
            description=f"Page size (1-{AUDIT_LOG_PAGE_MAX}).",
        ),
    ] = AUDIT_LOG_PAGE_DEFAULT,
    cursor: Annotated[
        str | None,
        Query(
            description=(
                "Opaque pagination cursor (the previous page's "
                "``next_cursor``). Omit on the first page."
            ),
        ),
    ] = None,
) -> AuditLogPage:
    """GET /api/v1/admin/audit-log — admin-only read of the audit log.

    Filters compose with AND. The result is ordered by
    ``timestamp DESC`` (most recent first). Pagination is cursor-based
    against the timestamp+id pair, so concurrent inserts during a
    paginated walk don't shift the page boundaries.

    Privilege filter semantics: ``privilege_marked=true`` returns only
    privileged-project rows (per PRD §3.11 / D3 verification step);
    ``privilege_marked=false`` returns only non-privileged rows; omitting
    the parameter returns both.
    """

    stmt = select(AuditLog)

    if privilege_marked is not None:
        stmt = stmt.where(AuditLog.privilege_marked.is_(privilege_marked))
    if routed_inference_tier is not None:
        stmt = stmt.where(AuditLog.routed_inference_tier == routed_inference_tier)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if since is not None:
        stmt = stmt.where(AuditLog.timestamp >= since)
    if until is not None:
        stmt = stmt.where(AuditLog.timestamp <= until)

    if cursor is not None:
        # Cursor encodes (iso-timestamp)|(uuid). We split on the last
        # ``|`` to remain robust against ISO timestamps that contain
        # ``+``. Bad cursors fall through to the "no filter" branch
        # rather than 4xx-ing — the next page just starts from the top.
        try:
            cursor_ts_str, cursor_id = cursor.rsplit("|", 1)
            cursor_ts = datetime.fromisoformat(cursor_ts_str)
            stmt = stmt.where(
                (AuditLog.timestamp < cursor_ts)
                | ((AuditLog.timestamp == cursor_ts) & (AuditLog.id > cursor_id))
            )
        except (ValueError, TypeError):
            pass

    stmt = stmt.order_by(AuditLog.timestamp.desc(), AuditLog.id.asc()).limit(limit + 1)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    next_cursor: str | None = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = f"{last.timestamp.isoformat()}|{last.id}"

    items = [
        AuditLogEntry(
            id=str(r.id),
            timestamp=r.timestamp,
            user_id=str(r.user_id) if r.user_id else None,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            privilege_marked=r.privilege_marked,
            privilege_basis=r.privilege_basis,
            routed_inference_tier=r.routed_inference_tier,
            routed_provider=r.routed_provider,
            ip_address=str(r.ip_address) if r.ip_address else None,
            user_agent=r.user_agent,
            request_id=r.request_id,
            details=r.details,
        )
        for r in page_rows
    ]

    return AuditLogPage(items=items, next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# Existing surface (A4 stubs not yet implemented)
# ---------------------------------------------------------------------------


class TierPolicyResponse(BaseModel):
    """``GET /admin/tier-policy`` body (Wave B)."""

    allowed_tiers_global: list[int]
    default_minimum_tier: int
    privileged_minimum_tier: int
    warn_on_tiers: list[int]


class TierPolicyPatchRequest(BaseModel):
    """``PATCH /admin/tier-policy`` body — partial update (Wave B)."""

    allowed_tiers_global: list[int] | None = None
    default_minimum_tier: int | None = Field(default=None, ge=1, le=5)
    privileged_minimum_tier: int | None = Field(default=None, ge=1, le=5)
    warn_on_tiers: list[int] | None = None


def _project_tier_policy(payload: dict[str, Any]) -> TierPolicyResponse:
    policy = payload.get("tier_policy", {})
    return TierPolicyResponse(
        allowed_tiers_global=list(policy.get("allowed_tiers_global") or [1, 2, 3, 4]),
        default_minimum_tier=int(policy.get("default_minimum_tier", 4)),
        privileged_minimum_tier=int(policy.get("privileged_minimum_tier", 3)),
        warn_on_tiers=list(policy.get("warn_on_tiers") or [4, 5]),
    )


@router.get("/tier-policy", response_model=TierPolicyResponse)
async def get_tier_policy(
    request: Request,
    _admin: AdminUser,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> TierPolicyResponse:
    """GET /api/v1/admin/tier-policy — operator's tier policy (admin-only).

    Returns the same shape as ``GET /api/v1/inference/tier-config``;
    the admin variant exists so the admin UI can render the policy on
    the operator console without granting the read endpoint to every
    user (it's already user-accessible at the non-admin URL, but
    surfacing it under /admin keeps the operator UI's permission model
    clean).
    """

    payload = await gateway.get_tier_config(request_id=request.headers.get("x-request-id"))
    return _project_tier_policy(payload)


@router.patch("/tier-policy", response_model=TierPolicyResponse)
async def update_tier_policy(
    request: Request,
    body: TierPolicyPatchRequest,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> TierPolicyResponse:
    """PATCH /api/v1/admin/tier-policy — partial-update the tier policy.

    Proxies through to the gateway's PATCH /admin/v1/tier-config (which
    atomically rewrites ``gateway.yaml`` and reloads the live snapshot).
    Writes a ``tier_policy.updated`` audit row with before/after values
    so a privacy auditor can reconstruct the policy history.
    """

    from app.audit import audit_action

    before_payload = await gateway.get_tier_config(request_id=request.headers.get("x-request-id"))
    before = _project_tier_policy(before_payload)

    payload_to_send = body.model_dump(exclude_none=True)
    if not payload_to_send:
        return before

    updated_payload = await gateway.patch_tier_config(
        body=payload_to_send,
        request_id=request.headers.get("x-request-id"),
    )
    after = _project_tier_policy(updated_payload)

    if after.model_dump() != before.model_dump():
        await audit_action(
            db,
            user_id=admin.id,
            action="tier_policy.updated",
            resource_type="tier_policy",
            resource_id="singleton",
            request=request,
            details={
                "before": before.model_dump(),
                "after": after.model_dump(),
                "fields_supplied": sorted(payload_to_send.keys()),
            },
        )
        await db.commit()

    return after


# ---------------------------------------------------------------------------
# Wave B — /admin/usage (cost + tokens dashboard)
# ---------------------------------------------------------------------------


class UsageRow(BaseModel):
    """One aggregated row from /admin/usage."""

    group_key: str
    request_count: int
    tokens_in_sum: int = 0
    tokens_out_sum: int = 0
    cost_estimate_sum: float = 0.0


class UsageResponse(BaseModel):
    rows: list[UsageRow]
    group_by: str
    total_request_count: int
    total_tokens_in: int
    total_tokens_out: int
    total_cost_estimate: float


_USAGE_GROUP_BY = {"user", "provider", "model", "tier", "day"}


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    request: Request,
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    group_by: str = Query(default="provider"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    user_id: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    tier: int | None = Query(default=None, ge=1, le=5),
) -> UsageResponse:
    """GET /api/v1/admin/usage — cost + tokens aggregations (Wave B / PRD §5.5).

    Aggregates ``inference_routing_log`` by one of: user, provider,
    model, tier, day. Filters on the same dimensions plus a date range.
    Refusals are excluded by default (they didn't consume tokens
    upstream). All counts/sums are returned alongside a deployment-wide
    total so the admin UI can render percentages without a second
    query.
    """

    from app.models.inference import InferenceRoutingLog

    if group_by not in _USAGE_GROUP_BY:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail=f"group_by must be one of {sorted(_USAGE_GROUP_BY)}",
        )

    group_col_map = {
        "user": func.coalesce(
            func.cast(InferenceRoutingLog.user_id, type_=Text),
            "anonymous",
        ),
        "provider": InferenceRoutingLog.routed_provider,
        "model": InferenceRoutingLog.routed_model,
        "tier": func.cast(InferenceRoutingLog.routed_inference_tier, type_=Text),
        "day": func.to_char(InferenceRoutingLog.timestamp, "YYYY-MM-DD"),
    }
    group_col = group_col_map[group_by]

    # Annotate as `ColumnElement[bool]` so mypy doesn't infer the narrower
    # `BinaryExpression[bool]` from the first element and then reject the
    # `==` / `>=` comparisons below.
    conditions: list[ColumnElement[bool]] = [InferenceRoutingLog.refused.is_(False)]
    if date_from is not None:
        conditions.append(InferenceRoutingLog.timestamp >= date_from)
    if date_to is not None:
        conditions.append(InferenceRoutingLog.timestamp <= date_to)
    if user_id is not None:
        conditions.append(func.cast(InferenceRoutingLog.user_id, type_=Text) == user_id)
    if provider is not None:
        conditions.append(InferenceRoutingLog.routed_provider == provider)
    if model is not None:
        conditions.append(InferenceRoutingLog.routed_model == model)
    if tier is not None:
        conditions.append(InferenceRoutingLog.routed_inference_tier == tier)

    # `group_col` is dynamic across the if-branches above, so mypy can't
    # infer the row type for the Select; annotate explicitly.
    stmt: Select[Any] = (
        select(
            group_col.label("group_key"),
            func.count().label("request_count"),
            func.coalesce(func.sum(InferenceRoutingLog.tokens_in), 0).label("tokens_in_sum"),
            func.coalesce(func.sum(InferenceRoutingLog.tokens_out), 0).label("tokens_out_sum"),
            func.coalesce(func.sum(InferenceRoutingLog.cost_estimate), 0).label(
                "cost_estimate_sum"
            ),
        )
        .where(and_(*conditions))
        .group_by(group_col)
        .order_by(func.count().desc())
    )

    rows = (await db.execute(stmt)).all()

    usage_rows = [
        UsageRow(
            group_key=str(row.group_key) if row.group_key is not None else "unknown",
            request_count=int(row.request_count or 0),
            tokens_in_sum=int(row.tokens_in_sum or 0),
            tokens_out_sum=int(row.tokens_out_sum or 0),
            cost_estimate_sum=float(row.cost_estimate_sum or 0),
        )
        for row in rows
    ]

    return UsageResponse(
        rows=usage_rows,
        group_by=group_by,
        total_request_count=sum(r.request_count for r in usage_rows),
        total_tokens_in=sum(r.tokens_in_sum for r in usage_rows),
        total_tokens_out=sum(r.tokens_out_sum for r in usage_rows),
        total_cost_estimate=sum(r.cost_estimate_sum for r in usage_rows),
    )


# ---------------------------------------------------------------------------
# D0.5: alias CRUD proxy
# ---------------------------------------------------------------------------


class _FallbackEntry(BaseModel):
    """One ``fallback`` list entry on an alias write."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


class AliasCreateRequest(BaseModel):
    """Request body for ``POST /api/v1/admin/aliases``."""

    name: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    fallback: list[_FallbackEntry] | None = None


class AliasUpdateRequest(BaseModel):
    """Request body for ``PATCH /api/v1/admin/aliases/{name}``."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    fallback: list[_FallbackEntry] | None = None


@router.get("/aliases")
async def list_aliases(
    _admin: AdminUser,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> dict[str, Any]:
    """List configured aliases via the gateway's admin surface."""

    return await gateway.list_aliases()


@router.get("/aliases/{name}")
async def get_alias(
    name: str,
    _admin: AdminUser,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> dict[str, Any]:
    """Return a single alias. 404 propagates from the gateway."""

    return await gateway.get_alias(name)


@router.post("/aliases", status_code=status.HTTP_201_CREATED)
async def create_alias(
    body: AliasCreateRequest,
    _admin: AdminUser,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> dict[str, Any]:
    """Create a new alias. 409 propagates from the gateway."""

    payload = body.model_dump(mode="json", exclude_none=True)
    return await gateway.create_alias(payload)


@router.patch("/aliases/{name}")
async def update_alias(
    name: str,
    body: AliasUpdateRequest,
    _admin: AdminUser,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> dict[str, Any]:
    """Update an existing alias. 404 propagates from the gateway."""

    payload = body.model_dump(mode="json", exclude_none=True)
    return await gateway.update_alias(name, payload)


@router.delete("/aliases/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_alias(
    name: str,
    _admin: AdminUser,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> JSONResponse:
    """Remove an alias. 404 propagates from the gateway."""

    await gateway.delete_alias(name)
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)


@router.get("/config")
async def get_admin_config(
    _admin: AdminUser,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> dict[str, Any]:
    """Return the gateway's sanitized current config (D0.5)."""

    return await gateway.get_admin_config()


# ---------------------------------------------------------------------------
# Donna #7 — runtime provider-key (BYOK) proxy
# ---------------------------------------------------------------------------
# These endpoints proxy the gateway's ``/admin/v1/provider-keys`` surface,
# mirroring the alias-CRUD proxy above. The backend is the only entity that
# holds the gateway-key; the frontend never does. The gateway encrypts the
# plaintext key, persists it to gateway.yaml, and hot-applies the rebuilt
# adapter — the backend simply forwards the JSON. No secret is ever returned
# (the gateway's status rows carry at most the last 4 characters of a key).
#
# Error propagation: the gateway returns 400 (``failed_precondition``) when
# the master key is unset, 404 (``not_found``) for an unknown provider, and
# 409 (``conflict``) when revoking a non-runtime (env-sourced) key. The
# GatewayClient maps each via ``map_gateway_error_code`` to a backend typed
# exception, so the same 4xx surfaces to the caller (the 400 master-key case
# maps to ValidationError → 400, not a 500).


class ProviderKeySetRequest(BaseModel):
    """Request body for ``POST /api/v1/admin/provider-keys``."""

    provider: str = Field(min_length=1)
    api_key: str = Field(min_length=1)


class ProviderKeyRotateRequest(BaseModel):
    """Request body for ``PATCH /api/v1/admin/provider-keys/{provider}``."""

    api_key: str = Field(min_length=1)


@router.get("/provider-keys")
async def list_provider_keys(
    _admin: AdminUser,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> dict[str, Any]:
    """List provider-key status via the gateway. No secret is returned."""

    return await gateway.list_provider_keys()


@router.post("/provider-keys")
async def set_provider_key(
    body: ProviderKeySetRequest,
    _admin: AdminUser,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> dict[str, Any]:
    """Set/replace a provider's runtime key. 400 / 404 propagate from the gateway."""

    return await gateway.set_provider_key(body.model_dump(mode="json"))


@router.patch("/provider-keys/{provider}")
async def rotate_provider_key(
    provider: str,
    body: ProviderKeyRotateRequest,
    _admin: AdminUser,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> dict[str, Any]:
    """Rotate a provider's runtime key. 400 / 404 propagate from the gateway."""

    return await gateway.rotate_provider_key(provider, body.model_dump(mode="json"))


@router.delete(
    "/provider-keys/{provider}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def revoke_provider_key(
    provider: str,
    _admin: AdminUser,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> Response:
    """Revoke a provider's runtime key. 404 / 409 propagate from the gateway.

    Uses the canonical DELETE-204 recipe (``response_class=Response`` plus an
    explicit empty ``Response`` return) so the 204 carries a genuinely empty
    body.
    """

    await gateway.delete_provider_key(provider)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Wave C — RBAC three-role management (PRD §5.2)
# ---------------------------------------------------------------------------

_ROLE_ENUM = frozenset({"admin", "member", "viewer"})


class AdminUserRow(BaseModel):
    """One row in the admin user list (Wave B v2 — PRD §5.2)."""

    id: _uuid_mod.UUID
    email: str
    display_name: str | None
    role: str  # 'admin' | 'member' | 'viewer'
    is_admin: bool
    mfa_enabled: bool
    must_change_password: bool
    created_at: datetime
    last_login_at: datetime | None
    deletion_scheduled_at: datetime | None


class AdminUserListResponse(BaseModel):
    """Paginated user list for ``GET /api/v1/admin/users``."""

    users: list[AdminUserRow]
    total_count: int
    limit: int
    offset: int


@router.get(
    "/users",
    response_model=AdminUserListResponse,
    summary="List users for RBAC administration (Wave B v2 — PRD §5.2)",
)
async def list_users(
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: str | None = None,
    email_q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AdminUserListResponse:
    """GET /api/v1/admin/users — paginated, filtered user list (admin-only).

    Returns all non-deleted users with their full auth state. Supports
    optional filtering by role and email substring. Default sort is
    ``email ASC`` for predictable alphabetical scanning. Pagination via
    ``limit`` + ``offset``; ``total_count`` is the full filtered count
    before pagination so the UI can show "Showing 50 of 187".

    Users with a pending deletion (``deletion_scheduled_at`` set) are
    included so admins can see the grace-period state and act if needed.
    """
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    stmt = select(UserORM).where(UserORM.deleted_at.is_(None))

    if role is not None:
        if role not in _ROLE_ENUM:
            raise HTTPException(status_code=400, detail="invalid role filter")
        stmt = stmt.where(UserORM.role == role)

    if email_q is not None and email_q.strip():
        # email is CITEXT — ilike works but CITEXT makes the comparison
        # case-insensitive at the DB layer already; ilike adds the
        # substring wildcard.
        stmt = stmt.where(UserORM.email.ilike(f"%{email_q.strip()}%"))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count: int = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(UserORM.email.asc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()

    return AdminUserListResponse(
        users=[
            AdminUserRow(
                id=r.id,
                email=r.email,
                display_name=r.display_name,
                role=r.role,
                is_admin=r.is_admin,
                mfa_enabled=r.mfa_enabled,
                must_change_password=r.must_change_password,
                created_at=r.created_at,
                last_login_at=r.last_login_at,
                deletion_scheduled_at=r.deletion_scheduled_at,
            )
            for r in rows
        ],
        total_count=total_count,
        limit=limit,
        offset=offset,
    )


class UserRoleUpdate(BaseModel):
    """``PATCH /admin/users/{user_id}/role`` body."""

    role: str


class UserRoleResponse(BaseModel):
    """``PATCH /admin/users/{user_id}/role`` response."""

    user_id: str
    email: str
    role: str
    is_admin: bool


@router.patch("/users/{user_id}/role", response_model=UserRoleResponse)
async def update_user_role(
    user_id: str,
    body: UserRoleUpdate,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserRoleResponse:
    """PATCH /api/v1/admin/users/{user_id}/role — set RBAC role (Wave C).

    Admin-only. Updates ``users.role`` and keeps ``is_admin`` in sync
    (True iff role='admin'). Idempotent: re-applying the same role
    returns 200 without writing an audit row. Writes
    ``user.role_updated`` on real changes with before/after values.

    Refuses to demote the last admin (lockout protection): if the
    target user is the only ``role='admin'`` row in the deployment
    and the caller is trying to set them to non-admin, returns 409
    so the operator can promote someone else first.
    """

    from app.audit import audit_action
    from app.errors import Forbidden, NotFound

    if body.role not in _ROLE_ENUM:
        raise HTTPException(
            status_code=422,
            detail=f"role must be one of {sorted(_ROLE_ENUM)}",
        )

    try:
        target_uuid = _uuid_mod.UUID(user_id)
    except (TypeError, ValueError):
        raise NotFound(message="user not found") from None

    target = await db.get(UserORM, target_uuid)
    if target is None or target.deleted_at is not None:
        raise NotFound(message="user not found")

    before_role = target.role
    if before_role == body.role:
        return UserRoleResponse(
            user_id=str(target.id),
            email=target.email,
            role=target.role,
            is_admin=target.is_admin,
        )

    # Lockout protection: don't allow demoting the last admin.
    if before_role == "admin" and body.role != "admin":
        remaining_admins = (
            await db.execute(
                select(func.count())
                .select_from(UserORM)
                .where(
                    UserORM.role == "admin",
                    UserORM.id != target.id,
                    UserORM.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        if int(remaining_admins or 0) == 0:
            raise Forbidden(
                message=(
                    "Cannot demote the last admin. Promote another user to "
                    "admin first, then retry the demotion."
                ),
            )

    target.role = body.role
    target.is_admin = body.role == "admin"

    await audit_action(
        db,
        user_id=admin.id,
        action="user.role_updated",
        resource_type="user",
        resource_id=str(target.id),
        request=request,
        details={
            "before": {"role": before_role},
            "after": {"role": body.role},
            "target_user_email": target.email,
        },
    )
    await db.commit()
    await db.refresh(target)

    return UserRoleResponse(
        user_id=str(target.id),
        email=target.email,
        role=target.role,
        is_admin=target.is_admin,
    )


# ---------------------------------------------------------------------------
# M3-0.3 / DE-276 — /admin/ingest-health (aggregate ingest status)
# ---------------------------------------------------------------------------


class IngestHealthResponse(BaseModel):
    """Aggregate ingest-status counts across the deployment.

    The four document-level buckets sum to roughly the document count
    (rows in ``documents``); ``parse_failed`` reports file-level
    failures (rows in ``files`` with ``ingestion_status='failed'``),
    which never reach the ``documents`` table.

    Operators use this surface as the canonical "is my ingest healthy?"
    signal — a non-zero ``embed_failed`` or ``partial`` count is the
    silent-degrade signal that triggered DE-276; a non-zero
    ``parse_failed`` count is the operator's cue to inspect specific
    files via the existing file-list UI.
    """

    ok: int = Field(description="Documents with all chunks successfully embedded.")
    embed_failed: int = Field(
        description=(
            "Documents whose embed worker raised before any chunk was embedded — "
            "hybrid retrieval degrades to FTS-only for these."
        )
    )
    partial: int = Field(
        description=(
            "Documents whose embed worker raised mid-batch — some chunks have "
            "vectors, others are NULL. Operators may re-run ingest to recover."
        )
    )
    parse_failed: int = Field(
        description=(
            "Files that failed at parse time and never produced a documents row "
            "(``files.ingestion_status='failed'``)."
        )
    )
    total_documents: int = Field(
        description="Total rows in the documents table (sum of ok + embed_failed + partial)."
    )


@router.get("/ingest-health", response_model=IngestHealthResponse)
async def get_ingest_health(
    _admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IngestHealthResponse:
    """GET /api/v1/admin/ingest-health — aggregate ingest-status counts (admin-only).

    The endpoint is read-only and stateless. Two queries: one grouped
    aggregate over ``documents.ingest_status``, one filtered count over
    ``files.ingestion_status``. Soft-deleted rows are excluded from
    both (the operator is asking about the live deployment surface, not
    historical state).
    """

    # Document-level statuses (M3-0.3 / DE-276 surface).
    doc_status_stmt = (
        select(DocumentORM.ingest_status, func.count())
        .select_from(DocumentORM)
        .join(FileORM, DocumentORM.file_id == FileORM.id)
        .where(FileORM.deleted_at.is_(None))
        .group_by(DocumentORM.ingest_status)
    )
    doc_status_rows = (await db.execute(doc_status_stmt)).all()
    by_status: dict[str, int] = {row[0]: int(row[1]) for row in doc_status_rows}

    ok_count = by_status.get("ok", 0)
    embed_failed_count = by_status.get("embed_failed", 0)
    partial_count = by_status.get("partial", 0)
    total_documents = ok_count + embed_failed_count + partial_count

    # File-level parse failures (existing M1 surface — surfaced here so
    # operators get a single ingest-health summary instead of two).
    parse_failed_stmt = (
        select(func.count())
        .select_from(FileORM)
        .where(FileORM.ingestion_status == "failed", FileORM.deleted_at.is_(None))
    )
    parse_failed_count = int((await db.execute(parse_failed_stmt)).scalar_one())

    return IngestHealthResponse(
        ok=ok_count,
        embed_failed=embed_failed_count,
        partial=partial_count,
        parse_failed=parse_failed_count,
        total_documents=total_documents,
    )
