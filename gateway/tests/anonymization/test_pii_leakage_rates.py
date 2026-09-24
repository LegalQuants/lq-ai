"""DE-240 — PII leakage rates: harness run + anti-regression pin.

Runs the measurement harness (``tests/anonymization/pii_leakage.py``)
against the real Presidio + spaCy engine over the labeled corpus at
``tests/pii/corpus/pii_corpus.json`` (repo root) and enforces two
things:

1. **The harness runs and produces a complete report** — every corpus
   entry evaluated, every expected entity scored. This is the CI gate:
   the *measurement capability* must not rot.
2. **No-regression drift pin** — a targeted class's full-leak rate may
   not worsen by more than ``DRIFT_THRESHOLD_POINTS`` (5) percentage
   points versus the committed baseline
   (``tests/pii/baseline/pii_leakage_baseline.json``). The absolute
   rates are deliberately NOT gated: they are informational until
   DE-282 calibrates recognizer accuracy on a real legal-document
   corpus, and several are honestly bad (see
   ``docs/quality/pii-leakage-rates.md`` — ORGANIZATION leaks 100% as
   of the first measurement). The pin only catches *drift*: an
   engine/config/model change that silently starts leaking a class
   that used to be caught.

Untargeted classes (``targeted: false`` in the corpus — SSN, EIN,
driver's license, IP, IBAN, ...) are measured informationally and
never gate; they document what the recognizer configuration
deliberately does not cover.

Regenerating the baseline after a deliberate corpus or engine change:

    cd gateway && .venv/bin/python -m tests.anonymization.pii_leakage --write-baseline

Marked ``slow`` (spaCy ``en_core_web_lg`` load, ~1-3s; the ~70 analyze
calls add roughly the same again).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.anonymization import pii_leakage

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    """Run the full measurement once for this module."""

    from app.anonymization.engine import _reset_analyzer_engine_for_tests

    _reset_analyzer_engine_for_tests()
    return pii_leakage.measure()


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    assert pii_leakage.BASELINE_PATH.exists(), (
        f"Missing committed baseline {pii_leakage.BASELINE_PATH}. Generate it with: "
        f"cd gateway && python -m tests.anonymization.pii_leakage --write-baseline"
    )
    with pii_leakage.BASELINE_PATH.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


def test_harness_evaluates_every_corpus_entity(report: dict[str, Any]) -> None:
    """Gate: the harness runs end-to-end and scores the whole corpus."""

    corpus = pii_leakage.load_corpus()
    expected_total = sum(len(e["expected_entities"]) for e in corpus["entries"])

    assert report["metadata"]["corpus_entries"] == len(corpus["entries"])
    assert report["metadata"]["expected_entities"] == expected_total
    assert len(report["entities"]) == expected_total

    # Every targeted class the corpus documents shows up in the report.
    reported = set(report["classes"])
    corpus_classes = {
        expected["class"] for entry in corpus["entries"] for expected in entry["expected_entities"]
    }
    assert corpus_classes == reported


def test_report_attributes_the_measured_configuration(report: dict[str, Any]) -> None:
    """The report is honestly attributed: versions + real recognizer inventory."""

    versions = report["metadata"]["versions"]
    for pkg in ("presidio-analyzer", "presidio-anonymizer", "spacy", "en_core_web_lg"):
        assert versions[pkg] != "not-installed", f"{pkg} missing from the measured environment"

    recognizer_names = {r["name"] for r in report["metadata"]["recognizers"]}
    # The custom legal recognizers must be part of the measured config.
    assert {"CaseNumberRecognizer", "MatterNumberRecognizer"} <= recognizer_names
    # The disabled defaults must NOT be part of the measured config.
    from app.anonymization.engine import DISABLED_DEFAULT_RECOGNIZERS

    assert not (set(DISABLED_DEFAULT_RECOGNIZERS) & recognizer_names)


def test_corpus_matches_baseline_shape(report: dict[str, Any], baseline: dict[str, Any]) -> None:
    """Corpus changes require a deliberate baseline regeneration."""

    assert report["metadata"]["corpus_entries"] == baseline["metadata"]["corpus_entries"], (
        "Corpus entry count changed vs the committed baseline. If the corpus change "
        "is deliberate, regenerate: cd gateway && python -m tests.anonymization.pii_leakage "
        "--write-baseline (and refresh docs/quality/pii-leakage-rates.md)."
    )
    assert report["metadata"]["expected_entities"] == baseline["metadata"]["expected_entities"]


def test_targeted_full_leak_rates_do_not_regress(
    report: dict[str, Any], baseline: dict[str, Any]
) -> None:
    """Drift pin: no targeted class worsens by > DRIFT_THRESHOLD_POINTS points."""

    threshold = pii_leakage.DRIFT_THRESHOLD_POINTS
    regressions: list[str] = []
    for cls_name, base_cls in baseline["classes"].items():
        if not base_cls["targeted"]:
            continue  # untargeted classes are informational, never gate
        current = report["classes"].get(cls_name)
        assert current is not None, f"class {cls_name} vanished from the report"
        delta = current["full_leak_rate"] - base_cls["full_leak_rate"]
        if delta > threshold:
            regressions.append(
                f"{cls_name}: {base_cls['full_leak_rate']}% -> {current['full_leak_rate']}% "
                f"(+{round(delta, 1)} points)"
            )

    assert not regressions, (
        "PII full-leak rate regressed beyond the ±"
        f"{threshold}-point drift pin for: {'; '.join(regressions)}. If the regression is "
        "an accepted trade-off (documented!), regenerate the baseline and update "
        "docs/quality/pii-leakage-rates.md; otherwise fix the engine/config drift."
    )


def test_untargeted_classes_are_present_and_informational(
    report: dict[str, Any],
) -> None:
    """The known-untargeted section exists — the out-of-scope surface stays documented."""

    untargeted = [name for name, cls in report["classes"].items() if not cls["targeted"]]
    assert "US_SSN" in untargeted, (
        "The corpus must keep documenting deliberately-untargeted classes "
        "(engine.py disables UsSsnRecognizer et al.); US_SSN is the canonical example."
    )
