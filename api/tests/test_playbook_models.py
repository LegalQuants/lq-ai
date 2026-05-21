"""Model + migration tests for the Playbook substrate — M3-A1.

Covers:

* CRUD round-trip on all three new tables (``playbooks``,
  ``playbook_positions``, ``playbook_executions``).
* Cascade delete from ``playbooks`` → ``playbook_positions`` and
  ``playbook_executions``.
* ON DELETE SET NULL on ``playbooks.created_by`` and
  ``playbook_executions.user_id`` / ``project_id`` — historical rows
  survive operator / project deletion.
* CHECK constraints pin both enums at the storage layer
  (``severity_if_missing``, ``status``).
* Index on ``(playbook_id, position_order)`` produces an ordered fetch
  via the ORM relationship.
* JSONB ``fallback_tiers`` and ``results`` round-trip cleanly.

Tests run against the same SAVEPOINT-rolled-back per-test session as
the rest of the API tests (per ``tests/conftest.py``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.file import File as FileModel
from app.models.playbook import Playbook, PlaybookExecution, PlaybookPosition
from app.models.project import Project
from app.models.user import User
from app.security import hash_password


async def _make_user(db: AsyncSession, *, is_admin: bool = False) -> User:
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=is_admin,
        role="admin" if is_admin else "member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_document(db: AsyncSession, *, owner: User) -> tuple[FileModel, Document]:
    f = FileModel(
        owner_id=owner.id,
        filename=f"playbook-target-{uuid.uuid4().hex[:8]}.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        hash_sha256="a" * 64,
        storage_path=f"playbook-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db.add(f)
    await db.flush()
    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=10,
        character_count=5000,
        normalized_content="x" * 5000,
        was_ocrd=False,
    )
    db.add(doc)
    await db.flush()
    return f, doc


# ---------------------------------------------------------------------------
# Playbook CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_playbook_round_trip(db_session: AsyncSession) -> None:
    """Insert + read returns the same Playbook with timestamps populated."""
    author = await _make_user(db_session)

    pb = Playbook(
        name="Test NDA Playbook",
        contract_type="NDA",
        description="A test playbook for round-trip coverage.",
        version="1.0.0",
        created_by=author.id,
    )
    db_session.add(pb)
    await db_session.flush()
    await db_session.refresh(pb)

    assert pb.id is not None
    assert isinstance(pb.id, uuid.UUID)
    assert pb.created_at is not None
    assert pb.updated_at is not None

    result = await db_session.execute(select(Playbook).where(Playbook.id == pb.id))
    fetched = result.scalar_one()
    assert fetched.name == "Test NDA Playbook"
    assert fetched.contract_type == "NDA"
    assert fetched.version == "1.0.0"
    assert fetched.created_by == author.id


@pytest.mark.integration
async def test_playbook_positions_load_in_order(db_session: AsyncSession) -> None:
    """The ``positions`` relationship returns rows in ``position_order`` ASC."""
    pb = Playbook(name="Ordered", contract_type="NDA")
    db_session.add(pb)
    await db_session.flush()

    # Insert out of order so the ordering must come from the relationship.
    db_session.add_all(
        [
            PlaybookPosition(
                playbook_id=pb.id,
                issue="Survival",
                standard_language="...",
                severity_if_missing="medium",
                position_order=2,
            ),
            PlaybookPosition(
                playbook_id=pb.id,
                issue="Definition of confidential information",
                standard_language="...",
                severity_if_missing="critical",
                position_order=0,
            ),
            PlaybookPosition(
                playbook_id=pb.id,
                issue="Term",
                standard_language="...",
                severity_if_missing="high",
                position_order=1,
            ),
        ]
    )
    await db_session.flush()
    await db_session.refresh(pb, attribute_names=["positions"])

    ordering = [p.issue for p in pb.positions]
    assert ordering == [
        "Definition of confidential information",
        "Term",
        "Survival",
    ]


@pytest.mark.integration
async def test_playbook_position_severity_check_constraint(
    db_session: AsyncSession,
) -> None:
    """The CHECK constraint pins the severity enum at the storage layer."""
    pb = Playbook(name="Bad", contract_type="NDA")
    db_session.add(pb)
    await db_session.flush()

    bad = PlaybookPosition(
        playbook_id=pb.id,
        issue="Whatever",
        standard_language="...",
        severity_if_missing="catastrophic",  # not in the enum
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
async def test_playbook_position_fallback_tiers_jsonb_round_trip(
    db_session: AsyncSession,
) -> None:
    """JSONB ``fallback_tiers`` round-trips the Pydantic FallbackTier shape."""
    pb = Playbook(name="JSONB", contract_type="MSA-SaaS")
    db_session.add(pb)
    await db_session.flush()

    tiers = [
        {"rank": 1, "description": "12-month cap", "language": "...."},
        {"rank": 2, "description": "24-month cap", "language": "...."},
        {"rank": 3, "description": "Uncapped only for breach", "language": "...."},
    ]
    position = PlaybookPosition(
        playbook_id=pb.id,
        issue="Limitation of Liability",
        standard_language="The party's aggregate liability shall be ...",
        severity_if_missing="critical",
        fallback_tiers=tiers,
        detection_keywords=["liability", "cap", "limitation"],
        detection_examples=[
            "Each party's aggregate liability shall not exceed the fees paid in the prior 12 months."
        ],
    )
    db_session.add(position)
    await db_session.flush()
    await db_session.refresh(position)

    assert position.fallback_tiers == tiers
    assert position.detection_keywords == ["liability", "cap", "limitation"]
    assert len(position.detection_examples) == 1


@pytest.mark.integration
async def test_playbook_delete_cascades_to_positions(db_session: AsyncSession) -> None:
    """Deleting a playbook removes its positions (ON DELETE CASCADE)."""
    pb = Playbook(name="Cascade", contract_type="NDA")
    db_session.add(pb)
    await db_session.flush()
    db_session.add(
        PlaybookPosition(
            playbook_id=pb.id,
            issue="Test",
            standard_language="...",
            severity_if_missing="low",
        )
    )
    await db_session.flush()

    await db_session.delete(pb)
    await db_session.flush()

    remaining = (
        (
            await db_session.execute(
                select(PlaybookPosition).where(PlaybookPosition.playbook_id == pb.id)
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


@pytest.mark.integration
async def test_playbook_created_by_set_null_on_user_delete(
    db_session: AsyncSession,
) -> None:
    """Deleting the author of a playbook nulls ``created_by`` rather than the row."""
    author = await _make_user(db_session)
    pb = Playbook(name="Author Survives", contract_type="NDA", created_by=author.id)
    db_session.add(pb)
    await db_session.flush()
    pb_id = pb.id

    await db_session.delete(author)
    await db_session.flush()
    # The FK ON DELETE SET NULL fires at the DB level; the ORM session's
    # identity-mapped Playbook still carries the old created_by. Expire
    # so the refetch reads from the DB.
    db_session.expire_all()

    fetched = (await db_session.execute(select(Playbook).where(Playbook.id == pb_id))).scalar_one()
    assert fetched.created_by is None
    assert fetched.name == "Author Survives"


# ---------------------------------------------------------------------------
# PlaybookExecution CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_playbook_execution_round_trip(db_session: AsyncSession) -> None:
    """Insert + read returns a PlaybookExecution with default 'pending' status."""
    author = await _make_user(db_session)
    _file, doc = await _make_document(db_session, owner=author)
    pb = Playbook(name="Execute Me", contract_type="NDA", created_by=author.id)
    db_session.add(pb)
    await db_session.flush()

    execution = PlaybookExecution(
        playbook_id=pb.id,
        target_document_id=doc.id,
        user_id=author.id,
    )
    db_session.add(execution)
    await db_session.flush()
    await db_session.refresh(execution)

    assert execution.id is not None
    assert execution.status == "pending"
    assert execution.results is None
    assert execution.error is None
    assert execution.completed_at is None


@pytest.mark.integration
async def test_playbook_execution_status_check_constraint(
    db_session: AsyncSession,
) -> None:
    """The CHECK constraint pins the execution-status enum."""
    author = await _make_user(db_session)
    _file, doc = await _make_document(db_session, owner=author)
    pb = Playbook(name="Bad Status", contract_type="NDA")
    db_session.add(pb)
    await db_session.flush()

    bad = PlaybookExecution(
        playbook_id=pb.id,
        target_document_id=doc.id,
        user_id=author.id,
        status="warp_speed",  # not in the enum
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.integration
async def test_playbook_execution_results_jsonb_round_trip(
    db_session: AsyncSession,
) -> None:
    """The ``results`` column round-trips arbitrary JSONB payloads."""
    author = await _make_user(db_session)
    _file, doc = await _make_document(db_session, owner=author)
    pb = Playbook(name="Results Shape", contract_type="MSA-SaaS")
    db_session.add(pb)
    await db_session.flush()

    payload = {
        "positions": [
            {"id": str(uuid.uuid4()), "verdict": "matches_standard", "confidence": 0.95},
            {
                "id": str(uuid.uuid4()),
                "verdict": "deviates",
                "confidence": 0.6,
                "redline": {"old": "uncapped", "new": "capped at 12 months fees"},
            },
        ],
        "summary": "1 deviation flagged.",
    }
    execution = PlaybookExecution(
        playbook_id=pb.id,
        target_document_id=doc.id,
        user_id=author.id,
        status="completed",
        results=payload,
        completed_at=datetime.now(UTC),
    )
    db_session.add(execution)
    await db_session.flush()
    await db_session.refresh(execution)

    assert execution.results == payload


@pytest.mark.integration
async def test_playbook_delete_cascades_to_executions(
    db_session: AsyncSession,
) -> None:
    """Deleting a playbook removes its executions (history audit trail)."""
    author = await _make_user(db_session)
    _file, doc = await _make_document(db_session, owner=author)
    pb = Playbook(name="Cascaded", contract_type="NDA")
    db_session.add(pb)
    await db_session.flush()
    db_session.add(
        PlaybookExecution(
            playbook_id=pb.id,
            target_document_id=doc.id,
            user_id=author.id,
        )
    )
    await db_session.flush()

    await db_session.delete(pb)
    await db_session.flush()

    remaining = (
        (
            await db_session.execute(
                select(PlaybookExecution).where(PlaybookExecution.playbook_id == pb.id)
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


@pytest.mark.integration
async def test_playbook_execution_user_set_null_on_user_delete(
    db_session: AsyncSession,
) -> None:
    """Deleting the executing user nulls ``user_id`` (history preserved).

    Uses two distinct users — ``file_owner`` owns the underlying file
    (the files table's ``owner_id`` FK uses NO ACTION so we can't
    delete that one) and ``executor`` is the operator who ran the
    playbook. Only ``executor`` is deleted in this test.
    """
    file_owner = await _make_user(db_session)
    executor = await _make_user(db_session)
    _file, doc = await _make_document(db_session, owner=file_owner)
    pb = Playbook(name="History", contract_type="NDA")
    db_session.add(pb)
    await db_session.flush()
    execution = PlaybookExecution(
        playbook_id=pb.id,
        target_document_id=doc.id,
        user_id=executor.id,
    )
    db_session.add(execution)
    await db_session.flush()
    execution_id = execution.id

    await db_session.delete(executor)
    await db_session.flush()
    db_session.expire_all()

    fetched = (
        await db_session.execute(
            select(PlaybookExecution).where(PlaybookExecution.id == execution_id)
        )
    ).scalar_one()
    assert fetched.user_id is None


@pytest.mark.integration
async def test_playbook_execution_project_set_null_on_project_delete(
    db_session: AsyncSession,
) -> None:
    """Deleting the project nulls ``project_id`` on historical executions."""
    author = await _make_user(db_session)
    _file, doc = await _make_document(db_session, owner=author)
    proj = Project(
        owner_id=author.id,
        name="P",
        slug=f"p-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(proj)
    await db_session.flush()
    pb = Playbook(name="Proj-scoped", contract_type="NDA")
    db_session.add(pb)
    await db_session.flush()
    execution = PlaybookExecution(
        playbook_id=pb.id,
        target_document_id=doc.id,
        user_id=author.id,
        project_id=proj.id,
    )
    db_session.add(execution)
    await db_session.flush()
    execution_id = execution.id

    await db_session.delete(proj)
    await db_session.flush()
    db_session.expire_all()

    fetched = (
        await db_session.execute(
            select(PlaybookExecution).where(PlaybookExecution.id == execution_id)
        )
    ).scalar_one()
    assert fetched.project_id is None


# ---------------------------------------------------------------------------
# Schema-level smoke: indexes present per the migration spec
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_playbook_indexes_present_on_disk(db_session: AsyncSession) -> None:
    """The three indexes the M3-A1 spec requires exist after migration."""
    result = await db_session.execute(
        text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = current_schema() "
            "AND indexname IN ("
            "'idx_playbook_positions_playbook_order',"
            "'idx_playbook_executions_user_created',"
            "'idx_playbook_executions_target_document'"
            ")"
        )
    )
    present = {row[0] for row in result.all()}
    assert present == {
        "idx_playbook_positions_playbook_order",
        "idx_playbook_executions_user_created",
        "idx_playbook_executions_target_document",
    }


@pytest.mark.unit
def test_playbook_models_registered_with_metadata() -> None:
    """Importing the models module registers all three tables with the Base."""
    from app.db.base import Base

    table_names = set(Base.metadata.tables.keys())
    assert "playbooks" in table_names
    assert "playbook_positions" in table_names
    assert "playbook_executions" in table_names


@pytest.mark.unit
def test_playbook_columns_match_migration() -> None:
    """The ORM model columns line up with the migration's column set."""
    pb_cols = {c.name for c in inspect(Playbook).columns}
    assert pb_cols == {
        "id",
        "name",
        "contract_type",
        "description",
        "version",
        "created_by",
        "created_at",
        "updated_at",
        # M3-A6 Phase 2: soft delete (migration 0034).
        "deleted_at",
    }

    pos_cols = {c.name for c in inspect(PlaybookPosition).columns}
    assert pos_cols == {
        "id",
        "playbook_id",
        "issue",
        "description",
        "standard_language",
        "fallback_tiers",
        "redline_strategy",
        "severity_if_missing",
        "detection_keywords",
        "detection_examples",
        "position_order",
    }

    exec_cols = {c.name for c in inspect(PlaybookExecution).columns}
    assert exec_cols == {
        "id",
        "playbook_id",
        "target_document_id",
        "user_id",
        "project_id",
        "status",
        "results",
        "error",
        "created_at",
        "completed_at",
    }
