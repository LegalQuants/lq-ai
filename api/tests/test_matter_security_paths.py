"""Adversarial checks against PR 719; safe assertions should pass before merge.

Run from api/ with -c pyproject.toml -p tests.conftest against a disposable DB.
All data is synthetic. Queue dispatch and object downloads are mocked.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import get_gateway_client
from app.errors import Conflict
from app.main import app
from app.models.autonomous import AutonomousMemory, AutonomousSession
from app.models.chat import Chat, Message
from app.models.file import File
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.project import Project
from app.models.project_knowledge_base import ProjectKnowledgeBase
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
from tests.test_tabular_endpoints import _make_doc_with_chunk


async def screen(db: AsyncSession, matter: Project, owner: User, caller: User) -> None:
    db.add(
        ProjectMember(
            project_id=matter.id, user_id=caller.id, added_by_user_id=owner.id, role="blocked"
        )
    )
    await db.flush()


@pytest.mark.parametrize("screened", [False, True])
async def test_override_rejects_admin_without_matter_access(
    client: AsyncClient, db_session: AsyncSession, owner: User, matter: Project, screened: bool
) -> None:
    admin = await _mk_user(db_session, is_admin=True, role="admin")
    chat = Chat(owner_id=owner.id, project_id=matter.id, title="Synthetic refused exchange")
    db_session.add(chat)
    await db_session.flush()
    now = datetime.now(UTC)
    prompt = Message(
        chat_id=chat.id,
        role="user",
        kind="user",
        content="Synthetic confidential settlement ceiling",
        created_at=now - timedelta(seconds=10),
    )
    refusal = Message(
        chat_id=chat.id,
        role="assistant",
        kind="refusal",
        content="Synthetic refusal",
        created_at=now,
    )
    db_session.add_all([prompt, refusal])
    await db_session.flush()
    if screened:
        await screen(db_session, matter, owner, admin)
    direct = await client.get(f"/api/v1/chats/{chat.id}", headers=_bearer(admin))
    assert direct.status_code == 404
    gateway = SimpleNamespace(
        chat_completion=AsyncMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=prompt.content))],
                lq_ai_applied_skills=[],
                routed_provider="synthetic",
                model="synthetic",
                routed_inference_tier=4,
                usage=None,
                cost_estimate=None,
            )
        )
    )
    app.dependency_overrides[get_gateway_client] = lambda: gateway
    try:
        response = await client.post(
            "/api/v1/inference/override-tier-floor",
            headers=_bearer(admin),
            json={"message_id": str(refusal.id), "reason": "Synthetic security review request"},
        )
    finally:
        app.dependency_overrides.pop(get_gateway_client, None)
    assert response.status_code == 404, response.text
    gateway.chat_completion.assert_not_called()


@pytest.mark.parametrize("admin,screened", [(False, True), (True, True), (True, False)])
async def test_tabular_rejects_screened_document(
    client: AsyncClient,
    db_session: AsyncSession,
    owner: User,
    matter: Project,
    admin: bool,
    screened: bool,
) -> None:
    caller = await _mk_user(db_session, is_admin=admin, role="admin" if admin else "member")
    doc, _ = await _make_doc_with_chunk(
        db_session,
        owner=caller if screened else owner,
        content="Synthetic confidential matter text",
        page_start=1,
    )
    file = await db_session.get(File, doc.file_id)
    assert file is not None
    file.project_id = matter.id
    if screened:
        await screen(db_session, matter, owner, caller)
    else:
        await db_session.flush()
        denied = await client.get(f"/api/v1/projects/{matter.id}", headers=_bearer(caller))
        assert denied.status_code == 404
    direct = await client.get(f"/api/v1/files/{file.id}", headers=_bearer(caller))
    assert direct.status_code == 404
    with patch("app.api.tabular.enqueue_tabular_execution_job", new=AsyncMock(return_value=True)):
        response = await client.post(
            "/api/v1/tabular/execute",
            headers=_bearer(caller),
            json={
                "document_ids": [str(doc.id)],
                "columns": [{"name": "Secret", "query": "Extract the text"}],
            },
        )
    assert response.status_code == 404, response.text


async def test_screen_hides_session_memory(
    client: AsyncClient, db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    session = AutonomousSession(
        user_id=colleague.id, project_id=matter.id, trigger_kind="manual", status="completed"
    )
    db_session.add(session)
    await db_session.flush()
    memory = AutonomousMemory(
        user_id=colleague.id,
        state="kept",
        category="matter_fact",
        content="Synthetic confidential settlement ceiling",
        source_session_id=session.id,
    )
    db_session.add(memory)
    await screen(db_session, matter, owner, colleague)
    session_response = await client.get(
        f"/api/v1/autonomous/sessions/{session.id}", headers=_bearer(colleague)
    )
    assert session_response.status_code == 404
    response = await client.get("/api/v1/autonomous/memory", headers=_bearer(colleague))
    assert response.status_code == 200, response.text
    assert str(memory.id) not in {entry["id"] for entry in response.json()["entries"]}, (
        response.text
    )


async def test_screen_follows_kb_membership_to_file(
    client: AsyncClient, db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    file = File(
        owner_id=colleague.id,
        filename="synthetic-secret.pdf",
        mime_type="application/pdf",
        size_bytes=6,
        hash_sha256="1" * 64,
        storage_path="synthetic-review-source",
    )
    kb = KnowledgeBase(owner_id=colleague.id, name="Synthetic matter KB")
    db_session.add_all([file, kb])
    await db_session.flush()
    db_session.add_all(
        [
            KnowledgeBaseFile(kb_id=kb.id, file_id=file.id),
            ProjectKnowledgeBase(project_id=matter.id, knowledge_base_id=kb.id),
        ]
    )
    await screen(db_session, matter, owner, colleague)
    kb_response = await client.get(f"/api/v1/knowledge-bases/{kb.id}", headers=_bearer(colleague))
    assert kb_response.status_code == 404

    @asynccontextmanager
    async def fake_download(**kwargs: Any) -> AsyncIterator[AsyncIterator[bytes]]:
        async def chunks() -> AsyncIterator[bytes]:
            yield b"SECRET"

        yield chunks()

    with patch("app.api.files.stream_download", new=fake_download):
        response = await client.get(f"/api/v1/files/{file.id}/content", headers=_bearer(colleague))
    assert response.status_code == 404, response.content


async def test_erasure_preserves_file_in_retained_kb(
    client: AsyncClient, db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    from app.models.storage_deletion import StorageDeletion
    from app.workers.user_deletion import _hard_delete_user

    file = File(
        owner_id=owner.id,
        filename="retained-source.pdf",
        mime_type="application/pdf",
        size_bytes=6,
        hash_sha256="2" * 64,
        storage_path="synthetic-retained-source",
    )
    kb = KnowledgeBase(owner_id=owner.id, name="Retained matter KB", project_id=matter.id)
    db_session.add_all([file, kb])
    await db_session.flush()
    db_session.add(KnowledgeBaseFile(kb_id=kb.id, file_id=file.id))
    await db_session.flush()
    admin = await _mk_user(db_session, is_admin=True, role="admin")
    transferred = await client.post(
        f"/api/v1/admin/matters/{matter.id}/transfer",
        headers=_bearer(admin),
        json={
            "owner_id": str(colleague.id),
            "former_owner_role": "reader",
            "reason": "Synthetic review custody transfer",
        },
    )
    assert transferred.status_code == 200, transferred.text
    await db_session.refresh(kb)
    await db_session.refresh(file)
    assert kb.owner_id == colleague.id
    assert file.owner_id == owner.id
    with pytest.raises(Conflict):
        await _hard_delete_user(db_session, owner)
    await db_session.flush()
    retained_file = await db_session.scalar(select(File.id).where(File.id == file.id))
    queued = await db_session.get(StorageDeletion, "synthetic-retained-source")
    assert retained_file is not None
    assert queued is None


@pytest.mark.parametrize("role", ["blocked", "reader"])
async def test_worker_rechecks_scope_before_each_dispatch(
    db_session: AsyncSession, owner: User, colleague: User, matter: Project, role: str
) -> None:
    from app.authz.documents import DocumentWorkflowGateway
    from app.clients.gateway import GatewayClient
    from app.errors import Forbidden, NotFound
    from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest

    doc, _ = await _make_doc_with_chunk(
        db_session, owner=colleague, content="Synthetic private excerpt", page_start=1
    )
    file = await db_session.get(File, doc.file_id)
    assert file is not None
    file.project_id = matter.id
    grant = ProjectMember(
        project_id=matter.id, user_id=colleague.id, added_by_user_id=owner.id, role="contributor"
    )
    db_session.add(grant)
    await db_session.flush()
    gateway = AsyncMock(spec=GatewayClient)
    guarded = DocumentWorkflowGateway(gateway, db_session, colleague.id, [doc.id])
    request = ChatCompletionRequest(
        model="smart",
        messages=[ChatCompletionMessage(role="user", content="Synthetic private excerpt")],
    )
    await guarded.chat_completion(request)
    gateway.chat_completion.assert_awaited_once()
    grant.role = role
    await db_session.flush()
    with pytest.raises(NotFound if role == "blocked" else Forbidden):
        await guarded.chat_completion(request)
    gateway.chat_completion.assert_awaited_once()


async def test_worker_admission_refuses_queued_screened_work(
    db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    from app.clients.gateway import GatewayClient
    from app.models.tabular import TabularExecution
    from app.tabular.executor import run_tabular_execution

    doc, _ = await _make_doc_with_chunk(
        db_session, owner=colleague, content="Synthetic restricted excerpt", page_start=1
    )
    file = await db_session.get(File, doc.file_id)
    assert file is not None
    file.project_id = matter.id
    execution = TabularExecution(
        user_id=colleague.id,
        document_ids=[doc.id],
        columns=[{"name": "Term", "query": "Extract a term"}],
        status="pending",
    )
    db_session.add(execution)
    await screen(db_session, matter, owner, colleague)
    gateway = AsyncMock(spec=GatewayClient)
    await run_tabular_execution(db_session, execution_id=execution.id, gateway=gateway)
    await db_session.refresh(execution)
    assert execution.status == "failed"
    gateway.chat_completion.assert_not_called()


@pytest.mark.parametrize("direct_scope", [False, True])
async def test_screened_kb_source_cannot_reappear_in_another_kb(
    db_session: AsyncSession, owner: User, colleague: User, matter: Project, direct_scope: bool
) -> None:
    from app.knowledge.retrieval import hybrid_search

    doc, _ = await _make_doc_with_chunk(
        db_session, owner=colleague, content="Synthetic confidential settlement", page_start=1
    )
    kb = KnowledgeBase(
        owner_id=colleague.id, name="Matter source", project_id=matter.id if direct_scope else None
    )
    other = KnowledgeBase(owner_id=colleague.id, name="Other source")
    db_session.add_all([kb, other])
    await db_session.flush()
    db_session.add_all(
        [
            KnowledgeBaseFile(kb_id=kb.id, file_id=doc.file_id),
            KnowledgeBaseFile(kb_id=other.id, file_id=doc.file_id),
        ]
    )
    if not direct_scope:
        db_session.add(ProjectKnowledgeBase(project_id=matter.id, knowledge_base_id=kb.id))
    await db_session.flush()
    visible = await hybrid_search(
        db_session,
        kb_id=other.id,
        user_id=colleague.id,
        query="confidential",
        query_embedding=None,
        top_k=5,
        alpha=1.0,
    )
    assert visible
    await screen(db_session, matter, owner, colleague)
    assert not await hybrid_search(
        db_session,
        kb_id=other.id,
        user_id=colleague.id,
        query="confidential",
        query_embedding=None,
        top_k=5,
        alpha=1.0,
    )


async def test_reader_cannot_delete_a_retained_kb_source(
    client: AsyncClient, db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    file = File(
        owner_id=colleague.id,
        filename="retained.pdf",
        mime_type="application/pdf",
        size_bytes=6,
        hash_sha256="3" * 64,
        storage_path="synthetic-retained-reader",
    )
    kb = KnowledgeBase(owner_id=colleague.id, name="Matter KB", project_id=matter.id)
    db_session.add_all([file, kb])
    await db_session.flush()
    db_session.add_all(
        [
            KnowledgeBaseFile(kb_id=kb.id, file_id=file.id),
            ProjectMember(
                project_id=matter.id, user_id=colleague.id, role="reader", added_by_user_id=owner.id
            ),
        ]
    )
    await db_session.flush()
    response = await client.delete(f"/api/v1/files/{file.id}", headers=_bearer(colleague))
    assert response.status_code == 403, response.text
    await db_session.refresh(file)
    assert file.deleted_at is None


async def test_screen_blocks_memory_mutations_and_prompt_loading(
    client: AsyncClient, db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    from app.autonomous.memory import load_kept_memory

    colleague.autonomous_enabled = True
    session = AutonomousSession(
        user_id=colleague.id, project_id=matter.id, trigger_kind="manual", status="completed"
    )
    db_session.add(session)
    await db_session.flush()
    memory = AutonomousMemory(
        user_id=colleague.id,
        state="kept",
        category="matter_fact",
        content="Synthetic private note",
        source_session_id=session.id,
    )
    db_session.add(memory)
    await screen(db_session, matter, owner, colleague)
    for suffix in ["keep", "dismiss"]:
        response = await client.post(
            f"/api/v1/autonomous/memory/{memory.id}/{suffix}", headers=_bearer(colleague)
        )
        assert response.status_code == 404
    response = await client.delete(
        f"/api/v1/autonomous/memory/{memory.id}", headers=_bearer(colleague)
    )
    assert response.status_code == 404
    assert not await load_kept_memory(db_session, colleague.id)


async def test_playbook_worker_checks_explicit_matter_with_unscoped_source(
    client: AsyncClient, db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    from app.clients.gateway import GatewayClient
    from app.models.playbook import Playbook, PlaybookExecution
    from app.playbooks.executor import run_playbook_execution

    doc, _ = await _make_doc_with_chunk(
        db_session, owner=colleague, content="Synthetic agreement", page_start=1
    )
    playbook = Playbook(name="Synthetic review", contract_type="NDA", created_by=colleague.id)
    db_session.add(playbook)
    await db_session.flush()
    execution = PlaybookExecution(
        playbook_id=playbook.id,
        target_document_id=doc.id,
        user_id=colleague.id,
        project_id=matter.id,
        status="pending",
    )
    db_session.add(execution)
    await screen(db_session, matter, owner, colleague)
    response = await client.get(
        f"/api/v1/playbook-executions/{execution.id}", headers=_bearer(colleague)
    )
    assert response.status_code == 404
    gateway = AsyncMock(spec=GatewayClient)
    await run_playbook_execution(db_session, execution_id=execution.id, gateway=gateway)
    await db_session.refresh(execution)
    assert execution.status == "error"
    gateway.chat_completion.assert_not_called()


async def test_autonomous_sources_require_direct_matter_grant(
    db_session: AsyncSession, owner: User, colleague: User, matter: Project
) -> None:
    from app.autonomous.guard import _assert_file_owned, _assert_kb_owned

    file = File(
        owner_id=colleague.id,
        project_id=matter.id,
        filename="scoped.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        hash_sha256="4" * 64,
        storage_path="synthetic-scoped-source",
    )
    kb = KnowledgeBase(owner_id=colleague.id, project_id=matter.id, name="Scoped source")
    db_session.add_all([file, kb])
    await db_session.flush()
    with pytest.raises(ValueError):
        await _assert_file_owned(db_session, file.id, colleague.id)
    with pytest.raises(ValueError):
        await _assert_kb_owned(db_session, kb.id, colleague.id)
    db_session.add(
        ProjectMember(
            project_id=matter.id, user_id=colleague.id, added_by_user_id=owner.id, role="reader"
        )
    )
    await db_session.flush()
    await _assert_file_owned(db_session, file.id, colleague.id)
    await _assert_kb_owned(db_session, kb.id, colleague.id)


async def test_worker_refuses_missing_actor_before_dispatch(db_session: AsyncSession) -> None:
    import uuid

    from app.authz.documents import DocumentWorkflowGateway
    from app.clients.gateway import GatewayClient
    from app.errors import NotFound
    from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest

    gateway = AsyncMock(spec=GatewayClient)
    guarded = DocumentWorkflowGateway(gateway, db_session, uuid.uuid4(), [])
    request = ChatCompletionRequest(
        model="smart",
        messages=[ChatCompletionMessage(role="user", content="Synthetic cached text")],
    )
    with pytest.raises(NotFound):
        await guarded.chat_completion(request)
    gateway.chat_completion.assert_not_called()
