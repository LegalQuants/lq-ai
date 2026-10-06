import json
from types import SimpleNamespace

import pytest

from app.citation.treatment_judge import (
    TREATMENT_CLASSES,
    TreatmentJudgment,
    build_treatment_judge_prompt,
    judge_treatment,
    parse_treatment_response,
)
from app.schemas.gateway import ChatCompletionRequest


def _resp(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_prompt_includes_case_and_snippet() -> None:
    msgs = build_treatment_judge_prompt(
        cited_case_name="Smith v. Jones", snippet="We overrule Smith."
    )
    assert msgs[0].role == "system" and msgs[1].role == "user"
    assert msgs[1].content is not None
    assert "Smith v. Jones" in msgs[1].content and "We overrule Smith." in msgs[1].content


@pytest.mark.parametrize("cls", TREATMENT_CLASSES)
def test_parse_accepts_every_class(cls: str) -> None:
    out = parse_treatment_response(
        _resp(json.dumps({"treatment": cls, "confidence": "high", "justification": "x"}))
    )
    assert out == TreatmentJudgment(classification=cls, confidence=0.90, justification="x")


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        json.dumps({"treatment": "bogus", "confidence": "high", "justification": "x"}),
        json.dumps({"treatment": "overruled", "confidence": "??", "justification": "x"}),
        json.dumps({"confidence": "high", "justification": "x"}),  # missing treatment
        json.dumps(["overruled"]),  # not a dict
        "",
        json.dumps(
            {"treatment": "followed", "confidence": "high", "justification": "   "}
        ),  # whitespace-only
        json.dumps({"treatment": "followed", "confidence": "high"}),  # missing justification
    ],
)
def test_parse_returns_none_on_garbage(bad: str) -> None:
    assert parse_treatment_response(_resp(bad)) is None


def test_parse_none_on_no_choices() -> None:
    assert parse_treatment_response(SimpleNamespace(choices=[])) is None


@pytest.mark.asyncio
async def test_judge_treatment_swallows_gateway_error() -> None:
    class Boom:
        async def chat_completion(
            self, request: ChatCompletionRequest, *, request_id: str | None = None
        ) -> SimpleNamespace:
            raise RuntimeError("down")

    assert (
        await judge_treatment(cited_case_name="X", snippet="y", gateway=Boom(), judge_model="fast")
        is None
    )


@pytest.mark.asyncio
async def test_judge_treatment_tags_purpose_and_parses() -> None:
    seen: dict[str, object] = {}

    class GW:
        async def chat_completion(
            self, request: ChatCompletionRequest, *, request_id: str | None = None
        ) -> SimpleNamespace:
            seen["purpose"] = request.lq_ai_purpose
            seen["anonymize"] = request.anonymize
            seen["temperature"] = request.temperature
            seen["max_tokens"] = request.max_tokens
            return _resp(
                json.dumps(
                    {
                        "treatment": "questioned",
                        "confidence": "medium",
                        "justification": "doubted it",
                    }
                )
            )

    out = await judge_treatment(cited_case_name="X", snippet="y", gateway=GW(), judge_model="fast")
    assert out == TreatmentJudgment("questioned", 0.70, "doubted it")
    assert seen["purpose"] == "judge_treatment" and seen["anonymize"] is False
    assert seen["temperature"] == 0.0
    assert seen["max_tokens"] == 400
