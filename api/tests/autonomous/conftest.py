"""Shared fixtures for autonomous-package tests.

Scoped to the M4 real-executor-work additions:

- :func:`kb_with_one_indexed_file` (Task 6) — KB + file + document + one
  chunk that is queryable via hybrid search (FTS) AND fetchable directly
  by ``file_id``.  Used by mode-1 (query) and mode-2 (file_id) tests of
  :func:`app.autonomous.guard._handle_retrieve_chunks`.
- :func:`kb_with_old_and_new_files` (Task 6) — KB with TWO attached
  files; ``old_file`` has ``KnowledgeBaseFile.attached_at`` set far in
  the past, ``new_file`` has it at "now".  Used by mode-3 (``since``)
  tests to verify the since-cutoff filters correctly.
- :func:`session_with_skill_ref` / :func:`session_with_playbook_id` /
  :func:`session_without_target` / :func:`sample_chunks` (Task 7) —
  ``AutonomousSession`` rows shaped for the prompt-assembly tests
  (``test_prompts.py``).  Also installs a synthetic
  :class:`SkillRegistry` at ``app.state.skill_registry`` so
  :func:`assemble_analysis_messages` can resolve the skill_ref without
  depending on FastAPI lifespan having run.

Both Task-6 fixtures populate the ``content_tsv`` generated column by
issuing a no-op UPDATE — mirrors the pattern in
:mod:`tests.autonomous.test_autonomous_observability` so FTS works
under the per-test SAVEPOINT-rollback session.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.autonomous import AutonomousSession
from app.models.document import Document, DocumentChunk
from app.models.file import File as FileModel
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.playbook import Playbook, PlaybookPosition
from app.models.user import User
from app.security import hash_password
from app.skills import load_registry
from app.skills.registry import MutableSkillRegistry

# Fixtures under tests/fixtures/skills/ — same corpus the C1 internal-skills
# tests use; ``alpha-test-skill`` is a known-loaded name.
_SKILL_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "skills"

# A real fixture skill the registry always loads from
# ``tests/fixtures/skills/`` (see test_internal_skills.py for the
# canonical access pattern).  Hard-coding a real fixture name keeps the
# prompts test deterministic — no dependency on which production skills
# happen to be present in ``skills/`` at test time.
_FIXTURE_SKILL_REF = "alpha-test-skill"


@dataclass
class KbOneFile:
    """Bundle exposing the IDs a Task-6 test needs.

    ``file_id`` is the :attr:`File.id` of the attached file — what a
    real caller would pass into ``_handle_retrieve_chunks(file_id=...)``.
    ``document_id`` is the matching :attr:`Document.id` — the value
    that appears in ``chunk["document_id"]`` per the existing
    query-path payload shape.
    """

    kb_id: uuid.UUID
    file_id: uuid.UUID
    document_id: uuid.UUID
    chunk_id: uuid.UUID


@dataclass
class KbTwoFiles:
    """Bundle exposing IDs for the ``since`` cutoff test (Mode 3).

    ``old_file_id`` was attached far in the past (backdated 1 hour);
    ``new_file_id`` was attached at "now".  A test passing a
    5-minute-ago ``since`` should see only ``new_file_id``'s chunks.
    """

    kb_id: uuid.UUID
    old_file_id: uuid.UUID
    new_file_id: uuid.UUID


_CHUNK_TEXT_DEFAULT = (
    "This Non-Disclosure Agreement is entered into between the parties "
    "and the receiving party shall keep all test information confidential."
)


async def _make_owner(db: AsyncSession) -> User:
    user = User(
        email=f"u-retr-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_kb(db: AsyncSession, *, owner: User) -> KnowledgeBase:
    kb = KnowledgeBase(
        owner_id=owner.id,
        name=f"retr-kb-{uuid.uuid4().hex[:6]}",
        hybrid_alpha=1.0,  # FTS-only — no embedding needed for these tests
    )
    db.add(kb)
    await db.flush()
    return kb


async def _attach_file_with_chunk(
    db: AsyncSession,
    *,
    owner: User,
    kb: KnowledgeBase,
    chunk_text: str = _CHUNK_TEXT_DEFAULT,
    attached_at: datetime | None = None,
) -> tuple[FileModel, Document, DocumentChunk]:
    """Create a file + document + one chunk attached to ``kb``.

    If ``attached_at`` is provided, the ``KnowledgeBaseFile`` row is
    written with that timestamp (used by
    :func:`kb_with_old_and_new_files` to backdate the "old" file).
    Otherwise the DB default (``now()``) wins.
    """
    f = FileModel(
        owner_id=owner.id,
        filename=f"retr-{uuid.uuid4().hex[:6]}.txt",
        mime_type="text/plain",
        size_bytes=len(chunk_text),
        hash_sha256="f" * 64,
        storage_path=f"retr-fixture/{uuid.uuid4()}",
        ingestion_status="ready",
    )
    db.add(f)
    await db.flush()

    kbf_kwargs: dict[str, object] = {"kb_id": kb.id, "file_id": f.id}
    if attached_at is not None:
        kbf_kwargs["attached_at"] = attached_at
    kbf = KnowledgeBaseFile(**kbf_kwargs)
    db.add(kbf)
    await db.flush()

    doc = Document(
        file_id=f.id,
        parser="pymupdf-only",
        parser_version="pymupdf=1.27",
        page_count=1,
        character_count=len(chunk_text),
        normalized_content=chunk_text,
        was_ocrd=False,
    )
    db.add(doc)
    await db.flush()

    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content=chunk_text,
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=len(chunk_text),
    )
    db.add(chunk)
    await db.flush()
    return f, doc, chunk


@pytest_asyncio.fixture
async def kb_with_one_indexed_file(db_session: AsyncSession) -> KbOneFile:
    """KB + one attached file with a single chunk; FTS-queryable.

    Returns ``kb_id``, ``file_id`` (files.id — the real semantic file
    identifier callers pass into ``_handle_retrieve_chunks``),
    ``document_id`` (documents.id — appears in ``chunk["document_id"]``
    per the existing payload shape), and ``chunk_id``.
    """
    owner = await _make_owner(db_session)
    kb = await _make_kb(db_session, owner=owner)
    f, doc, chunk = await _attach_file_with_chunk(db_session, owner=owner, kb=kb)
    # Force Postgres to compute the generated content_tsv column so FTS works.
    await db_session.execute(text("UPDATE document_chunks SET chunk_index = chunk_index"))
    await db_session.flush()
    return KbOneFile(kb_id=kb.id, file_id=f.id, document_id=doc.id, chunk_id=chunk.id)


@pytest_asyncio.fixture
async def kb_with_old_and_new_files(db_session: AsyncSession) -> KbTwoFiles:
    """KB with TWO attached files: one backdated, one at "now".

    ``old_file`` has ``KnowledgeBaseFile.attached_at = now - 1 hour``;
    ``new_file`` has the DB default (``now()``).  A test passing
    ``since = now - 5 minutes`` should see only ``new_file``'s chunks.
    """
    owner = await _make_owner(db_session)
    kb = await _make_kb(db_session, owner=owner)

    old_attached_at = datetime.now(UTC) - timedelta(hours=1)
    old_f, _, _ = await _attach_file_with_chunk(
        db_session,
        owner=owner,
        kb=kb,
        chunk_text="Old indexed contract text from last quarter.",
        attached_at=old_attached_at,
    )
    new_f, _, _ = await _attach_file_with_chunk(
        db_session,
        owner=owner,
        kb=kb,
        chunk_text="Fresh contract uploaded today for the autonomous run.",
    )

    await db_session.execute(text("UPDATE document_chunks SET chunk_index = chunk_index"))
    await db_session.flush()

    return KbTwoFiles(kb_id=kb.id, old_file_id=old_f.id, new_file_id=new_f.id)


# ---------------------------------------------------------------------------
# Task 7 — prompt assembly fixtures (test_prompts.py)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def _installed_skill_registry() -> AsyncIterator[None]:
    """Install the fixture skill registry at ``app.state.skill_registry``.

    :mod:`app.autonomous.prompts` reads the registry holder from
    ``app.state`` when no explicit registry is passed.  In production
    the lifespan handler populates it (``app/main.py:88``); in tests we
    install the C1-fixtures registry so ``alpha-test-skill`` is
    resolvable.  The previous holder (if any) is restored on teardown.
    """
    from app.main import app

    holder = MutableSkillRegistry(load_registry(_SKILL_FIXTURES_DIR))
    prior_holder = getattr(app.state, "skill_registry", None)
    app.state.skill_registry = holder
    try:
        yield
    finally:
        if prior_holder is None:
            delattr(app.state, "skill_registry")
        else:
            app.state.skill_registry = prior_holder


async def _make_autonomous_user(db: AsyncSession) -> User:
    """Create an opted-in user for the autonomous-prompt fixtures."""
    user = User(
        email=f"u-prompt-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_session(
    db: AsyncSession,
    *,
    user: User,
    params: dict[str, Any],
) -> AutonomousSession:
    """Insert a minimal ``AutonomousSession`` row with the given params."""
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="manual",
        params=params,
    )
    db.add(sess)
    await db.flush()
    return sess


@pytest_asyncio.fixture
async def session_with_skill_ref(
    db_session: AsyncSession,
    _installed_skill_registry: None,
) -> AutonomousSession:
    """``AutonomousSession`` whose ``params`` points at the fixture skill.

    The fixture skill (``alpha-test-skill``) is loaded into
    ``app.state.skill_registry`` by :func:`_installed_skill_registry`,
    so :func:`app.autonomous.prompts.assemble_analysis_messages` can
    resolve it without an explicit ``registry=`` argument.
    """
    user = await _make_autonomous_user(db_session)
    return await _make_session(
        db_session,
        user=user,
        params={"skill_ref": _FIXTURE_SKILL_REF},
    )


@pytest_asyncio.fixture
async def session_with_playbook_id(
    db_session: AsyncSession,
) -> AutonomousSession:
    """``AutonomousSession`` whose ``params`` points at a seeded playbook.

    The playbook + a single position are inserted inline so the
    prompt-assembly path's ``selectinload(Playbook.positions)`` query
    has real rows to walk.  Mirrors the lightweight pattern in
    ``tests/playbooks/test_executor.py``'s ``_make_playbook_with_position``.
    """
    user = await _make_autonomous_user(db_session)
    playbook = Playbook(
        name="Prompt Fixture Playbook",
        contract_type="NDA",
        description="Synthetic playbook used by test_prompts.py.",
    )
    db_session.add(playbook)
    await db_session.flush()
    position = PlaybookPosition(
        playbook_id=playbook.id,
        issue="Confidentiality term",
        description="Receiving Party obligation scope.",
        standard_language=(
            "The Receiving Party shall hold Confidential Information in confidence "
            "and shall not disclose it to any third party."
        ),
        severity_if_missing="high",
        detection_keywords=["confidence", "confidential"],
        detection_examples=[],
        redline_strategy="Tighten to the standard language above.",
        fallback_tiers=[{"rank": 1, "description": "Allow disclosure to professional advisors."}],
        position_order=0,
    )
    db_session.add(position)
    await db_session.flush()
    return await _make_session(
        db_session,
        user=user,
        params={"playbook_id": str(playbook.id)},
    )


@pytest_asyncio.fixture
async def session_without_target(
    db_session: AsyncSession,
) -> AutonomousSession:
    """``AutonomousSession`` whose ``params`` carries neither target.

    Used to assert that :func:`assemble_analysis_messages` raises
    ``ValueError`` rather than silently producing an empty system
    prompt.
    """
    user = await _make_autonomous_user(db_session)
    return await _make_session(db_session, user=user, params={})


@pytest_asyncio.fixture
def sample_chunks() -> list[dict[str, Any]]:
    """A small chunks list shaped like ``_handle_retrieve_chunks`` output.

    The keys mirror the payload built in
    :func:`app.autonomous.guard._format_chunks_result` so a prompt
    assembled against this fixture exercises the real downstream shape.
    """
    return [
        {
            "chunk_id": str(uuid.uuid4()),
            "document_id": str(uuid.uuid4()),
            "file_id": str(uuid.uuid4()),
            "file_name": "fixture-nda.pdf",
            "content": (
                "Section 1. The Receiving Party shall hold Confidential "
                "Information in confidence and not disclose it."
            ),
            "char_offset_start": 0,
            "char_offset_end": 110,
            "hybrid_score": 0.91,
        },
        {
            "chunk_id": str(uuid.uuid4()),
            "document_id": str(uuid.uuid4()),
            "file_id": str(uuid.uuid4()),
            "file_name": "fixture-nda.pdf",
            "content": "Section 2. The term of this Agreement is three (3) years.",
            "char_offset_start": 110,
            "char_offset_end": 170,
            "hybrid_score": 0.42,
        },
    ]


# ---------------------------------------------------------------------------
# Tasks 9 + 10 — intake_node dispatch fixtures (test_executor_real_work.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_gateway() -> MagicMock:
    """Minimal gateway double for intake-node tests.

    ``retrieve_chunks`` is a cost-0 local retrieval — the chokepoint
    never touches the gateway in mode 2 or mode 3.  The factory
    signature accepts a gateway, so we hand it a ``MagicMock`` with an
    ``AsyncMock`` ``chat_completion`` so any accidental gateway call
    fails loud (and so a test that grows past intake into analysis
    won't need to refactor the fixture).
    """
    gw = MagicMock()
    gw.chat_completion = AsyncMock()
    return gw


async def _make_optedin_user(db: AsyncSession) -> User:
    """Create an opted-in user for the intake-node session fixtures."""
    user = User(
        email=f"u-intake-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_running_session(
    db: AsyncSession,
    *,
    user: User,
    trigger_kind: str,
    params: dict[str, Any],
) -> AutonomousSession:
    """Insert a running ``AutonomousSession`` ready for intake-node dispatch.

    The session lands in ``status='running'`` / ``halt_state='running'``
    / ``current_phase='intake'`` with a finite ``max_cost_usd`` so the
    chokepoint's pre-call brake checks pass without negotiating a
    pending→running transition.
    """
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind=trigger_kind,
        status="running",
        halt_state="running",
        current_phase="intake",
        max_cost_usd=Decimal("5.00"),
        params=params,
    )
    db.add(sess)
    await db.flush()
    return sess


@pytest_asyncio.fixture
async def running_watch_session(
    db_session: AsyncSession,
    kb_with_one_indexed_file: KbOneFile,
) -> AutonomousSession:
    """Watch-triggered session: ``params`` carries ``kb_id`` + ``file_id``.

    Reuses :func:`kb_with_one_indexed_file` so the file_id-scoped
    retrieval has a real chunk to return — keeps the test exercising
    the mode 2 path end-to-end through the chokepoint rather than
    asserting against an empty list.
    """
    user = await _make_optedin_user(db_session)
    return await _make_running_session(
        db_session,
        user=user,
        trigger_kind="watch",
        params={
            "kb_id": str(kb_with_one_indexed_file.kb_id),
            "file_id": str(kb_with_one_indexed_file.file_id),
        },
    )


@pytest_asyncio.fixture
async def running_schedule_session_with_since(
    db_session: AsyncSession,
    kb_with_old_and_new_files: KbTwoFiles,
) -> AutonomousSession:
    """Schedule session with a since-cutoff between the two attached files.

    ``kb_with_old_and_new_files`` backdates ``old_file`` by 1 hour and
    leaves ``new_file`` at "now".  A ``since`` of 5 minutes ago
    therefore exercises the mode-3 cutoff: only ``new_file``'s chunks
    should come back.
    """
    user = await _make_optedin_user(db_session)
    since_iso = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    return await _make_running_session(
        db_session,
        user=user,
        trigger_kind="schedule",
        params={
            "kb_id": str(kb_with_old_and_new_files.kb_id),
            "since": since_iso,
        },
    )


@pytest_asyncio.fixture
async def running_schedule_session_first_tick(
    db_session: AsyncSession,
) -> AutonomousSession:
    """Schedule session whose ``params`` has ``kb_id`` but no ``since``.

    Represents the first cron tick after a schedule was created —
    ``schedules.last_run_at`` is NULL at spawn so the dispatcher hands
    intake a KB-only target.  Intake must skip retrieval and record
    ``first_tick_no_baseline=True``.
    """
    user = await _make_optedin_user(db_session)
    kb = await _make_kb(db_session, owner=user)
    return await _make_running_session(
        db_session,
        user=user,
        trigger_kind="schedule",
        params={"kb_id": str(kb.id)},
    )


@pytest_asyncio.fixture
async def running_session_without_target(
    db_session: AsyncSession,
) -> AutonomousSession:
    """Manual session with no target keys in ``params``.

    Degenerate case (test/manual spawn): intake must stay empty without
    error so delivery can still complete with an empty-findings
    notification.
    """
    user = await _make_optedin_user(db_session)
    return await _make_running_session(
        db_session,
        user=user,
        trigger_kind="manual",
        params={},
    )


# ---------------------------------------------------------------------------
# Task 11 — analysis_node fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def running_watch_session_at_analysis(
    db_session: AsyncSession,
    kb_with_one_indexed_file: KbOneFile,
    _installed_skill_registry: None,
) -> AutonomousSession:
    """Watch-triggered session sitting at the analysis-phase boundary.

    Same shape as :func:`running_watch_session` (mode-2 file-scoped
    target) PLUS a real ``skill_ref`` so :func:`assemble_analysis_messages`
    has a resolvable system prompt. ``current_phase`` is left at
    ``"intake"`` — the analysis node runs the intake→analysis transition
    itself. ``_installed_skill_registry`` is requested so
    ``alpha-test-skill`` is loaded into ``app.state.skill_registry`` and
    the prompt assembly path resolves without an explicit ``registry=``.
    """
    user = await _make_optedin_user(db_session)
    return await _make_running_session(
        db_session,
        user=user,
        trigger_kind="watch",
        params={
            "kb_id": str(kb_with_one_indexed_file.kb_id),
            "file_id": str(kb_with_one_indexed_file.file_id),
            "skill_ref": _FIXTURE_SKILL_REF,
        },
    )


@pytest_asyncio.fixture
async def running_session_at_drafting(db_session: AsyncSession) -> AutonomousSession:
    """Running session ready for the drafting node.

    ``current_phase`` is left at ``"intake"``; the drafting node runs the
    transition to ``"drafting"`` itself (``run_phase_transition`` does no
    ordering validation), then dispatches the per-item guarded calls.
    """
    user = await _make_optedin_user(db_session)
    return await _make_running_session(db_session, user=user, trigger_kind="watch", params={})


@pytest_asyncio.fixture
async def running_session_at_ethics(db_session: AsyncSession) -> AutonomousSession:
    """Running session ready for the ethics-review node."""
    user = await _make_optedin_user(db_session)
    return await _make_running_session(db_session, user=user, trigger_kind="watch", params={})


@pytest_asyncio.fixture
async def running_session_at_delivery(db_session: AsyncSession) -> AutonomousSession:
    """Running session ready for the delivery node (terminal_reason regression)."""
    user = await _make_optedin_user(db_session)
    return await _make_running_session(db_session, user=user, trigger_kind="watch", params={})


@pytest.fixture
def mock_gateway_structured_response() -> MagicMock:
    """Gateway double whose ``chat_completion`` returns a structured-output stub.

    The returned object mimics :class:`ChatCompletionResponse` closely
    enough for :func:`app.autonomous.guard._handle_gateway_inference` to
    extract ``choices[0].message.content`` and ``usage.prompt_tokens`` /
    ``usage.completion_tokens``. We do NOT instantiate the real Pydantic
    model — the chokepoint accesses attributes directly, so a
    ``MagicMock`` tree with the right attribute names is sufficient and
    keeps the fixture decoupled from schema drift.
    """
    content_json = (
        "```json\n"
        '{"findings": [{"title": "T", "summary": "S", "severity": "info", '
        '"source_chunk_ids": []}], '
        '"suggested_memories": [], '
        '"suggested_precedents": [], '
        '"privilege_concerns": [], '
        '"scope_concerns": []}\n'
        "```"
    )
    message = MagicMock()
    message.content = content_json
    choice = MagicMock()
    choice.message = message
    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    usage.total_tokens = 150
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage

    gw = MagicMock()
    gw.chat_completion = AsyncMock(return_value=response)
    return gw
