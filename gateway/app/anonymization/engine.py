"""Anonymizer façade — top-level engine wiring (M2-A3 scaffold).

The :class:`Anonymizer` is the entry point the gateway middleware
(M2-B3) will use to pseudonymize an outbound prompt and rehydrate the
returning response. M2-A3 ships the class shape and a stub
:class:`PseudonymMapper`-only path; the heavy Presidio
:class:`~presidio_analyzer.AnalyzerEngine` + spaCy NLP wiring lands
in M2-B3 once the custom legal recognizers (M2-B2) and the spaCy
model image bake (also M2-B2) are in place.

The interface is intentionally final from the start so the middleware
in M2-B3 can target it without re-shaping callers.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.anonymization.mapper import PseudonymMapper


@dataclass(slots=True)
class AnonymizationResult:
    """Outcome of a pseudonymization pass.

    ``text`` is the substituted text the gateway forwards to the
    provider. ``mapper`` carries the assignments so the response path
    can rehydrate originals via :meth:`PseudonymMapper.reverse`.
    """

    text: str
    mapper: PseudonymMapper


class Anonymizer:
    """Pseudonymize entities in outbound text; rehydrate on the response path.

    M2-A3 ships the class signature only. :meth:`pseudonymize` raises
    :class:`NotImplementedError` until M2-B3 wires Presidio's
    :class:`AnalyzerEngine`, the custom legal recognizers (M2-B2), and
    the spaCy NLP backbone. The middleware will allocate one instance
    per request and discard it on response.
    """

    def pseudonymize(self, text: str) -> AnonymizationResult:
        """Return an :class:`AnonymizationResult` with pseudonymized text.

        Stub for M2-A3; the real Presidio-backed implementation lands
        in M2-B3. Defined here so the middleware (M2-B3) and tests
        (M2-C3 round-trip) target a stable signature from the start.
        """

        raise NotImplementedError(
            "Anonymizer.pseudonymize is a stub until M2-B3 wires Presidio + "
            "the spaCy NLP backbone. M2-A3 ships PseudonymMapper only."
        )

    def rehydrate(self, text: str, mapper: PseudonymMapper) -> str:
        """Walk pseudonyms in ``text`` and substitute originals.

        Stub for M2-A3; M2-B3 will implement the response-path
        rehydration. The implementation is straightforward (one pass
        over ``mapper.reverse()`` items, ``str.replace`` for each)
        but the trade-offs between replacement strategies (length-
        ordered to avoid prefix collisions, regex-based to handle word
        boundaries, etc.) are M2-B3's decision.
        """

        raise NotImplementedError(
            "Anonymizer.rehydrate is a stub until M2-B3 lands the response-"
            "path middleware. M2-A3 ships PseudonymMapper only."
        )
