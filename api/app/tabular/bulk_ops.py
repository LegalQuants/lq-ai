"""Tabular bulk operations — DE-304 / ADR 0026.

Two operations over a *completed* tabular execution:

* ``redline_rows`` — one redline-style review memo per parent grid row
  (document), grounded in the row's extracted cell values plus leading
  document text; items combine into a redline report on the execution
  detail page.
* ``summarize_column`` — one memo synthesizing a single column across
  all rows (an execution-attached memo artifact).

This module carries the whole vertical for the feature:

* the cost estimator the preview endpoint calls (rolling average over
  ``purpose='tabular_bulk_op'`` routing-log rows, mirroring the
  M2-E2 / M3-C2 pattern in :mod:`app.tabular.cost`);
* the ARQ job (``tabular_bulk_op_job``) registered on the shared
  playbook queue (``arq:m3a6`` per Decision C-3) — one job walks the
  parent grid sequentially, one gateway call per item, each wrapped in
  try/except so a failed item never blocks the batch (ADR 0026 D4);
* the prompt builders (pure functions, unit-testable without a DB).

All inference goes through the same :class:`GatewayClient` surface the
tabular cell node uses (ADR 0014 — no new egress path), tagged
``lq_ai_purpose='tabular_bulk_op'`` so the estimator's rolling average
calibrates off real spend.

Per the M3-C2 quality bar: both outputs are drafts for attorney
review. "Batch completed" means every item reached a terminal
per-item state — not that any redline or memo is correct or fit for
use without review.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inference import InferenceRoutingLog
from app.models.tabular import TabularBulkOp, TabularExecution
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest
from app.schemas.tabular import TabularBulkOpKind, TabularBulkOpPreviewResponse

if TYPE_CHECKING:
    from app.clients.gateway import GatewayClient

logger = logging.getLogger(__name__)


TABULAR_BULK_OP_PURPOSE = "tabular_bulk_op"
"""``lq_ai_purpose`` tag on every bulk-op gateway call. The gateway
writes it through to ``inference_routing_log.purpose`` (M2-E2); the
cost estimator filters on it so bulk-op calibration is not polluted by
extraction / chat / judge traffic."""

DEFAULT_PER_CALL_USD: Decimal = Decimal("0.01")
"""Cold-start per-call cost fallback — 2x the tabular per-cell default
(:data:`app.tabular.cost.DEFAULT_PER_CELL_USD`) because bulk-op calls
generate long-form prose (redline memos) rather than short extractions
(ADR 0026 D3). Conservative on purpose: a 200-row redline op previews
at $2.00 cold, which arms the UI-side $1.00 confirmation gate
(Decision C-5)."""

BULK_OP_RESULTS_SCHEMA_VERSION = "de304-v1"
"""Schema-version stamp on ``tabular_bulk_ops.results``. Bumped on any
shape-breaking change so the results panel can refuse to render
unknown versions instead of crashing."""

BULK_OP_MAX_TOKENS = 1500
"""Max tokens per bulk-op call. Redline memos and column memos are
prose (unlike the 500-token cell extraction); 1500 keeps a 200-row
batch bounded while leaving room for a usable draft."""

BULK_OP_CHUNKS_PER_ROW = 4
"""Leading document chunks included per redline call. Matches the cell
node's ``RETRIEVAL_TOP_K`` context budget."""

# Job-function name registered on the worker — must match the constant
# in :mod:`app.workers.queue` so the api-side enqueue helper targets
# the right function on the shared playbook queue.
TABULAR_BULK_OP_JOB_NAME = "tabular_bulk_op_job"

_MIN_SAMPLES = 5
_WINDOW_SAMPLES = 100
_WINDOW_DAYS = 30
_CACHE_TTL_SECONDS = 300.0

# Single-slot in-process cache: (cached_at_monotonic, per_call_cost).
_cache: dict[str, tuple[float, Decimal]] = {}
_CACHE_KEY = "per_call_cost"


# ---------------------------------------------------------------------------
# Cost preview (ADR 0026 D3)
# ---------------------------------------------------------------------------


def invalidate_cache() -> None:
    """Reset the in-process cache. Tests call this between assertions."""

    _cache.clear()


def bulk_op_calls_count(kind: TabularBulkOpKind, *, n_rows: int) -> int:
    """Gateway calls the op will make: one per row for ``redline_rows``,
    one total for ``summarize_column`` (zero either way on an empty grid)."""

    if n_rows <= 0:
        return 0
    return n_rows if kind == "redline_rows" else 1


async def estimate_per_call_cost_usd(db: AsyncSession | None) -> Decimal:
    """Rolling-average per-call cost over recent bulk-op routing-log rows.

    Mirrors :func:`app.tabular.cost._estimate_per_cell_metrics`: last
    :data:`_WINDOW_SAMPLES` rows where ``purpose = 'tabular_bulk_op'``
    within :data:`_WINDOW_DAYS`; falls back to
    :data:`DEFAULT_PER_CALL_USD` below :data:`_MIN_SAMPLES` samples,
    on ``db=None``, or on any query error (the pre-flight must never
    break the endpoint). Cached in-process per
    :data:`_CACHE_TTL_SECONDS`.
    """

    if db is None:
        return DEFAULT_PER_CALL_USD

    now = time.monotonic()
    cached = _cache.get(_CACHE_KEY)
    if cached is not None:
        cached_at, cached_value = cached
        if now - cached_at < _CACHE_TTL_SECONDS:
            return cached_value

    cutoff = datetime.now(UTC) - timedelta(days=_WINDOW_DAYS)
    recent = (
        select(InferenceRoutingLog.cost_estimate)
        .where(
            InferenceRoutingLog.purpose == TABULAR_BULK_OP_PURPOSE,
            InferenceRoutingLog.cost_estimate.is_not(None),
            InferenceRoutingLog.timestamp >= cutoff,
        )
        .order_by(InferenceRoutingLog.timestamp.desc())
        .limit(_WINDOW_SAMPLES)
        .subquery()
    )
    stmt = select(func.avg(recent.c.cost_estimate), func.count(recent.c.cost_estimate))

    try:
        avg_cost_raw, count = (await db.execute(stmt)).one()
    except Exception as exc:
        logger.warning(
            "bulk-op cost calibration query failed: %s",
            exc,
            extra={
                "event": "tabular_bulk_op_cost_query_error",
                "error_type": type(exc).__name__,
            },
        )
        return DEFAULT_PER_CALL_USD

    if count is None or count < _MIN_SAMPLES or avg_cost_raw is None:
        _cache[_CACHE_KEY] = (now, DEFAULT_PER_CALL_USD)
        return DEFAULT_PER_CALL_USD

    per_call = Decimal(str(avg_cost_raw))
    _cache[_CACHE_KEY] = (now, per_call)
    return per_call


async def estimate_bulk_op_cost(
    db: AsyncSession | None,
    *,
    kind: TabularBulkOpKind,
    n_rows: int,
) -> TabularBulkOpPreviewResponse:
    """Compute the full preview payload for one proposed bulk op."""

    calls_count = bulk_op_calls_count(kind, n_rows=n_rows)
    per_call = await estimate_per_call_cost_usd(db)
    return TabularBulkOpPreviewResponse(
        kind=kind,
        calls_count=calls_count,
        per_call_cost_usd=per_call,
        estimated_cost_usd=per_call * Decimal(calls_count),
    )


# ---------------------------------------------------------------------------
# Prompt builders (pure — unit-testable without a DB)
# ---------------------------------------------------------------------------


_REDLINE_SYSTEM_PROMPT = """\
You are a legal review assistant for an in-house legal team, drafting a
FIRST-PASS redline memo for one document out of a multi-document review.

You will be given:
* The DOCUMENT NAME.
* EXTRACTED TERMS — key values a prior extraction pass pulled from this
  document, with per-term confidence. Terms marked "(extraction failed)"
  could not be extracted; do not invent values for them.
* DOCUMENT EXCERPTS — leading text of the document for context.

Write a concise redline-style review memo in Markdown with these sections:

## Issues
Numbered list of problematic or unusual terms, each with (a) what the
document says, (b) why it is a concern, (c) a suggested revised wording.

## Missing or unextracted
Terms that are absent or failed extraction and should be checked by hand.

## Overall posture
Two or three sentences on negotiation posture.

Ground every point in the EXTRACTED TERMS or the EXCERPTS. If the
provided material does not support a conclusion, say so plainly rather
than speculating. This memo is a draft for attorney review, not final
work product.
"""

_MEMO_SYSTEM_PROMPT = """\
You are a legal review assistant for an in-house legal team, drafting a
comparative memo about ONE extracted column across a multi-document
review grid.

You will be given the COLUMN name, the extraction QUERY that produced
it, and one line per document with that document's extracted value.
Lines marked "(no value — extraction failed)" are documents where
extraction failed; you MUST list those documents explicitly in the memo
rather than omitting them.

Write a concise memo in Markdown with these sections:

## Summary
The distribution of values across documents (counts, ranges, outliers).

## Outliers and concerns
Documents whose value deviates from the pack, and why that matters.

## Not covered
Every document with no extracted value, listed by name, so a human
reviews them by hand.

Use only the provided values; do not invent data. This memo is a draft
for attorney review, not final work product.
"""


def build_redline_messages(
    *,
    document_name: str,
    cells: dict[str, dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[ChatCompletionMessage]:
    """Render the redline-memo messages for one grid row.

    ``cells`` is the persisted grid-row cell map (column name →
    CellResult-shaped dict). Failed cells are surfaced to the model as
    ``(extraction failed)`` — the honesty marker the system prompt
    keys off — never silently dropped.
    """

    term_lines: list[str] = []
    for column_name, cell in cells.items():
        confidence = cell.get("confidence")
        value = cell.get("value")
        if confidence == "failed" or value is None:
            term_lines.append(f"- {column_name}: (extraction failed)")
        else:
            term_lines.append(f"- {column_name}: {value} [confidence: {confidence}]")

    chunk_blocks = [f"[EXCERPT {i}]\n{chunk['content']}" for i, chunk in enumerate(chunks)]
    user_content = (
        f"DOCUMENT NAME: {document_name}\n\n"
        f"EXTRACTED TERMS:\n" + ("\n".join(term_lines) if term_lines else "(none)") + "\n\n"
        "DOCUMENT EXCERPTS:\n" + ("\n\n".join(chunk_blocks) if chunk_blocks else "(none)")
    )
    return [
        ChatCompletionMessage(role="system", content=_REDLINE_SYSTEM_PROMPT),
        ChatCompletionMessage(role="user", content=user_content),
    ]


def build_memo_messages(
    *,
    column_name: str,
    column_query: str,
    row_values: list[tuple[str, str | None]],
) -> list[ChatCompletionMessage]:
    """Render the column-memo messages.

    ``row_values`` is ``(document_name, value-or-None)`` per grid row,
    in grid-row order. ``None`` values (failed / missing extraction)
    are rendered as ``(no value — extraction failed)`` so the memo
    accounts for every row (ADR 0026 D5).
    """

    lines = [
        f"- {name}: {value if value is not None else '(no value — extraction failed)'}"
        for name, value in row_values
    ]
    user_content = f"COLUMN: {column_name}\nQUERY: {column_query}\n\nVALUES PER DOCUMENT:\n" + (
        "\n".join(lines) if lines else "(no rows)"
    )
    return [
        ChatCompletionMessage(role="system", content=_MEMO_SYSTEM_PROMPT),
        ChatCompletionMessage(role="user", content=user_content),
    ]


# ---------------------------------------------------------------------------
# Per-item dispatch
# ---------------------------------------------------------------------------


async def _dispatch(
    gateway: GatewayClient,
    *,
    judge_model: str,
    messages: list[ChatCompletionMessage],
) -> str:
    """One bulk-op gateway call; returns the response text.

    Raises on any transport / shape problem — the caller's per-item
    try/except converts that into a failed item.
    """

    request = ChatCompletionRequest(
        model=judge_model,
        messages=messages,
        max_tokens=BULK_OP_MAX_TOKENS,
        anonymize=False,
        lq_ai_purpose=TABULAR_BULK_OP_PURPOSE,
    )
    response = await gateway.chat_completion(request)
    choices = getattr(response, "choices", None)
    if not choices:
        raise ValueError("empty response from gateway")
    content = choices[0].message.content
    if not content or not content.strip():
        raise ValueError("empty response content")
    return content.strip()


def _failed_item(
    *,
    document_id: str | None,
    document_name: str | None,
    reason: str,
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "document_name": document_name,
        "status": "failed",
        "output_text": None,
        "error": reason[:2000],
        "cost_usd": "0",
    }


def _completed_item(
    *,
    document_id: str | None,
    document_name: str | None,
    output_text: str,
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "document_name": document_name,
        "status": "completed",
        "output_text": output_text,
        "error": None,
        # Per-call cost reconciles off the routing log (same v0.3.0
        # posture as the cell node's cost_usd).
        "cost_usd": "0",
    }


def shape_bulk_op_results(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble the persisted ``tabular_bulk_ops.results`` payload.

    The summary counters are the fail-closed honesty surface: the UI
    renders ``failed_items`` prominently so a partially-failed batch
    never reads as a clean one.
    """

    return {
        "schema_version": BULK_OP_RESULTS_SCHEMA_VERSION,
        "items": items,
        "summary": {
            "total_items": len(items),
            "failed_items": sum(1 for item in items if item.get("status") == "failed"),
        },
    }


async def _run_redline_rows(
    db: AsyncSession,
    *,
    gateway: GatewayClient,
    judge_model: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One redline call per grid row; per-item failures never block the batch."""

    from app.tabular.nodes import _fetch_first_chunks

    items: list[dict[str, Any]] = []
    for row in rows:
        document_id = row.get("document_id")
        document_name = row.get("document_name") or ""
        try:
            chunks: list[dict[str, Any]] = []
            if document_id:
                chunks = await _fetch_first_chunks(
                    db,
                    uuid.UUID(str(document_id)),
                    limit=BULK_OP_CHUNKS_PER_ROW,
                )
            messages = build_redline_messages(
                document_name=document_name,
                cells=row.get("cells") or {},
                chunks=chunks,
            )
            output = await _dispatch(gateway, judge_model=judge_model, messages=messages)
            items.append(
                _completed_item(
                    document_id=document_id,
                    document_name=document_name,
                    output_text=output,
                )
            )
        except Exception as exc:
            logger.warning(
                "tabular bulk-op redline item failed: %s",
                exc,
                extra={
                    "event": "tabular_bulk_op_item_error",
                    "document_id": str(document_id),
                    "error_type": type(exc).__name__,
                },
            )
            items.append(
                _failed_item(
                    document_id=document_id,
                    document_name=document_name,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
    return items


async def _run_summarize_column(
    *,
    gateway: GatewayClient,
    judge_model: str,
    rows: list[dict[str, Any]],
    column_name: str,
    column_query: str,
) -> list[dict[str, Any]]:
    """One memo call spanning the whole grid — a single result item."""

    row_values: list[tuple[str, str | None]] = []
    for row in rows:
        cell = (row.get("cells") or {}).get(column_name) or {}
        value = cell.get("value")
        if cell.get("confidence") == "failed":
            value = None
        row_values.append((row.get("document_name") or "", value))

    try:
        messages = build_memo_messages(
            column_name=column_name,
            column_query=column_query,
            row_values=row_values,
        )
        output = await _dispatch(gateway, judge_model=judge_model, messages=messages)
        return [_completed_item(document_id=None, document_name=None, output_text=output)]
    except Exception as exc:
        logger.warning(
            "tabular bulk-op memo failed: %s",
            exc,
            extra={
                "event": "tabular_bulk_op_item_error",
                "column_name": column_name,
                "error_type": type(exc).__name__,
            },
        )
        return [
            _failed_item(
                document_id=None,
                document_name=None,
                reason=f"{type(exc).__name__}: {exc}",
            )
        ]


# ---------------------------------------------------------------------------
# Orchestration + ARQ job
# ---------------------------------------------------------------------------


async def run_tabular_bulk_op(
    db: AsyncSession,
    *,
    bulk_op_id: uuid.UUID,
    gateway: GatewayClient,
    judge_model: str | None = None,
) -> None:
    """Run one bulk op end to end.

    Lifecycle: ``pending → running`` on entry (sets ``started_at``);
    on batch completion writes ``results`` + ``cost_actual_usd`` and
    flips to ``completed`` — including batches with failed items (ADR
    0026 D4). Whole-batch failures (row missing, parent execution
    vanished, unreadable results payload, uncaught orchestration
    error) land at ``failed`` + ``error_text``.
    """

    from app.tabular.executor import DEFAULT_JUDGE_MODEL

    model = judge_model or DEFAULT_JUDGE_MODEL

    bulk_op = await db.get(TabularBulkOp, bulk_op_id)
    if bulk_op is None:
        logger.warning(
            "tabular bulk-op row not found; nothing to do",
            extra={
                "event": "tabular_bulk_op_row_missing",
                "bulk_op_id": str(bulk_op_id),
            },
        )
        return

    bulk_op.status = "running"
    bulk_op.started_at = datetime.now(UTC)
    await db.commit()

    try:
        execution = await db.get(TabularExecution, bulk_op.execution_id)
        if execution is None:
            await _mark_failed(db, bulk_op, "parent execution not found")
            return

        rows_raw = (execution.results or {}).get("rows")
        if not isinstance(rows_raw, list) or not rows_raw:
            await _mark_failed(db, bulk_op, "parent execution has no results grid")
            return
        rows: list[dict[str, Any]] = [row for row in rows_raw if isinstance(row, dict)]

        if bulk_op.kind == "redline_rows":
            items = await _run_redline_rows(
                db,
                gateway=gateway,
                judge_model=model,
                rows=rows,
            )
        else:
            column_name = str((bulk_op.params or {}).get("column_name") or "")
            column_query = next(
                (
                    str(col.get("query") or "")
                    for col in execution.columns
                    if col.get("name") == column_name
                ),
                "",
            )
            if not column_name:
                await _mark_failed(db, bulk_op, "params.column_name missing")
                return
            items = await _run_summarize_column(
                gateway=gateway,
                judge_model=model,
                rows=rows,
                column_name=column_name,
                column_query=column_query,
            )

        bulk_op.results = shape_bulk_op_results(items)
        bulk_op.cost_actual_usd = _sum_item_costs(items)
        bulk_op.status = "completed"
        bulk_op.completed_at = datetime.now(UTC)
        await db.commit()
    except Exception as exc:
        logger.exception(
            "tabular bulk-op crashed at orchestration layer",
            extra={
                "event": "tabular_bulk_op_crash",
                "bulk_op_id": str(bulk_op_id),
            },
        )
        await _mark_failed(db, bulk_op, f"{type(exc).__name__}: {exc}")


def _sum_item_costs(items: list[dict[str, Any]]) -> Decimal:
    total = Decimal("0")
    for item in items:
        raw = item.get("cost_usd")
        if raw is None:
            continue
        try:
            total += Decimal(str(raw))
        except Exception:
            continue
    return total


async def _mark_failed(db: AsyncSession, bulk_op: TabularBulkOp, error_text: str) -> None:
    """Best-effort write of the failed terminal state."""

    bulk_op.status = "failed"
    bulk_op.error_text = error_text[:2000]
    bulk_op.completed_at = datetime.now(UTC)
    try:
        await db.commit()
    except Exception as exc:  # pragma: no cover - DB best-effort
        logger.warning(
            "tabular bulk-op: failed-state write failed: %s",
            exc,
            extra={"event": "tabular_bulk_op_persist_failed_error"},
        )


async def tabular_bulk_op_job(ctx: dict[str, Any], bulk_op_id_str: str) -> dict[str, Any]:
    """ARQ job — run one bulk op on the shared playbook queue.

    Mirrors :func:`app.workers.tabular_worker.tabular_execution_job`:
    resolves a gateway client from the worker ``ctx``, opens its own
    session via the standard factory, and delegates to
    :func:`run_tabular_bulk_op` (which manages the lifecycle
    internally). BaseException (ARQ ``job_timeout`` cancellation)
    writes the failed terminal state then re-raises so arq's shutdown
    machinery still sees the cancel.
    """

    from app.db.session import get_session_factory
    from app.workers.tabular_worker import _gateway_from_ctx

    bulk_op_id = uuid.UUID(bulk_op_id_str)
    logger.info(
        "tabular bulk-op job start",
        extra={"event": "tabular_bulk_op_start", "bulk_op_id": bulk_op_id_str},
    )

    factory = get_session_factory()
    gateway = _gateway_from_ctx(ctx)

    async with factory() as session:
        try:
            await run_tabular_bulk_op(session, bulk_op_id=bulk_op_id, gateway=gateway)
        except BaseException as exc:
            # run_tabular_bulk_op catches Exception internally; only
            # BaseException (CancelledError / SystemExit) reaches here.
            logger.exception(
                "tabular bulk-op job cancelled / crashed at job layer",
                extra={
                    "event": "tabular_bulk_op_job_error",
                    "bulk_op_id": bulk_op_id_str,
                    "error_type": type(exc).__name__,
                },
            )
            from sqlalchemy import update

            await session.execute(
                update(TabularBulkOp)
                .where(TabularBulkOp.id == bulk_op_id)
                .values(
                    status="failed",
                    error_text=f"{type(exc).__name__}: {exc}"[:2000],
                    completed_at=datetime.now(UTC),
                )
            )
            await session.commit()
            raise

    logger.info(
        "tabular bulk-op job complete",
        extra={"event": "tabular_bulk_op_complete", "bulk_op_id": bulk_op_id_str},
    )
    return {"bulk_op_id": bulk_op_id_str, "status": "done"}


__all__ = [
    "BULK_OP_CHUNKS_PER_ROW",
    "BULK_OP_MAX_TOKENS",
    "BULK_OP_RESULTS_SCHEMA_VERSION",
    "DEFAULT_PER_CALL_USD",
    "TABULAR_BULK_OP_JOB_NAME",
    "TABULAR_BULK_OP_PURPOSE",
    "build_memo_messages",
    "build_redline_messages",
    "bulk_op_calls_count",
    "estimate_bulk_op_cost",
    "estimate_per_call_cost_usd",
    "invalidate_cache",
    "run_tabular_bulk_op",
    "shape_bulk_op_results",
    "tabular_bulk_op_job",
]
