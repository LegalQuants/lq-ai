"""Replay exact Qwen response wrappers and the repeated connected-list failure."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.models.document import Document
from app.playbooks.easy.extractor import (
    ExtractionResponseError,
    _parse_extracted_clauses,
    extract_clauses_from_document,
)
from app.playbooks.easy.json_output import unwrap_json_answer
from app.playbooks.easy.source_anchor import complete_connected_item
from app.schemas.gateway import ChatCompletionChoice, ChatCompletionMessage, ChatCompletionResponse

CAPTURE = json.loads(
    (Path(__file__).parent / "fixtures/easy_playbook/compatibility_regressions.json").read_text()
)


@pytest.mark.unit
@pytest.mark.parametrize("key", ["duplicate_fences", "prose_then_bare_json"])
def test_captured_wrapper_preserves_every_clause_without_rewriting(key: str) -> None:
    answer = CAPTURE[key]
    expected = json.loads(unwrap_json_answer(answer))["extracted_clauses"]
    clauses = _parse_extracted_clauses(answer, strict=True)
    assert len(clauses) >= 15
    assert [c.clause_text for c in clauses] == [c["clause_text"] for c in expected]


@pytest.mark.unit
@pytest.mark.parametrize(
    "answer",
    [
        'Before\n{"extracted_clauses": []}\n{"extracted_clauses": []}',
        'Before\n{"extracted_clauses": []}\nAfter the answer.',
        'Before ```json\n{"extracted_clauses": []}\n``` and ```json\n{"extracted_clauses": [{"issue": "Term", "clause_text": "Two years."}]}\n```',
        'Before\n{"extracted_clauses": [BROKEN]}',
        '{"extracted_clauses": [{"issue": "Term"}]}',
    ],
)
def test_invalid_or_conflicting_answers_cannot_silently_omit_a_document(answer: str) -> None:
    with pytest.raises(ExtractionResponseError):
        _parse_extracted_clauses(answer, strict=True)


@pytest.mark.unit
def test_valid_empty_answer_remains_distinct_from_failed_extraction() -> None:
    assert _parse_extracted_clauses('{"extracted_clauses": []}', strict=True) == []


def response(content: str) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="captured-compatibility",
        model="smart",
        created=0,
        choices=[
            ChatCompletionChoice(
                index=0,
                finish_reason="stop",
                message=ChatCompletionMessage(role="assistant", content=content),
            )
        ],
    )


@pytest.mark.unit
async def test_repeated_dangling_list_repair_uses_verified_complete_source_context() -> None:
    source = CAPTURE["connected_item_source"]
    gateway = AsyncMock()
    gateway.chat_completion.side_effect = [
        response(CAPTURE["connected_item_extraction"]),
        response(CAPTURE["connected_item_repair"]),
    ]
    clauses = await extract_clauses_from_document(
        document=Document(id=uuid.uuid4(), normalized_content=source),
        gateway=gateway,
    )
    assert len(clauses) == 16
    assert gateway.chat_completion.await_count == 2
    trade = next(c for c in clauses if c.issue == "Survival of Trade Secrets")
    assert "(b)" in trade.clause_text and "two (2) years" in trade.clause_text
    assert not trade.clause_text.rstrip().endswith("; and")
    for clause in clauses:
        assert clause.source_offsets is not None
        assert source[clause.source_offsets.start : clause.source_offsets.end] == clause.clause_text


@pytest.mark.unit
@pytest.mark.parametrize(
    "source,quote",
    [
        (
            "The Party shall: (a) use care; (b) encrypt data.",
            "(a) use care; and (c) encrypt data; and",
        ),
        ("The Party shall: (a) use care; and", "(a) use care; and"),
        ("The Party shall not disclose data.", "disclose data."),
    ],
)
def test_connected_item_fallback_cannot_repair_invented_or_unfinished_source(
    source: str, quote: str
) -> None:
    assert complete_connected_item(source, quote) is None
