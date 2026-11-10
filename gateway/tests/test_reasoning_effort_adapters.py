"""What each adapter does with ``reasoning_effort``.

The field is OpenAI's own. The OpenAI adapter sends it as it is, and so does
the Azure OpenAI adapter, which builds its body with the same function. The
Ollama adapter maps it to ``think`` (see ``test_ollama_tool_calls.py``). The
Anthropic adapter builds its body field by field and sends nothing for it.
Unset, no adapter sends anything, so a caller that never sets it is unaffected.
"""

from __future__ import annotations

import pytest

from app.providers.anthropic import _to_anthropic_request
from app.providers.openai import _to_openai_request
from app.providers.openai_schema import ChatCompletionMessage, ChatCompletionRequest


def _request(effort: str | None) -> ChatCompletionRequest:
    return ChatCompletionRequest.model_validate(
        {
            "model": "pinned",
            "messages": [ChatCompletionMessage(role="user", content="hi")],
            "reasoning_effort": effort,
        }
    )


@pytest.mark.unit
@pytest.mark.parametrize("effort", ["none", "minimal", "low", "medium", "high"])
def test_the_openai_body_carries_the_effort_as_given(effort: str) -> None:
    # Azure OpenAI builds its body with this same function.
    body = _to_openai_request(_request(effort), model="gpt-5", stream=False)
    assert body["reasoning_effort"] == effort


@pytest.mark.unit
def test_the_openai_body_has_no_effort_when_none_was_set() -> None:
    body = _to_openai_request(_request(None), model="gpt-5", stream=False)
    assert "reasoning_effort" not in body


@pytest.mark.unit
@pytest.mark.parametrize("effort", [None, "none", "low", "high"])
def test_the_anthropic_body_never_carries_an_effort(effort: str | None) -> None:
    body = _to_anthropic_request(_request(effort), model="claude", stream=False)
    assert "reasoning_effort" not in body
    assert "thinking" not in body


@pytest.mark.unit
def test_a_value_outside_the_vocabulary_is_refused_before_any_adapter() -> None:
    with pytest.raises(ValueError):
        _request("extreme")
