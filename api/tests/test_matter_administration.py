"""Security regression cases for central matter administration."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import Conflict
from app.models.audit import AuditLog
from app.models.chat import Chat
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from tests.test_matter_members import (
    _bearer,
    _mk_user,
    client as client,
    colleague as colleague,
    matter as matter,
    owner as owner,
)


async def test_admin_can_manage_without_content_access(
    client: AsyncClient, db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    admin = await _mk_user(db_session, is_admin=True, role="admin")
    response = await client.get("/api/v1/admin/matters", headers=_bearer(admin))
    assert response.status_code == 200
    row = next(p for p in response.json() if p["id"] == str(matter.id))
    assert "context_md" not in row and "attached_file_ids" not in row
    assert (
        await client.get(f"/api/v1/projects/{matter.id}", headers=_bearer(admin))
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/admin/matters/{matter.id}/members", headers=_bearer(admin))
    ).status_code == 200
    added = await client.post(
        f"/api/v1/projects/{matter.id}/members",
        headers=_bearer(admin),
        json={"user_id": str(colleague.id), "role": "reader", "reason": "Staff the matter"},
    )
    assert added.status_code == 201, added.text
    assert (
        await client.get(f"/api/v1/projects/{matter.id}", headers=_bearer(admin))
    ).status_code == 404
    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "matter.member_added", AuditLog.user_id == admin.id
        )
    )
    assert audit is not None
    assert audit.details is not None
    assert audit.details["reason"] == "Staff the matter"


async def test_admin_intervention_requires_reason(
    client: AsyncClient, db_session: AsyncSession, colleague: User, matter: Project
) -> None:
    admin = await _mk_user(db_session, is_admin=True, role="admin")
    response = await client.post(
        f"/api/v1/projects/{matter.id}/members",
        headers=_bearer(admin),
        json={"user_id": str(colleague.id), "role": "reader", "reason": "  "},
    )
    assert response.status_code == 422
    assert await db_session.get(ProjectMember, (matter.id, colleague.id)) is None


async def test_screened_admin_cannot_unblock_self(
    client: AsyncClient, db_session: AsyncSession, owner: User, matter: Project
) -> None:
    admin = await _mk_user(db_session, is_admin=True, role="admin")
    other = await _mk_user(db_session, is_admin=True, role="admin")
    response = await client.post(
        f"/api/v1/projects/{matter.id}/members",
        headers=_bearer(owner),
        json={"user_id": str(admin.id), "role": "blocked"},
    )
    assert response.status_code == 201
    response = await client.patch(
        f"/api/v1/projects/{matter.id}/members/{admin.id}",
        headers=_bearer(admin),
        json={"role": "lead", "reason": "Self grant"},
    )
    assert response.status_code == 404
    response = await client.get("/api/v1/admin/matters", headers=_bearer(admin))
    assert str(matter.id) not in {p["id"] for p in response.json()}
    response = await client.patch(
        f"/api/v1/projects/{matter.id}/members/{admin.id}",
        headers=_bearer(other),
        json={"role": "reader", "reason": "Screen released by authorised officer"},
    )
    assert response.status_code == 200, response.text


async def test_transfer_can_screen_former_owner(
    client: AsyncClient, db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    admin = await _mk_user(db_session, is_admin=True, role="admin")
    chat = Chat(owner_id=owner.id, project_id=matter.id, title="Retained work")
    db_session.add(chat)
    await db_session.flush()
    from app.models.chat import Message

    original = Message(chat_id=chat.id, role="user", content="Original direction")
    db_session.add(original)
    await db_session.flush()
    assert original.directed_by_user_id == owner.id
    response = await client.post(
        f"/api/v1/admin/matters/{matter.id}/transfer",
        headers=_bearer(admin),
        json={
            "owner_id": str(colleague.id),
            "former_owner_role": "blocked",
            "reason": "Reassign departing counsel's matter",
        },
    )
    assert response.status_code == 200, response.text
    await db_session.refresh(chat)
    assert chat.owner_id == colleague.id
    await db_session.refresh(original)
    assert original.directed_by_user_id == owner.id
    assert (
        await client.get(f"/api/v1/projects/{matter.id}", headers=_bearer(owner))
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/projects/{matter.id}", headers=_bearer(colleague))
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/projects/{matter.id}", headers=_bearer(admin))
    ).status_code == 404


async def test_auditor_cannot_administer(
    client: AsyncClient, db_session: AsyncSession, matter: Project
) -> None:
    auditor = await _mk_user(db_session, role="auditor")
    assert (await client.get("/api/v1/admin/matters", headers=_bearer(auditor))).status_code == 403


async def test_screen_applies_to_own_chat_and_receipts(
    client: AsyncClient, db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    chat = Chat(owner_id=colleague.id, project_id=matter.id, title="My prior work")
    db_session.add(chat)
    db_session.add(
        ProjectMember(
            project_id=matter.id, user_id=colleague.id, added_by_user_id=owner.id, role="blocked"
        )
    )
    await db_session.flush()
    for suffix in ["", "/messages", "/ledger", "/receipts", "/receipts/export"]:
        response = await client.get(f"/api/v1/chats/{chat.id}{suffix}", headers=_bearer(colleague))
        assert response.status_code == 404, (suffix, response.text)
    response = await client.post(
        f"/api/v1/chats/{chat.id}/messages",
        headers=_bearer(colleague),
        json={"content": "Still working"},
    )
    assert response.status_code == 404, response.text


async def test_sandbox_rejects_roster_mutations(
    client: AsyncClient, db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    matter.is_sandbox = True
    await db_session.flush()
    response = await client.post(
        f"/api/v1/projects/{matter.id}/members",
        headers=_bearer(owner),
        json={"user_id": str(colleague.id), "role": "reader"},
    )
    assert response.status_code == 400, response.text


async def test_shared_deletion_does_not_remove_storage(
    db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    from app.workers.user_deletion import _hard_delete_user

    db_session.add(
        ProjectMember(
            project_id=matter.id, user_id=colleague.id, added_by_user_id=owner.id, role="reader"
        )
    )
    await db_session.flush()
    with patch("app.workers.user_deletion.delete_object", new_callable=AsyncMock) as delete:
        with pytest.raises(Conflict):
            await _hard_delete_user(db_session, owner)
        delete.assert_not_called()
    assert await db_session.get(Project, matter.id) is not None


async def test_erasure_rollback_preserves_storage(db_session: AsyncSession, owner: User) -> None:
    from app.models.file import File
    from app.models.storage_deletion import StorageDeletion
    from app.workers.user_deletion import _hard_delete_user

    file = File(
        owner_id=owner.id,
        filename="retain.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        hash_sha256="0" * 64,
        storage_path="rollback-storage-key",
    )
    db_session.add(file)
    await db_session.flush()
    file_id = file.id
    with patch("app.workers.user_deletion.delete_object", new_callable=AsyncMock) as delete:
        nested = await db_session.begin_nested()
        await _hard_delete_user(db_session, owner)
        await db_session.flush()
        assert await db_session.get(StorageDeletion, "rollback-storage-key") is not None
        delete.assert_not_called()
        await nested.rollback()
        assert await db_session.get(File, file_id) is not None
        assert await db_session.get(StorageDeletion, "rollback-storage-key") is None


async def test_screen_follows_attached_files_and_kbs(
    client: AsyncClient, db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    from app.models.file import File
    from app.models.knowledge import KnowledgeBase
    from app.models.project import ProjectFile
    from app.models.project_knowledge_base import ProjectKnowledgeBase

    file = File(
        owner_id=colleague.id,
        filename="screened.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        hash_sha256="0" * 64,
        storage_path="screened-attached-file",
    )
    kb = KnowledgeBase(owner_id=colleague.id, name="Screened knowledge")
    db_session.add_all([file, kb])
    await db_session.flush()
    db_session.add_all(
        [
            ProjectFile(project_id=matter.id, file_id=file.id),
            ProjectKnowledgeBase(project_id=matter.id, knowledge_base_id=kb.id),
            ProjectMember(
                project_id=matter.id,
                user_id=colleague.id,
                added_by_user_id=owner.id,
                role="blocked",
            ),
        ]
    )
    await db_session.flush()
    assert (
        await client.get(f"/api/v1/files/{file.id}", headers=_bearer(colleague))
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/knowledge-bases/{kb.id}", headers=_bearer(colleague))
    ).status_code == 404
    listed = await client.get("/api/v1/knowledge-bases", headers=_bearer(colleague))
    assert str(kb.id) not in {row["id"] for row in listed.json()}


async def test_retrieval_cannot_reexpose_screened_attachment(
    db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    from app.knowledge.retrieval import hybrid_search
    from app.models.file import File
    from app.models.knowledge import KnowledgeBase
    from app.models.project import ProjectFile

    file = File(
        owner_id=colleague.id,
        filename="screened.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        hash_sha256="0" * 64,
        storage_path="screened-retrieval-file",
    )
    kb = KnowledgeBase(owner_id=colleague.id, name="Another KB")
    db_session.add_all([file, kb])
    await db_session.flush()
    db_session.add_all(
        [
            ProjectFile(project_id=matter.id, file_id=file.id),
            ProjectMember(
                project_id=matter.id,
                user_id=colleague.id,
                added_by_user_id=owner.id,
                role="blocked",
            ),
        ]
    )
    await db_session.flush()
    chunk_id = uuid.uuid4()
    row = {
        "chunk_id": chunk_id,
        "document_id": uuid.uuid4(),
        "file_id": file.id,
        "file_name": file.filename,
        "content": "Synthetic restricted matter content",
        "page_start": 1,
        "page_end": 1,
        "char_offset_start": 0,
        "char_offset_end": 35,
    }
    with (
        patch(
            "app.knowledge.retrieval._fts_candidates",
            new_callable=AsyncMock,
            return_value=[(chunk_id, 1.0)],
        ),
        patch(
            "app.knowledge.retrieval._hydrate_chunks", new_callable=AsyncMock, return_value=[row]
        ),
    ):
        result = await hybrid_search(
            db_session,
            kb_id=kb.id,
            user_id=colleague.id,
            query="matter",
            query_embedding=None,
            top_k=5,
            alpha=1,
        )
    assert result == []


@pytest.mark.parametrize("account_role", ["viewer", "auditor"])
async def test_membership_does_not_widen_readonly_account(
    client: AsyncClient, db_session: AsyncSession, owner: User, matter: Project, account_role: str
) -> None:
    reader = await _mk_user(db_session, role=account_role)
    db_session.add(
        ProjectMember(
            project_id=matter.id, user_id=reader.id, added_by_user_id=owner.id, role="lead"
        )
    )
    await db_session.flush()
    response = await client.get(f"/api/v1/projects/{matter.id}", headers=_bearer(reader))
    assert response.status_code == 200
    assert response.json()["caller_access"] == "read"
    response = await client.post(
        "/api/v1/chats",
        headers=_bearer(reader),
        json={"project_id": str(matter.id), "title": "Forbidden contribution"},
    )
    assert response.status_code == 403, response.text


async def test_owned_shared_resources_require_matter_write(
    client: AsyncClient, db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    from app.models.file import File
    from app.models.knowledge import KnowledgeBase

    file = File(
        owner_id=colleague.id,
        project_id=matter.id,
        filename="read-only.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        hash_sha256="0" * 64,
        storage_path="reader-owned-shared-file",
    )
    kb = KnowledgeBase(owner_id=colleague.id, project_id=matter.id, name="Read only KB")
    db_session.add_all(
        [
            file,
            kb,
            ProjectMember(
                project_id=matter.id, user_id=colleague.id, added_by_user_id=owner.id, role="reader"
            ),
        ]
    )
    await db_session.flush()
    assert (
        await client.delete(f"/api/v1/files/{file.id}", headers=_bearer(colleague))
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/knowledge-bases/{kb.id}",
            headers=_bearer(colleague),
            json={"name": "Forbidden rename"},
        )
    ).status_code == 403
