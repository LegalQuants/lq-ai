"""Unit tests for file-mounted secret delivery (#590, GW-06)."""

from __future__ import annotations

import os

import pytest

from app.secrets import (
    ProviderKeyResolver,
    SecretFileError,
    SecretSourceConflict,
    generate_master_key,
    resolve_secret,
    snapshot_secret_sources,
)


@pytest.fixture(autouse=True)
def private_secret_file_umask():
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


@pytest.mark.unit
def test_resolve_secret_env_only() -> None:
    assert resolve_secret("MY_KEY", {"MY_KEY": "abc"}) == "abc"


@pytest.mark.unit
def test_resolve_secret_unset_returns_none() -> None:
    assert resolve_secret("MY_KEY", {}) is None


@pytest.mark.unit
@pytest.mark.parametrize("mode", [0o400, 0o600])
def test_resolve_secret_file_only_strips_newline(tmp_path, mode: int) -> None:
    secret_file = tmp_path / "key.txt"
    secret_file.write_text("dummy-secret-value\n", encoding="utf-8")
    secret_file.chmod(mode)
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
@pytest.mark.parametrize("mode", [0o440, 0o644])
def test_resolve_secret_wide_permissions_rejected(tmp_path, mode: int) -> None:
    secret_file = tmp_path / "key.txt"
    secret_file.write_text("dummy-warn-value", encoding="utf-8")
    os.chmod(secret_file, mode)
    with pytest.raises(SecretFileError, match=f"{mode:04o}") as excinfo:
        resolve_secret("MY_KEY", {"MY_KEY_FILE": str(secret_file)})
    assert "dummy-warn-value" not in str(excinfo.value)


@pytest.mark.unit
def test_resolve_secret_symlink_checks_opened_target(tmp_path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("private-value", encoding="utf-8")
    link = tmp_path / "current.txt"
    link.symlink_to(target)
    assert resolve_secret("MY_KEY", {"MY_KEY_FILE": str(link)}) == "private-value"
    target.chmod(0o644)
    with pytest.raises(SecretFileError, match="0644"):
        resolve_secret("MY_KEY", {"MY_KEY_FILE": str(link)})


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
def test_provider_resolver_file_error_rejects_provider(tmp_path) -> None:
    missing = tmp_path / "missing.txt"
    resolver = ProviderKeyResolver(master_key=None, env={"OPENAI_API_KEY_FILE": str(missing)})
    with pytest.raises(SecretFileError):
        resolver.resolve(
            provider_name="openai-prod",
            api_key_env="OPENAI_API_KEY",
            api_key_encrypted=None,
        )


@pytest.mark.unit
def test_blank_file_source_is_not_treated_as_unset() -> None:
    with pytest.raises(SecretFileError, match="blank"):
        resolve_secret("MY_KEY", {"MY_KEY_FILE": " "})


@pytest.mark.unit
def test_snapshot_keeps_file_value_after_rotation(tmp_path) -> None:
    secret_file = tmp_path / "provider.txt"
    secret_file.write_text("original", encoding="utf-8")
    resolver, _ = snapshot_secret_sources(
        {"OPENAI_API_KEY_FILE": str(secret_file)},
        global_names={"LQ_AI_GATEWAY_KEY"},
        provider_names={"OPENAI_API_KEY"},
    )
    secret_file.write_text("rotated", encoding="utf-8")
    assert (
        resolver.resolve(
            provider_name="openai-prod", api_key_env="OPENAI_API_KEY", api_key_encrypted=None
        )
        == "original"
    )


@pytest.mark.unit
def test_snapshot_invalid_provider_file_remains_unavailable(tmp_path) -> None:
    missing = tmp_path / "missing.txt"
    resolver, _ = snapshot_secret_sources(
        {"OPENAI_API_KEY_FILE": str(missing)},
        global_names={"LQ_AI_GATEWAY_KEY"},
        provider_names={"OPENAI_API_KEY"},
    )
    with pytest.raises(SecretFileError):
        resolver.resolve(
            provider_name="openai-prod", api_key_env="OPENAI_API_KEY", api_key_encrypted=None
        )
    assert (
        resolver.resolve(provider_name="local-keyless", api_key_env=None, api_key_encrypted=None)
        == ""
    )


@pytest.mark.unit
def test_snapshot_global_key_is_bound_once(tmp_path) -> None:
    secret_file = tmp_path / "gateway-key.txt"
    secret_file.write_text("first", encoding="utf-8")
    _, global_keys = snapshot_secret_sources(
        {"LQ_AI_GATEWAY_KEY_FILE": str(secret_file)},
        global_names={"LQ_AI_GATEWAY_KEY"},
        provider_names=set(),
    )
    secret_file.unlink()
    assert global_keys["LQ_AI_GATEWAY_KEY"] == "first"


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
def test_gateway_key_dependency_uses_startup_value_after_file_change(tmp_path) -> None:
    from app.api.dependencies import _resolve_required_key
    from app.config import GatewayConfig

    secret_file = tmp_path / "gateway-key.txt"
    secret_file.write_text("initial-key", encoding="utf-8")
    _, global_keys = snapshot_secret_sources(
        {"LQ_AI_GATEWAY_KEY_FILE": str(secret_file)},
        global_names={"LQ_AI_GATEWAY_KEY"},
        provider_names=set(),
    )
    secret_file.write_text("rotated-key", encoding="utf-8")
    config = GatewayConfig.model_validate({"gateway_auth": {"enabled": True}})
    assert (
        _resolve_required_key(
            config,
            bound_name="LQ_AI_GATEWAY_KEY",
            bound_key=global_keys["LQ_AI_GATEWAY_KEY"],
        )
        == "initial-key"
    )


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
