"""Shared playbook ``arq`` worker — background jobs for Easy Playbook
generation (M3-A6) and Tabular Review execution (M3-C2).

Sister worker to :mod:`app.workers.document_pipeline` (the ``ingest-worker``
container). Both processes share the same Redis instance for coordination
but consume from **disjoint queues** so a backlog of one workload does not
delay the other.

Why a separate queue
--------------------

Long-running jobs — both Easy Playbook generation (PRD §3.7 NFR up to
10 minutes for a 10-document corpus) and Tabular Review execution (up
to 200 docs x 10 cols = 2000 cells over hours per Phase C prep doc
Decision C-3) — landing on the default ``arq:queue`` would compete
with document-ingest jobs and either side could starve the other
depending on queue depth. Worse, each worker would receive jobs whose
function name it does not register and reject them.

The worker therefore declares ``queue_name = M3_PLAYBOOK_QUEUE_NAME``
and the API-side enqueue helpers build their pool with
``default_queue_name=M3_PLAYBOOK_QUEUE_NAME`` so the playbook +
tabular pipelines never mix with the ingest pipeline.

Why share the queue between Easy Playbook + Tabular
---------------------------------------------------

Per Decision C-3: two arq containers per deployment would double the
operational surface for no isolation win — both workloads are bursty
in different shapes (Easy Playbook = 1-10 docs over ~10 min; Tabular =
up to 2000 cells over hours), but neither saturates a worker long
enough to deserve isolation. If we see queue contention in production,
splitting is a follow-on PR; the queue string stays ``arq:m3a6`` for
on-the-wire compatibility (rename is constant-name-only).

Registered functions:

* ``noop_job`` — lightweight "is the worker consuming?" health probe.
* :func:`app.workers.easy_playbook_worker.easy_playbook_generation_job`
  (M3-A6) — Easy Playbook generation pipeline.
* :func:`app.workers.tabular_worker.tabular_execution_job`
  (M3-C2) — Tabular Review execution pipeline.

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
from app.workers.tabular_worker import tabular_execution_job

log = logging.getLogger(__name__)


M3_PLAYBOOK_QUEUE_NAME = "arq:m3a6"
"""Dedicated arq queue for shared playbook + tabular background work.
Disjoint from the ingest-worker's default ``arq:queue`` so a backlog
on either side does not affect the other.

Queue string stays ``arq:m3a6`` (the original M3-A6 name) for
on-the-wire compatibility — only the Python constant was renamed to
better describe its current workload (Easy Playbook + Tabular share
this queue per Phase C prep doc Decision C-3). The
:data:`M3A6_QUEUE_NAME` alias below stays exported for one release so
in-flight code / external integrations keep working."""

M3A6_QUEUE_NAME = M3_PLAYBOOK_QUEUE_NAME
"""Backward-compat alias for the renamed :data:`M3_PLAYBOOK_QUEUE_NAME`.
Will be removed in a future release; new code should use
:data:`M3_PLAYBOOK_QUEUE_NAME`."""


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
        "arq-worker startup: playbook queue=%s ready",
        M3_PLAYBOOK_QUEUE_NAME,
        # Event name kept stable for log-query consumers; the queue
        # value uses the renamed constant (same string either way).
        extra={"event": "arq_m3a6_startup", "queue": M3_PLAYBOOK_QUEUE_NAME},
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

    functions: ClassVar[list[Any]] = [
        noop_job,
        easy_playbook_generation_job,
        tabular_execution_job,
    ]
    queue_name: ClassVar[str] = M3_PLAYBOOK_QUEUE_NAME
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
