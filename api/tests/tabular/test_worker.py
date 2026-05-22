"""Worker-side tests for the M3-C2 Tabular execution pipeline.

The :func:`tabular_execution_job` worker function dispatches to
:func:`app.tabular.executor.run_tabular_execution`. The expensive
pieces (LangGraph workflow + per-cell LLM dispatch) are mocked at the
import-site level so the worker's *orchestration* is tested without
re-running executor logic (which has its own coverage via
:mod:`tests.tabular.test_nodes`).

Verifies the load-bearing wiring:

* Function name + queue constants are stable (the
  ``M3A6_QUEUE_NAME → M3_PLAYBOOK_QUEUE_NAME`` rename keeps the alias).
* The worker is registered in :class:`WorkerSettings.functions`.
* The enqueue helper exists on the API-side queue module.
"""

from __future__ import annotations

import pytest

from app.workers import arq_setup, queue

# ---------------------------------------------------------------------------
# Queue + worker registration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_tabular_job_name_is_stable() -> None:
    """The ARQ function name is the contract between API and worker;
    pinning it here makes a rename a deliberate breaking change."""

    assert queue.TABULAR_JOB_NAME == "tabular_execution_job"


@pytest.mark.unit
def test_m3_playbook_queue_name_replaces_m3a6() -> None:
    """Decision C-3: rename ``M3A6_QUEUE_NAME → M3_PLAYBOOK_QUEUE_NAME``
    so the queue describes its workload (Easy Playbook + Tabular share
    it) instead of an obsolete task code."""

    assert arq_setup.M3_PLAYBOOK_QUEUE_NAME == "arq:m3a6"
    assert queue.M3_PLAYBOOK_QUEUE_NAME == "arq:m3a6"


@pytest.mark.unit
def test_m3a6_queue_name_backward_compat_alias() -> None:
    """The old constant stays exported as an alias for one release so
    in-flight deploys / external callers aren't broken (prep doc
    risk row 6)."""

    assert arq_setup.M3A6_QUEUE_NAME == arq_setup.M3_PLAYBOOK_QUEUE_NAME
    assert queue.M3A6_QUEUE_NAME == queue.M3_PLAYBOOK_QUEUE_NAME


@pytest.mark.unit
def test_worker_registers_tabular_execution_job() -> None:
    """``WorkerSettings.functions`` must include ``tabular_execution_job``
    or the ARQ worker would receive jobs whose function name it doesn't
    register and reject them."""

    from app.workers.tabular_worker import tabular_execution_job

    assert tabular_execution_job in arq_setup.WorkerSettings.functions


@pytest.mark.unit
def test_worker_still_registers_easy_playbook_job() -> None:
    """The rename must NOT drop the Easy Playbook function from
    ``WorkerSettings.functions`` (regression guard)."""

    from app.workers.easy_playbook_worker import easy_playbook_generation_job

    assert easy_playbook_generation_job in arq_setup.WorkerSettings.functions
