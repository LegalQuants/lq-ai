"""The files a run's knowledge-base searches found, by source number (ADR 0038 D5).

A selected document is numbered when the request is accepted and is in the
plan. A knowledge-base file is not known until a task's search finds it, so it
is numbered then, inside that task's own block of numbers
(:func:`app.autonomous.orchestration.tools.source_block`), and the number is
written in the search step's receipt with the file's identifiers and name.
Nothing else records it: this module reads the numbers back from those
receipts.

Three readers use it. The check on a delivered answer resolves a quotation's
``(Source: [N])`` marker to the file it names. The owner's view of a run lists
the sources. A later run's thread excerpt rewrites an earlier answer's markers
to file names, because numbers are per run.

A receipt holds identifiers, numbers and the owner's own file names. It never
holds passage text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orchestration import (
    OrchestrationAccount as Account,
    OrchestrationEffect as Effect,
)

SEARCH_STEP = "knowledge_search"


@dataclass(frozen=True)
class RunSource:
    """One knowledge-base file a task's search found, with the number it was given."""

    number: int
    file_id: UUID
    document_id: UUID
    filename: str
    # The task whose search found it.
    session_id: UUID


def step_sources(session_id: UUID, step: Any) -> list[RunSource]:
    """The sources one settled search step's note recorded. Malformed entries are skipped."""
    if not isinstance(step, dict) or step.get("kind") != SEARCH_STEP:
        return []
    summary = step.get("summary")
    found = []
    for entry in (summary.get("sources") if isinstance(summary, dict) else None) or ():
        try:
            number = entry["number"]
            if type(number) is not int or not 1 <= number <= 999:
                continue
            found.append(
                RunSource(
                    number=number,
                    file_id=UUID(str(entry["file_id"])),
                    document_id=UUID(str(entry["document_id"])),
                    filename=str(entry.get("filename") or "")[:256],
                    session_id=session_id,
                )
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return found


async def run_sources(db: AsyncSession, root_id: UUID) -> list[RunSource]:
    """Every knowledge-base source of one run, in number order.

    Read from the completed search steps of the run's sessions. A number is
    recorded by one task only, so the first record of a number is the only one.

    Only the step note is read, and only for search steps. The same column
    holds the text a document read or a search returned, which this must not
    load on every view of a run.
    """
    note = Effect.result["step"]
    rows = (
        await db.execute(
            select(Effect.session_id, note)
            .join(Account, Account.session_id == Effect.session_id)
            .where(
                Account.root_id == root_id,
                Effect.status == "completed",
                Effect.intent == "retrieve_chunks",
                note["kind"].astext == SEARCH_STEP,
            )
            .order_by(Effect.created_at, Effect.effect_key)
        )
    ).all()
    by_number: dict[int, RunSource] = {}
    for session_id, step in rows:
        for source in step_sources(session_id, step):
            by_number.setdefault(source.number, source)
    return [by_number[number] for number in sorted(by_number)]
