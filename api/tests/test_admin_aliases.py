"""Integration tests for the backend admin alias proxy (D0.5).

The backend's ``/api/v1/admin/aliases/*`` proxies the gateway. These
tests cover:

* The is_admin gate (non-admin → 403; admin → 200)
* Proxy translation (gateway 200 → backend 200; gateway 404 → 404;
  gateway 409 → 409; gateway 422 → 422)
* The CRUD round-trip (list / get / create / update / delete)
* Auth: bearer token required (401 without)
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

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


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
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


# ---------------------------------------------------------------------------
# Auth + admin gate
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_admin_aliases_requires_auth(client: AsyncClient) -> None:
    res = await client.get("/api/v1/admin/aliases")
    assert res.status_code == 401


@pytest.mark.unit
async def test_admin_aliases_rejects_non_admin(client: AsyncClient, regular_user: User) -> None:
    res = await client.get(
        "/api/v1/admin/aliases",
        headers={"Authorization": f"Bearer {_bearer_for(regular_user)}"},
    )
    assert res.status_code == 403
    body = res.json()
    assert body["detail"]["code"] == "forbidden"


@pytest.mark.unit
async def test_admin_aliases_admin_passes_through(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.get("/admin/v1/aliases").mock(
            return_value=httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {
                            "name": "smart",
                            "provider": "anthropic-prod",
                            "model": "claude-opus-4-7",
                            "fallback": [],
                        }
                    ],
                },
            )
        )
        res = await client.get(
            "/api/v1/admin/aliases",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
        )
    assert res.status_code == 200
    assert res.json()["data"][0]["name"] == "smart"


# ---------------------------------------------------------------------------
# CRUD round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_alias_proxies_through(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.get("/admin/v1/aliases/smart").mock(
            return_value=httpx.Response(
                200,
                json={
                    "name": "smart",
                    "provider": "anthropic-prod",
                    "model": "claude-opus-4-7",
                    "fallback": [],
                    "primary_inference_tier": 4,
                },
            )
        )
        res = await client.get(
            "/api/v1/admin/aliases/smart",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
        )
    assert res.status_code == 200
    assert res.json()["primary_inference_tier"] == 4


@pytest.mark.unit
async def test_get_alias_404_propagates(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.get("/admin/v1/aliases/ghost").mock(
            return_value=httpx.Response(
                404,
                json={
                    "error": {
                        "code": "not_found",
                        "message": "alias 'ghost' not found",
                        "details": {},
                    }
                },
            )
        )
        res = await client.get(
            "/api/v1/admin/aliases/ghost",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
        )
    assert res.status_code == 404
    assert res.json()["detail"]["code"] == "not_found"


@pytest.mark.unit
async def test_create_alias_proxies(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.post("/admin/v1/aliases").mock(
            return_value=httpx.Response(
                201,
                json={
                    "name": "new-alias",
                    "provider": "anthropic-prod",
                    "model": "claude-opus-4-7",
                    "fallback": [],
                },
            )
        )
        res = await client.post(
            "/api/v1/admin/aliases",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
            json={
                "name": "new-alias",
                "provider": "anthropic-prod",
                "model": "claude-opus-4-7",
            },
        )
    assert res.status_code == 201
    assert res.json()["name"] == "new-alias"


@pytest.mark.unit
async def test_create_alias_409_propagates(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.post("/admin/v1/aliases").mock(
            return_value=httpx.Response(
                409,
                json={
                    "error": {
                        "code": "conflict",
                        "message": "alias already exists",
                        "details": {},
                    }
                },
            )
        )
        res = await client.post(
            "/api/v1/admin/aliases",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
            json={
                "name": "smart",
                "provider": "anthropic-prod",
                "model": "claude-opus-4-7",
            },
        )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "conflict"


@pytest.mark.unit
async def test_update_alias_proxies(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.patch("/admin/v1/aliases/fast").mock(
            return_value=httpx.Response(
                200,
                json={
                    "name": "fast",
                    "provider": "anthropic-prod",
                    "model": "claude-haiku-4-5",
                    "fallback": [],
                },
            )
        )
        res = await client.patch(
            "/api/v1/admin/aliases/fast",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
            json={
                "provider": "anthropic-prod",
                "model": "claude-haiku-4-5",
            },
        )
    assert res.status_code == 200
    assert res.json()["model"] == "claude-haiku-4-5"


@pytest.mark.unit
async def test_update_alias_422_propagates(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.patch("/admin/v1/aliases/fast").mock(
            return_value=httpx.Response(
                422,
                json={
                    "error": {
                        "code": "invalid_request",
                        "message": "alias.provider 'ghost' is not configured",
                        "details": {},
                    }
                },
            )
        )
        res = await client.patch(
            "/api/v1/admin/aliases/fast",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
            json={"provider": "ghost", "model": "x"},
        )
    assert res.status_code == 400
    # ValidationError from the backend's lq_ai.errors maps invalid_request
    # → backend ValidationError → 400 per ADR 0003.
    assert res.json()["detail"]["code"] == "validation_error"


@pytest.mark.unit
async def test_delete_alias_proxies_204(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.delete("/admin/v1/aliases/throwaway").mock(return_value=httpx.Response(204))
        res = await client.delete(
            "/api/v1/admin/aliases/throwaway",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
        )
    assert res.status_code == 204


@pytest.mark.unit
async def test_admin_config_proxy(client: AsyncClient, admin_user: User) -> None:
    with respx.mock(base_url=GATEWAY_BASE, assert_all_called=False) as router:
        router.get("/admin/v1/config").mock(
            return_value=httpx.Response(
                200,
                json={
                    "providers": [{"name": "anthropic-prod", "type": "anthropic", "tier": 4}],
                    "model_aliases": {},
                },
            )
        )
        res = await client.get(
            "/api/v1/admin/config",
            headers={"Authorization": f"Bearer {_bearer_for(admin_user)}"},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["providers"][0]["name"] == "anthropic-prod"


@pytest.mark.unit
async def test_admin_config_rejects_non_admin(client: AsyncClient, regular_user: User) -> None:
    res = await client.get(
        "/api/v1/admin/config",
        headers={"Authorization": f"Bearer {_bearer_for(regular_user)}"},
    )
    assert res.status_code == 403
