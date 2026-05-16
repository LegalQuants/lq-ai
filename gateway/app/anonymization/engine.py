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
from typing import TYPE_CHECKING

from app.anonymization.mapper import PseudonymMapper
from app.anonymization.recognizers.case_number import CaseNumberRecognizer
from app.anonymization.recognizers.matter_number import MatterNumberRecognizer

if TYPE_CHECKING:
    from presidio_analyzer import AnalyzerEngine

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

    Method bodies stubbed until M2-B3 lands the gateway middleware
    and decides on the exact substitution strategy (length-ordered
    ``str.replace`` vs. regex-based, ordering when one pseudonym is a
    prefix of another, etc.). The signatures are final so M2-B3
    middleware + M2-C3 round-trip tests can target a stable shape.
    """

    def pseudonymize(self, text: str) -> AnonymizationResult:
        """Return an :class:`AnonymizationResult` with pseudonymized text.

        Stub until M2-B3 wires the gateway request-path middleware.
        The implementation will call :func:`get_analyzer_engine` for
        entity recognition and a Presidio :class:`AnonymizerEngine`
        for substitution; M2-B2 (this task) made the analyzer
        available, M2-B3 ties it to the request path.
        """

        raise NotImplementedError(
            "Anonymizer.pseudonymize is a stub until M2-B3 wires the gateway "
            "request-path middleware. M2-B2 made the AnalyzerEngine + custom "
            "recognizers available via get_analyzer_engine()."
        )

    def rehydrate(self, text: str, mapper: PseudonymMapper) -> str:
        """Walk pseudonyms in ``text`` and substitute originals.

        Stub until M2-B3 lands the response-path middleware. The
        implementation is straightforward (one pass over
        ``mapper.reverse()`` items, ``str.replace`` for each ordered
        by descending length so prefix-collisions like
        ``PERSON_0001`` vs ``PERSON_00010`` resolve correctly) but
        M2-B3 makes the call alongside the streaming-response handling.
        """

        raise NotImplementedError(
            "Anonymizer.rehydrate is a stub until M2-B3 lands the response-"
            "path middleware. M2-A3 ships PseudonymMapper only."
        )
