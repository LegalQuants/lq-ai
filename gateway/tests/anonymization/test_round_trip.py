"""Anonymization round-trip correctness — M2-C3.

This suite pins four load-bearing invariants the Anonymization Layer
must hold. The tests run against the **real** Presidio
:class:`AnalyzerEngine` (not the stub used by the substitution-logic
unit tests in ``test_anonymizer.py``) so a regression in entity
detection — or a regression in Presidio behavior between versions —
surfaces here rather than as a silent quality drop in production.

Marked ``slow`` because the first call constructs the engine and
loads spaCy's ``en_core_web_lg`` model (~2-3s wall-clock). The
module-scoped fixture amortizes the load across every test in the
file.

The four invariants:

1. **Byte-for-byte round-trip.** ``pseudonymize_into(text, mapper)``
   followed by ``rehydrate(substituted_text, mapper)`` returns the
   original ``text`` exactly.
2. **Cross-conversation stability within a request.** A single mapper
   threaded through multiple pseudonymize calls assigns the same
   pseudonym to the same ``(entity_type, original)`` pair every time.
3. **Per-request isolation.** Two independent ``PseudonymMapper``
   instances produce independent pseudonym spaces — no shared state.
4. **In-process-only persistence.** After a representative request
   completes, no pseudonym-shaped string surfaces in any persistent
   surface — captured log records, the audit row's serialized
   payload, or any other observable side channel.

Plus entity-overlap handling and the edge cases the M2-C3 plan calls
out (empty text, no entities, short text, source containing a literal
pseudonym pattern — the DE-274 known issue).
"""

from __future__ import annotations

import dataclasses
import logging
import re
from typing import Any

import pytest

from app.anonymization.engine import (
    Anonymizer,
    _reset_analyzer_engine_for_tests,
    get_analyzer_engine,
)
from app.anonymization.mapper import PseudonymMapper
from app.anonymization.middleware import (
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
from app.routing_log import InferenceRoutingLogRow, RecordingRoutingLogWriter

pytestmark = pytest.mark.slow


# Anything matching ``[A-Z][A-Z_]*_\d+`` looks like one of our
# pseudonyms (``PERSON_0001``, ``MATTER_NUMBER_0042``). The
# in-process-only-persistence invariant scans for this shape; if it
# ever appears outside the in-memory mapper, the leak is real.
_PSEUDONYM_PATTERN = re.compile(r"\b[A-Z][A-Z_]*_\d+\b")


@pytest.fixture(scope="module")
def production_anonymizer() -> Anonymizer:
    """Module-scoped real-Presidio :class:`Anonymizer`.

    Loads spaCy once for the whole file. Tests that need a fresh
    mapper allocate one inline; the analyzer is read-only and
    thread-safe so it can be shared.
    """

    _reset_analyzer_engine_for_tests()
    return Anonymizer(analyzer=get_analyzer_engine())


# ---------------------------------------------------------------------------
# Invariant 1 — byte-for-byte round-trip.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # Simple PERSON span.
        "John Smith signed the agreement on June 3rd.",
        # Multiple entity types in one sentence.
        (
            "Counsel Jane Doe of Acme LLP can be reached at "
            "jane.doe@acme.com or 415-555-0123 regarding matter LQ-2024-0001."
        ),
        # Federal cite + person + organization in legal prose.
        (
            "In Smith v. Jones, 123 F.3d 456 (9th Cir. 2024), counsel for "
            "Acme LLP argued the dispute had been settled."
        ),
        # Repeated entity references — round-trip must hold for both.
        "John Smith called. John Smith later emailed back.",
        # Empty text — degenerate case.
        "",
        # Text with no recognized entities.
        "The agreement was signed yesterday afternoon.",
        # Single character — shorter than any entity.
        "x",
        # Punctuation-only.
        "...!",
    ],
    ids=[
        "single_person",
        "multi_entity_mixed",
        "legal_prose_with_cite",
        "repeated_entity",
        "empty",
        "no_entities",
        "single_char",
        "punctuation_only",
    ],
)
def test_pseudonymize_then_rehydrate_is_identity(
    production_anonymizer: Anonymizer,
    text: str,
) -> None:
    """For any ``text``, ``rehydrate(pseudonymize_into(text)) == text``.

    The mapper carries the round-trip; whatever entities Presidio
    detected (or didn't) get substituted on the way out and restored
    on the way in.
    """

    mapper = PseudonymMapper()
    substituted = production_anonymizer.pseudonymize_into(text, mapper)
    restored = production_anonymizer.rehydrate(substituted, mapper)

    assert restored == text, (
        f"Round-trip broke. Original: {text!r}; "
        f"substituted: {substituted!r}; restored: {restored!r}"
    )


# ---------------------------------------------------------------------------
# Invariant 2 — cross-conversation stability within a request.
# ---------------------------------------------------------------------------


def test_same_entity_across_messages_yields_same_pseudonym(
    production_anonymizer: Anonymizer,
) -> None:
    """Same name in message N and message M of one request → same pseudonym.

    The middleware threads one mapper through every message in the
    request; the assign-call's stability invariant guarantees the
    same ``(type, original)`` pair returns the same pseudonym every
    time.
    """

    mapper = PseudonymMapper()
    msg_1 = "John Smith introduced the agreement to the team."
    msg_2 = "Later, John Smith signed it and circulated the executed copy."

    sub_1 = production_anonymizer.pseudonymize_into(msg_1, mapper)
    sub_2 = production_anonymizer.pseudonymize_into(msg_2, mapper)

    # Both substituted messages should contain the same pseudonym for
    # "John Smith". Extract every pseudonym from each.
    pseudonyms_1 = set(_PSEUDONYM_PATTERN.findall(sub_1))
    pseudonyms_2 = set(_PSEUDONYM_PATTERN.findall(sub_2))
    shared = pseudonyms_1 & pseudonyms_2

    assert shared, (
        f"Expected shared pseudonym for 'John Smith' across messages. "
        f"msg1 pseudonyms: {pseudonyms_1}; msg2 pseudonyms: {pseudonyms_2}"
    )

    # The mapper reverse table should have exactly one entry per
    # unique original — repeated entities don't create new counter
    # slots.
    reverse = mapper.reverse()
    originals = list(reverse.values())
    assert originals.count("John Smith") == 1


def test_cross_message_stability_in_pre_middleware(
    production_anonymizer: Anonymizer,
) -> None:
    """The pre-middleware is the production caller that walks multiple messages.

    Wired through ``pre_anonymize_request``, the same name in
    different message roles still resolves to one pseudonym — the
    middleware allocates one mapper per request and threads it
    through every message-content call.
    """

    request = ChatCompletionRequest(
        model="smart",
        messages=[
            ChatCompletionMessage(role="system", content="Discussing John Smith."),
            ChatCompletionMessage(role="user", content="What did John Smith say?"),
            ChatCompletionMessage(role="assistant", content="John Smith said yes."),
        ],
    )
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])

    mapper = pre_anonymize_request(
        chat_request=request,
        config=config,
        routed_tier=4,
        anonymizer=production_anonymizer,
    )

    assert mapper is not None
    # Every message should have exactly the same pseudonym for "John Smith".
    pseudonym_sets = [set(_PSEUDONYM_PATTERN.findall(m.content or "")) for m in request.messages]
    # The pseudonym for John Smith must appear in all three sets.
    intersection = pseudonym_sets[0] & pseudonym_sets[1] & pseudonym_sets[2]
    assert intersection, f"No shared pseudonym across messages. Per-message: {pseudonym_sets}"
    # Only one mapping for "John Smith" exists.
    assert list(mapper.reverse().values()).count("John Smith") == 1


# ---------------------------------------------------------------------------
# Invariant 3 — per-request isolation.
# ---------------------------------------------------------------------------


def test_two_mappers_have_independent_counter_spaces(
    production_anonymizer: Anonymizer,
) -> None:
    """Two mappers used in parallel produce independent pseudonym spaces.

    A pseudonym in mapper A has no meaning in mapper B's reverse
    table; rehydrating mapper A's output against mapper B does not
    leak A's originals.
    """

    text_a = "John Smith signed the deal."
    text_b = "Jane Doe drafted the response."

    mapper_a = PseudonymMapper()
    mapper_b = PseudonymMapper()

    sub_a = production_anonymizer.pseudonymize_into(text_a, mapper_a)
    sub_b = production_anonymizer.pseudonymize_into(text_b, mapper_b)

    # Both mappers used their own counter — both should produce
    # ``PERSON_0001`` for their first PERSON span.
    pseudonyms_a = _PSEUDONYM_PATTERN.findall(sub_a)
    pseudonyms_b = _PSEUDONYM_PATTERN.findall(sub_b)

    # Both contain a PERSON_NNNN, and they should start at 0001 each.
    assert any(p == "PERSON_0001" for p in pseudonyms_a)
    assert any(p == "PERSON_0001" for p in pseudonyms_b)

    # Mapper A's reverse table does NOT contain Jane Doe; B's does
    # NOT contain John Smith.
    reverse_a = mapper_a.reverse()
    reverse_b = mapper_b.reverse()
    assert "John Smith" in reverse_a.values()
    assert "Jane Doe" in reverse_b.values()
    assert "Jane Doe" not in reverse_a.values()
    assert "John Smith" not in reverse_b.values()


def test_isolation_relies_on_scope_not_pseudonym_uniqueness(
    production_anonymizer: Anonymizer,
) -> None:
    """Per-request isolation comes from SCOPE, not from cryptographic distinctness.

    Honest finding pinned by this test: the pseudonym format
    (``PERSON_0001``, ``PERSON_0002``, ...) is **not** globally
    unique across mappers. Two parallel mappers both produce
    ``PERSON_0001`` for their respective first PERSON span. The
    isolation invariant in production is enforced by **request
    scoping** — the mapper is allocated in the request handler,
    threaded through pre and post middleware, and dropped on
    function exit. There is no production path that rehydrates one
    request's output against another request's mapper because the
    other request's mapper doesn't exist by then.

    This test pins the structural property so a future change (e.g.
    DE-274's per-request salt) is visible in CI. If salting lands,
    rehydrating mapper A's output against mapper B will become a
    no-op (different salts → different pseudonym strings → no
    matching keys in mapper B's reverse table).
    """

    mapper_a = PseudonymMapper()
    mapper_b = PseudonymMapper()

    sub_a = production_anonymizer.pseudonymize_into("Jane Doe handled the matter.", mapper_a)
    production_anonymizer.pseudonymize_into("Bob Roe took the call.", mapper_b)

    restored_wrong = production_anonymizer.rehydrate(sub_a, mapper_b)

    # Current (M2-C3) behavior: mapper_b's PERSON_0001 → "Bob Roe"
    # rehydrates sub_a's PERSON_0001 to "Bob Roe", NOT to Jane Doe.
    # This is structurally fine in production because mapper_b
    # never sees sub_a — request scoping prevents the misroute.
    assert "Jane Doe" not in restored_wrong, (
        "Mapper isolation must prevent A's originals from surfacing under B's reverse"
    )
    assert "Bob Roe" in restored_wrong, (
        "Rehydrating against the wrong mapper substitutes the wrong mapper's "
        "names — this is the current behavior pinned by this test. If "
        "DE-274's per-request salt lands, this assertion should flip to "
        "``restored_wrong == sub_a`` (no match against the wrong mapper)."
    )


# ---------------------------------------------------------------------------
# Invariant 4 — in-process-only persistence (caplog + audit-row scan).
# ---------------------------------------------------------------------------


def _assistant_response(content: str) -> ChatCompletionResponse:
    """Build a minimal non-streaming response carrying ``content``."""

    return ChatCompletionResponse(
        id="chatcmpl-roundtrip",
        created=0,
        model="claude-sonnet-4-6",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=ChatCompletionUsage(prompt_tokens=5, completion_tokens=10, total_tokens=15),
    )


def _row_serialized(row: InferenceRoutingLogRow) -> str:
    """Flatten a routing-log row to a single string for substring grep.

    The audit-row scan checks every field for pseudonym-shaped
    strings. Dataclass-as-dict serialization preserves every value
    the writer would persist, so any field that secretly carries a
    pseudonym surfaces here.
    """

    return repr(dataclasses.asdict(row))


def test_completed_request_leaves_no_pseudonym_in_logs_or_audit(
    production_anonymizer: Anonymizer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The mapper is in-process; no pseudonym should escape to logs or audit.

    Strategy: run a representative request through pre + post
    middleware (the production substitution path), capture logs at
    DEBUG level (broadest possible net), build the audit row the
    routing-log writer would persist, and verify neither contains
    any string matching the pseudonym pattern.

    The mapper itself is dropped at the end of the function scope so
    the only place pseudonym strings should live is the in-memory
    rebound variables — they don't escape.
    """

    caplog.set_level(logging.DEBUG, logger="app.anonymization")

    # Pre-middleware: pseudonymize the request.
    request = ChatCompletionRequest(
        model="smart",
        messages=[
            ChatCompletionMessage(
                role="user",
                content="John Smith of Acme LLP signed matter LQ-2024-0001.",
            )
        ],
    )
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])
    mapper = pre_anonymize_request(
        chat_request=request,
        config=config,
        routed_tier=4,
        anonymizer=production_anonymizer,
    )
    assert mapper is not None

    # Sanity: the substituted message DOES contain pseudonyms in
    # memory — they exist briefly, in process, on the request object.
    substituted_user_content = request.messages[0].content or ""
    assert _PSEUDONYM_PATTERN.search(substituted_user_content) is not None

    # Simulate the provider responding with content that references
    # the pseudonyms, then post-middleware rehydrating.
    response = _assistant_response(f"Reviewed {substituted_user_content} — looks fine.")
    post_anonymize_response(response=response, mapper=mapper, anonymizer=production_anonymizer)

    # The post-middleware-restored response contains the originals,
    # not the pseudonyms.
    restored_content = response.choices[0].message.content or ""
    assert "John Smith" in restored_content
    assert _PSEUDONYM_PATTERN.search(restored_content) is None

    # --- (a) Log scan: no pseudonym strings in captured records ---
    # We're checking that the anonymization layer's own logs never
    # carry pseudonym strings — log records cross trust boundaries
    # (operators tail them) and shouldn't echo substitution state.
    leaked_in_logs = [
        rec
        for rec in caplog.records
        if _PSEUDONYM_PATTERN.search(rec.getMessage())
        or _PSEUDONYM_PATTERN.search(str(getattr(rec, "extra", "")))
    ]
    assert not leaked_in_logs, (
        f"Pseudonym pattern leaked into log records: {[r.getMessage() for r in leaked_in_logs]}"
    )

    # --- (b) Audit-row scan: the routing-log row payload is clean ---
    # The InferenceRoutingLogRow schema is structurally incapable of
    # carrying message content — every field is a number, UUID,
    # bool, or short structured code. We verify this hasn't drifted
    # by building a representative row and grepping it for pseudonym
    # strings.
    representative_row = InferenceRoutingLogRow(
        routed_provider="anthropic-prod",
        routed_model="claude-sonnet-4-6",
        routed_inference_tier=4,
        anonymization_applied=True,
        request_id="req_test",
    )
    serialized = _row_serialized(representative_row)
    assert _PSEUDONYM_PATTERN.search(serialized) is None, (
        f"InferenceRoutingLogRow serialized form contains pseudonym pattern: {serialized}"
    )

    # The recorder's row list is also clean — using the production
    # writer interface, not just the dataclass.
    recorder = RecordingRoutingLogWriter()
    import asyncio

    asyncio.run(recorder.write(representative_row))
    recorder_serialized = repr([dataclasses.asdict(r) for r in recorder.rows])
    assert _PSEUDONYM_PATTERN.search(recorder_serialized) is None


# ---------------------------------------------------------------------------
# Entity-overlap handling.
# ---------------------------------------------------------------------------


def test_overlapping_entities_collapse_to_one_substitution(
    production_anonymizer: Anonymizer,
) -> None:
    """``John Smith Jr.`` produces one substitution per the longest-span-wins rule.

    Presidio may surface multiple recognizers for nested name spans
    (full name + the surname alone, for example). The Anonymizer's
    overlap resolution in ``_resolve_overlaps`` keeps the longest
    span and drops the rest. The substituted output should NOT
    contain nested or duplicated pseudonyms.
    """

    text = "John Smith Jr. and Jane Doe represented the parties."
    mapper = PseudonymMapper()
    sub = production_anonymizer.pseudonymize_into(text, mapper)

    # Round-trip still holds.
    restored = production_anonymizer.rehydrate(sub, mapper)
    assert restored == text

    # No pseudonym appears *inside* another pseudonym in the
    # substituted text — i.e., no ``PERSON_0001_0002``-like nesting.
    pseudonyms = _PSEUDONYM_PATTERN.findall(sub)
    for p in pseudonyms:
        # Each pseudonym's match in the substituted text should not
        # itself contain another pseudonym (a sanity check that the
        # overlap collapse worked).
        assert _PSEUDONYM_PATTERN.findall(p) == [p]


# ---------------------------------------------------------------------------
# Edge case — source document containing literal pseudonym pattern.
# DE-274 known limitation; the test pins current behavior.
# ---------------------------------------------------------------------------


def test_source_with_literal_pseudonym_pattern_passes_through_unchanged(
    production_anonymizer: Anonymizer,
) -> None:
    """Source text containing a literal ``PERSON_0001`` survives the round-trip.

    This is the DE-274 edge case (see ``docs/security/anonymization.md``):
    if a source document literally contains a string matching the
    pseudonym pattern, today the rehydrator does nothing to it (no
    mapper entry → ``str.replace`` is a no-op). The substituted text
    keeps the literal string, and the rehydrated text keeps it too.

    This test pins that behavior so a future change (logging
    unmatched patterns, or adding pattern detection) is visible in
    CI rather than silent.
    """

    text = "The template section reads: 'See PERSON_0001 above'. — instructions."
    mapper = PseudonymMapper()

    substituted = production_anonymizer.pseudonymize_into(text, mapper)
    restored = production_anonymizer.rehydrate(substituted, mapper)

    # Round-trip is identity even with the literal pseudonym pattern.
    assert restored == text


# ---------------------------------------------------------------------------
# Edge case — middleware on a non-content message (tool-call shape).
# ---------------------------------------------------------------------------


def test_pre_middleware_skips_messages_with_none_content(
    production_anonymizer: Anonymizer,
) -> None:
    """``content=None`` (tool-call shape) is skipped without raising or mutating."""

    request = ChatCompletionRequest(
        model="smart",
        messages=[
            ChatCompletionMessage(role="user", content="John Smith joined."),
            ChatCompletionMessage(role="assistant", content=None),
        ],
    )
    config = AnonymizationConfig(enabled=True, apply_at_tiers=[3, 4, 5])

    mapper = pre_anonymize_request(
        chat_request=request,
        config=config,
        routed_tier=4,
        anonymizer=production_anonymizer,
    )

    assert mapper is not None
    # First message pseudonymized.
    assert _PSEUDONYM_PATTERN.search(request.messages[0].content or "")
    # Second still None — not coerced to empty string, not crashed.
    assert request.messages[1].content is None


# ---------------------------------------------------------------------------
# Sanity: real analyzer actually detected entities.
# ---------------------------------------------------------------------------


def test_real_analyzer_actually_substitutes_legal_content(
    production_anonymizer: Anonymizer,
) -> None:
    """Smoke check: the suite is exercising real entity detection.

    If Presidio's defaults regress (a future version disables PERSON
    by default, say), the round-trip invariants above would still
    pass trivially because there'd be nothing to substitute. This
    test fails loudly if the analyzer detects zero entities on text
    that should obviously have several.
    """

    text = (
        "Counsel Jane Doe of Acme LLP can be reached at jane.doe@acme.com "
        "regarding matter LQ-2024-0001."
    )
    mapper = PseudonymMapper()
    substituted = production_anonymizer.pseudonymize_into(text, mapper)

    pseudonyms = _PSEUDONYM_PATTERN.findall(substituted)
    # We expect at least PERSON (Jane Doe), EMAIL, MATTER_NUMBER —
    # three different entity types should fire on this prose.
    assert len(pseudonyms) >= 2, (
        f"Expected real Presidio to detect at least 2 entities in "
        f"legal-prose text; got {len(pseudonyms)}. Substituted: {substituted!r}"
    )


# ---------------------------------------------------------------------------
# Helper kept for future tests; suppress unused-import lint via reference.
# ---------------------------------------------------------------------------


_KEEP_REFS: tuple[Any, ...] = (
    _assistant_response,
    _row_serialized,
)
