"""ARQ worker function for the Easy Playbook generation pipeline — M3-A6 Phase 5.

The POST /api/v1/playbooks/easy handler creates an
:class:`EasyPlaybookGeneration` row at ``status='pending'`` and
enqueues this job (via :func:`app.workers.queue.enqueue_easy_playbook_generation_job`)
onto the dedicated ``arq:m3a6`` queue. The M3-A6 worker container
(see ``docker-compose.yml::arq-worker`` and
:mod:`app.workers.arq_setup`) picks it up and runs the algorithm
pipeline assembled in Phases 3+4:

* extract clauses per document via :func:`extract_clauses_from_document`
  (Phase 3 — :mod:`app.playbooks.easy.extractor`);
* cluster across the corpus via :func:`cluster_clauses_by_issue`
  (Phase 4 — :mod:`app.playbooks.easy.clustering`);
* assemble a :class:`PlaybookCreate` via :func:`assemble_playbook`
  (Phase 4 — :mod:`app.playbooks.easy.assembly`);

…then writes the result back to the generation row. The wizard's
Step 2 polling endpoint (GET /api/v1/playbooks/easy/{id}) surfaces
the row's current state to the UI; Step 3 binds the inline editor
to ``draft_playbook`` once status reaches ``completed``.

Per the M3-A6 quality bar reframe, the assembled playbook is a
*starting point* the user-attorney edits during Step 3. Worker
"success" means the pipeline produced a structurally-valid
``PlaybookCreate`` — not that the playbook is correct, complete, or
fit for use without review.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient
from app.db.session import get_session_factory
from app.models.document import Document
from app.models.playbook import EasyPlaybookGeneration
from app.playbooks.easy.assembly import assemble_playbook
from app.playbooks.easy.clustering import ClauseInput, cluster_clauses_by_issue
from app.playbooks.easy.extractor import extract_clauses_from_document

logger = logging.getLogger(__name__)


# Function name registered on the M3-A6 worker — must match the constant
# in :mod:`app.workers.queue` so the api-side enqueue helper targets the
# right function on the right queue.
EASY_PLAYBOOK_JOB_NAME = "easy_playbook_generation_job"


async def easy_playbook_generation_job(
    ctx: dict[str, Any], generation_id_str: str
) -> dict[str, Any]:
    """ARQ job — run the Easy Playbook generation pipeline for one row.

    Updates the row's lifecycle:

    * On entry: ``pending → running``; sets ``started_at``.
    * On success: ``running → completed``; sets ``completed_at`` and
      ``draft_playbook`` to the assembled ``PlaybookCreate.model_dump()``.
    * On any unhandled exception: ``running → error``; sets
      ``completed_at`` and ``error_message``; ``draft_playbook`` may
      be ``None`` or carry partial output depending on where the
      pipeline raised.

    Returns a small dict for arq's result-tracking (visible via arq's
    CLI). All real state lives on the generation row; the return
    value is for log fields and operator observability.
    """

    generation_id = uuid.UUID(generation_id_str)
    logger.info(
        "easy_playbook_worker: job start",
        extra={
            "event": "easy_playbook_worker_start",
            "generation_id": generation_id_str,
        },
    )

    factory = get_session_factory()
    gateway = _gateway_from_ctx(ctx)

    async with factory() as session:
        generation = await session.get(EasyPlaybookGeneration, generation_id)
        if generation is None:
            logger.warning(
                "easy_playbook_worker: row not found; nothing to do",
                extra={
                    "event": "easy_playbook_worker_row_missing",
                    "generation_id": generation_id_str,
                },
            )
            return {"generation_id": generation_id_str, "status": "missing"}

        generation.status = "running"
        generation.started_at = datetime.now(tz=UTC)
        await session.commit()

        try:
            await _run_pipeline(
                session=session,
                generation=generation,
                gateway=gateway,
            )
        except BaseException as exc:
            # BaseException (not Exception) so the cancellation path
            # ARQ uses on job_timeout still marks the row as error
            # rather than leaving it stuck at 'running'. The previous
            # `except Exception` swallowed normal failures but let
            # asyncio.CancelledError / TimeoutError propagate, which
            # crash-cancelled the task mid-write and left orphans.
            logger.exception(
                "easy_playbook_worker: pipeline failed",
                extra={
                    "event": "easy_playbook_worker_error",
                    "generation_id": generation_id_str,
                    "error_type": type(exc).__name__,
                },
            )
            generation.status = "error"
            generation.error_message = f"{type(exc).__name__}: {exc}"
            generation.completed_at = datetime.now(tz=UTC)
            await session.commit()
            # Re-raise BaseException subclasses (CancelledError,
            # SystemExit, KeyboardInterrupt) after the bookkeeping
            # write so arq's shutdown machinery still sees the cancel.
            if not isinstance(exc, Exception):
                raise
            return {
                "generation_id": generation_id_str,
                "status": "error",
                "error": str(exc),
            }

        logger.info(
            "easy_playbook_worker: job complete",
            extra={
                "event": "easy_playbook_worker_complete",
                "generation_id": generation_id_str,
            },
        )
        return {"generation_id": generation_id_str, "status": "completed"}


# ---------------------------------------------------------------------------
# Pipeline internals
# ---------------------------------------------------------------------------


async def _run_pipeline(
    *,
    session: AsyncSession,
    generation: EasyPlaybookGeneration,
    gateway: GatewayClient,
) -> None:
    """Run extract → cluster → assemble and write the result to the row.

    Document-level extraction failures are tolerated — a single bad
    document degrades clustering signal but does not kill the whole
    run. A 0-clause corpus (every document yielded nothing) still
    completes with an empty playbook; the wizard's UI will surface
    "no positions detected" so the user-attorney knows the corpus
    was too thin or non-contract.
    """

    documents = await _load_documents(session, generation.document_ids)
    contract_type = generation.contract_type

    all_clauses: list[ClauseInput] = []
    for document in documents:
        try:
            extracted = await extract_clauses_from_document(
                document=document,
                gateway=gateway,
                contract_type=contract_type,
            )
        except Exception as exc:
            logger.warning(
                "easy_playbook_worker: per-document extraction failed; continuing",
                extra={
                    "event": "easy_playbook_worker_extract_failed",
                    "generation_id": str(generation.id),
                    "document_id": str(document.id),
                    "error_type": type(exc).__name__,
                },
            )
            continue
        for clause in extracted:
            all_clauses.append(
                ClauseInput(
                    document_id=document.id,
                    issue=clause.issue,
                    clause_text=clause.clause_text,
                    source_offsets=clause.source_offsets,
                )
            )

    clusters = await cluster_clauses_by_issue(
        clauses=all_clauses,
        gateway=gateway,
    )

    playbook_name = _default_playbook_name(contract_type)
    draft = await assemble_playbook(
        clusters=clusters,
        name=playbook_name,
        contract_type=contract_type,
        gateway=gateway,
    )

    generation.draft_playbook = draft.model_dump(mode="json")
    generation.status = "completed"
    generation.completed_at = datetime.now(tz=UTC)
    await session.commit()


async def _load_documents(
    session: AsyncSession,
    document_ids: list[uuid.UUID],
) -> list[Document]:
    """Load every Document by id; preserve ``document_ids`` order.

    Missing rows (e.g., the source file was soft-deleted between
    enqueue and worker pickup) are silently skipped — the run continues
    with whatever documents are still resolvable. The corpus snapshot
    on ``EasyPlaybookGeneration.document_ids`` is the authoritative
    record of what the user requested.
    """

    if not document_ids:
        return []
    stmt = select(Document).where(Document.id.in_(document_ids))
    rows = (await session.execute(stmt)).scalars().all()
    by_id = {row.id: row for row in rows}
    return [by_id[did] for did in document_ids if did in by_id]


def _default_playbook_name(contract_type: str) -> str:
    """Fallback name when the request body didn't supply one.

    The wizard's Step 1 collects a name; this is a guard for the
    direct-API caller that omitted it (also the Phase 5 enqueue
    helper's smoke-test path).
    """

    cleaned = contract_type.strip() or "Custom"
    return f"Generated {cleaned} Playbook"


def _gateway_from_ctx(ctx: dict[str, Any]) -> GatewayClient:
    """Resolve a :class:`GatewayClient` from the arq worker ``ctx``.

    The M3-A6 worker doesn't pre-populate ``ctx`` with a gateway
    client today (the existing ingest-worker doesn't either), so we
    build one on demand via the api's standard factory. Future
    optimization: hoist this into ``on_startup`` so every job
    reuses one client.
    """

    existing = ctx.get("gateway")
    if isinstance(existing, GatewayClient):
        return existing
    # Lazy import — keeps the worker module importable in environments
    # where the gateway client isn't yet configured.
    from app.clients.gateway import get_gateway_client

    return get_gateway_client()
