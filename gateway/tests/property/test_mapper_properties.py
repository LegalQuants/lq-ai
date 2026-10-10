"""PseudonymMapper property tests — DE-230.

Pins the mapper's three documented invariants (stability, per-type
counter independence, reverse-table fidelity) over generated
assignment sequences instead of hand-picked examples.
"""

from __future__ import annotations

import re

from hypothesis import given, strategies as st

from app.anonymization.mapper import PseudonymMapper

from .strategies import ENTITY_TYPES, entity_original

# A sequence of (entity_type, original) assignment calls, duplicates
# encouraged (duplicates are exactly what the stability invariant is
# about).
assignments = st.lists(
    st.tuples(st.sampled_from(ENTITY_TYPES), entity_original),
    max_size=40,
)

_PSEUDONYM_FORMAT = re.compile(r"^[A-Z][A-Z_]*_\d{4,}$")


@given(assignments)
def test_assign_is_stable_and_format_locked(calls: list[tuple[str, str]]) -> None:
    """Same (type, original) → same pseudonym; format is {TYPE}_{NNNN}."""

    mapper = PseudonymMapper()
    seen: dict[tuple[str, str], str] = {}
    for etype, original in calls:
        pseudonym = mapper.assign(etype, original)
        assert _PSEUDONYM_FORMAT.match(pseudonym), pseudonym
        assert pseudonym.startswith(f"{etype}_")
        if (etype, original) in seen:
            assert pseudonym == seen[(etype, original)]
        seen[(etype, original)] = pseudonym


@given(assignments)
def test_distinct_pairs_get_distinct_pseudonyms(calls: list[tuple[str, str]]) -> None:
    """Injectivity: two different (type, original) pairs never share a pseudonym.

    Without this, rehydration would silently swap one party's name for
    another's — the worst possible failure for legal work product.
    """

    mapper = PseudonymMapper()
    by_pseudonym: dict[str, tuple[str, str]] = {}
    for etype, original in calls:
        pseudonym = mapper.assign(etype, original)
        assert by_pseudonym.setdefault(pseudonym, (etype, original)) == (etype, original)


@given(assignments)
def test_reverse_maps_every_pseudonym_to_its_original(calls: list[tuple[str, str]]) -> None:
    """reverse() is the exact inverse of the assignments made."""

    mapper = PseudonymMapper()
    expected: dict[str, str] = {}
    for etype, original in calls:
        expected[mapper.assign(etype, original)] = original
    assert mapper.reverse() == expected


@given(assignments)
def test_per_type_counters_are_independent_and_dense(calls: list[tuple[str, str]]) -> None:
    """Counters count distinct originals per type, starting at 1, no gaps."""

    mapper = PseudonymMapper()
    for etype, original in calls:
        mapper.assign(etype, original)
    distinct_per_type: dict[str, set[str]] = {}
    for etype, original in calls:
        distinct_per_type.setdefault(etype, set()).add(original)
    counts = mapper.entity_counts()
    assert counts == {etype: len(originals) for etype, originals in distinct_per_type.items()}


@given(assignments, assignments)
def test_mapper_instances_are_isolated(
    calls_a: list[tuple[str, str]], calls_b: list[tuple[str, str]]
) -> None:
    """Two mappers share no state: same call sequence → same pseudonyms."""

    mapper_a = PseudonymMapper()
    mapper_b = PseudonymMapper()
    for etype, original in calls_a:
        mapper_a.assign(etype, original)
    # Interleave: b sees only calls_b regardless of a's history.
    results_b = [mapper_b.assign(etype, original) for etype, original in calls_b]
    fresh = PseudonymMapper()
    assert results_b == [fresh.assign(etype, original) for etype, original in calls_b]
