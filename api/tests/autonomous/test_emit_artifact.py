"""Chokepoint tests for the ``emit_artifact`` handler — Donna ask #8, Task 2.

The ``emit_artifact`` chokepoint persists a run's document-grade artifact
into the target KB as a REAL document: upload-first to object storage,
then File + Document + chunks + direct KB attach + an
``autonomous_artifacts`` reference. Covers:

- Happy path: all five write surfaces (object storage, files, documents/
  document_chunks, knowledge_base_files, autonomous_artifacts) plus the
  returned data keys and zero cost.
- Honest skips: no target KB / empty content → no rows, no upload.
- Storage failure: ``storage_error`` outcome with NO DB rows (the
  gateway_error honesty pattern).
- Name sanitization (path-traversal name) and content truncation
  (``_ARTIFACT_MAX_CHARS`` clamp).
- R6: emit_artifact is drafting-only — any other phase raises
  ToolNotGranted.
- Mode-3 retrieval echo exclusion: a schedule's "files attached since
  last run" fetch must NOT return a prior run's own memo.
- Watch-loop guard: the direct KB attach bypasses fire_watches_for_kb
  by design — no watch-triggered session can spawn from an artifact.

``upload_bytes`` and ``enqueue_embed_job`` are monkeypatched at their
source modules (the handler imports them locally) — no MinIO/Redis in
unit tests, matching the FakeS3Client posture of test_storage_streaming.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import PHASE_GRANTS, Phase, ToolIntent
from app.autonomous.guard import _ARTIFACT_MAX_CHARS, _handle_retrieve_chunks, guarded_tool_call
from app.models.autonomous import AutonomousArtifact, AutonomousSession
from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.user import User
from app.security import hash_password
from tests.autonomous.conftest import _attach_file_with_chunk


class _StubGateway:
    """emit_artifact is local/zero-cost; the gateway is never touched."""


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"artifact-test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_kb(db: AsyncSession, *, owner: User) -> KnowledgeBase:
    kb = KnowledgeBase(
        owner_id=owner.id,
        name=f"artifact-kb-{uuid.uuid4().hex[:6]}",
        hybrid_alpha=1.0,
    )
    db.add(kb)
    await db.flush()
    return kb


async def _make_session(
    db: AsyncSession,
    *,
    user: User,
    phase: str = "drafting",
    params: dict[str, Any] | None = None,
) -> AutonomousSession:
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="manual",
        status="running",
        halt_state="running",
        current_phase=phase,
        params=params or {},
    )
    db.add(sess)
    await db.flush()
    await db.refresh(sess)
    return sess


def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace ``app.storage.upload_bytes`` with a recording stub.

    The handler imports ``upload_bytes`` locally at call time, so
    patching the source module is picked up.
    """
    calls: list[dict[str, Any]] = []

    async def _fake_upload(*, storage_path: str, body: bytes, content_type: str) -> None:
        calls.append({"storage_path": storage_path, "body": body, "content_type": content_type})

    monkeypatch.setattr("app.storage.upload_bytes", _fake_upload)
    return calls


def _stub_embed(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Replace ``app.workers.queue.enqueue_embed_job`` with a recording stub."""
    calls: list[uuid.UUID] = []

    async def _fake_enqueue(file_id: uuid.UUID) -> bool:
        calls.append(file_id)
        return True

    monkeypatch.setattr("app.workers.queue.enqueue_embed_job", _fake_enqueue)
    return calls


async def _count(db: AsyncSession, model: type) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _all_counts(db: AsyncSession) -> dict[str, int]:
    """Row counts of the four tables the handler writes."""
    return {
        "files": await _count(db, FileModel),
        "documents": await _count(db, Document),
        "knowledge_base_files": await _count(db, KnowledgeBaseFile),
        "autonomous_artifacts": await _count(db, AutonomousArtifact),
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_emit_artifact_happy_path(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A drafting-phase session with a target KB persists all four row
    kinds + the storage object, and returns the documented data keys."""
    upload_calls = _stub_storage(monkeypatch)
    embed_calls = _stub_embed(monkeypatch)

    user = await _make_user(db_session)
    kb = await _make_kb(db_session, owner=user)
    sess = await _make_session(db_session, user=user, params={"kb_id": str(kb.id)})

    content = "# Memo\n\nThe reviewed NDA's term clause is three (3) years."
    result = await guarded_tool_call(
        sess,
        ToolIntent.emit_artifact,
        {"artifact": {"name": "Review memo", "content": content}},
        db_session,
        _StubGateway(),
    )

    assert result.cost_usd == Decimal("0")
    assert result.outcome == "success"
    data = result.data
    assert set(data.keys()) == {"artifact_id", "file_id", "document_id", "name", "size_bytes"}

    body = content.encode("utf-8")

    # File row — owner/mime/status/storage-key/size/hash from encoded bytes.
    file_row = await db_session.get(FileModel, uuid.UUID(data["file_id"]))
    assert file_row is not None
    assert file_row.owner_id == user.id
    assert file_row.mime_type == "text/markdown"
    assert file_row.ingestion_status == "ready"
    assert file_row.storage_path == str(file_row.id)
    assert file_row.size_bytes == len(body)
    assert file_row.hash_sha256 == hashlib.sha256(body).hexdigest()
    # Name had no extension → ".md" appended.
    assert file_row.filename == "Review memo.md"

    # Upload happened, keyed by the (client-generated) file id, BEFORE rows.
    assert len(upload_calls) == 1
    assert upload_calls[0]["storage_path"] == str(file_row.id)
    assert upload_calls[0]["body"] == body
    assert upload_calls[0]["content_type"] == "text/markdown"

    # Document row — direct-text persistence, honest parser label.
    doc = await db_session.get(Document, uuid.UUID(data["document_id"]))
    assert doc is not None
    assert doc.file_id == file_row.id
    assert doc.parser == "autonomous-artifact"
    assert doc.normalized_content == content
    assert doc.character_count == len(content)
    assert doc.page_count == 1

    # Chunks exist and uphold the M2-A1 re-read invariant.
    chunks = (
        (await db_session.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)))
        .scalars()
        .all()
    )
    assert len(chunks) >= 1
    for chunk in chunks:
        assert (
            chunk.content == doc.normalized_content[chunk.char_offset_start : chunk.char_offset_end]
        )

    # KB attach join row.
    kbf = (
        await db_session.execute(
            select(KnowledgeBaseFile)
            .where(KnowledgeBaseFile.kb_id == kb.id)
            .where(KnowledgeBaseFile.file_id == file_row.id)
        )
    ).scalar_one()
    assert kbf is not None

    # Artifact reference row.
    artifact_row = await db_session.get(AutonomousArtifact, uuid.UUID(data["artifact_id"]))
    assert artifact_row is not None
    assert artifact_row.session_id == sess.id
    assert artifact_row.file_id == file_row.id
    assert artifact_row.name == "Review memo.md"
    assert artifact_row.mime == "text/markdown"
    assert artifact_row.size_bytes == len(body)

    # Best-effort embed enqueue fired for the new file.
    assert embed_calls == [file_row.id]


# ---------------------------------------------------------------------------
# Honest skips
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_emit_artifact_skips_without_target_kb(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No kb_id in session params → honest skip; zero rows, zero uploads."""
    upload_calls = _stub_storage(monkeypatch)
    _stub_embed(monkeypatch)

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, params={})

    before = await _all_counts(db_session)
    result = await guarded_tool_call(
        sess,
        ToolIntent.emit_artifact,
        {"artifact": {"name": "memo.md", "content": "# Memo"}},
        db_session,
        _StubGateway(),
    )

    assert result.data == {"skipped": "no_target_kb"}
    assert result.outcome == "skipped"
    assert result.cost_usd == Decimal("0")
    assert await _all_counts(db_session) == before
    assert upload_calls == []


@pytest.mark.integration
async def test_emit_artifact_skips_empty_content(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty (or missing) content → honest skip; zero rows, zero uploads."""
    upload_calls = _stub_storage(monkeypatch)
    _stub_embed(monkeypatch)

    user = await _make_user(db_session)
    kb = await _make_kb(db_session, owner=user)
    sess = await _make_session(db_session, user=user, params={"kb_id": str(kb.id)})

    before = await _all_counts(db_session)
    result = await guarded_tool_call(
        sess,
        ToolIntent.emit_artifact,
        {"artifact": {"name": "memo.md", "content": ""}},
        db_session,
        _StubGateway(),
    )

    assert result.data == {"skipped": "empty_content"}
    assert result.outcome == "skipped"
    assert await _all_counts(db_session) == before
    assert upload_calls == []

    # Missing content key entirely → same honest skip.
    result = await guarded_tool_call(
        sess,
        ToolIntent.emit_artifact,
        {"artifact": {"name": "x"}},
        db_session,
        _StubGateway(),
    )

    assert result.data == {"skipped": "empty_content"}
    assert result.outcome == "skipped"
    assert await _all_counts(db_session) == before
    assert upload_calls == []


# ---------------------------------------------------------------------------
# Storage failure — honest outcome, NO DB rows
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_emit_artifact_storage_failure_writes_no_rows(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Upload failure → outcome='storage_error', error in data, NO rows in
    any of the four tables (the gateway_error honesty pattern)."""
    _stub_embed(monkeypatch)

    async def _failing_upload(*, storage_path: str, body: bytes, content_type: str) -> None:
        raise RuntimeError("minio is down")

    monkeypatch.setattr("app.storage.upload_bytes", _failing_upload)

    user = await _make_user(db_session)
    kb = await _make_kb(db_session, owner=user)
    sess = await _make_session(db_session, user=user, params={"kb_id": str(kb.id)})

    before = await _all_counts(db_session)
    result = await guarded_tool_call(
        sess,
        ToolIntent.emit_artifact,
        {"artifact": {"name": "memo.md", "content": "# Memo"}},
        db_session,
        _StubGateway(),
    )

    assert result.outcome == "storage_error"
    assert result.cost_usd == Decimal("0")
    assert "RuntimeError" in result.data["error"]
    assert await _all_counts(db_session) == before


# ---------------------------------------------------------------------------
# Sanitization + truncation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_emit_artifact_sanitizes_path_traversal_name(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path-traversal name is basenamed and given an extension."""
    _stub_storage(monkeypatch)
    _stub_embed(monkeypatch)

    user = await _make_user(db_session)
    kb = await _make_kb(db_session, owner=user)
    sess = await _make_session(db_session, user=user, params={"kb_id": str(kb.id)})

    result = await guarded_tool_call(
        sess,
        ToolIntent.emit_artifact,
        {"artifact": {"name": "../../etc/passwd", "content": "# Memo"}},
        db_session,
        _StubGateway(),
    )

    file_row = await db_session.get(FileModel, uuid.UUID(result.data["file_id"]))
    assert file_row is not None
    assert "/" not in file_row.filename
    assert "\\" not in file_row.filename
    # Basename has no extension → ".md" appended.
    assert file_row.filename == "passwd.md"
    assert "." in file_row.filename


@pytest.mark.integration
async def test_emit_artifact_strips_nul_bytes(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NUL bytes in content and name are stripped before persistence —
    Postgres TEXT rejects \\x00 at flush (post-upload orphan otherwise)."""
    _stub_storage(monkeypatch)
    _stub_embed(monkeypatch)

    user = await _make_user(db_session)
    kb = await _make_kb(db_session, owner=user)
    sess = await _make_session(db_session, user=user, params={"kb_id": str(kb.id)})

    result = await guarded_tool_call(
        sess,
        ToolIntent.emit_artifact,
        {"artifact": {"name": "me\x00mo.md", "content": "a\x00b"}},
        db_session,
        _StubGateway(),
    )

    assert result.outcome == "success"
    doc = await db_session.get(Document, uuid.UUID(result.data["document_id"]))
    assert doc is not None
    assert doc.normalized_content == "ab"
    file_row = await db_session.get(FileModel, uuid.UUID(result.data["file_id"]))
    assert file_row is not None
    assert file_row.filename == "memo.md"


@pytest.mark.integration
async def test_emit_artifact_truncates_oversize_content(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Content beyond _ARTIFACT_MAX_CHARS is clamped and flagged."""
    _stub_storage(monkeypatch)
    _stub_embed(monkeypatch)

    user = await _make_user(db_session)
    kb = await _make_kb(db_session, owner=user)
    sess = await _make_session(db_session, user=user, params={"kb_id": str(kb.id)})

    oversize = "x" * (_ARTIFACT_MAX_CHARS + 17)
    result = await guarded_tool_call(
        sess,
        ToolIntent.emit_artifact,
        {"artifact": {"name": "big.md", "content": oversize}},
        db_session,
        _StubGateway(),
    )

    assert result.data["truncated"] is True
    assert result.data["size_bytes"] == _ARTIFACT_MAX_CHARS  # ASCII: 1 byte/char

    doc = await db_session.get(Document, uuid.UUID(result.data["document_id"]))
    assert doc is not None
    assert doc.character_count == _ARTIFACT_MAX_CHARS
    assert len(doc.normalized_content) == _ARTIFACT_MAX_CHARS


# ---------------------------------------------------------------------------
# R6 — drafting-only grant
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_emit_artifact_granted_at_drafting_only() -> None:
    """emit_artifact appears in the drafting grant set and NOWHERE else."""
    assert ToolIntent.emit_artifact in PHASE_GRANTS[Phase.drafting]
    for phase in (Phase.intake, Phase.analysis, Phase.ethics_review, Phase.delivery):
        assert ToolIntent.emit_artifact not in PHASE_GRANTS[phase], (
            f"emit_artifact must not be granted at {phase}"
        )


@pytest.mark.integration
@pytest.mark.parametrize("phase", ["intake", "analysis", "ethics_review", "delivery"])
async def test_emit_artifact_rejected_at_ungranted_phase(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    """The chokepoint raises ToolNotGranted outside drafting (R6)."""
    from app.errors import ToolNotGranted

    upload_calls = _stub_storage(monkeypatch)
    _stub_embed(monkeypatch)

    user = await _make_user(db_session)
    kb = await _make_kb(db_session, owner=user)
    sess = await _make_session(db_session, user=user, phase=phase, params={"kb_id": str(kb.id)})

    with pytest.raises(ToolNotGranted):
        await guarded_tool_call(
            sess,
            ToolIntent.emit_artifact,
            {"artifact": {"name": "memo.md", "content": "# Memo"}},
            db_session,
            _StubGateway(),
        )
    # _dispatch was never reached — no upload attempted.
    assert upload_calls == []


# ---------------------------------------------------------------------------
# Mode-3 retrieval echo exclusion
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_retrieve_chunks_since_excludes_artifact_files(
    db_session: AsyncSession,
) -> None:
    """Mode 3 (since + kb_id) returns only ordinary files — a file referenced
    by an autonomous_artifacts row (a prior run's own memo) is excluded so
    the next tick does not re-analyze it (self-ingestion echo)."""
    user = await _make_user(db_session)
    kb = await _make_kb(db_session, owner=user)

    # Both files attached AFTER the cutoff; one is an artifact.
    ordinary_file, _, _ = await _attach_file_with_chunk(
        db_session, owner=user, kb=kb, chunk_text="Ordinary contract uploaded today."
    )
    artifact_file, _, _ = await _attach_file_with_chunk(
        db_session, owner=user, kb=kb, chunk_text="Prior run's memo content."
    )
    prior_sess = await _make_session(db_session, user=user)
    db_session.add(
        AutonomousArtifact(
            session_id=prior_sess.id,
            file_id=artifact_file.id,
            name="memo.md",
            mime="text/markdown",
            size_bytes=25,
        )
    )
    await db_session.flush()

    since = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    result = await _handle_retrieve_chunks({"since": since, "kb_id": str(kb.id)}, db=db_session)

    returned_file_ids = {c["file_id"] for c in result.data["chunks"]}
    assert str(ordinary_file.id) in returned_file_ids
    assert str(artifact_file.id) not in returned_file_ids


# ---------------------------------------------------------------------------
# Watch-loop guard
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_emit_artifact_does_not_fire_watches(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The direct KB attach bypasses fire_watches_for_kb by design — no
    watch dispatch, no new AutonomousSession spawned by the handler."""
    from unittest.mock import AsyncMock

    _stub_storage(monkeypatch)
    _stub_embed(monkeypatch)
    watch_spy = AsyncMock()
    monkeypatch.setattr("app.autonomous.watch_trigger.fire_watches_for_kb", watch_spy)

    user = await _make_user(db_session)
    kb = await _make_kb(db_session, owner=user)
    sess = await _make_session(db_session, user=user, params={"kb_id": str(kb.id)})

    sessions_before = await _count(db_session, AutonomousSession)
    await guarded_tool_call(
        sess,
        ToolIntent.emit_artifact,
        {"artifact": {"name": "memo.md", "content": "# Memo"}},
        db_session,
        _StubGateway(),
    )

    watch_spy.assert_not_called()
    assert await _count(db_session, AutonomousSession) == sessions_before
