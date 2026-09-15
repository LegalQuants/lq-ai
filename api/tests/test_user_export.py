"""Integration tests for the D6 GDPR Article 20 export surface.

Covers:

* POST /users/me/export inserts a queued row + audit-logs the request.
* GET /users/me/export/{id} returns status; 404s on cross-user access.
* The worker's _build_zip produces a ZIP with the expected entries.
* The GC cron clears storage_key for expired rows.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models import AuditLog, Chat, Project, User, UserExportJob
from app.security import create_access_token, hash_password
from app.workers.user_export import build_export_zip_for_test, export_gc_job


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
    user = User(
        email=f"export-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Export Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# /users/me/export — POST
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_export_post_inserts_queued_row(
    client: AsyncClient, db_session: AsyncSession, seed_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST returns 202 with job_id + status='queued'; row persisted; audit row written."""

    # Prevent the test from actually trying to enqueue against arq/Redis.
    async def _noop_enqueue(_job_id: uuid.UUID) -> bool:
        return True

    monkeypatch.setattr("app.api.users.enqueue_user_export_job", _noop_enqueue)

    resp = await client.post("/api/v1/users/me/export", headers=_bearer(seed_user))
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["download_url"] is None
    job_id = uuid.UUID(body["job_id"])

    job = await db_session.get(UserExportJob, job_id)
    assert job is not None
    assert job.user_id == seed_user.id
    assert job.status == "queued"
    assert job.storage_key is None

    # Audit-log row written for the request.
    rows = (
        (await db_session.execute(select(AuditLog).where(AuditLog.user_id == seed_user.id)))
        .scalars()
        .all()
    )
    actions = {r.action for r in rows}
    assert "user.export_requested" in actions


# ---------------------------------------------------------------------------
# /users/me/export/{job_id} — GET
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_export_get_returns_job_status(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    job = UserExportJob(user_id=seed_user.id, status="queued")
    db_session.add(job)
    await db_session.flush()

    resp = await client.get(
        f"/api/v1/users/me/export/{job.id}",
        headers=_bearer(seed_user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"
    assert resp.json()["download_url"] is None


@pytest.mark.integration
async def test_export_get_for_completed_returns_download_url(
    client: AsyncClient,
    db_session: AsyncSession,
    seed_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed job with storage_key gets a presigned URL in the response."""
    job = UserExportJob(
        user_id=seed_user.id,
        status="completed",
        storage_key=f"exports/{seed_user.id}/{uuid.uuid4()}.zip",
        expires_at=datetime.now(tz=UTC) + timedelta(days=7),
    )
    db_session.add(job)
    await db_session.flush()

    async def _fake_presign(*, storage_path: str, expires_in_seconds: int) -> str:
        return f"https://presigned.example/{storage_path}?Expires={expires_in_seconds}"

    monkeypatch.setattr("app.api.users.presigned_get_url", _fake_presign)

    resp = await client.get(
        f"/api/v1/users/me/export/{job.id}",
        headers=_bearer(seed_user),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["download_url"]
    assert "presigned.example" in body["download_url"]


@pytest.mark.integration
async def test_export_get_for_other_user_returns_404(
    client: AsyncClient, db_session: AsyncSession, seed_user: User
) -> None:
    """Accessing another user's job is a 404, not a 403 — don't leak existence."""
    other = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("other-password"),
        is_admin=False,
    )
    db_session.add(other)
    await db_session.flush()

    other_job = UserExportJob(user_id=other.id, status="completed")
    db_session.add(other_job)
    await db_session.flush()

    resp = await client.get(
        f"/api/v1/users/me/export/{other_job.id}",
        headers=_bearer(seed_user),
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_export_get_with_garbage_id_returns_404(client: AsyncClient, seed_user: User) -> None:
    resp = await client.get(
        "/api/v1/users/me/export/not-a-uuid",
        headers=_bearer(seed_user),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Worker — _build_zip
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_build_export_zip_includes_expected_entries(
    db_session: AsyncSession, seed_user: User
) -> None:
    """The worker's _build_zip produces an archive with the documented layout."""
    project = Project(
        owner_id=seed_user.id,
        name="A Matter",
        slug="a-matter",
        description="Test project",
    )
    db_session.add(project)
    chat = Chat(owner_id=seed_user.id, title="Some chat")
    db_session.add(chat)
    await db_session.flush()

    zip_bytes = await build_export_zip_for_test(db_session, seed_user)
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = set(archive.namelist())

    for entry in (
        "README.md",
        "user.json",
        "chats.json",
        "messages.json",
        "projects.json",
        "files.json",
        "knowledge_bases.json",
        "audit_log.json",
        "skills.json",
    ):
        assert entry in names, f"missing entry: {entry}"

    user_json = json.loads(archive.read("user.json"))
    assert user_json["email"] == seed_user.email
    # Sanitized — no credential material in the export.
    for forbidden in ("hashed_password", "totp_secret", "recovery_codes"):
        assert forbidden not in user_json

    chats_json = json.loads(archive.read("chats.json"))
    assert any(c["id"] == str(chat.id) for c in chats_json)

    projects_json = json.loads(archive.read("projects.json"))
    assert any(p["slug"] == "a-matter" for p in projects_json)


# ---------------------------------------------------------------------------
# GC cron
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_export_gc_clears_expired_rows(
    db_session: AsyncSession, seed_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """export_gc_job clears storage_key for rows past expires_at."""

    expired = UserExportJob(
        user_id=seed_user.id,
        status="completed",
        storage_key=f"exports/{seed_user.id}/{uuid.uuid4()}.zip",
        expires_at=datetime.now(tz=UTC) - timedelta(hours=1),
    )
    fresh = UserExportJob(
        user_id=seed_user.id,
        status="completed",
        storage_key=f"exports/{seed_user.id}/{uuid.uuid4()}.zip",
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    db_session.add_all([expired, fresh])
    await db_session.flush()
    expired_id = expired.id
    fresh_id = fresh.id

    deleted: list[str] = []

    async def _fake_delete(*, storage_path: str) -> None:
        deleted.append(storage_path)

    # Patch the storage delete and the session factory to use the test
    # session; arq's cron entry point goes through these.
    from contextlib import AbstractAsyncContextManager, asynccontextmanager

    monkeypatch.setattr("app.workers.user_export.delete_object", _fake_delete)

    @asynccontextmanager
    async def _factory_cm() -> AsyncIterator[AsyncSession]:
        yield db_session

    def _factory_callable() -> AbstractAsyncContextManager[AsyncSession]:
        return _factory_cm()

    monkeypatch.setattr("app.workers.user_export.get_session_factory", lambda: _factory_callable)

    result = await export_gc_job({})

    assert result["reaped"] >= 1
    assert len(deleted) >= 1

    # The expired row's storage_key is cleared; the fresh row is untouched.
    expired_row = await db_session.get(UserExportJob, expired_id)
    fresh_row = await db_session.get(UserExportJob, fresh_id)
    assert expired_row is not None and fresh_row is not None
    await db_session.refresh(expired_row)
    await db_session.refresh(fresh_row)
    assert expired_row.storage_key is None
    assert fresh_row.storage_key is not None
