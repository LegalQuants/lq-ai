"""Integration tests for GET /autonomous/sessions/{id}/artifacts (Donna #8, Task 4).

The read surface for a run's persisted document-grade artifact references
(Task 1 substrate + Task 2 chokepoint work-product). Mirrors
test_findings_endpoint.py. Covers:
- Happy path: a session's artifacts return with name/mime/size_bytes,
  correct total_count, ordered by created_at ASC with id ASC tiebreaker
  (stable, repeatable order — not a guaranteed emission sequence).
- document_id enrichment: artifact with a File + Document → document_id
  resolved via the unique documents.file_id; NULL file_id → document_id
  None; file without a documents row → None.
- Cross-user 404: user B requesting user A's session → 404 (id-probing-safe).
- Empty: a session with no artifacts → 200, artifacts=[], total_count=0.
- Pagination: ?limit=1&offset=1 returns the middle artifact + full total_count.
- Stable pagination under identical created_at: rows a run emits in one
  executor commit share a transaction-stable now(); the id tiebreaker
  keeps limit/offset paging free of skips/duplicates and repeatable.
- Unauth → 401.
- OpenAPI conformance for the artifacts path + schemas.
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
from app.models.autonomous import AutonomousArtifact, AutonomousSession
from app.models.document import Document
from app.models.file import File as FileModel
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
        email=f"artif-ep-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Artifact Test User {suffix}".strip(),
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


async def _make_file(db: AsyncSession, *, owner: User, name: str = "memo.md") -> FileModel:
    file_id = uuid.uuid4()
    file_row = FileModel(
        id=file_id,
        owner_id=owner.id,
        filename=name,
        mime_type="text/markdown",
        size_bytes=10,
        hash_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        storage_path=str(file_id),
        ingestion_status="ready",
    )
    db.add(file_row)
    await db.flush()
    return file_row


async def _make_document(db: AsyncSession, *, file: FileModel) -> Document:
    doc = Document(
        file_id=file.id,
        parser="autonomous-artifact",
        page_count=1,
        character_count=10,
        normalized_content="# memo\nhi",
    )
    db.add(doc)
    await db.flush()
    return doc


async def _make_artifact(
    db: AsyncSession,
    *,
    session: AutonomousSession,
    file_id: uuid.UUID | None = None,
    name: str = "memo.md",
    mime: str = "text/markdown",
    size_bytes: int = 10,
    created_at: datetime | None = None,
) -> AutonomousArtifact:
    artifact = AutonomousArtifact(
        session_id=session.id,
        file_id=file_id,
        name=name,
        mime=mime,
        size_bytes=size_bytes,
    )
    if created_at is not None:
        artifact.created_at = created_at
    db.add(artifact)
    await db.flush()
    await db.refresh(artifact)
    return artifact


# ---------------------------------------------------------------------------
# Happy path + document_id enrichment
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_artifacts_returns_them_in_emission_order(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A session's artifacts return with name/mime/size_bytes, ASC by created_at."""
    sess = await _make_session(db_session, user=user_a)
    base = datetime.now(UTC)
    # Insert out of order; explicit created_at proves the ASC sort.
    await _make_artifact(
        db_session,
        session=sess,
        name="second.md",
        size_bytes=22,
        created_at=base + timedelta(seconds=2),
    )
    await _make_artifact(
        db_session,
        session=sess,
        name="first.md",
        size_bytes=11,
        created_at=base + timedelta(seconds=1),
    )
    await _make_artifact(
        db_session,
        session=sess,
        name="third.md",
        size_bytes=33,
        created_at=base + timedelta(seconds=3),
    )

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/artifacts",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    names = [a["name"] for a in body["artifacts"]]
    assert names == ["first.md", "second.md", "third.md"]
    assert body["total_count"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 0

    first = body["artifacts"][0]
    assert first["mime"] == "text/markdown"
    assert first["size_bytes"] == 11
    # No file rows were created — file_id and document_id are null.
    assert first["file_id"] is None
    assert first["document_id"] is None


@pytest.mark.integration
async def test_list_artifacts_enriches_document_id(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """An artifact whose file has a Document gets document_id via documents.file_id."""
    sess = await _make_session(db_session, user=user_a)
    file_row = await _make_file(db_session, owner=user_a)
    doc = await _make_document(db_session, file=file_row)
    await _make_artifact(db_session, session=sess, file_id=file_row.id)

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/artifacts",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["artifacts"][0]
    assert item["file_id"] == str(file_row.id)
    assert item["document_id"] == str(doc.id)


@pytest.mark.integration
async def test_list_artifacts_null_file_id_yields_null_document_id(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A SET-NULLed file_id (file hard-deleted) returns both refs as null."""
    sess = await _make_session(db_session, user=user_a)
    await _make_artifact(db_session, session=sess, file_id=None, name="orphan.md")

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/artifacts",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["artifacts"][0]
    # The metadata survives the hard delete; the refs are honest nulls.
    assert item["name"] == "orphan.md"
    assert item["file_id"] is None
    assert item["document_id"] is None


@pytest.mark.integration
async def test_list_artifacts_file_without_document_yields_null_document_id(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A live file_id with no documents row maps to document_id=None."""
    sess = await _make_session(db_session, user=user_a)
    file_row = await _make_file(db_session, owner=user_a)  # no Document created
    await _make_artifact(db_session, session=sess, file_id=file_row.id)

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/artifacts",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["artifacts"][0]
    assert item["file_id"] == str(file_row.id)
    assert item["document_id"] is None


# ---------------------------------------------------------------------------
# Cross-user 404 (id-probing-safe)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_artifacts_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """User B requesting user A's session artifacts returns 404 (no leakage)."""
    sess = await _make_session(db_session, user=user_a)
    await _make_artifact(db_session, session=sess, name="secret.md")

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/artifacts",
        headers=_bearer(user_b),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_list_artifacts_missing_session_returns_404(
    client: AsyncClient,
    user_a: User,
) -> None:
    """A nonexistent session id returns 404 (same posture as cross-user)."""
    resp = await client.get(
        f"/api/v1/autonomous/sessions/{uuid.uuid4()}/artifacts",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Empty
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_artifacts_empty_session(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A session with no artifacts returns 200, artifacts=[], total_count=0."""
    sess = await _make_session(db_session, user=user_a)

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/artifacts",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["artifacts"] == []
    assert body["total_count"] == 0


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_artifacts_pagination_returns_middle(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """?limit=1&offset=1 returns the middle artifact + full total_count."""
    sess = await _make_session(db_session, user=user_a)
    base = datetime.now(UTC)
    for i in range(3):
        await _make_artifact(
            db_session,
            session=sess,
            name=f"a{i}.md",
            created_at=base + timedelta(seconds=i),
        )

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/artifacts",
        headers=_bearer(user_a),
        params={"limit": 1, "offset": 1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["artifacts"]) == 1
    assert body["artifacts"][0]["name"] == "a1.md"
    assert body["total_count"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1


@pytest.mark.integration
async def test_list_artifacts_identical_created_at_pagination_is_stable(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Artifacts sharing one created_at paginate with no skips/dupes, repeatably.

    Rows a run emits in its single executor commit share one created_at
    (server-side now() is transaction-stable in Postgres); the id ASC
    tiebreaker is what keeps limit/offset paging deterministic.
    """
    sess = await _make_session(db_session, user=user_a)
    shared = datetime.now(UTC)
    created = [
        await _make_artifact(db_session, session=sess, name=f"memo-{i}.md", created_at=shared)
        for i in range(4)
    ]
    expected_ids = {str(a.id) for a in created}

    async def read_pages() -> list[str]:
        ids: list[str] = []
        for offset in range(4):
            resp = await client.get(
                f"/api/v1/autonomous/sessions/{sess.id}/artifacts",
                headers=_bearer(user_a),
                params={"limit": 1, "offset": offset},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["total_count"] == 4
            assert len(body["artifacts"]) == 1
            ids.append(body["artifacts"][0]["id"])
        return ids

    first_pass = await read_pages()
    # Union of all pages is exactly the full set — no skips, no duplicates.
    assert len(first_pass) == len(set(first_pass)) == 4
    assert set(first_pass) == expected_ids
    # And the order is repeatable across a second full read.
    second_pass = await read_pages()
    assert second_pass == first_pass


@pytest.mark.integration
async def test_list_artifacts_isolated_by_session(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Artifacts of one session are not returned for another session of the same user."""
    sess1 = await _make_session(db_session, user=user_a)
    sess2 = await _make_session(db_session, user=user_a)
    await _make_artifact(db_session, session=sess1, name="for-1.md")
    await _make_artifact(db_session, session=sess2, name="for-2.md")

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess1.id}/artifacts",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    names = {a["name"] for a in body["artifacts"]}
    assert names == {"for-1.md"}
    assert body["total_count"] == 1


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_artifacts_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """No Authorization header returns 401."""
    sess = await _make_session(db_session, user=user_a)
    resp = await client.get(f"/api/v1/autonomous/sessions/{sess.id}/artifacts")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# OpenAPI conformance
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_openapi_artifacts_path_registered() -> None:
    """The artifacts path is registered as a GET with 200/401/404."""
    schema = app.openapi()
    path = schema["paths"]["/api/v1/autonomous/sessions/{session_id}/artifacts"]
    assert "get" in path
    get_op = path["get"]
    assert "200" in get_op["responses"]
    assert "401" in get_op["responses"]
    assert "404" in get_op["responses"]


@pytest.mark.unit
def test_openapi_artifact_schemas_in_components() -> None:
    """AutonomousArtifactRead + ListResponse are in components/schemas with the right shape."""
    schema = app.openapi()
    schemas = schema.get("components", {}).get("schemas", {})
    assert "AutonomousArtifactRead" in schemas
    assert "AutonomousArtifactListResponse" in schemas

    read_props = schemas["AutonomousArtifactRead"].get("properties", {})
    for field in ("id", "name", "mime", "size_bytes", "file_id", "document_id", "created_at"):
        assert field in read_props

    list_props = schemas["AutonomousArtifactListResponse"].get("properties", {})
    for field in ("artifacts", "total_count", "limit", "offset"):
        assert field in list_props
