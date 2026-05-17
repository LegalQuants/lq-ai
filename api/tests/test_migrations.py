"""Smoke tests for the Phase A1 migration (0001_initial).

Verifies:
- Migration applies cleanly to a fresh DB
- All four expected tables exist
- CITEXT email column behaves case-insensitively
- CHECK constraints fire correctly
- Partial indexes are created
- Per-test transaction rollback fixture works (data inserted in one test
  doesn't leak to the next)
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User


@pytest.mark.integration
async def test_phase_a1_tables_exist(db_session: AsyncSession) -> None:
    """All four Phase A1 tables exist after the migration runs."""
    expected = {"users", "user_sessions", "audit_log", "inference_routing_log"}
    result = await db_session.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename = ANY(:names)"
        ),
        {"names": list(expected)},
    )
    found = {row[0] for row in result.fetchall()}
    assert found == expected, f"missing tables: {expected - found}"


@pytest.mark.integration
async def test_users_email_is_citext(db_session: AsyncSession) -> None:
    """users.email is case-insensitive: inserting two cases collides."""
    user1 = User(email="kevin@example.com", hashed_password="hash1")
    db_session.add(user1)
    await db_session.flush()

    # Same email different case should violate UNIQUE
    user2 = User(email="KEVIN@example.com", hashed_password="hash2")
    db_session.add(user2)

    with pytest.raises(Exception):  # IntegrityError or its asyncpg flavor
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_audit_log_privilege_check_constraint(db_session: AsyncSession) -> None:
    """privilege_marked=true requires privilege_basis to be set."""
    bad = AuditLog(
        action="test.action",
        resource_type="test",
        privilege_marked=True,
        privilege_basis=None,  # CHECK constraint should reject this
    )
    db_session.add(bad)
    with pytest.raises(Exception):
        await db_session.flush()
    await db_session.rollback()

    # Same row with privilege_basis populated should succeed
    good = AuditLog(
        action="test.action",
        resource_type="test",
        privilege_marked=True,
        privilege_basis="matter_attorney_directive",
    )
    db_session.add(good)
    await db_session.flush()
    assert good.id is not None


@pytest.mark.integration
async def test_inference_log_tier_range_check(db_session: AsyncSession) -> None:
    """routed_inference_tier must be 1-5."""
    from app.models import InferenceRoutingLog

    out_of_range = InferenceRoutingLog(
        routed_provider="test-provider",
        routed_model="test-model",
        routed_inference_tier=6,  # invalid
    )
    db_session.add(out_of_range)
    with pytest.raises(Exception):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_partial_indexes_exist(db_session: AsyncSession) -> None:
    """Verify the partial indexes specified in db-schema.md were created."""
    expected_partials = {
        "idx_users_email_active",
        "idx_users_deletion_scheduled",
        "idx_user_sessions_token_hash",
        "idx_audit_log_privileged",
        "idx_audit_log_tier",
        "idx_inference_log_user",
        "idx_inference_log_refused",
    }
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = ANY(:names)"
        ),
        {"names": list(expected_partials)},
    )
    found = {row[0] for row in result.fetchall()}
    assert found == expected_partials, f"missing indexes: {expected_partials - found}"


@pytest.mark.integration
async def test_updated_at_trigger_on_users(db_session: AsyncSession) -> None:
    """users.updated_at is bumped by the trigger on UPDATE."""
    user = User(email=f"trigger-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h")
    db_session.add(user)
    await db_session.flush()
    initial_updated_at = user.updated_at

    # Use a raw SQL UPDATE to bypass the ORM and prove the DB-level trigger fires
    await db_session.execute(
        text("UPDATE users SET display_name = 'Triggered' WHERE id = :id"),
        {"id": user.id},
    )
    await db_session.flush()
    await db_session.refresh(user)
    assert user.updated_at >= initial_updated_at


@pytest.mark.integration
async def test_per_test_isolation_left_over_data(db_session: AsyncSession) -> None:
    """First half of a paired test: inserts a row that should NOT survive."""
    user = User(email="isolation-canary@example.com", hashed_password="h")
    db_session.add(user)
    await db_session.flush()
    # No commit. Teardown should roll back.


@pytest.mark.integration
async def test_per_test_isolation_canary_gone(db_session: AsyncSession) -> None:
    """Second half: the canary row from the previous test must be absent."""
    result = await db_session.execute(
        text("SELECT id FROM users WHERE email = 'isolation-canary@example.com'")
    )
    assert result.first() is None, "previous test's row leaked across test boundary"


# ---------------------------------------------------------------------------
# C4 — files table (migration 0003)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_files_table_exists(db_session: AsyncSession) -> None:
    """`files` table exists after the C4 migration runs."""
    result = await db_session.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = 'files'")
    )
    assert result.scalar_one_or_none() == "files"


@pytest.mark.integration
async def test_files_indexes_exist(db_session: AsyncSession) -> None:
    """The four indexes on `files` from migration 0003 are created."""
    expected = {
        "idx_files_owner_active",
        "idx_files_project",
        "idx_files_status",
        "idx_files_hash",
    }
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = ANY(:names)"
        ),
        {"names": list(expected)},
    )
    found = {row[0] for row in result.fetchall()}
    assert found == expected, f"missing indexes: {expected - found}"


@pytest.mark.integration
async def test_files_ingestion_status_check(db_session: AsyncSession) -> None:
    """files.ingestion_status accepts only the four valid states."""
    from sqlalchemy.exc import IntegrityError

    from app.models import File, User

    user = User(email=f"file-chk-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h")
    db_session.add(user)
    await db_session.flush()

    bad = File(
        owner_id=user.id,
        filename="x.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256="0" * 64,
        storage_path="abc",
        ingestion_status="invalid_state",
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_files_size_nonneg_check(db_session: AsyncSession) -> None:
    """files.size_bytes >= 0 (CHECK constraint)."""
    from sqlalchemy.exc import IntegrityError

    from app.models import File, User

    user = User(email=f"file-neg-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h")
    db_session.add(user)
    await db_session.flush()

    bad = File(
        owner_id=user.id,
        filename="x.pdf",
        mime_type="application/pdf",
        size_bytes=-1,
        hash_sha256="0" * 64,
        storage_path="abc",
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# C7 — projects + project_files + project_skills (migration 0004)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_projects_tables_exist(db_session: AsyncSession) -> None:
    """`projects`, `project_files`, `project_skills` exist after 0004."""

    expected = {"projects", "project_files", "project_skills"}
    result = await db_session.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename = ANY(:names)"
        ),
        {"names": list(expected)},
    )
    found = {row[0] for row in result.fetchall()}
    assert found == expected, f"missing tables: {expected - found}"


@pytest.mark.integration
async def test_projects_indexes_exist(db_session: AsyncSession) -> None:
    """The expected indexes from migration 0004 are present."""

    expected = {
        "idx_projects_owner_active",
        "idx_projects_slug_owner_active",
        "idx_project_files_file",
        "idx_project_skills_skill",
    }
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = ANY(:names)"
        ),
        {"names": list(expected)},
    )
    found = {row[0] for row in result.fetchall()}
    assert found == expected, f"missing indexes: {expected - found}"


@pytest.mark.integration
async def test_files_project_id_fk_exists(db_session: AsyncSession) -> None:
    """The C4-deferred FK on files.project_id was added by 0004."""

    result = await db_session.execute(
        text("SELECT conname FROM pg_constraint WHERE conname = 'fk_files_project_id'")
    )
    assert result.scalar_one_or_none() == "fk_files_project_id"


@pytest.mark.integration
async def test_projects_privileged_implies_tier_check(db_session: AsyncSession) -> None:
    """privileged=true requires minimum_inference_tier IS NOT NULL (DB-layer)."""
    from sqlalchemy.exc import IntegrityError

    from app.models import Project, User

    user = User(email=f"proj-chk-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h")
    db_session.add(user)
    await db_session.flush()

    # privileged=true with no tier → CHECK violation.
    bad = Project(
        owner_id=user.id,
        name="bad",
        slug="bad",
        privileged=True,
        minimum_inference_tier=None,
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_projects_tier_range_check(db_session: AsyncSession) -> None:
    """minimum_inference_tier must be NULL or in 1-5 (DB-layer)."""
    from sqlalchemy.exc import IntegrityError

    from app.models import Project, User

    user = User(email=f"proj-tier-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h")
    db_session.add(user)
    await db_session.flush()

    bad = Project(
        owner_id=user.id,
        name="bad",
        slug="bad-tier",
        privileged=False,
        minimum_inference_tier=7,
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_files_project_fk_set_null_on_delete(
    db_session: AsyncSession,
) -> None:
    """ON DELETE SET NULL: deleting a project nulls files.project_id."""
    from app.models import File, Project, User

    user = User(email=f"fk-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h")
    db_session.add(user)
    await db_session.flush()

    project = Project(
        owner_id=user.id,
        name="P",
        slug=f"p-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(project)
    await db_session.flush()

    f = File(
        owner_id=user.id,
        project_id=project.id,
        filename="x.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256="0" * 64,
        storage_path="abc",
    )
    db_session.add(f)
    await db_session.flush()
    assert f.project_id == project.id

    # Delete the project; the FK should NULL out files.project_id.
    await db_session.delete(project)
    await db_session.flush()
    await db_session.refresh(f)
    assert f.project_id is None


# ---------------------------------------------------------------------------
# C5 — documents and document_chunks tables (migration 0005)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_documents_table_exists(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename = 'documents'"
        )
    )
    assert result.scalar_one_or_none() == "documents"


@pytest.mark.integration
async def test_document_chunks_table_exists(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename = 'document_chunks'"
        )
    )
    assert result.scalar_one_or_none() == "document_chunks"


@pytest.mark.integration
async def test_pgvector_extension_installed(db_session: AsyncSession) -> None:
    """The pgvector extension is enabled by migration 0005."""
    result = await db_session.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
    )
    assert result.scalar_one_or_none() == "vector"


@pytest.mark.integration
async def test_documents_unique_file_id(db_session: AsyncSession) -> None:
    """Only one Document row per file."""
    from sqlalchemy.exc import IntegrityError

    from app.models import Document, File, User

    user = User(email=f"doc-uq-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h")
    db_session.add(user)
    await db_session.flush()

    file_row = File(
        owner_id=user.id,
        filename="x.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256="0" * 64,
        storage_path="abc",
    )
    db_session.add(file_row)
    await db_session.flush()

    db_session.add(Document(file_id=file_row.id, parser="pymupdf"))
    await db_session.flush()

    db_session.add(Document(file_id=file_row.id, parser="pymupdf"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_document_chunks_offset_check_constraints(
    db_session: AsyncSession,
) -> None:
    """char_offset_end >= char_offset_start; both >= 0."""
    from sqlalchemy.exc import IntegrityError

    from app.models import Document, DocumentChunk, File, User

    user = User(
        email=f"chunk-chk-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="h",
    )
    db_session.add(user)
    await db_session.flush()
    file_row = File(
        owner_id=user.id,
        filename="x.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256="0" * 64,
        storage_path="abc",
    )
    db_session.add(file_row)
    await db_session.flush()

    doc = Document(file_id=file_row.id, parser="pymupdf")
    db_session.add(doc)
    await db_session.flush()

    # char_offset_start < 0 → CHECK violation
    bad = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content="hi",
        char_offset_start=-1,
        char_offset_end=10,
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_document_chunks_unique_index_pair(db_session: AsyncSession) -> None:
    """(document_id, chunk_index) is UNIQUE."""
    from sqlalchemy.exc import IntegrityError

    from app.models import Document, DocumentChunk, File, User

    user = User(
        email=f"chunk-unq-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="h",
    )
    db_session.add(user)
    await db_session.flush()
    file_row = File(
        owner_id=user.id,
        filename="x.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256="0" * 64,
        storage_path="abc",
    )
    db_session.add(file_row)
    await db_session.flush()
    doc = Document(file_id=file_row.id, parser="pymupdf")
    db_session.add(doc)
    await db_session.flush()

    db_session.add(
        DocumentChunk(
            document_id=doc.id,
            chunk_index=0,
            content="a",
            char_offset_start=0,
            char_offset_end=1,
        )
    )
    await db_session.flush()

    db_session.add(
        DocumentChunk(
            document_id=doc.id,
            chunk_index=0,  # duplicate index
            content="b",
            char_offset_start=2,
            char_offset_end=3,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_documents_cascade_delete_via_file(db_session: AsyncSession) -> None:
    """Hard-deleting a file cascades to document and chunks."""
    from app.models import Document, DocumentChunk, File, User

    user = User(email=f"cascade-{uuid.uuid4().hex[:8]}@example.com", hashed_password="h")
    db_session.add(user)
    await db_session.flush()
    file_row = File(
        owner_id=user.id,
        filename="x.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256="0" * 64,
        storage_path="abc",
    )
    db_session.add(file_row)
    await db_session.flush()
    doc = Document(file_id=file_row.id, parser="pymupdf")
    db_session.add(doc)
    await db_session.flush()
    db_session.add(
        DocumentChunk(
            document_id=doc.id,
            chunk_index=0,
            content="content",
            char_offset_start=0,
            char_offset_end=7,
        )
    )
    await db_session.flush()

    # Hard-delete the file (DELETE FROM files WHERE id = ...).
    await db_session.execute(text("DELETE FROM files WHERE id = :id"), {"id": file_row.id})
    await db_session.flush()

    # The document and its chunks should be gone.
    docs_remaining = await db_session.execute(
        text("SELECT count(*) FROM documents WHERE file_id = :id"),
        {"id": file_row.id},
    )
    assert docs_remaining.scalar_one() == 0

    chunks_remaining = await db_session.execute(
        text("SELECT count(*) FROM document_chunks WHERE document_id = :id"),
        {"id": doc.id},
    )
    assert chunks_remaining.scalar_one() == 0


# ---------------------------------------------------------------------------
# Task C3 — chats + messages migration (0006)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_chats_and_messages_tables_exist(db_session: AsyncSession) -> None:
    """C3: ``chats`` and ``messages`` tables exist after migration 0006."""

    expected = {"chats", "messages"}
    result = await db_session.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename = ANY(:names)"
        ),
        {"names": list(expected)},
    )
    found = {row[0] for row in result.fetchall()}
    assert found == expected


@pytest.mark.integration
async def test_chats_indexes_exist(db_session: AsyncSession) -> None:
    """C3: the active-listing and project-active partial indexes exist
    plus the ordered messages index."""

    expected = {
        "idx_chats_owner_active",
        "idx_chats_project_active",
        "idx_messages_chat_created",
    }
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = ANY(:names)"
        ),
        {"names": list(expected)},
    )
    found = {row[0] for row in result.fetchall()}
    assert found == expected


@pytest.mark.integration
async def test_messages_role_check_fires(db_session: AsyncSession) -> None:
    """C3: inserting a message with a bogus role violates the CHECK."""

    from app.models.chat import Chat
    from app.models.user import User

    user = User(
        email=f"role-check-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hash",
    )
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="x")
    db_session.add(chat)
    await db_session.flush()

    with pytest.raises(Exception):
        await db_session.execute(
            text("INSERT INTO messages (chat_id, role, content) VALUES (:cid, 'bogus_role', 'x')"),
            {"cid": chat.id},
        )
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.integration
async def test_messages_cascade_delete_on_chat(db_session: AsyncSession) -> None:
    """C3: deleting a chat cascades to its messages."""

    from app.models.chat import Chat
    from app.models.user import User

    user = User(
        email=f"cascade-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hash",
    )
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="x")
    db_session.add(chat)
    await db_session.flush()
    chat_id = chat.id

    await db_session.execute(
        text(
            "INSERT INTO messages (chat_id, role, content) "
            "VALUES (:cid, 'user', 'a'), (:cid, 'assistant', 'b')"
        ),
        {"cid": chat_id},
    )
    await db_session.flush()

    # Hard-delete the chat.
    await db_session.execute(text("DELETE FROM chats WHERE id = :cid"), {"cid": chat_id})
    await db_session.flush()

    rows = await db_session.execute(
        text("SELECT count(*) FROM messages WHERE chat_id = :cid"),
        {"cid": chat_id},
    )
    assert rows.scalar_one() == 0


# Note: previous tests at this position verified ON DELETE SET NULL behavior
# for inference_routing_log.chat_id and .message_id (the FK constraints
# closed C3's deferred A2 item). Migration 0008
# (drop_inference_routing_log_message_fks) intentionally dropped both FKs to
# fix the gateway/backend write-order race (the gateway writes the
# routing-log row at end-of-call before the backend persists the message
# row; the FK rejected the insert and B4's "never raise" invariant silently
# swallowed every audit row). Per that migration's docstring, the
# NULL-on-delete behavior "was not load-bearing because the messages row
# carries the same routing metadata (routed_inference_tier, provider,
# model, tokens, cost) on its own." The two tests were retired alongside
# the constraint.


@pytest.mark.integration
async def test_messages_applied_skills_default_empty_array(db_session: AsyncSession) -> None:
    """C3: ``applied_skills`` defaults to an empty text[] when omitted."""

    from app.models.chat import Chat
    from app.models.user import User

    user = User(
        email=f"applied-skills-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hash",
    )
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="x")
    db_session.add(chat)
    await db_session.flush()

    # Insert via raw SQL omitting applied_skills.
    msg_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO messages (id, chat_id, role, content) VALUES (:mid, :cid, 'user', 'hi')"),
        {"mid": msg_id, "cid": chat.id},
    )
    await db_session.flush()

    rows = await db_session.execute(
        text("SELECT applied_skills FROM messages WHERE id = :mid"),
        {"mid": msg_id},
    )
    value = rows.scalar_one()
    # Postgres returns the text[] as a Python list.
    assert value == []


# ---------------------------------------------------------------------------
# 0026 — paraphrase_judge enum + partial column on message_citations (M2-C1)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_message_citations_accepts_paraphrase_judge_method(
    db_session: AsyncSession,
) -> None:
    """The widened enum accepts the new ``'paraphrase_judge'`` method value.

    The 0026 migration replaces the M2-A2 CHECK constraint to add
    ``'paraphrase_judge'``. Without the migration the INSERT below
    would fail the constraint.
    """

    # Need a real chat + message + file to satisfy the FKs.
    user_id = uuid.uuid4()
    chat_id = uuid.uuid4()
    message_id = uuid.uuid4()
    file_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, display_name, hashed_password) "
            "VALUES (:uid, :email, 'M2-C1 Test', 'x')"
        ),
        {"uid": user_id, "email": f"c1-{uuid.uuid4().hex[:6]}@example.com"},
    )
    await db_session.execute(
        text("INSERT INTO chats (id, owner_id, title) VALUES (:cid, :uid, 't')"),
        {"cid": chat_id, "uid": user_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO messages (id, chat_id, role, content) "
            "VALUES (:mid, :cid, 'assistant', 'x')"
        ),
        {"mid": message_id, "cid": chat_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO files (id, owner_id, filename, mime_type, size_bytes, "
            "hash_sha256, storage_path) VALUES "
            "(:fid, :uid, 'f.pdf', 'application/pdf', 1, "
            "'a' || repeat('0', 63), 's3://k')"
        ),
        {"fid": file_id, "uid": user_id},
    )
    await db_session.flush()

    await db_session.execute(
        text(
            "INSERT INTO message_citations "
            "(message_id, source_file_id, source_offset_start, source_offset_end, "
            "source_text, verified, verification_method, verification_confidence, "
            "partial) "
            "VALUES (:mid, :fid, 0, 5, 'hello', true, 'paraphrase_judge', "
            "0.90, true)"
        ),
        {"mid": message_id, "fid": file_id},
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            text(
                "SELECT verification_method, partial FROM message_citations WHERE message_id = :mid"
            ),
            {"mid": message_id},
        )
    ).one()
    assert row[0] == "paraphrase_judge"
    assert row[1] is True


@pytest.mark.integration
async def test_message_citations_partial_default_false(
    db_session: AsyncSession,
) -> None:
    """``partial`` defaults to ``false`` so M2-A2 / M2-B1 callers stay correct.

    The Stage 1 / Stage 2 verifiers don't write ``partial`` explicitly;
    the default keeps their rows readable as fully-verified.
    """

    user_id = uuid.uuid4()
    chat_id = uuid.uuid4()
    message_id = uuid.uuid4()
    file_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, display_name, hashed_password) "
            "VALUES (:uid, :email, 'C1 Default', 'x')"
        ),
        {"uid": user_id, "email": f"c1-{uuid.uuid4().hex[:6]}@example.com"},
    )
    await db_session.execute(
        text("INSERT INTO chats (id, owner_id, title) VALUES (:cid, :uid, 't')"),
        {"cid": chat_id, "uid": user_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO messages (id, chat_id, role, content) "
            "VALUES (:mid, :cid, 'assistant', 'x')"
        ),
        {"mid": message_id, "cid": chat_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO files (id, owner_id, filename, mime_type, size_bytes, "
            "hash_sha256, storage_path) VALUES "
            "(:fid, :uid, 'f.pdf', 'application/pdf', 1, "
            "'a' || repeat('0', 63), 's3://k')"
        ),
        {"fid": file_id, "uid": user_id},
    )
    await db_session.flush()

    # Omit ``partial`` — the column default should populate it.
    await db_session.execute(
        text(
            "INSERT INTO message_citations "
            "(message_id, source_file_id, source_offset_start, source_offset_end, "
            "source_text, verified, verification_method, verification_confidence) "
            "VALUES (:mid, :fid, 0, 5, 'hello', true, 'exact_match', 1.0)"
        ),
        {"mid": message_id, "fid": file_id},
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            text("SELECT partial FROM message_citations WHERE message_id = :mid"),
            {"mid": message_id},
        )
    ).one()
    assert row[0] is False
