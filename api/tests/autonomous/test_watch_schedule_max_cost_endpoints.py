"""Tests for M4 Task 4 — ``max_cost_usd`` round-trips through watch + schedule endpoints.

Task 3 added the column + Pydantic field; this task wires the POST + PATCH
endpoint handlers in :mod:`app.api.autonomous` to persist ``max_cost_usd``
to the ORM row so GETs surface it via the Read schemas.

Covers:

* POST /autonomous/watches with ``max_cost_usd`` round-trips through
  create → response → re-GET.
* PATCH /autonomous/watches/{id} can SET ``max_cost_usd`` to a value
  AND clear it back to NULL (the "fall back to global default" semantic
  per the design doc).
* POST /autonomous/schedules with ``max_cost_usd`` round-trips through
  create → response.
* PATCH /autonomous/schedules/{id} can SET and clear ``max_cost_usd``.

Mirrors ``test_watches.py`` / ``test_schedules.py`` fixture style
(local ``client`` + ``user_a`` + ``_bearer`` + ``_make_kb`` helpers) —
this folder has no shared conftest beyond the repo-root ``conftest.py``'s
``db_session``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.knowledge import KnowledgeBase
from app.models.user import User
from app.security import create_access_token, hash_password


def _override_get_db(db_session: AsyncSession):
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
async def user_a(db_session: AsyncSession) -> User:
    user = User(
        email=f"max-cost-ep-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Max Cost Endpoint Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=True,  # mutate endpoints require opt-in
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def kb_a(db_session: AsyncSession, user_a: User) -> KnowledgeBase:
    kb = KnowledgeBase(owner_id=user_a.id, name="max-cost-watch-kb")
    db_session.add(kb)
    await db_session.flush()
    await db_session.refresh(kb)
    return kb


# ===========================================================================
# Watches — POST + PATCH persist max_cost_usd
# ===========================================================================


@pytest.mark.integration
async def test_create_watch_with_max_cost_usd_round_trips(
    client: AsyncClient,
    user_a: User,
    kb_a: KnowledgeBase,
) -> None:
    resp = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb_a.id), "max_cost_usd": "0.50"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(body["max_cost_usd"]) == Decimal("0.50")

    # And the value surfaces on a follow-up GET (Read schema includes the field).
    get_resp = await client.get(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
    )
    assert get_resp.status_code == 200, get_resp.text
    listed = next(w for w in get_resp.json()["watches"] if w["id"] == body["id"])
    assert Decimal(listed["max_cost_usd"]) == Decimal("0.50")


@pytest.mark.integration
async def test_create_watch_without_max_cost_usd_defaults_null(
    client: AsyncClient,
    user_a: User,
    kb_a: KnowledgeBase,
) -> None:
    """Omitting max_cost_usd leaves it NULL — the 'fall back to global default' state."""
    resp = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb_a.id)},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["max_cost_usd"] is None


@pytest.mark.integration
async def test_patch_watch_max_cost_usd(
    client: AsyncClient,
    user_a: User,
    kb_a: KnowledgeBase,
) -> None:
    create = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb_a.id)},
    )
    assert create.status_code == 201, create.text
    watch_id = create.json()["id"]

    patched = await client.patch(
        f"/api/v1/autonomous/watches/{watch_id}",
        headers=_bearer(user_a),
        json={"max_cost_usd": "0.10"},
    )
    assert patched.status_code == 200, patched.text
    assert Decimal(patched.json()["max_cost_usd"]) == Decimal("0.10")


@pytest.mark.integration
async def test_patch_watch_clears_max_cost_usd_to_null(
    client: AsyncClient,
    user_a: User,
    kb_a: KnowledgeBase,
) -> None:
    """PATCH max_cost_usd=null clears the per-watch cap → fall back to global default.

    Uses ``model_dump(exclude_unset=True)`` semantics: a body that explicitly
    sets the field to null is distinguishable from one that omits it.
    """
    create = await client.post(
        "/api/v1/autonomous/watches",
        headers=_bearer(user_a),
        json={"knowledge_base_id": str(kb_a.id), "max_cost_usd": "0.75"},
    )
    assert create.status_code == 201, create.text
    watch_id = create.json()["id"]
    assert Decimal(create.json()["max_cost_usd"]) == Decimal("0.75")

    cleared = await client.patch(
        f"/api/v1/autonomous/watches/{watch_id}",
        headers=_bearer(user_a),
        json={"max_cost_usd": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["max_cost_usd"] is None


# ===========================================================================
# Schedules — POST + PATCH persist max_cost_usd
# ===========================================================================


@pytest.mark.integration
async def test_create_schedule_with_max_cost_usd_round_trips(
    client: AsyncClient,
    user_a: User,
) -> None:
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "0 9 * * *", "max_cost_usd": "0.25"},
    )
    assert resp.status_code == 201, resp.text
    assert Decimal(resp.json()["max_cost_usd"]) == Decimal("0.25")


@pytest.mark.integration
async def test_create_schedule_without_max_cost_usd_defaults_null(
    client: AsyncClient,
    user_a: User,
) -> None:
    resp = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "0 9 * * *"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["max_cost_usd"] is None


@pytest.mark.integration
async def test_patch_schedule_max_cost_usd(
    client: AsyncClient,
    user_a: User,
) -> None:
    create = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "0 9 * * *"},
    )
    assert create.status_code == 201, create.text
    schedule_id = create.json()["id"]

    patched = await client.patch(
        f"/api/v1/autonomous/schedules/{schedule_id}",
        headers=_bearer(user_a),
        json={"max_cost_usd": "0.42"},
    )
    assert patched.status_code == 200, patched.text
    assert Decimal(patched.json()["max_cost_usd"]) == Decimal("0.42")


@pytest.mark.integration
async def test_patch_schedule_clears_max_cost_usd_to_null(
    client: AsyncClient,
    user_a: User,
) -> None:
    """PATCH max_cost_usd=null clears the per-schedule cap → fall back to global default."""
    create = await client.post(
        "/api/v1/autonomous/schedules",
        headers=_bearer(user_a),
        json={"cron_expr": "0 9 * * *", "max_cost_usd": "1.00"},
    )
    assert create.status_code == 201, create.text
    schedule_id = create.json()["id"]
    assert Decimal(create.json()["max_cost_usd"]) == Decimal("1.00")

    cleared = await client.patch(
        f"/api/v1/autonomous/schedules/{schedule_id}",
        headers=_bearer(user_a),
        json={"max_cost_usd": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["max_cost_usd"] is None
