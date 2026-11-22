"""Regression cases from the live Qwen/nomic walkthrough; no live providers."""

from __future__ import annotations

import math
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.playbooks.easy.assembly import _ground_metadata
from app.playbooks.easy.clustering import ClauseInput, cluster_clauses_by_issue
from app.playbooks.easy.extractor import (
    ExtractedClause,
    ExtractedClauseSourceOffsets,
    ExtractionResponseError,
    _anchor_extracted_clauses,
    extract_clauses_from_document,
)
from app.playbooks.easy.source_anchor import anchor_quote, repair_context
from app.schemas.gateway import ChatCompletionChoice, ChatCompletionMessage, ChatCompletionResponse
from app.schemas.playbooks import FallbackTier, PositionCreate


@pytest.mark.unit
async def test_descriptions_are_prompted_from_the_selected_standard_only() -> None:
    from app.playbooks.easy.assembly import _describe_position
    from app.playbooks.easy.clustering import Cluster

    standard = ClauseInput(
        document_id=uuid.uuid4(), issue="Term", clause_text="The agreement expires after two years."
    )
    variant = ClauseInput(
        document_id=uuid.uuid4(),
        issue="Term",
        clause_text="The agreement expires after five years.",
    )
    gateway = AsyncMock()
    gateway.chat_completion.return_value = response({"description": "A two-year term."})
    await _describe_position(
        cluster=Cluster(
            issue_label="Term",
            member_clauses=[standard, variant],
            modal_clause=standard,
            neighbor_clauses=[variant],
        ),
        gateway=gateway,
        judge_model="smart",
        contract_type="NDA",
    )
    user_content = gateway.chat_completion.await_args.args[0].messages[1].content
    assert standard.clause_text in user_content
    assert variant.clause_text not in user_content


@pytest.mark.unit
async def test_even_a_positive_verdict_cannot_invert_expiry() -> None:
    source = "The obligations terminate upon expiration of the Term."
    position = PositionCreate(
        issue="Survival",
        standard_language=source,
        severity_if_missing="high",
        description="The obligations continue after expiry.",
    )
    gateway = AsyncMock()
    gateway.chat_completion.return_value = response(
        {
            "checks": [
                {
                    "id": "position/0",
                    "description_supported": True,
                    "redline_supported": True,
                    "source_quotes": [source],
                }
            ]
        }
    )
    await _ground_metadata([position], gateway=gateway, judge_model="smart")
    assert position.description == "Selected standard: " + source


@pytest.mark.unit
async def test_source_repair_transport_failure_is_not_silently_omitted() -> None:
    from types import SimpleNamespace

    doc = SimpleNamespace(id=uuid.uuid4(), normalized_content="The obligations expire.")
    gateway = AsyncMock()
    gateway.chat_completion.side_effect = [
        response(
            {"extracted_clauses": [{"issue": "Term", "clause_text": "The obligations survive."}]}
        ),
        ConnectionError("unavailable"),
    ]
    with pytest.raises(ExtractionResponseError, match="Source quotation repair failed"):
        await extract_clauses_from_document(document=doc, gateway=gateway)  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.parametrize("cosine", [1.0, 0.82])
@pytest.mark.parametrize(
    "labels",
    [
        ("Definition of Confidential Information", "Exclusions from Confidential Information"),
        ("Permitted Disclosures", "Compelled Disclosure"),
        ("Remedies", "Liability for Disclosees"),
        ("Governing Law", "Jurisdiction"),
        ("Term of Agreement", "Term of Confidentiality Obligation"),
        ("Unknown concession A", "Unknown concession B"),
    ],
)
async def test_distinct_issues_never_merge_or_fold(labels: tuple[str, str], cosine: float) -> None:
    clauses = [
        ClauseInput(document_id=uuid.uuid4(), issue=label, clause_text=f"Source {i}.")
        for i, label in enumerate([labels[0], labels[0], labels[1]])
    ]
    gateway = AsyncMock()
    gateway.embeddings.return_value = {
        "data": [
            {"index": i, "embedding": vector}
            for i, vector in enumerate(
                [[1.0, 0.0], [1.0, 0.0], [cosine, math.sqrt(1 - cosine * cosine)]]
            )
        ]
    }
    clusters = await cluster_clauses_by_issue(clauses=clauses, gateway=gateway)
    assert len(clusters) == 2
    assert all(len({c.issue for c in cluster.member_clauses}) == 1 for cluster in clusters)
    assert any(cluster.member_clauses == [clauses[2]] for cluster in clusters)


@pytest.mark.unit
def test_repair_context_preserves_both_survival_conditions_and_quoted_endings() -> None:
    source = 'Definition. "Information" means non-public information identified as "confidential." The obligations survive for trade secrets, and otherwise terminate upon expiry.'
    assert (
        anchor_quote(
            source, '"Information" means non-public information identified as "confidential."'
        )
        is not None
    )
    fragment = "and otherwise terminate upon expiry."
    assert anchor_quote(source, fragment) is None
    context = repair_context(source, fragment)
    assert (
        context == "The obligations survive for trade secrets, and otherwise terminate upon expiry."
    )
    assert anchor_quote(source, context) is not None


@pytest.mark.unit
def test_source_anchor_uses_exact_slice_and_rejects_stitching_and_lost_negation() -> None:
    source = "Header.\nThe Receiving Party shall not disclose the information.\n(a) Use reasonable\ncare; (b) use only for the Purpose; (c) encrypt data."
    match = anchor_quote(source, "Use reasonable care")
    assert match is not None
    assert match.text == "Use reasonable\ncare"
    assert source[match.start : match.end] == match.text
    assert anchor_quote(source, "disclose the information.") is None
    assert anchor_quote(source, "(a) Use reasonable care; and (c) encrypt data.") is None
    clause = ExtractedClause(
        issue="Standard of Care",
        clause_text="Use reasonable care",
        source_offsets=ExtractedClauseSourceOffsets(start=0, end=1),
    )
    accepted, rejected = _anchor_extracted_clauses([clause], source)
    assert not rejected
    assert accepted[0].source_offsets is not None
    assert (
        source[accepted[0].source_offsets.start : accepted[0].source_offsets.end]
        == accepted[0].clause_text
    )


def response(payload: dict[str, Any]) -> ChatCompletionResponse:
    import json

    return ChatCompletionResponse(
        id="test",
        created=0,
        model="test",
        choices=[
            ChatCompletionChoice(
                index=0,
                finish_reason="stop",
                message=ChatCompletionMessage(role="assistant", content=json.dumps(payload)),
            )
        ],
    )


@pytest.mark.unit
@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_stitched_quote_is_reextracted_or_generation_fails(repair_succeeds: bool) -> None:
    from types import SimpleNamespace

    source = "The Party agrees: (a) use care; (b) use only for the Purpose; (c) encrypt data."
    bad = {
        "extracted_clauses": [
            {
                "issue": "Standard of Care",
                "clause_text": "The Party agrees: (a) use care; and (c) encrypt data.",
            }
        ]
    }
    good = {"extracted_clauses": [{"issue": "Standard of Care", "clause_text": "(a) use care;"}]}
    gateway = AsyncMock()
    gateway.chat_completion.side_effect = [
        response(bad),
        response(good if repair_succeeds else bad),
    ]
    doc = SimpleNamespace(id=uuid.uuid4(), normalized_content=source)
    if repair_succeeds:
        result = await extract_clauses_from_document(document=doc, gateway=gateway)  # type: ignore[arg-type]
        assert len(result) == 1 and result[0].clause_text == "(a) use care;"
        assert result[0].source_offsets is not None
        assert (
            source[result[0].source_offsets.start : result[0].source_offsets.end]
            == result[0].clause_text
        )
    else:
        with pytest.raises(ExtractionResponseError, match="contiguous source quotations"):
            await extract_clauses_from_document(document=doc, gateway=gateway)  # type: ignore[arg-type]
    assert gateway.chat_completion.await_count == 2


@pytest.mark.unit
@pytest.mark.parametrize("verdict", [False, "true", True])
async def test_unverified_or_unanchored_description_cannot_invert_expiry(verdict: Any) -> None:
    standard = "The obligations terminate upon expiration of the Term."
    position = PositionCreate(
        issue="Survival",
        standard_language=standard,
        severity_if_missing="high",
        description="The obligations continue after expiration.",
        redline_strategy="Add five years.",
        fallback_tiers=[
            FallbackTier(
                rank=1,
                language="The obligations survive for one year.",
                description="An acceptable fallback.",
            )
        ],
    )
    gateway = AsyncMock()
    gateway.chat_completion.return_value = response(
        {
            "checks": [
                {
                    "id": "position/0",
                    "description_supported": verdict,
                    "redline_supported": False,
                    "source_quotes": ["invented evidence"],
                },
                {
                    "id": "tier/0/1",
                    "description_supported": True,
                    "source_quotes": [standard, "invented evidence"],
                },
            ]
        }
    )
    await _ground_metadata([position], gateway=gateway, judge_model="smart")
    assert position.description == "Selected standard: " + standard
    assert position.redline_strategy == "Review deviations against the selected standard language."
    assert (
        position.fallback_tiers[0].description
        == "Alternative source language: " + position.fallback_tiers[0].language
    )
