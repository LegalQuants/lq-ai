"""DE-240 — deterministic integrity checks for the PII corpus + extraction fixtures.

Keyless and dependency-free: validates the committed JSON artifacts so a
malformed corpus entry or a false-positive-prone extraction fixture
fails fast, without spaCy, a provider key, or a running stack.

The load-bearing rule for extraction fixtures: a ``leak_indicator``
must be a TRANSFORMED rendering of the planted value (reversed,
letter-spelled, base64, ...), never something the normal
pseudonymize → provider → rehydrate round-trip could reproduce. If an
indicator were a substring of the setup text or of a planted value,
the live test would flag legitimate rehydrated responses as leaks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PII_DIR = Path(__file__).resolve().parent
CORPUS_PATH = PII_DIR / "corpus" / "pii_corpus.json"
BASELINE_PATH = PII_DIR / "baseline" / "pii_leakage_baseline.json"
EXTRACTION_PATH = PII_DIR / "extraction" / "extraction_prompts.json"

TARGETED_CLASSES = {
    "PERSON",
    "ORGANIZATION",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_BANK_NUMBER",
    "LOCATION",
    "CASE_NUMBER",
    "MATTER_NUMBER",
}


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


def test_corpus_entries_are_well_formed() -> None:
    corpus = _load(CORPUS_PATH)
    assert corpus["schema_version"] == 1

    seen_ids: set[str] = set()
    for entry in corpus["entries"]:
        assert set(entry) == {"id", "class", "variant", "targeted", "text", "expected_entities"}, (
            f"unexpected keys in corpus entry {entry.get('id')!r}"
        )
        assert entry["id"] not in seen_ids, f"duplicate corpus id {entry['id']}"
        seen_ids.add(entry["id"])
        assert entry["expected_entities"], f"{entry['id']}: no expected entities"
        for expected in entry["expected_entities"]:
            assert expected["value"] in entry["text"], (
                f"{entry['id']}: expected value {expected['value']!r} not present in text"
            )
        # Targeted entries use recognizer-target classes; untargeted
        # entries document the out-of-scope surface and must NOT claim
        # a targeted class.
        if entry["targeted"]:
            assert entry["class"] in TARGETED_CLASSES, (
                f"{entry['id']}: targeted entry uses non-recognizer class {entry['class']}"
            )
        else:
            assert entry["class"] not in TARGETED_CLASSES, (
                f"{entry['id']}: untargeted entry claims a targeted class"
            )


def test_corpus_covers_every_recognizer_target_class() -> None:
    """Corpus classes = the gateway's real recognizer targets, all of them."""

    corpus = _load(CORPUS_PATH)
    targeted_present = {e["class"] for e in corpus["entries"] if e["targeted"]}
    assert targeted_present == TARGETED_CLASSES

    untargeted_present = {e["class"] for e in corpus["entries"] if not e["targeted"]}
    assert untargeted_present, "the known-untargeted section must not be empty"


def test_baseline_is_committed_and_covers_targeted_classes() -> None:
    """The anti-regression baseline exists and matches the corpus scale."""

    corpus = _load(CORPUS_PATH)
    baseline = _load(BASELINE_PATH)

    assert baseline["metadata"]["corpus_entries"] == len(corpus["entries"])
    expected_total = sum(len(e["expected_entities"]) for e in corpus["entries"])
    assert baseline["metadata"]["expected_entities"] == expected_total

    baseline_targeted = {n for n, c in baseline["classes"].items() if c["targeted"]}
    assert baseline_targeted == TARGETED_CLASSES


def test_extraction_fixtures_are_well_formed() -> None:
    data = _load(EXTRACTION_PATH)
    assert data["schema_version"] == 1

    seen_ids: set[str] = set()
    for fixture in data["fixtures"]:
        assert fixture["id"] not in seen_ids
        seen_ids.add(fixture["id"])
        assert fixture["setup_content"]
        assert fixture["attack_content"]
        assert fixture["planted_values"], f"{fixture['id']}: no planted values"
        assert fixture["leak_indicators"], f"{fixture['id']}: no leak indicators"
        for planted in fixture["planted_values"]:
            assert planted in fixture["setup_content"], (
                f"{fixture['id']}: planted value {planted!r} not in setup_content"
            )


def test_extraction_indicators_cannot_false_positive_on_rehydration() -> None:
    """Indicators must be unreachable via the legitimate round-trip.

    A response produced by echoing pseudonyms is rehydrated back to the
    planted originals — so any indicator that appears inside the setup
    text or inside a planted value would fire on a NON-leaking system.
    """

    data = _load(EXTRACTION_PATH)
    for fixture in data["fixtures"]:
        for indicator in fixture["leak_indicators"]:
            assert indicator not in fixture["setup_content"], (
                f"{fixture['id']}: indicator {indicator!r} appears in setup_content"
            )
            assert indicator not in fixture["attack_content"], (
                f"{fixture['id']}: indicator {indicator!r} appears in attack_content"
            )
            for planted in fixture["planted_values"]:
                assert indicator not in planted, (
                    f"{fixture['id']}: indicator {indicator!r} is a substring of a "
                    f"planted value — rehydration would false-positive"
                )
