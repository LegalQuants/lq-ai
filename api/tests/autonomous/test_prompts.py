"""Tests for the M4 autonomous prompt-assembly module.

Covers :func:`app.autonomous.prompts.assemble_analysis_messages` for
both target kinds (``skill_ref`` and ``playbook_id``), the no-target
error path, and the contract of
:data:`app.autonomous.prompts.STRUCTURED_OUTPUT_INSTRUCTION` (every
JSON key the drafting node parses must be named in the instruction
text).

Fixtures live in ``conftest.py``:

* ``session_with_skill_ref`` — installs a fixture skill registry at
  ``app.state.skill_registry`` and seeds a session whose ``params``
  references the loaded fixture skill.
* ``session_with_playbook_id`` — inserts a real Playbook + one
  PlaybookPosition inline; the session ``params`` carries the
  playbook's id.
* ``session_without_target`` — session with empty ``params``.
* ``sample_chunks`` — list of dicts shaped like
  ``_handle_retrieve_chunks``'s output.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.prompts import (
    STRUCTURED_OUTPUT_INSTRUCTION,
    assemble_analysis_messages,
)
from app.models.autonomous import AutonomousSession


@pytest.mark.asyncio
async def test_assemble_messages_for_skill_ref(
    db_session: AsyncSession,
    session_with_skill_ref: AutonomousSession,
    sample_chunks: list[dict[str, object]],
) -> None:
    msgs = await assemble_analysis_messages(
        session_with_skill_ref, chunks=sample_chunks, db=db_session
    )
    # Shape: list of role/content dicts
    assert all("role" in m and "content" in m for m in msgs)
    # System prompt carries the skill's SKILL.md
    assert msgs[0]["role"] == "system"
    # The structured-output instruction tail is appended (system or final user msg)
    full = "\n".join(m["content"] for m in msgs)
    assert STRUCTURED_OUTPUT_INSTRUCTION in full
    # Chunks reach the model
    assert any("CHUNK" in m["content"] or "[chunk_id" in m["content"] for m in msgs)


@pytest.mark.asyncio
async def test_assemble_messages_for_playbook_id(
    db_session: AsyncSession,
    session_with_playbook_id: AutonomousSession,
    sample_chunks: list[dict[str, object]],
) -> None:
    msgs = await assemble_analysis_messages(
        session_with_playbook_id, chunks=sample_chunks, db=db_session
    )
    assert msgs[0]["role"] == "system"
    assert len(msgs[0]["content"]) > 50


@pytest.mark.asyncio
async def test_assemble_messages_no_target_raises(
    db_session: AsyncSession,
    session_without_target: AutonomousSession,
    sample_chunks: list[dict[str, object]],
) -> None:
    with pytest.raises(ValueError, match="no skill_ref or playbook_id"):
        await assemble_analysis_messages(
            session_without_target, chunks=sample_chunks, db=db_session
        )


def test_structured_output_instruction_carries_schema_keys() -> None:
    """The instruction tail names every key the drafting node parses."""
    inst = STRUCTURED_OUTPUT_INSTRUCTION
    assert "findings" in inst
    assert "suggested_memories" in inst
    assert "suggested_precedents" in inst
    assert "privilege_concerns" in inst
    assert "scope_concerns" in inst


@pytest.mark.asyncio
async def test_assemble_messages_raises_when_playbook_soft_deleted(
    db_session: AsyncSession, session_with_playbook_id, sample_chunks
) -> None:
    """Soft-deleted playbooks are refused, not analysed."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.models.playbook import Playbook

    pb_id = uuid.UUID(session_with_playbook_id.params["playbook_id"])
    playbook = (await db_session.execute(select(Playbook).where(Playbook.id == pb_id))).scalar_one()
    playbook.deleted_at = datetime.now(UTC)
    await db_session.flush()

    with pytest.raises(ValueError, match="playbook"):
        await assemble_analysis_messages(
            session_with_playbook_id, chunks=sample_chunks, db=db_session
        )
