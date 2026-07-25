from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult
from app.autonomous.planner import collect_evidence, summarize_observation


def test_caselaw_observation_includes_cluster_id() -> None:
    result = ToolResult(
        data={
            "results": [
                {
                    "case_name": "Smith v. Jones",
                    "court": "ca9",
                    "date_filed": "2021-01-01",
                    "cluster_id": 42,
                },
            ]
        },
        outcome="success",
    )
    s = summarize_observation(ToolIntent.retrieve_caselaw, "find authority", result)
    assert "Smith v. Jones" in s
    assert "42" in s  # cluster_id is shown so the synthesis can cite it


def test_collect_evidence_numbers_kb_chunks() -> None:
    result = ToolResult(
        data={
            "chunks": [
                {
                    "chunk_id": "c1",
                    "file_name": "nda.pdf",
                    "content": "Confidential Information clause text.",
                },
                {"chunk_id": "c2", "file_name": "nda.pdf", "content": "Term clause text."},
            ]
        },
        outcome="success",
    )
    items = collect_evidence(ToolIntent.retrieve_chunks, result, start_n=1)
    assert [i.n for i in items] == [1, 2]
    assert items[0].kind == "kb" and items[0].ref == "c1"
    assert items[0].content == "Confidential Information clause text."


def test_collect_evidence_numbers_caselaw() -> None:
    result = ToolResult(
        data={
            "results": [
                {
                    "case_name": "Smith v. Jones",
                    "cluster_id": 42,
                    "opinion_text": "It is held that...",
                },
            ]
        },
        outcome="success",
    )
    items = collect_evidence(ToolIntent.retrieve_caselaw, result, start_n=5)
    assert items[0].n == 5 and items[0].kind == "caselaw" and items[0].ref == "42"
    assert "held" in items[0].content


def test_collect_evidence_empty_on_failure() -> None:
    assert (
        collect_evidence(ToolIntent.retrieve_caselaw, ToolResult(data=None, outcome="error"), 1)
        == []
    )
