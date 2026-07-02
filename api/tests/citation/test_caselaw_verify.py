import pytest

from app.citation.caselaw import (
    _CaselawCandidate,
    locate_passage,
    opinion_target,
)
from app.citation.verification import verify

OPINION = "Before the quote. The implied covenant of good faith applies here. After."


def test_locate_passage_found():
    loc = locate_passage("The implied covenant of good faith applies here.", OPINION)
    assert loc is not None
    start, end = loc
    assert OPINION[start:end] == "The implied covenant of good faith applies here."


def test_locate_passage_absent_returns_none():
    assert locate_passage("a sentence that is not in the opinion", OPINION) is None


@pytest.mark.asyncio
async def test_verify_exact_match_against_opinion():
    passage = "The implied covenant of good faith applies here."
    start, end = locate_passage(passage, OPINION)
    target = opinion_target(opinion_id=777, text=OPINION)
    candidate = _CaselawCandidate(
        source_offset_start=start,
        source_offset_end=end,
        source_text=passage,
        source_document_id=target.id,
    )
    result = await verify(candidate, target, gateway=None)
    assert result.verified is True
    assert result.method == "exact_match"


@pytest.mark.asyncio
async def test_invented_quote_not_verified():
    target = opinion_target(opinion_id=777, text=OPINION)
    candidate = _CaselawCandidate(
        source_offset_start=0,
        source_offset_end=5,
        source_text="WRONG",  # opinion[0:5] == "Befor", not "WRONG"
        source_document_id=target.id,
    )
    result = await verify(candidate, target, gateway=None)
    assert result.verified is False
