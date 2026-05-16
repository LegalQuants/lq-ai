"""One-time backfill of ``documents.normalized_content`` from chunks — M2-A1.

The M2-A1 migration adds ``normalized_content`` and ``was_ocrd`` to the
``documents`` table with safe defaults so deploys don't block. Pre-M2
documents land with the empty-string default; this script reconstructs
their text from the existing chunks so the M2 Citation Engine has a
canonical source to re-read at chunk offsets.

Usage (from inside the API container):

    docker compose exec api python /app/scripts/backfill_normalized_content.py
    docker compose exec api python /app/scripts/backfill_normalized_content.py --force

By default the script skips documents whose ``normalized_content`` is
already non-empty. ``--force`` re-processes every row — only use it if
you suspect a previous backfill produced wrong text and you've worked
out why.

The reconstruction is overlap-aware. If a document's chunks have a gap
(no chunk covers some byte range of the original) the document is
left untouched and the operator is asked to investigate. Corrupt
``normalized_content`` is worse than missing ``normalized_content``:
the Citation Engine compares against it byte-for-byte.

Exit codes:
    0  — success (any combination of processed/skipped/gaps reported).
    1  — unrecoverable error (DB connection failure, etc.).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.pipeline.normalized_backfill import backfill_documents

log = logging.getLogger("backfill_normalized_content")


async def _run(force: bool) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            report = await backfill_documents(session, force=force)
    finally:
        await engine.dispose()

    log.info(
        "backfill complete: processed=%d, skipped=%d, gaps=%d",
        report.processed,
        report.skipped,
        report.gaps,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill documents.normalized_content from existing chunks (M2-A1)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process documents whose normalized_content is already populated.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        return asyncio.run(_run(force=args.force))
    except Exception as exc:
        log.error("backfill failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
