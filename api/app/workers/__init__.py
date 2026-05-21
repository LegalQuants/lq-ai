"""Async workers for the LQ.AI backend.

Currently houses the document-pipeline worker (Task C5). Future
async backend work (audit-log batch flushing, soft-delete GC, etc.)
will live here too.

The worker process is started via ``arq`` against the
``WorkerSettings`` class in :mod:`app.workers.document_pipeline`. The
docker-compose ``ingest-worker`` service runs it. See
:doc:`docs/adr/0006-document-pipeline-architecture.md` for the
mechanism rationale.
"""

from app.workers.queue import (
    enqueue_easy_playbook_generation_job,
    enqueue_ingest_job,
)

__all__ = [
    "enqueue_easy_playbook_generation_job",
    "enqueue_ingest_job",
]
