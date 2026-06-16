"""Tests for the per-provider ``use_max_completion_tokens`` flag.

GPT-5 / o-series reasoning deployments reject ``max_tokens`` (hard 400) and
require ``max_completion_tokens``. The gateway gates the rename per-provider
(not by model name) so OpenAI-compatible local servers — which may reject the
unknown field (vLLM < 0.6.4) or silently drop it (LM Studio / Ollama / TGI) —
keep receiving ``max_tokens`` by default.

What these tests pin:

* When the flag is on, ``_to_openai_request`` renames ``max_tokens`` to
  ``max_completion_tokens`` AND drops ``max_tokens`` entirely (its mere
  presence re-triggers the 400 on reasoning models).
* When off (the default), ``max_tokens`` is left untouched.
* Both the OpenAI and Azure adapters read the flag from ``ProviderConfig``.
"""

from __future__ import annotations

import pytest

from app.config import ProviderConfig
from app.providers.azure_openai import AzureOpenAIAdapter
from app.providers.openai import OpenAIAdapter, _to_openai_request
from app.providers.openai_schema import ChatCompletionMessage, ChatCompletionRequest


def _request(max_tokens: int | None = 256) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="gpt-5",
        messages=[ChatCompletionMessage(role="user", content="hi")],
        max_tokens=max_tokens,
    )


# --- _to_openai_request body translation ------------------------------------


@pytest.mark.unit
def test_flag_on_renames_max_tokens_and_drops_original() -> None:
    body = _to_openai_request(
        _request(256), model="gpt-5", stream=False, use_max_completion_tokens=True
    )
    assert body["max_completion_tokens"] == 256
    assert "max_tokens" not in body  # presence alone re-triggers the 400


@pytest.mark.unit
def test_flag_off_keeps_max_tokens() -> None:
    body = _to_openai_request(
        _request(256), model="gpt-4o", stream=False, use_max_completion_tokens=False
    )
    assert body["max_tokens"] == 256
    assert "max_completion_tokens" not in body


@pytest.mark.unit
def test_flag_defaults_off() -> None:
    body = _to_openai_request(_request(256), model="gpt-4o", stream=False)
    assert body["max_tokens"] == 256
    assert "max_completion_tokens" not in body


@pytest.mark.unit
def test_flag_on_without_max_tokens_adds_nothing() -> None:
    # max_tokens omitted by the caller (dropped via exclude_none); the flag
    # must not invent a budget.
    body = _to_openai_request(
        _request(None), model="gpt-5", stream=False, use_max_completion_tokens=True
    )
    assert "max_tokens" not in body
    assert "max_completion_tokens" not in body


# --- ProviderConfig + adapter wiring ----------------------------------------


@pytest.mark.unit
def test_provider_config_flag_defaults_false() -> None:
    cfg = ProviderConfig.model_validate(
        {
            "name": "openai-prod",
            "type": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY_TEST",
            "tier": 4,
            "models": ["gpt-5"],
        }
    )
    assert cfg.use_max_completion_tokens is False


@pytest.mark.unit
def test_openai_adapter_reads_flag_from_config() -> None:
    cfg = ProviderConfig.model_validate(
        {
            "name": "openai-prod",
            "type": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY_TEST",
            "tier": 4,
            "models": ["gpt-5"],
            "use_max_completion_tokens": True,
        }
    )
    adapter = OpenAIAdapter.from_config(cfg, env={"OPENAI_API_KEY_TEST": "sk-test"})
    assert adapter._use_max_completion_tokens is True


@pytest.mark.unit
def test_azure_adapter_reads_flag_from_config() -> None:
    cfg = ProviderConfig.model_validate(
        {
            "name": "azure-openai",
            "type": "azure_openai",
            "base_url": "https://res.openai.azure.com",
            "api_key_env": "AZURE_OPENAI_API_KEY_TEST",
            "api_version": "2024-10-21",
            "tier": 3,
            "models": ["gpt-5-prod"],
            "use_max_completion_tokens": True,
        }
    )
    adapter = AzureOpenAIAdapter.from_config(cfg, env={"AZURE_OPENAI_API_KEY_TEST": "az-test"})
    assert adapter._use_max_completion_tokens is True
