"""arq job — derive citation-graph treatment for an assistant turn (WS-G PR1/PR2).

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
from app.clients.gateway import GatewayClient, get_gateway_client
from app.db.session import get_session_factory

log = logging.getLogger(__name__)


async def run_treatment_derivation(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    fetch_citing: _FetchCiting = _default_fetch_citing,
    gateway: GatewayClient | None = None,
) -> int:
    """Session-injected core (testable without arq/Redis).

    Resolves a gateway + judge model for the PR2 judge pass; degrades to
    graph-only (``gateway=None``) if the gateway or judge-model can't be
    resolved (e.g. worker running without gateway config).

    The ``gateway`` kwarg allows test injection; when omitted the
    process-global :func:`get_gateway_client` is used.

    Calls ``derive_treatment_for_message`` with a UTC-aware *now*, then
    commits the session. Returns the number of ledger entries linked.
    """
    # _gw is always a GatewayClient (ternary guarantees it); the separate
    # derive_gateway variable starts as _gw and is cleared to None in the
    # degrade path so mypy can track both states cleanly.
    _gw: GatewayClient = gateway if gateway is not None else get_gateway_client()
    judge_model = "fast"
    derive_gateway: GatewayClient | None = _gw
    try:
        judge_model = await _gw.get_citation_engine_judge_model()
    except Exception as exc:
        log.warning(
            "treatment judge-model resolve failed; degrading to graph-only: %r",
            exc,
            extra={"event": "treatment_judge_model_unavailable"},
        )
        derive_gateway = None

    linked = await derive_treatment_for_message(
        db,
        message_id=message_id,
        now=datetime.now(UTC),
        fetch_citing=fetch_citing,
        gateway=derive_gateway,
        judge_model=judge_model,
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
