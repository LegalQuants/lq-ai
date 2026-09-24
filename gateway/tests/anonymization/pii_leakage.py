"""DE-240 — PII leakage measurement harness.

Runs the REAL anonymization engine (Presidio + spaCy ``en_core_web_lg``,
exactly as configured by :func:`app.anonymization.engine.get_analyzer_engine`)
over the labeled synthetic corpus at ``tests/pii/corpus/pii_corpus.json``
(repo root) and measures per-class / per-variant leakage rates.

Metric definitions (documented in ``docs/quality/pii-leakage-rates.md``):

* **full leak** — the expected entity value survives verbatim (substring,
  case-sensitive) in the anonymized output. The provider would receive
  the exact PII string.
* **partial leak** — the full value no longer survives, but at least one
  *significant token* of it does (length >= 4, not a generic
  structural/corporate word). The provider would receive an identifying
  fragment (a surname, a street name, a digit group).

The unit of measurement is the *expected entity occurrence*, not the
corpus entry — entries carrying several entities contribute one
measurement per entity. Leakage is measured, not classification
accuracy: an entity substituted under the "wrong" type (e.g. a person
caught as ORGANIZATION) still counts as protected, because the original
text never reaches the provider.

Two consumers:

* ``tests/anonymization/test_pii_leakage_rates.py`` — the slow-marked
  pytest module that runs the harness and enforces the anti-regression
  pin against the committed baseline.
* ``python -m tests.anonymization.pii_leakage`` (from ``gateway/``, in
  the gateway venv) — regenerates the baseline JSON and/or prints the
  markdown rate tables for ``docs/quality/pii-leakage-rates.md``.

The corpus and baseline live under the repo-root ``tests/pii/`` tree so
they're shared work product (DE-282's legal-corpus validation is the
successor for recall claims on *real* documents; this harness measures
format-variant behavior on synthetic values).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_PATH = REPO_ROOT / "tests" / "pii" / "corpus" / "pii_corpus.json"
BASELINE_PATH = REPO_ROOT / "tests" / "pii" / "baseline" / "pii_leakage_baseline.json"

# A targeted class's full-leak rate may not worsen by more than this
# many percentage points vs the committed baseline before the drift
# test fails. Rates are informational until DE-282 calibrates them; the
# pin only catches *regressions* (an engine/config/model drift that
# silently starts leaking a class it used to catch).
DRIFT_THRESHOLD_POINTS = 5.0

# Tokens of an expected value that are structural/generic and don't
# identify anyone on their own. A surviving "Avenue" or "Corporation"
# is not treated as a partial leak; a surviving "Marlowe" or "4472" is.
_GENERIC_TOKENS = frozenset(
    {
        # structural words that appear inside address/identifier values
        "avenue",
        "street",
        "road",
        "boulevard",
        "suite",
        "county",
        "courthouse",
        "account",
        "matter",
        "case",
        "number",
        # corporate suffixes (>= 4 chars; shorter ones are excluded by
        # the length rule anyway)
        "corporation",
        "company",
        "holdings",
        "incorporated",
        "limited",
        "gmbh",
    }
)
_MIN_TOKEN_LEN = 4

# Word-ish tokens: digit runs or letter runs (unicode-aware via \w
# minus digits/underscore).
_TOKEN_RE = re.compile(r"\d+|[^\W\d_]+", re.UNICODE)

# Canonical ordering for report rows: targeted classes in the order the
# engine documentation lists them, then whatever untargeted classes the
# corpus carries (sorted).
TARGETED_CLASS_ORDER = (
    "PERSON",
    "ORGANIZATION",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_BANK_NUMBER",
    "LOCATION",
    "CASE_NUMBER",
    "MATTER_NUMBER",
)


@dataclass(slots=True)
class EntityOutcome:
    """Measured outcome for one expected entity occurrence."""

    entry_id: str
    entity_class: str
    variant: str
    targeted: bool
    value: str
    full_leak: bool
    partial_leak: bool
    leaked_tokens: list[str]


def load_corpus(path: Path = CORPUS_PATH) -> dict[str, Any]:
    """Load and structurally validate the corpus JSON."""

    with path.open(encoding="utf-8") as fh:
        corpus: dict[str, Any] = json.load(fh)

    entries = corpus["entries"]
    seen_ids: set[str] = set()
    for entry in entries:
        entry_id = entry["id"]
        if entry_id in seen_ids:
            raise ValueError(f"duplicate corpus entry id: {entry_id}")
        seen_ids.add(entry_id)
        for expected in entry["expected_entities"]:
            if expected["value"] not in entry["text"]:
                raise ValueError(
                    f"corpus entry {entry_id}: expected value {expected['value']!r} "
                    f"does not appear in the entry text"
                )
    return corpus


def significant_tokens(value: str) -> list[str]:
    """Tokens of ``value`` that identify something on their own."""

    return [
        token
        for token in _TOKEN_RE.findall(value)
        if len(token) >= _MIN_TOKEN_LEN and token.lower() not in _GENERIC_TOKENS
    ]


def evaluate_entry(anonymized_text: str, entry: dict[str, Any]) -> list[EntityOutcome]:
    """Score one corpus entry's expected entities against its anonymized text."""

    outcomes: list[EntityOutcome] = []
    for expected in entry["expected_entities"]:
        value = expected["value"]
        full_leak = value in anonymized_text
        leaked_tokens = (
            [] if full_leak else [t for t in significant_tokens(value) if t in anonymized_text]
        )
        outcomes.append(
            EntityOutcome(
                entry_id=entry["id"],
                entity_class=expected["class"],
                variant=entry["variant"],
                targeted=bool(entry["targeted"]),
                value=value,
                full_leak=full_leak,
                partial_leak=bool(leaked_tokens),
                leaked_tokens=leaked_tokens,
            )
        )
    return outcomes


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:  # pragma: no cover - environment-dependent
        return "not-installed"


def _rate(count: int, n: int) -> float:
    return round(100.0 * count / n, 1) if n else 0.0


def measure(corpus: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the real engine over the corpus; return the rates report.

    Imports the engine lazily so merely importing this module never
    triggers the spaCy model load.
    """

    from app.anonymization.engine import Anonymizer, get_analyzer_engine
    from app.anonymization.mapper import PseudonymMapper

    if corpus is None:
        corpus = load_corpus()

    engine = get_analyzer_engine()
    anonymizer = Anonymizer(analyzer=engine)

    outcomes: list[EntityOutcome] = []
    for entry in corpus["entries"]:
        mapper = PseudonymMapper()
        anonymized = anonymizer.pseudonymize_into(entry["text"], mapper)
        outcomes.extend(evaluate_entry(anonymized, entry))

    return build_report(corpus, outcomes, recognizers=_recognizer_inventory(engine))


def _recognizer_inventory(engine: Any) -> list[dict[str, Any]]:
    """The recognizer set actually registered — honest config attribution."""

    return sorted(
        (
            {
                "name": type(recognizer).__name__,
                "supported_entities": sorted(recognizer.supported_entities),
            }
            for recognizer in engine.registry.recognizers
        ),
        key=lambda r: str(r["name"]),
    )


def build_report(
    corpus: dict[str, Any],
    outcomes: list[EntityOutcome],
    recognizers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate per-entity outcomes into the rates report structure."""

    classes: dict[str, dict[str, Any]] = {}
    for outcome in outcomes:
        cls = classes.setdefault(
            outcome.entity_class,
            {
                "targeted": outcome.targeted,
                "n": 0,
                "full_leaks": 0,
                "partial_leaks": 0,
                "variants": {},
            },
        )
        cls["n"] += 1
        cls["full_leaks"] += int(outcome.full_leak)
        cls["partial_leaks"] += int(outcome.partial_leak)
        var = cls["variants"].setdefault(
            outcome.variant, {"n": 0, "full_leaks": 0, "partial_leaks": 0}
        )
        var["n"] += 1
        var["full_leaks"] += int(outcome.full_leak)
        var["partial_leaks"] += int(outcome.partial_leak)

    for cls in classes.values():
        cls["full_leak_rate"] = _rate(cls["full_leaks"], cls["n"])
        cls["partial_leak_rate"] = _rate(cls["partial_leaks"], cls["n"])
        for var in cls["variants"].values():
            var["full_leak_rate"] = _rate(var["full_leaks"], var["n"])
            var["partial_leak_rate"] = _rate(var["partial_leaks"], var["n"])

    return {
        "metadata": {
            "generated": date.today().isoformat(),
            "corpus_schema_version": corpus["schema_version"],
            "corpus_entries": len(corpus["entries"]),
            "expected_entities": len(outcomes),
            "drift_threshold_points": DRIFT_THRESHOLD_POINTS,
            "versions": {
                "presidio-analyzer": _pkg_version("presidio-analyzer"),
                "presidio-anonymizer": _pkg_version("presidio-anonymizer"),
                "spacy": _pkg_version("spacy"),
                "en_core_web_lg": _pkg_version("en_core_web_lg"),
            },
            "recognizers": recognizers or [],
        },
        "classes": classes,
        "entities": [asdict(o) for o in outcomes],
    }


def ordered_classes(report: dict[str, Any]) -> list[str]:
    """Targeted classes in canonical order, then untargeted classes sorted."""

    classes = report["classes"]
    targeted = [c for c in TARGETED_CLASS_ORDER if c in classes]
    untargeted = sorted(c for c in classes if c not in TARGETED_CLASS_ORDER)
    return targeted + untargeted


def render_markdown(report: dict[str, Any]) -> str:
    """Render the rate tables for ``docs/quality/pii-leakage-rates.md``."""

    meta = report["metadata"]
    lines: list[str] = []
    versions = ", ".join(f"{k} {v}" for k, v in meta["versions"].items())
    lines.append(f"Measured {meta['generated']} — {versions}.")
    lines.append("")
    lines.append("| Class | Targeted | Entities | Full-leak rate | Partial-leak rate |")
    lines.append("|---|---|---:|---:|---:|")
    for cls_name in ordered_classes(report):
        cls = report["classes"][cls_name]
        lines.append(
            f"| {cls_name} | {'yes' if cls['targeted'] else 'no (documented out of scope)'} "
            f"| {cls['n']} | {cls['full_leak_rate']}% | {cls['partial_leak_rate']}% |"
        )
    lines.append("")
    lines.append("Per-variant breakdown (full-leak / partial-leak, n):")
    lines.append("")
    lines.append("| Class | Variant | n | Full leaks | Partial leaks |")
    lines.append("|---|---|---:|---:|---:|")
    for cls_name in ordered_classes(report):
        cls = report["classes"][cls_name]
        for variant_name in sorted(cls["variants"]):
            var = cls["variants"][variant_name]
            lines.append(
                f"| {cls_name} | {variant_name} | {var['n']} "
                f"| {var['full_leaks']} | {var['partial_leaks']} |"
            )
    return "\n".join(lines) + "\n"


def write_baseline(report: dict[str, Any], path: Path = BASELINE_PATH) -> None:
    """Write the committed anti-regression baseline (rates only, no per-entity rows)."""

    baseline = {
        "metadata": report["metadata"],
        "classes": {
            name: {
                "targeted": cls["targeted"],
                "n": cls["n"],
                "full_leaks": cls["full_leaks"],
                "full_leak_rate": cls["full_leak_rate"],
                "partial_leaks": cls["partial_leaks"],
                "partial_leak_rate": cls["partial_leak_rate"],
            }
            for name, cls in report["classes"].items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DE-240 PII leakage measurement")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help=f"write the anti-regression baseline to {BASELINE_PATH}",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="print the docs-ready markdown tables instead of the JSON report",
    )
    args = parser.parse_args(argv)

    report = measure()
    if args.write_baseline:
        write_baseline(report)
        print(f"baseline written: {BASELINE_PATH}", file=sys.stderr)
    if args.markdown:
        print(render_markdown(report))
    elif not args.write_baseline:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
