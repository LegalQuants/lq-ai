"""Pure tests for the keyword query the playbook retrieve node sends to Postgres FTS.

``websearch_to_tsquery`` ANDs space-separated words, so joining a position's
``detection_keywords`` with spaces demanded that one passage contain *every*
keyword. The helper joins them with ``or`` instead (multi-word keywords as quoted
phrases) so a passage with any keyword is a candidate and ``ts_rank_cd`` ranks
the ones that contain more of them higher.
"""

from __future__ import annotations

import pytest

from app.playbooks.nodes import _keywords_to_tsquery


def test_single_keyword_is_unchanged() -> None:
    assert _keywords_to_tsquery(["term"]) == "term"


def test_keywords_are_joined_with_or_not_space() -> None:
    assert _keywords_to_tsquery(["term", "duration", "expiry"]) == "term or duration or expiry"


def test_multi_word_keywords_become_quoted_phrases() -> None:
    assert (
        _keywords_to_tsquery(["term", "survival period", "expiry"])
        == 'term or "survival period" or expiry'
    )


def test_blank_and_whitespace_only_keywords_are_dropped() -> None:
    assert _keywords_to_tsquery(["term", "", "   ", "expiry"]) == "term or expiry"


def test_all_blank_keywords_give_an_empty_query() -> None:
    assert _keywords_to_tsquery(["", "  "]) == ""


def test_internal_whitespace_is_collapsed() -> None:
    assert _keywords_to_tsquery(["governing   law"]) == '"governing law"'


def test_embedded_double_quotes_cannot_break_out_of_a_phrase() -> None:
    assert _keywords_to_tsquery(['say "hi" there']) == '"say hi there"'


@pytest.mark.parametrize(
    ("keyword", "expected"),
    [
        ("-confidential", "confidential"),  # websearch syntax: a leading '-' would negate
        ("--term", "term"),
        ("or", '"or"'),  # a bare 'or' would be read as the operator
        ("OR", '"OR"'),
    ],
)
def test_websearch_operators_in_keywords_are_neutralised(keyword: str, expected: str) -> None:
    assert _keywords_to_tsquery([keyword]) == expected


def test_keyword_that_is_only_dashes_is_dropped() -> None:
    assert _keywords_to_tsquery(["---", "term"]) == "term"
