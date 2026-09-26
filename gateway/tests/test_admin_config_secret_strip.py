"""GET /admin/v1/config must not echo secret-shaped provider fields.

Pen-test 2026-09-25 finding gateway#F3a: ProviderConfig is extra="allow" and
load_config expands ${VAR} before validation, so the deprecated
`api_key: ${ANTHROPIC_API_KEY}` form (or any ${SECRET} in an extra field) left
the expanded plaintext in the admin-config payload. `_sanitized_config_payload`
now strips secret-shaped fields by name shape.
"""

from __future__ import annotations

import pytest

from app.api.admin import _is_secret_field, _sanitized_config_payload
from app.config import GatewayConfig


@pytest.mark.unit
def test_sanitized_payload_strips_plaintext_and_encrypted_keys() -> None:
    config = GatewayConfig.model_validate(
        {
            "providers": [
                {
                    "name": "anthropic-prod",
                    "type": "anthropic",
                    "base_url": "https://api.anthropic.com",
                    "api_key_env": "ANTHROPIC_API_KEY",
                    # Deprecated form: load_config would have expanded ${VAR} to
                    # the plaintext key here (extra="allow" keeps it).
                    "api_key": "sk-ant-super-secret-plaintext",
                    "aws_secret_access_key": "AKIA-shaped-secret",
                    "tier": 2,
                    "models": ["claude-x"],
                }
            ]
        }
    )

    payload = _sanitized_config_payload(config)
    provider = payload["providers"][0]

    # Secret-shaped fields are gone.
    assert "api_key" not in provider
    assert "aws_secret_access_key" not in provider
    # Safe fields remain.
    assert provider["name"] == "anthropic-prod"
    assert provider["api_key_env"] == "ANTHROPIC_API_KEY"
    assert provider["tier"] == 2

    # No secret plaintext anywhere in the serialized payload.
    import json

    assert "super-secret-plaintext" not in json.dumps(payload)
    assert "AKIA-shaped-secret" not in json.dumps(payload)


@pytest.mark.unit
def test_is_secret_field_classification() -> None:
    assert _is_secret_field("api_key")
    assert _is_secret_field("api_key_encrypted")
    assert _is_secret_field("aws_secret_access_key")
    assert _is_secret_field("auth_token")
    assert _is_secret_field("password")
    # api_key_env is a variable name, not a value — kept.
    assert not _is_secret_field("api_key_env")
    assert not _is_secret_field("name")
    assert not _is_secret_field("base_url")
    assert not _is_secret_field("tier")
