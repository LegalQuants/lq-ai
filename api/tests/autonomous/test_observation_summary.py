from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult
from app.autonomous.planner import summarize_observation


def test_caselaw_summary_lists_case_names_not_full_text():
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


def test_chunks_summary_counts_and_files():
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


def test_failed_result_is_summarized_not_raised():
    result = ToolResult(data=None, outcome="gateway_error")
    s = summarize_observation(ToolIntent.retrieve_caselaw, "x", result)
    assert "failed" in s and "gateway_error" in s
