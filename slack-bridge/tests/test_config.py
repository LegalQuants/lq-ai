"""Tests for the slack-bridge Settings validator (DE-305).

The bridge env vars use the ``${VAR:-}`` (empty-default) form in
docker-compose.yml so a default ``docker compose up`` with the ``slack``
profile inactive does not abort at interpolation time. The
"required when the profile is active" guarantee moves into ``Settings``:
the bridge only constructs ``Settings`` when its container starts (profile
enabled), so an empty required credential must fail fast at startup.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

_VALID = {
    "slack_client_id": "cid",
    "slack_client_secret": "csecret",
    "slack_signing_secret": "ssecret",
    "lq_ai_backend_url": "http://api:8000",
    "lq_ai_bridge_token": "token",
    "lq_ai_bridge_public_url": "https://bridge.example.com",
}


def test_valid_settings_construct() -> None:
    settings = Settings(**_VALID)
    assert settings.slack_client_id == "cid"


@pytest.mark.parametrize(
    "field",
    [
        "slack_client_id",
        "slack_client_secret",
        "slack_signing_secret",
        "lq_ai_bridge_token",
        "lq_ai_bridge_public_url",
    ],
)
def test_empty_required_field_rejected(field: str) -> None:
    """An empty operator credential fails fast with a clear message."""

    bad = {**_VALID, field: ""}
    with pytest.raises(ValidationError) as exc:
        Settings(**bad)
    assert "required when the slack profile is enabled" in str(exc.value)


def test_whitespace_only_required_field_rejected() -> None:
    bad = {**_VALID, "slack_client_id": "   "}
    with pytest.raises(ValidationError) as exc:
        Settings(**bad)
    assert "slack_client_id is required when the slack profile is enabled" in str(exc.value)
