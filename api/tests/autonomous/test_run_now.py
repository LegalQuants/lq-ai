"""POST /autonomous/run-now — one-off manual session spawn (Phase 1 §4.4).

Verifies the endpoint that wires the defined-but-unused
``trigger_kind='manual'``: a single session for a skill/playbook (+optional
KB/matter/cap), spawned + enqueued, reusing the executor + R4/R5/R6 brakes +
receipt — mirroring ``_run_schedule_sweep``.

Fixtures mirror ``test_schedules.py``: a per-file ``client`` fixture that
overrides ``get_db`` onto the test's SAVEPOINT session, locally-built users
(``autonomous_enabled`` on/off), and ``_bearer()`` for auth headers. The
real endpoint enqueues onto arq; we monkeypatch
``app.api.autonomous.enqueue_autonomous_session_job`` to an async no-op so a
missing Redis never errors.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.autonomous as autonomous_api
from app.db.session import get_db
from app.main import app
from app.models.autonomous import AutonomousSession
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


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run-now endpoint enqueues onto arq; stub it to an async no-op so a
    missing Redis never errors the test (the spawn + DB write is what we assert).
    """
    monkeypatch.setattr(
        autonomous_api, "enqueue_autonomous_session_job", AsyncMock(return_value=True)
    )


async def _make_user(db: AsyncSession, *, autonomous_enabled: bool) -> User:
    user = User(
        email=f"run-now-test-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Run-Now Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=autonomous_enabled,
    )
    db.add(user)
    await db.flush()
    return user


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def opted_in_user(db_session: AsyncSession) -> User:
    return await _make_user(db_session, autonomous_enabled=True)


@pytest_asyncio.fixture
async def plain_user(db_session: AsyncSession) -> User:
    return await _make_user(db_session, autonomous_enabled=False)


@pytest.mark.asyncio
async def test_run_now_spawns_manual_session(
    client: AsyncClient,
    opted_in_user: User,
    db_session: AsyncSession,
) -> None:
    """A skill-targeted run-now creates a running, trigger_kind='manual' session with a non-null cap."""
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        json={"skill_ref": "nda-review", "max_cost_usd": "0.50"},
        headers=_bearer(opted_in_user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["trigger_kind"] == "manual"
    assert body["status"] == "running"
    session_id = uuid.UUID(body["id"])
    row = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.id == session_id)
        )
    ).scalar_one()
    assert row.trigger_kind == "manual"
    assert row.max_cost_usd == Decimal("0.50")
    assert row.params.get("skill_ref") == "nda-review"
    # emit_artifacts was not requested — excluded from params (non-null
    # subset; the key is present iff the body opted in — Donna ask #8).
    assert "emit_artifacts" not in row.params


@pytest.mark.asyncio
async def test_run_now_copies_emit_artifacts_flag_into_params(
    client: AsyncClient,
    opted_in_user: User,
    db_session: AsyncSession,
) -> None:
    """emit_artifacts=true in the body → session params carry the flag
    (Donna ask #8 opt-in plumbing — run-now has no schedule/watch row to
    inherit from, so the request body is the opt-in source)."""
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        json={"skill_ref": "nda-review", "emit_artifacts": True},
        headers=_bearer(opted_in_user),
    )
    assert resp.status_code == 201, resp.text
    session_id = uuid.UUID(resp.json()["id"])
    row = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.id == session_id)
        )
    ).scalar_one()
    assert row.params["emit_artifacts"] is True

    # Explicit false behaves like the default: key absent.
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        json={"skill_ref": "nda-review", "emit_artifacts": False},
        headers=_bearer(opted_in_user),
    )
    assert resp.status_code == 201, resp.text
    session_id = uuid.UUID(resp.json()["id"])
    row = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.id == session_id)
        )
    ).scalar_one()
    assert "emit_artifacts" not in row.params


@pytest.mark.asyncio
async def test_run_now_defaults_cost_cap_when_omitted(
    client: AsyncClient,
    opted_in_user: User,
    db_session: AsyncSession,
) -> None:
    """Omitting max_cost_usd falls back to the config default (never NULL → R4 always armed)."""
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        json={"skill_ref": "nda-review"},
        headers=_bearer(opted_in_user),
    )
    assert resp.status_code == 201, resp.text
    session_id = uuid.UUID(resp.json()["id"])
    row = (
        await db_session.execute(
            select(AutonomousSession).where(AutonomousSession.id == session_id)
        )
    ).scalar_one()
    assert row.max_cost_usd is not None


@pytest.mark.asyncio
async def test_run_now_requires_exactly_one_target(
    client: AsyncClient,
    opted_in_user: User,
) -> None:
    """Zero or both of playbook_id/skill_ref → 422."""
    both = await client.post(
        "/api/v1/autonomous/run-now",
        json={"skill_ref": "nda-review", "playbook_id": str(uuid.uuid4())},
        headers=_bearer(opted_in_user),
    )
    assert both.status_code == 422, both.text
    neither = await client.post(
        "/api/v1/autonomous/run-now", json={}, headers=_bearer(opted_in_user)
    )
    assert neither.status_code == 422, neither.text


@pytest.mark.asyncio
async def test_run_now_requires_opt_in(
    client: AsyncClient,
    plain_user: User,
) -> None:
    """A user without autonomous_enabled gets 403 (AutonomousEnabledUser gate)."""
    resp = await client.post(
        "/api/v1/autonomous/run-now",
        json={"skill_ref": "nda-review"},
        headers=_bearer(plain_user),
    )
    assert resp.status_code == 403, resp.text
