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
from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.clients.gateway import GatewayClient
from app.config import get_settings
from app.errors import GatewayInvalidResponse
from app.models.document import Document
from app.playbooks.easy.issue_identity import issue_identity
from app.playbooks.easy.json_output import unwrap_json_answer
from app.playbooks.easy.source_anchor import (
    anchor_quote,
    complete_connected_item,
    remedy_context,
    repair_context,
)
from app.playbooks.easy.source_facts import source_issue
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest

logger = logging.getLogger(__name__)


class ExtractionResponseError(GatewayInvalidResponse):
    """A missing or truncated answer cannot be accepted as corpus evidence."""


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

    Extraction derives exact offsets from a verified source slice. The
    field stays nullable for callers constructing intermediate candidates.
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
   (confidentiality definition, term, standard of care, limitation
   of liability, indemnification, payment terms, governing law,
   etc.).
2. Is recognizable as a position, not pure boilerplate. Skip
   standard severability / notice / integration clauses UNLESS the
   contract takes an unusual position on them.
3. Is contained in identifiable, contiguous text. Don't emit
   fragmentary spans.

A single section often bundles positions on MORE than one issue —
e.g., an "Obligations of Receiving Party" section that both fixes
the standard of care and restricts use and disclosure. Emit one
entry per issue, each quoting only the sentence(s) or list item(s)
that carry that position; do not collapse distinct positions into
one section-sized entry. Prefer disjoint sentences or list items. If one
complete sentence genuinely governs multiple issues, it may be quoted for
each issue to preserve context; do not reconstruct fragments.
The standard of care is a recurring negotiated position in
confidentiality agreements — extract it as its own "Standard of
Care" entry even when it has no dedicated heading.

Keep definitions separate from exclusions; permitted disclosures separate from
compelled disclosures; recipient liability separate from remedies; agreement
duration separate from confidentiality survival; and governing law separate
from forum/venue. Use specific survival labels for trade secrets and general
confidential information when the source supports separate entries. Preserve
other genuine issues; do not target a fixed number of entries.

Keep technical security safeguards (such as encryption and access controls)
separate from a prohibition on disclosure and from the benchmark for the
standard of care. Use "Security Safeguards" for those measures. When a uniform
survival rule expressly covers trade secrets and other confidential information,
identify both issues using the complete shared sentence(s), without inventing
a separate survival period.

For remedies, retain the immediately adjacent acknowledgement of irreparable
harm and the relief entitlement when they form one passage. Do not quote only
the injunction sentence and thereby omit who acknowledges the harm.

For an NDA, reuse these labels when they fit: "Definition of Confidential
Information", "Exclusions from Confidential Information", "Standard of Care",
"Permitted Use", "Restriction on Disclosure", "Permitted Disclosures",
"Compelled Disclosure", "Recipient Liability", "Term of Agreement",
"Survival of Trade Secrets", "Survival of General Information", "Return or
Destruction", "Archival Copy Exception", "Remedies", "Governing Law",
"Jurisdiction", and "No License". These are label conventions, not a required
set or a limit. Keep a genuinely different or combined issue under its own label.

Quote contiguous source text only. Never join a list header to a non-adjacent
item, stitch items (a) and (c), or insert connecting words. Include enough
adjacent context to preserve the actor, conditions, and negation. If offsets
are uncertain, use null; the application validates quotes and derives offsets.

For each identified clause, emit one entry with:

* ``issue`` — short descriptive noun phrase from common contract
  vocabulary ("Limitation of Liability", "Permitted Disclosures",
  "Standard of Care", "Term of Confidentiality Obligation"). Reuse
  common labels when they fit — clustering downstream depends on
  label consistency.
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

# Verbatim quotes from a short contract plus JSON labels/offsets can exceed
# 3500 tokens. Reasoning is controlled separately, never parsed as the answer.
EASY_EXTRACT_MAX_TOKENS = 8192

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

    Returns an empty list for a document without normalized content or a valid
    empty extraction. Transport failures, malformed response shapes, missing
    content and token-truncated answers raise ``ExtractionResponseError``:
    these cannot be accepted as evidence that a document has no positions.

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
        except ExtractionResponseError:
            raise
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
            raise ExtractionResponseError(
                "Clause extraction request failed; retry generation."
            ) from exc
        merged.extend(clauses)

    # Correct the narrow source/label mismatch observed in the walkthrough.
    # Keep the complete source quotation and coordinates unchanged.
    merged = [
        clause.model_copy(update={"issue": source_issue(clause.issue, clause.clause_text)})
        for clause in merged
    ]

    # Overlapping input spans must not give the same source clause extra votes.
    merged = list(
        {
            (issue_identity(c.issue), c.source_offsets.start, c.source_offsets.end): c
            for c in merged
            if c.source_offsets is not None
        }.values()
    )

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
        reasoning_effort=get_settings().lq_ai_easy_playbook_reasoning_effort or None,
        # `temperature` is omitted: Anthropic Opus 4.x reasoning models
        # rejected the parameter as of 2026-05, and the gateway already
        # only forwards non-None values to providers. Determinism for
        # reasoning models is implicit; sampled models keep their
        # provider default.
        anonymize=False,
        lq_ai_purpose="playbook_easy_extract",
    )

    parsed = await _dispatch_extraction(gateway, request)
    anchored, rejected = _anchor_extracted_clauses(parsed, span_text)
    if rejected:
        logger.warning(
            "easy_extract: repairing unmatched source quotations",
            extra={"event": "easy_extract_source_repair", "unanchored_count": len(rejected)},
        )
        repair_request = request.model_copy(
            update={
                "lq_ai_purpose": "playbook_easy_extract_repair",
                "messages": [
                    *messages,
                    ChatCompletionMessage(
                        role="user",
                        content=(
                            "Re-extract ONLY the issues listed below from DOCUMENT TEXT. The previous "
                            "quotes did not match a contiguous source slice. Copy one contiguous sentence "
                            "or list item for each issue. Do not join a header to a non-adjacent item or "
                            "stitch items (a) and (c). Do not add connecting words. Set source_offsets to null; "
                            "the application locates the quote. Return the same extracted_clauses JSON shape.\n"
                            "When a source_context is supplied, copy its COMPLETE sentence, including "
                            "all conditions and both survival alternatives. Do not split at a comma. "
                            "The same full sentence may be quoted for two distinct issues.\n"
                            + json.dumps(
                                [
                                    {
                                        "issue": c.issue,
                                        "rejected_quote": c.clause_text,
                                        "source_context": repair_context(span_text, c.clause_text),
                                    }
                                    for c in rejected
                                ]
                            )
                        ),
                    ),
                ],
            }
        )
        try:
            repaired = await _dispatch_extraction(gateway, repair_request)
        except ExtractionResponseError:
            raise
        except Exception as exc:
            raise ExtractionResponseError(
                "Source quotation repair failed; retry generation."
            ) from exc
        repaired, still_rejected = _anchor_extracted_clauses(repaired, span_text)
        unresolved: list[ExtractedClause] = []
        for clause in still_rejected:
            complete = complete_connected_item(span_text, clause.clause_text)
            if complete is None:
                unresolved.append(clause)
            else:
                repaired.append(
                    clause.model_copy(
                        update={
                            "clause_text": complete.text,
                            "source_offsets": ExtractedClauseSourceOffsets(
                                start=complete.start, end=complete.end
                            ),
                        }
                    )
                )
        still_rejected = unresolved
        if still_rejected or Counter(issue_identity(c.issue) for c in repaired) != Counter(
            issue_identity(c.issue) for c in rejected
        ):
            raise ExtractionResponseError(
                "Clause extraction could not produce contiguous source quotations after repair. "
                "Review the source documents or retry with a different model."
            )
        anchored.extend(repaired)
    return [_rebase_offsets(c, delta=span_offset) for c in anchored]


def _anchor_extracted_clauses(
    clauses: list[ExtractedClause], source: str
) -> tuple[list[ExtractedClause], list[ExtractedClause]]:
    anchored: list[ExtractedClause] = []
    rejected: list[ExtractedClause] = []
    for clause in clauses:
        match = anchor_quote(source, clause.clause_text)
        if match is None:
            rejected.append(clause)
        else:
            if issue_identity(clause.issue) == "Remedies":
                match = remedy_context(source, match.text) or match
            anchored.append(
                clause.model_copy(
                    update={
                        "clause_text": match.text,
                        "source_offsets": ExtractedClauseSourceOffsets(
                            start=match.start, end=match.end
                        ),
                    }
                )
            )
    return anchored, rejected


async def _dispatch_extraction(
    gateway: GatewayClient, request: ChatCompletionRequest
) -> list[ExtractedClause]:
    response = await gateway.chat_completion(request)
    if response.choices and getattr(response.choices[0], "finish_reason", None) == "length":
        raise ExtractionResponseError(
            "Clause extraction reached the model output limit. "
            "Configure the model's reasoning effort or use a model with sufficient output capacity."
        )
    content = _extract_response_content(response)
    if not content:
        raise ExtractionResponseError(
            "Clause extraction returned no answer content. Check the model's reasoning configuration."
        )

    return _parse_extracted_clauses(content, strict=True)


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


def _parse_extracted_clauses(content: str, *, strict: bool = False) -> list[ExtractedClause]:
    """Parse JSON and validate entries, with explicit failures in production.

    Tolerates a leading ``` ```json ``` fence (some models wrap output).
    A top-level non-object response returns an empty list; a top-level
    object missing ``extracted_clauses`` returns an empty list. Per-entry
    validation failures log a WARNING and skip the entry rather than
    rejecting the whole response — a model that produces 19 valid entries
    plus 1 malformed one is still useful. With ``strict=True`` (the dispatch
    path), invalid JSON, invalid shape or all-invalid entries raise instead of
    silently treating a failed response as a valid empty extraction.
    """

    stripped = unwrap_json_answer(content)

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
        if strict:
            raise ExtractionResponseError(
                "Clause extraction returned invalid JSON; retry generation."
            ) from exc
        return []

    if not isinstance(parsed, dict):
        if strict:
            raise ExtractionResponseError("Clause extraction returned an invalid response shape.")
        return []
    raw_clauses = parsed.get("extracted_clauses")
    if not isinstance(raw_clauses, list):
        if strict:
            raise ExtractionResponseError("Clause extraction returned an invalid response shape.")
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
    if strict and raw_clauses and not out:
        raise ExtractionResponseError("Clause extraction returned no valid clause entries.")
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
