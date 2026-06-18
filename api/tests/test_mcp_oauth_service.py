"""Service tests for the PR4c MCP OAuth flow (``app.mcp.oauth``).

Security-critical surface: build the authorize URL (PKCE-S256), exchange the
code, store/refresh Fernet-encrypted per-user tokens, supply a valid access
token.  All third-party HTTP goes through the gateway passthrough — these
tests respx-mock the gateway endpoints (``/admin/v1/config``,
``/v1/oauth/{provider}/discover``, ``/v1/oauth/{provider}/token``) exactly the
way the gateway client speaks to them, mirroring ``test_mcp_service.py``.

The encryptor reads ``LQ_AI_MCP_MASTER_KEY`` from the environment at
point-of-use (``MCPTokenEncryptor.from_environ``); every test sets it via the
``mcp_master_key`` fixture (monkeypatch), mirroring ``test_mcp_encryption.py``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp import oauth
from app.models.mcp_oauth import MCPOAuthState, MCPOAuthToken
from app.models.user import User
from app.security.encryption import (
    MCP_MASTER_KEY_ENV,
    MCPTokenEncryptor,
    generate_master_key,
)
from app.security.passwords import hash_password

GW = "http://localhost:8001"  # settings.lq_ai_gateway_url default

PROVIDER = "court-listener"
SERVER_URL = "https://mcp.courtlistener.test/"
CLIENT_ID = "lq-ai-client-id"
AUTH_ENDPOINT = "https://as.courtlistener.test/authorize"
TOKEN_ENDPOINT = "https://as.courtlistener.test/token"
ISSUER = "https://as.courtlistener.test"
RESOURCE = "https://mcp.courtlistener.test/"
REDIRECT_URI = "https://lq-ai.local/api/v1/oauth/court-listener/callback"

ACCESS_TOKEN = "access-tok-PLAINTEXT-SECRET-aaaa"
REFRESH_TOKEN = "refresh-tok-PLAINTEXT-SECRET-bbbb"
NEW_ACCESS_TOKEN = "access-tok-ROTATED-cccc"
NEW_REFRESH_TOKEN = "refresh-tok-ROTATED-dddd"
AUTH_CODE = "auth-code-PLAINTEXT-SECRET-eeee"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_master_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Bind a fresh MCP master key for the duration of a test."""
    key = generate_master_key()
    monkeypatch.setenv(MCP_MASTER_KEY_ENV, key)
    return key


def _config_payload(*, with_oauth: bool = True) -> dict:
    """Sanitised gateway ``/admin/v1/config`` payload with one oauth MCP."""
    providers = []
    if with_oauth:
        providers.append(
            {
                "name": PROVIDER,
                "type": "mcp",
                "auth": "oauth",
                "base_url": SERVER_URL,
                "oauth_client_id": CLIENT_ID,
            }
        )
    return {"tool_providers": providers}


def _discover_payload(*, iss_supported: bool = True, resource: str | None = RESOURCE) -> dict:
    meta = {
        "authorization_endpoint": AUTH_ENDPOINT,
        "token_endpoint": TOKEN_ENDPOINT,
        "issuer": ISSUER,
        "scopes_supported": ["read", "search"],
        "authorization_response_iss_parameter_supported": iss_supported,
    }
    if resource is not None:
        meta["resource"] = resource
    return meta


def _mock_config(mock: respx.MockRouter, *, with_oauth: bool = True) -> None:
    mock.get("/admin/v1/config").mock(
        return_value=httpx.Response(200, json=_config_payload(with_oauth=with_oauth))
    )


def _mock_discover(
    mock: respx.MockRouter, *, iss_supported: bool = True, resource: str | None = RESOURCE
) -> None:
    mock.post(f"/v1/oauth/{PROVIDER}/discover").mock(
        return_value=httpx.Response(
            200, json=_discover_payload(iss_supported=iss_supported, resource=resource)
        )
    )


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"mcp-oauth-svc-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("test-pass"),
        is_admin=False,
        mfa_enabled=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _seed_state(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    state: str = "state-xyz",
    code_verifier: str = "verifier-xyz",
    as_iss_supported: bool = True,
    resource: str | None = RESOURCE,
    expires_in_minutes: int = 10,
) -> MCPOAuthState:
    row = MCPOAuthState(
        state=state,
        user_id=user_id,
        provider_name=PROVIDER,
        code_verifier=code_verifier,
        issuer=ISSUER,
        resource=resource,
        token_endpoint=TOKEN_ENDPOINT,
        redirect_uri=REDIRECT_URI,
        as_iss_supported=as_iss_supported,
        expires_at=datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
    )
    db.add(row)
    await db.flush()
    return row


def _token_response(
    *,
    access: str = ACCESS_TOKEN,
    refresh: str | None = REFRESH_TOKEN,
    expires_in: int | None = 3600,
    scope: str | None = "read search",
) -> dict:
    body: dict = {"access_token": access, "token_type": "Bearer"}
    if refresh is not None:
        body["refresh_token"] = refresh
    if expires_in is not None:
        body["expires_in"] = expires_in
    if scope is not None:
        body["scope"] = scope
    return body


# ---------------------------------------------------------------------------
# build_authorize_url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_authorize_url_happy_path(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    with respx.mock(base_url=GW) as mock:
        _mock_config(mock)
        _mock_discover(mock)
        url = await oauth.build_authorize_url(
            db_session, user_id=user.id, server=PROVIDER, redirect_uri=REDIRECT_URI
        )

    split = urlsplit(url)
    assert f"{split.scheme}://{split.netloc}{split.path}" == AUTH_ENDPOINT
    q = parse_qs(split.query)
    assert q["response_type"] == ["code"]
    assert q["client_id"] == [CLIENT_ID]
    assert q["redirect_uri"] == [REDIRECT_URI]
    assert q["code_challenge_method"] == ["S256"]
    assert q["code_challenge"][0]  # present + non-empty
    assert q["state"][0]
    assert q["resource"] == [RESOURCE]
    assert q["scope"] == ["read search"]

    # A matching state row is persisted with verifier/issuer/token_endpoint/iss.
    row = (
        await db_session.execute(select(MCPOAuthState).where(MCPOAuthState.state == q["state"][0]))
    ).scalar_one()
    assert row.code_verifier
    assert row.issuer == ISSUER
    assert row.token_endpoint == TOKEN_ENDPOINT
    assert row.resource == RESOURCE
    assert row.as_iss_supported is True
    assert row.expires_at > datetime.now(UTC)
    # The code_verifier is NOT the code_challenge (challenge is the hash).
    assert row.code_verifier != q["code_challenge"][0]


@pytest.mark.asyncio
async def test_build_authorize_url_omits_scope_when_empty(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    with respx.mock(base_url=GW) as mock:
        _mock_config(mock)
        mock.post(f"/v1/oauth/{PROVIDER}/discover").mock(
            return_value=httpx.Response(
                200,
                json={
                    "authorization_endpoint": AUTH_ENDPOINT,
                    "token_endpoint": TOKEN_ENDPOINT,
                    "issuer": ISSUER,
                    "resource": RESOURCE,
                    "scopes_supported": [],
                    "authorization_response_iss_parameter_supported": True,
                },
            )
        )
        url = await oauth.build_authorize_url(
            db_session, user_id=user.id, server=PROVIDER, redirect_uri=REDIRECT_URI
        )
    q = parse_qs(urlsplit(url).query)
    assert "scope" not in q


@pytest.mark.asyncio
async def test_build_authorize_url_not_configured(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    with respx.mock(base_url=GW) as mock:
        _mock_config(mock, with_oauth=False)
        with pytest.raises(oauth.MCPOAuthNotConfigured):
            await oauth.build_authorize_url(
                db_session, user_id=user.id, server=PROVIDER, redirect_uri=REDIRECT_URI
            )


# ---------------------------------------------------------------------------
# exchange_code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_code_happy_path_encrypts_and_consumes_state(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    await _seed_state(db_session, user_id=user.id, state="st-happy")
    with respx.mock(base_url=GW) as mock:
        _mock_config(mock)
        mock.post(f"/v1/oauth/{PROVIDER}/token").mock(
            return_value=httpx.Response(200, json=_token_response())
        )
        token = await oauth.exchange_code(db_session, state="st-happy", code=AUTH_CODE, iss=ISSUER)

    # Token row: ciphertext columns are NOT the plaintext; decrypt round-trips.
    assert isinstance(token.access_token, bytes)
    assert token.access_token != ACCESS_TOKEN.encode()
    assert token.refresh_token is not None
    assert token.refresh_token != REFRESH_TOKEN.encode()
    enc = MCPTokenEncryptor.from_environ()
    assert enc.decrypt(token.access_token) == ACCESS_TOKEN
    assert enc.decrypt(token.refresh_token) == REFRESH_TOKEN
    assert token.scopes == ["read", "search"]
    assert token.issuer == ISSUER
    assert token.expires_at is not None and token.expires_at > datetime.now(UTC)

    # State row consumed (single-use).
    assert (
        await db_session.execute(select(MCPOAuthState).where(MCPOAuthState.state == "st-happy"))
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_exchange_code_unknown_state(db_session: AsyncSession, mcp_master_key: str) -> None:
    with pytest.raises(oauth.MCPOAuthStateError):
        await oauth.exchange_code(db_session, state="nope", code=AUTH_CODE, iss=ISSUER)


@pytest.mark.asyncio
async def test_exchange_code_expired_state_deletes_row(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    await _seed_state(db_session, user_id=user.id, state="st-expired", expires_in_minutes=-1)
    with pytest.raises(oauth.MCPOAuthStateError):
        await oauth.exchange_code(db_session, state="st-expired", code=AUTH_CODE, iss=ISSUER)
    assert (
        await db_session.execute(select(MCPOAuthState).where(MCPOAuthState.state == "st-expired"))
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_exchange_code_iss_mismatch(db_session: AsyncSession, mcp_master_key: str) -> None:
    user = await _make_user(db_session)
    await _seed_state(db_session, user_id=user.id, state="st-iss-mm")
    with pytest.raises(oauth.MCPOAuthStateError):
        await oauth.exchange_code(
            db_session, state="st-iss-mm", code=AUTH_CODE, iss="https://evil.test"
        )


@pytest.mark.asyncio
async def test_exchange_code_missing_iss_when_supported(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    await _seed_state(db_session, user_id=user.id, state="st-iss-missing", as_iss_supported=True)
    with pytest.raises(oauth.MCPOAuthStateError):
        await oauth.exchange_code(db_session, state="st-iss-missing", code=AUTH_CODE, iss=None)


@pytest.mark.asyncio
async def test_exchange_code_missing_iss_when_not_supported_ok(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    """When the AS does not support iss, a missing iss is fine."""
    user = await _make_user(db_session)
    await _seed_state(db_session, user_id=user.id, state="st-noiss", as_iss_supported=False)
    with respx.mock(base_url=GW) as mock:
        _mock_config(mock)
        mock.post(f"/v1/oauth/{PROVIDER}/token").mock(
            return_value=httpx.Response(200, json=_token_response())
        )
        token = await oauth.exchange_code(db_session, state="st-noiss", code=AUTH_CODE, iss=None)
    assert token is not None


@pytest.mark.asyncio
async def test_exchange_code_as_error_raises_and_consumes_state(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    await _seed_state(db_session, user_id=user.id, state="st-bad-grant")
    with respx.mock(base_url=GW) as mock:
        _mock_config(mock)
        mock.post(f"/v1/oauth/{PROVIDER}/token").mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )
        with pytest.raises(oauth.MCPOAuthExchangeError) as excinfo:
            await oauth.exchange_code(db_session, state="st-bad-grant", code=AUTH_CODE, iss=ISSUER)
    # The AS error string is carried; no token/code/verifier value leaks.
    msg = str(excinfo.value)
    assert "invalid_grant" in msg
    for secret in (AUTH_CODE, "verifier-xyz", ACCESS_TOKEN, REFRESH_TOKEN):
        assert secret not in msg
    # State consumed on the error path too.
    assert (
        await db_session.execute(select(MCPOAuthState).where(MCPOAuthState.state == "st-bad-grant"))
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_exchange_code_missing_access_token_is_error(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    await _seed_state(db_session, user_id=user.id, state="st-noat")
    with respx.mock(base_url=GW) as mock:
        _mock_config(mock)
        mock.post(f"/v1/oauth/{PROVIDER}/token").mock(
            return_value=httpx.Response(200, json={"token_type": "Bearer"})
        )
        with pytest.raises(oauth.MCPOAuthExchangeError):
            await oauth.exchange_code(db_session, state="st-noat", code=AUTH_CODE, iss=ISSUER)


# ---------------------------------------------------------------------------
# get_valid_token
# ---------------------------------------------------------------------------


async def _seed_token(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    access: str = ACCESS_TOKEN,
    refresh: str | None = REFRESH_TOKEN,
    expires_at: datetime | None,
) -> MCPOAuthToken:
    enc = MCPTokenEncryptor.from_environ()
    row = MCPOAuthToken(
        user_id=user_id,
        provider_name=PROVIDER,
        access_token=enc.encrypt(access),
        refresh_token=enc.encrypt(refresh) if refresh is not None else None,
        expires_at=expires_at,
        scopes=["read"],
        issuer=ISSUER,
        updated_at=datetime.now(UTC),
    )
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
async def test_get_valid_token_unexpired_returns_plaintext(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    await _seed_token(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    tok = await oauth.get_valid_token(db_session, user_id=user.id, server=PROVIDER)
    assert tok == ACCESS_TOKEN


@pytest.mark.asyncio
async def test_get_valid_token_null_expiry_returns_plaintext(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    await _seed_token(db_session, user_id=user.id, expires_at=None)
    tok = await oauth.get_valid_token(db_session, user_id=user.id, server=PROVIDER)
    assert tok == ACCESS_TOKEN


@pytest.mark.asyncio
async def test_get_valid_token_no_row_returns_none(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    assert await oauth.get_valid_token(db_session, user_id=user.id, server=PROVIDER) is None


@pytest.mark.asyncio
async def test_get_valid_token_expired_refresh_succeeds(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    await _seed_token(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    with respx.mock(base_url=GW) as mock:
        _mock_config(mock)
        _mock_discover(mock)
        mock.post(f"/v1/oauth/{PROVIDER}/token").mock(
            return_value=httpx.Response(
                200,
                json=_token_response(
                    access=NEW_ACCESS_TOKEN, refresh=NEW_REFRESH_TOKEN, expires_in=3600
                ),
            )
        )
        tok = await oauth.get_valid_token(db_session, user_id=user.id, server=PROVIDER)
    assert tok == NEW_ACCESS_TOKEN
    # Persisted row now holds the rotated (encrypted) tokens.
    row = (
        await db_session.execute(
            select(MCPOAuthToken).where(
                MCPOAuthToken.user_id == user.id,
                MCPOAuthToken.provider_name == PROVIDER,
            )
        )
    ).scalar_one()
    enc = MCPTokenEncryptor.from_environ()
    assert row.access_token != NEW_ACCESS_TOKEN.encode()
    assert enc.decrypt(row.access_token) == NEW_ACCESS_TOKEN
    assert row.refresh_token is not None
    assert enc.decrypt(row.refresh_token) == NEW_REFRESH_TOKEN


@pytest.mark.asyncio
async def test_get_valid_token_refresh_keeps_old_refresh_when_absent(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    await _seed_token(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    with respx.mock(base_url=GW) as mock:
        _mock_config(mock)
        _mock_discover(mock)
        mock.post(f"/v1/oauth/{PROVIDER}/token").mock(
            return_value=httpx.Response(
                200, json=_token_response(access=NEW_ACCESS_TOKEN, refresh=None)
            )
        )
        tok = await oauth.get_valid_token(db_session, user_id=user.id, server=PROVIDER)
    assert tok == NEW_ACCESS_TOKEN
    row = (
        await db_session.execute(select(MCPOAuthToken).where(MCPOAuthToken.user_id == user.id))
    ).scalar_one()
    enc = MCPTokenEncryptor.from_environ()
    # Old refresh token retained.
    assert row.refresh_token is not None
    assert enc.decrypt(row.refresh_token) == REFRESH_TOKEN


@pytest.mark.asyncio
async def test_get_valid_token_expired_refresh_as_400_deletes_row(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    await _seed_token(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    with respx.mock(base_url=GW) as mock:
        _mock_config(mock)
        _mock_discover(mock)
        mock.post(f"/v1/oauth/{PROVIDER}/token").mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )
        tok = await oauth.get_valid_token(db_session, user_id=user.id, server=PROVIDER)
    assert tok is None
    assert (
        await db_session.execute(select(MCPOAuthToken).where(MCPOAuthToken.user_id == user.id))
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_get_valid_token_expired_no_refresh_returns_none(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    await _seed_token(
        db_session,
        user_id=user.id,
        refresh=None,
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    assert await oauth.get_valid_token(db_session, user_id=user.id, server=PROVIDER) is None


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_deletes_then_idempotent(
    db_session: AsyncSession, mcp_master_key: str
) -> None:
    user = await _make_user(db_session)
    await _seed_token(db_session, user_id=user.id, expires_at=None)
    assert await oauth.disconnect(db_session, user_id=user.id, server=PROVIDER) is True
    assert await oauth.disconnect(db_session, user_id=user.id, server=PROVIDER) is False


# ---------------------------------------------------------------------------
# Credential-leak guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_credentials_leak_in_logs_or_exceptions(
    db_session: AsyncSession, mcp_master_key: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Drive a full happy path AND an error path; assert NO token/code/verifier
    literal appears in any emitted log record or in the raised exception text."""
    secrets_to_guard = [
        AUTH_CODE,
        "verifier-leak-test",
        ACCESS_TOKEN,
        REFRESH_TOKEN,
        NEW_ACCESS_TOKEN,
        NEW_REFRESH_TOKEN,
    ]

    caplog.set_level(logging.DEBUG)

    user = await _make_user(db_session)

    # Happy path: authorize -> exchange.
    with respx.mock(base_url=GW) as mock:
        _mock_config(mock)
        _mock_discover(mock)
        await oauth.build_authorize_url(
            db_session, user_id=user.id, server=PROVIDER, redirect_uri=REDIRECT_URI
        )
        await _seed_state(
            db_session,
            user_id=user.id,
            state="st-leak",
            code_verifier="verifier-leak-test",
        )
        mock.post(f"/v1/oauth/{PROVIDER}/token").mock(
            return_value=httpx.Response(200, json=_token_response())
        )
        await oauth.exchange_code(db_session, state="st-leak", code=AUTH_CODE, iss=ISSUER)

    # Refresh path: force the token row to appear expired, then call
    # get_valid_token so the refresh branch actually runs.  This makes the
    # NEW_ACCESS_TOKEN / NEW_REFRESH_TOKEN literals genuinely pass through the
    # service code, so the no-leak assertion below is non-vacuous.
    token_row = (
        await db_session.execute(
            select(MCPOAuthToken).where(
                MCPOAuthToken.user_id == user.id,
                MCPOAuthToken.provider_name == PROVIDER,
            )
        )
    ).scalar_one()
    token_row.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.flush()

    with respx.mock(base_url=GW) as mock:
        _mock_config(mock)
        _mock_discover(mock)
        mock.post(f"/v1/oauth/{PROVIDER}/token").mock(
            return_value=httpx.Response(
                200,
                json=_token_response(
                    access=NEW_ACCESS_TOKEN, refresh=NEW_REFRESH_TOKEN, expires_in=3600
                ),
            )
        )
        await oauth.get_valid_token(db_session, user_id=user.id, server=PROVIDER)

    # Error path: an AS 400 on exchange.
    captured_exc_text = ""
    await _seed_state(
        db_session, user_id=user.id, state="st-leak-err", code_verifier="verifier-leak-test"
    )
    with respx.mock(base_url=GW) as mock:
        _mock_config(mock)
        mock.post(f"/v1/oauth/{PROVIDER}/token").mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )
        try:
            await oauth.exchange_code(db_session, state="st-leak-err", code=AUTH_CODE, iss=ISSUER)
        except oauth.MCPOAuthExchangeError as exc:
            # Scan str() and repr() only; MCPOAuthExchangeError has no .details
            # attribute so that term would always be an empty string.
            captured_exc_text = repr(exc) + str(exc)

    haystack = "\n".join(r.getMessage() for r in caplog.records) + "\n" + captured_exc_text
    for secret in secrets_to_guard:
        assert secret not in haystack, f"credential leaked into logs/exception: {secret!r}"
