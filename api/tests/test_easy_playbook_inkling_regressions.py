"""Replay the actual Inkling prose, even against an affirmative model check."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.playbooks.easy.assembly import _ground_metadata
from app.playbooks.easy.source_facts import position_source_summary, unsupported_metadata
from app.schemas.gateway import ChatCompletionChoice, ChatCompletionMessage, ChatCompletionResponse
from app.schemas.playbooks import PositionCreate

CASES = json.loads(
    (Path(__file__).parent / "fixtures/easy_playbook/inkling_prose_regressions.json").read_text()
)["cases"]


@pytest.mark.unit
@pytest.mark.parametrize("case", CASES, ids=[c["issue"] for c in CASES])
async def test_captured_prose_cannot_survive_a_positive_consistency_verdict(case: dict) -> None:
    position = PositionCreate(**case, severity_if_missing="high")
    gateway = AsyncMock()
    gateway.chat_completion.return_value = ChatCompletionResponse(
        id="inkling-replay",
        model="smart",
        created=0,
        choices=[
            ChatCompletionChoice(
                index=0,
                finish_reason="stop",
                message=ChatCompletionMessage(
                    role="assistant",
                    content=json.dumps(
                        {
                            "checks": [
                                {
                                    "id": "position/0",
                                    "description_supported": True,
                                    "redline_supported": True,
                                    "source_quotes": [case["standard_language"]],
                                }
                            ]
                        }
                    ),
                ),
            )
        ],
    )
    await _ground_metadata([position], gateway=gateway, judge_model="smart")
    if case["issue"] == "Remedies":
        assert position.description.startswith("Selected standard:")
        assert "entitled to seek" in " ".join(position.description.split())
        assert (
            position.redline_strategy == "Review deviations against the selected standard language."
        )
    elif case["issue"] == "Survival of General Information":
        assert (
            position.description
            == "Obligations for general confidential information last for the agreement term."
        )
        assert "trade secret" not in position.description.casefold()
    else:
        assert "continues to qualify as a trade secret" in position.description
        assert "other Confidential Information" not in position.description
        assert (
            position.redline_strategy == "Review deviations against the selected standard language."
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "prose",
    [
        "The Disclosing Party is entitled to seek injunctive relief.",
        "Preserve the right to seek equitable relief.",
    ],
)
def test_accurate_seeking_language_is_not_rejected(prose: str) -> None:
    assert not unsupported_metadata("Remedies", [CASES[0]["standard_language"]], prose)


@pytest.mark.unit
def test_stronger_source_and_ambiguous_survival_are_not_rewritten() -> None:
    assert not unsupported_metadata(
        "Remedies",
        ["The Party is entitled to injunctive relief."],
        "The Party is entitled to injunctive relief.",
    )
    assert (
        position_source_summary(
            "Survival of Trade Secrets",
            "Obligations continue for five years while the information qualifies as a trade secret.",
        )
        is None
    )
    assert (
        position_source_summary(
            "Survival of General Information",
            "Obligations last for five years unless terminated earlier.",
        )
        is None
    )


@pytest.mark.unit
def test_ongoing_qualification_and_issue_scoped_strategy_are_preserved() -> None:
    text = "Trade-secret obligations continue for so long as the information continues to qualify as a trade secret."
    assert not unsupported_metadata(
        "Survival of Trade Secrets", [CASES[2]["standard_language"]], text
    )
    assert not unsupported_metadata(
        "Survival of General Information",
        [CASES[1]["standard_language"]],
        "Align general-information obligations with the agreement term.",
    )


@pytest.mark.unit
@pytest.mark.parametrize("spelling", ["trade-secret", "trade secret", "trade-secrets"])
async def test_hyphenated_trade_secret_instruction_is_removed_from_general_strategy(
    spelling: str,
) -> None:
    """The fresh live strategy bypassed the space-only scope guard."""
    position = PositionCreate(
        issue="Survival of General Information",
        standard_language=CASES[1]["standard_language"],
        description="Obligations for general confidential information last for the agreement term.",
        redline_strategy=f"If the contract caps survival at expiration, expand it to at least the 3-year {spelling} tail.",
        severity_if_missing="medium",
    )
    gateway = AsyncMock()
    gateway.chat_completion.return_value = ChatCompletionResponse(
        id="hyphenated-live-replay",
        model="smart",
        created=0,
        choices=[
            ChatCompletionChoice(
                index=0,
                finish_reason="stop",
                message=ChatCompletionMessage(
                    role="assistant",
                    content=json.dumps(
                        {
                            "checks": [
                                {
                                    "id": "position/0",
                                    "description_supported": True,
                                    "redline_supported": True,
                                    "source_quotes": [position.standard_language],
                                }
                            ]
                        }
                    ),
                ),
            )
        ],
    )
    await _ground_metadata([position], gateway=gateway, judge_model="smart")
    assert (
        position.description
        == "Obligations for general confidential information last for the agreement term."
    )
    assert position.redline_strategy == "Review deviations against the selected standard language."
