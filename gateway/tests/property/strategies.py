"""Shared Hypothesis strategies for the gateway property suite — DE-230.

The anonymization strategies generate *entity-laden documents*: a text
plus the exact entity spans a (stubbed) analyzer will report for it.
Driving :meth:`Anonymizer.pseudonymize_into` with a span-list stub
exercises the substitution / overlap-resolution / rehydration machinery
at property scale without paying the spaCy model load per example, and
— unlike the real NER — makes the "which spans were recognized"
half of the contract deterministic.

DE-274 constraint: source text that already contains a literal
pseudonym-shaped string (``PERSON_0001``-like) is a *known, documented*
rehydration ambiguity. The strategies therefore filter assembled
documents through :data:`PSEUDONYM_SHAPE` so the properties pin the
supported contract instead of rediscovering the known issue. The
excluded shape is itself covered by an explicit example test in
``tests/anonymization/test_round_trip.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from hypothesis import assume, strategies as st

# The entity-type vocabulary the production analyzer can emit (enabled
# Presidio defaults + the custom legal recognizers). Pseudonyms are
# ``{TYPE}_{NNNN}``; the StreamingRehydrator's hold-pattern
# (``[A-Z][A-Z_]*(?:_\d*)?$``) is designed around exactly this shape,
# so realistic types are load-bearing for the streaming properties.
ENTITY_TYPES: tuple[str, ...] = (
    "PERSON",
    "ORGANIZATION",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_BANK_NUMBER",
    "LOCATION",
    "CASE_NUMBER",
    "MATTER_NUMBER",
)

# Anything matching this could collide with a mapper-issued pseudonym
# (DE-274). Documents containing it are filtered out (see module doc).
PSEUDONYM_SHAPE: re.Pattern[str] = re.compile(r"[A-Z][A-Z_]*_\d")


@dataclass(frozen=True)
class Span:
    """The subset of Presidio's ``RecognizerResult`` the engine reads."""

    entity_type: str
    start: int
    end: int
    score: float = 0.85


class SpanListAnalyzer:
    """Analyzer stub returning a fixed span list for any text.

    Satisfies :class:`app.anonymization.engine._AnalyzerProtocol`; the
    span list is precomputed by :func:`entity_documents` to match the
    generated text.
    """

    def __init__(self, spans: list[Span]) -> None:
        self._spans = spans

    def analyze(self, *, text: str, language: str = "en") -> list[Span]:
        return list(self._spans)


# Filler between entities: arbitrary unicode (including whitespace and
# combining characters) so offsets/splices are exercised against the
# messy end of the input space. Surrogates are excluded because the
# transport layer (JSON) can't carry them anyway.
filler_text = st.text(
    alphabet=st.characters(exclude_categories=("Cs",)),
    max_size=40,
)

# Entity originals: non-empty. Newlines and exotic unicode are allowed —
# the analyzer decides what an entity is; the substitution machinery
# must round-trip whatever it was handed.
entity_original = st.text(
    alphabet=st.characters(exclude_categories=("Cs",)),
    min_size=1,
    max_size=30,
)

# Greek-only originals for the no-entity-survives property: the filler
# strategy below excludes Greek, so every Greek character in a document
# is inside a recognized entity span — making "no Greek survives
# anonymization" an exact statement of "no recognized entity text
# survives anonymization".
GREEK = "αβγδεζηθικλμνξο"
greek_entity_original = st.text(alphabet=GREEK, min_size=1, max_size=20)
non_greek_filler = st.text(
    alphabet=st.characters(exclude_categories=("Cs",), exclude_characters=GREEK),
    max_size=40,
)


@st.composite
def entity_documents(
    draw: st.DrawFn,
    *,
    originals: st.SearchStrategy[str] = entity_original,
    filler: st.SearchStrategy[str] = filler_text,
    max_entities: int = 8,
) -> tuple[str, list[Span]]:
    """Generate ``(text, spans)`` — filler interleaved with entity spans.

    Spans are non-overlapping by construction and listed in reading
    order; the pseudonym-shape filter (DE-274, module doc) is applied
    to the assembled text.
    """

    n = draw(st.integers(min_value=0, max_value=max_entities))
    text = ""
    spans: list[Span] = []
    for _ in range(n):
        text += draw(filler)
        etype = draw(st.sampled_from(ENTITY_TYPES))
        original = draw(originals)
        start = len(text)
        text += original
        spans.append(Span(entity_type=etype, start=start, end=len(text)))
    text += draw(filler)
    # DE-274: assembled text (junctions included) must not carry a
    # literal pseudonym shape.
    assume(not PSEUDONYM_SHAPE.search(text))
    return text, spans


def chunk_at(text: str, cuts: list[int]) -> list[str]:
    """Split ``text`` at the (sorted, clamped) ``cuts`` positions."""

    positions = sorted({min(max(c, 0), len(text)) for c in cuts})
    out: list[str] = []
    prev = 0
    for pos in [*positions, len(text)]:
        out.append(text[prev:pos])
        prev = pos
    return out
