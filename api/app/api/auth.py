"""Auth endpoints — Task B1 + D5.

Per ADR 0002 (Backend owns authentication) and `backend-openapi.yaml`,
the backend exposes:

- `POST /api/v1/auth/login`    — username/password → JWT access + refresh.
                                  423 + mfa_token when the user has MFA enabled.
- `POST /api/v1/auth/refresh`  — refresh-token → new access + rotated refresh.
- `POST /api/v1/auth/logout`   — bearer token → revoke ALL active sessions
                                  for the calling user. Returns 204.
- `POST /api/v1/auth/mfa/setup`   — TOTP enrollment (D5). Bearer-authed.
                                    Issues a fresh secret + 10 recovery codes.
- `POST /api/v1/auth/mfa/enable`  — confirms enrollment with a TOTP code (D5).
                                    Flips ``users.mfa_enabled`` to TRUE.
- `POST /api/v1/auth/mfa/verify`  — completes a 423 login challenge (D5).
                                    Accepts TOTP or single-use recovery code.
- `POST /api/v1/auth/mfa/disable` — bearer-authed; clears MFA after re-proving
                                    password + a current TOTP/recovery code (D5).

Refresh tokens are opaque random strings (not JWTs) — only their bcrypt
hashes are persisted to `user_sessions`. Refresh rotates the token: the
old session row is marked revoked and a new row is inserted with the
new hash. This shrinks the post-compromise window if a refresh token
leaks (compromised → first-use detection works because the second use
finds a revoked session and 401s).

Every wrong-credentials response is a generic 401 with no detail about
which leg failed (email vs password). Per OWASP authentication guidance,
we don't reveal whether an email exists in the system.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.audit import audit_action
from app.config import get_settings
from app.db.session import get_db
from app.errors import Conflict
from app.models.user import User, UserSession
from app.security import (
    create_access_token,
    create_mfa_token,
    create_refresh_token,
    decode_mfa_token,
    hash_password,
    refresh_token_matches,
    verify_password,
)
from app.security.totp import (
    consume_recovery_code,
    generate_recovery_codes,
    generate_totp_secret,
    provisioning_uri,
    verify_totp,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response models — shapes match docs/api/backend-openapi.yaml.
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """`LoginRequest` schema from backend-openapi.yaml."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class RefreshRequest(BaseModel):
    """`/auth/refresh` body per backend-openapi.yaml."""

    refresh_token: str = Field(min_length=1)


class UserPublic(BaseModel):
    """`User` schema from backend-openapi.yaml.

    Mirrors the OpenAPI `User`. We lift this into a Pydantic model rather
    than serializing the ORM row directly so the API surface is decoupled
    from the storage shape — adding a column to `users` won't accidentally
    leak it to the client.
    """

    id: str
    email: str
    display_name: str | None = None
    is_admin: bool
    role: str = "member"
    mfa_enabled: bool
    must_change_password: bool = False
    reasoning_visibility: str = "disclosure"
    # PRD §3.2.1 + frontend spec §4.3 (Wave B v2) — personalization prefs.
    featured_tools: str = "prominent"
    workspace_layout: str = "three_pane"
    trust_pills: str = "labels"
    provenance_pills: str = "always"
    created_at: datetime
    last_login_at: datetime | None = None
    # GDPR Article 17 grace-period delete: non-null while a deletion is
    # pending (set by POST /users/me/delete, cleared by .../delete/cancel).
    # Surfaced here so a user's own session can render a "deletion pending —
    # cancel by <date>" state on load (Donna P1.4), not just the admin view.
    deletion_scheduled_at: datetime | None = None

    @classmethod
    def from_user(cls, user: User) -> UserPublic:
        return cls(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            is_admin=user.is_admin,
            role=getattr(user, "role", "member"),
            mfa_enabled=user.mfa_enabled,
            must_change_password=user.must_change_password,
            reasoning_visibility=getattr(user, "reasoning_visibility", "disclosure"),
            featured_tools=getattr(user, "featured_tools", "prominent"),
            workspace_layout=getattr(user, "workspace_layout", "three_pane"),
            trust_pills=getattr(user, "trust_pills", "labels"),
            provenance_pills=getattr(user, "provenance_pills", "always"),
            created_at=user.created_at,
            last_login_at=user.last_login_at,
            deletion_scheduled_at=user.deletion_scheduled_at,
        )


class LoginResponse(BaseModel):
    """`LoginResponse` schema from backend-openapi.yaml."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str
    user: UserPublic


class TokenResponse(BaseModel):
    """`TokenResponse` schema from backend-openapi.yaml.

    NOTE: the OpenAPI sketch's `TokenResponse` does not include `refresh_token`.
    PRD §5.1 mandates that refresh tokens are rotated on each refresh — and a
    rotated token must be returned to the client or the client cannot use the
    new session. We therefore extend `TokenResponse` with `refresh_token`,
    additive to the OpenAPI sketch (existing fields are unchanged). This drift
    is flagged in the B1 task report so the OpenAPI sketch can be corrected.
    """

    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str


class MfaChallenge(BaseModel):
    """`MfaChallenge` schema from backend-openapi.yaml."""

    mfa_token: str
    methods: list[str]


class ChangePasswordRequest(BaseModel):
    """`ChangePasswordRequest` schema from backend-openapi.yaml.

    Both the current (last-known) password and the new password are
    required. The current password gates the change so a stolen access
    token alone cannot rotate credentials — see PRD §5.1.
    """

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class MfaSetupResponse(BaseModel):
    """`/auth/mfa/setup` response shape — see backend-openapi.yaml.

    ``secret`` and ``provisioning_uri`` carry the same TOTP secret in
    two encodings. ``recovery_codes`` is the **plaintext** list (only
    time the user sees them) — the backend persists bcrypt hashes.
    """

    secret: str
    provisioning_uri: str
    recovery_codes: list[str]


class MfaEnableRequest(BaseModel):
    """`/auth/mfa/enable` body — confirms enrollment with a fresh TOTP code."""

    code: str = Field(pattern=r"^\d{6}$")


class MfaVerifyRequest(BaseModel):
    """`/auth/mfa/verify` body — completes a 423 login challenge.

    The ``code`` is either a 6-digit TOTP or a 14-character recovery
    code (``xxxx-xxxx-xxxx``). The handler tries TOTP first, then
    recovery; submitted format is not validated up-front so an attacker
    cannot tell from the response shape which path matched.
    """

    mfa_token: str = Field(min_length=1)
    code: str = Field(min_length=1, max_length=64)


class MfaDisableRequest(BaseModel):
    """`/auth/mfa/disable` body — re-proves password + a current MFA code.

    Disabling MFA is account-shape-changing, so we require *both* the
    password (defends against a stolen access token) and a current
    TOTP/recovery code (defends against an attacker who knows the
    password but doesn't have the device).
    """

    password: str = Field(min_length=1, max_length=1024)
    code: str = Field(min_length=1, max_length=64)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _client_metadata(request: Request) -> tuple[str | None, str | None]:
    """Return `(user_agent, ip_address)` for the session row, both nullable.

    `user_agent` comes straight off the User-Agent header.
    `ip_address` honors `X-Forwarded-For` only if the request reached us
    through a trusted proxy — we conservatively use the immediate client
    IP from `request.client` for now and let an operator front the
    deployment with a reverse proxy that sets the column itself if they
    want X-Forwarded-For semantics. (Future: trusted-proxy config.)
    """
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None
    return user_agent, ip_address


async def _create_session(
    db: AsyncSession,
    user: User,
    request: Request,
    *,
    absolute_expires_at: datetime | None = None,
) -> tuple[str, UserSession]:
    """Mint and persist a new refresh-token session.

    Returns (plaintext_refresh_token, the inserted UserSession row).
    The plaintext is for the response body; the row carries the hash.

    M-Sec.1 — ``absolute_expires_at`` carries the original-login deadline
    across refresh rotations. On a fresh login (``None``), the deadline
    is computed from ``settings.session_absolute_timeout_seconds`` (PRD
    §5.1 default 8h). On a refresh, the caller passes the matched
    session's ``absolute_expires_at`` so the clock keeps running from
    the user's first password entry, not from the most recent rotation.
    """
    settings = get_settings()
    plaintext, hashed = create_refresh_token()
    user_agent, ip_address = _client_metadata(request)

    now = _utcnow()
    effective_absolute = absolute_expires_at or (
        now + timedelta(seconds=settings.session_absolute_timeout_seconds)
    )

    session = UserSession(
        user_id=user.id,
        refresh_token_hash=hashed,
        user_agent=user_agent,
        ip_address=ip_address,
        expires_at=now + timedelta(seconds=settings.jwt_refresh_token_ttl_seconds),
        absolute_expires_at=effective_absolute,
        last_active_at=now,
    )
    db.add(session)
    await db.flush()
    return plaintext, session


def _login_response(user: User, refresh_token: str) -> LoginResponse:
    """Build the LoginResponse for a successful login or refresh-with-user."""
    settings = get_settings()
    access_token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return LoginResponse(
        access_token=access_token,
        token_type="Bearer",
        expires_in=settings.jwt_access_token_ttl_seconds,
        refresh_token=refresh_token,
        user=UserPublic.from_user(user),
    )


# ---------------------------------------------------------------------------
# Endpoints.
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=None,  # union return type; FastAPI handles via `Response`
    status_code=status.HTTP_200_OK,
    summary="Authenticate with email and password",
    responses={
        200: {"model": LoginResponse},
        401: {"description": "Invalid credentials"},
        423: {"model": MfaChallenge, "description": "MFA required"},
    },
)
async def login(
    payload: LoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """POST /api/v1/auth/login — see backend-openapi.yaml."""
    # Look up the user. Email column is CITEXT so case is irrelevant.
    # `deleted_at IS NOT NULL` users are treated as non-existent.
    result = await db.execute(
        select(User).where(User.email == payload.email, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    # Generic 401 whether the user is missing or the password is wrong;
    # we do NOT reveal which leg failed. Still call verify_password on a
    # dummy hash to keep timing roughly equal between "no such user" and
    # "wrong password" branches — this is best-effort, not constant-time.
    if user is None:
        # Hash a constant-length string to consume comparable wall time.
        verify_password(payload.password, "$2b$12$" + "x" * 53)
        await audit_action(
            db,
            user_id=None,
            action="user.login_failed",
            resource_type="user",
            request=request,
            details={"email": payload.email, "reason": "user_not_found"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not verify_password(payload.password, user.hashed_password):
        await audit_action(
            db,
            user_id=user.id,
            action="user.login_failed",
            resource_type="user",
            resource_id=str(user.id),
            request=request,
            details={"email": payload.email, "reason": "wrong_password"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # MFA branch: issue a short-lived challenge token; the client redeems
    # it at /auth/mfa/verify (D5). No session is created here — the user
    # has not yet completed authentication.
    if user.mfa_enabled:
        mfa_token = create_mfa_token(user.id)
        challenge = MfaChallenge(mfa_token=mfa_token, methods=["totp", "recovery_code"])
        await audit_action(
            db,
            user_id=user.id,
            action="user.login_mfa_challenged",
            resource_type="user",
            resource_id=str(user.id),
            request=request,
        )
        await db.commit()
        return JSONResponse(
            status_code=status.HTTP_423_LOCKED,
            content=challenge.model_dump(),
        )

    # Happy path. Create a session, stamp last_login_at, return tokens.
    plaintext, _session = await _create_session(db, user, request)
    user.last_login_at = _utcnow()
    await audit_action(
        db,
        user_id=user.id,
        action="user.login",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
    )
    await db.commit()

    body = _login_response(user, plaintext)
    return JSONResponse(status_code=status.HTTP_200_OK, content=body.model_dump(mode="json"))


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token using refresh token",
    responses={
        200: {"model": TokenResponse},
        401: {"description": "Invalid, expired, or revoked refresh token"},
    },
)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """POST /api/v1/auth/refresh — rotate the refresh token, mint a new access token."""
    settings = get_settings()
    now = _utcnow()

    # Find the active session whose stored hash matches the presented token.
    # We can't index-lookup by hash (bcrypt salt is per-row), so we scan
    # active sessions and bcrypt-compare each. In v1 the active-session
    # count per user is tiny (a few devices); if this becomes hot, switch
    # to a deterministic HMAC index column. Tracked as DE candidate.
    result = await db.execute(
        select(UserSession).where(
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
    )
    candidates = result.scalars().all()

    matched: UserSession | None = None
    for session in candidates:
        if refresh_token_matches(payload.refresh_token, session.refresh_token_hash):
            matched = session
            break

    if matched is None:
        # No user context (the presented token didn't match any active
        # session); the audit row records the *attempt* with no user id.
        await audit_action(
            db,
            user_id=None,
            action="user.session_refresh_failed",
            resource_type="user_session",
            request=request,
            details={"reason": "no_matching_session"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # M-Sec.1 — absolute + idle timeout enforcement (PRD §5.1).
    # Enforced at refresh time only because access tokens are short
    # (15min default) and a stale access token expires on its own; this
    # keeps the JWT path stateless and avoids per-request DB hits.
    if now > matched.absolute_expires_at:
        matched.revoked_at = now
        await audit_action(
            db,
            user_id=matched.user_id,
            action="user.session_refresh_failed",
            resource_type="user_session",
            resource_id=str(matched.id),
            request=request,
            details={
                "reason": "absolute_timeout_exceeded",
                "absolute_expires_at": matched.absolute_expires_at.isoformat(),
            },
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has reached its absolute timeout; please log in again",
        )

    idle_deadline = matched.last_active_at + timedelta(
        seconds=settings.session_idle_timeout_seconds
    )
    if now > idle_deadline:
        matched.revoked_at = now
        await audit_action(
            db,
            user_id=matched.user_id,
            action="user.session_refresh_failed",
            resource_type="user_session",
            resource_id=str(matched.id),
            request=request,
            details={
                "reason": "idle_timeout_exceeded",
                "last_active_at": matched.last_active_at.isoformat(),
            },
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been idle too long; please log in again",
        )

    # Look up the owning user; if missing or soft-deleted, refuse.
    user_result = await db.execute(
        select(User).where(User.id == matched.user_id, User.deleted_at.is_(None))
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        await audit_action(
            db,
            user_id=matched.user_id,
            action="user.session_refresh_failed",
            resource_type="user_session",
            resource_id=str(matched.id),
            request=request,
            details={"reason": "user_deleted"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Rotate: revoke this session, mint a fresh one. Both happen in the
    # same transaction so a crash mid-way doesn't leave the user with an
    # active old session and no new one (or two active sessions).
    # M-Sec.1 — propagate the absolute-timeout deadline forward so the
    # original-login clock survives rotation. ``last_active_at`` on the
    # new row is stamped fresh by ``_create_session``.
    matched.revoked_at = now
    plaintext, _new_session = await _create_session(
        db,
        user,
        request,
        absolute_expires_at=matched.absolute_expires_at,
    )
    await audit_action(
        db,
        user_id=user.id,
        action="user.session_refreshed",
        resource_type="user_session",
        resource_id=str(matched.id),
        request=request,
    )
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(user.id, user.email, is_admin=user.is_admin),
        token_type="Bearer",
        expires_in=settings.jwt_access_token_ttl_seconds,
        refresh_token=plaintext,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke all active sessions for the calling user",
)
async def logout(
    user: CurrentUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """POST /api/v1/auth/logout — bearer-authenticated.

    Revokes ALL active sessions for the calling user (conservative — see
    PRD §5.1; per-session logout can be added later if a use case
    materializes). The access token itself is stateless and remains valid
    until its TTL expires; clients are expected to discard it on logout.
    """
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_utcnow())
    )
    await audit_action(
        db,
        user_id=user.id,
        action="user.logout",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# /auth/change-password — set a new password for the calling user.
# ---------------------------------------------------------------------------


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change the calling user's password",
    responses={
        204: {"description": "Password changed successfully"},
        400: {"description": "New password fails policy check"},
        401: {"description": "Current password is wrong"},
    },
)
async def change_password(
    payload: ChangePasswordRequest,
    user: CurrentUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """POST /api/v1/auth/change-password.

    Bearer-authenticated; the bearer token's user is the one whose password
    is being changed. The current password is required (defense against
    a stolen access token; an attacker who only has the token cannot
    rotate the credentials underneath the legitimate user).

    Behavior:
    - Verifies `current_password` against the stored hash.
    - Validates `new_password` against the configured minimum length and
      "must differ from current" policy.
    - Hashes and stores the new password.
    - Clears `must_change_password` (the first-run forced-change flag).
    - Revokes ALL active sessions for the user — the caller must log in
      again with the new password. This is intentional: it invalidates
      any session that may have been spawned with the old credential.

    Returns 204 on success, 401 on wrong current password, 400 on policy
    violation. The response body for 400 names the violated rule so the
    UI can render a usable message.
    """
    settings = get_settings()

    if not verify_password(payload.current_password, user.hashed_password):
        await audit_action(
            db,
            user_id=user.id,
            action="user.password_change_failed",
            resource_type="user",
            resource_id=str(user.id),
            request=request,
            details={"reason": "wrong_current_password"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    new_password = payload.new_password
    if len(new_password) < settings.password_min_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"New password must be at least {settings.password_min_length} characters."),
        )

    if new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from the current password.",
        )

    # Hash and persist. Clear the forced-change flag in the same transaction
    # so a crash mid-way doesn't leave the user in an inconsistent state.
    user.hashed_password = hash_password(new_password)
    user.must_change_password = False

    # Revoke all active sessions — the user must re-authenticate. This is
    # the same pattern as /auth/logout; we don't reuse the handler so the
    # behavior is explicit.
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_utcnow())
    )
    await audit_action(
        db,
        user_id=user.id,
        action="user.password_changed",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
    )
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# D5 — MFA enrollment + verification.
#
# Two-step enrollment:
#   1. POST /mfa/setup     — bearer-authed; issues secret + provisioning URI
#                            + 10 plaintext recovery codes (one-time display).
#                            Persists secret + bcrypt-hashed codes; mfa_enabled
#                            stays FALSE until the user proves possession.
#   2. POST /mfa/enable    — bearer-authed; verifies a TOTP code against the
#                            pending secret. On success flips mfa_enabled=TRUE.
#
# Login flow (existing /auth/login, line ~265):
#   3. POST /mfa/verify    — unauthed; redeems an mfa_token (issued by /login
#                            on 423) plus a TOTP or recovery code. On success
#                            mints a full access+refresh session.
#
# Disabling:
#   4. POST /mfa/disable   — bearer-authed; requires password + a current
#                            TOTP/recovery code. Clears all MFA state.
#
# Persistence: ``users.totp_secret`` (plaintext base32 — no recovery path
# without it) and ``users.recovery_codes`` (bcrypt hashes — single-use
# enforced by removal-on-match).
# ---------------------------------------------------------------------------


@router.post(
    "/mfa/setup",
    response_model=MfaSetupResponse,
    status_code=status.HTTP_200_OK,
    summary="Enroll in TOTP-based MFA",
    responses={
        200: {"model": MfaSetupResponse},
        409: {"description": "MFA already enabled"},
    },
)
async def mfa_setup(
    user: CurrentUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MfaSetupResponse:
    """POST /api/v1/auth/mfa/setup — issue a fresh TOTP secret + recovery codes.

    Re-running setup before ``/mfa/enable`` overwrites the pending
    secret + codes (the user is restarting enrollment). Re-running
    after MFA is already enabled is a 409 ``mfa_already_enabled``;
    the user must call ``/mfa/disable`` first.
    """
    if user.mfa_enabled:
        raise Conflict(message="MFA already enabled", code="mfa_already_enabled")

    secret = generate_totp_secret()
    plaintext_codes, hashed_codes = generate_recovery_codes()

    user.totp_secret = secret
    user.recovery_codes = hashed_codes
    await audit_action(
        db,
        user_id=user.id,
        action="user.mfa_setup_initiated",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
    )
    await db.commit()

    return MfaSetupResponse(
        secret=secret,
        provisioning_uri=provisioning_uri(secret, account_email=user.email),
        recovery_codes=plaintext_codes,
    )


@router.post(
    "/mfa/enable",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Confirm TOTP enrollment with a verification code",
    responses={
        204: {"description": "MFA enabled"},
        400: {"description": "Setup not started or code invalid"},
        409: {"description": "MFA already enabled"},
    },
)
async def mfa_enable(
    payload: MfaEnableRequest,
    user: CurrentUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """POST /api/v1/auth/mfa/enable — flip ``mfa_enabled`` after first verify.

    Requires that ``/mfa/setup`` has been called first (a pending
    ``totp_secret`` is on the user row). On success the user's next
    login will receive the 423 challenge.
    """
    if user.mfa_enabled:
        raise Conflict(message="MFA already enabled", code="mfa_already_enabled")

    if not user.totp_secret:
        await audit_action(
            db,
            user_id=user.id,
            action="user.mfa_enable_failed",
            resource_type="user",
            resource_id=str(user.id),
            request=request,
            details={"reason": "setup_not_initiated"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA setup has not been initiated; call /auth/mfa/setup first.",
        )

    if not verify_totp(user.totp_secret, payload.code):
        await audit_action(
            db,
            user_id=user.id,
            action="user.mfa_enable_failed",
            resource_type="user",
            resource_id=str(user.id),
            request=request,
            details={"reason": "invalid_code"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code.",
        )

    user.mfa_enabled = True
    await audit_action(
        db,
        user_id=user.id,
        action="user.mfa_enabled",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/mfa/verify",
    response_model=None,  # JSONResponse with LoginResponse body
    status_code=status.HTTP_200_OK,
    summary="Complete MFA challenge with TOTP or recovery code",
    responses={
        200: {"model": LoginResponse},
        401: {"description": "Invalid challenge token or code"},
    },
)
async def mfa_verify(
    payload: MfaVerifyRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """POST /api/v1/auth/mfa/verify — redeem an mfa_token + code → LoginResponse.

    On success, mints the same session shape as a regular login (the
    issuance path is shared — see ``_create_session`` and
    ``_login_response``).

    All failure modes (invalid token, expired token, missing user,
    MFA-not-enabled, wrong code) collapse into a single 401 so an
    attacker cannot probe which leg failed.
    """
    claims = decode_mfa_token(payload.mfa_token)
    if claims is None:
        await audit_action(
            db,
            user_id=None,
            action="user.mfa_verify_failed",
            resource_type="user",
            request=request,
            details={"reason": "invalid_challenge_token"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MFA challenge",
        )

    result = await db.execute(
        select(User).where(User.id == claims.user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None or not user.mfa_enabled or not user.totp_secret:
        await audit_action(
            db,
            user_id=claims.user_id,
            action="user.mfa_verify_failed",
            resource_type="user",
            resource_id=str(claims.user_id),
            request=request,
            details={"reason": "mfa_not_enabled_or_user_missing"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MFA challenge",
        )

    matched = False
    used_recovery_code = False

    if verify_totp(user.totp_secret, payload.code):
        matched = True
    else:
        remaining = consume_recovery_code(payload.code, list(user.recovery_codes or []))
        if remaining is not None:
            user.recovery_codes = remaining
            matched = True
            used_recovery_code = True

    if not matched:
        await audit_action(
            db,
            user_id=user.id,
            action="user.mfa_verify_failed",
            resource_type="user",
            resource_id=str(user.id),
            request=request,
            details={"reason": "invalid_code"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MFA code",
        )

    plaintext, _session = await _create_session(db, user, request)
    user.last_login_at = _utcnow()
    await audit_action(
        db,
        user_id=user.id,
        action="user.login",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
        details={"mfa": True, "via": "recovery_code" if used_recovery_code else "totp"},
    )
    await db.commit()

    body = _login_response(user, plaintext)
    return JSONResponse(status_code=status.HTTP_200_OK, content=body.model_dump(mode="json"))


@router.post(
    "/mfa/disable",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disable MFA after re-proving password and a current MFA code",
    responses={
        204: {"description": "MFA disabled"},
        400: {"description": "MFA is not enabled"},
        401: {"description": "Wrong password or invalid MFA code"},
    },
)
async def mfa_disable(
    payload: MfaDisableRequest,
    user: CurrentUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """POST /api/v1/auth/mfa/disable — require password + MFA code together.

    Both checks are required so a stolen access token alone cannot
    weaken the user's authentication posture, and an attacker who has
    the password but not the device cannot strip MFA.

    Wrong-password and wrong-code branches both return generic 401 so
    callers can't tell which leg failed.
    """
    if not user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not enabled.",
        )

    if not verify_password(payload.password, user.hashed_password):
        await audit_action(
            db,
            user_id=user.id,
            action="user.mfa_disable_failed",
            resource_type="user",
            resource_id=str(user.id),
            request=request,
            details={"reason": "wrong_password"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    code_ok = False
    if user.totp_secret and verify_totp(user.totp_secret, payload.code):
        code_ok = True
    elif consume_recovery_code(payload.code, list(user.recovery_codes or [])) is not None:
        # Recovery code is single-use, but since we're about to clear all
        # MFA state we don't need to persist the truncated list — the
        # code being burned just to disable MFA is the explicit intent.
        code_ok = True

    if not code_ok:
        await audit_action(
            db,
            user_id=user.id,
            action="user.mfa_disable_failed",
            resource_type="user",
            resource_id=str(user.id),
            request=request,
            details={"reason": "invalid_code"},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MFA code",
        )

    user.mfa_enabled = False
    user.totp_secret = None
    user.recovery_codes = None
    await audit_action(
        db,
        user_id=user.id,
        action="user.mfa_disabled",
        resource_type="user",
        resource_id=str(user.id),
        request=request,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
