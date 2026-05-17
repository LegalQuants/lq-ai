"""Anonymizer façade + module-level AnalyzerEngine — M2-A3 → M2-B2.

The :class:`Anonymizer` is the entry point the gateway middleware
(M2-B3) will use to pseudonymize an outbound prompt and rehydrate the
returning response. M2-A3 shipped the class shape; M2-B2 (this task)
adds:

* :func:`get_analyzer_engine` — module-level singleton that
  constructs a Presidio :class:`AnalyzerEngine`, registers the
  custom legal recognizers (``CaseNumberRecognizer``,
  ``MatterNumberRecognizer``), and disables the noisy default
  recognizers that don't pay off on legal-document corpus.
* :data:`ENABLED_DEFAULT_RECOGNIZERS` and
  :data:`DISABLED_DEFAULT_RECOGNIZERS` — the recognizer-list
  configuration the singleton applies. Documented inline so the
  rationale is alongside the code.

M2-B3 will wire :meth:`Anonymizer.pseudonymize` and
:meth:`Anonymizer.rehydrate` to call the engine + the Presidio
:class:`AnonymizerEngine`. Today those methods still raise
:class:`NotImplementedError` because the request/response middleware
path isn't built yet.

Why a module-level singleton?
-----------------------------

Constructing an :class:`AnalyzerEngine` loads spaCy's
``en_core_web_lg`` model (~560MB on disk, 2-3 seconds wall-clock).
Doing that per-request would dominate gateway latency. The
middleware allocates one mapper per request (in-process, drops on
response) but **reuses the analyzer** across requests. Same pattern
Presidio's own examples and FastAPI integrations follow.

The singleton is lazy: it's only constructed on first call. The
test suite that just exercises the custom recognizers in isolation
(via ``recognizer.analyze(...)`` directly) never triggers it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

from app.anonymization.mapper import PseudonymMapper
from app.anonymization.recognizers.case_number import CaseNumberRecognizer
from app.anonymization.recognizers.matter_number import MatterNumberRecognizer

if TYPE_CHECKING:
    from presidio_analyzer import AnalyzerEngine


class _AnalyzerProtocol(Protocol):
    """Subset of :class:`presidio_analyzer.AnalyzerEngine` we depend on.

    Lets :class:`Anonymizer` accept either the real Presidio engine
    (the production path) or a test double in unit tests, without
    importing Presidio just for type-checking. The real engine's
    ``analyze`` returns ``list[RecognizerResult]``; we only read
    ``entity_type``, ``start``, ``end`` (and ``score`` for overlap
    tie-breaks), which both shapes expose.
    """

    def analyze(self, *, text: str, language: str = "en") -> list[Any]: ...


# Default-recognizer configuration for legal-document corpus.
#
# **Enabled** — these recognizers pay off on legal prose; the
# false-positive rate is acceptable and the entities they catch are
# the ones in-house lawyers actually want pseudonymized:
#
# * ``PERSON`` — names of parties, judges, counsel, witnesses.
# * ``ORG`` — corporate entities, firms, agencies.
# * ``EMAIL_ADDRESS`` — counsel email, party email.
# * ``PHONE_NUMBER`` — contact numbers in correspondence.
# * ``US_BANK_NUMBER`` — bank account numbers that show up in
#   settlement statements, escrow docs. Surfaces under Presidio's
#   built-in ``US_BANK_NUMBER`` entity type.
# * ``LOCATION`` — addresses, courthouses, jurisdictions. Mapped to
#   ``ADDRESS`` in the pseudonym domain to match the operator's
#   mental model.
# * Custom entities from this task — ``CASE_NUMBER``,
#   ``MATTER_NUMBER``.
ENABLED_DEFAULT_RECOGNIZERS: tuple[str, ...] = (
    "PERSON",
    "ORGANIZATION",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_BANK_NUMBER",
    "LOCATION",
)

# **Disabled** — these recognizers ship in Presidio's default set
# but produce a high false-positive rate on legal corpus, or cover
# entity types that are irrelevant for in-house legal work. We
# remove them from the analyzer so they don't fire even when an
# operator's text accidentally pattern-matches:
#
# * ``US_PASSPORT`` / ``US_DRIVER_LICENSE`` / ``US_SSN`` — high
#   false-positive rate in contract numbers, dates, and exhibit
#   indexes. The downside risk of redacting "Exhibit A-123-45-6789"
#   as an SSN outweighs the small probability of an actual SSN
#   appearing in a brief.
# * ``CRYPTO`` — irrelevant for legal corpus; the patterns
#   (Bitcoin/Ethereum addresses) collide with random hex strings.
# * ``IBAN_CODE`` — US-centric deployments rarely see them; when
#   they do, the bank-number recognizer covers the use case.
# * ``IP_ADDRESS`` — incidental in evidence logs but extremely
#   high false-positive rate against version numbers, page
#   references, and dotted numeric identifiers.
# * ``MEDICAL_LICENSE`` — niche to healthcare practice areas; the
#   shape collides with case numbers in unrelated corpora.
#
# Operators whose corpus benefits from these (e.g. a healthcare
# practice that needs ``MEDICAL_LICENSE``) re-enable per-recognizer
# in their deployment config; see ``docs/security/anonymization.md``.
DISABLED_DEFAULT_RECOGNIZERS: tuple[str, ...] = (
    "UsPassportRecognizer",
    "UsLicenseRecognizer",
    "UsSsnRecognizer",
    "CryptoRecognizer",
    "IbanRecognizer",
    "IpRecognizer",
    "MedicalLicenseRecognizer",
)


_analyzer_singleton: AnalyzerEngine | None = None


def get_analyzer_engine() -> AnalyzerEngine:
    """Return a configured :class:`AnalyzerEngine`, constructing once.

    First call constructs the engine, loads spaCy's NLP backbone,
    registers the custom legal recognizers, and removes the disabled
    defaults. Subsequent calls return the cached instance — the
    AnalyzerEngine is thread-safe for read-only ``analyze`` calls.

    Tests that exercise individual recognizers in isolation should
    NOT call this — they should instantiate the recognizer directly
    and invoke ``recognizer.analyze(text, entities=[...])``. Calling
    this triggers the spaCy load.
    """

    global _analyzer_singleton
    if _analyzer_singleton is not None:
        return _analyzer_singleton

    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry

    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()

    # Remove the noisy default recognizers (see
    # DISABLED_DEFAULT_RECOGNIZERS above for the per-name rationale).
    registry.recognizers = [
        r for r in registry.recognizers if type(r).__name__ not in DISABLED_DEFAULT_RECOGNIZERS
    ]

    # Register the custom legal recognizers.
    registry.add_recognizer(CaseNumberRecognizer())
    registry.add_recognizer(MatterNumberRecognizer())

    _analyzer_singleton = AnalyzerEngine(registry=registry)
    return _analyzer_singleton


def _reset_analyzer_engine_for_tests() -> None:
    """Drop the cached singleton. Tests use this to start from a clean state."""

    global _analyzer_singleton
    _analyzer_singleton = None


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

    Instances are lightweight and stateless beyond the (optionally
    injected) analyzer. The middleware allocates one Anonymizer +
    one :class:`PseudonymMapper` per request; the analyzer dependency
    is the module-level singleton (``get_analyzer_engine``) by default
    so spaCy stays loaded across requests, but tests inject a stub to
    keep the fast-feedback path off the spaCy model.

    Two entry points:

    * :meth:`pseudonymize_into` — extends an existing mapper with
      substitutions from ``text``. The middleware uses this so the
      same name appearing across multiple messages resolves to the
      same pseudonym.
    * :meth:`pseudonymize` — one-shot convenience that wraps a fresh
      mapper in an :class:`AnonymizationResult`. Useful in tests and
      single-text callers; the middleware does NOT use this.
    """

    def __init__(self, analyzer: _AnalyzerProtocol | None = None) -> None:
        """Inject an analyzer or fall back to the module singleton lazily.

        Passing ``analyzer=None`` (the default) defers the analyzer
        lookup to first ``pseudonymize_into`` call — Anonymizer
        construction never triggers a spaCy load on its own.
        """

        self._analyzer = analyzer

    def _resolve_analyzer(self) -> _AnalyzerProtocol:
        analyzer = self._analyzer
        if analyzer is None:
            # ``AnalyzerEngine`` (the real Presidio type) satisfies
            # ``_AnalyzerProtocol`` structurally — both expose
            # ``analyze(text, language)`` returning a list. mypy can't
            # verify that because Presidio's types are untyped at the
            # third-party boundary, so we cast at the import edge.
            analyzer = cast(_AnalyzerProtocol, get_analyzer_engine())
            self._analyzer = analyzer
        return analyzer

    def pseudonymize(self, text: str) -> AnonymizationResult:
        """One-shot: pseudonymize ``text`` against a fresh mapper.

        Returns an :class:`AnonymizationResult` carrying the substituted
        text + the freshly populated mapper. The middleware does NOT
        use this — it allocates one mapper per request and threads it
        through :meth:`pseudonymize_into` for each message — but
        single-text callers (tests, one-off rehydration scripts) get a
        clean façade.
        """

        mapper = PseudonymMapper()
        substituted = self.pseudonymize_into(text, mapper)
        return AnonymizationResult(text=substituted, mapper=mapper)

    def pseudonymize_into(self, text: str, mapper: PseudonymMapper) -> str:
        """Extend ``mapper`` with substitutions from ``text``; return the result.

        Walks the analyzer's spans, resolves overlapping detections to
        the longer span (ties broken by score), then substitutes
        right-to-left so earlier offsets stay valid. Calling
        :meth:`PseudonymMapper.assign` for an already-known
        ``(entity_type, original)`` reuses the prior pseudonym, so the
        same name across multiple ``pseudonymize_into`` calls on the
        same mapper resolves to the same pseudonym.

        Empty text short-circuits; the analyzer is never called.
        """

        if not text:
            return text

        analyzer = self._resolve_analyzer()
        results = analyzer.analyze(text=text, language="en")
        spans = _resolve_overlaps(results)

        # Two-pass substitution. Pass 1 walks spans left-to-right and
        # calls ``mapper.assign`` so the per-entity-type counter
        # increments in *reading* order (``PERSON_0001`` is the first
        # name in the text, not the last). Pass 2 splices substitutions
        # in right-to-left order so earlier ``(start, end)`` offsets
        # stay valid as the text length changes around each splice.
        ordered = sorted(spans, key=lambda s: s.start)
        pseudonyms: list[tuple[Any, str]] = [
            (span, mapper.assign(span.entity_type, text[span.start : span.end])) for span in ordered
        ]

        out = text
        for span, pseudonym in reversed(pseudonyms):
            out = out[: span.start] + pseudonym + out[span.end :]
        return out

    def rehydrate(self, text: str, mapper: PseudonymMapper) -> str:
        """Walk pseudonyms in ``text`` and substitute originals.

        One pass over ``mapper.reverse()`` items, ``str.replace`` for
        each pseudonym ordered by descending length. The ordering is
        load-bearing: without it a shorter pseudonym (``PERSON_0001``)
        would match-and-replace inside a longer one (``PERSON_00010``)
        and mangle the output.

        Empty mapper, empty text, and text containing no pseudonyms
        all return cleanly (an empty ``reverse()`` table makes the
        loop a no-op).
        """

        if not text:
            return text
        for pseudonym, original in sorted(
            mapper.reverse().items(), key=lambda kv: len(kv[0]), reverse=True
        ):
            text = text.replace(pseudonym, original)
        return text


def _resolve_overlaps(results: list[Any]) -> list[Any]:
    """Collapse overlapping analyzer spans to one per region.

    Presidio's :class:`AnalyzerEngine` returns every recognizer's hit;
    two recognizers detecting the same span (e.g. ``PERSON`` and a
    false-positive ``US_BANK_NUMBER`` on ``John Smith``) surface as
    two results. The substitution loop must see one span per region or
    it will try to splice inside an already-substituted pseudonym.

    Resolution: sort by ``(span_length, score)`` descending and walk;
    for each span, drop any later span whose ``[start, end)`` overlaps
    one already kept. Longest wins; same length → higher score wins.
    """

    if not results:
        return []
    ordered = sorted(
        results,
        key=lambda r: (r.end - r.start, getattr(r, "score", 0.0)),
        reverse=True,
    )
    kept: list[Any] = []
    for span in ordered:
        if any(_overlaps(span, k) for k in kept):
            continue
        kept.append(span)
    return kept


def _overlaps(a: Any, b: Any) -> bool:
    """True iff ``[a.start, a.end)`` and ``[b.start, b.end)`` share any char."""

    return bool(a.start < b.end and b.start < a.end)
