"""Tests for `app.config.Settings`.

Per CLAUDE.md, decisions are explicit: the backend reads its configuration
from environment variables (and a `.env` file) via pydantic-settings. These
tests pin that behaviour: required-feeling fields *load* from env, defaults
apply when env is absent, and the `lru_cache`-backed accessor reflects
re-reads after a cache clear.
"""

from __future__ import annotations

import pytest

from app.config import Settings, get_settings


@pytest.mark.unit
def test_defaults_apply_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings constructs cleanly with no overrides — defaults are usable."""
    # Wipe out any inherited values so we exercise the defaults.
    for var in (
        "DATABASE_URL",
        "REDIS_URL",
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "S3_BUCKET",
        "S3_REGION",
        "LQ_AI_GATEWAY_URL",
        "LQ_AI_GATEWAY_KEY",
        "JWT_SECRET",
        "JWT_ACCESS_TOKEN_TTL_SECONDS",
        "JWT_REFRESH_TOKEN_TTL_SECONDS",
        "LOG_LEVEL",
        "LQ_AI_DEV_MODE",
    ):
        monkeypatch.delenv(var, raising=False)

    s = Settings(_env_file=None)  # type: ignore[call-arg]

    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.redis_url.startswith("redis://")
    assert s.s3_bucket == "lq-ai-files"
    assert s.s3_region == "us-east-1"
    assert s.jwt_access_token_ttl_seconds == 900
    assert s.jwt_refresh_token_ttl_seconds == 604800
    assert s.log_level == "info"
    assert s.lq_ai_dev_mode is False


@pytest.mark.unit
def test_overrides_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each declared field reads from its corresponding env var."""
    env = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/d",
        "REDIS_URL": "redis://r:6379/3",
        "S3_ENDPOINT_URL": "https://s3.example.com",
        "S3_ACCESS_KEY": "AK",
        "S3_SECRET_KEY": "SK",
        "S3_BUCKET": "custom-bucket",
        "S3_REGION": "us-west-2",
        "LQ_AI_GATEWAY_URL": "http://gw:9999",
        "LQ_AI_GATEWAY_KEY": "gw-key",
        "JWT_SECRET": "jwt-secret",
        "JWT_ACCESS_TOKEN_TTL_SECONDS": "120",
        "JWT_REFRESH_TOKEN_TTL_SECONDS": "240",
        "LOG_LEVEL": "debug",
        "LQ_AI_DEV_MODE": "true",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    s = Settings(_env_file=None)  # type: ignore[call-arg]

    assert s.database_url == env["DATABASE_URL"]
    assert s.redis_url == env["REDIS_URL"]
    assert s.s3_endpoint_url == env["S3_ENDPOINT_URL"]
    assert s.s3_access_key == env["S3_ACCESS_KEY"]
    assert s.s3_secret_key == env["S3_SECRET_KEY"]
    assert s.s3_bucket == env["S3_BUCKET"]
    assert s.s3_region == env["S3_REGION"]
    assert s.lq_ai_gateway_url == env["LQ_AI_GATEWAY_URL"]
    assert s.lq_ai_gateway_key == env["LQ_AI_GATEWAY_KEY"]
    assert s.jwt_secret == env["JWT_SECRET"]
    assert s.jwt_access_token_ttl_seconds == 120
    assert s.jwt_refresh_token_ttl_seconds == 240
    assert s.log_level == "debug"
    assert s.lq_ai_dev_mode is True


@pytest.mark.unit
def test_chat_tool_call_cap_env_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression (issue #207, finding 2): the cap honors the documented
    ``LQ_AI_CHAT_TOOL_CALL_CAP`` var, and still accepts the bare
    ``CHAT_TOOL_CALL_CAP`` so existing deployments don't break."""
    # The documented, LQ_AI_-prefixed var now works (it silently did not before).
    monkeypatch.delenv("CHAT_TOOL_CALL_CAP", raising=False)
    monkeypatch.setenv("LQ_AI_CHAT_TOOL_CALL_CAP", "3")
    assert Settings(_env_file=None).chat_tool_call_cap == 3  # type: ignore[call-arg]

    # The bare name still binds (back-compat for anyone relying on the accident).
    monkeypatch.delenv("LQ_AI_CHAT_TOOL_CALL_CAP", raising=False)
    monkeypatch.setenv("CHAT_TOOL_CALL_CAP", "5")
    assert Settings(_env_file=None).chat_tool_call_cap == 5  # type: ignore[call-arg]


@pytest.mark.unit
def test_get_settings_is_cached() -> None:
    """`get_settings()` returns the same instance until the cache is cleared."""
    a = get_settings()
    b = get_settings()
    assert a is b
    get_settings.cache_clear()
    c = get_settings()
    assert c is not a
