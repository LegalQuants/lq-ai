"""Anonymization Layer edge cases — M2-D4 sweep.

Per docs/M2-IMPLEMENTATION-PLAN.md §M2-D4, this file pins regression
tests for the anonymization-side edge cases the M2 plan calls out:

* **Long entity names (>200 chars)** — the pseudonymizer handles
  arbitrarily long spans without crashing; the resulting pseudonym
  is the standard ``{TYPE}_{NNNN}`` format regardless of source length.
* **Multi-line entities** — spans that cross line boundaries
  (``\\n`` characters inside an entity match) substitute correctly.
* **Pseudonym collision with literal source text** — already covered
  by ``test_round_trip.py::test_source_text_with_literal_pseudonym_survives_round_trip``
  (DE-274 known limitation); this file adds a focused middleware-level
  pin so the round-trip and middleware perspectives stay coherent.
* **Entities in cited spans (post-rehydration)** — a model response
  that contains a pseudonym AS PART OF a cited quote (e.g.,
  ``"PERSON_0001 signed the agreement" (Source: [1])``) rehydrates
  the pseudonym inside the quote on the response path. The cite-
  extraction step on the api/ side then sees the rehydrated original.

The foreign-language edge case is documented as a known limitation
in ``docs/security/anonymization.md``; no test (Presidio's English-only
configuration is the binding constraint and is out of scope for v1).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.anonymization.engine import Anonymizer
from app.anonymization.mapper import PseudonymMapper
from app.anonymization.middleware import (
    StreamingRehydrator,
    post_anonymize_response,
    pre_anonymize_request,
)
from app.config import AnonymizationConfig
from app.providers.openai_schema import (
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
)

# ---------------------------------------------------------------------------
# Stub analyzer — same shape as test_middleware.py / test_anonymizer.py.
# Duplicated here rather than imported (see test_middleware.py comment).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Span:
    entity_type: str
    start: int
    end: int
    score: float = 0.85


class _StubAnalyzer:
    def __init__(self, by_text: dict[str, list[_Span]]) -> None:
        self._by_text = by_text

    def analyze(self, *, text: str, language: str = "en", **_kwargs: object) -> list[_Span]:
        return list(self._by_text.get(text, []))


def _make_request(*, messages: list[ChatCompletionMessage]) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="smart",
        messages=messages,
        anonymize=True,
        lq_ai_privileged=False,
    )


def _make_response(content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-edge",
        created=0,
        model="claude-sonnet-4-6",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=ChatCompletionUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    )


# ---------------------------------------------------------------------------
# Long entity names (>200 chars)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pre_anonymize_long_entity_name_substitutes_without_crash() -> None:
    """Entities >200 chars pseudonymize using the standard format.

    Pseudonym format is ``{TYPE}_{NNNN}`` regardless of source-span
    length — the substitution shrinks the wire payload rather than
    expanding it for long entities. The mapper holds the full original
    (whatever its length) so the rehydrator can restore it byte-for-byte
    on the response path. No truncation today; the binding limit is
    Presidio's per-span analysis cost.
    """

    long_name = "Very Long Organization Name " * 10 + "Inc."  # ~290 chars
    content = f"Discussing {long_name} liability."
    span_start = content.index(long_name)
    span_end = span_start + len(long_name)

    req = _make_request(messages=[ChatCompletionMessage(role="user", content=content)])
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer({content: [_Span("ORGANIZATION", span_start, span_end)]})

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is not None
    assert req.messages[0].content == "Discussing ORGANIZATION_0001 liability."
    # Mapper holds the full original — rehydration restores it byte-for-byte.
    reverse_map = mapper.reverse()
    assert reverse_map["ORGANIZATION_0001"] == long_name
    assert len(reverse_map["ORGANIZATION_0001"]) > 200


@pytest.mark.unit
def test_post_anonymize_rehydrates_long_entity_byte_for_byte() -> None:
    """Round-trip preserves long-entity originals exactly."""

    long_name = "Very Long Organization Name " * 10 + "Inc."  # ~290 chars
    mapper = PseudonymMapper()
    mapper.assign("ORGANIZATION", long_name)  # allocates ORGANIZATION_0001

    response = _make_response(content="ORGANIZATION_0001 is the counterparty.")
    analyzer = _StubAnalyzer({})  # not used by post_anonymize_response

    post_anonymize_response(
        response=response,
        mapper=mapper,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert response.choices[0].message.content == f"{long_name} is the counterparty."


# ---------------------------------------------------------------------------
# Multi-line entities (span crosses \n)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pre_anonymize_multiline_entity_substitutes_across_newline() -> None:
    """A span carrying ``\\n`` substitutes correctly.

    Address blocks frequently include line breaks (``"Acme Corp\\n123
    Main St\\nNew York, NY"``); a presidio-detected address entity may
    span the whole block. The substitution replaces the entire range —
    including the newlines — with a single pseudonym, then the response
    rehydrator restores the original multi-line string.
    """

    multiline_address = "Acme Corp\n123 Main St\nNew York, NY 10001"
    content = f"Contract counterparty:\n{multiline_address}\n\nSignatory: John Doe"
    span_start = content.index(multiline_address)
    span_end = span_start + len(multiline_address)

    req = _make_request(messages=[ChatCompletionMessage(role="user", content=content)])
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    analyzer = _StubAnalyzer({content: [_Span("LOCATION", span_start, span_end)]})

    mapper = pre_anonymize_request(
        chat_request=req,
        config=config,
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=analyzer),
    )

    assert mapper is not None
    assert req.messages[0].content == (
        "Contract counterparty:\nLOCATION_0001\n\nSignatory: John Doe"
    )
    assert mapper.reverse()["LOCATION_0001"] == multiline_address


@pytest.mark.unit
def test_post_anonymize_rehydrates_multiline_entity_with_newlines_preserved() -> None:
    """Rehydration of a multi-line pseudonym restores the embedded newlines."""

    multiline_address = "Acme Corp\n123 Main St\nNew York, NY 10001"
    mapper = PseudonymMapper()
    mapper.assign("LOCATION", multiline_address)

    response = _make_response(content="The counterparty at LOCATION_0001 signed the agreement.")
    post_anonymize_response(
        response=response,
        mapper=mapper,
        anonymizer=Anonymizer(analyzer=_StubAnalyzer({})),
    )

    assert response.choices[0].message.content == (
        f"The counterparty at {multiline_address} signed the agreement."
    )


# ---------------------------------------------------------------------------
# Pseudonym-collision middleware perspective (DE-274 cross-ref)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_post_anonymize_literal_pseudonym_in_response_passes_through() -> None:
    """A response containing a literal pseudonym pattern that the mapper
    has no entry for passes through unchanged.

    Cross-references DE-274 (per-request salt). The rehydrator's
    substitution is ``str.replace(pseudonym, original)`` keyed by the
    mapper's contents. A literal ``"PERSON_0001"`` in the source
    document — surfaced into the response via a model citation — that
    happens to also be a pseudonym format string is a no-op when the
    mapper has no matching entry. The literal preserves on the way
    out (no false rehydration). When the mapper DOES have an entry
    for ``PERSON_0001`` (because a real PERSON was detected in the
    request), the response's literal gets rewritten to the original
    — the cross-mapper collision DE-274 documents.

    This test pins the no-mapper case; the with-mapper case is
    pinned by the round-trip suite at
    ``test_round_trip.py::test_source_text_with_literal_pseudonym_survives_round_trip``.
    """

    mapper = PseudonymMapper()  # empty — no entries

    response = _make_response(content="The contract template uses PERSON_0001 as a placeholder.")
    post_anonymize_response(
        response=response,
        mapper=mapper,
        anonymizer=Anonymizer(analyzer=_StubAnalyzer({})),
    )

    # No-op: the literal "PERSON_0001" passes through unchanged.
    assert response.choices[0].message.content == (
        "The contract template uses PERSON_0001 as a placeholder."
    )


# ---------------------------------------------------------------------------
# Entities in cited spans (post-rehydration walks citation text too)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_post_anonymize_rehydrates_pseudonyms_inside_quoted_citation_span() -> None:
    """Rehydration scans the entire response content — including text
    inside ``"..." (Source: [N])`` markers.

    Per M2-D2 the api/ marks the retrieval-context system message
    with ``lq_ai_skip_anonymization=True`` so source quotes reach the
    model un-pseudonymized; in normal operation the model's citations
    quote real source text directly and no rehydration inside the
    quote is needed. But in edge scenarios (e.g., the model paraphrases
    pseudonymized chat-turn content into something that *looks like*
    a cited quote), the rehydrator still walks the whole response
    string — pseudonyms anywhere in the content get restored. This
    test pins that contract.
    """

    mapper = PseudonymMapper()
    mapper.assign("PERSON", "John Smith")  # allocates PERSON_0001

    response = _make_response(
        content='The agreement says "PERSON_0001 shall not compete" (Source: [1]).'
    )
    post_anonymize_response(
        response=response,
        mapper=mapper,
        anonymizer=Anonymizer(analyzer=_StubAnalyzer({})),
    )

    # Pseudonym inside the quote is restored along with anywhere else
    # in the response content.
    assert response.choices[0].message.content == (
        'The agreement says "John Smith shall not compete" (Source: [1]).'
    )


# ---------------------------------------------------------------------------
# Streaming rehydration of multi-line / long entities
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_streaming_rehydrator_handles_long_entity_across_chunks() -> None:
    """StreamingRehydrator restores a long-entity pseudonym that arrives
    across several SSE chunks.

    The pseudonym format is ``{TYPE}_{NNNN}`` (short — fewer than 30
    chars typically), so the partial-pattern tail buffer easily
    contains it. But the rehydrated ORIGINAL may be arbitrarily long;
    this test confirms the rehydrator emits the full original even
    when the source pseudonym arrived split.
    """

    long_name = "Very Long Organization Name " * 10 + "Inc."
    mapper = PseudonymMapper()
    mapper.assign("ORGANIZATION", long_name)

    r = StreamingRehydrator(mapper=mapper, anonymizer=Anonymizer(analyzer=_StubAnalyzer({})))

    # Split "ORGANIZATION_0001 is here." across three chunks
    pieces = ["ORGAN", "IZATION_0001 ", "is here."]
    out = "".join(r.process(p) for p in pieces) + r.flush()

    assert out == f"{long_name} is here."
