"""LangGraph nodes for the Tabular Review executor — M3-C2.

Three nodes run sequentially:

1. :func:`load_documents_node` — resolve ``document_ids`` to
   :class:`app.models.document.Document` rows; emit a list of
   document snapshots (id + name) the extraction node reads. Documents
   that have been soft-deleted between request time and worker pickup
   are skipped silently — the row is preserved as audit but the result
   set is honest about which sources were resolvable.
2. :func:`extract_cells_node` — for each ``(document, column)`` pair,
   FTS over the document's chunks using the column's ``query`` as
   keyword input, then run a structured-output LLM call to extract the
   answer + cited chunk indices. Per-cell try/except: any failure (no
   chunks, gateway error, malformed response) lands as
   ``confidence='failed'`` per Decision C-10. Sequential dispatch in
   v0.3.0; per-cell parallelism is a follow-on if 200 x 10 latency
   forces it.
3. :func:`aggregate_node` — group per-cell results by document into
   the final ``tabular_executions.results`` JSONB payload. Flips status
   to ``'completed'`` (or ``'failed'`` if a prior node set
   ``state['error']``). Persists ``cost_actual_usd`` as the sum across
   all cells.

Failure handling: any node may set ``state['error']`` to short-circuit
later nodes. :func:`aggregate_node` reads ``error`` and routes the row
to ``'failed'`` rather than ``'completed'``. Gateway / DB exceptions
inside a node bubble up; the executor catches them at the
graph-invocation boundary.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.models.file import File
from app.models.tabular import TabularExecution
from app.observability_helpers import get_tracer, record_attributes
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest
from app.schemas.tabular import ColumnSpec
from app.tabular.cost import TABULAR_EXTRACTION_PURPOSE
from app.tabular.state import TabularExecutionState

if TYPE_CHECKING:
    from app.clients.gateway import GatewayClient

logger = logging.getLogger(__name__)


# Top-k chunks retrieved per cell. Bounded so the per-cell LLM context
# stays reasonable across the 200 x 10 cell upper bound — at 4 chunks
# x ~500 chars each, input is ~2K plus the system prompt.
RETRIEVAL_TOP_K = 4

# Max tokens for the cell-extraction LLM call. The structured output
# is short — value + cited indices + confidence + brief justification.
EXTRACT_MAX_TOKENS = 500

# Schema-version stamp on the persisted ``results`` JSONB. Bumped on
# any shape-breaking change so the result-view renderer can refuse to
# render unknown versions instead of crashing.
RESULTS_SCHEMA_VERSION = "m3-c2-v1"

_VALID_CONFIDENCES: frozenset[str] = frozenset({"high", "medium", "low", "failed"})


# ---------------------------------------------------------------------------
# load_documents_node
# ---------------------------------------------------------------------------


def make_load_documents_node(
    db: AsyncSession,
    document_ids: list[uuid.UUID],
) -> Callable[[TabularExecutionState], Awaitable[dict[str, Any]]]:
    """Build the load-documents node bound to a DB session."""

    async def load_documents_node(state: TabularExecutionState) -> dict[str, Any]:
        # Join the parent File for the operator-facing filename — the
        # display name for the grid's row label. The Document row itself
        # carries no filename (it lives on files.filename), so without
        # the join the row label falls back to the document UUID.
        stmt = (
            select(Document.id, File.filename)
            .join(File, Document.file_id == File.id)
            .where(Document.id.in_(document_ids))
        )
        by_id = {row.id: row.filename for row in (await db.execute(stmt)).all()}

        # Preserve the operator's selection order (matches the playbook
        # easy_playbook_worker's _load_documents helper); missing rows
        # are silently skipped.
        documents: list[dict[str, str]] = []
        for did in document_ids:
            filename = by_id.get(did)
            if filename is None:
                logger.info(
                    "tabular_executor.load_documents: document missing; skipping",
                    extra={
                        "event": "tabular_load_documents_missing",
                        "document_id": str(did),
                    },
                )
                continue
            documents.append(
                {
                    "id": str(did),
                    "name": filename,
                }
            )

        return {"documents": documents}

    return load_documents_node


# ---------------------------------------------------------------------------
# extract_cells_node
# ---------------------------------------------------------------------------


_EXTRACT_SYSTEM_PROMPT = """\
You are a Tabular Extraction Assistant for a legal AI tool.

You will be given:
* A DOCUMENT NAME (for context).
* A QUERY (the column header's per-row prompt).
* A ranked list of DOCUMENT EXCERPTS retrieved via lexical search over
  the document.

Your job: extract a concise answer to the QUERY from the EXCERPTS, and
cite which excerpts back your answer.

Output STRICTLY VALID JSON in this exact shape:

  {"value": "<extracted value as a short string; empty string if not present>",
   "cited_chunk_indices": [<int>, ...],
   "confidence": "high" | "medium" | "low" | "failed",
   "justification": "<one or two sentences explaining the value or why none was found>"}

Confidence meanings:

* "high" — the answer is stated explicitly in one or more excerpts.
* "medium" — the answer is implied but not stated verbatim.
* "low" — the excerpts only weakly support the answer; flag for human review.
* "failed" — the excerpts do not contain enough information to answer.

The ``cited_chunk_indices`` field is a list of 0-based indices of the
excerpts (in the order presented below) whose content supports your
answer. Always include at least one index for non-"failed" confidence.

Bias toward "failed" when the document does not address the QUERY at
all — false positives are worse than false negatives in tabular review.
"""


def make_extract_cells_node(
    *,
    db: AsyncSession,
    gateway: GatewayClient,
    judge_model: str,
) -> Callable[[TabularExecutionState], Awaitable[dict[str, Any]]]:
    """Build the cell-extraction node bound to a DB session + gateway.

    Walks ``documents x columns`` sequentially; per cell, fetches the
    top-K relevant chunks via FTS using the column's query as keyword
    input, then calls :func:`extract_cell` to dispatch the LLM call.
    Accumulates results into ``state['per_cell_results']``.
    """

    async def extract_cells_node(state: TabularExecutionState) -> dict[str, Any]:
        documents = state.get("documents", []) or []
        columns_raw = state.get("columns", []) or []
        # Re-hydrate the column spec from the state dict shape; the
        # serializable representation lives in state but the cell-level
        # logic wants the Pydantic shape for field access.
        columns = [ColumnSpec.model_validate(col) for col in columns_raw]

        per_cell_results: list[dict[str, Any]] = []

        tracer = get_tracer()
        for document in documents:
            document_id = uuid.UUID(document["id"])
            for column in columns:
                with tracer.start_as_current_span("tabular.cell") as cell_span:
                    record_attributes(
                        cell_span,
                        **{
                            "tabular.document.id": document["id"],
                            "tabular.column.name": column.name,
                        },
                    )
                    chunks = await _fts_over_document(
                        db,
                        document_id=document_id,
                        query=column.query,
                        limit=RETRIEVAL_TOP_K,
                    )
                    cell = await extract_cell(
                        gateway=gateway,
                        judge_model=judge_model,
                        document_name=document["name"],
                        chunks=chunks,
                        column=column,
                    )
                    cell["document_id"] = str(document_id)
                    cell["column_name"] = column.name
                    per_cell_results.append(cell)

        return {"per_cell_results": per_cell_results}

    return extract_cells_node


async def extract_cell(
    *,
    gateway: GatewayClient,
    judge_model: str,
    document_name: str,
    chunks: list[dict[str, Any]],
    column: ColumnSpec,
) -> dict[str, Any]:
    """Run one cell extraction; return a cell-result dict.

    Public surface (not just an internal helper) so the unit tests can
    exercise the LLM-dispatch + parsing logic without standing up the
    full LangGraph workflow + DB.

    Failure paths:

    * No chunks retrieved (empty document or no FTS hits at all on a
      cold-keywordless query) → short-circuit to ``confidence='failed'``
      without a gateway call.
    * Gateway raises → ``confidence='failed'`` with ``error`` populated.
    * LLM response is malformed JSON or missing ``value`` →
      ``confidence='failed'``.
    """

    if not chunks:
        return _failed_cell("no chunks retrieved")

    messages = _build_extract_messages(
        document_name=document_name,
        column=column,
        chunks=chunks,
    )

    request = ChatCompletionRequest(
        model=judge_model,
        messages=messages,
        max_tokens=EXTRACT_MAX_TOKENS,
        anonymize=False,
        lq_ai_purpose=TABULAR_EXTRACTION_PURPOSE,
        minimum_inference_tier=column.minimum_inference_tier,
    )

    try:
        response = await gateway.chat_completion(request)
    except Exception as exc:
        logger.warning(
            "tabular extract_cell gateway error: %s",
            exc,
            extra={
                "event": "tabular_extract_cell_error",
                "error_type": type(exc).__name__,
            },
        )
        return _failed_cell(f"{type(exc).__name__}: {exc}")

    try:
        choices = response.choices
        if not choices:
            return _failed_cell("empty response from gateway")
        content = choices[0].message.content
    except AttributeError:
        return _failed_cell("malformed gateway response")

    if not content:
        return _failed_cell("empty response content")

    parsed = _parse_cell_response(content)
    value = parsed.get("value")
    if not value or not isinstance(value, str) or not value.strip():
        return _failed_cell("no value in extraction response")

    confidence = _coerce_confidence(parsed.get("confidence"))
    cited_indices = _coerce_chunk_indices(
        parsed.get("cited_chunk_indices"),
        n_chunks=len(chunks),
    )
    cited_chunk_ids = [chunks[i]["id"] for i in cited_indices]

    return {
        "value": value.strip(),
        "cited_chunk_ids": cited_chunk_ids,
        "confidence": confidence,
        "tier_used": column.minimum_inference_tier,
        # cost_usd is best filled by the gateway response surface; for
        # v0.3.0 we leave it at 0 here and reconcile from the routing
        # log post-hoc in the aggregate node. The cost-estimator's
        # rolling-average converges off the routing log either way.
        "cost_usd": "0",
        "error": None,
    }


def _failed_cell(reason: str) -> dict[str, Any]:
    return {
        "value": None,
        "cited_chunk_ids": [],
        "confidence": "failed",
        "tier_used": None,
        "cost_usd": "0",
        "error": reason,
    }


def _build_extract_messages(
    *,
    document_name: str,
    column: ColumnSpec,
    chunks: list[dict[str, Any]],
) -> list[ChatCompletionMessage]:
    """Render the extraction-prompt messages for one cell."""

    chunk_blocks: list[str] = []
    for i, chunk in enumerate(chunks):
        chunk_blocks.append(f"[CHUNK {i}]\n{chunk['content']}")

    user_content = (
        f"DOCUMENT NAME: {document_name}\n\n"
        f"QUERY: {column.query}\n\n"
        f"DOCUMENT EXCERPTS:\n" + ("\n\n".join(chunk_blocks) if chunk_blocks else "(none)")
    )
    return [
        ChatCompletionMessage(role="system", content=_EXTRACT_SYSTEM_PROMPT),
        ChatCompletionMessage(role="user", content=user_content),
    ]


async def _fts_over_document(
    db: AsyncSession,
    *,
    document_id: uuid.UUID,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Lexical FTS over ``document_chunks`` scoped to one document.

    Mirrors :func:`app.playbooks.nodes._fts_over_document` — uses
    ``websearch_to_tsquery`` so multi-word queries with OR-like
    semantics rank chunks that hit any token. Falls back to the first
    N chunks when FTS yields nothing (so the LLM still sees document
    context to evaluate)."""

    if not query.strip():
        return await _fetch_first_chunks(db, document_id, limit=limit)

    result = await db.execute(
        text(
            "SELECT dc.id::text, dc.chunk_index, dc.content, "
            "dc.char_offset_start, dc.char_offset_end, dc.page_start, "
            "ts_rank_cd(dc.content_tsv, websearch_to_tsquery('english', :q)) AS rank "
            "FROM document_chunks dc "
            "WHERE dc.document_id = :doc_id "
            "AND dc.content_tsv @@ websearch_to_tsquery('english', :q) "
            "ORDER BY rank DESC, dc.chunk_index ASC "
            "LIMIT :limit"
        ),
        {"q": query, "doc_id": str(document_id), "limit": limit},
    )
    rows = [
        {
            "id": row.id,
            "chunk_index": row.chunk_index,
            "content": row.content,
            "char_offset_start": row.char_offset_start,
            "char_offset_end": row.char_offset_end,
            "page_start": row.page_start,
        }
        for row in result
    ]
    if rows:
        return rows
    return await _fetch_first_chunks(db, document_id, limit=limit)


async def _fetch_first_chunks(
    db: AsyncSession,
    document_id: uuid.UUID,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Defensive fallback when FTS yields no rows."""

    stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(row.id),
            "chunk_index": row.chunk_index,
            "content": row.content,
            "char_offset_start": row.char_offset_start,
            "char_offset_end": row.char_offset_end,
            "page_start": row.page_start,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# aggregate_node — group cells by document, persist results
# ---------------------------------------------------------------------------


def make_aggregate_node(
    db: AsyncSession,
) -> Callable[[TabularExecutionState], Awaitable[dict[str, Any]]]:
    """Build the aggregation node bound to a DB session.

    Groups ``state['per_cell_results']`` by document into the final
    ``tabular_executions.results`` JSONB shape; flips status to
    ``'completed'`` (or ``'failed'`` if a prior node set
    ``state['error']``); writes ``cost_actual_usd`` as the sum across
    cells; sets ``completed_at``.
    """

    async def aggregate_node(state: TabularExecutionState) -> dict[str, Any]:
        execution_id = uuid.UUID(state["execution_id"])
        documents = state.get("documents", []) or []
        per_cell_results = state.get("per_cell_results", []) or []
        error = state.get("error")

        results_payload = _shape_results_payload(per_cell_results, documents)
        cost_actual = _sum_cell_costs(per_cell_results)

        values: dict[str, Any] = {
            "results": results_payload,
            "cost_actual_usd": cost_actual,
            "completed_at": datetime.now(UTC),
        }
        if error:
            values["status"] = "failed"
            values["error_text"] = str(error)[:2000]
        else:
            values["status"] = "completed"

        await db.execute(
            update(TabularExecution).where(TabularExecution.id == execution_id).values(**values)
        )
        await db.commit()
        return {}

    return aggregate_node


def _assemble_rows(
    per_cell_results: list[Any],
    documents: list[Any],
) -> list[dict[str, Any]]:
    """Group cells by document and emit rows in ``documents`` order.

    Cells are keyed by ``column_name`` within each row. The per-cell
    in-flight shape (with ``document_id`` + ``column_name`` keys) gets
    converted to the persisted :class:`app.schemas.tabular.CellResult`
    shape (no document_id / column_name; those live on the row /
    cell-map key)."""

    by_doc: dict[str, dict[str, dict[str, Any]]] = {}
    for cell in per_cell_results:
        doc_id = cell.get("document_id")
        col_name = cell.get("column_name")
        if not doc_id or not col_name:
            continue
        by_doc.setdefault(doc_id, {})[col_name] = _strip_state_keys(cell)

    rows: list[dict[str, Any]] = []
    for doc in documents:
        cells = by_doc.get(doc["id"], {})
        rows.append(
            {
                "document_id": doc["id"],
                "document_name": doc["name"],
                "cells": cells,
            }
        )
    return rows


def _strip_state_keys(cell: dict[str, Any]) -> dict[str, Any]:
    """Project the in-flight cell shape down to the persisted shape."""
    keys = ("value", "cited_chunk_ids", "confidence", "tier_used", "cost_usd", "error")
    return {key: cell.get(key) for key in keys}


def _shape_results_payload(
    per_cell_results: list[Any],
    documents: list[Any],
) -> dict[str, Any]:
    """Render the per-cell results into the JSONB payload shape."""

    rows = _assemble_rows(per_cell_results, documents)
    total = len(per_cell_results)
    failed = sum(1 for c in per_cell_results if c.get("confidence") == "failed")
    return {
        "schema_version": RESULTS_SCHEMA_VERSION,
        "rows": rows,
        "summary": {
            "total_cells": total,
            "failed_cells": failed,
        },
    }


def _sum_cell_costs(per_cell_results: list[Any]) -> Decimal:
    """Sum per-cell costs to derive ``cost_actual_usd``.

    Cells without a recorded cost contribute 0 — the v0.3.0 cell node
    does not yet propagate per-call cost back from the gateway
    response surface, so this defaults to 0 across all cells until
    the gateway returns cost in its response shape. Once it does,
    this sum becomes the authoritative actual."""

    total = Decimal("0")
    for cell in per_cell_results:
        raw = cell.get("cost_usd")
        if raw is None:
            continue
        try:
            total += Decimal(str(raw))
        except Exception:
            continue
    return total


# ---------------------------------------------------------------------------
# Structured-output JSON parser (lenient)
# ---------------------------------------------------------------------------


def _parse_cell_response(content: str) -> dict[str, Any]:
    """Lenient JSON parse — trim a leading code fence if present, then
    :func:`json.loads`."""

    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```", 2)[1]
        if stripped.startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.rstrip("`").strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        logger.warning(
            "tabular extract_cell returned malformed JSON: %s",
            exc,
            extra={"event": "tabular_extract_cell_malformed_json"},
        )
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _coerce_confidence(raw: Any) -> str:
    """Normalize confidence to one of the four valid values; default ``low``."""

    if isinstance(raw, str) and raw in _VALID_CONFIDENCES:
        return raw
    return "low"


def _coerce_chunk_indices(raw: Any, *, n_chunks: int) -> list[int]:
    """Filter the model-emitted index list to valid 0-based ints inside the chunk count."""

    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for item in raw:
        if isinstance(item, int) and not isinstance(item, bool) and 0 <= item < n_chunks:
            out.append(item)
    return out


__all__ = [
    "RESULTS_SCHEMA_VERSION",
    "RETRIEVAL_TOP_K",
    "extract_cell",
    "make_aggregate_node",
    "make_extract_cells_node",
    "make_load_documents_node",
]
