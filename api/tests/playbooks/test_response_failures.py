"""Unfinished/invalid model replies must never become successful absence findings."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.playbooks.nodes import (
    PlaybookResponseError,
    _dispatch_structured_call,
    make_classify_node,
    make_redline_node,
)


def reply(content: str, finish: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)]
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "content,finish",
    [
        ('{"verdict":"missing","confidence":"high","justification":"Absent."}', "length"),
        ('{"verdict":"missing"}', "content_filter"),
        ("", "stop"),
        ("{broken", "stop"),
        ("{}", "stop"),
        ("[]", "stop"),
    ],
)
async def test_unusable_response_raises_even_if_truncated_json_is_valid(
    content: str, finish: str
) -> None:
    gateway = AsyncMock()
    gateway.chat_completion.return_value = reply(content, finish)
    with pytest.raises(PlaybookResponseError):
        await _dispatch_structured_call(
            gateway=gateway, model="smart", messages=[], max_tokens=4096
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"verdict": "unknown"},
        {"verdict": "missing", "confidence": "high"},
        {"verdict": "missing", "confidence": [], "justification": "Absent."},
    ],
)
async def test_invalid_classification_returns_error_without_a_missing_row(bad: dict) -> None:
    gateway = AsyncMock()
    gateway.chat_completion.return_value = reply(json.dumps(bad))
    result = await make_classify_node(gateway=gateway, judge_model="smart")(
        {
            "positions": [
                {
                    "id": "p",
                    "issue": "Term",
                    "standard_language": "Two years.",
                    "severity_if_missing": "medium",
                }
            ],
        }
    )
    assert result["per_position_results"] == []
    assert "Unable to classify Term" in result["error"]
    assert await make_redline_node(gateway=gateway, judge_model="smart")(result) == {}


@pytest.mark.unit
async def test_explicit_complete_missing_is_preserved_and_executor_settings_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.playbooks.nodes.get_settings",
        lambda: Settings(
            lq_ai_playbook_classify_max_tokens=6144, lq_ai_playbook_executor_reasoning_effort="none"
        ),
    )
    gateway = AsyncMock()
    gateway.chat_completion.return_value = reply(
        json.dumps(
            {
                "verdict": "missing",
                "confidence": "high",
                "justification": "The supplied contract contains no assignment clause.",
            }
        )
    )
    result = await make_classify_node(gateway=gateway, judge_model="smart")(
        {
            "positions": [
                {
                    "id": "p",
                    "issue": "Assignment",
                    "standard_language": "Consent required.",
                    "severity_if_missing": "medium",
                }
            ],
        }
    )
    assert not result.get("error")
    assert result["per_position_results"][0]["verdict"] == "missing"
    request = gateway.chat_completion.call_args.args[0]
    assert request.max_tokens == 6144
    assert request.reasoning_effort == "none"


@pytest.mark.unit
async def test_truncated_redline_cannot_publish_a_partial_suggestion() -> None:
    gateway = AsyncMock()
    gateway.chat_completion.return_value = reply(
        '{"old_text":"one","new_text":"two","justification":"Align term."}', "length"
    )
    state = {
        "positions": [{"id": "p", "issue": "Term", "standard_language": "Two years."}],
        "per_position_results": [
            {
                "position_id": "p",
                "issue": "Term",
                "verdict": "deviates",
                "matched_text": "One year.",
            }
        ],
    }
    result = await make_redline_node(gateway=gateway, judge_model="smart")(state)
    assert "Unable to draft redline for Term" in result["error"]
    assert "per_position_results" not in result


@pytest.mark.unit
async def test_failure_preserves_prior_complete_results_and_stops_remaining_positions() -> None:
    gateway = AsyncMock()
    complete = {
        "verdict": "missing",
        "confidence": "high",
        "justification": "No assignment clause appears.",
    }
    gateway.chat_completion.side_effect = [
        reply(json.dumps(complete)),
        reply(json.dumps(complete), "length"),
    ]
    positions = [
        {
            "id": str(i),
            "issue": issue,
            "standard_language": "Consent required.",
            "severity_if_missing": "medium",
        }
        for i, issue in enumerate(("Assignment", "Affiliate", "Term"))
    ]
    result = await make_classify_node(gateway=gateway, judge_model="smart")(
        {"positions": positions}
    )
    assert [r["issue"] for r in result["per_position_results"]] == ["Assignment"]
    assert "Unable to classify Affiliate" in result["error"]
    assert gateway.chat_completion.call_count == 2
