"""Tests for ``app.playbooks.easy.extractor`` — M3-A6 Phase 3.

Per the M3-A6 prep doc, the bar for this stage is **structural
correctness**: the extractor returns valid :class:`ExtractedClause`
instances with the expected shape. Content (whether the LLM picked
the "right" clauses) is the user-attorney's downstream evaluation
during the wizard's Step 3 inline editor, not this test's job.

The tests stub :meth:`GatewayClient.chat_completion` with a queued
JSON-string sequence — same pattern as :mod:`tests.playbooks.test_executor`.
No live LLM, no live gateway.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.playbooks.easy.extractor import (
    DEFAULT_CHARACTER_BUDGET,
    SPAN_OVERLAP_CHARACTERS,
    ExtractedClause,
    _build_spans,
    extract_clauses_from_document,
)

# ---------------------------------------------------------------------------
# Stub gateway — mirrors tests/playbooks/test_executor.py::_StubGateway
# ---------------------------------------------------------------------------


@dataclass
class _StubMessage:
    content: str


@dataclass
class _StubChoice:
    message: _StubMessage


@dataclass
class _StubResponse:
    choices: list[_StubChoice]


@dataclass
class _StubGateway:
    """Returns a queued list of LLM responses, one per call.

    Each entry in ``payloads`` is either:
      * a ``dict`` — JSON-serialized as the LLM response content;
      * a ``str`` — returned verbatim (use for malformed-JSON tests);
      * an ``Exception`` instance — raised on the call (transport-failure tests).
    """

    payloads: list[Any] = field(default_factory=list)
    calls_received: list[Any] = field(default_factory=list)

    async def chat_completion(self, request: Any) -> _StubResponse:
        self.calls_received.append(request)
        if not self.payloads:
            return _StubResponse(choices=[_StubChoice(message=_StubMessage(content=""))])
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, str):
            return _StubResponse(choices=[_StubChoice(message=_StubMessage(content=payload))])
        return _StubResponse(
            choices=[_StubChoice(message=_StubMessage(content=json.dumps(payload)))]
        )


@dataclass
class _StubDocument:
    """Minimal stand-in for ``app.models.document.Document``.

    The extractor only reads ``id`` (for log fields) and
    ``normalized_content`` — no ORM behavior required.
    """

    id: uuid.UUID
    normalized_content: str


def _make_doc(text: str) -> _StubDocument:
    return _StubDocument(id=uuid.uuid4(), normalized_content=text)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_empty_document_returns_empty_list() -> None:
    gateway = _StubGateway()
    clauses = await extract_clauses_from_document(
        document=_make_doc(""),
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert clauses == []
    # No LLM call was made.
    assert gateway.calls_received == []


@pytest.mark.unit
async def test_whitespace_only_document_returns_empty_list() -> None:
    gateway = _StubGateway()
    clauses = await extract_clauses_from_document(
        document=_make_doc("   \n\n  \t  "),
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert clauses == []
    assert gateway.calls_received == []


@pytest.mark.unit
async def test_short_document_single_call_returns_parsed_clauses() -> None:
    text = "1. Confidentiality term is three (3) years.\n2. Governing law is Delaware."
    gateway = _StubGateway(
        payloads=[
            {
                "extracted_clauses": [
                    {
                        "issue": "Term of Confidentiality Obligation",
                        "clause_text": "Confidentiality term is three (3) years.",
                        "source_offsets": {"start": 3, "end": 44},
                    },
                    {
                        "issue": "Governing Law",
                        "clause_text": "Governing law is Delaware.",
                        "source_offsets": {"start": 47, "end": 73},
                    },
                ]
            }
        ]
    )
    clauses = await extract_clauses_from_document(
        document=_make_doc(text),
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert len(clauses) == 2
    assert clauses[0].issue == "Term of Confidentiality Obligation"
    assert clauses[0].clause_text == "Confidentiality term is three (3) years."
    assert clauses[0].source_offsets is not None
    assert clauses[0].source_offsets.start == 3
    assert clauses[0].source_offsets.end == 44
    assert clauses[1].issue == "Governing Law"
    # One LLM call.
    assert len(gateway.calls_received) == 1


@pytest.mark.unit
async def test_contract_type_hint_passed_through_to_user_message() -> None:
    gateway = _StubGateway(payloads=[{"extracted_clauses": []}])
    await extract_clauses_from_document(
        document=_make_doc("Some contract text."),
        gateway=gateway,  # type: ignore[arg-type]
        contract_type="NDA",
    )
    request = gateway.calls_received[0]
    user_msg = next(m for m in request.messages if m.role == "user")
    assert "CONTRACT TYPE HINT: NDA" in user_msg.content
    assert "Some contract text." in user_msg.content


@pytest.mark.unit
async def test_no_contract_type_hint_when_omitted() -> None:
    gateway = _StubGateway(payloads=[{"extracted_clauses": []}])
    await extract_clauses_from_document(
        document=_make_doc("Some contract text."),
        gateway=gateway,  # type: ignore[arg-type]
    )
    user_msg = next(m for m in gateway.calls_received[0].messages if m.role == "user")
    assert "CONTRACT TYPE HINT" not in user_msg.content


@pytest.mark.unit
async def test_request_carries_lq_ai_purpose_for_audit_routing() -> None:
    gateway = _StubGateway(payloads=[{"extracted_clauses": []}])
    await extract_clauses_from_document(
        document=_make_doc("text"),
        gateway=gateway,  # type: ignore[arg-type]
    )
    request = gateway.calls_received[0]
    assert request.lq_ai_purpose == "playbook_easy_extract"
    assert request.anonymize is False
    # `temperature` is intentionally omitted — Opus 4.x reasoning models
    # rejected it as of 2026-05; the gateway only forwards non-None.
    assert request.temperature is None


# ---------------------------------------------------------------------------
# Malformed responses (non-fatal)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_malformed_json_response_returns_empty_list() -> None:
    gateway = _StubGateway(payloads=["not valid json {[}"])
    clauses = await extract_clauses_from_document(
        document=_make_doc("Some text"),
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert clauses == []


@pytest.mark.unit
async def test_top_level_array_response_returns_empty_list() -> None:
    """A response that's a JSON array (not an object) is treated as malformed."""
    gateway = _StubGateway(payloads=['[{"issue": "x", "clause_text": "y"}]'])
    clauses = await extract_clauses_from_document(
        document=_make_doc("Some text"),
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert clauses == []


@pytest.mark.unit
async def test_missing_extracted_clauses_key_returns_empty_list() -> None:
    gateway = _StubGateway(payloads=[{"clauses": [{"issue": "x"}]}])
    clauses = await extract_clauses_from_document(
        document=_make_doc("Some text"),
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert clauses == []


@pytest.mark.unit
async def test_per_entry_validation_drops_only_the_bad_entry() -> None:
    """One valid + one invalid clause: keep the valid one, drop the bad one."""
    gateway = _StubGateway(
        payloads=[
            {
                "extracted_clauses": [
                    {
                        "issue": "Governing Law",
                        "clause_text": "Delaware law applies.",
                        "source_offsets": {"start": 0, "end": 21},
                    },
                    # Missing required fields (no issue, no clause_text).
                    {"source_offsets": {"start": 0, "end": 5}},
                ]
            }
        ]
    )
    clauses = await extract_clauses_from_document(
        document=_make_doc("Delaware law applies."),
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert len(clauses) == 1
    assert clauses[0].issue == "Governing Law"


@pytest.mark.unit
async def test_clause_without_source_offsets_is_accepted() -> None:
    gateway = _StubGateway(
        payloads=[
            {
                "extracted_clauses": [
                    {"issue": "Governing Law", "clause_text": "Delaware law applies."}
                ]
            }
        ]
    )
    clauses = await extract_clauses_from_document(
        document=_make_doc("Delaware law applies."),
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert len(clauses) == 1
    assert clauses[0].source_offsets is None


@pytest.mark.unit
async def test_gateway_exception_is_swallowed_returns_empty_list() -> None:
    """A transport failure on the only span returns ``[]``; doesn't crash the corpus run."""

    gateway = _StubGateway(payloads=[ConnectionError("gateway down")])
    clauses = await extract_clauses_from_document(
        document=_make_doc("Some contract text."),
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert clauses == []


@pytest.mark.unit
async def test_markdown_fenced_json_is_unwrapped() -> None:
    """Some models wrap structured output in a ```json fence; the extractor tolerates it."""

    fenced = (
        '```json\n{"extracted_clauses": [{"issue": "Term", "clause_text": "Three years."}]}\n```'
    )
    gateway = _StubGateway(payloads=[fenced])
    clauses = await extract_clauses_from_document(
        document=_make_doc("Three years."),
        gateway=gateway,  # type: ignore[arg-type]
    )
    assert len(clauses) == 1
    assert clauses[0].issue == "Term"


# ---------------------------------------------------------------------------
# Long documents → multi-span dispatch with offset rebasing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_spans_short_document_single_span() -> None:
    spans = _build_spans("hello world", budget=100, overlap=10)
    assert spans == [(0, "hello world")]


@pytest.mark.unit
def test_build_spans_long_document_overlapping_spans() -> None:
    # 250-char text, budget=100, overlap=20 → stride 80 → starts at 0, 80, 160 (last span 160..250).
    text = "x" * 250
    spans = _build_spans(text, budget=100, overlap=20)
    assert [start for start, _ in spans] == [0, 80, 160]
    assert all(len(span_text) <= 100 for _, span_text in spans)
    # Last span goes to end of text.
    last_start, last_text = spans[-1]
    assert last_start + len(last_text) == 250


@pytest.mark.unit
async def test_long_document_multiple_calls_offsets_rebased() -> None:
    """Each span gets its own call; per-span offsets are rebased to document-global."""

    # Force exactly two spans with a small budget. Override the
    # module-default overlap (1500) which would otherwise dominate
    # our 100-char test budget.
    budget = 100
    overlap = 20
    text = "x" * 150  # spans: (0, "x"*100) and (80, "x"*70)

    gateway = _StubGateway(
        payloads=[
            # Span 0 (offset 0): emits one clause with per-span offsets (0, 50).
            {
                "extracted_clauses": [
                    {
                        "issue": "Issue A",
                        "clause_text": "Clause A",
                        "source_offsets": {"start": 0, "end": 50},
                    }
                ]
            },
            # Span 1 (offset 80): emits one clause with per-span offsets (10, 40)
            # which should be rebased to (90, 120) in document coordinates.
            {
                "extracted_clauses": [
                    {
                        "issue": "Issue B",
                        "clause_text": "Clause B",
                        "source_offsets": {"start": 10, "end": 40},
                    }
                ]
            },
        ]
    )

    clauses = await extract_clauses_from_document(
        document=_make_doc(text),
        gateway=gateway,  # type: ignore[arg-type]
        character_budget=budget,
        span_overlap_characters=overlap,
    )
    assert len(gateway.calls_received) == 2
    assert len(clauses) == 2
    # First clause: span 0, offsets unchanged.
    assert clauses[0].issue == "Issue A"
    assert clauses[0].source_offsets is not None
    assert clauses[0].source_offsets.start == 0
    assert clauses[0].source_offsets.end == 50
    # Second clause: span 1 (offset 80), per-span (10, 40) → (90, 120).
    assert clauses[1].issue == "Issue B"
    assert clauses[1].source_offsets is not None
    assert clauses[1].source_offsets.start == 90
    assert clauses[1].source_offsets.end == 120


@pytest.mark.unit
async def test_one_failed_span_does_not_kill_other_spans() -> None:
    """A transport failure on span 0 doesn't block span 1 from contributing."""

    text = "x" * 150
    gateway = _StubGateway(
        payloads=[
            ConnectionError("transient gateway timeout"),
            {
                "extracted_clauses": [
                    {
                        "issue": "Recovered",
                        "clause_text": "still got this one",
                    }
                ]
            },
        ]
    )
    clauses = await extract_clauses_from_document(
        document=_make_doc(text),
        gateway=gateway,  # type: ignore[arg-type]
        character_budget=100,
        span_overlap_characters=20,
    )
    assert len(clauses) == 1
    assert clauses[0].issue == "Recovered"


# ---------------------------------------------------------------------------
# Sanity: chunking constants are coherent
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_default_character_budget_leaves_room_for_overlap() -> None:
    """Overlap must be strictly less than budget — otherwise stride would be non-positive."""
    assert SPAN_OVERLAP_CHARACTERS < DEFAULT_CHARACTER_BUDGET


@pytest.mark.unit
def test_extracted_clause_pydantic_rejects_extra_fields() -> None:
    """``ExtractedClause`` model_config sets ``extra='forbid'`` — keeps the wire shape tight."""
    with pytest.raises(Exception):
        ExtractedClause.model_validate(
            {
                "issue": "x",
                "clause_text": "y",
                "bogus_field": "z",
            }
        )
