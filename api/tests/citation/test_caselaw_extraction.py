from app.citation.caselaw import AttributedPassage, attribute_passages, extract_blockquote_passages


def test_extracts_single_blockquote() -> None:
    answer = (
        "**Relevant passage:**\n"
        "> The implied covenant of good faith and fair dealing.\n"
        "\nHow this bears on the question: ...\n"
    )
    assert extract_blockquote_passages(answer) == [
        "The implied covenant of good faith and fair dealing."
    ]


def test_joins_consecutive_blockquote_lines() -> None:
    answer = "> first line\n> second line\n"
    assert extract_blockquote_passages(answer) == ["first line second line"]


def test_multiple_separate_blockquotes() -> None:
    answer = "> alpha\n\nsome prose\n\n> beta\n"
    assert extract_blockquote_passages(answer) == ["alpha", "beta"]


def test_no_blockquotes_returns_empty() -> None:
    assert extract_blockquote_passages("just prose, no quotes") == []


def test_strips_marker_and_extra_spaces() -> None:
    answer = ">   padded passage   \n"
    assert extract_blockquote_passages(answer) == ["padded passage"]


def test_attributes_blockquote_to_nearest_h3_case() -> None:
    answer = (
        "### Brown v. Board of Education, U.S. Supreme Court, 1954 (347 U.S. 483)\n"
        "\n**Relevant passage:**\n"
        "> Separate educational facilities are inherently unequal.\n"
    )
    assert attribute_passages(answer) == [
        AttributedPassage(
            passage="Separate educational facilities are inherently unequal.",
            case_name="Brown v. Board of Education",
        )
    ]


def test_blockquote_with_no_preceding_h3_has_none_case_name() -> None:
    answer = "> some emphasis quote with no case heading above it\n"
    assert attribute_passages(answer) == [
        AttributedPassage(
            passage="some emphasis quote with no case heading above it", case_name=None
        )
    ]


def test_uses_nearest_preceding_h3_when_prose_separates() -> None:
    answer = (
        "### Palsgraf v. Long Island R.R., N.Y., 1928\n"
        "What was retrieved: the opinion discusses proximate cause.\n"
        "How this bears: relevant to foreseeability.\n"
        "> The risk reasonably to be perceived defines the duty to be obeyed.\n"
    )
    result = attribute_passages(answer)
    assert result == [
        AttributedPassage(
            passage="The risk reasonably to be perceived defines the duty to be obeyed.",
            case_name="Palsgraf v. Long Island R.R.",
        )
    ]


def test_case_name_is_text_before_first_comma() -> None:
    # The skill format is "### [Case Name], [Court], [Year] ([Citation])".
    answer = "### Roe v. Wade, U.S., 1973 (410 U.S. 113)\n> a passage\n"
    assert attribute_passages(answer)[0].case_name == "Roe v. Wade"


def test_non_h3_headings_do_not_attribute() -> None:
    # A "## Gaps and caveats" section (level-2) must not attribute its content.
    answer = "## Gaps and caveats\n> not a case passage\n"
    assert attribute_passages(answer) == [
        AttributedPassage(passage="not a case passage", case_name=None)
    ]


def test_later_h3_resets_attribution_for_subsequent_blockquote() -> None:
    answer = "### Case A, Court, 1990\n> passage one\n### Case B, Court, 1991\n> passage two\n"
    assert attribute_passages(answer) == [
        AttributedPassage(passage="passage one", case_name="Case A"),
        AttributedPassage(passage="passage two", case_name="Case B"),
    ]


def test_extract_blockquote_passages_still_returns_flat_list() -> None:
    answer = "### Case A, Court, 1990\n> alpha\n\nprose\n\n> beta\n"
    assert extract_blockquote_passages(answer) == ["alpha", "beta"]
