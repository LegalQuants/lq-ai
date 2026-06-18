"""Model + migration test for research metadata tables — WS3b.

Verifies that ``research_cluster_metadata`` and ``research_opinion_metadata``
rows persist and read back with their core fields intact after the 0049
migration runs.

Tests run against the same SAVEPOINT-rolled-back per-test session as
the rest of the API tests (per ``tests/conftest.py``).

Also covers schema-layer typing added in WS3b-follow (Donna asks 2 & 3):
- VerifiedCitation / CitationCluster round-trips the adapter's exact emitted shape.
- OpinionTextField Literal accepts all 7 values (incl xml_harvard) and is used
  on OpinionMeta and OpinionText.

And cursor pagination (Donna ask — Slice A "load more"):
- SearchRequest accepts an optional cursor field and flows it through model_dump.
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from app.models.research import ResearchClusterMetadata, ResearchOpinionMetadata
from app.schemas.research import (
    CitationCluster,
    OpinionMeta,
    OpinionText,
    OpinionTextField,
    SearchRequest,
    VerifiedCitation,
    VerifyCitationsResponse,
)


async def test_research_metadata_roundtrips(db_session) -> None:
    cluster = ResearchClusterMetadata(
        cluster_id=2812209,
        case_name="Obergefell v. Hodges",
        court="scotus",
        date_filed="2015-06-26",
        absolute_url="/opinion/2812209/",
    )
    db_session.add(cluster)
    await db_session.flush()
    op = ResearchOpinionMetadata(
        opinion_id=3247759,
        cluster_id=2812209,
        text_field_used="html_with_citations",
        storage_path="courtlistener/opinions/by-cluster/2812209/3247759",
        char_length=1234,
    )
    db_session.add(op)
    await db_session.flush()
    assert op.opinion_id == 3247759
    assert cluster.case_name == "Obergefell v. Hodges"


# ---------------------------------------------------------------------------
# VerifiedCitation / CitationCluster schema typing (Donna ask #2)
# ---------------------------------------------------------------------------


def test_verified_citation_roundtrips_adapter_shape() -> None:
    """VerifyCitationsResponse coerces the adapter's exact emitted dict shape."""
    adapter_item = {
        "citation": "576 U.S. 644",
        "normalized_citations": ["576 U.S. 644"],
        "status": 200,
        "error_message": None,
        "clusters": [
            {
                "id": 2812209,
                "case_name": "Obergefell v. Hodges",
                "absolute_url": "/opinion/2812209/",
            }
        ],
    }
    resp = VerifyCitationsResponse(citations=[adapter_item])
    assert len(resp.citations) == 1
    vc = resp.citations[0]
    assert isinstance(vc, VerifiedCitation)
    assert vc.citation == "576 U.S. 644"
    assert vc.normalized_citations == ["576 U.S. 644"]
    assert vc.status == 200
    assert vc.error_message is None
    assert len(vc.clusters) == 1
    cl = vc.clusters[0]
    assert isinstance(cl, CitationCluster)
    assert cl.id == 2812209
    assert cl.case_name == "Obergefell v. Hodges"
    assert cl.absolute_url == "/opinion/2812209/"


def test_verified_citation_not_found_item() -> None:
    """404 / error_message item with empty clusters is accepted."""
    adapter_item = {
        "citation": "999 F.3d 999",
        "normalized_citations": [],
        "status": 404,
        "error_message": "not found",
        "clusters": [],
    }
    resp = VerifyCitationsResponse(citations=[adapter_item])
    vc = resp.citations[0]
    assert vc.status == 404
    assert vc.error_message == "not found"
    assert vc.clusters == []


def test_verified_citation_none_fields_accepted() -> None:
    """Fields that can be None (citation, status, id) accept None defensively."""
    adapter_item = {
        "citation": None,
        "normalized_citations": [],
        "status": None,
        "error_message": None,
        "clusters": [{"id": None, "case_name": None, "absolute_url": None}],
    }
    resp = VerifyCitationsResponse(citations=[adapter_item])
    vc = resp.citations[0]
    assert vc.citation is None
    assert vc.status is None
    assert vc.clusters[0].id is None


def test_verify_citations_response_empty_default() -> None:
    """VerifyCitationsResponse defaults to an empty list."""
    resp = VerifyCitationsResponse()
    assert resp.citations == []


# ---------------------------------------------------------------------------
# OpinionTextField Literal (Donna ask #3)
# ---------------------------------------------------------------------------

_ALL_TEXT_FIELDS = list(get_args(OpinionTextField))


@pytest.mark.parametrize("field", _ALL_TEXT_FIELDS)
def test_opinion_meta_accepts_all_text_fields(field: str) -> None:
    """OpinionMeta validates all 7 OpinionTextField values incl xml_harvard."""
    meta = OpinionMeta(opinion_id=1, char_length=100, text_field_used=field)
    assert meta.text_field_used == field


@pytest.mark.parametrize("field", _ALL_TEXT_FIELDS)
def test_opinion_text_accepts_all_text_fields(field: str) -> None:
    """OpinionText validates all 7 OpinionTextField values incl xml_harvard."""
    ot = OpinionText(opinion_id=1, cluster_id=2, text_field_used=field, text="Sample text.")
    assert ot.text_field_used == field


def test_opinion_meta_text_field_used_none() -> None:
    """text_field_used=None is valid on OpinionMeta."""
    meta = OpinionMeta(opinion_id=1, char_length=0, text_field_used=None)
    assert meta.text_field_used is None


def test_opinion_text_text_field_used_none() -> None:
    """text_field_used=None is valid on OpinionText."""
    ot = OpinionText(opinion_id=1, cluster_id=2, text_field_used=None, text="x")
    assert ot.text_field_used is None


def test_opinion_meta_rejects_invalid_text_field() -> None:
    """OpinionMeta rejects values outside the closed Literal set."""
    with pytest.raises(ValidationError):
        OpinionMeta(opinion_id=1, char_length=0, text_field_used="raw_text")


def test_opinion_text_rejects_invalid_text_field() -> None:
    """OpinionText rejects values outside the closed Literal set."""
    with pytest.raises(ValidationError):
        OpinionText(opinion_id=1, cluster_id=2, text_field_used="raw_text", text="x")


# ---------------------------------------------------------------------------
# SearchRequest cursor pagination (Donna ask — Slice A "load more")
# ---------------------------------------------------------------------------


def test_search_request_accepts_cursor() -> None:
    """SearchRequest accepts a cursor and exposes it on the model."""
    req = SearchRequest(q="privacy", cursor="abc")
    assert req.cursor == "abc"


def test_search_request_cursor_in_model_dump_when_set() -> None:
    """model_dump(exclude_none=True) includes cursor when it is set."""
    req = SearchRequest(q="privacy", cursor="abc")
    dumped = req.model_dump(exclude_none=True)
    assert dumped["cursor"] == "abc"
    assert dumped["q"] == "privacy"


def test_search_request_cursor_omitted_from_model_dump_when_none() -> None:
    """model_dump(exclude_none=True) omits cursor when it is None (default)."""
    req = SearchRequest(q="privacy")
    dumped = req.model_dump(exclude_none=True)
    assert "cursor" not in dumped


def test_search_request_cursor_default_none() -> None:
    """cursor defaults to None when not supplied."""
    req = SearchRequest(q="contract")
    assert req.cursor is None


def test_search_request_rejects_extra_field() -> None:
    """extra='forbid' is preserved — unknown fields still raise."""
    with pytest.raises(ValidationError):
        SearchRequest(q="x", unknown_field="y")
