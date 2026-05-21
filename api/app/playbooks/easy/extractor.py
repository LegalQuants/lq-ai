"""Per-document clause extraction — M3-A6 Phase 3.

The Easy Playbook generation pipeline calls
:func:`extract_clauses_from_document` once per uploaded corpus
document. Each call returns the list of negotiated positions found
in that document; the downstream clustering step (Phase 4) groups
the union across the corpus.

The actual LLM prompt mirrors :doc:`skills/playbook-easy-extract/SKILL.md`
— the SKILL.md is the human-readable source of truth and what surfaces
in the operator's skill library UI; this module embeds a Python copy
of the same prompt so the gateway dispatch can run without a runtime
SKILL.md fetch (matches the M3-A2 executor's pattern in
:mod:`app.playbooks.nodes`). When the SKILL.md is updated the Python
constant must be updated in step; the relationship is documented in
the SKILL.md.

Chunking
--------

Most contracts fit in one LLM call (a 20-page MSA is ~50K chars ≈
12K tokens, well within modern models' context windows). For longer
documents the extractor batches the document into overlapping spans
and merges the results. The clustering step is tolerant of
near-duplicates from overlapping spans — they collapse into a single
cluster — so we don't need a cross-span dedup step here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.clients.gateway import GatewayClient
from app.models.document import Document
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------


class ExtractedClauseSourceOffsets(BaseModel):
    """Half-open character interval ``[start, end)`` into the source document.

    Matches the M2 Citation Engine's offset semantics: ``start`` is
    inclusive, ``end`` is exclusive, both 0-based, both indices into
    :attr:`app.models.document.Document.normalized_content`.
    """

    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(ge=0)


class ExtractedClause(BaseModel):
    """One position extracted from one source document.

    Issue labels are short, descriptive noun phrases ("Limitation of
    Liability", "Definition of Confidential Information") — the
    clustering step depends on label consistency across the corpus.

    Clause text is verbatim — the clustering step embeds these
    strings for variant detection.

    Source offsets are best-effort. If the model could not identify
    exact offsets, the field is ``None`` and the UI's "open in
    document" affordance is omitted for that clause.
    """

    model_config = ConfigDict(extra="forbid")

    issue: str
    clause_text: str
    source_offsets: ExtractedClauseSourceOffsets | None = None


# ---------------------------------------------------------------------------
# Prompt (mirror of skills/playbook-easy-extract/SKILL.md)
# ---------------------------------------------------------------------------


EASY_EXTRACT_SYSTEM_PROMPT = """\
You are the Playbook Easy Extract skill — an internal step in the
Easy Playbook generation pipeline. You read a single contract and
emit a structured list of the negotiated positions it takes.

Identify every clause that:

1. Takes a substantive position on a recurring contract issue
   (confidentiality definition, term, limitation of liability,
   indemnification, payment terms, governing law, etc.).
2. Is recognizable as a position, not pure boilerplate. Skip
   standard severability / notice / integration clauses UNLESS the
   contract takes an unusual position on them.
3. Is contained in identifiable, contiguous text. Don't emit
   overlapping or fragmentary spans.

For each identified clause, emit one entry with:

* ``issue`` — short descriptive noun phrase from common contract
  vocabulary ("Limitation of Liability", "Permitted Disclosures",
  "Term of Confidentiality Obligation"). Reuse common labels when
  they fit — clustering downstream depends on label consistency.
* ``clause_text`` — verbatim quote from the contract. Preserve
  original wording, casing, and punctuation. Do not paraphrase.
* ``source_offsets`` — half-open character interval
  ``{"start": int, "end": int}`` into the supplied DOCUMENT TEXT
  (0-based; ``end`` exclusive). Use ``null`` if you cannot identify
  exact offsets.

Output STRICTLY VALID JSON in this exact shape:

  {"extracted_clauses": [
      {"issue": "<label>", "clause_text": "<verbatim>",
       "source_offsets": {"start": <int>, "end": <int>}},
      ...
    ]
  }

Constraints:

* Output is INTERMEDIATE — the pipeline clusters it downstream and a
  user-attorney reviews the assembled playbook. Do NOT opine on
  clause quality, favorability, or unusualness.
* Do NOT invent clauses. Every entry must correspond to text that
  actually appears in the document.
* Do NOT fix or rewrite clauses. Quote verbatim even if drafting is
  messy.
* A typical contract yields 5-20 entries. An empty array is correct
  if the document is not a contract.

If the document is not in English, extract as best-effort and prefix
the issue label with ``[non-English source]``.
"""


# Character budget per LLM call. 50,000 characters is roughly 12K
# tokens — comfortable for any modern judge model and leaves headroom
# for the system prompt + output. Documents longer than this are
# batched into overlapping spans.
DEFAULT_CHARACTER_BUDGET = 50_000

# Overlap between consecutive spans when a document exceeds the budget.
# Prevents clauses that straddle a span boundary from being missed.
SPAN_OVERLAP_CHARACTERS = 1_500

# Max output tokens. 20 clauses at ~120 tokens each = 2400; 3500 keeps
# headroom for verbose clauses without letting the model meander.
EASY_EXTRACT_MAX_TOKENS = 3500

# Default judge-model alias. Matches the M3-A2 executor's default;
# the alias resolves to the deployment-configured "smart" model
# (typically Sonnet-class on the default tier envelope).
DEFAULT_JUDGE_MODEL = "smart"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract_clauses_from_document(
    *,
    document: Document,
    gateway: GatewayClient,
    contract_type: str | None = None,
    judge_model: str = DEFAULT_JUDGE_MODEL,
    character_budget: int = DEFAULT_CHARACTER_BUDGET,
    span_overlap_characters: int = SPAN_OVERLAP_CHARACTERS,
) -> list[ExtractedClause]:
    """Extract negotiated positions from one contract.

    Reads :attr:`Document.normalized_content` (the M2 canonical text),
    issues one LLM call per character-budgeted span (with overlap),
    parses the structured-JSON response, and returns the merged list
    of :class:`ExtractedClause` instances.

    Returns an empty list if the document has no normalized content
    or if every LLM call returned malformed output. Failure-of-the-
    LLM is non-fatal for the corpus-level pipeline — one bad
    extraction reduces clustering signal but doesn't kill the
    generation.

    Args:
        document: the source document. ``normalized_content`` is
            consumed; other fields are unused (the caller is
            responsible for visibility / RBAC scoping before
            invoking the extractor).
        gateway: inference gateway client.
        contract_type: optional contract family hint
            ("NDA", "MSA-SaaS", "DPA") passed to the model so it
            recognizes family-appropriate issues. None falls back to
            general extraction.
        judge_model: gateway model alias for the LLM call.
        character_budget: max characters per LLM call. Documents
            longer than this are split into overlapping spans.
    """

    text = document.normalized_content or ""
    if not text.strip():
        logger.info(
            "easy_extract: empty document; returning []",
            extra={
                "event": "easy_extract_empty",
                "document_id": str(document.id),
            },
        )
        return []

    spans = _build_spans(text, budget=character_budget, overlap=span_overlap_characters)
    logger.info(
        "easy_extract: starting extraction",
        extra={
            "event": "easy_extract_start",
            "document_id": str(document.id),
            "characters": len(text),
            "span_count": len(spans),
            "contract_type": contract_type,
        },
    )

    merged: list[ExtractedClause] = []
    for index, (offset, span_text) in enumerate(spans):
        try:
            clauses = await _extract_one_span(
                gateway=gateway,
                model=judge_model,
                span_text=span_text,
                span_offset=offset,
                contract_type=contract_type,
            )
        except Exception as exc:
            logger.warning(
                "easy_extract: span extraction failed",
                extra={
                    "event": "easy_extract_span_failed",
                    "document_id": str(document.id),
                    "span_index": index,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            continue
        merged.extend(clauses)

    logger.info(
        "easy_extract: extraction complete",
        extra={
            "event": "easy_extract_complete",
            "document_id": str(document.id),
            "clause_count": len(merged),
        },
    )
    return merged


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_spans(
    text: str,
    *,
    budget: int,
    overlap: int,
) -> list[tuple[int, str]]:
    """Split ``text`` into overlapping spans bounded by ``budget`` characters.

    Returns a list of ``(start_offset, span_text)`` pairs. ``start_offset``
    is the 0-based character position of the span within ``text``; the
    caller uses it to rebase per-span source offsets emitted by the LLM
    back to document-global coordinates.

    For short documents (``len(text) <= budget``) returns a single
    ``(0, text)`` entry. For longer documents, splits with ``overlap``
    characters of repetition between adjacent spans so clauses that
    straddle a boundary land cleanly in at least one span.
    """

    if len(text) <= budget:
        return [(0, text)]

    spans: list[tuple[int, str]] = []
    stride = max(budget - overlap, 1)
    start = 0
    while start < len(text):
        end = min(start + budget, len(text))
        spans.append((start, text[start:end]))
        if end >= len(text):
            break
        start += stride
    return spans


async def _extract_one_span(
    *,
    gateway: GatewayClient,
    model: str,
    span_text: str,
    span_offset: int,
    contract_type: str | None,
) -> list[ExtractedClause]:
    """One LLM call extracting clauses from a single text span.

    Rebases per-span offsets back to document-global coordinates
    before returning, so the caller's merge step receives a flat list
    in document-global units regardless of how many spans the
    document was split into.
    """

    user_lines: list[str] = []
    if contract_type:
        user_lines.append(f"CONTRACT TYPE HINT: {contract_type}")
        user_lines.append("")
    user_lines.append("DOCUMENT TEXT:")
    user_lines.append(span_text)
    user_content = "\n".join(user_lines)

    messages = [
        ChatCompletionMessage(role="system", content=EASY_EXTRACT_SYSTEM_PROMPT),
        ChatCompletionMessage(role="user", content=user_content),
    ]

    request = ChatCompletionRequest(
        model=model,
        messages=messages,
        max_tokens=EASY_EXTRACT_MAX_TOKENS,
        # `temperature` is omitted: Anthropic Opus 4.x reasoning models
        # rejected the parameter as of 2026-05, and the gateway already
        # only forwards non-None values to providers. Determinism for
        # reasoning models is implicit; sampled models keep their
        # provider default.
        anonymize=False,
        lq_ai_purpose="playbook_easy_extract",
    )

    response = await gateway.chat_completion(request)
    content = _extract_response_content(response)
    if not content:
        return []

    parsed = _parse_extracted_clauses(content)
    if span_offset > 0:
        parsed = [_rebase_offsets(clause, delta=span_offset) for clause in parsed]
    return parsed


def _extract_response_content(response: Any) -> str | None:
    """Pull the text content out of a ChatCompletion response."""

    try:
        choices = response.choices
    except AttributeError:
        return None
    if not choices:
        return None
    try:
        content = choices[0].message.content
    except AttributeError:
        return None
    if not isinstance(content, str) or not content.strip():
        return None
    return content


def _parse_extracted_clauses(content: str) -> list[ExtractedClause]:
    """Lenient JSON parse + Pydantic validation; drop malformed entries.

    Tolerates a leading ``` ```json ``` fence (some models wrap output).
    A top-level non-object response returns an empty list; a top-level
    object missing ``extracted_clauses`` returns an empty list. Per-entry
    validation failures log a WARNING and skip the entry rather than
    rejecting the whole response — a model that produces 19 valid entries
    plus 1 malformed one is still useful.
    """

    stripped = content.strip()
    if stripped.startswith("```"):
        # Drop a leading ``` or ```json fence and the trailing fence.
        parts = stripped.split("```", 2)
        if len(parts) >= 2:
            stripped = parts[1]
        if stripped.startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.rstrip("`").strip()

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        logger.warning(
            "easy_extract: malformed JSON in LLM response",
            extra={
                "event": "easy_extract_malformed_json",
                "error": str(exc),
            },
        )
        return []

    if not isinstance(parsed, dict):
        return []
    raw_clauses = parsed.get("extracted_clauses")
    if not isinstance(raw_clauses, list):
        return []

    out: list[ExtractedClause] = []
    for index, raw in enumerate(raw_clauses):
        if not isinstance(raw, dict):
            continue
        try:
            out.append(ExtractedClause.model_validate(raw))
        except Exception as exc:
            logger.warning(
                "easy_extract: clause validation failed; skipping",
                extra={
                    "event": "easy_extract_clause_invalid",
                    "clause_index": index,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            continue
    return out


def _rebase_offsets(clause: ExtractedClause, *, delta: int) -> ExtractedClause:
    """Shift per-span source offsets by ``delta`` to document-global coordinates."""

    if clause.source_offsets is None:
        return clause
    return ExtractedClause(
        issue=clause.issue,
        clause_text=clause.clause_text,
        source_offsets=ExtractedClauseSourceOffsets(
            start=clause.source_offsets.start + delta,
            end=clause.source_offsets.end + delta,
        ),
    )
