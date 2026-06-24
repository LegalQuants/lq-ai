from app.citation.caselaw import extract_blockquote_passages


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
