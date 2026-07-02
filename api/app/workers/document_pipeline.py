"""Document-pipeline ``arq`` worker — Task C5 (+ D6 cron jobs).

Run as a separate process via the docker-compose ``ingest-worker``
service::

    arq app.workers.document_pipeline.WorkerSettings

The worker:

1. On startup, opens a SQLAlchemy session-factory and an arq queue
   handle, then runs a sweep of any files stuck in ``pending`` /
   ``processing`` and re-enqueues them. This is self-healing across
   restarts: if a previous worker crashed mid-job and left a row at
   ``processing``, the next worker picks it up.
2. Consumes ingest jobs by file_id. Each job runs
   :func:`app.pipeline.ingest.ingest_file` against a fresh DB session.
3. Errors raised inside ``ingest_file`` (storage failures) bubble up
   to arq's retry mechanism. Failures inside the parser cascade
   are caught by ``ingest_file`` itself and translate to
   ``ingestion_status='failed'`` rather than retries.
4. Hosts the D6 GDPR jobs alongside the ingest pipeline:
   :func:`app.workers.user_export.export_user_data_job` (queued from
   the API on POST /users/me/export), :func:`...export_gc_job`
   (hourly cron sweeping expired bundles), and
   :func:`app.workers.user_deletion.hard_delete_due_users_job` (daily
   cron). Keeping all M1 background work in one worker process is
   simpler than running a separate cron container; the job-functions
   are independent enough that lock contention isn't a concern at
   single-tenant deployment scale.

Concurrency is configured via :data:`LQ_AI_INGEST_WORKER_CONCURRENCY`
in the settings. The default of 2 is conservative — bump it for
beefier deployments.

The worker keeps the API's :mod:`app.errors` hierarchy in scope so
exceptions from shared helpers render consistently in logs.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, ClassVar

from app.config import get_settings
from app.db.session import dispose_engine, get_session_factory
from app.pipeline.ingest import find_orphaned_files, ingest_file
from app.workers.treatment_worker import treatment_derivation_job
from app.workers.user_deletion import hard_delete_due_users_job
from app.workers.user_export import export_gc_job, export_user_data_job

log = logging.getLogger(__name__)

# DE-351: arq's hard ``job_timeout`` is set strictly ABOVE the in-job docling
# soft timeout (``app.pipeline.ingest`` wraps the parse in ``asyncio.wait_for``
# at ``lq_ai_docling_timeout_seconds``). The buffer guarantees the soft path
# fires first and can persist a terminal ``failed`` row, rather than arq
# killing the worker mid-parse and leaving the file stuck in ``processing``.
_ARQ_JOB_TIMEOUT_BUFFER_SECONDS = 60


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------


async def ingest_file_job(ctx: dict[str, Any], file_id_str: str) -> dict[str, Any]:
    """Worker job: ingest a single file by id.

    The arq job-function signature is ``async def f(ctx, *args)`` —
    ``ctx`` carries the worker-startup state and arq metadata.

    The function returns a dict for arq's result-tracking (visible via
    arq's CLI / monitoring). Errors raised inside are arq-retried per
    the configured retry policy.
    """

    file_id = uuid.UUID(file_id_str)
    log.info(
        "worker: ingest job start",
        extra={"event": "worker_ingest_start", "file_id": file_id_str},
    )

    factory = get_session_factory()
    async with factory() as session:
        result = await ingest_file(session, file_id)

    # C6: enqueue an embed-chunks job after a successful ingest so
    # newly-written chunks land in the vector index without waiting for
    # the next KB-attach call. Best-effort; failures here don't block
    # the ingest result. The job itself is a no-op if no chunks need
    # embedding (idempotent).
    if result.status == "ready":
        redis = ctx.get("redis")
        if redis is not None:
            try:
                await redis.enqueue_job("embed_chunks_for_file_job", file_id_str)
            except Exception as exc:
                log.warning(
                    "worker: failed to enqueue embed job after ingest",
                    extra={
                        "event": "worker_embed_enqueue_failed",
                        "file_id": file_id_str,
                        "error": str(exc),
                    },
                )

    return {
        "file_id": str(result.file_id),
        "status": result.status,
        "document_id": (str(result.document_id) if result.document_id is not None else None),
        "chunk_count": result.chunk_count,
        "parser": result.parser,
        "error": result.error,
    }


async def embed_chunks_for_file_job(
    ctx: dict[str, Any],
    file_id_str: str,
) -> dict[str, Any]:
    """Worker job: embed every NULL-embedding chunk of a file (C6).

    Idempotent — the underlying ``embed_chunks_for_file`` filters on
    ``embedding IS NULL`` so a re-run is a no-op when nothing needs
    embedding. Failures (gateway down, OpenAI 429, etc.) bubble to
    arq's retry mechanism; partial-success state is preserved (chunks
    that did get embedded stay embedded).
    """

    file_id = uuid.UUID(file_id_str)
    log.info(
        "worker: embed job start",
        extra={"event": "worker_embed_start", "file_id": file_id_str},
    )

    factory = get_session_factory()
    async with factory() as session:
        from app.knowledge.embed import embed_chunks_for_file

        result = await embed_chunks_for_file(session, file_id)

    return {
        "file_id": str(result.file_id),
        "chunks_embedded": result.chunks_embedded,
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# Worker startup / shutdown
# ---------------------------------------------------------------------------


async def on_startup(ctx: dict[str, Any]) -> None:
    """Worker startup hook — log version, sweep stuck rows.

    The sweep handles two cases:

    * A previous worker crashed mid-job and left rows at
      ``processing``. We re-enqueue them.
    * A previous API process couldn't reach Redis when an upload
      completed and its row stayed at ``pending``. We pick those
      up too.

    The sweep is best-effort: a DB outage at startup logs a warning
    and continues — the worker will start consuming any future
    arq-queued jobs as soon as Redis is reachable.
    """

    log.info("worker startup: starting document-pipeline worker")
    factory = get_session_factory()
    try:
        async with factory() as session:
            orphaned = await find_orphaned_files(session)
        if orphaned:
            log.info(
                "worker startup: re-enqueuing %d orphaned file(s)",
                len(orphaned),
                extra={
                    "event": "worker_startup_sweep",
                    "count": len(orphaned),
                },
            )
            redis = ctx.get("redis")
            if redis is None:  # pragma: no cover - arq always provides this
                log.warning("worker startup: no redis in ctx; cannot re-enqueue")
                return
            for file_id in orphaned:
                try:
                    await redis.enqueue_job("ingest_file_job", str(file_id))
                except Exception as exc:
                    log.warning(
                        "worker startup: re-enqueue failed for %s: %s",
                        file_id,
                        exc,
                    )
    except Exception as exc:
        log.warning("worker startup: sweep failed: %s (continuing)", exc)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """Worker shutdown hook — dispose the DB engine."""

    log.info("worker shutdown: disposing DB engine")
    try:
        await dispose_engine()
    except Exception as exc:  # pragma: no cover - shutdown best-effort
        log.warning("worker shutdown: dispose_engine failed: %s", exc)


# ---------------------------------------------------------------------------
# arq WorkerSettings — discovered by `arq <module>.WorkerSettings`
# ---------------------------------------------------------------------------


def _build_redis_settings() -> Any:
    """Build arq's RedisSettings from our REDIS_URL.

    arq's :class:`arq.connections.RedisSettings.from_dsn` accepts our
    URL format directly. The function is wrapped so the import is
    deferred (so this module imports cleanly when arq isn't installed
    in environments where the worker isn't running).
    """

    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(get_settings().redis_url)


def _build_cron_jobs() -> list[Any]:
    """Build arq's cron_jobs list. Lazy import keeps arq optional at module load."""

    from arq import cron

    return [
        # Hourly: clear expired user-export bundles from MinIO + the
        # user_export_jobs row's storage_key. Runs at minute 7 to avoid
        # piling onto top-of-hour traffic.
        cron(export_gc_job, minute=7),
        # Daily at 03:00 UTC: hard-delete users whose grace period
        # elapsed. The window is intentionally off-peak so a slow
        # cascade (lots of files) doesn't compete with daytime traffic.
        cron(hard_delete_due_users_job, hour=3, minute=0),
    ]


class WorkerSettings:
    """arq worker configuration discovered by the arq CLI.

    See https://arq-docs.helpmanual.io/#workersettings for the schema.
    """

    functions: ClassVar[list[Any]] = [
        ingest_file_job,
        embed_chunks_for_file_job,
        export_user_data_job,
        treatment_derivation_job,
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    # Lazily resolved via property-like attribute lookup arq does on
    # first run; computing it at class-build time would require arq
    # at import time which we avoid for testability.

    @classmethod
    def settings_dict(cls) -> dict[str, Any]:
        """Return the dict arq actually uses; for documentation/tests."""

        settings = get_settings()
        return {
            "functions": cls.functions,
            "cron_jobs": _build_cron_jobs(),
            "on_startup": cls.on_startup,
            "on_shutdown": cls.on_shutdown,
            "redis_settings": _build_redis_settings(),
            "max_jobs": settings.lq_ai_ingest_worker_concurrency,
            "job_timeout": (
                settings.lq_ai_docling_timeout_seconds + _ARQ_JOB_TIMEOUT_BUFFER_SECONDS
            ),
            # arq's queue-name default is "arq:queue"; we override
            # only if a future config wants to namespace.
        }


# Module-level convenience: arq's CLI looks for the class attributes
# directly on `WorkerSettings`. The settings_dict() method is for
# tests / docs — production arq invocations use the class attributes.
def _populate_class_attrs() -> None:
    """Populate `WorkerSettings.redis_settings` etc. for arq CLI discovery.

    arq reads class attributes directly. We populate the attributes
    that need runtime values (like RedisSettings) lazily so the import
    succeeds in arq-less environments.
    """

    try:
        WorkerSettings.redis_settings = _build_redis_settings()  # type: ignore[attr-defined]
        WorkerSettings.cron_jobs = _build_cron_jobs()  # type: ignore[attr-defined]
        settings = get_settings()
        WorkerSettings.max_jobs = settings.lq_ai_ingest_worker_concurrency  # type: ignore[attr-defined]
        WorkerSettings.job_timeout = (  # type: ignore[attr-defined]
            settings.lq_ai_docling_timeout_seconds + _ARQ_JOB_TIMEOUT_BUFFER_SECONDS
        )
    except ImportError:  # pragma: no cover - arq missing in some envs
        pass


_populate_class_attrs()
