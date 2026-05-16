"""Backfill ``documents.normalized_content`` from existing chunks — M2-A1.

The M2-A1 migration adds ``normalized_content TEXT NOT NULL DEFAULT ''``
to the ``documents`` table. New ingests populate it directly from the
PyMuPDF canonical text. Pre-M2 rows land with the empty-string default
and need backfilling — this module is what fills them.

The reconstruction algorithm walks chunks in order of
``char_offset_start`` and appends only the suffix that extends beyond
the running end position. That handles the chunker's overlap (default
200 chars) correctly: overlapping ranges represent the *same* bytes,
and we only need each byte once. A gap between consecutive chunks is
flagged rather than silently filled — corrupt reconstruction is a
worse failure than skipped reconstruction, because the Citation Engine
re-reads ``normalized_content`` at chunk offsets and would compare
against wrong bytes.

The module is split into two layers so the algorithm is unit-testable
without touching a database:

* :func:`reconstruct_from_chunks` — pure function, takes a list of
  :class:`DocumentChunk` and returns ``(text, has_gap)``.
* :func:`backfill_documents` — async DB walker that finds candidate
  documents, loads their chunks, calls the pure function, and writes
  the result back. Skips rows already populated unless ``force=True``.

The thin CLI wrapper lives at ``scripts/backfill_normalized_content.py``
at the repo root so the script appears where the M2 plan said it would.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BackfillReport:
    """Summary of a backfill run.

    ``processed`` rows had their ``normalized_content`` written.
    ``skipped`` rows were already populated (and ``force`` was False).
    ``gaps`` rows had a gap between consecutive chunks — they are
    logged and left untouched so the operator can investigate; the
    Citation Engine treats an empty ``normalized_content`` as "cannot
    verify" rather than verifying against the wrong text.
    """

    processed: int = 0
    skipped: int = 0
    gaps: int = 0


# ---------------------------------------------------------------------------
# Pure algorithm
# ---------------------------------------------------------------------------


def reconstruct_from_chunks(chunks: Iterable[DocumentChunk]) -> tuple[str, bool]:
    """Reconstruct canonical text from a document's chunks.

    Walks chunks in order of ``char_offset_start`` and appends only the
    portion of each chunk that extends beyond the running end position.
    Overlapping ranges (the chunker emits a configurable overlap) are
    folded together — the overlap region is appended exactly once.

    Args:
        chunks: One document's :class:`DocumentChunk` rows, any order.

    Returns:
        ``(text, has_gap)``. ``has_gap`` is True if any chunk starts
        beyond the running end position — i.e. there's a range of the
        original document that no chunk covers. The reconstruction is
        best-effort in that case; callers should skip writing rather
        than persisting partial text.
    """

    sorted_chunks = sorted(chunks, key=lambda c: c.char_offset_start)
    if not sorted_chunks:
        return "", False

    parts: list[str] = []
    cur_end = 0
    has_gap = False

    for chunk in sorted_chunks:
        start = chunk.char_offset_start
        end = chunk.char_offset_end

        if start > cur_end:
            # Gap. Flag but continue assembling — the caller decides
            # whether to persist or skip.
            has_gap = True
            parts.append(chunk.content)
            cur_end = end
        elif end <= cur_end:
            # Fully contained in what we've already collected.
            continue
        else:
            # Overlap or perfect adjacency.
            overlap = cur_end - start
            parts.append(chunk.content[overlap:])
            cur_end = end

    return "".join(parts), has_gap


# ---------------------------------------------------------------------------
# Async DB walker
# ---------------------------------------------------------------------------


async def backfill_documents(
    db: AsyncSession,
    *,
    force: bool = False,
) -> BackfillReport:
    """Reconstruct ``normalized_content`` for every document that needs it.

    Args:
        db: An active :class:`AsyncSession`. The function commits per
            document so a long-running backfill can be interrupted and
            resumed without losing the rows already written.
        force: When True, re-process rows whose ``normalized_content``
            is already non-empty. The default is to skip them — the
            common case is the one-time migration from pre-M2 state.

    Returns:
        :class:`BackfillReport` summarising the run.
    """

    report = BackfillReport()

    # Load every document and decide per-row whether to process or
    # skip. Backfills run rarely and the documents table is small
    # relative to the chunks table — there's no efficiency win from
    # filtering in SQL, and we lose the "skipped" count operators rely
    # on to confirm the script saw the rows they expected.
    rows = (await db.execute(select(Document))).scalars().all()

    for doc in rows:
        # ``normalized_content == ''`` is the canonical "needs backfill"
        # marker; when ``force=True`` we re-process every row regardless.
        if not force and doc.normalized_content != "":
            report.skipped += 1
            continue

        chunk_rows = (
            (await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)))
            .scalars()
            .all()
        )

        text, has_gap = reconstruct_from_chunks(chunk_rows)

        if has_gap:
            log.warning(
                "backfill: gap detected in chunks; skipping document",
                extra={
                    "event": "backfill_gap_detected",
                    "document_id": str(doc.id),
                    "chunk_count": len(chunk_rows),
                },
            )
            report.gaps += 1
            continue

        doc.normalized_content = text
        await db.commit()
        report.processed += 1

        log.info(
            "backfill: populated normalized_content",
            extra={
                "event": "backfill_document_populated",
                "document_id": str(doc.id),
                "chars": len(text),
                "chunk_count": len(chunk_rows),
            },
        )

    return report
