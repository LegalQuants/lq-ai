from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult
from app.autonomous.planner import summarize_observation


def test_caselaw_summary_lists_case_names_not_full_text() -> None:
    result = ToolResult(
        data={
            "results": [
                {
                    "case_name": "Smith v. Jones",
                    "court": "ca9",
                    "date_filed": "2021-01-01",
                    "opinion_text": "X" * 5000,
                },
                {"case_name": "Doe v. Roe", "court": "ca2", "date_filed": "2019-06-01"},
            ]
        },
        outcome="success",
    )
    s = summarize_observation(ToolIntent.retrieve_caselaw, "find authority", result)
    assert "Smith v. Jones" in s and "Doe v. Roe" in s
    assert "XXXX" not in s  # no full opinion text
    assert len(s) < 400


def test_chunks_summary_counts_and_files() -> None:
    result = ToolResult(
        data={
            "chunks": [
                {"chunk_id": "c1", "file_name": "nda.pdf", "content": "Y" * 4000},
                {"chunk_id": "c2", "file_name": "nda.pdf", "content": "Z" * 4000},
            ]
        },
        outcome="success",
    )
    s = summarize_observation(ToolIntent.retrieve_chunks, "read clause", result)
    assert "2" in s and "nda.pdf" in s
    assert "YYYY" not in s


def test_failed_result_is_summarized_not_raised() -> None:
    result = ToolResult(data=None, outcome="gateway_error")
    s = summarize_observation(ToolIntent.retrieve_caselaw, "x", result)
    assert "failed" in s and "gateway_error" in s


def test_mcp_tool_summary_emits_keys_not_values() -> None:
    result = ToolResult(
        data={"status": "ok", "citation": "X" * 500, "tool": "courtlistener"},
        outcome="success",
    )
    s = summarize_observation(ToolIntent.call_mcp_tool, "fetch", result)
    assert "citation" in s and "status" in s and "tool" in s
    assert "XXXX" not in s  # P3: keys only, never values


def test_caselaw_summary_caps_at_five_and_notes_more() -> None:
    result = ToolResult(
        data={
            "results": [
                {"case_name": f"Case {i}", "court": "ca9", "date_filed": "2021-01-01"}
                for i in range(8)
            ]
        },
        outcome="success",
    )
    s = summarize_observation(ToolIntent.retrieve_caselaw, "x", result)
    assert "+3 more" in s  # 8 results, 5 shown
    assert "Case 0" in s and "Case 7" not in s  # only first 5 listed
