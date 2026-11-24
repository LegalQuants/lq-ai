"""Replay the missed comparisons and protect unrelated drafting behavior."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.models.document import Document
from app.playbooks.easy.assembly import _describe_tier, _ground_metadata
from app.playbooks.easy.clustering import ClauseInput, cluster_clauses_by_issue
from app.playbooks.easy.extractor import extract_clauses_from_document
from app.playbooks.easy.source_facts import (
    source_issue,
    tier_comparison,
    unsupported_court_type,
    unsupported_metadata,
)
from app.schemas.gateway import ChatCompletionChoice, ChatCompletionMessage, ChatCompletionResponse
from app.schemas.playbooks import FallbackTier, PositionCreate

CASES = json.loads(
    (Path(__file__).parent / "fixtures/easy_playbook/semantic_regressions.json").read_text()
)["cases"]


def response(value: dict[str, Any]) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="source-facts",
        model="smart",
        created=0,
        choices=[
            ChatCompletionChoice(
                index=0,
                finish_reason="stop",
                message=ChatCompletionMessage(role="assistant", content=json.dumps(value)),
            )
        ],
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "case", CASES[1:], ids=[c["kind"] + str(i) for i, c in enumerate(CASES[1:])]
)
@pytest.mark.parametrize("verdict", [True, False])
async def test_captured_bad_comparison_cannot_survive_a_model_verdict(
    case: dict[str, Any], verdict: bool
) -> None:
    position = PositionCreate(
        issue=case["issue"],
        standard_language=case["standard"],
        description="Review the selected standard.",
        severity_if_missing="medium",
        fallback_tiers=[
            FallbackTier(
                rank=1, language=case["alternative"], description=case["generated_description"]
            )
        ],
    )
    gateway = AsyncMock()
    gateway.chat_completion.return_value = response(
        {
            "checks": [
                {
                    "id": "tier/0/1",
                    "description_supported": verdict,
                    "source_quotes": [case["standard"], case["alternative"]],
                }
            ]
        }
    )
    await _ground_metadata([position], gateway=gateway, judge_model="smart")
    description = position.fallback_tiers[0].description
    assert description != case["generated_description"]
    assert not description.startswith("Alternative source language:")
    if case["kind"] == "reversed_comparison":
        assert "the Receiving Party in the alternative" in description
        assert "both parties in the standard" in description
    elif case["kind"] == "reversed_survival_direction":
        assert "adds two years" in description
        assert "standard limits that protection to the agreement term" in description
    else:
        assert description.startswith("Agreement term:")
        assert "Confidentiality term" not in description
        assert "four years in the standard" in description


@pytest.mark.unit
async def test_security_source_is_preserved_as_a_separate_group_even_with_identical_vectors() -> (
    None
):
    case = CASES[0]
    clauses = [
        ClauseInput(document_id=uuid.uuid4(), issue=case["issue"], clause_text=text)
        for text in [case["standard"], case["standard"], case["alternative"]]
    ]
    gateway = AsyncMock()
    gateway.embeddings.return_value = {
        "data": [{"index": i, "embedding": [1.0, 0.0]} for i in range(3)]
    }
    clusters = await cluster_clauses_by_issue(clauses=clauses, gateway=gateway)
    assert len(clusters) == 2
    security = next(c for c in clusters if c.issue_label == "Security Safeguards")
    assert security.modal_clause.clause_text == case["alternative"]
    assert all(
        c.clause_text == case["standard"]
        for c in next(c for c in clusters if c.issue_label == case["issue"]).member_clauses
    )
    assert clauses[2].issue == case["issue"]  # caller-owned input is unchanged


@pytest.mark.unit
async def test_extractor_relabels_security_without_changing_quote_or_coordinates() -> None:
    case = CASES[0]
    source = case["alternative"]
    gateway = AsyncMock()
    gateway.chat_completion.return_value = response(
        {"extracted_clauses": [{"issue": case["issue"], "clause_text": source}]}
    )
    clauses = await extract_clauses_from_document(
        document=Document(id=uuid.uuid4(), normalized_content=source), gateway=gateway
    )
    assert len(clauses) == 1 and clauses[0].issue == "Security Safeguards"
    assert clauses[0].clause_text == source
    assert clauses[0].source_offsets is not None
    assert source[clauses[0].source_offsets.start : clauses[0].source_offsets.end] == source


@pytest.mark.unit
@pytest.mark.parametrize(
    "label,text,expected",
    [
        (
            "Restriction on Disclosure",
            "The Party shall not disclose data and shall use encryption.",
            "Non-Disclosure and Security Safeguards",
        ),
        (
            "Restriction on Disclosure",
            "The Party may disclose data only to employees and shall use encryption.",
            "Non-Disclosure and Security Safeguards",
        ),
        (
            "Standard of Care",
            "Use reasonable care, including encryption and access controls.",
            "Standard of Care",
        ),
        (
            "Restriction on Disclosure",
            "The Party shall not disclose information.",
            "Restriction on Disclosure",
        ),
        ("Unknown negotiated issue", "Use encryption.", "Unknown negotiated issue"),
    ],
)
def test_security_guard_preserves_combined_clauses_care_and_unknown_issues(
    label: str, text: str, expected: str
) -> None:
    assert source_issue(label, text) == expected


@pytest.mark.unit
def test_period_comparisons_handle_reverse_and_conditional_cases() -> None:
    during = "The obligations terminate upon expiration of the Agreement."
    after = "The obligations continue for two (2) years following expiration."
    assert "limits protection" in (
        tier_comparison("Survival of General Information", after, during) or ""
    )
    assert "two years in the alternative versus five years" in (
        tier_comparison(
            "Survival of General Information", after.replace("two (2)", "five (5)"), after
        )
        or ""
    )
    standard = "This Agreement shall remain in effect for four (4) years."
    assert (
        tier_comparison(
            "Term",
            standard,
            "This Agreement shall continue in effect for two years and renew for one year.",
        )
        is None
    )
    assert (
        tier_comparison("Term", standard, "The Agreement may terminate on thirty days notice.")
        is None
    )
    assert (
        tier_comparison(
            "Term", standard, "This Agreement shall remain in effect for two (3) years."
        )
        is None
    )
    assert (
        tier_comparison(
            "Survival of General Information",
            during,
            after + " Unless the parties agree otherwise.",
        )
        is None
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "period",
    ["1.5", "1/2", "twenty-one", "twenty one", "at least two", "up to two", "0", "two (3)"],
)
def test_ambiguous_or_unsupported_duration_uses_normal_drafting(period: str) -> None:
    assert (
        tier_comparison(
            "Term",
            "This Agreement shall remain in effect for four years.",
            f"This Agreement shall remain in effect for {period} years.",
        )
        is None
    )


@pytest.mark.unit
def test_conditional_acknowledgement_uses_normal_drafting() -> None:
    assert (
        tier_comparison(
            "Remedies",
            "The Parties acknowledge irreparable harm.",
            "The Receiving Party acknowledges irreparable harm if misuse occurs.",
        )
        is None
    )


@pytest.mark.unit
async def test_issue_and_source_direction_reach_the_tier_writer() -> None:
    case = CASES[-1]
    gateway = AsyncMock()
    gateway.chat_completion.return_value = response(
        {"description": "An agreement-duration difference."}
    )
    await _describe_tier(
        modal_text=case["standard"],
        tier_text=case["alternative"],
        issue_label=case["issue"],
        gateway=gateway,
        judge_model="smart",
        contract_type="NDA",
    )
    request = gateway.chat_completion.await_args.args[0]
    assert "ISSUE: Term of Agreement" in request.messages[1].content
    assert (
        "two years in the alternative, compared with four years in the standard"
        in request.messages[1].content
    )


@pytest.mark.unit
async def test_other_supported_generated_descriptions_are_kept() -> None:
    standard = "Use the information only for the Purpose."
    alternative = "Use the information only for the Purpose and do not commercially exploit it."
    description = "The alternative adds an express prohibition on commercial exploitation."
    position = PositionCreate(
        issue="Permitted Use",
        standard_language=standard,
        description="Purpose-limited use.",
        severity_if_missing="medium",
        fallback_tiers=[FallbackTier(rank=1, language=alternative, description=description)],
    )
    gateway = AsyncMock()
    gateway.chat_completion.return_value = response(
        {
            "checks": [
                {
                    "id": "tier/0/1",
                    "description_supported": True,
                    "source_quotes": [standard, alternative],
                }
            ]
        }
    )
    await _ground_metadata([position], gateway=gateway, judge_model="smart")
    assert position.fallback_tiers[0].description == description
    assert not unsupported_court_type(
        ["State and federal courts", "Court of Chancery"], "Chancery replaces general state courts."
    )
    assert unsupported_court_type(
        ["State and federal courts", "Court of Chancery"], "Excludes state district courts."
    )


@pytest.mark.unit
async def test_invented_court_type_is_rejected_even_when_model_approves() -> None:
    standard = "The state and federal courts located in Delaware have exclusive jurisdiction."
    alternative = "The Court of Chancery of Delaware has exclusive jurisdiction."
    position = PositionCreate(
        issue="Jurisdiction",
        standard_language=standard,
        description="Delaware courts.",
        severity_if_missing="medium",
        fallback_tiers=[
            FallbackTier(
                rank=1,
                language=alternative,
                description="The alternative excludes state district courts.",
            )
        ],
    )
    gateway = AsyncMock()
    gateway.chat_completion.return_value = response(
        {
            "checks": [
                {
                    "id": "tier/0/1",
                    "description_supported": True,
                    "source_quotes": [standard, alternative],
                }
            ]
        }
    )
    await _ground_metadata([position], gateway=gateway, judge_model="smart")
    assert "district" not in position.fallback_tiers[0].description
    assert alternative in position.fallback_tiers[0].description


METADATA_CASES = json.loads(
    (Path(__file__).parent / "fixtures/easy_playbook/metadata_regressions.json").read_text()
)["cases"]


@pytest.mark.unit
@pytest.mark.parametrize("case", METADATA_CASES, ids=[c["issue"] for c in METADATA_CASES])
async def test_new_captured_wording_defects_cannot_survive_positive_verdict(
    case: dict[str, Any],
) -> None:
    is_tier = case["field"] == "tier_description"
    position = PositionCreate(
        issue=case["issue"],
        standard_language=case["standard"],
        description="Review the selected standard.",
        severity_if_missing="medium",
        redline_strategy=case["generated_prose"] if not is_tier else "Review deviations.",
        fallback_tiers=[
            FallbackTier(rank=1, language=case["alternative"], description=case["generated_prose"])
        ]
        if is_tier
        else [],
    )
    sources = [case["standard"], case["alternative"]] if is_tier else [case["standard"]]
    gateway = AsyncMock()
    gateway.chat_completion.return_value = response(
        {
            "checks": [
                {
                    "id": "tier/0/1" if is_tier else "position/0",
                    "description_supported": True,
                    "redline_supported": True,
                    "source_quotes": sources,
                }
            ]
        }
    )
    await _ground_metadata([position], gateway=gateway, judge_model="smart")
    if is_tier:
        assert (
            position.fallback_tiers[0].description
            == "Alternative source language: " + case["alternative"]
        )
    else:
        assert (
            position.redline_strategy == "Review deviations against the selected standard language."
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "issue,sources,prose",
    [
        (
            "No License",
            ["No license is granted.", "Nothing grants the Receiving Party rights."],
            "Both sources grant no license; the alternative expressly names the Receiving Party.",
        ),
        (
            "No License",
            [
                "The license grant is limited to internal use.",
                "The license grant permits internal use only.",
            ],
            "The alternative limits the license grant to internal use.",
        ),
        (
            "Standard of Care",
            ["Use reasonable care consistent with industry practice."],
            "Use an industry standard of care.",
        ),
        (
            "Standard of Care",
            [
                "Use at least the care used for its own information and no less than reasonable care."
            ],
            "The alternative omits the own-information care benchmark.",
        ),
        (
            "Jurisdiction",
            [
                "The Parties consent to Chancery (or, if such court lacks subject-matter jurisdiction, the federal courts located in Delaware)."
            ],
            "Chancery has priority; federal courts apply only if it lacks subject-matter jurisdiction.",
        ),
        (
            "Exclusions from Confidential Information",
            ["Exclude information that is independently developed."],
            "Preserve the independent-development exclusion.",
        ),
    ],
)
def test_new_guards_keep_supported_wording(issue: str, sources: list[str], prose: str) -> None:
    assert not unsupported_metadata(issue, sources, prose)
