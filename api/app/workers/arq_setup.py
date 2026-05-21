"""M3-A6 ``arq`` worker — background jobs for the Playbook Service.

Sister worker to :mod:`app.workers.document_pipeline` (the ``ingest-worker``
container). Both processes share the same Redis instance for coordination
but consume from **disjoint queues** so a backlog of one workload does not
delay the other.

Why a separate queue
--------------------

The Easy Playbook generation pipeline (M3-A6 Phase 5) is a long-running
job — the PRD §3.7 NFR allows up to 10 minutes for a 10-document corpus.
If easy-playbook jobs landed on the default ``arq:queue`` they would
compete with document-ingest jobs and either side could starve the other
depending on queue depth. Worse, each worker would receive jobs whose
function name it does not register and reject them.

The new worker therefore declares ``queue_name = M3A6_QUEUE_NAME`` and
the API-side enqueue helpers (added in Phase 5) build their pool with
``default_queue_name=M3A6_QUEUE_NAME`` so the two pipelines never mix.

Registered functions:

* ``noop_job`` (Phase 1) — kept indefinitely as a lightweight
  "is the worker consuming?" health probe.
* :func:`app.workers.easy_playbook_worker.easy_playbook_generation_job`
  (Phase 5) — the real Easy Playbook generation pipeline.

Discovered by the ``arq`` CLI via::

    arq app.workers.arq_setup.WorkerSettings

See ``docker-compose.yml`` (``arq-worker`` service).
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, ClassVar

from app.config import get_settings
from app.db.session import dispose_engine
from app.workers.easy_playbook_worker import easy_playbook_generation_job

log = logging.getLogger(__name__)


M3A6_QUEUE_NAME = "arq:m3a6"
"""Dedicated arq queue for M3-A6+ background work. Disjoint from the
ingest-worker's default ``arq:queue`` so a backlog on either side does
not affect the other. Phase 5 introduces the API-side enqueue helper
that targets this queue; Phase 1 only proves the worker consumes from
it (via the smoke test)."""


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------


async def noop_job(ctx: dict[str, Any]) -> str:
    """Smoke-test job: returns ``"ok"``.

    Kept indefinitely after Phase 5 lands the real easy-playbook
    function — it's a tiny, dependency-free hook that the smoke test
    (and any future health probe) can enqueue to verify the worker is
    consuming from the M3-A6 queue.
    """

    log.info(
        "arq_setup.noop_job: executed",
        extra={"event": "arq_m3a6_noop"},
    )
    return "ok"


# ---------------------------------------------------------------------------
# Worker startup / shutdown
# ---------------------------------------------------------------------------


async def on_startup(ctx: dict[str, Any]) -> None:
    """Worker startup hook — log boot.

    No sweep-of-orphaned-rows logic yet; the only registered job
    (``noop_job``) is stateless. Phase 5 will add the easy-playbook
    generation-row sweep here, mirroring the pattern in
    :mod:`app.workers.document_pipeline.on_startup`.
    """

    log.info(
        "arq-worker startup: M3-A6 queue=%s ready",
        M3A6_QUEUE_NAME,
        extra={"event": "arq_m3a6_startup", "queue": M3A6_QUEUE_NAME},
    )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """Worker shutdown hook — dispose the DB engine.

    Mirrors :mod:`app.workers.document_pipeline.on_shutdown`. ``dispose_engine``
    is idempotent and safe to call even if no session was ever opened.
    """

    log.info("arq-worker shutdown: disposing DB engine")
    try:
        await dispose_engine()
    except Exception as exc:  # pragma: no cover - shutdown best-effort
        log.warning("arq-worker shutdown: dispose_engine failed: %s", exc)


# ---------------------------------------------------------------------------
# arq WorkerSettings — discovered by ``arq <module>.WorkerSettings``
# ---------------------------------------------------------------------------


def _build_redis_settings() -> Any:
    """Build arq's ``RedisSettings`` from the configured ``REDIS_URL``.

    Lazy import so the module imports cleanly in environments where
    ``arq`` is not installed (matches the pattern in
    :mod:`app.workers.document_pipeline`).
    """

    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    """arq worker configuration discovered by the arq CLI.

    See https://arq-docs.helpmanual.io/#workersettings for the schema.
    """

    functions: ClassVar[list[Any]] = [noop_job, easy_playbook_generation_job]
    queue_name: ClassVar[str] = M3A6_QUEUE_NAME
    # PRD §3.7 NFR caps generation at 10 min for a 10-doc corpus on the
    # default judge model. A 5-doc corpus is ~5 min, so the prior
    # default-300s ceiling cut runs off mid-assembly. 900s = NFR + 50%
    # headroom; a future tuning pass can lower it if cluster sizes
    # plateau lower than the worst case.
    job_timeout: ClassVar[int] = 900
    on_startup = on_startup
    on_shutdown = on_shutdown


def _populate_class_attrs() -> None:
    """Populate runtime-resolved class attrs (``redis_settings``).

    arq reads class attributes directly. We populate the attributes
    that need runtime values lazily so the module import succeeds even
    when arq is absent.
    """

    # arq is a runtime dep but the import is deferred so this module loads
    # cleanly in environments where arq is absent (matching the pattern in
    # :mod:`app.workers.document_pipeline`).
    with contextlib.suppress(ImportError):  # pragma: no cover - arq missing in some envs
        WorkerSettings.redis_settings = _build_redis_settings()  # type: ignore[attr-defined]


_populate_class_attrs()
