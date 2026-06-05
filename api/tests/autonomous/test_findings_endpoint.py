"""Integration tests for GET /autonomous/sessions/{id}/findings (Task 2).

The read surface for a run's persisted findings (Task 1 work-product).
Covers:
- Happy path: a session's findings return with severity/title/content,
  correct total_count, ordered by created_at ASC (emission order).
- Cross-user 404: user B requesting user A's session → 404 (id-probing-safe).
- Empty: a session with no findings → 200, findings=[], total_count=0.
- Pagination: ?limit=1&offset=1 returns the middle finding + full total_count.
- Unauth → 401.
- OpenAPI conformance for the findings path + schemas.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.autonomous import AutonomousFinding, AutonomousSession
from app.models.user import User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


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


async def _make_user(db: AsyncSession, *, suffix: str = "") -> User:
    user = User(
        email=f"find-ep-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Finding Test User {suffix}".strip(),
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    return await _make_user(db_session, suffix="a")


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    return await _make_user(db_session, suffix="b")


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


async def _make_session(db: AsyncSession, *, user: User) -> AutonomousSession:
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="manual",
        halt_state="running",
        status="running",
        current_phase="intake",
    )
    db.add(sess)
    await db.flush()
    await db.refresh(sess)
    return sess


async def _make_finding(
    db: AsyncSession,
    *,
    session: AutonomousSession,
    severity: str = "info",
    title: str = "Finding",
    content: str = "body",
    created_at: datetime | None = None,
) -> AutonomousFinding:
    finding = AutonomousFinding(
        session_id=session.id,
        severity=severity,
        title=title,
        content=content,
    )
    if created_at is not None:
        finding.created_at = created_at
    db.add(finding)
    await db.flush()
    await db.refresh(finding)
    return finding


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_findings_returns_them_in_emission_order(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A session's findings return with severity/title/content, ASC by created_at."""
    sess = await _make_session(db_session, user=user_a)
    base = datetime.now(UTC)
    # Insert out of order; explicit created_at proves the ASC sort.
    await _make_finding(
        db_session,
        session=sess,
        severity="warn",
        title="Second",
        content="b2",
        created_at=base + timedelta(seconds=2),
    )
    await _make_finding(
        db_session,
        session=sess,
        severity="info",
        title="First",
        content="b1",
        created_at=base + timedelta(seconds=1),
    )
    await _make_finding(
        db_session,
        session=sess,
        severity="critical",
        title="Third",
        content="b3",
        created_at=base + timedelta(seconds=3),
    )

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/findings",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    titles = [f["title"] for f in body["findings"]]
    assert titles == ["First", "Second", "Third"]
    assert body["total_count"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 0

    first = body["findings"][0]
    assert first["severity"] == "info"
    assert first["content"] == "b1"
    assert first["session_id"] == str(sess.id)


# ---------------------------------------------------------------------------
# Cross-user 404 (id-probing-safe)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_findings_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """User B requesting user A's session findings returns 404 (no leakage)."""
    sess = await _make_session(db_session, user=user_a)
    await _make_finding(db_session, session=sess, title="secret")

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/findings",
        headers=_bearer(user_b),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_list_findings_missing_session_returns_404(
    client: AsyncClient,
    user_a: User,
) -> None:
    """A nonexistent session id returns 404 (same posture as cross-user)."""
    resp = await client.get(
        f"/api/v1/autonomous/sessions/{uuid.uuid4()}/findings",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Empty
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_findings_empty_session(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A session with no findings returns 200, findings=[], total_count=0."""
    sess = await _make_session(db_session, user=user_a)

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/findings",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["findings"] == []
    assert body["total_count"] == 0


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_findings_pagination_returns_middle(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """?limit=1&offset=1 returns the middle finding + full total_count."""
    sess = await _make_session(db_session, user=user_a)
    base = datetime.now(UTC)
    for i in range(3):
        await _make_finding(
            db_session,
            session=sess,
            title=f"F{i}",
            created_at=base + timedelta(seconds=i),
        )

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/findings",
        headers=_bearer(user_a),
        params={"limit": 1, "offset": 1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["findings"]) == 1
    assert body["findings"][0]["title"] == "F1"
    assert body["total_count"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1


@pytest.mark.integration
async def test_list_findings_isolated_by_session(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Findings of one session are not returned for another session of the same user."""
    sess1 = await _make_session(db_session, user=user_a)
    sess2 = await _make_session(db_session, user=user_a)
    await _make_finding(db_session, session=sess1, title="for-1")
    await _make_finding(db_session, session=sess2, title="for-2")

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess1.id}/findings",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    titles = {f["title"] for f in body["findings"]}
    assert titles == {"for-1"}
    assert body["total_count"] == 1


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_findings_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """No Authorization header returns 401."""
    sess = await _make_session(db_session, user=user_a)
    resp = await client.get(f"/api/v1/autonomous/sessions/{sess.id}/findings")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# OpenAPI conformance
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_openapi_findings_path_registered() -> None:
    """The findings path is registered as a GET with 200/401/404."""
    schema = app.openapi()
    path = schema["paths"]["/api/v1/autonomous/sessions/{session_id}/findings"]
    assert "get" in path
    get_op = path["get"]
    assert "200" in get_op["responses"]
    assert "401" in get_op["responses"]
    assert "404" in get_op["responses"]


@pytest.mark.unit
def test_openapi_findings_schemas_in_components() -> None:
    """AutonomousFindingRead + ListResponse are in components/schemas with the right shape."""
    schema = app.openapi()
    schemas = schema.get("components", {}).get("schemas", {})
    assert "AutonomousFindingRead" in schemas
    assert "AutonomousFindingListResponse" in schemas

    read_props = schemas["AutonomousFindingRead"].get("properties", {})
    for field in ("id", "session_id", "severity", "title", "content", "created_at"):
        assert field in read_props

    list_props = schemas["AutonomousFindingListResponse"].get("properties", {})
    for field in ("findings", "total_count", "limit", "offset"):
        assert field in list_props
