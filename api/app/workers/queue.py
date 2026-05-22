"""arq queue helpers — enqueue document-ingest jobs from the API process.

Per ADR 0006 §5: the API's upload handler enqueues an ingest job
after the file row is committed. This module is the API-side helper
for that path. The worker process consumes the queue (see
:mod:`app.workers.document_pipeline`).

Design notes
------------

* The arq queue connection is built from the same ``REDIS_URL`` the
  rest of the API uses (via ``get_settings()``). It's cached as a
  module-global so the API process pools the connection across
  requests rather than reconnecting per upload.
* Enqueue failures are non-fatal for the upload: the upload handler
  catches and logs at WARNING. A row stuck at ``pending`` will be
  swept up by the worker's startup re-enqueue (see
  :mod:`app.workers.document_pipeline`).
* The job name (``ingest_file_job``) is the function the worker
  invokes; the function lives on the worker side. We enqueue by
  string name to avoid pulling worker-only deps into the API
  process.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

log = logging.getLogger(__name__)

# Job-function name on the worker side. Must match the function name
# in :mod:`app.workers.document_pipeline`.
INGEST_JOB_NAME = "ingest_file_job"

EMBED_JOB_NAME = "embed_chunks_for_file_job"
"""C6 — embedding-on-write job for ``document_chunks`` of a single
file. Triggered on KB attachment (when the file has chunks with NULL
embeddings) and from the ingest-completion hook."""

EXPORT_USER_DATA_JOB_NAME = "export_user_data_job"
"""D6 — GDPR Article 20 export job. Triggered by the API when a user
calls ``POST /api/v1/users/me/export``; the worker assembles the ZIP
and writes it to MinIO under ``exports/<user_id>/<job_id>.zip``."""

EASY_PLAYBOOK_JOB_NAME = "easy_playbook_generation_job"
"""M3-A6 Phase 5 — Easy Playbook generation pipeline. Triggered by
the API when a user calls ``POST /api/v1/playbooks/easy``; the
playbook worker (see :mod:`app.workers.arq_setup`) consumes from the
shared playbook queue, walks the document corpus, and writes the
assembled draft playbook back to the ``easy_playbook_generations`` row."""

TABULAR_JOB_NAME = "tabular_execution_job"
"""M3-C2 — Tabular Review execution pipeline. Triggered by the API
when a user calls ``POST /api/v1/tabular/execute``; the playbook
worker consumes from the same shared queue as Easy Playbook (per
Decision C-3) and walks the documents x columns grid via the
LangGraph executor."""

M3_PLAYBOOK_QUEUE_NAME = "arq:m3a6"
"""Mirror of :data:`app.workers.arq_setup.M3_PLAYBOOK_QUEUE_NAME` (kept
here to avoid a circular import). Must stay in sync; a discrepancy
would queue jobs that the worker never sees. Queue string stays
``arq:m3a6`` for on-the-wire compatibility — only the Python constant
was renamed."""

M3A6_QUEUE_NAME = M3_PLAYBOOK_QUEUE_NAME
"""Backward-compat alias for the renamed :data:`M3_PLAYBOOK_QUEUE_NAME`.
Will be removed in a future release; new code should use
:data:`M3_PLAYBOOK_QUEUE_NAME`."""

_pool: Any = None
_m3a6_pool: Any = None
"""Separate pool whose ``default_queue_name`` targets the M3-A6 queue.
Keeps the api-side enqueue path symmetric with the worker side: jobs
the api enqueues onto this pool land on the queue the M3-A6 worker is
consuming from."""


async def _get_pool() -> Any:
    """Return a cached arq Redis pool, building it on first use.

    arq is imported lazily so the API process imports cleanly even
    when arq isn't installed (it's a runtime dep but we want the
    import path to fail loudly in tests where arq is mocked rather
    than failing at module import).
    """

    global _pool
    if _pool is not None:
        return _pool

    from arq import create_pool
    from arq.connections import RedisSettings

    from app.config import get_settings

    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    _pool = await create_pool(redis_settings)
    return _pool


async def close_pool() -> None:
    """Close the cached arq Redis pool(s). Idempotent.

    Closes both the default-queue pool (ingest path) and the M3-A6
    pool (easy-playbook path) so an FastAPI shutdown handler that
    calls this leaves no orphan connections.
    """

    global _pool, _m3a6_pool
    for name, pool in (("default", _pool), ("m3a6", _m3a6_pool)):
        if pool is None:
            continue
        try:
            await pool.aclose()
        except Exception as exc:  # pragma: no cover - shutdown best-effort
            log.warning("close_pool: arq %s pool close failed: %s", name, exc)
    _pool = None
    _m3a6_pool = None


async def _get_m3a6_pool() -> Any:
    """Return a cached arq Redis pool whose default queue is ``arq:m3a6``.

    Separate from :func:`_get_pool` so the api process can enqueue onto
    either queue without specifying ``_queue_name`` per call. Lazy
    import of ``arq`` so the api imports cleanly in test environments
    where arq is mocked.
    """

    global _m3a6_pool
    if _m3a6_pool is not None:
        return _m3a6_pool

    from arq import create_pool
    from arq.connections import RedisSettings

    from app.config import get_settings

    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    _m3a6_pool = await create_pool(redis_settings, default_queue_name=M3_PLAYBOOK_QUEUE_NAME)
    return _m3a6_pool


async def enqueue_ingest_job(file_id: uuid.UUID) -> bool:
    """Enqueue an ingest job for ``file_id``; return True on success.

    Failures are caught and logged — the caller (upload handler)
    treats failure as non-fatal. The row stays at ``pending`` and
    will be re-enqueued by the worker's startup sweep.
    """

    try:
        pool = await _get_pool()
        await pool.enqueue_job(INGEST_JOB_NAME, str(file_id))
        log.info(
            "enqueue_ingest_job: enqueued",
            extra={"event": "ingest_enqueue", "file_id": str(file_id)},
        )
        return True
    except Exception as exc:
        log.warning(
            "enqueue_ingest_job: failed; row stays pending",
            extra={
                "event": "ingest_enqueue_failed",
                "file_id": str(file_id),
                "error": str(exc),
            },
        )
        return False


async def enqueue_embed_job(file_id: uuid.UUID) -> bool:
    """Enqueue an embed-chunks job for ``file_id``; return True on success.

    Triggered from the KB attach handler when a newly-attached file has
    chunks with NULL embeddings. Failures are non-fatal — the lazy
    embed-on-read path in the query handler covers the gap.
    """

    try:
        pool = await _get_pool()
        await pool.enqueue_job(EMBED_JOB_NAME, str(file_id))
        log.info(
            "enqueue_embed_job: enqueued",
            extra={"event": "embed_enqueue", "file_id": str(file_id)},
        )
        return True
    except Exception as exc:
        log.warning(
            "enqueue_embed_job: failed; embed-on-read will cover at query time",
            extra={
                "event": "embed_enqueue_failed",
                "file_id": str(file_id),
                "error": str(exc),
            },
        )
        return False


async def enqueue_easy_playbook_generation_job(generation_id: uuid.UUID) -> bool:
    """Enqueue an Easy Playbook generation job onto the shared playbook queue.

    Returns True on success, False on transport / import failure
    (matching the other ``enqueue_*`` helpers' best-effort posture).
    The POST handler logs at WARNING on failure but does NOT roll back
    the row — the wizard's UI polls the generation row regardless, and
    an operator can re-enqueue manually if needed.
    """

    try:
        pool = await _get_m3a6_pool()
        await pool.enqueue_job(EASY_PLAYBOOK_JOB_NAME, str(generation_id))
        log.info(
            "enqueue_easy_playbook_generation_job: enqueued",
            extra={
                "event": "easy_playbook_enqueue",
                "generation_id": str(generation_id),
            },
        )
        return True
    except Exception as exc:
        log.warning(
            "enqueue_easy_playbook_generation_job: failed; row stays pending",
            extra={
                "event": "easy_playbook_enqueue_failed",
                "generation_id": str(generation_id),
                "error": str(exc),
            },
        )
        return False


async def enqueue_tabular_execution_job(execution_id: uuid.UUID) -> bool:
    """Enqueue a Tabular Review execution job onto the shared playbook queue.

    Shares the M3-A6-original queue with Easy Playbook per Decision C-3
    (one shared worker container for both long-running playbook /
    tabular workloads).

    Returns True on success, False on transport / import failure. The
    POST handler logs at WARNING on failure but does NOT roll back
    the row — the result-view polls regardless, and an operator can
    re-enqueue manually if the row is stuck at ``pending``.
    """

    try:
        pool = await _get_m3a6_pool()
        await pool.enqueue_job(TABULAR_JOB_NAME, str(execution_id))
        log.info(
            "enqueue_tabular_execution_job: enqueued",
            extra={
                "event": "tabular_execution_enqueue",
                "execution_id": str(execution_id),
            },
        )
        return True
    except Exception as exc:
        log.warning(
            "enqueue_tabular_execution_job: failed; row stays pending",
            extra={
                "event": "tabular_execution_enqueue_failed",
                "execution_id": str(execution_id),
                "error": str(exc),
            },
        )
        return False


async def enqueue_user_export_job(job_id: uuid.UUID) -> bool:
    """Enqueue a D6 GDPR export job; return True on success.

    Failures here surface to the API endpoint which keeps the job row
    at ``status='queued'`` and returns 202 to the caller (the user can
    retry). The status-poll endpoint will report queued indefinitely
    until the worker picks it up — operators monitoring the
    ``user_export_jobs`` table for stale rows can re-enqueue manually.
    """

    try:
        pool = await _get_pool()
        await pool.enqueue_job(EXPORT_USER_DATA_JOB_NAME, str(job_id))
        log.info(
            "enqueue_user_export_job: enqueued",
            extra={"event": "user_export_enqueue", "job_id": str(job_id)},
        )
        return True
    except Exception as exc:
        log.warning(
            "enqueue_user_export_job: failed; job stays queued",
            extra={
                "event": "user_export_enqueue_failed",
                "job_id": str(job_id),
                "error": str(exc),
            },
        )
        return False
