"""Tests for assemble_synthesis_messages (WS-D PR1, Task 4).

Verifies that the synthesis message builder:
- Preserves the structured-findings JSON contract from assemble_analysis_messages
  (same system prompt → same fenced-JSON schema the drafting node parses).
- Appends the matter GOAL and the loop's OBSERVATIONS to a trailing user message.
- Handles the empty-observations edge case gracefully.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.prompts import STRUCTURED_OUTPUT_INSTRUCTION, assemble_synthesis_messages
from app.models.autonomous import AutonomousSession

pytestmark = pytest.mark.asyncio


async def test_synthesis_preserves_structured_contract_and_adds_goal_and_observations(
    db_session: AsyncSession,
    session_with_skill_ref: AutonomousSession,
    sample_chunks: list[dict[str, object]],
) -> None:
    """Core contract: system carries the JSON schema; trailing user carries goal + obs."""
    msgs = await assemble_synthesis_messages(
        session_with_skill_ref,
        goal="Is the clause enforceable?",
        observations=["retrieve_caselaw → 1 result: [Smith (9th 2021)]"],
        chunks=sample_chunks,
        db=db_session,
    )

    # Shape
    assert all("role" in m and "content" in m for m in msgs)
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"

    # Structured-output JSON contract is preserved in the system prompt
    assert "findings" in msgs[0]["content"]
    assert "```json" in msgs[0]["content"]
    assert STRUCTURED_OUTPUT_INSTRUCTION in msgs[0]["content"]

    # Goal and observation appear somewhere in the user messages
    user_blob = " ".join(m["content"] for m in msgs if m["role"] == "user")
    assert "Is the clause enforceable?" in user_blob
    assert "Smith (9th 2021)" in user_blob


async def test_synthesis_empty_observations_produces_placeholder(
    db_session: AsyncSession,
    session_with_skill_ref: AutonomousSession,
    sample_chunks: list[dict[str, object]],
) -> None:
    """Empty observations list → a placeholder string in the trailing user message."""
    msgs = await assemble_synthesis_messages(
        session_with_skill_ref,
        goal="Summarise liability exposure.",
        observations=[],
        chunks=sample_chunks,
        db=db_session,
    )

    user_blob = " ".join(m["content"] for m in msgs if m["role"] == "user")
    assert "Summarise liability exposure." in user_blob
    assert "no research steps" in user_blob


async def test_synthesis_message_count_is_base_plus_one(
    db_session: AsyncSession,
    session_with_skill_ref: AutonomousSession,
    sample_chunks: list[dict[str, object]],
) -> None:
    """assemble_synthesis_messages appends exactly one message to the base [system, user] pair."""
    from app.autonomous.prompts import assemble_analysis_messages

    base = await assemble_analysis_messages(
        session_with_skill_ref, chunks=sample_chunks, db=db_session
    )
    synthesis = await assemble_synthesis_messages(
        session_with_skill_ref,
        goal="Test goal.",
        observations=["obs 1", "obs 2"],
        chunks=sample_chunks,
        db=db_session,
    )
    assert len(synthesis) == len(base) + 1


async def test_synthesis_does_not_alter_system_prompt(
    db_session: AsyncSession,
    session_with_skill_ref: AutonomousSession,
    sample_chunks: list[dict[str, object]],
) -> None:
    """The system prompt is identical to assemble_analysis_messages output."""
    from app.autonomous.prompts import assemble_analysis_messages

    base = await assemble_analysis_messages(
        session_with_skill_ref, chunks=sample_chunks, db=db_session
    )
    synthesis = await assemble_synthesis_messages(
        session_with_skill_ref,
        goal="Goal text.",
        observations=["some obs"],
        chunks=sample_chunks,
        db=db_session,
    )
    assert synthesis[0]["content"] == base[0]["content"]
