"""Unit tests for the C5 enqueue helper.

The actual arq worker is not exercised here (that's an integration
test against a live Redis). What we cover:

* :func:`enqueue_ingest_job` returns False on enqueue failure
  (e.g., Redis unreachable) and does not raise — the upload handler
  treats it as best-effort.
* The job-name constant is ``ingest_file_job`` (matches the worker
  side).
* The ``close_pool`` helper is idempotent (safe to call when no
  pool was ever opened).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.workers.queue import (
    INGEST_JOB_NAME,
    close_pool,
    enqueue_ingest_job,
)


@pytest.mark.unit
def test_job_name_constant() -> None:
    assert INGEST_JOB_NAME == "ingest_file_job"


@pytest.mark.unit
async def test_enqueue_succeeds_returns_true() -> None:
    import uuid as _uuid

    fake_pool = AsyncMock()
    fake_pool.enqueue_job = AsyncMock(return_value="job-id")

    with patch("app.workers.queue._get_pool", AsyncMock(return_value=fake_pool)):
        ok = await enqueue_ingest_job(_uuid.uuid4())

    assert ok is True
    fake_pool.enqueue_job.assert_awaited_once()
    args, _ = fake_pool.enqueue_job.call_args
    assert args[0] == INGEST_JOB_NAME


@pytest.mark.unit
async def test_enqueue_redis_failure_returns_false() -> None:
    """Redis-unreachable failures don't raise; they return False."""

    import uuid as _uuid

    fake_pool = AsyncMock()
    fake_pool.enqueue_job = AsyncMock(side_effect=ConnectionError("redis down"))

    with patch("app.workers.queue._get_pool", AsyncMock(return_value=fake_pool)):
        ok = await enqueue_ingest_job(_uuid.uuid4())

    assert ok is False  # No exception raised; logged warning instead.


@pytest.mark.unit
async def test_close_pool_when_no_pool_built_is_safe() -> None:
    """Calling close_pool when nothing was opened is a no-op."""

    # Reset the module-global for safety.
    import app.workers.queue as queue_mod

    queue_mod._pool = None
    await close_pool()  # Must not raise.
    assert queue_mod._pool is None


@pytest.mark.unit
async def test_enqueue_get_pool_failure_returns_false() -> None:
    """A failure inside _get_pool itself (e.g., import error) is caught."""

    import uuid as _uuid

    with patch(
        "app.workers.queue._get_pool",
        AsyncMock(side_effect=ImportError("arq not installed")),
    ):
        ok = await enqueue_ingest_job(_uuid.uuid4())

    assert ok is False


@pytest.mark.unit
async def test_enqueue_treatment_uses_dedup_job_id() -> None:
    """Treatment enqueue passes _job_id for arq coalescing (DE-363)."""

    import uuid as _uuid

    from app.workers.queue import (
        TREATMENT_DERIVATION_JOB_NAME,
        enqueue_treatment_derivation_job,
    )

    fake_pool = AsyncMock()
    fake_pool.enqueue_job = AsyncMock(return_value="job-id")

    with patch("app.workers.queue._get_pool", AsyncMock(return_value=fake_pool)):
        mid = _uuid.uuid4()
        ok = await enqueue_treatment_derivation_job(mid)

    assert ok is True
    fake_pool.enqueue_job.assert_awaited_once()
    args, kwargs = fake_pool.enqueue_job.call_args
    assert args[0] == TREATMENT_DERIVATION_JOB_NAME
    assert args[1] == str(mid)
    assert kwargs.get("_job_id") == f"treatment:{mid}"
