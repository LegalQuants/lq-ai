"""Integration tests for the C6 knowledge-bases surface.

Covers the C6 verification flow:

    Add 5 files to a KB; query for content; verify expected chunks
    appear in top results. After backfill, no chunks have NULL
    embeddings.

This module focuses on CRUD + attach round-trips. The query path with
end-to-end embed-on-write/read is in test_knowledge_query_endpoint.py;
the embed-on-write worker job is in test_knowledge_embed_unit.py.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.file import File as FileModel
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.project import Project
from app.models.project_knowledge_base import ProjectKnowledgeBase
from app.models.user import User
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
async def db_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"kb-{uuid.uuid4().hex[:8]}@example.com",
        display_name="KB Test User",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"kb-other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer_for(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


def _auth_headers(user: User) -> dict[str, str]:
    return {"authorization": f"Bearer {_bearer_for(user)}"}


# --- Auth ----------------------------------------------------------------


@pytest.mark.integration
async def test_unauth_returns_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/knowledge-bases")
    assert response.status_code == 401


@pytest.mark.integration
async def test_must_change_password_returns_403(
    db_session: AsyncSession,
    client: AsyncClient,
) -> None:
    user = User(
        email=f"forced-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("hunter22hunter22"),
        must_change_password=True,
    )
    db_session.add(user)
    await db_session.flush()
    response = await client.get("/api/v1/knowledge-bases", headers=_auth_headers(user))
    assert response.status_code == 403
    body = response.json()
    assert body["detail"]["code"] == "password_change_required"


# --- CRUD ----------------------------------------------------------------


@pytest.mark.integration
async def test_create_kb_minimal(client: AsyncClient, db_user: User) -> None:
    response = await client.post(
        "/api/v1/knowledge-bases",
        headers=_auth_headers(db_user),
        json={"name": "case-research"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "case-research"
    assert body["hybrid_alpha"] == 0.5
    assert body["file_count"] == 0
    assert body["chunk_count"] == 0
    assert body["archived_at"] is None
    assert body["owner_id"] == str(db_user.id)


@pytest.mark.integration
async def test_create_kb_with_alpha(client: AsyncClient, db_user: User) -> None:
    response = await client.post(
        "/api/v1/knowledge-bases",
        headers=_auth_headers(db_user),
        json={"name": "vector-heavy", "hybrid_alpha": 0.2, "description": "FYI"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["hybrid_alpha"] == 0.2
    assert body["description"] == "FYI"


@pytest.mark.integration
async def test_create_kb_alpha_out_of_range_422(client: AsyncClient, db_user: User) -> None:
    response = await client.post(
        "/api/v1/knowledge-bases",
        headers=_auth_headers(db_user),
        json={"name": "bad", "hybrid_alpha": 1.5},
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_create_kb_with_unknown_project_404(client: AsyncClient, db_user: User) -> None:
    response = await client.post(
        "/api/v1/knowledge-bases",
        headers=_auth_headers(db_user),
        json={"name": "k", "project_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_create_kb_with_cross_user_project_404(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
    other_user: User,
) -> None:
    foreign_proj = Project(owner_id=other_user.id, name="theirs", slug="theirs")
    db_session.add(foreign_proj)
    await db_session.flush()
    response = await client.post(
        "/api/v1/knowledge-bases",
        headers=_auth_headers(db_user),
        json={"name": "k", "project_id": str(foreign_proj.id)},
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_list_kbs_active_only_by_default(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    active = KnowledgeBase(owner_id=db_user.id, name="active")
    archived = KnowledgeBase(
        owner_id=db_user.id,
        name="archived",
    )
    from datetime import UTC, datetime

    archived.archived_at = datetime.now(tz=UTC)
    db_session.add_all([active, archived])
    await db_session.flush()

    response = await client.get("/api/v1/knowledge-bases", headers=_auth_headers(db_user))
    assert response.status_code == 200
    body = response.json()
    names = {kb["name"] for kb in body}
    assert "active" in names
    assert "archived" not in names


@pytest.mark.integration
async def test_list_kbs_archived_filter(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    from datetime import UTC, datetime

    active = KnowledgeBase(owner_id=db_user.id, name="active2")
    archived = KnowledgeBase(owner_id=db_user.id, name="archived2")
    archived.archived_at = datetime.now(tz=UTC)
    db_session.add_all([active, archived])
    await db_session.flush()

    response = await client.get(
        "/api/v1/knowledge-bases?archived=true",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 200
    names = {kb["name"] for kb in response.json()}
    assert names == {"archived2"}


@pytest.mark.integration
async def test_list_kbs_per_user_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
    other_user: User,
) -> None:
    mine = KnowledgeBase(owner_id=db_user.id, name="mine")
    theirs = KnowledgeBase(owner_id=other_user.id, name="theirs")
    db_session.add_all([mine, theirs])
    await db_session.flush()

    response = await client.get("/api/v1/knowledge-bases", headers=_auth_headers(db_user))
    assert response.status_code == 200
    names = {kb["name"] for kb in response.json()}
    assert names == {"mine"}


@pytest.mark.integration
async def test_list_kbs_project_filter_uses_join_table(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    """``?project_id=`` returns KBs linked via the join table.

    Regression test: the list endpoint previously filtered on the legacy
    ``knowledge_bases.project_id`` column, so a KB attached through
    ``POST /projects/{id}/knowledge-bases`` (which writes the
    ``project_knowledge_bases`` junction, not the legacy column) was
    functional in retrieval but invisible on the matter page. The filter
    must key off the junction row instead.
    """

    project = Project(owner_id=db_user.id, name="Matter A", slug=f"matter-{uuid.uuid4().hex[:8]}")
    other_project = Project(
        owner_id=db_user.id, name="Matter B", slug=f"matter-{uuid.uuid4().hex[:8]}"
    )
    db_session.add_all([project, other_project])
    await db_session.flush()

    # Linked only via the join table — legacy project_id left NULL.
    linked = KnowledgeBase(owner_id=db_user.id, name="linked-via-join")
    # A KB attached to a *different* project via the join table.
    other_linked = KnowledgeBase(owner_id=db_user.id, name="linked-elsewhere")
    # A KB carrying a stale legacy project_id but with NO join row: under the
    # join-table semantics it is NOT in the project.
    stale_legacy = KnowledgeBase(owner_id=db_user.id, name="stale-legacy", project_id=project.id)
    db_session.add_all([linked, other_linked, stale_legacy])
    await db_session.flush()

    db_session.add_all(
        [
            ProjectKnowledgeBase(
                project_id=project.id,
                knowledge_base_id=linked.id,
                attached_by_user_id=db_user.id,
            ),
            ProjectKnowledgeBase(
                project_id=other_project.id,
                knowledge_base_id=other_linked.id,
                attached_by_user_id=db_user.id,
            ),
        ]
    )
    await db_session.flush()

    response = await client.get(
        f"/api/v1/knowledge-bases?project_id={project.id}",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 200
    names = {kb["name"] for kb in response.json()}
    assert names == {"linked-via-join"}
    # KB attached to a different project is excluded.
    assert "linked-elsewhere" not in names
    # Stale legacy project_id (no join row) is NOT treated as in-project.
    assert "stale-legacy" not in names


@pytest.mark.integration
async def test_list_kbs_project_filter_respects_owner_and_archived(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
    other_user: User,
) -> None:
    """Project filter keeps the owner scope and the active-only default."""

    from datetime import UTC, datetime

    project = Project(owner_id=db_user.id, name="Matter C", slug=f"matter-{uuid.uuid4().hex[:8]}")
    db_session.add(project)
    await db_session.flush()

    active = KnowledgeBase(owner_id=db_user.id, name="active-in-project")
    archived = KnowledgeBase(owner_id=db_user.id, name="archived-in-project")
    archived.archived_at = datetime.now(tz=UTC)
    # A join row owned-context: another user's KB joined to db_user's project
    # must never leak (owner scope wins).
    foreign = KnowledgeBase(owner_id=other_user.id, name="foreign-in-project")
    db_session.add_all([active, archived, foreign])
    await db_session.flush()

    db_session.add_all(
        [
            ProjectKnowledgeBase(project_id=project.id, knowledge_base_id=active.id),
            ProjectKnowledgeBase(project_id=project.id, knowledge_base_id=archived.id),
            ProjectKnowledgeBase(project_id=project.id, knowledge_base_id=foreign.id),
        ]
    )
    await db_session.flush()

    response = await client.get(
        f"/api/v1/knowledge-bases?project_id={project.id}",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 200
    names = {kb["name"] for kb in response.json()}
    assert names == {"active-in-project"}


@pytest.mark.integration
async def test_get_kb_round_trip(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    kb = KnowledgeBase(owner_id=db_user.id, name="round-trip")
    db_session.add(kb)
    await db_session.flush()
    response = await client.get(
        f"/api/v1/knowledge-bases/{kb.id}",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(kb.id)
    assert body["name"] == "round-trip"


@pytest.mark.integration
async def test_get_kb_cross_user_404(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
    other_user: User,
) -> None:
    kb = KnowledgeBase(owner_id=other_user.id, name="theirs")
    db_session.add(kb)
    await db_session.flush()
    response = await client.get(
        f"/api/v1/knowledge-bases/{kb.id}",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_get_kb_invalid_uuid_400(client: AsyncClient, db_user: User) -> None:
    response = await client.get(
        "/api/v1/knowledge-bases/not-a-uuid",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 400


@pytest.mark.integration
async def test_patch_kb_alpha(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    kb = KnowledgeBase(owner_id=db_user.id, name="patch-me", hybrid_alpha=0.5)
    db_session.add(kb)
    await db_session.flush()
    response = await client.patch(
        f"/api/v1/knowledge-bases/{kb.id}",
        headers=_auth_headers(db_user),
        json={"hybrid_alpha": 0.8},
    )
    assert response.status_code == 200
    assert response.json()["hybrid_alpha"] == 0.8


@pytest.mark.integration
async def test_patch_kb_archive_then_unarchive(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    kb = KnowledgeBase(owner_id=db_user.id, name="archive-cycle")
    db_session.add(kb)
    await db_session.flush()

    archived = await client.patch(
        f"/api/v1/knowledge-bases/{kb.id}",
        headers=_auth_headers(db_user),
        json={"archived": True},
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None

    unarchived = await client.patch(
        f"/api/v1/knowledge-bases/{kb.id}",
        headers=_auth_headers(db_user),
        json={"archived": False},
    )
    assert unarchived.status_code == 200
    assert unarchived.json()["archived_at"] is None


@pytest.mark.integration
async def test_delete_kb_soft_deletes(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    kb = KnowledgeBase(owner_id=db_user.id, name="delete-me")
    db_session.add(kb)
    await db_session.flush()
    response = await client.delete(
        f"/api/v1/knowledge-bases/{kb.id}",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 204

    # Direct GET still works (archived rows visible via direct GET).
    fetch = await client.get(
        f"/api/v1/knowledge-bases/{kb.id}",
        headers=_auth_headers(db_user),
    )
    assert fetch.status_code == 200
    assert fetch.json()["archived_at"] is not None

    # List excludes by default.
    listing = await client.get(
        "/api/v1/knowledge-bases",
        headers=_auth_headers(db_user),
    )
    names = {row["name"] for row in listing.json()}
    assert "delete-me" not in names


@pytest.mark.integration
async def test_delete_kb_idempotent_returns_404_on_second_call(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    kb = KnowledgeBase(owner_id=db_user.id, name="del2")
    db_session.add(kb)
    await db_session.flush()

    first = await client.delete(
        f"/api/v1/knowledge-bases/{kb.id}",
        headers=_auth_headers(db_user),
    )
    assert first.status_code == 204

    second = await client.delete(
        f"/api/v1/knowledge-bases/{kb.id}",
        headers=_auth_headers(db_user),
    )
    assert second.status_code == 404


# --- File attachment ------------------------------------------------------


def _make_ready_file(owner_id: uuid.UUID, filename: str = "doc.pdf") -> FileModel:
    return FileModel(
        owner_id=owner_id,
        filename=filename,
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        storage_path=str(uuid.uuid4()),
        ingestion_status="ready",
    )


@pytest.mark.integration
async def test_attach_ready_file_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    kb = KnowledgeBase(owner_id=db_user.id, name="attach")
    file_row = _make_ready_file(db_user.id)
    db_session.add_all([kb, file_row])
    await db_session.flush()

    response = await client.post(
        f"/api/v1/knowledge-bases/{kb.id}/files",
        headers=_auth_headers(db_user),
        json={"file_id": str(file_row.id)},
    )
    assert response.status_code == 204

    # Confirm file_count reflects the attach.
    fetch = await client.get(
        f"/api/v1/knowledge-bases/{kb.id}",
        headers=_auth_headers(db_user),
    )
    assert fetch.status_code == 200
    assert fetch.json()["file_count"] == 1


@pytest.mark.integration
async def test_attach_pending_file_422(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    kb = KnowledgeBase(owner_id=db_user.id, name="attach-pending")
    pending = _make_ready_file(db_user.id, "p.pdf")
    pending.ingestion_status = "pending"
    db_session.add_all([kb, pending])
    await db_session.flush()

    response = await client.post(
        f"/api/v1/knowledge-bases/{kb.id}/files",
        headers=_auth_headers(db_user),
        json={"file_id": str(pending.id)},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["code"] == "validation_error"


@pytest.mark.integration
async def test_attach_cross_user_file_404(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
    other_user: User,
) -> None:
    kb = KnowledgeBase(owner_id=db_user.id, name="x-user-file")
    foreign = _make_ready_file(other_user.id, "theirs.pdf")
    db_session.add_all([kb, foreign])
    await db_session.flush()

    response = await client.post(
        f"/api/v1/knowledge-bases/{kb.id}/files",
        headers=_auth_headers(db_user),
        json={"file_id": str(foreign.id)},
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_attach_already_attached_409(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    kb = KnowledgeBase(owner_id=db_user.id, name="dup")
    file_row = _make_ready_file(db_user.id)
    db_session.add_all([kb, file_row])
    await db_session.flush()

    first = await client.post(
        f"/api/v1/knowledge-bases/{kb.id}/files",
        headers=_auth_headers(db_user),
        json={"file_id": str(file_row.id)},
    )
    assert first.status_code == 204

    second = await client.post(
        f"/api/v1/knowledge-bases/{kb.id}/files",
        headers=_auth_headers(db_user),
        json={"file_id": str(file_row.id)},
    )
    assert second.status_code == 409


@pytest.mark.integration
async def test_detach_file_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    kb = KnowledgeBase(owner_id=db_user.id, name="detach")
    file_row = _make_ready_file(db_user.id)
    db_session.add_all([kb, file_row])
    await db_session.flush()
    join = KnowledgeBaseFile(kb_id=kb.id, file_id=file_row.id)
    db_session.add(join)
    await db_session.flush()

    response = await client.delete(
        f"/api/v1/knowledge-bases/{kb.id}/files/{file_row.id}",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 204


@pytest.mark.integration
async def test_detach_unknown_file_404(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    kb = KnowledgeBase(owner_id=db_user.id, name="detach-404")
    db_session.add(kb)
    await db_session.flush()

    response = await client.delete(
        f"/api/v1/knowledge-bases/{kb.id}/files/{uuid.uuid4()}",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_attach_to_cross_user_kb_404(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
    other_user: User,
) -> None:
    foreign_kb = KnowledgeBase(owner_id=other_user.id, name="theirs")
    db_session.add(foreign_kb)
    await db_session.flush()

    response = await client.post(
        f"/api/v1/knowledge-bases/{foreign_kb.id}/files",
        headers=_auth_headers(db_user),
        json={"file_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


# --- List attached files (Wave C — Knowledge surface) -------------------


@pytest.mark.integration
async def test_list_kb_files_returns_attached(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    """The Knowledge detail page consumes this endpoint; assert a happy
    round-trip surfaces filename + ingestion_status + attached_at."""

    kb = KnowledgeBase(owner_id=db_user.id, name="docs")
    file_a = _make_ready_file(db_user.id, "alpha.pdf")
    file_b = _make_ready_file(db_user.id, "beta.pdf")
    db_session.add_all([kb, file_a, file_b])
    await db_session.flush()

    # Attach both via the API so attached_at gets a real timestamp + the
    # join + audit row exercise the full path.
    for f in (file_a, file_b):
        attach = await client.post(
            f"/api/v1/knowledge-bases/{kb.id}/files",
            headers=_auth_headers(db_user),
            json={"file_id": str(f.id)},
        )
        assert attach.status_code == 204

    response = await client.get(
        f"/api/v1/knowledge-bases/{kb.id}/files",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    by_name = {r["filename"]: r for r in rows}
    assert set(by_name) == {"alpha.pdf", "beta.pdf"}
    sample = by_name["alpha.pdf"]
    assert sample["ingestion_status"] == "ready"
    assert sample["mime_type"] == "application/pdf"
    assert sample["size_bytes"] == 10
    assert sample["owner_id"] == str(db_user.id)
    assert sample["attached_at"] is not None
    assert sample["created_at"] is not None
    # page_count / character_count are populated by the C5 pipeline; the
    # raw fixture has no Document row so they serialize as null.
    assert sample["page_count"] is None
    assert sample["character_count"] is None


@pytest.mark.integration
async def test_list_kb_files_empty(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    kb = KnowledgeBase(owner_id=db_user.id, name="empty")
    db_session.add(kb)
    await db_session.flush()
    response = await client.get(
        f"/api/v1/knowledge-bases/{kb.id}/files",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.integration
async def test_list_kb_files_cross_user_404(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
    other_user: User,
) -> None:
    """Same posture as the rest of the KB surface — cross-user → 404."""

    foreign = KnowledgeBase(owner_id=other_user.id, name="theirs")
    db_session.add(foreign)
    await db_session.flush()
    response = await client.get(
        f"/api/v1/knowledge-bases/{foreign.id}/files",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_list_kb_files_invalid_uuid_400(
    client: AsyncClient,
    db_user: User,
) -> None:
    response = await client.get(
        "/api/v1/knowledge-bases/not-a-uuid/files",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 400


@pytest.mark.integration
async def test_list_kb_files_excludes_soft_deleted(
    client: AsyncClient,
    db_session: AsyncSession,
    db_user: User,
) -> None:
    """Soft-deleted files (`deleted_at` set) drop out of the list even if
    the join row still exists — keeps the detail page from rendering
    rows for files the caller has already deleted."""

    from datetime import UTC, datetime

    kb = KnowledgeBase(owner_id=db_user.id, name="exclude-deleted")
    keep = _make_ready_file(db_user.id, "keep.pdf")
    drop = _make_ready_file(db_user.id, "drop.pdf")
    db_session.add_all([kb, keep, drop])
    await db_session.flush()

    db_session.add_all(
        [
            KnowledgeBaseFile(kb_id=kb.id, file_id=keep.id),
            KnowledgeBaseFile(kb_id=kb.id, file_id=drop.id),
        ]
    )
    drop.deleted_at = datetime.now(tz=UTC)
    await db_session.flush()

    response = await client.get(
        f"/api/v1/knowledge-bases/{kb.id}/files",
        headers=_auth_headers(db_user),
    )
    assert response.status_code == 200
    names = {row["filename"] for row in response.json()}
    assert names == {"keep.pdf"}
