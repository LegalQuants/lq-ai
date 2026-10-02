"""Tests for the LLM provider base_url egress guard (#288, GW-04).

The prompt-carrying LLM path must not send cleartext to a public host or use
a non-http(s) scheme, mirroring the hardened tool-egress path. `https` is
always allowed; `http` only to an explicitly allowlisted local host
(`_LOCAL_HOSTS`) or an IP inside `_LOCAL_NETWORKS`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import status

from app.config import ProviderConfig
from app.errors import CODE_PROVIDER_UNAVAILABLE, LQAIError
from app.main import build_adapter
from app.providers.base_url_policy import ProviderEgressRefused, validate_llm_base_url

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "https://api.anthropic.com",
        "https://api.openai.com/v1",
        "https://us-central1-aiplatform.googleapis.com",
        "http://ollama:11434",  # compose service name
        "http://vllm:8000/v1",
        "http://host.docker.internal:11434",  # .env.example's default OLLAMA_BASE_URL
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
        "http://169.254.169.254/latest/meta-data/",  # link-local cloud metadata
        "http://nginx:8080",  # single-label name that is not an allowlisted local provider
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


@pytest.mark.unit
async def test_lifespan_refuses_to_start_on_refused_base_url(
    example_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An egress-policy violation is FATAL at startup, never a silent skip.

    Regression guard for the deliberate design call on this PR: if
    ``ProviderEgressRefused`` were ever swallowed by the lifespan's
    ``except ValueError`` skip path (e.g. by a refactor re-basing the
    exception), the router would fall through to the next candidate in the
    chain and silently send prompts somewhere the operator did not choose.
    This reproduces the operator story: a mistyped ``OLLAMA_BASE_URL``.
    """

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://attacker.example/v1")
    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(EXAMPLE_CONFIG))

    from app.main import app

    with pytest.raises(ProviderEgressRefused):
        async with app.router.lifespan_context(app):
            pass  # pragma: no cover — startup must raise before entry


@pytest.mark.unit
def test_provider_egress_refused_is_typed_lqai_error() -> None:
    """Regression guard for the LQAIError derivation (CONTRIBUTING: subsystem
    errors are typed, never bare ``Exception``). A refusal that reaches a
    request path must render the canonical envelope with the existing
    ``provider_unavailable`` code and a 503 — not an unhandled 500. Narrowing
    the class back to bare ``Exception`` fails here before it 500s live.
    """

    exc = ProviderEgressRefused("cleartext egress to attacker.example")
    assert isinstance(exc, LQAIError)
    assert exc.reason == "cleartext egress to attacker.example"
    assert exc.effective_code == CODE_PROVIDER_UNAVAILABLE
    assert exc.effective_http_status == status.HTTP_503_SERVICE_UNAVAILABLE
    assert exc.to_envelope()["error"]["code"] == CODE_PROVIDER_UNAVAILABLE
