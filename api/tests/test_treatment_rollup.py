from app.citation.treatment_judge import TreatmentJudgment
from app.citation.treatment_rollup import NEGATIVE_SEVERITY, Rollup, roll_up


def _j(cls, conf=0.7):
    return TreatmentJudgment(classification=cls, confidence=conf, justification="x")


def test_severity_order_is_fixed():
    assert NEGATIVE_SEVERITY == (
        "overruled",
        "superseded",
        "criticized",
        "questioned",
        "distinguished",
    )


def test_empty():
    r = roll_up([])
    assert r == Rollup(None, {}, None, 0)


def test_all_non_negative_has_no_strongest():
    r = roll_up([_j("followed"), _j("neutral"), _j("followed")])
    assert r.strongest_negative_class is None
    assert r.case_confidence is None
    assert r.per_class_counts == {"followed": 2, "neutral": 1}
    assert r.judged_count == 3


def test_picks_most_severe_negative():
    r = roll_up([_j("distinguished"), _j("questioned"), _j("overruled"), _j("followed")])
    assert r.strongest_negative_class == "overruled"
    assert r.per_class_counts["distinguished"] == 1


def test_corroboration_bumps_confidence():
    # two "questioned" @0.70 → 0.70 + 0.05*(2-1) = 0.75
    r = roll_up([_j("questioned", 0.70), _j("questioned", 0.70), _j("followed")])
    assert r.strongest_negative_class == "questioned"
    assert abs(r.case_confidence - 0.75) < 1e-9


def test_confidence_capped():
    sig = [_j("criticized", 0.90)] * 6  # 0.90 + 0.05*5 = 1.15 → cap 0.95
    r = roll_up(sig)
    assert abs(r.case_confidence - 0.95) < 1e-9


def test_confidence_uses_strongest_class_only():
    # strongest = overruled (one @0.50); the questioned ones don't corroborate it
    r = roll_up([_j("overruled", 0.50), _j("questioned", 0.90), _j("questioned", 0.90)])
    assert r.strongest_negative_class == "overruled"
    assert abs(r.case_confidence - 0.50) < 1e-9
