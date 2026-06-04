"""Integration tests for the backend admin provider-key proxy (Donna #7).

The backend's ``/api/v1/admin/provider-keys*`` proxies the gateway's
``/admin/v1/provider-keys`` surface (runtime BYOK). These tests mirror
``test_admin_aliases.py``; they cover:

* The is_admin gate (non-admin → 403; admin → proxied result)
* Auth: bearer token required (401 without)
* Proxy translation of success + the gateway's structured 4xx errors:
  - 400 ``failed_precondition`` (master key unset) → backend 400
  - 404 ``not_found`` (unknown provider)          → backend 404
  - 409 ``conflict`` (env-only revoke)            → backend 409
* DELETE returns 204 with a genuinely empty body
* No secret appears in any response (the gateway returns only
  ``{provider, type, configured, last4, source}``)
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Admin",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=True,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def regular_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Regular",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    gw = GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)
    set_gateway_client(gw)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    set_gateway_client(None)
    await gw.aclose()
    app.dependency_overrides.pop(get_db, None)


def _bearer_for(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


# A canned secret-safe status row — no full key, only last4 + source.
_STATUS_ROW = {
    "provider": "anthropic",
    "type": "anthropic",
    "configured": True,
    "last4": "cdef",
    "source": "runtime",
}


def _assert_no_secret(body: object) -> None:
    """The status payload must never carry a full key / token field."""

    text = repr(body)
    for forbidden in ("api_key", "api_key_encrypted", "sk-", "plaintext"):
        assert forbidden not in text, f"secret-like field {forbidden!r} leaked: {text}"


# ---------------------------------------------------------------------------
# Auth + admin gate
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_provider_keys_requires_auth(client: AsyncClient) -> None:
    res = await client.get("/api/v1/admin/provider-keys")
    assert res.status_code == 401


@pytest.mark.unit
async def test_list_provider_keys_rejects_non_admin(
    client: AsyncClient, regular_user: User
) -> None:
    res = await client.get(
        "/api/v1/admin/provider-keys",
        headers={"Authorization": f"Bearer {_bearer_for(regular_user)}"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "forbidden"


@pytest.mark.unit
async def test_set_provider_key_rejects_non_admin(client: AsyncClient, regular_user: User) -> None:
    res = await client.post(
        "/api/v1/admin/provider-keys",
        headers={"Authorization": f"Bearer {_bearer_for(regular_user)}"},
        json={"provider": "anthropic", "api_key": "sk-abcdef"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "forbidden"


@pytest.mark.unit
async def test_rotate_provider_key_rejects_non_admin(
    client: AsyncClient, regular_user: User
) -> None:
    res = await client.patch(
        "/api/v1/admin/provider-keys/anthropic",
        headers={"Authorization": f"Bearer {_bearer_for(regular_user)}"},
        json={"api_key": "sk-abcdef"},
    )
    assert res.status_code == 403


@pytest.mark.unit
async def test_revoke_provider_key_rejects_non_admin(
    client: AsyncClient, regular_user: User
) -> None:
    res = await client.delete(
        "/api/v1/admin/provider-keys/anthropic",
        headers={"Authorization": f"Bearer {_bearer_for(regular_user)}"},
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_list_provider_keys_proxies(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.get("/admin/v1/provider-keys").mock(
            return_value=httpx.Response(
                200,
                json={
                    "provider_keys": [
                        _STATUS_ROW,
                        {
                            "provider": "openai",
                            "type": "openai",
                            "configured": False,
                            "last4": None,
                            "source": None,
                        },
                    ]
                },
            )
        )
        res = await client.get(
            "/api/v1/admin/provider-keys",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["provider_keys"][0]["provider"] == "anthropic"
    assert body["provider_keys"][0]["last4"] == "cdef"
    _assert_no_secret(body)


@pytest.mark.unit
async def test_set_provider_key_proxies(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.post("/admin/v1/provider-keys").mock(
            return_value=httpx.Response(200, json=_STATUS_ROW)
        )
        res = await client.post(
            "/api/v1/admin/provider-keys",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
            json={"provider": "anthropic", "api_key": "sk-test-abcdef"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "anthropic"
    assert body["configured"] is True
    _assert_no_secret(body)


@pytest.mark.unit
async def test_rotate_provider_key_proxies(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.patch("/admin/v1/provider-keys/anthropic").mock(
            return_value=httpx.Response(200, json=_STATUS_ROW)
        )
        res = await client.patch(
            "/api/v1/admin/provider-keys/anthropic",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
            json={"api_key": "sk-test-rotated"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "anthropic"
    _assert_no_secret(body)


@pytest.mark.unit
async def test_revoke_provider_key_proxies_204_empty_body(
    client: AsyncClient, admin_user: User
) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.delete("/admin/v1/provider-keys/anthropic").mock(return_value=httpx.Response(204))
        res = await client.delete(
            "/api/v1/admin/provider-keys/anthropic",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
        )
    assert res.status_code == 204
    # Canonical DELETE-204 recipe → genuinely empty body.
    assert res.content == b""


# ---------------------------------------------------------------------------
# Error propagation (gateway structured 4xx → backend 4xx)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_set_provider_key_master_key_missing_400(
    client: AsyncClient, admin_user: User
) -> None:
    """Gateway 400 ``failed_precondition`` (master key unset) must surface
    as a backend 4xx — NOT a 500."""

    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.post("/admin/v1/provider-keys").mock(
            return_value=httpx.Response(
                400,
                json={
                    "error": {
                        "code": "failed_precondition",
                        "message": "runtime key storage requires LQ_AI_GATEWAY_MASTER_KEY to be set",
                        "details": {"provider": "anthropic"},
                    }
                },
            )
        )
        res = await client.post(
            "/api/v1/admin/provider-keys",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
            json={"provider": "anthropic", "api_key": "sk-test"},
        )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "validation_error"


@pytest.mark.unit
async def test_set_provider_key_unknown_provider_404(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.post("/admin/v1/provider-keys").mock(
            return_value=httpx.Response(
                404,
                json={
                    "error": {
                        "code": "not_found",
                        "message": "provider 'ghost' is not configured",
                        "details": {"provider": "ghost"},
                    }
                },
            )
        )
        res = await client.post(
            "/api/v1/admin/provider-keys",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
            json={"provider": "ghost", "api_key": "sk-test"},
        )
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "not_found"


@pytest.mark.unit
async def test_rotate_provider_key_master_key_missing_400(
    client: AsyncClient, admin_user: User
) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.patch("/admin/v1/provider-keys/anthropic").mock(
            return_value=httpx.Response(
                400,
                json={
                    "error": {
                        "code": "failed_precondition",
                        "message": "runtime key storage requires LQ_AI_GATEWAY_MASTER_KEY to be set",
                        "details": {"provider": "anthropic"},
                    }
                },
            )
        )
        res = await client.patch(
            "/api/v1/admin/provider-keys/anthropic",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
            json={"api_key": "sk-test"},
        )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "validation_error"


@pytest.mark.unit
async def test_revoke_provider_key_env_only_409(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.delete("/admin/v1/provider-keys/anthropic").mock(
            return_value=httpx.Response(
                409,
                json={
                    "error": {
                        "code": "conflict",
                        "message": "provider 'anthropic' has no runtime key to revoke",
                        "details": {"provider": "anthropic"},
                    }
                },
            )
        )
        res = await client.delete(
            "/api/v1/admin/provider-keys/anthropic",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
        )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "conflict"


@pytest.mark.unit
async def test_revoke_provider_key_unknown_provider_404(
    client: AsyncClient, admin_user: User
) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.delete("/admin/v1/provider-keys/ghost").mock(
            return_value=httpx.Response(
                404,
                json={
                    "error": {
                        "code": "not_found",
                        "message": "provider 'ghost' is not configured",
                        "details": {"provider": "ghost"},
                    }
                },
            )
        )
        res = await client.delete(
            "/api/v1/admin/provider-keys/ghost",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
        )
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "not_found"
