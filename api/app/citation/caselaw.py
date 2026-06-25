"""Caselaw quote verification (P1-A1).

Extracts blockquote passages from an assistant answer, locates each verbatim in
a consulted CourtListener opinion's stored plaintext, runs the existing citation
cascade (deterministic stages 1-2), and persists verified rows.
See docs/superpowers/specs/2026-06-24-p1a1-external-caselaw-quote-verification-design.md.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tool_loop import ToolSourceRecord
from app.citation.verification import verify
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.research import ResearchOpinionMetadata
from app.research.service import read_opinion


def extract_blockquote_passages(answer_text: str) -> list[str]:
    """Return the text of each markdown blockquote in ``answer_text``.

    The case-law-research skill renders each cited passage as a markdown
    blockquote (``> ...``) under a "Relevant passage:" header. Consecutive
    blockquote lines are one passage (wrapped quote); a non-blockquote line
    ends the current passage.
    """
    passages: list[str] = []
    current: list[str] = []
    for line in answer_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(">"):
            current.append(stripped[1:].strip())
        elif current:
            joined = " ".join(p for p in current if p).strip()
            if joined:
                passages.append(joined)
            current = []
    if current:
        joined = " ".join(p for p in current if p).strip()
        if joined:
            passages.append(joined)
    return passages


# Stable namespace so a given opinion_id maps to a deterministic synthetic id.
_OPINION_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")


@dataclass(slots=True)
class _OpinionVerificationTarget:
    """Adapts a stored opinion to the verifier's document protocol (no DB row)."""

    id: uuid.UUID
    normalized_content: str
    was_ocrd: bool = False


@dataclass(slots=True)
class _CaselawCandidate:
    """A located quote span, shaped for the verifier's candidate protocol."""

    source_offset_start: int
    source_offset_end: int
    source_text: str
    source_document_id: uuid.UUID


def opinion_target(opinion_id: int, text: str) -> _OpinionVerificationTarget:
    return _OpinionVerificationTarget(
        id=uuid.uuid5(_OPINION_NS, str(opinion_id)),
        normalized_content=text,
        was_ocrd=False,
    )


def locate_passage(passage: str, opinion_text: str) -> tuple[int, int] | None:
    """Exact-substring offsets of ``passage`` in ``opinion_text``, or None.

    v1 locates verbatim spans only; the cascade confirms them as ``exact_match``.
    A whitespace-tolerant locator (feeding stage-2) is a noted follow-on.
    """
    needle = passage.strip()
    if not needle:
        return None
    idx = opinion_text.find(needle)
    if idx < 0:
        return None
    return idx, idx + len(needle)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

log = logging.getLogger(__name__)

_LoadOpinionText = Callable[[AsyncSession, int], Awaitable[str]]


async def _default_load_opinion_text(db: AsyncSession, opinion_id: int) -> str:
    result: dict[str, Any] = await read_opinion(db, opinion_id=opinion_id)
    return result["text"]


async def verify_and_persist_caselaw_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    assistant_text: str,
    tool_sources: Sequence[ToolSourceRecord],
    load_opinion_text: _LoadOpinionText = _default_load_opinion_text,
) -> int:
    """Verify verbatim caselaw quotes in ``assistant_text`` and persist verified rows.

    Deterministic stages 1-2 only (``gateway=None``). Returns the row count.
    Never raises on a per-opinion failure (conservative posture): a load miss is
    logged and skipped, and the turn proceeds with whatever verified.
    """
    cluster_ids = {
        int(r.external_ref)
        for r in tool_sources
        if r.source_kind == "caselaw" and r.external_ref and r.external_ref.isdigit()
    }
    if not cluster_ids:
        return 0
    passages = extract_blockquote_passages(assistant_text)
    if not passages:
        return 0
    opinions = (
        (
            await db.execute(
                select(ResearchOpinionMetadata).where(
                    ResearchOpinionMetadata.cluster_id.in_(cluster_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    if not opinions:
        return 0

    # Read each consulted opinion's text once (skip unreadable).
    texts: list[tuple[ResearchOpinionMetadata, str]] = []
    for op in opinions:
        try:
            texts.append((op, await load_opinion_text(db, op.opinion_id)))
        except Exception as exc:  # storage miss / not-fetched — never fatal
            log.warning("caselaw verify: could not load opinion %s: %r", op.opinion_id, exc)

    rows: list[MessageCaselawCitation] = []
    for passage in passages:
        for op, text in texts:
            loc = locate_passage(passage, text)
            if loc is None:
                continue
            start, end = loc
            target = opinion_target(op.opinion_id, text)
            candidate = _CaselawCandidate(
                source_offset_start=start,
                source_offset_end=end,
                source_text=passage,
                source_document_id=target.id,
            )
            result = await verify(candidate, target, gateway=None)
            if not result.verified:
                continue
            rows.append(
                MessageCaselawCitation(
                    message_id=message_id,
                    opinion_id=op.opinion_id,
                    cluster_id=op.cluster_id,
                    source_offset_start=start,
                    source_offset_end=end,
                    source_text=passage,
                    verified=True,
                    verification_method=result.method,
                    verification_confidence=result.confidence,
                    partial=result.partial,
                )
            )
            break  # one verified row per passage (first matching opinion wins)

    if rows:
        db.add_all(rows)
        await db.flush()
    return len(rows)
