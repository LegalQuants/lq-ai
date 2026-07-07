"""Tests for the LLM provider base_url egress guard (#288, GW-04).

The prompt-carrying LLM path must not send cleartext to a public host or use
a non-http(s) scheme, mirroring the hardened tool-egress path. `https` is
always allowed; `http` only to a local host (Ollama/vLLM).
"""

from __future__ import annotations

import pytest

from app.config import ProviderConfig
from app.main import build_adapter
from app.providers.base_url_policy import ProviderEgressRefused, validate_llm_base_url


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "https://api.anthropic.com",
        "https://api.openai.com/v1",
        "https://us-central1-aiplatform.googleapis.com",
        "http://ollama:11434",  # compose service name
        "http://vllm:8000/v1",
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://[::1]:11434",
        "http://10.0.0.5:8000",  # private
    ],
)
def test_accepts_valid_targets(url: str) -> None:
    validate_llm_base_url(url)  # does not raise


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "http://api.openai.com/v1",  # plaintext to a public host
        "http://attacker.example/v1",
        "http://8.8.8.8/v1",  # plaintext to a public IP
        "ftp://api.openai.com",  # unsupported scheme
        "file:///etc/passwd",
        "https://",  # no host
    ],
)
def test_rejects_bad_targets(url: str) -> None:
    with pytest.raises(ProviderEgressRefused):
        validate_llm_base_url(url)


@pytest.mark.unit
def test_build_adapter_rejects_plaintext_public_base_url() -> None:
    """build_adapter fails fast when a provider is configured to send prompts
    in cleartext to a public host."""
    provider = ProviderConfig.model_validate(
        {
            "name": "evil",
            "type": "ollama",  # ollama needs no API key, so build reaches the guard
            "base_url": "http://attacker.example/v1",
            "tier": 1,
        }
    )
    with pytest.raises(ProviderEgressRefused):
        build_adapter(provider)


@pytest.mark.unit
def test_build_adapter_allows_local_ollama() -> None:
    """A normal local Ollama config over http builds without complaint."""
    provider = ProviderConfig.model_validate(
        {
            "name": "ollama-local",
            "type": "ollama",
            "base_url": "http://ollama:11434",
            "tier": 1,
        }
    )
    adapter = build_adapter(provider)
    assert adapter is not None
