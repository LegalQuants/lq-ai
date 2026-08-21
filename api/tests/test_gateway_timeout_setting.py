"""`LQ_AI_GATEWAY_TIMEOUT_SECONDS` — the deployment-wide gateway timeout.

Before this setting existed, `DEFAULT_TIMEOUT_SECONDS = 60.0` was a module
constant with no override path. 60s is fine against a hosted provider and far
too short for a self-hosted deployment running a local model on modest
hardware, where a single long generation can exceed ten minutes. Operators
were patching the constant inside the running image — a change lost on every
container recreate, and one that silently reverts a deployment to a timeout
that surfaces as a fake "upstream error" with no hint that a timeout caused it.

The default stays 60.0, so this changes nothing for anyone who does not set it.
"""

from __future__ import annotations

import pytest

from app.clients.gateway import (
    DEFAULT_TIMEOUT_SECONDS,
    GatewayClient,
    get_gateway_client,
    set_gateway_client,
)
from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_client():
    set_gateway_client(None)
    get_settings.cache_clear()
    yield
    set_gateway_client(None)
    get_settings.cache_clear()


def test_default_is_unchanged() -> None:
    """A deployment that sets nothing keeps the previous behaviour."""
    assert Settings().lq_ai_gateway_timeout_seconds == DEFAULT_TIMEOUT_SECONDS == 60.0


def test_setting_reaches_the_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LQ_AI_GATEWAY_TIMEOUT_SECONDS", "1800")
    get_settings.cache_clear()

    client = get_gateway_client()
    # httpx stores the per-request timeout on the client; the connect/read/write
    # legs all inherit the scalar we passed.
    assert client.http_client.timeout.read == pytest.approx(1800.0)
    assert client.http_client.timeout.connect == pytest.approx(1800.0)


def test_explicit_construction_still_wins() -> None:
    client = GatewayClient(base_url="http://gw", gateway_key="k", timeout=12.5)
    assert client.http_client.timeout.read == pytest.approx(12.5)


def test_non_positive_timeout_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A zero or negative timeout would make every gateway call fail instantly;
    fail at startup with a legible error instead."""
    monkeypatch.setenv("LQ_AI_GATEWAY_TIMEOUT_SECONDS", "0")
    with pytest.raises(Exception):
        Settings()
