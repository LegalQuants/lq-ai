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
import math
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.caselaw import locate_passage
from app.citation.verification import verify
from app.models.document import Document, DocumentChunk
from app.models.file import File
from app.models.tabular import TabularCellCitation, TabularExecution
from app.observability_helpers import get_tracer, record_attributes
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest
from app.schemas.tabular import ColumnSpec
from app.tabular.cost import TABULAR_EXTRACTION_PURPOSE
from app.tabular.state import TabularExecutionState

if TYPE_CHECKING:
    from app.clients.gateway import EnsembleConfig, GatewayClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cell-verification candidate / document stubs (Donna #6)
# ---------------------------------------------------------------------------
#
# The Citation Engine's :func:`app.citation.verification.verify` reads a
# candidate (the "claim") and a document (the "source") via duck-typed
# protocols. For a tabular cell the claim is the extracted value and the
# source is the concatenated cited-chunk text. We mint these minimal
# stubs (mirroring ``tests/citation/test_ensemble.py``'s
# ``_StubCandidate`` / ``_StubDocument``) rather than load a real
# Document row — the cell's grounding evidence is the chunk text already
# in hand, and the synthetic ids only feed a trace-span attribute.


# Not ``frozen`` — the verifier's ``_CandidateProtocol`` /
# ``_DocumentProtocol`` declare settable attributes, so a frozen
# (read-only) dataclass fails the structural-subtype check. ``slots``
# keeps them lightweight; we never mutate them after construction.
@dataclass(slots=True)
class _CellVerifyCandidate:
    source_offset_start: int
    source_offset_end: int
    source_text: str
    source_document_id: uuid.UUID


@dataclass(slots=True)
class _CellVerifyDocument:
    id: uuid.UUID
    normalized_content: str
    was_ocrd: bool = False


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

        # Resolve the gateway's Stage-4 ensemble config ONCE for the whole
        # run (the lookup is process-cached). Per column we then decide
        # the effective flag: explicit per-column value wins; None falls
        # back to the gateway's deployment default. ``verify_ensemble_config``
        # is the gateway config when this column should actually run
        # ensemble AND the gateway has ensemble configured — else None.
        #
        # Cost posture (intentional): tabular ensemble verification runs one
        # ensemble pass per cell and is NOT bounded by a mid-run per-message
        # cost cap the way the chat path is (``_resolve_ensemble_config`` in
        # ``api/app/api/chats.py`` falls back to a single judge once an
        # estimate exceeds ``max_cost_per_message_usd``). Instead, tabular
        # gates cost up-front: ``POST /api/v1/tabular/preview-cost`` surfaces
        # the ensemble premium and the operator confirms ``confirmed_cost_usd``
        # before the run starts (Decision C-5 cost-confirmation gate). A future
        # mid-run / per-cell ensemble cost ceiling is deferred as DE-331.
        ensemble_config = await gateway.get_citation_engine_ensemble_config()

        tracer = get_tracer()
        for document in documents:
            document_id = uuid.UUID(document["id"])
            for column in columns:
                effective = (
                    column.ensemble_verification
                    if column.ensemble_verification is not None
                    else (ensemble_config.default_enabled if ensemble_config is not None else False)
                )
                verify_ensemble_config = (
                    ensemble_config if (effective and ensemble_config is not None) else None
                )
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
                        verify_ensemble_config=verify_ensemble_config,
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
    verify_ensemble_config: EnsembleConfig | None = None,
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
    value = value.strip()

    # Stage-4 ensemble verification (Donna #6). When this column should
    # run ensemble (config supplied) and the cell has grounding chunks,
    # run ONE ensemble pass over the concatenation of ALL cited chunks:
    # the "claim" is the extracted value, the "source" is the cited
    # chunk text. Stages 1-2 usually MISS (a short value rarely equals
    # the long concatenation), so Stage 4 fires. Note: a near-verbatim
    # single-chunk value CAN legitimately hit Stage 1 (``exact_match``) or
    # Stage 2 (``fuzz.ratio`` >= 95, ``tolerant_match``) — that surfaces a
    # ``verification_method`` of ``exact_match``/``tolerant_match`` instead
    # of an ``ensemble_*`` value, which is a STRONGER verification, not an
    # error. A verification failure must NEVER fail the cell or alter its
    # value/confidence/citations, so the whole pass is defensively wrapped.
    verification_method: str | None = None
    if verify_ensemble_config is not None and cited_chunk_ids:
        verification_method = await _verify_cell_ensemble(
            gateway=gateway,
            value=value,
            chunks=chunks,
            cited_chunk_ids=cited_chunk_ids,
            ensemble_config=verify_ensemble_config,
        )

    # DE-309: deterministic offset-bearing provenance. Locate the
    # extracted value verbatim inside each cited chunk's canonical text;
    # every hit becomes a ``cell_citations`` entry the aggregate node
    # persists as a ``tabular_cell_citations`` row. Fail-closed: a miss
    # mints nothing (the cell renders unverified read-side) — never a
    # fake offset row. In-flight only; ``_strip_state_keys`` drops it
    # from the persisted results JSONB.
    cell_citations = await _locate_cell_citations(
        value=value,
        chunks=chunks,
        cited_chunk_ids=cited_chunk_ids,
    )

    # DE-310: real per-cell tier + cost from the gateway's response
    # annotations (``_annotate_response`` stamps ``routed_inference_tier``
    # + ``cost_estimate`` on every non-streaming completion). ``getattr``
    # because the annotations are gateway extensions a minimal
    # OpenAI-shaped response may lack; a missing annotation degrades to
    # ``None`` (schema-nullable) rather than claiming the column's tier
    # floor as the routed tier or ``"0"`` as a cost that was never
    # reported. Ensemble judge spend (``_verify_cell_ensemble``) is NOT
    # included: the shared verification cascade
    # (:func:`app.citation.verification.verify`) discards the judge
    # responses' cost annotations before returning, and threading cost
    # through :class:`VerificationResult` reshapes the chat Citation
    # Engine's surface — out of scope here; the routing log still
    # records those judge calls.
    return {
        "value": value,
        "cited_chunk_ids": cited_chunk_ids,
        "confidence": confidence,
        "tier_used": getattr(response, "routed_inference_tier", None),
        "cost_usd": _cost_usd_str(getattr(response, "cost_estimate", None)),
        "error": None,
        "verification_method": verification_method,
        "cell_citations": cell_citations,
    }


def _cost_usd_str(cost_estimate: Any) -> str | None:
    """Decimal-stringify the gateway's float ``cost_estimate`` annotation.

    Fixed-point notation (never scientific — ``format(..., 'f')``) per
    the Decimal-as-string wire rule; ``None`` (or a non-numeric value)
    stays ``None`` — an unreported cost is unknown, not zero.
    """

    if not isinstance(cost_estimate, (int, float)) or isinstance(cost_estimate, bool):
        return None
    if not math.isfinite(cost_estimate):
        return None
    return format(Decimal(str(cost_estimate)), "f")


async def _verify_cell_ensemble(
    *,
    gateway: GatewayClient,
    value: str,
    chunks: list[dict[str, Any]],
    cited_chunk_ids: list[str],
    ensemble_config: EnsembleConfig,
) -> str | None:
    """Run one Stage-4 ensemble verify pass for a tabular cell.

    Concatenates ALL cited chunks' content as the source and the
    extracted ``value`` as the claim, then dispatches through
    :func:`app.citation.verification.verify`. Returns the method string
    (e.g. ``ensemble_strict``) when the ensemble verified the value, else
    ``None``. Any exception degrades to ``None`` — a verification failure
    is never a cell failure.
    """

    try:
        cited_set = set(cited_chunk_ids)
        concat = "\n---\n".join(chunk["content"] for chunk in chunks if chunk["id"] in cited_set)
        # Deterministic synthetic ids — used only for a trace-span
        # attribute, so a stable uuid5 off the primary chunk id is
        # preferred over uuid4.
        synthetic_id = uuid.uuid5(uuid.NAMESPACE_DNS, cited_chunk_ids[0])
        candidate = _CellVerifyCandidate(
            source_offset_start=0,
            source_offset_end=len(concat),
            source_text=value,
            source_document_id=synthetic_id,
        )
        document = _CellVerifyDocument(id=synthetic_id, normalized_content=concat)
        result = await verify(
            candidate,
            document,
            gateway=gateway,
            ensemble_config=ensemble_config,
        )
        return result.method if result.verified else None
    except Exception as exc:
        logger.warning(
            "tabular extract_cell ensemble verification error: %s",
            exc,
            extra={
                "event": "tabular_extract_cell_verify_error",
                "error_type": type(exc).__name__,
            },
        )
        return None


async def _locate_cell_citations(
    *,
    value: str,
    chunks: list[dict[str, Any]],
    cited_chunk_ids: list[str],
) -> list[dict[str, Any]]:
    """Deterministically locate ``value`` in each cited chunk's text (DE-309).

    Verbatim-only, mirroring the fetched-authority pass in
    :mod:`app.citation.authority`: :func:`locate_passage` finds the exact
    substring span, then the located span is confirmed through the
    verification cascade with ``gateway=None`` (Stages 1-2 only — no LLM
    judge for cells in this item). A hit yields one in-flight citation
    dict per cited chunk with chunk-local char offsets + the cascade's
    method/confidence; a miss yields nothing for that chunk (fail-closed
    — an unlocatable value must render unverified, never carry a fake
    offset row).

    Duplicate cited chunk ids are deduplicated (first occurrence wins)
    so a model emitting ``[0, 0]`` can't mint the same provenance row
    twice. Any unexpected exception degrades to "no citations located"
    for the remaining chunks — provenance minting must never fail the
    cell.
    """

    if not value or not cited_chunk_ids:
        return []

    content_by_id = {chunk["id"]: chunk["content"] for chunk in chunks}
    located: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk_id in cited_chunk_ids:
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        try:
            content = content_by_id.get(chunk_id)
            if not content:
                continue
            span = locate_passage(value, content)
            if span is None:
                continue
            start, end = span
            candidate = _CellVerifyCandidate(
                source_offset_start=start,
                source_offset_end=end,
                # locate_passage strips the needle before searching, so
                # the located slice is the stripped value — use exactly
                # what was located so Stage 1 compares byte-for-byte.
                source_text=content[start:end],
                source_document_id=uuid.UUID(chunk_id),
            )
            document = _CellVerifyDocument(id=uuid.UUID(chunk_id), normalized_content=content)
            # gateway=None: the cascade runs Stages 1-2 only and MISSes
            # rather than escalating to a judge. With byte-exact offsets
            # from locate_passage this confirms as ``exact_match``; the
            # defensive re-check keeps the row's method/confidence
            # anchored in the canonical cascade rather than asserted here.
            result = await verify(candidate, document, gateway=None)
            if not result.verified or result.method is None:
                continue
            located.append(
                {
                    "chunk_id": chunk_id,
                    "source_offset_start": start,
                    "source_offset_end": end,
                    "verification_method": result.method,
                    "verification_confidence": result.confidence,
                }
            )
        except Exception as exc:
            logger.warning(
                "tabular cell citation locate error: %s",
                exc,
                extra={
                    "event": "tabular_cell_citation_locate_error",
                    "error_type": type(exc).__name__,
                },
            )
            continue
    return located


def _failed_cell(reason: str) -> dict[str, Any]:
    return {
        "value": None,
        "cited_chunk_ids": [],
        "confidence": "failed",
        "tier_used": None,
        "cost_usd": "0",
        "error": reason,
        "verification_method": None,
        "cell_citations": [],
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

        # DE-309: batch-insert the offset-bearing provenance rows the
        # extract node located, in the SAME transaction as the results
        # write — the grid and its provenance land (or roll back)
        # together.
        db.add_all(_mint_cell_citation_rows(execution_id, per_cell_results))

        await db.execute(
            update(TabularExecution).where(TabularExecution.id == execution_id).values(**values)
        )
        await db.commit()
        return {}

    return aggregate_node


def _mint_cell_citation_rows(
    execution_id: uuid.UUID,
    per_cell_results: list[Any],
) -> list[TabularCellCitation]:
    """Project in-flight ``cell_citations`` into :class:`TabularCellCitation` rows.

    One row per located (cell, chunk) pair, keyed the way cells are keyed
    in the results payload: ``document_id`` (the grid row) +
    ``column_name`` (the grid column). Cells without located citations
    contribute nothing — the absence of rows IS the unverified signal
    (fail-closed). Malformed in-flight entries are skipped rather than
    sinking the aggregate write.
    """

    rows: list[TabularCellCitation] = []
    for cell in per_cell_results:
        doc_id = cell.get("document_id")
        col_name = cell.get("column_name")
        if not doc_id or not col_name:
            continue
        for citation in cell.get("cell_citations") or []:
            try:
                confidence = citation.get("verification_confidence")
                rows.append(
                    TabularCellCitation(
                        execution_id=execution_id,
                        document_id=uuid.UUID(str(doc_id)),
                        column_name=col_name,
                        chunk_id=uuid.UUID(str(citation["chunk_id"])),
                        source_offset_start=int(citation["source_offset_start"]),
                        source_offset_end=int(citation["source_offset_end"]),
                        verification_method=str(citation["verification_method"]),
                        verification_confidence=(
                            Decimal(str(round(float(confidence), 2)))
                            if confidence is not None
                            else None
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "tabular aggregate: malformed cell citation skipped: %s",
                    exc,
                    extra={
                        "event": "tabular_cell_citation_malformed",
                        "error_type": type(exc).__name__,
                    },
                )
                continue
    return rows


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
    """Project the in-flight cell shape down to the persisted shape.

    ``document_id`` / ``column_name`` move to the row / cell-map key;
    ``cell_citations`` (DE-309) is persisted as ``tabular_cell_citations``
    rows by the aggregate node, not in the results JSONB — the payload
    shape (schema_version m3-c2-v1) is unchanged.
    """
    keys = (
        "value",
        "cited_chunk_ids",
        "confidence",
        "tier_used",
        "cost_usd",
        "error",
        "verification_method",
    )
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

    ``cost_usd`` carries the gateway's per-call ``cost_estimate``
    annotation as a decimal string (DE-310), so this sum is the actual
    extraction spend. Cells without a recorded cost (failed before the
    gateway call, or the gateway had no rate configured for the routed
    model) contribute 0. Ensemble judge spend is not included — see
    the DE-310 note in :func:`extract_cell`."""

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
