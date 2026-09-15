"""Unit tests for :mod:`app.providers.openai_schema`.

Covers ``ChatCompletionRequest`` field acceptance, ``model_dump`` round-trips,
and the explicit ``tools``/``tool_choice`` fields added in PR5b.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.providers.openai_schema import ChatCompletionRequest


@pytest.mark.unit
def test_chat_completion_request_accepts_tools_and_tool_choice() -> None:
    """PR5b: ``tools`` and ``tool_choice`` are explicit typed fields on
    :class:`ChatCompletionRequest`.  They must be accessible as attributes
    (not buried in ``model_extra``) and survive a ``model_dump`` round-trip."""

    req = ChatCompletionRequest(
        model="smart",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "verify_citations", "parameters": {}}}],
        tool_choice="auto",
    )
    assert req.tools is not None and req.tools[0]["function"]["name"] == "verify_citations"
    assert req.tool_choice == "auto"
    # Round-trips through model_dump (the OpenAI adapter serializes this).
    dumped = req.model_dump(mode="json", exclude_none=True)
    assert "tools" in dumped and "tool_choice" in dumped


def _tool_decl(i: int) -> dict:
    return {"type": "function", "function": {"name": f"tool_{i}", "parameters": {}}}


@pytest.mark.unit
def test_chat_completion_request_accepts_tools_at_cap() -> None:
    """DE-358 item 3: exactly 64 tool declarations are accepted."""

    req = ChatCompletionRequest(
        model="smart",
        messages=[{"role": "user", "content": "hi"}],
        tools=[_tool_decl(i) for i in range(64)],
    )
    assert req.tools is not None and len(req.tools) == 64


@pytest.mark.unit
def test_chat_completion_request_rejects_tools_over_cap() -> None:
    """DE-358 item 3: the 65th tool declaration fails validation (fail
    restrictive — the prompt-multiplication surface is bounded at 64)."""

    with pytest.raises(ValidationError):
        ChatCompletionRequest(
            model="smart",
            messages=[{"role": "user", "content": "hi"}],
            tools=[_tool_decl(i) for i in range(65)],
        )
