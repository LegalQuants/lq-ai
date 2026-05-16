"""Request-scoped pseudonym assignment — M2-A3.

The mapper sits between the gateway's middleware and the anonymizer
engine: when Presidio (or a custom recognizer) flags an entity span,
the middleware calls :meth:`PseudonymMapper.assign` to get a stable
pseudonym to substitute into the outbound prompt. On the response
path the middleware calls :meth:`PseudonymMapper.reverse` once and
walks the response text replacing pseudonyms with their originals.

Key invariants:

* **Stable per (type, original).** ``assign("PERSON", "John Smith")``
  always returns the same pseudonym within a single mapper instance.
  Same name surfacing twice in one prompt only counts toward one
  counter slot.
* **Per-type counters.** ``PERSON`` and ``ORGANIZATION`` increment
  independently so a transcript that mentions five people and three
  companies reads cleanly: ``PERSON_0001..PERSON_0005`` /
  ``ORGANIZATION_0001..ORGANIZATION_0003``.
* **In-process only.** The mapping is held in plain Python dicts on
  the instance. Never persisted, never logged, never serialized to
  any side channel. A new request gets a new instance; the old one
  is dropped on response.

The format ``{ENTITY_TYPE}_{COUNTER:04d}`` is locked in by the M2
plan's verification step ("returns ``PERSON_0001``"). Five-digit
counter would also have worked; four is the plan's call.
"""

from __future__ import annotations

from collections import defaultdict


class PseudonymMapper:
    """Stable, per-request, in-memory pseudonym assignment.

    Holds two dicts: ``_assignments`` keyed by ``(entity_type,
    original_text)`` → pseudonym for the stability invariant, and
    ``_counters`` keyed by ``entity_type`` → next counter value for
    the per-type independence invariant. Both are populated by
    :meth:`assign` and read by :meth:`reverse`.
    """

    __slots__ = ("_assignments", "_counters")

    def __init__(self) -> None:
        self._assignments: dict[tuple[str, str], str] = {}
        self._counters: defaultdict[str, int] = defaultdict(int)

    def assign(self, entity_type: str, original: str) -> str:
        """Return the stable pseudonym for ``(entity_type, original)``.

        First call for a new ``(type, original)`` pair allocates the
        next counter for ``entity_type``; subsequent calls return the
        previously allocated pseudonym byte-for-byte.

        Args:
            entity_type: Canonical entity-type label, e.g. ``"PERSON"``,
                ``"ORGANIZATION"``, ``"PHONE_NUMBER"``. Presidio's
                vocabulary is what M2-B3 wires in; custom recognizers
                (M2-B2) extend it.
            original: The literal text of the entity as Presidio saw
                it in the source prompt.

        Returns:
            The pseudonym, formatted ``{entity_type}_{NNNN}`` with a
            zero-padded four-digit counter (``PERSON_0001``,
            ``PERSON_0042``, etc.). Counter resets across instances
            but not across calls within an instance.
        """

        key = (entity_type, original)
        existing = self._assignments.get(key)
        if existing is not None:
            return existing

        self._counters[entity_type] += 1
        pseudonym = f"{entity_type}_{self._counters[entity_type]:04d}"
        self._assignments[key] = pseudonym
        return pseudonym

    def reverse(self) -> dict[str, str]:
        """Return a fresh ``pseudonym → original`` mapping for rehydration.

        The middleware calls this once per response to rebuild the
        post-substitution text. We return a copy rather than the live
        internal dict so callers can mutate the result (or accidentally
        drop it on the floor) without corrupting the mapper.

        Empty mapper → empty dict; never raises.
        """

        return {pseudonym: original for (_, original), pseudonym in self._assignments.items()}
