"""Unit tests for the DE-370 citation-attribution parser (pure, no DB/I-O).

Covers: each recognized citation form, near-miss negatives, window
boundaries, proximity ordering, normalization matching against realistic
external_ref shapes (GovInfo package/granule ids, EUR-Lex CELEX ids, EDGAR
accession numbers as a must-never-match negative), and a pathological-input
ReDoS guard.
"""

from __future__ import annotations

import time

from app.citation.authority_attribution import (
    ATTRIBUTION_WINDOW_CHARS,
    AttributedAuthorityPassage,
    ParsedAuthorityReference,
    attribute_authority_passages,
    reference_matches_external_ref,
)
from app.citation.caselaw import extract_blockquote_passages

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _single(text: str) -> AttributedAuthorityPassage:
    out = attribute_authority_passages(text)
    assert len(out) == 1, f"expected exactly one passage, got {out!r}"
    return out[0]


def _refs(text: str) -> tuple[ParsedAuthorityReference, ...]:
    return _single(text).references


# ---------------------------------------------------------------------------
# US Code forms
# ---------------------------------------------------------------------------


def test_usc_canonical_form() -> None:
    (ref,) = _refs("Under 17 U.S.C. § 107:\n\n> quoted text.\n")
    assert (ref.kind, ref.title, ref.sections) == ("usc", "17", ("107",))
    assert ref.section_range is None


def test_usc_bare_form() -> None:
    (ref,) = _refs("Under 17 USC 107:\n\n> quoted text.\n")
    assert (ref.kind, ref.title, ref.sections) == ("usc", "17", ("107",))


def test_usc_spaced_abbreviation() -> None:
    (ref,) = _refs("Under 17 U. S. C. § 107:\n\n> quoted text.\n")
    assert (ref.kind, ref.title, ref.sections) == ("usc", "17", ("107",))


def test_usc_double_section_range() -> None:
    (ref,) = _refs("See 17 U.S.C. §§ 107-108.\n\n> quoted text.\n")
    assert ref.sections == ("107", "108")
    assert ref.section_range == (107, 108)


def test_usc_en_dash_range() -> None:
    (ref,) = _refs("See 17 U.S.C. §§ 107–108.\n\n> quoted text.\n")  # noqa: RUF001
    assert ref.section_range == (107, 108)


def test_usc_lettered_section_with_dash_is_single_section() -> None:
    (ref,) = _refs("Under 15 U.S.C. § 1681s-2:\n\n> furnisher duties.\n")
    assert ref.sections == ("1681s-2",)
    assert ref.section_range is None


def test_usc_citation_inside_blockquote_attributes() -> None:
    (ref,) = _refs("> As stated in 17 U.S.C. § 107, fair use is not infringement.\n")
    assert (ref.kind, ref.title) == ("usc", "17")


def test_usc_trailing_digit_never_truncated() -> None:
    # "§ 1078" must parse as section 1078, never a truncated 107.
    (ref,) = _refs("Under 17 U.S.C. § 1078:\n\n> quoted text.\n")
    assert ref.sections == ("1078",)


# ---------------------------------------------------------------------------
# CFR forms
# ---------------------------------------------------------------------------


def test_cfr_bare_form() -> None:
    (ref,) = _refs("Per 40 CFR 1500.1:\n\n> nepa text.\n")
    assert (ref.kind, ref.title, ref.sections) == ("cfr", "40", ("1500-1",))


def test_cfr_canonical_form_with_section_sign() -> None:
    (ref,) = _refs("Per 40 C.F.R. § 1500.1:\n\n> nepa text.\n")
    assert (ref.kind, ref.title, ref.sections) == ("cfr", "40", ("1500-1",))


def test_cfr_part_form() -> None:
    (ref,) = _refs("Per 29 C.F.R. part 1910:\n\n> osha text.\n")
    assert (ref.kind, ref.title, ref.sections) == ("cfr", "29", ("1910",))


# ---------------------------------------------------------------------------
# EU / CELEX forms
# ---------------------------------------------------------------------------


def test_celex_raw_id() -> None:
    (ref,) = _refs("Per 32016R0679:\n\n> gdpr text.\n")
    assert (ref.kind, ref.celex) == ("celex", "32016R0679")


def test_eu_regulation_modern_form() -> None:
    (ref,) = _refs("Regulation (EU) 2016/679 provides:\n\n> gdpr text.\n")
    assert ref.celex == "32016R0679"


def test_eu_directive_classic_two_digit_year() -> None:
    (ref,) = _refs("Directive 95/46/EC provided:\n\n> dpd text.\n")
    assert ref.celex == "31995L0046"


def test_eu_directive_modern_form() -> None:
    (ref,) = _refs("Directive (EU) 2016/680 provides:\n\n> led text.\n")
    assert ref.celex == "32016L0680"


def test_eu_regulation_old_number_first_form() -> None:
    (ref,) = _refs("Regulation (EC) No 45/2001 provides:\n\n> text.\n")
    assert ref.celex == "32001R0045"


def test_eu_decision_modern_form() -> None:
    (ref,) = _refs("Decision (EU) 2015/1814 provides:\n\n> msr text.\n")
    assert ref.celex == "32015D1814"


def test_eu_textual_shorthand_not_mapped() -> None:
    # "Article 6(1)(a) GDPR" needs a name registry -> deterministically
    # unmappable -> unattributed (never guess).
    assert _refs("Article 6(1)(a) GDPR provides:\n\n> text.\n") == ()


# ---------------------------------------------------------------------------
# Near-miss negatives
# ---------------------------------------------------------------------------


def test_no_citation_no_references() -> None:
    assert _refs("The statute provides:\n\n> quoted text.\n") == ()


def test_usc_without_title_not_parsed() -> None:
    assert _refs("See USC 107 for details:\n\n> quoted text.\n") == ()


def test_usc_without_section_not_parsed() -> None:
    assert _refs("Title 17 U.S.C. governs copyright generally.\n\n> quoted text.\n") == ()


def test_prose_directive_fraction_not_parsed() -> None:
    # No (EU)/(EC) prefix, no "No", no /EC suffix -> prose, not a citation.
    assert _refs("Directive 12/34 said something:\n\n> text.\n") == ()


def test_plain_number_run_not_celex() -> None:
    assert _refs("Invoice 3201670679 was overdue.\n\n> text.\n") == ()


def test_no_blockquote_no_passages() -> None:
    assert attribute_authority_passages("Under 17 U.S.C. § 107 fair use applies.") == []


# ---------------------------------------------------------------------------
# Window boundaries and proximity
# ---------------------------------------------------------------------------


def test_citation_within_preceding_window_attributes() -> None:
    cite = "See 17 U.S.C. 107."
    pad = "x" * (ATTRIBUTION_WINDOW_CHARS - len(cite) - 4)
    (ref,) = _refs(f"{cite} {pad}\n\n> quote.\n")
    assert ref.title == "17"


def test_citation_beyond_preceding_window_not_attributed() -> None:
    cite = "See 17 U.S.C. 107."
    pad = "x" * (ATTRIBUTION_WINDOW_CHARS + 10)
    assert _refs(f"{cite} {pad}\n\n> quote.\n") == ()


def test_citation_in_following_window_attributes() -> None:
    (ref,) = _refs("> quote.\n\n— 17 U.S.C. § 107.\n")
    assert ref.title == "17"


def test_citation_beyond_following_window_not_attributed() -> None:
    pad = "x" * (ATTRIBUTION_WINDOW_CHARS + 10)
    assert _refs(f"> quote.\n\n{pad} 17 U.S.C. § 107.\n") == ()


def test_citation_inside_previous_blockquote_does_not_leak() -> None:
    out = attribute_authority_passages(
        "> first quote citing 17 U.S.C. § 107 inline.\n\nplain text\n\n> second quote.\n"
    )
    assert len(out) == 2
    assert len(out[0].references) == 1
    assert out[1].references == ()


def test_proximity_ordering_nearest_first() -> None:
    refs = _refs("See 40 CFR 1500.1. Meanwhile, under 17 U.S.C. § 107:\n\n> quote.\n")
    assert [r.kind for r in refs] == ["usc", "cfr"]


def test_in_block_citation_ranks_before_window_citation() -> None:
    refs = _refs("Under 40 CFR 1500.1:\n\n> quote citing 17 U.S.C. § 107 inline.\n")
    assert [r.kind for r in refs] == ["usc", "cfr"]


def test_passages_align_with_extract_blockquote_passages() -> None:
    text = (
        "Under 17 U.S.C. § 107:\n\n> first quote.\n> continued line.\n\n"
        "And per 40 CFR 1500.1:\n\n> second quote.\n"
    )
    attributed = attribute_authority_passages(text)
    assert [a.passage for a in attributed] == extract_blockquote_passages(text)


# ---------------------------------------------------------------------------
# Normalization matching against realistic external_ref shapes
# ---------------------------------------------------------------------------


def _usc_ref(text: str = "Under 17 U.S.C. § 107:\n\n> q.\n") -> ParsedAuthorityReference:
    return _refs(text)[0]


def test_usc_matches_title_level_govinfo_package() -> None:
    assert reference_matches_external_ref(_usc_ref(), "USCODE-2022-title17")


def test_usc_title_mismatch_does_not_match() -> None:
    assert not reference_matches_external_ref(_usc_ref(), "USCODE-2022-title15")


def test_usc_matches_section_granule() -> None:
    assert reference_matches_external_ref(_usc_ref(), "USCODE-2022-title17-chap1-sec107")


def test_usc_section_granule_mismatch() -> None:
    assert not reference_matches_external_ref(_usc_ref(), "USCODE-2022-title17-chap1-sec108")


def test_usc_range_covers_interior_section_granule() -> None:
    ref = _usc_ref("See 17 U.S.C. §§ 107-110:\n\n> q.\n")
    assert reference_matches_external_ref(ref, "USCODE-2022-title17-chap1-sec108")
    assert not reference_matches_external_ref(ref, "USCODE-2022-title17-chap1-sec111")


def test_usc_never_matches_edgar_accession_number() -> None:
    assert not reference_matches_external_ref(_usc_ref(), "0000320193-24-000123")


def test_usc_never_matches_celex_ref() -> None:
    assert not reference_matches_external_ref(_usc_ref(), "32016R0679")


def _cfr_ref() -> ParsedAuthorityReference:
    return _refs("Per 40 CFR 1500.1:\n\n> q.\n")[0]


def test_cfr_matches_title_level_govinfo_package() -> None:
    assert reference_matches_external_ref(_cfr_ref(), "CFR-2023-title40")


def test_cfr_title_mismatch_does_not_match() -> None:
    assert not reference_matches_external_ref(_cfr_ref(), "CFR-2023-title29")


def test_cfr_matches_section_granule_dots_normalized() -> None:
    assert reference_matches_external_ref(_cfr_ref(), "CFR-2023-title40-vol33-sec1500-1")


def test_cfr_section_granule_mismatch() -> None:
    assert not reference_matches_external_ref(_cfr_ref(), "CFR-2023-title40-vol33-sec1500-2")


def test_cfr_part_granule_match_and_mismatch() -> None:
    assert reference_matches_external_ref(_cfr_ref(), "CFR-2023-title40-part1500")
    assert not reference_matches_external_ref(_cfr_ref(), "CFR-2023-title40-part1501")


def test_cfr_part_cite_covers_section_granule_in_part() -> None:
    ref = _refs("Per 29 C.F.R. part 1910:\n\n> q.\n")[0]
    assert reference_matches_external_ref(ref, "CFR-2023-title29-vol5-sec1910-95")


def test_celex_matches_exact_ref_only() -> None:
    ref = _refs("Regulation (EU) 2016/679:\n\n> q.\n")[0]
    assert reference_matches_external_ref(ref, "32016R0679")
    assert not reference_matches_external_ref(ref, "31995L0046")
    assert not reference_matches_external_ref(ref, "USCODE-2022-title17")
    assert not reference_matches_external_ref(ref, "0000320193-24-000123")


# ---------------------------------------------------------------------------
# ReDoS guard (the Onyx catastrophic-backtracking lesson)
# ---------------------------------------------------------------------------


def test_pathological_input_parses_fast() -> None:
    adversarial = (
        "17 "
        + "U" * 5_000
        + " "
        + "1" * 50_000
        + " U.S.C. § "
        + "9" * 50_000
        + " "
        + "1-" * 30_000
        + "\n17 U.S.C. §§ "
        + "10-" * 20_000
        + "\n40 C"
        + "." * 5_000
        + "F.R. 1500."
        + "\nRegulation (EU) "
        + "2016/" * 10_000
        + "\n> "
        + "q" * 100_000
        + "\n"
    )
    start = time.monotonic()
    attribute_authority_passages(adversarial)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"pathological input took {elapsed:.3f}s"
