"""LangGraph nodes for the Playbook executor — M3-A2.

Four nodes run sequentially:

1. :func:`retrieve_node` — for each position, FTS over the target
   document's chunks using ``detection_keywords`` (lexical) to pick
   candidate clauses.
2. :func:`classify_node` — one structured-output LLM call per position
   producing ``matches_standard | matches_fallback | deviates | missing``
   plus a confidence and the chunks the verdict referenced.
3. :func:`redline_node` — for ``deviates`` verdicts only, a second
   structured-output LLM call drafts ``{old_text, new_text, justification}``
   per the position's ``redline_strategy``.
4. :func:`compile_node` — assembles the per-position results into the
   final ``playbook_executions.results`` JSONB payload and flips the
   execution row to ``completed`` (or ``error`` if a prior node set
   ``state["error"]``).

The dependencies the nodes need (DB session, gateway client, judge
model) live in node closures returned by the factories below — keeps
the node functions pure-ish over the state dict so LangGraph's merge
semantics stay clean.

Failure handling: any node may set ``state["error"]`` to short-circuit
later nodes. :func:`compile_node` checks for it and flips the execution
row to ``status='error'`` rather than ``'completed'``. Gateway / DB
exceptions inside a node bubble up; the executor catches them at the
graph-invocation boundary and updates the row similarly.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient
from app.models.document import DocumentChunk
from app.models.playbook import PlaybookExecution
from app.observability_helpers import get_tracer, record_attributes
from app.playbooks.state import (
    PlaybookExecutionState,
    PositionVerdict,
)
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest

logger = logging.getLogger(__name__)

# Top-k chunks retrieved per position. Keeps the classifier's context
# window bounded — the Playbook executor calls the LLM N times (once
# per position), so per-call cost matters. 4 chunks is enough to cover
# most clause spans while staying well under the typical 8K-input cap
# even on cheap models.
RETRIEVAL_TOP_K = 4

# Maximum tokens for the classify call. The structured output is
# short — verdict + confidence + matched_text + justification — so
# 600 tokens is generous without letting a chatty model run away.
CLASSIFY_MAX_TOKENS = 600

# Maximum tokens for the redline call. Slightly larger because the
# redline output includes old_text + new_text + justification, all
# free-form English.
REDLINE_MAX_TOKENS = 800

# Classifier output JSON schema (documented in the prompt; parsed by
# :func:`_parse_classify_response`). The verdict + confidence pair
# mirrors the M2-C1 paraphrase-judge shape so future telemetry can
# unify on a single verdict-confidence schema across surfaces.
_VALID_VERDICTS: frozenset[str] = frozenset(
    {"matches_standard", "matches_fallback", "deviates", "missing"}
)
_VALID_CONFIDENCES: frozenset[str] = frozenset({"high", "medium", "low"})
_CONFIDENCE_NUMERIC: dict[str, float] = {"high": 0.9, "medium": 0.7, "low": 0.5}


# ---------------------------------------------------------------------------
# Retrieve
# ---------------------------------------------------------------------------


def make_retrieve_node(
    db: AsyncSession,
) -> Callable[[PlaybookExecutionState], Awaitable[dict[str, Any]]]:
    """Build the retrieve node bound to a DB session."""

    async def retrieve_node(state: PlaybookExecutionState) -> dict[str, Any]:
        target_doc_id = uuid.UUID(state["target_document_id"])
        retrievals: list[dict[str, Any]] = []

        for pos in state.get("positions", []):
            # Lexical FTS over the target document's chunks. The query
            # is the union of detection_keywords; we'd prefer to also
            # mix in detection_examples via vector search, but per-doc
            # embedding search adds a layer of complexity the executor
            # skeleton doesn't need to ship with — the keyword path
            # works well for the high-signal contract-clause case
            # (counterparty / cap / term / governing law), and the
            # M3-A2 spec accepts this scope.
            keywords = pos.get("detection_keywords") or []
            if not keywords:
                # No keywords supplied → take the first chunk as a
                # defensive fallback so the classifier still sees the
                # document. This is the "missing keyword" failure mode
                # operators see if they author a playbook position
                # without populating ``detection_keywords``.
                logger.info(
                    "playbook_executor.retrieve: position has no detection_keywords",
                    extra={
                        "event": "playbook_retrieve_no_keywords",
                        "position_id": pos["id"],
                        "issue": pos["issue"],
                    },
                )
                fallback = await _fetch_first_chunks(db, target_doc_id, limit=RETRIEVAL_TOP_K)
                retrievals.append({"position_id": pos["id"], "chunks": fallback})
                continue

            query = " ".join(keywords)
            chunks = await _fts_over_document(
                db,
                document_id=target_doc_id,
                query=query,
                limit=RETRIEVAL_TOP_K,
            )
            if not chunks:
                # No FTS hits — fall back to the document's first
                # chunks so the classifier still has document context
                # to evaluate. The classifier's verdict in this case
                # will typically be ``missing`` (the position's clause
                # isn't in the doc).
                chunks = await _fetch_first_chunks(db, target_doc_id, limit=RETRIEVAL_TOP_K)
            retrievals.append({"position_id": pos["id"], "chunks": chunks})

        return {"retrievals": retrievals}

    return retrieve_node


async def _fts_over_document(
    db: AsyncSession,
    *,
    document_id: uuid.UUID,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Run FTS over ``document_chunks`` scoped to one document.

    Uses ``websearch_to_tsquery`` rather than ``plainto_tsquery`` so
    multi-keyword queries with OR-like semantics rank chunks that hit
    any keyword (the user's intent when they list multiple
    ``detection_keywords``).
    """
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
    return [
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


async def _fetch_first_chunks(
    db: AsyncSession,
    document_id: uuid.UUID,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Defensive fallback when the FTS yields no rows for a position."""
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
# Classify
# ---------------------------------------------------------------------------


_CLASSIFY_SYSTEM_PROMPT = """\
You are a Contract Review Classifier for a legal AI assistant.

You will be given:
* The org's STANDARD POSITION on a contract issue (the preferred clause).
* A ranked list of FALLBACK TIERS — acceptable alternatives to the standard.
* The actual CONTRACT EXCERPT to evaluate.

Your job: determine how the contract excerpt compares to the standard
+ fallbacks. Output STRICTLY VALID JSON in this exact shape:

  {"verdict": "matches_standard" | "matches_fallback" | "deviates" | "missing",
   "confidence": "high" | "medium" | "low",
   "matched_fallback_rank": <int|null>,
   "matched_text": "<verbatim quote of the contract clause your verdict references, or empty if missing>",
   "cited_chunk_indices": [<int>, ...],
   "justification": "<one or two sentences explaining your verdict>"}

Verdict meanings:

* "matches_standard" — the contract's clause is materially equivalent
  to the standard position (same legal effect; wording may differ).
* "matches_fallback" — the contract's clause matches one of the
  fallback tiers. Populate ``matched_fallback_rank`` with the matched
  tier's rank (1 = preferred fallback; higher numbers = weaker).
* "deviates" — the contract addresses the issue but the clause is
  worse than every listed fallback. The redliner will draft a
  suggested edit using the position's redline_strategy.
* "missing" — the contract does NOT address the issue at all. Leave
  ``matched_text`` empty.

Confidence meanings:

* "high" — the verdict is unambiguous; another careful reader would
  reach the same conclusion.
* "medium" — the verdict is supported but reasonable readers might
  disagree.
* "low" — the source evidence is thin or ambiguous; flag for human
  review.

The ``cited_chunk_indices`` field is a list of the 0-based indices of
the chunks (in the order they were presented below) whose content
supports your verdict. Always include at least one index for
non-``missing`` verdicts.

Bias toward "low" confidence and toward ``missing`` on uncertainty.
False positives — calling a missing position "matches" — do more
damage in contract review than false negatives.
"""


def make_classify_node(
    *,
    gateway: GatewayClient,
    judge_model: str,
) -> Callable[[PlaybookExecutionState], Awaitable[dict[str, Any]]]:
    """Build the classify node bound to a gateway client + model alias."""

    async def classify_node(state: PlaybookExecutionState) -> dict[str, Any]:
        # Typed-as-Any because the chunk items are TypedDict
        # (``_ChunkForRetrieval``); mypy refuses to widen them to plain
        # dicts. Same posture as :func:`redline_node`.
        retrievals_by_position: dict[str, list[Any]] = {
            r["position_id"]: list(r["chunks"]) for r in state.get("retrievals", [])
        }
        results: list[dict[str, Any]] = []

        tracer = get_tracer()
        for pos in state.get("positions", []):
            with tracer.start_as_current_span("playbook.position") as pos_span:
                record_attributes(
                    pos_span,
                    **{
                        "playbook.position.id": str(pos["id"]),
                        "playbook.position.order": pos.get("position_order"),
                    },
                )
                chunks = retrievals_by_position.get(pos["id"], [])
                messages = _build_classify_messages(pos, chunks)
                verdict_data = await _dispatch_structured_call(
                    gateway=gateway,
                    model=judge_model,
                    messages=messages,
                    max_tokens=CLASSIFY_MAX_TOKENS,
                )

                verdict = _coerce_verdict(verdict_data.get("verdict"))
                confidence_str = _coerce_confidence(verdict_data.get("confidence"))
                cited_indices = _coerce_chunk_indices(
                    verdict_data.get("cited_chunk_indices"), n_chunks=len(chunks)
                )
                cited_chunk_ids = [chunks[i]["id"] for i in cited_indices] if chunks else []
                matched_text = str(verdict_data.get("matched_text") or "")
                justification = str(verdict_data.get("justification") or "")
                matched_fallback_rank_raw = verdict_data.get("matched_fallback_rank")
                matched_fallback_rank: int | None
                if verdict == "matches_fallback" and isinstance(matched_fallback_rank_raw, int):
                    matched_fallback_rank = matched_fallback_rank_raw
                else:
                    matched_fallback_rank = None

                results.append(
                    {
                        "position_id": pos["id"],
                        "issue": pos["issue"],
                        "severity_if_missing": pos["severity_if_missing"],
                        "verdict": verdict,
                        "confidence": _CONFIDENCE_NUMERIC[confidence_str],
                        "matched_fallback_rank": matched_fallback_rank,
                        "cited_chunk_ids": cited_chunk_ids,
                        "matched_text": matched_text,
                        "redline": None,
                        "justification": justification,
                    }
                )

        return {"per_position_results": results}

    return classify_node


def _build_classify_messages(
    position: Any,
    chunks: list[Any],
) -> list[ChatCompletionMessage]:
    """Render the classify-prompt messages for one position + its retrieved chunks.

    Typed as :data:`Any` for the same TypedDict-widening reason as
    :func:`_build_redline_messages` (q.v.).
    """
    fallback_lines: list[str] = []
    for tier in position.get("fallback_tiers") or []:
        rank = tier.get("rank")
        description = tier.get("description") or ""
        language = tier.get("language") or ""
        fallback_lines.append(f"Tier {rank} — {description}\nLanguage:\n{language}")

    chunk_blocks: list[str] = []
    for i, chunk in enumerate(chunks):
        chunk_blocks.append(f"[CHUNK {i}]\n{chunk['content']}")

    user_content = (
        f"ISSUE: {position['issue']}\n\n"
        f"STANDARD POSITION:\n{position['standard_language']}\n\n"
        f"FALLBACK TIERS:\n"
        + ("\n\n".join(fallback_lines) if fallback_lines else "(none specified)")
        + "\n\n"
        + "CONTRACT EXCERPT:\n"
        + ("\n\n".join(chunk_blocks) if chunk_blocks else "(no chunks retrieved)")
    )
    return [
        ChatCompletionMessage(role="system", content=_CLASSIFY_SYSTEM_PROMPT),
        ChatCompletionMessage(role="user", content=user_content),
    ]


# ---------------------------------------------------------------------------
# Redline
# ---------------------------------------------------------------------------


_REDLINE_SYSTEM_PROMPT = """\
You are a Contract Redline Drafter for a legal AI assistant.

You will be given:
* The org's STANDARD POSITION on a contract issue.
* The contract's CURRENT CLAUSE that deviates from the standard.
* The REDLINE STRATEGY — instructions on how to redline this position.

Draft a tracked-changes redline. Output STRICTLY VALID JSON:

  {"old_text": "<verbatim text from the contract that should be replaced>",
   "new_text": "<suggested replacement text>",
   "justification": "<one or two sentences explaining why the change improves the contract>"}

The ``old_text`` field MUST be a verbatim substring of the contract
clause provided — the operator's editor will use it for textual
matching. If you cannot identify a single contiguous span to replace,
return ``old_text`` as the empty string and explain in
``justification``.

Preserve the contract's drafting style — match definite/indefinite
articles, capitalization, and tense. Don't introduce defined terms
that aren't already in the contract.
"""


def make_redline_node(
    *,
    gateway: GatewayClient,
    judge_model: str,
) -> Callable[[PlaybookExecutionState], Awaitable[dict[str, Any]]]:
    """Build the redline node bound to a gateway client + model alias.

    Iterates :func:`classify_node`'s ``per_position_results`` and runs a
    structured-output LLM call for each ``"deviates"`` row, populating
    its ``redline`` field. Non-deviating rows pass through unchanged.
    """

    positions_index: dict[str, dict[str, Any]] = {}

    async def redline_node(state: PlaybookExecutionState) -> dict[str, Any]:
        # Rebuild the per-position index for redline_strategy lookup.
        # Typed-as-Any because the position items are TypedDict; mypy
        # narrows them to ``_PositionInput`` and refuses the
        # ``dict[str, Any]`` value annotation otherwise.
        nonlocal positions_index
        positions_index = {pos["id"]: dict(pos) for pos in state.get("positions", [])}

        updated: list[Any] = []
        for result in state.get("per_position_results", []):
            if result.get("verdict") != "deviates":
                updated.append(result)
                continue

            pos = positions_index.get(result["position_id"])
            if pos is None:
                # Defensive: the position vanished between classify and
                # redline. Pass through without a redline.
                updated.append(result)
                continue

            messages = _build_redline_messages(pos, result)
            redline_data = await _dispatch_structured_call(
                gateway=gateway,
                model=judge_model,
                messages=messages,
                max_tokens=REDLINE_MAX_TOKENS,
            )
            redline = {
                "old_text": str(redline_data.get("old_text") or ""),
                "new_text": str(redline_data.get("new_text") or ""),
                "justification": str(redline_data.get("justification") or ""),
            }
            updated.append({**result, "redline": redline})

        return {"per_position_results": updated}

    return redline_node


def _build_redline_messages(
    position: Any,
    classify_result: Any,
) -> list[ChatCompletionMessage]:
    """Render the redline-prompt messages for one deviating position.

    Typed as :data:`Any` because the runtime callers pass TypedDict
    instances (``_PositionInput`` / ``_PositionResult``) that
    structurally satisfy the dict access here. mypy doesn't widen
    TypedDicts to plain dicts automatically; the structural-only
    access keeps this safe.
    """
    user_content = (
        f"ISSUE: {position['issue']}\n\n"
        f"STANDARD POSITION:\n{position['standard_language']}\n\n"
        f"REDLINE STRATEGY:\n{position.get('redline_strategy') or '(none specified)'}\n\n"
        f"CONTRACT'S CURRENT CLAUSE:\n{classify_result.get('matched_text') or ''}"
    )
    return [
        ChatCompletionMessage(role="system", content=_REDLINE_SYSTEM_PROMPT),
        ChatCompletionMessage(role="user", content=user_content),
    ]


# ---------------------------------------------------------------------------
# Compile + persist
# ---------------------------------------------------------------------------


def make_compile_node(
    db: AsyncSession,
) -> Callable[[PlaybookExecutionState], Awaitable[dict[str, Any]]]:
    """Build the compile node bound to a DB session.

    The compile node writes the assembled results into
    ``playbook_executions`` and flips status to ``'completed'`` (or
    ``'error'`` if a prior node set ``state["error"]``). It also
    populates ``completed_at``.
    """

    async def compile_node(state: PlaybookExecutionState) -> dict[str, Any]:
        execution_id = uuid.UUID(state["execution_id"])
        results_payload = _shape_results_payload(state)
        error = state.get("error")

        if error:
            await db.execute(
                update(PlaybookExecution)
                .where(PlaybookExecution.id == execution_id)
                .values(
                    status="error",
                    error=error,
                    results=results_payload,
                    completed_at=datetime.now(UTC),
                )
            )
        else:
            await db.execute(
                update(PlaybookExecution)
                .where(PlaybookExecution.id == execution_id)
                .values(
                    status="completed",
                    results=results_payload,
                    completed_at=datetime.now(UTC),
                )
            )
        await db.commit()
        return {}

    return compile_node


def _shape_results_payload(state: PlaybookExecutionState) -> dict[str, Any]:
    """Render the per-position results into the JSONB payload shape."""
    per_position = state.get("per_position_results", [])
    summary = _summarize(per_position)
    return {
        "schema_version": "m3-a2-v1",
        "positions": per_position,
        "summary": summary,
    }


def _summarize(per_position: list[Any]) -> dict[str, int]:
    """Aggregate per-position verdict counts for the UI summary card.

    Typed as ``list[Any]`` because the runtime callers pass a list of
    ``_PositionResult`` TypedDicts; mypy doesn't widen TypedDicts to
    plain dicts. The aggregation only reads the ``verdict`` key.
    """
    counts = {
        "matches_standard": 0,
        "matches_fallback": 0,
        "deviates": 0,
        "missing": 0,
    }
    for result in per_position:
        verdict = result.get("verdict")
        if verdict in counts:
            counts[verdict] += 1
    return counts


# ---------------------------------------------------------------------------
# Structured-output dispatcher
# ---------------------------------------------------------------------------


async def _dispatch_structured_call(
    *,
    gateway: GatewayClient,
    model: str,
    messages: list[ChatCompletionMessage],
    max_tokens: int,
) -> dict[str, Any]:
    """Run a structured-JSON LLM call and return the parsed dict.

    Mirrors the M2-C1 paraphrase-judge dispatch pattern. ``temperature``
    is omitted: Anthropic Opus 4.x reasoning models rejected the
    parameter as of 2026-05, and the gateway only forwards non-None
    values to providers. Determinism for reasoning models is implicit;
    sampled models retain their provider default. ``anonymize=False``
    because the classifier needs to see the actual contract text to
    verify it; ``lq_ai_purpose='playbook_executor'`` so the routing log
    can be filtered for cost calibration.

    Returns an empty dict on transport / parse failure; the caller
    treats that as a low-confidence ``missing`` (the classifier's
    "I have nothing to say" failure mode).
    """
    request = ChatCompletionRequest(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        anonymize=False,
        lq_ai_purpose="playbook_executor",
    )
    try:
        response = await gateway.chat_completion(request)
    except Exception as exc:
        logger.warning(
            "playbook structured-call gateway error: %s",
            exc,
            extra={
                "event": "playbook_structured_call_error",
                "error_type": type(exc).__name__,
            },
        )
        return {}

    try:
        choices = response.choices
        if not choices:
            return {}
        content = choices[0].message.content
    except AttributeError:
        return {}
    if not content:
        return {}

    return _parse_json_object(content)


def _parse_json_object(content: str) -> dict[str, Any]:
    """Lenient JSON parse — trim a leading code fence if present, then ``json.loads``."""
    stripped = content.strip()
    if stripped.startswith("```"):
        # Drop a leading ``` or ```json fence and the trailing ``` line.
        stripped = stripped.split("```", 2)[1]
        if stripped.startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.rstrip("`").strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        logger.warning(
            "playbook structured-call returned malformed JSON: %s",
            exc,
            extra={"event": "playbook_structured_call_malformed_json"},
        )
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _coerce_verdict(raw: Any) -> PositionVerdict:
    """Normalize the model's verdict to the canonical enum or default ``missing``."""
    if isinstance(raw, str) and raw in _VALID_VERDICTS:
        return raw  # type: ignore[return-value]
    return "missing"


def _coerce_confidence(raw: Any) -> str:
    """Normalize confidence to one of the three valid values; default ``low``."""
    if isinstance(raw, str) and raw in _VALID_CONFIDENCES:
        return raw
    return "low"


def _coerce_chunk_indices(raw: Any, *, n_chunks: int) -> list[int]:
    """Filter the model-emitted index list to valid 0-based ints inside the chunk count."""
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for item in raw:
        if isinstance(item, int) and 0 <= item < n_chunks:
            out.append(item)
    return out
