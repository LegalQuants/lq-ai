"""Tests for tabular bulk operations — DE-304 / ADR 0026.

Covers the :mod:`app.tabular.bulk_ops` vertical:

* preview math (calls count + cold-start default);
* prompt builders' fail-closed honesty (failed cells / missing values
  are surfaced to the model, never silently dropped);
* results shaping (summary counters);
* the batch runner — partial failures land as failed *items* while the
  batch completes (ADR 0026 D4), results stay causally linked to the
  parent execution, and a missing grid fails the whole batch;
* queue / worker registration wiring (mirrors
  :mod:`tests.tabular.test_worker`).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tabular import TabularBulkOp, TabularExecution
from app.models.user import User
from app.security import hash_password
from app.tabular import bulk_ops
from app.tabular.bulk_ops import (
    DEFAULT_PER_CALL_USD,
    build_memo_messages,
    build_redline_messages,
    bulk_op_calls_count,
    estimate_bulk_op_cost,
    run_tabular_bulk_op,
    shape_bulk_op_results,
)
from app.workers import arq_setup, queue


@pytest.fixture(autouse=True)
def _fresh_cost_cache() -> None:
    bulk_ops.invalidate_cache()


# ---------------------------------------------------------------------------
# Preview math (unit)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_calls_count_math() -> None:
    """One call per row for redlines; one total for the memo; zero on
    an empty grid either way."""

    assert bulk_op_calls_count("redline_rows", n_rows=7) == 7
    assert bulk_op_calls_count("summarize_column", n_rows=7) == 1
    assert bulk_op_calls_count("redline_rows", n_rows=0) == 0
    assert bulk_op_calls_count("summarize_column", n_rows=0) == 0


@pytest.mark.unit
async def test_estimate_cold_start_uses_default_per_call() -> None:
    """``db=None`` previews at the conservative cold-start default
    (ADR 0026 D3)."""

    preview = await estimate_bulk_op_cost(None, kind="redline_rows", n_rows=3)
    assert preview.calls_count == 3
    assert preview.per_call_cost_usd == DEFAULT_PER_CALL_USD
    assert preview.estimated_cost_usd == DEFAULT_PER_CALL_USD * 3

    memo_preview = await estimate_bulk_op_cost(None, kind="summarize_column", n_rows=3)
    assert memo_preview.calls_count == 1
    assert memo_preview.estimated_cost_usd == DEFAULT_PER_CALL_USD


# ---------------------------------------------------------------------------
# Prompt builders (unit)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_redline_messages_mark_failed_cells() -> None:
    """Failed cells surface as ``(extraction failed)`` — never dropped."""

    messages = build_redline_messages(
        document_name="nda-1.pdf",
        cells={
            "Term": {"value": "3 years", "confidence": "high"},
            "Survival": {"value": None, "confidence": "failed", "error": "boom"},
        },
        chunks=[{"content": "This Agreement lasts three years."}],
    )
    assert messages[0].role == "system"
    user = messages[1].content
    assert "nda-1.pdf" in user
    assert "Term: 3 years [confidence: high]" in user
    assert "Survival: (extraction failed)" in user
    assert "This Agreement lasts three years." in user


@pytest.mark.unit
def test_memo_messages_list_missing_rows() -> None:
    """Every row appears in the memo prompt; missing values are marked
    explicitly so the memo accounts for them (ADR 0026 D5)."""

    messages = build_memo_messages(
        column_name="Term",
        column_query="What is the term length?",
        row_values=[("a.pdf", "3 years"), ("b.pdf", None)],
    )
    user = messages[1].content
    assert "COLUMN: Term" in user
    assert "a.pdf: 3 years" in user
    assert "b.pdf: (no value — extraction failed)" in user


@pytest.mark.unit
def test_shape_results_counts_failures() -> None:
    """The summary counters are the fail-closed honesty surface."""

    items = [
        {"status": "completed", "output_text": "memo"},
        {"status": "failed", "error": "boom"},
        {"status": "completed", "output_text": "memo2"},
    ]
    payload = shape_bulk_op_results(items)
    assert payload["schema_version"] == bulk_ops.BULK_OP_RESULTS_SCHEMA_VERSION
    assert payload["summary"] == {"total_items": 3, "failed_items": 1}
    assert payload["items"] == items


# ---------------------------------------------------------------------------
# Queue / worker registration wiring (unit)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_bulk_op_job_name_is_stable() -> None:
    """The ARQ function name is the API↔worker contract."""

    assert queue.TABULAR_BULK_OP_JOB_NAME == "tabular_bulk_op_job"
    assert bulk_ops.TABULAR_BULK_OP_JOB_NAME == queue.TABULAR_BULK_OP_JOB_NAME


@pytest.mark.unit
def test_worker_registers_bulk_op_job() -> None:
    """``WorkerSettings.functions`` must include ``tabular_bulk_op_job``
    or the shared playbook worker would reject the job by name."""

    from app.tabular.bulk_ops import tabular_bulk_op_job

    assert tabular_bulk_op_job in arq_setup.WorkerSettings.functions


@pytest.mark.unit
def test_enqueue_helper_exists() -> None:
    assert callable(queue.enqueue_tabular_bulk_op_job)


# ---------------------------------------------------------------------------
# Batch runner (integration — real DB, stub gateway)
# ---------------------------------------------------------------------------


class _StubGateway:
    """Gateway stub: fails any call whose user prompt contains a marker
    string; otherwise returns a canned completion. Captures every
    request so tests can assert on prompt content."""

    def __init__(self, *, fail_markers: set[str] | None = None, text: str = "DRAFT MEMO") -> None:
        self.fail_markers = fail_markers or set()
        self.text = text
        self.requests: list[Any] = []

    async def chat_completion(self, request: Any) -> Any:
        self.requests.append(request)
        user_content = request.messages[-1].content
        for marker in self.fail_markers:
            if marker in user_content:
                raise RuntimeError("stub gateway failure")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.text))]
        )


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"bulk-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


def _grid_row(name: str, term_value: str | None, *, failed: bool = False) -> dict[str, Any]:
    cell: dict[str, Any] = (
        {"value": None, "confidence": "failed", "error": "no chunks"}
        if failed
        else {"value": term_value, "confidence": "high"}
    )
    return {
        "document_id": str(uuid.uuid4()),
        "document_name": name,
        "cells": {"Term": cell},
    }


async def _make_execution(
    db: AsyncSession,
    *,
    user: User,
    rows: list[dict[str, Any]] | None,
) -> TabularExecution:
    execution = TabularExecution(
        user_id=user.id,
        status="completed",
        document_ids=[],
        columns=[{"name": "Term", "query": "What is the term?"}],
        results=({"schema_version": "m3-c2-v1", "rows": rows} if rows is not None else None),
    )
    db.add(execution)
    await db.flush()
    return execution


async def _make_bulk_op(
    db: AsyncSession,
    *,
    execution: TabularExecution,
    user: User,
    kind: str,
    params: dict[str, Any] | None = None,
) -> TabularBulkOp:
    bulk_op = TabularBulkOp(
        execution_id=execution.id,
        user_id=user.id,
        kind=kind,
        status="pending",
        params=params or {},
    )
    db.add(bulk_op)
    await db.flush()
    return bulk_op


@pytest.mark.integration
async def test_redline_partial_failure_completes_batch(db_session: AsyncSession) -> None:
    """One row's gateway call errors → that item lands failed with its
    error persisted; the other rows complete; the BATCH completes
    (ADR 0026 D4) and results stay linked to the parent execution."""

    user = await _make_user(db_session)
    rows = [
        _grid_row("good-1.pdf", "3 years"),
        _grid_row("bad.pdf", "5 years"),
        _grid_row("good-2.pdf", "1 year"),
    ]
    execution = await _make_execution(db_session, user=user, rows=rows)
    bulk_op = await _make_bulk_op(db_session, execution=execution, user=user, kind="redline_rows")

    gateway = _StubGateway(fail_markers={"bad.pdf"}, text="## Issues\n1. ...")
    await run_tabular_bulk_op(
        db_session,
        bulk_op_id=bulk_op.id,
        gateway=gateway,  # type: ignore[arg-type]
    )

    refreshed = await db_session.get(TabularBulkOp, bulk_op.id)
    assert refreshed is not None
    # Linkage: the results row is tied to the parent execution.
    assert refreshed.execution_id == execution.id
    assert refreshed.status == "completed"
    assert refreshed.started_at is not None and refreshed.completed_at is not None

    results = refreshed.results
    assert results is not None
    items = results["items"]
    assert [item["document_name"] for item in items] == [
        "good-1.pdf",
        "bad.pdf",
        "good-2.pdf",
    ]
    assert [item["status"] for item in items] == ["completed", "failed", "completed"]
    # The failed item carries its error and no output; it is never omitted.
    assert "RuntimeError" in items[1]["error"]
    assert items[1]["output_text"] is None
    assert items[0]["output_text"] == "## Issues\n1. ..."
    assert results["summary"] == {"total_items": 3, "failed_items": 1}
    # Item document_ids echo the grid rows (per-row linkage).
    assert items[0]["document_id"] == rows[0]["document_id"]
    # 3 gateway calls were attempted — the failure did not short-circuit.
    assert len(gateway.requests) == 3
    assert all(r.lq_ai_purpose == bulk_ops.TABULAR_BULK_OP_PURPOSE for r in gateway.requests)


@pytest.mark.integration
async def test_summarize_column_single_memo_lists_failed_rows(
    db_session: AsyncSession,
) -> None:
    """The memo op makes ONE call spanning the grid; rows whose cell
    failed are fed to the model as explicit no-value markers."""

    user = await _make_user(db_session)
    rows = [
        _grid_row("a.pdf", "3 years"),
        _grid_row("b.pdf", None, failed=True),
    ]
    execution = await _make_execution(db_session, user=user, rows=rows)
    bulk_op = await _make_bulk_op(
        db_session,
        execution=execution,
        user=user,
        kind="summarize_column",
        params={"column_name": "Term"},
    )

    gateway = _StubGateway(text="## Summary\n...")
    await run_tabular_bulk_op(
        db_session,
        bulk_op_id=bulk_op.id,
        gateway=gateway,  # type: ignore[arg-type]
    )

    refreshed = await db_session.get(TabularBulkOp, bulk_op.id)
    assert refreshed is not None
    assert refreshed.status == "completed"
    assert refreshed.results is not None
    items = refreshed.results["items"]
    assert len(items) == 1
    assert items[0]["document_id"] is None
    assert items[0]["status"] == "completed"
    assert items[0]["output_text"] == "## Summary\n..."

    # One call; its prompt covers every row honestly.
    assert len(gateway.requests) == 1
    prompt = gateway.requests[0].messages[-1].content
    assert "a.pdf: 3 years" in prompt
    assert "b.pdf: (no value — extraction failed)" in prompt


@pytest.mark.integration
async def test_missing_results_grid_fails_whole_batch(db_session: AsyncSession) -> None:
    """A parent execution without a results grid is a whole-batch
    failure (pre-flight), not a fabricated empty report."""

    user = await _make_user(db_session)
    execution = await _make_execution(db_session, user=user, rows=None)
    bulk_op = await _make_bulk_op(db_session, execution=execution, user=user, kind="redline_rows")

    gateway = _StubGateway()
    await run_tabular_bulk_op(
        db_session,
        bulk_op_id=bulk_op.id,
        gateway=gateway,  # type: ignore[arg-type]
    )

    refreshed = await db_session.get(TabularBulkOp, bulk_op.id)
    assert refreshed is not None
    assert refreshed.status == "failed"
    assert refreshed.error_text is not None
    assert "no results grid" in refreshed.error_text
    assert gateway.requests == []


@pytest.mark.integration
async def test_cost_actual_summed_from_items(db_session: AsyncSession) -> None:
    """``cost_actual_usd`` is the item-cost sum (v0.3.0 posture: zero
    until the gateway returns per-call cost; the column is wired)."""

    user = await _make_user(db_session)
    execution = await _make_execution(db_session, user=user, rows=[_grid_row("a.pdf", "x")])
    bulk_op = await _make_bulk_op(db_session, execution=execution, user=user, kind="redline_rows")
    await run_tabular_bulk_op(
        db_session,
        bulk_op_id=bulk_op.id,
        gateway=_StubGateway(),  # type: ignore[arg-type]
    )
    refreshed = await db_session.get(TabularBulkOp, bulk_op.id)
    assert refreshed is not None
    assert refreshed.cost_actual_usd == Decimal("0")
