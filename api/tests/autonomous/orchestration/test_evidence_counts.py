"""ADR 0038 D5: what the citation checks could and could not see in an answer.

The checks see a quotation only when it carries ``(Source: [N])`` for a
selected document. These counts tell the owner about the rest, so that "every
checked quotation matched" is never read as "every quotation matched".
"""

from app.autonomous.orchestration.evidence import (
    MAX_CHECKED_QUOTATIONS,
    MIN_QUOTATION_CHARS,
    quotation_counts,
)

SELECTED = {1, 2}


def counts(content: str) -> tuple[int, int, int]:
    found = quotation_counts(content, SELECTED)
    return found["marked"], found["unresolved"], found["unmarked"]


def test_marked_quotations_for_selected_documents_leave_nothing_unseen() -> None:
    answer = (
        'Fees are due "within thirty (30) days of the invoice date" (Source: [1]). '
        "Notice is due “without undue delay and within 48 hours” (Source: [2])."
    )
    assert counts(answer) == (2, 0, 0)


def test_a_quoted_passage_without_a_marker_is_counted_as_unmarked() -> None:
    answer = (
        'The relevant clause is [§2]:\n\n> "The Customer shall pay the Supplier a fee of GBP 4,500 '
        'per month, invoiced monthly in advance."\n\n[§2]\n\n'
        'Renewal: "The agreement then renews for successive 12 month terms." (Source: [1])'
    )
    assert counts(answer) == (1, 0, 1)


def test_a_curly_quoted_passage_without_a_marker_is_counted_too() -> None:
    answer = "It says “the Supplier may suspend the service on seven days notice” in clause 9."
    assert counts(answer) == (0, 0, 1)


def test_a_passage_quoted_across_lines_is_one_passage() -> None:
    answer = '> "Either party may terminate this agreement\n> immediately by written notice."\n'
    assert counts(answer) == (0, 0, 1)


def test_a_short_quoted_term_is_not_a_quotation() -> None:
    term = "Confidential Info"
    assert len(term) < MIN_QUOTATION_CHARS
    assert counts(f'"{term}" means what clause 1 says, and "Fees" are defined in clause 2.') == (
        0,
        0,
        0,
    )


def test_a_short_marked_quotation_does_not_disturb_the_pairing_of_the_next() -> None:
    answer = (
        'Payment is due in "30 days" (Source: [1]), and it adds '
        '"interest accrues daily on any overdue amount" with no marker.'
    )
    assert counts(answer) == (1, 0, 1)


def test_a_marker_for_a_document_outside_the_selection_is_unresolved() -> None:
    answer = (
        '"within thirty (30) days of the invoice date" (Source: [1]) and '
        '"something from a document nobody selected" (Source: [9]).'
    )
    assert counts(answer) == (2, 1, 0)


def test_quotations_past_the_checking_cap_are_unresolved() -> None:
    answer = " ".join(
        f'"quotation number {index} of the long answer text" (Source: [1])'
        for index in range(MAX_CHECKED_QUOTATIONS + 3)
    )
    assert counts(answer) == (MAX_CHECKED_QUOTATIONS + 3, 3, 0)


def test_an_answer_with_no_quoted_text_counts_nothing() -> None:
    assert counts("Fees are due in thirty days. Breach notice is due in 72 hours.") == (0, 0, 0)
    assert counts("") == (0, 0, 0)


def test_a_stray_quotation_mark_never_raises() -> None:
    answer = 'A stray " mark, then "a properly quoted passage of some length" (Source: [1]).'
    marked, unresolved, _ = counts(answer)
    assert (marked, unresolved) == (1, 0)
