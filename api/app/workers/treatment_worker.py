"""arq job — derive citation-graph treatment for an assistant turn (WS-G PR1).

Runs OFF the turn's critical path: enqueued best-effort after each assistant
turn finalizes (see ``app.api.chats``), consumed by the ingest worker.
Mirrors the ``ingest_file_job`` session-factory pattern.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.treatment import _default_fetch_citing, _FetchCiting, derive_treatment_for_message
from app.db.session import get_session_factory

log = logging.getLogger(__name__)


async def run_treatment_derivation(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    fetch_citing: _FetchCiting = _default_fetch_citing,
) -> int:
    """Session-injected core (testable without arq/Redis).

    Calls ``derive_treatment_for_message`` with a UTC-aware *now*, then
    commits the session. Returns the number of ledger entries linked.
    """
    linked = await derive_treatment_for_message(
        db,
        message_id=message_id,
        now=datetime.now(UTC),
        fetch_citing=fetch_citing,
    )
    await db.commit()
    return linked


async def treatment_derivation_job(ctx: dict[str, Any], message_id_str: str) -> dict[str, Any]:
    """arq entrypoint — opens a session, runs derivation, commits.

    The outer try/except is the backstop for session-level and flush
    failures; it ensures the worker never crashes on a single bad turn.
    """
    message_id = uuid.UUID(message_id_str)
    try:
        factory = get_session_factory()
        async with factory() as db:
            linked = await run_treatment_derivation(db, message_id=message_id)
    except Exception as exc:  # outer guard: session-level/flush failures
        log.warning(
            "treatment_derivation_job failed for %s: %r",
            message_id,
            exc,
            extra={"event": "treatment_derivation_failed", "message_id": message_id_str},
        )
        return {"message_id": message_id_str, "linked": 0, "ok": False}
    log.info(
        "treatment_derivation_job complete",
        extra={
            "event": "treatment_derivation_complete",
            "message_id": message_id_str,
            "linked": linked,
        },
    )
    return {"message_id": message_id_str, "linked": linked, "ok": True}
