"""Integration tests for the D5 MFA endpoints.

Covers the verification step from M1-IMPLEMENTATION-ORDER.md Task D5:

    Full enroll → login → unenroll cycle. Recovery code single-use
    enforcement verified.

Plus the surrounding 401/409/400 paths.

Layout mirrors :mod:`tests.test_auth` — `client` and `seed_user`
fixtures bind a fresh per-test session. New helpers below mint the
per-test access token and exercise the full setup → enable → login
→ verify round-trip.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import jwt as pyjwt
import pyotp
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.user import User, UserSession
from app.security import create_access_token, hash_password


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def seed_user(db_session: AsyncSession) -> User:
    """A baseline user with MFA disabled and the canonical test password."""
    user = User(
        email=f"mfa-{uuid.uuid4().hex[:8]}@example.com",
        display_name="MFA Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> dict[str, str]:
    """Mint a valid access token for `user` and return the auth header."""
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


async def _setup_and_enable(
    client: AsyncClient, db_session: AsyncSession, user: User
) -> tuple[str, list[str]]:
    """Run setup + enable for `user`; return `(secret, recovery_codes)`.

    Wraps the two-step enrollment so individual tests can focus on the
    behavior under test rather than re-running the same plumbing.
    """
    setup = await client.post("/api/v1/auth/mfa/setup", headers=_bearer(user))
    assert setup.status_code == 200, setup.text
    body = setup.json()
    secret: str = body["secret"]
    recovery_codes: list[str] = body["recovery_codes"]

    code = pyotp.TOTP(secret).now()
    enable = await client.post(
        "/api/v1/auth/mfa/enable", headers=_bearer(user), json={"code": code}
    )
    assert enable.status_code == 204, enable.text

    await db_session.refresh(user)
    return secret, recovery_codes


# ---------------------------------------------------------------------------
# /auth/mfa/setup
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_mfa_setup_returns_shape_and_persists_pending_state(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """`/mfa/setup` returns secret + uri + 10 codes; persists secret + hashes."""
    resp = await client.post("/api/v1/auth/mfa/setup", headers=_bearer(seed_user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["secret"]
    assert body["provisioning_uri"].startswith("otpauth://totp/")
    assert "LQ.AI" in body["provisioning_uri"]
    assert len(body["recovery_codes"]) == 10
    assert all("-" in c for c in body["recovery_codes"])

    await db_session.refresh(seed_user)
    assert seed_user.totp_secret == body["secret"]
    assert seed_user.recovery_codes is not None
    assert len(seed_user.recovery_codes) == 10
    # Stored values are bcrypt hashes, not the plaintext codes.
    for stored, plaintext in zip(seed_user.recovery_codes, body["recovery_codes"], strict=True):
        assert stored != plaintext
        assert stored.startswith("$2")
    # mfa_enabled is NOT flipped until /mfa/enable.
    assert seed_user.mfa_enabled is False


@pytest.mark.integration
async def test_mfa_setup_rerun_before_enable_overwrites_pending(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """Re-running setup before enable replaces the pending secret + codes."""
    first = (await client.post("/api/v1/auth/mfa/setup", headers=_bearer(seed_user))).json()
    second = (await client.post("/api/v1/auth/mfa/setup", headers=_bearer(seed_user))).json()

    assert first["secret"] != second["secret"]
    assert first["recovery_codes"] != second["recovery_codes"]

    await db_session.refresh(seed_user)
    assert seed_user.totp_secret == second["secret"]


@pytest.mark.integration
async def test_mfa_setup_after_enabled_returns_409(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """After MFA is on, /mfa/setup is a 409 with the canonical error code."""
    await _setup_and_enable(client, db_session, seed_user)

    resp = await client.post("/api/v1/auth/mfa/setup", headers=_bearer(seed_user))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "mfa_already_enabled"


@pytest.mark.integration
async def test_mfa_setup_without_token_returns_401(client: AsyncClient) -> None:
    """Setup is bearer-authed; missing token is a 401."""
    resp = await client.post("/api/v1/auth/mfa/setup")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/mfa/enable
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_mfa_enable_with_valid_code_flips_flag(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    setup = (await client.post("/api/v1/auth/mfa/setup", headers=_bearer(seed_user))).json()
    code = pyotp.TOTP(setup["secret"]).now()

    resp = await client.post(
        "/api/v1/auth/mfa/enable", headers=_bearer(seed_user), json={"code": code}
    )
    assert resp.status_code == 204

    await db_session.refresh(seed_user)
    assert seed_user.mfa_enabled is True


@pytest.mark.integration
async def test_mfa_enable_without_setup_returns_400(client: AsyncClient, seed_user: User) -> None:
    """Calling enable before setup is a 400 — there is no pending secret."""
    resp = await client.post(
        "/api/v1/auth/mfa/enable", headers=_bearer(seed_user), json={"code": "123456"}
    )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_mfa_enable_with_wrong_code_returns_400(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    await client.post("/api/v1/auth/mfa/setup", headers=_bearer(seed_user))
    resp = await client.post(
        "/api/v1/auth/mfa/enable", headers=_bearer(seed_user), json={"code": "000000"}
    )
    assert resp.status_code == 400

    await db_session.refresh(seed_user)
    assert seed_user.mfa_enabled is False


@pytest.mark.integration
async def test_mfa_enable_after_already_enabled_returns_409(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    secret, _ = await _setup_and_enable(client, db_session, seed_user)

    resp = await client.post(
        "/api/v1/auth/mfa/enable",
        headers=_bearer(seed_user),
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "mfa_already_enabled"


# ---------------------------------------------------------------------------
# /auth/mfa/verify (login challenge redemption)
# ---------------------------------------------------------------------------


async def _begin_login_challenge(client: AsyncClient, user: User) -> str:
    """Hit /auth/login as `user`; return the mfa_token from the 423 body."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "correct-horse-battery-staple"},
    )
    assert resp.status_code == 423, resp.text
    return str(resp.json()["mfa_token"])


@pytest.mark.integration
async def test_mfa_verify_with_totp_returns_login_response(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    secret, _ = await _setup_and_enable(client, db_session, seed_user)

    mfa_token = await _begin_login_challenge(client, seed_user)
    resp = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["user"]["email"] == seed_user.email
    assert body["user"]["mfa_enabled"] is True

    sessions = (
        (await db_session.execute(select(UserSession).where(UserSession.user_id == seed_user.id)))
        .scalars()
        .all()
    )
    assert len(sessions) == 1
    assert sessions[0].revoked_at is None


@pytest.mark.integration
async def test_mfa_verify_with_recovery_code_consumes_it(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """Recovery code works once; the same code is rejected on the second try."""
    _secret, recovery_codes = await _setup_and_enable(client, db_session, seed_user)
    one_code = recovery_codes[0]

    mfa_token = await _begin_login_challenge(client, seed_user)
    first = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": one_code},
    )
    assert first.status_code == 200, first.text

    await db_session.refresh(seed_user)
    assert seed_user.recovery_codes is not None
    assert len(seed_user.recovery_codes) == 9

    # Second attempt with the same recovery code must fail — single-use.
    mfa_token_2 = await _begin_login_challenge(client, seed_user)
    second = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token_2, "code": one_code},
    )
    assert second.status_code == 401


@pytest.mark.integration
async def test_mfa_verify_with_wrong_code_returns_401(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    await _setup_and_enable(client, db_session, seed_user)
    mfa_token = await _begin_login_challenge(client, seed_user)

    resp = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": "000000"},
    )
    assert resp.status_code == 401


@pytest.mark.integration
async def test_mfa_verify_with_garbage_token_returns_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": "not-a-real-jwt", "code": "123456"},
    )
    assert resp.status_code == 401


@pytest.mark.integration
async def test_mfa_verify_for_user_without_mfa_returns_401(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """An attacker forging an mfa_token for a non-MFA user gets 401, not a session."""
    from app.security import create_mfa_token

    forged = create_mfa_token(seed_user.id)
    resp = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": forged, "code": "123456"},
    )
    assert resp.status_code == 401


@pytest.mark.integration
async def test_mfa_verify_with_expired_token_returns_401(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """An mfa_token past its TTL is rejected without a session being minted."""
    await _setup_and_enable(client, db_session, seed_user)

    from app.config import get_settings
    from app.security import create_mfa_token

    settings = get_settings()
    token = create_mfa_token(seed_user.id)
    decoded = pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    # Force-expire by re-issuing with iat/exp in the past — the jwt
    # decoder is strict about exp, so the verify path returns 401 for
    # the same reason a real-clock-expired token would.
    expired = pyjwt.encode(
        {**decoded, "iat": decoded["iat"] - 10_000, "exp": decoded["exp"] - 10_000},
        settings.jwt_secret,
        algorithm="HS256",
    )
    resp = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": expired, "code": "000000"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/mfa/disable
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_mfa_disable_with_password_and_code_clears_state(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    secret, _ = await _setup_and_enable(client, db_session, seed_user)

    resp = await client.post(
        "/api/v1/auth/mfa/disable",
        headers=_bearer(seed_user),
        json={
            "password": "correct-horse-battery-staple",
            "code": pyotp.TOTP(secret).now(),
        },
    )
    assert resp.status_code == 204

    await db_session.refresh(seed_user)
    assert seed_user.mfa_enabled is False
    assert seed_user.totp_secret is None
    assert seed_user.recovery_codes is None


@pytest.mark.integration
async def test_mfa_disable_with_wrong_password_returns_401(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    secret, _ = await _setup_and_enable(client, db_session, seed_user)

    resp = await client.post(
        "/api/v1/auth/mfa/disable",
        headers=_bearer(seed_user),
        json={
            "password": "wrong-password",
            "code": pyotp.TOTP(secret).now(),
        },
    )
    assert resp.status_code == 401

    await db_session.refresh(seed_user)
    assert seed_user.mfa_enabled is True


@pytest.mark.integration
async def test_mfa_disable_with_wrong_code_returns_401(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    await _setup_and_enable(client, db_session, seed_user)

    resp = await client.post(
        "/api/v1/auth/mfa/disable",
        headers=_bearer(seed_user),
        json={
            "password": "correct-horse-battery-staple",
            "code": "000000",
        },
    )
    assert resp.status_code == 401

    await db_session.refresh(seed_user)
    assert seed_user.mfa_enabled is True


@pytest.mark.integration
async def test_mfa_disable_with_recovery_code_works(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """Disable accepts a recovery code as the second factor."""
    _secret, recovery_codes = await _setup_and_enable(client, db_session, seed_user)

    resp = await client.post(
        "/api/v1/auth/mfa/disable",
        headers=_bearer(seed_user),
        json={
            "password": "correct-horse-battery-staple",
            "code": recovery_codes[0],
        },
    )
    assert resp.status_code == 204

    await db_session.refresh(seed_user)
    assert seed_user.mfa_enabled is False


@pytest.mark.integration
async def test_mfa_disable_when_not_enabled_returns_400(
    client: AsyncClient, seed_user: User
) -> None:
    resp = await client.post(
        "/api/v1/auth/mfa/disable",
        headers=_bearer(seed_user),
        json={"password": "correct-horse-battery-staple", "code": "000000"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Full round trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_full_enroll_login_unenroll_cycle(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """The PRD §5.3 cycle: enroll, log in with TOTP, unenroll."""
    # 1. Enroll.
    secret, recovery_codes = await _setup_and_enable(client, db_session, seed_user)
    assert seed_user.mfa_enabled is True

    # 2. Log out / fresh login → 423.
    mfa_token = await _begin_login_challenge(client, seed_user)
    verify = await client.post(
        "/api/v1/auth/mfa/verify",
        json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()},
    )
    assert verify.status_code == 200
    assert verify.json()["access_token"]

    # 3. Unenroll using the password + a recovery code.
    disable = await client.post(
        "/api/v1/auth/mfa/disable",
        headers=_bearer(seed_user),
        json={
            "password": "correct-horse-battery-staple",
            "code": recovery_codes[0],
        },
    )
    assert disable.status_code == 204

    # 4. Subsequent login should bypass the MFA challenge.
    plain = await client.post(
        "/api/v1/auth/login",
        json={"email": seed_user.email, "password": "correct-horse-battery-staple"},
    )
    assert plain.status_code == 200
    assert plain.json()["access_token"]
