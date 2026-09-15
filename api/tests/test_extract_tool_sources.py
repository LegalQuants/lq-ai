"""Unit tests for extract_tool_sources logic (no DB required)."""

from app.chat.tool_loop import (
    collect_tool_sources,
    extract_mcp_tool_source,
    extract_tool_sources,
)
from app.chat.tool_schemas import ToolSpec


def test_extract_from_search_case_law() -> None:
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


def test_extract_from_get_cluster() -> None:
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


def test_extract_non_research_and_empty() -> None:
    assert extract_tool_sources("read_opinion", {"opinion_id": 1}) == []
    assert extract_tool_sources("find_in_case", {"matches": []}) == []
    assert extract_tool_sources("some_mcp_tool", {"payload": {}}) == []
    assert extract_tool_sources("search_case_law", {"results": []}) == []
    assert extract_tool_sources("search_case_law", None) == []


def _spec(kind: str, provider: str, tool: str) -> ToolSpec:
    return ToolSpec(
        function_name=f"{provider}__{tool}",
        kind=kind,  # type: ignore[arg-type]
        provider=provider,
        tool=tool,
        read_only=True,
        destructive=False,
        requires_confirmation=False,
        parameters={},
    )


def test_mcp_source_from_dict_payload_with_title_and_url() -> None:
    spec = _spec("mcp", "deepwiki", "ask_question")
    data = {"title": "Repo answer", "url": "https://example.com/x", "body": "..."}
    rec = extract_mcp_tool_source(spec, data)
    assert rec is not None
    assert rec.source_kind == "mcp"
    assert rec.provider == "deepwiki"
    assert rec.tool == "ask_question"
    assert rec.label == "Repo answer"
    assert rec.url == "https://example.com/x"
    assert rec.external_ref is None


def test_mcp_source_from_text_blocks_falls_back_to_descriptor() -> None:
    spec = _spec("mcp", "deepwiki", "ask_question")
    data = [{"type": "text", "text": "some answer"}, {"type": "text", "text": "more"}]
    rec = extract_mcp_tool_source(spec, data)
    assert rec is not None
    assert rec.label == "deepwiki · ask_question"
    assert rec.url is None


def test_mcp_source_from_dict_block_inside_list_surfaces_url() -> None:
    spec = _spec("mcp", "srv", "search")
    data = [{"type": "text", "text": "intro"}, {"name": "Result One", "link": "https://e/1"}]
    rec = extract_mcp_tool_source(spec, data)
    assert rec is not None
    assert rec.label == "Result One"
    assert rec.url == "https://e/1"


def test_mcp_source_malformed_payload_never_crashes() -> None:
    spec = _spec("mcp", "srv", "t")
    for data in (None, "a bare string", [1, 2, 3], {"url": 5}):  # url=5 is not a str -> ignored
        rec = extract_mcp_tool_source(spec, data)
        assert rec is not None
        assert rec.label == "srv · t"
        assert rec.url is None


def test_extract_mcp_returns_none_for_non_mcp_spec() -> None:
    assert extract_mcp_tool_source(_spec("research", "courtlistener", "get_cluster"), {}) is None


def test_collect_routes_mcp_to_one_record() -> None:
    recs = collect_tool_sources(_spec("mcp", "srv", "t"), {"title": "T"})
    assert len(recs) == 1
    assert recs[0].source_kind == "mcp"


def test_collect_routes_research_caselaw_to_existing_path() -> None:
    data = {
        "cluster": {
            "cluster_id": 7,
            "case_name": "X v. Y",
            "court": "ca9",
            "date_filed": "2001-05-05",
            "absolute_url": "https://www.courtlistener.com/opinion/7/",
        }
    }
    recs = collect_tool_sources(_spec("research", "courtlistener", "get_cluster"), data)
    assert len(recs) == 1
    assert recs[0].source_kind == "caselaw"
    assert recs[0].external_ref == "7"


def test_collect_research_non_caselaw_tool_yields_no_rows() -> None:
    assert (
        collect_tool_sources(_spec("research", "courtlistener", "read_opinion"), {"text": "..."})
        == []
    )
