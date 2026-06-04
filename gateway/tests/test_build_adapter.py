"""Tests for :func:`app.main.build_adapter` — the reusable adapter builder.

``build_adapter`` is the single source of truth for "which adapter does
this provider get", extracted from the lifespan so the runtime BYOK
hot-apply path (Donna #7, Task B) can reuse it. These tests pin its
contract directly; the heavier behavior-preservation guarantee (the
exact set of adapters built for the example config) is covered by the
full gateway suite running the real lifespan.
"""

from __future__ import annotations

import pytest

from app.config import ProviderConfig
from app.main import build_adapter
from app.providers import AnthropicAdapter, OllamaAdapter, OpenAIAdapter


@pytest.mark.unit
def test_build_adapter_returns_anthropic_for_keyed_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    provider = ProviderConfig(
        name="anthropic-prod",
        type="anthropic",
        base_url="https://api.anthropic.com",
        api_key_env="ANTHROPIC_API_KEY",
        tier=4,
    )
    adapter = build_adapter(provider)
    assert isinstance(adapter, AnthropicAdapter)


@pytest.mark.unit
def test_build_adapter_handles_openai_compatible_without_key() -> None:
    # openai_compatible local servers legitimately have no key.
    provider = ProviderConfig(
        name="vllm-local",
        type="openai_compatible",
        base_url="http://vllm:8000/v1",
        api_key_env="",
        tier=1,
    )
    adapter = build_adapter(provider)
    assert isinstance(adapter, OpenAIAdapter)


@pytest.mark.unit
def test_build_adapter_returns_ollama() -> None:
    provider = ProviderConfig(
        name="ollama-local",
        type="ollama",
        base_url="http://ollama:11434",
        api_key_env="",
        tier=1,
    )
    adapter = build_adapter(provider)
    assert isinstance(adapter, OllamaAdapter)


@pytest.mark.unit
def test_build_adapter_returns_none_for_disabled_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    provider = ProviderConfig(
        name="anthropic-prod",
        type="anthropic",
        base_url="https://api.anthropic.com",
        api_key_env="ANTHROPIC_API_KEY",
        tier=4,
        enabled=False,
    )
    assert build_adapter(provider) is None


@pytest.mark.unit
def test_build_adapter_returns_none_for_typeless_adapter() -> None:
    # vertex/bedrock have no adapter yet (awaiting B6) → None, not raise.
    provider = ProviderConfig(
        name="bedrock",
        type="bedrock",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
        tier=3,
    )
    assert build_adapter(provider) is None


@pytest.mark.unit
def test_build_adapter_raises_value_error_for_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Supported provider whose key can't be resolved → ValueError
    # (the signal the factories raise; the lifespan catches+skips).
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LQ_AI_GATEWAY_MASTER_KEY", raising=False)
    provider = ProviderConfig(
        name="anthropic-prod",
        type="anthropic",
        base_url="https://api.anthropic.com",
        api_key_env="ANTHROPIC_API_KEY",
        tier=4,
    )
    with pytest.raises(ValueError):
        build_adapter(provider)
