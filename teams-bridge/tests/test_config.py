"""Tests for the teams-bridge Settings validator (DE-305).

The bridge env vars use the ``${VAR:-}`` (empty-default) form in
docker-compose.yml so a default ``docker compose up`` with the ``teams``
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
    "microsoft_app_id": "app-id",
    "microsoft_app_password": "app-password",
    "lq_ai_backend_url": "http://api:8000",
    "lq_ai_bridge_token": "token",
    "lq_ai_teams_bridge_public_url": "https://teams-bridge.example.com",
}


def test_valid_settings_construct() -> None:
    settings = Settings(**_VALID)
    assert settings.microsoft_app_id == "app-id"


@pytest.mark.parametrize(
    "field",
    [
        "microsoft_app_id",
        "microsoft_app_password",
        "lq_ai_bridge_token",
        "lq_ai_teams_bridge_public_url",
    ],
)
def test_empty_required_field_rejected(field: str) -> None:
    """An empty operator credential fails fast with a clear message."""

    bad = {**_VALID, field: ""}
    with pytest.raises(ValidationError) as exc:
        Settings(**bad)
    assert "required when the teams profile is enabled" in str(exc.value)


def test_whitespace_only_required_field_rejected() -> None:
    bad = {**_VALID, "microsoft_app_id": "   "}
    with pytest.raises(ValidationError) as exc:
        Settings(**bad)
    assert "microsoft_app_id is required when the teams profile is enabled" in str(exc.value)
