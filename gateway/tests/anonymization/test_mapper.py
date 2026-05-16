"""PseudonymMapper smoke tests — M2-A3 scaffold.

The mapper is a request-scoped, in-process dictionary that assigns a
stable pseudonym to every entity it sees and exposes the reverse
mapping for rehydration on the response path. The middleware wires
the mapper into the gateway lifecycle in M2-B3; M2-A3 only ships
the data structure + its invariants.

Verifies the four contracts from the M2 plan §M2-A3:

* Same original → same pseudonym across calls (stable assignment).
* Different originals → different pseudonyms.
* Counter increments per entity type independently.
* ``reverse()`` returns the pseudonym → original mapping for the
  rehydration step.

The mapper holds nothing persistent: a new instance starts empty,
and there is no read path that escapes its memory. The middleware
allocates one mapper per request and drops it at response time.
"""

from __future__ import annotations

import pytest

from app.anonymization.mapper import PseudonymMapper


@pytest.mark.unit
def test_same_original_returns_same_pseudonym() -> None:
    """Calling ``assign`` twice with the same (type, original) is stable."""

    m = PseudonymMapper()
    first = m.assign("PERSON", "John Smith")
    second = m.assign("PERSON", "John Smith")

    assert first == second


@pytest.mark.unit
def test_first_assignment_uses_one_indexed_zero_padded_counter() -> None:
    """First assigned PERSON → ``PERSON_0001`` per the plan's verification check."""

    m = PseudonymMapper()
    assert m.assign("PERSON", "John Smith") == "PERSON_0001"


@pytest.mark.unit
def test_counter_increments_for_distinct_originals_same_type() -> None:
    """Second distinct original gets a fresh counter under the same type."""

    m = PseudonymMapper()
    first = m.assign("PERSON", "John Smith")
    second = m.assign("PERSON", "Jane Doe")

    assert first == "PERSON_0001"
    assert second == "PERSON_0002"


@pytest.mark.unit
def test_counter_is_per_entity_type() -> None:
    """PERSON and ORGANIZATION each have their own counter starting at 1."""

    m = PseudonymMapper()
    person = m.assign("PERSON", "John Smith")
    org = m.assign("ORGANIZATION", "Acme Corp.")

    assert person == "PERSON_0001"
    assert org == "ORGANIZATION_0001"


@pytest.mark.unit
def test_reverse_returns_pseudonym_to_original_mapping() -> None:
    """``reverse()`` is what the response-path middleware consumes."""

    m = PseudonymMapper()
    m.assign("PERSON", "John Smith")
    m.assign("PERSON", "Jane Doe")
    m.assign("ORGANIZATION", "Acme Corp.")

    rev = m.reverse()

    assert rev == {
        "PERSON_0001": "John Smith",
        "PERSON_0002": "Jane Doe",
        "ORGANIZATION_0001": "Acme Corp.",
    }


@pytest.mark.unit
def test_new_instance_starts_empty() -> None:
    """Mapper state is per-instance — no shared / persistent state."""

    first = PseudonymMapper()
    first.assign("PERSON", "John Smith")

    second = PseudonymMapper()
    rev = second.reverse()

    assert rev == {}
    # Sanity: second instance also assigns starting at 0001.
    assert second.assign("PERSON", "Someone Else") == "PERSON_0001"


@pytest.mark.unit
def test_reverse_returned_dict_is_a_copy() -> None:
    """Mutating the reverse-mapping return value must not affect the mapper."""

    m = PseudonymMapper()
    m.assign("PERSON", "John Smith")

    rev = m.reverse()
    rev["PERSON_9999"] = "tampered"

    # Original assignment is preserved.
    assert m.assign("PERSON", "John Smith") == "PERSON_0001"
    # And re-fetching reverse() shows no taint.
    assert m.reverse() == {"PERSON_0001": "John Smith"}
