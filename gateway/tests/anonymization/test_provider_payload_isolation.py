"""DE-240 — the rehydration mapper never reaches provider-bound payloads.

The adversarial-extraction premise (tests/pii/extraction/ at repo root)
is only sound if the provider *cannot* know the pseudonym → original
mapping. Two structural guarantees make that true, and this module
pins both deterministically (stub analyzer — no spaCy, not slow):

1. After ``pre_anonymize_request`` runs, the serialized request (the
   object every provider adapter builds its outbound payload from)
   contains pseudonyms only — no original entity text, in message
   content or in nested skill inputs.
2. The request object carries no reference to the mapper or its
   reverse table at all — the mapping lives exclusively in the
   in-process ``PseudonymMapper`` the middleware returns to the
   caller, which is never serialized (see also the persistence
   invariant in ``test_round_trip.py`` and the adapter-level checks in
   ``test_inference_anonymization.py``).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.anonymization.engine import Anonymizer
from app.anonymization.mapper import PseudonymMapper
from app.anonymization.middleware import pre_anonymize_request
from app.config import AnonymizationConfig
from app.providers.openai_schema import ChatCompletionMessage, ChatCompletionRequest

_ORIGINALS = ("John Smith", "Acme LLP")


@dataclass(slots=True)
class _Span:
    entity_type: str
    start: int
    end: int
    score: float = 0.9


class _StubAnalyzer:
    """Deterministic analyzer: flags every occurrence of the known originals."""

    def analyze(self, *, text: str, language: str = "en") -> list[_Span]:
        spans: list[_Span] = []
        for value, entity_type in ((_ORIGINALS[0], "PERSON"), (_ORIGINALS[1], "ORGANIZATION")):
            start = 0
            while (found := text.find(value, start)) != -1:
                spans.append(_Span(entity_type=entity_type, start=found, end=found + len(value)))
                start = found + len(value)
        return spans


def _pseudonymized_request() -> tuple[ChatCompletionRequest, PseudonymMapper]:
    request = ChatCompletionRequest(
        model="smart",
        messages=[
            ChatCompletionMessage(role="system", content="Context: John Smith retained Acme LLP."),
            ChatCompletionMessage(role="user", content="Summarize John Smith's obligations."),
        ],
        lq_ai_skill_inputs={
            "nda-review": {"party": "John Smith", "nested": {"firm": ["Acme LLP"]}}
        },
    )
    mapper = pre_anonymize_request(
        chat_request=request,
        config=AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5]),
        routed_tier=4,
        anonymizer=Anonymizer(analyzer=_StubAnalyzer()),
    )
    assert mapper is not None
    return request, mapper


def test_serialized_request_contains_pseudonyms_and_no_originals() -> None:
    """The provider-bound serialization carries zero original entity text."""

    request, mapper = _pseudonymized_request()
    serialized = request.model_dump_json()

    for original in _ORIGINALS:
        assert original not in serialized, f"original {original!r} leaked into provider payload"
    # Sanity: substitution actually happened (guards against a vacuous pass).
    assert "PERSON_0001" in serialized
    assert "ORGANIZATION_0001" in serialized

    # The mapper knows the originals — in process only.
    assert set(mapper.reverse().values()) == set(_ORIGINALS)


def test_skill_inputs_are_pseudonymized_in_serialized_request() -> None:
    """Nested skill-input strings are substituted too, not just message content."""

    request, _ = _pseudonymized_request()
    assert request.lq_ai_skill_inputs is not None
    inputs = request.lq_ai_skill_inputs["nda-review"]
    assert inputs["party"] == "PERSON_0001"
    assert inputs["nested"]["firm"] == ["ORGANIZATION_0001"]


def test_request_object_holds_no_reference_to_the_mapper() -> None:
    """No field of the request (or its dump) can carry the reverse mapping."""

    request, mapper = _pseudonymized_request()

    # No attribute of the pydantic model is (or contains) the mapper.
    dumped = request.model_dump()

    def _walk(value: object) -> None:
        assert not isinstance(value, PseudonymMapper)
        assert not isinstance(value, dict) or all(
            not isinstance(v, PseudonymMapper) for v in value.values()
        )
        if isinstance(value, dict):
            for v in value.values():
                _walk(v)
        elif isinstance(value, list):
            for v in value:
                _walk(v)

    _walk(dumped)

    # And the serialized form never mentions the reverse table's contents.
    serialized = request.model_dump_json()
    for original in mapper.reverse().values():
        assert original not in serialized
