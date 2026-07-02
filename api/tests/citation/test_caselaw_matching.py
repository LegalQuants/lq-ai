from app.citation.caselaw import match_case_name, normalize_case_name


def test_normalize_lowercases_and_collapses_whitespace() -> None:
    assert normalize_case_name("Brown   v.  Board") == "brown v. board"


def test_normalize_strips_trailing_citation_parenthetical() -> None:
    assert normalize_case_name("Roe v. Wade (410 U.S. 113)") == "roe v. wade"


def test_normalize_strips_trailing_punctuation() -> None:
    assert normalize_case_name("Palsgraf v. Long Island R.R.,") == "palsgraf v. long island r.r."


def test_match_returns_cluster_on_single_exact_match() -> None:
    clusters = [(701, "Brown v. Board of Education"), (702, "Roe v. Wade")]
    assert match_case_name("Brown v. Board of Education", clusters) == 701


def test_match_is_case_and_whitespace_insensitive() -> None:
    clusters = [(701, "Brown v. Board of Education")]
    assert match_case_name("brown   v.   board of education", clusters) == 701


def test_match_returns_none_on_zero_matches() -> None:
    clusters = [(701, "Brown v. Board of Education")]
    assert match_case_name("Marbury v. Madison", clusters) is None


def test_match_returns_none_on_two_matches() -> None:
    # Two consulted clusters share a normalized name -> ambiguous -> no attribution.
    clusters = [(701, "Smith v. Jones"), (702, "smith v. jones")]
    assert match_case_name("Smith v. Jones", clusters) is None


def test_match_skips_clusters_with_empty_case_name() -> None:
    clusters = [(701, ""), (702, "Roe v. Wade")]
    assert match_case_name("Roe v. Wade", clusters) == 702
