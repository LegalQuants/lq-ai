"""Unit tests for extract_tool_sources logic (no DB required)."""

from app.chat.tool_loop import extract_tool_sources


def test_extract_from_search_case_law():
    data = {
        "count": 1,
        "results": [
            {
                "cluster_id": 42,
                "case_name": "Roe v. Wade",
                "court": "scotus",
                "date_filed": "1973-01-22",
                "absolute_url": "/opinion/42/",
                "snippet": "…",
            }
        ],
    }
    recs = extract_tool_sources("search_case_law", data)
    assert len(recs) == 1
    r = recs[0]
    assert r.source_kind == "caselaw"
    assert r.label == "Roe v. Wade"
    assert r.subtitle == "scotus · 1973-01-22"
    assert r.url == "https://www.courtlistener.com/opinion/42/"  # absolutized
    assert r.external_ref == "42"
    assert r.provider == "courtlistener"
    assert r.tool == "search_case_law"


def test_extract_from_get_cluster():
    data = {
        "cluster": {
            "cluster_id": 7,
            "case_name": "X v. Y",
            "court": "ca9",
            "date_filed": "2001-05-05",
            "absolute_url": "https://www.courtlistener.com/opinion/7/",
        },
        "opinions": [],
    }
    recs = extract_tool_sources("get_cluster", data)
    assert len(recs) == 1
    assert recs[0].label == "X v. Y"
    assert recs[0].external_ref == "7"
    assert recs[0].url == "https://www.courtlistener.com/opinion/7/"  # already absolute → unchanged


def test_extract_non_research_and_empty():
    assert extract_tool_sources("read_opinion", {"opinion_id": 1}) == []
    assert extract_tool_sources("find_in_case", {"matches": []}) == []
    assert extract_tool_sources("some_mcp_tool", {"payload": {}}) == []
    assert extract_tool_sources("search_case_law", {"results": []}) == []
    assert extract_tool_sources("search_case_law", None) == []
