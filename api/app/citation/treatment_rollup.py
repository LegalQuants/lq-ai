"""Roll per-passage treatment judgments up to a case-level signal (WS-G PR2).

Strongest-negative posture (ADR 0019 D5): the case-level signal is the most
SEVERE negative class present; confidence (D6) is that class's strongest
contributor confidence plus a small corroboration bump per additional
agreeing passage, capped. Absence of any negative class → None (surfaced as
"no negative treatment found as of <date>", never "good law"). Pure + total.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from app.citation.treatment_judge import TreatmentJudgment

# Strongest first.
NEGATIVE_SEVERITY: tuple[str, ...] = (
    "overruled",
    "superseded",
    "criticized",
    "questioned",
    "distinguished",
)
_CORROBORATION_BUMP = 0.05
_CONFIDENCE_CAP = 0.95


@dataclass(slots=True)
class Rollup:
    strongest_negative_class: str | None
    per_class_counts: dict[str, int]
    case_confidence: float | None
    judged_count: int


def roll_up(signals: Sequence[TreatmentJudgment]) -> Rollup:
    counts = Counter(s.classification for s in signals)
    per_class = dict(counts)
    strongest: str | None = next((c for c in NEGATIVE_SEVERITY if counts.get(c)), None)
    if strongest is None:
        return Rollup(None, per_class, None, len(signals))
    agreeing = [s.confidence for s in signals if s.classification == strongest]
    base = max(agreeing)
    bumped = base + _CORROBORATION_BUMP * (len(agreeing) - 1)
    confidence = min(bumped, _CONFIDENCE_CAP)
    return Rollup(strongest, per_class, confidence, len(signals))
