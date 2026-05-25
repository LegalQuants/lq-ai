"""Kept-only memory loader — M4-B1 (ADR-0013 D4 guarantee).

The ADR-0013 D4 guarantee states that ONLY ``state='kept'`` AND
non-deleted memory entries may flow into an autonomous session's prompt
context.  This module is the single call-site that enforces that
invariant.

Usage (future executor / prompt-context assembly point)
-------------------------------------------------------
When the executor builds the system-prompt context for a new session, it
calls::

    from app.autonomous.memory import load_kept_memory

    kept = await load_kept_memory(db, user_id=session.user_id)

and injects the returned entries into the prompt.  The wiring point is
expected to be :mod:`app.autonomous.executor` (the session-level context
builder) once that component is extended with per-user memory injection
in a later M4 task.

Design notes
------------
* ``proposed`` and ``dismissed`` entries are intentionally excluded —
  the user must explicitly keep a memory note before it influences any
  autonomous work.  This prevents the agent from silently surfacing its
  own unreviewed observations into future runs (ADR-0013 §D4).
* Soft-deleted entries (``deleted_at IS NOT NULL``) are excluded even if
  their ``state`` is ``'kept'`` — deletion is final from the injection
  perspective.
* Ordered by ``kept_at DESC`` so the most-recently curated notes are
  earliest in the injected list (highest-recency bias).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.autonomous import AutonomousMemory


async def load_kept_memory(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[AutonomousMemory]:
    """Return ONLY kept, non-deleted memory entries for ``user_id``.

    This is the **only** function that feeds memory into an autonomous
    session's prompt context (ADR-0013 D4 — no silent kept writes;
    the agent only proposes).  Callers MUST NOT bypass this function to
    inject memory directly.

    Args:
        db: Active async ORM session.
        user_id: The user whose memory entries to load.

    Returns:
        List of :class:`~app.models.autonomous.AutonomousMemory` rows
        with ``state='kept'`` and ``deleted_at IS NULL``, ordered by
        ``kept_at DESC`` (most-recently kept first).
    """
    stmt = (
        select(AutonomousMemory)
        .where(
            AutonomousMemory.user_id == user_id,
            AutonomousMemory.state == "kept",
            AutonomousMemory.deleted_at.is_(None),
        )
        .order_by(AutonomousMemory.kept_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)
