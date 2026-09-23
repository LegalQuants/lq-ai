"""Unit tests for file-mounted secret delivery (#590, GW-06)."""

from __future__ import annotations

import logging
import os

import pytest

from app.secrets import (
    ProviderKeyResolver,
    SecretFileError,
    SecretSourceConflict,
    generate_master_key,
    resolve_secret,
)


@pytest.mark.unit
def test_resolve_secret_env_only() -> None:
    assert resolve_secret("MY_KEY", {"MY_KEY": "abc"}) == "abc"


@pytest.mark.unit
def test_resolve_secret_unset_returns_none() -> None:
    assert resolve_secret("MY_KEY", {}) is None


@pytest.mark.unit
def test_resolve_secret_file_only_strips_newline(tmp_path) -> None:
    secret_file = tmp_path / "key.txt"
    secret_file.write_text("dummy-secret-value\n", encoding="utf-8")
    out = resolve_secret("MY_KEY", {"MY_KEY_FILE": str(secret_file)})
    assert out == "dummy-secret-value"


@pytest.mark.unit
def test_resolve_secret_file_strips_crlf_and_spaces(tmp_path) -> None:
    secret_file = tmp_path / "key.txt"
    secret_file.write_text("  spaced-value \r\n", encoding="utf-8")
    assert resolve_secret("MY_KEY", {"MY_KEY_FILE": str(secret_file)}) == "spaced-value"


@pytest.mark.unit
def test_resolve_secret_conflict_raises() -> None:
    with pytest.raises(SecretSourceConflict) as excinfo:
        resolve_secret("MY_KEY", {"MY_KEY": "env-secret-value", "MY_KEY_FILE": "/tmp/x"})
    assert "MY_KEY" in str(excinfo.value)
    assert "env-secret-value" not in str(excinfo.value)


@pytest.mark.unit
def test_resolve_secret_missing_file_raises(tmp_path) -> None:
    missing = tmp_path / "nope.txt"
    with pytest.raises(SecretFileError) as excinfo:
        resolve_secret("MY_KEY", {"MY_KEY_FILE": str(missing)})
    assert "MY_KEY_FILE" in str(excinfo.value)


@pytest.mark.unit
def test_resolve_secret_directory_raises(tmp_path) -> None:
    with pytest.raises(SecretFileError):
        resolve_secret("MY_KEY", {"MY_KEY_FILE": str(tmp_path)})


@pytest.mark.unit
def test_resolve_secret_empty_file_raises(tmp_path) -> None:
    secret_file = tmp_path / "key.txt"
    secret_file.write_text("  \n", encoding="utf-8")
    with pytest.raises(SecretFileError):
        resolve_secret("MY_KEY", {"MY_KEY_FILE": str(secret_file)})


@pytest.mark.unit
def test_resolve_secret_world_readable_warns_but_loads(tmp_path, caplog) -> None:
    secret_file = tmp_path / "key.txt"
    secret_file.write_text("dummy-warn-value", encoding="utf-8")
    os.chmod(secret_file, 0o644)
    with caplog.at_level(logging.WARNING, logger="app.secrets"):
        out = resolve_secret("MY_KEY", {"MY_KEY_FILE": str(secret_file)})
    assert out == "dummy-warn-value"
    assert any("group/world-accessible" in r.message for r in caplog.records)
    assert not any("dummy-warn-value" in r.message for r in caplog.records)


@pytest.mark.unit
def test_resolve_secret_error_never_contains_value(tmp_path) -> None:
    secret_file = tmp_path / "key.txt"
    secret_file.write_text("dummy-payload-value", encoding="utf-8")
    assert secret_file.read_text().strip() == "dummy-payload-value"
    missing = tmp_path / "missing.txt"
    with pytest.raises(SecretFileError) as excinfo:
        resolve_secret("OTHER_KEY", {"OTHER_KEY_FILE": str(missing)})
    assert "dummy-payload-value" not in str(excinfo.value)


@pytest.mark.unit
def test_provider_resolver_reads_file_key(tmp_path) -> None:
    secret_file = tmp_path / "anthropic.txt"
    secret_file.write_text("test-provider-file-key\n", encoding="utf-8")
    resolver = ProviderKeyResolver(
        master_key=None, env={"ANTHROPIC_API_KEY_FILE": str(secret_file)}
    )
    out = resolver.resolve(
        provider_name="anthropic-prod",
        api_key_env="ANTHROPIC_API_KEY",
        api_key_encrypted=None,
    )
    assert out == "test-provider-file-key"


@pytest.mark.unit
def test_provider_resolver_file_error_degrades_to_empty(tmp_path) -> None:
    missing = tmp_path / "missing.txt"
    resolver = ProviderKeyResolver(master_key=None, env={"OPENAI_API_KEY_FILE": str(missing)})
    out = resolver.resolve(
        provider_name="openai-prod",
        api_key_env="OPENAI_API_KEY",
        api_key_encrypted=None,
    )
    assert out == ""


@pytest.mark.unit
def test_provider_resolver_env_file_conflict_raises(tmp_path) -> None:
    secret_file = tmp_path / "k.txt"
    secret_file.write_text("v", encoding="utf-8")
    resolver = ProviderKeyResolver(
        master_key=None,
        env={"OPENAI_API_KEY": "env-value", "OPENAI_API_KEY_FILE": str(secret_file)},
    )
    with pytest.raises(SecretSourceConflict):
        resolver.resolve(
            provider_name="openai-prod",
            api_key_env="OPENAI_API_KEY",
            api_key_encrypted=None,
        )


@pytest.mark.unit
def test_from_environ_reads_master_key_file(tmp_path, monkeypatch) -> None:
    master = generate_master_key()
    master_file = tmp_path / "master.txt"
    master_file.write_text(master + "\n", encoding="utf-8")
    monkeypatch.delenv("LQ_AI_GATEWAY_MASTER_KEY", raising=False)
    monkeypatch.setenv("LQ_AI_GATEWAY_MASTER_KEY_FILE", str(master_file))
    resolver = ProviderKeyResolver.from_environ()
    assert resolver.master_key == master


@pytest.mark.unit
def test_from_env_dict_reads_master_key_file(tmp_path) -> None:
    master = generate_master_key()
    master_file = tmp_path / "master.txt"
    master_file.write_text(master, encoding="utf-8")
    resolver = ProviderKeyResolver.from_env_dict(
        {"LQ_AI_GATEWAY_MASTER_KEY_FILE": str(master_file)}
    )
    assert resolver.master_key == master


@pytest.mark.unit
def test_gateway_key_file_resolves_for_dependencies(tmp_path, monkeypatch) -> None:
    from app.api.dependencies import _resolve_required_key
    from app.config import GatewayConfig

    secret_file = tmp_path / "gateway-key.txt"
    secret_file.write_text("dep-file-key\n", encoding="utf-8")
    monkeypatch.delenv("LQ_AI_GATEWAY_KEY", raising=False)
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY_FILE", str(secret_file))
    config = GatewayConfig.model_validate(
        {"gateway_auth": {"enabled": True, "api_key_env": "LQ_AI_GATEWAY_KEY"}}
    )
    assert _resolve_required_key(config) == "dep-file-key"


@pytest.mark.unit
def test_gateway_key_file_conflict_raises(tmp_path, monkeypatch) -> None:
    from app.api.dependencies import _resolve_required_key
    from app.config import GatewayConfig
    from app.secrets import SecretSourceConflict

    secret_file = tmp_path / "gateway-key.txt"
    secret_file.write_text("v", encoding="utf-8")
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", "env-value")
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY_FILE", str(secret_file))
    config = GatewayConfig.model_validate(
        {"gateway_auth": {"enabled": True, "api_key_env": "LQ_AI_GATEWAY_KEY"}}
    )
    with pytest.raises(SecretSourceConflict):
        _resolve_required_key(config)
