"""Tests for :mod:`app.config_holder` — hot-reload (D0.5).

Covers the atomic-swap pattern, SIGHUP-driven reload, and the rollback
posture when a reload picks up a malformed file.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.config_holder import (
    ConfigReloadError,
    MutableConfigHolder,
    install_sighup_reload,
)
from app.config_loader import load_config
from app.config_writer import (
    ProviderKeyMutationError,
    delete_provider_key,
    upsert_provider_key,
)
from app.secrets import encrypt_value

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"


@pytest.fixture
def example_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Satisfy gateway.yaml.example placeholders for direct loads."""

    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AZURE_OPENAI_RESOURCE", "test-openai")
    monkeypatch.setenv("LQ_AI_VERSION", "0.1.0-test")


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Copy gateway.yaml.example into a tmp dir for safe mutation."""

    target = tmp_path / "gateway.yaml"
    target.write_text(EXAMPLE_CONFIG.read_text(), encoding="utf-8")
    return target


@pytest.mark.unit
def test_holder_current_returns_initial_snapshot(tmp_config: Path, example_env: None) -> None:
    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)
    assert holder.current() is initial
    assert holder.config_path == tmp_config


@pytest.mark.unit
def test_holder_replace_swaps_atomically(tmp_config: Path, example_env: None) -> None:
    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)

    fresh = load_config(tmp_config)
    old = holder.replace(fresh)
    assert old is initial
    assert holder.current() is fresh


@pytest.mark.unit
def test_reload_from_disk_picks_up_changes(tmp_config: Path, example_env: None) -> None:
    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)

    # Mutate the file: append a synthetic alias pointing at an existing
    # provider so the new config is valid.
    text = tmp_config.read_text(encoding="utf-8")
    text = text.replace(
        "model_aliases:\n",
        "model_aliases:\n  hot-reload-marker:\n    primary:\n"
        "      provider: anthropic-prod\n      model: claude-opus-4-7\n"
        "    fallback: []\n",
        1,
    )
    tmp_config.write_text(text, encoding="utf-8")

    new_config = holder.reload_from_disk()
    assert "hot-reload-marker" in new_config.model_aliases
    assert holder.current() is new_config


@pytest.mark.unit
def test_reload_rejects_malformed_and_keeps_old(tmp_config: Path, example_env: None) -> None:
    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)

    # Write a file that points an alias at a non-existent provider —
    # the schema validator catches this and reload fails.
    tmp_config.write_text(
        "providers: []\nmodel_aliases:\n  smart:\n    primary:\n"
        "      provider: ghost\n      model: gpt-4o\n    fallback: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigReloadError):
        holder.reload_from_disk()

    # Holder keeps the prior snapshot.
    assert holder.current() is initial


@pytest.mark.unit
def test_reload_rejects_yaml_parse_error(tmp_config: Path, example_env: None) -> None:
    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)

    tmp_config.write_text("not: yaml: content: : :", encoding="utf-8")
    with pytest.raises(ConfigReloadError):
        holder.reload_from_disk()
    assert holder.current() is initial


@pytest.mark.unit
def test_reload_rejects_missing_required_env_var(
    tmp_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `${REQUIRED_VAR}` placeholder with no default raises through."""

    tmp_config.write_text(
        "providers:\n  - name: x\n    type: openai\n"
        "    base_url: ${UNSET_REQUIRED_VAR}\n    tier: 4\n"
        "model_aliases: {}\n",
        encoding="utf-8",
    )
    # Need a successful initial load to construct the holder; we
    # therefore set the var, build the holder, then unset and reload.
    monkeypatch.setenv("UNSET_REQUIRED_VAR", "https://x.example.com")
    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)
    monkeypatch.delenv("UNSET_REQUIRED_VAR", raising=False)

    with pytest.raises(ConfigReloadError):
        holder.reload_from_disk()
    assert holder.current() is initial


@pytest.mark.unit
@pytest.mark.skipif(
    not hasattr(signal, "SIGHUP"),
    reason="SIGHUP is unavailable on this platform",
)
def test_sighup_handler_triggers_reload(tmp_config: Path, example_env: None) -> None:
    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)
    install_sighup_reload(holder)

    text = tmp_config.read_text(encoding="utf-8")
    text = text.replace(
        "model_aliases:\n",
        "model_aliases:\n  sighup-marker:\n    primary:\n"
        "      provider: anthropic-prod\n      model: claude-opus-4-7\n"
        "    fallback: []\n",
        1,
    )
    tmp_config.write_text(text, encoding="utf-8")

    os.kill(os.getpid(), signal.SIGHUP)
    # SIGHUP delivery isn't synchronous; give the handler a moment.
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if "sighup-marker" in holder.current().model_aliases:
            break
        time.sleep(0.02)
    assert "sighup-marker" in holder.current().model_aliases


@pytest.mark.unit
@pytest.mark.skipif(
    not hasattr(signal, "SIGHUP"),
    reason="SIGHUP is unavailable on this platform",
)
def test_sighup_handler_does_not_raise_on_bad_file(tmp_config: Path, example_env: None) -> None:
    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)
    install_sighup_reload(holder)

    tmp_config.write_text("malformed: : : :", encoding="utf-8")

    # Send SIGHUP — the handler must NOT raise, and the prior snapshot
    # must remain.
    os.kill(os.getpid(), signal.SIGHUP)
    time.sleep(0.1)
    assert holder.current() is initial


# --- Provider-key mutation (runtime BYOK, Donna #7) --------------------------


def _read_provider_entry(config_path: Path, name: str) -> dict[str, object]:
    """Read the raw YAML providers entry for ``name`` (no env expansion)."""

    import yaml

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for entry in raw["providers"]:
        if entry.get("name") == name:
            return entry
    raise AssertionError(f"provider {name!r} not found in {config_path}")


@pytest.mark.unit
def test_upsert_provider_key_sets_encrypted_and_clears_env(
    tmp_config: Path, example_env: None
) -> None:
    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)

    token = encrypt_value("sk-test", master_key=Fernet.generate_key().decode())
    upsert_provider_key(holder, provider_name="anthropic-prod", encrypted_token=token)

    # On-disk YAML: gains api_key_encrypted, loses api_key_env.
    entry = _read_provider_entry(tmp_config, "anthropic-prod")
    assert entry["api_key_encrypted"] == token
    assert "api_key_env" not in entry

    # holder.current() reflects it (and round-trips the token).
    provider = holder.current().provider_by_name("anthropic-prod")
    assert provider is not None
    assert provider.api_key_encrypted == token
    assert provider.api_key_env is None


@pytest.mark.unit
def test_upsert_provider_key_unknown_provider_raises_404(
    tmp_config: Path, example_env: None
) -> None:
    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)

    token = encrypt_value("sk-test", master_key=Fernet.generate_key().decode())
    with pytest.raises(ProviderKeyMutationError) as excinfo:
        upsert_provider_key(holder, provider_name="does-not-exist", encrypted_token=token)
    assert excinfo.value.http_status == 404


@pytest.mark.unit
def test_delete_provider_key_removes_runtime_key(tmp_config: Path, example_env: None) -> None:
    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)

    # First set a runtime key, then revoke it.
    token = encrypt_value("sk-test", master_key=Fernet.generate_key().decode())
    upsert_provider_key(holder, provider_name="anthropic-prod", encrypted_token=token)
    delete_provider_key(holder, provider_name="anthropic-prod")

    entry = _read_provider_entry(tmp_config, "anthropic-prod")
    assert "api_key_encrypted" not in entry
    provider = holder.current().provider_by_name("anthropic-prod")
    assert provider is not None
    assert provider.api_key_encrypted is None


@pytest.mark.unit
def test_delete_provider_key_env_only_raises_409(tmp_config: Path, example_env: None) -> None:
    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)

    # openai-prod ships with api_key_env only — no runtime key to revoke.
    with pytest.raises(ProviderKeyMutationError) as excinfo:
        delete_provider_key(holder, provider_name="openai-prod")
    assert excinfo.value.http_status == 409


@pytest.mark.unit
def test_delete_provider_key_unknown_provider_raises_404(
    tmp_config: Path, example_env: None
) -> None:
    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)

    with pytest.raises(ProviderKeyMutationError) as excinfo:
        delete_provider_key(holder, provider_name="does-not-exist")
    assert excinfo.value.http_status == 404


@pytest.mark.unit
def test_upsert_provider_key_empty_token_raises_422(tmp_config: Path, example_env: None) -> None:
    """An empty ciphertext can never produce a keyless provider."""

    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)

    with pytest.raises(ProviderKeyMutationError) as excinfo:
        upsert_provider_key(holder, provider_name="anthropic-prod", encrypted_token="")
    assert excinfo.value.http_status == 422


@pytest.mark.unit
def test_upsert_provider_key_no_providers_list_raises_500(
    tmp_config: Path, example_env: None
) -> None:
    """A config whose ``providers:`` key is absent (or not a list) is
    treated as a malformed config — 500, not 404."""

    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)

    # Overwrite the file with a mapping that has no ``providers`` list.
    tmp_config.write_text("model_aliases: {}\n", encoding="utf-8")

    token = encrypt_value("sk-test", master_key=Fernet.generate_key().decode())
    with pytest.raises(ProviderKeyMutationError) as excinfo:
        upsert_provider_key(holder, provider_name="anthropic-prod", encrypted_token=token)
    assert excinfo.value.http_status == 500


@pytest.mark.unit
def test_upsert_provider_key_preserves_other_provider_fields(
    tmp_config: Path, example_env: None
) -> None:
    """Mutating one provider leaves a DIFFERENT provider's fields intact.

    Locks in the raw-YAML round-trip guarantee: ``base_url`` / ``tier``
    on an unrelated entry must survive the write untouched.
    """

    initial = load_config(tmp_config)
    holder = MutableConfigHolder(initial, config_path=tmp_config)

    before = holder.current().provider_by_name("openai-prod")
    assert before is not None
    base_url_before = before.base_url
    tier_before = before.tier

    token = encrypt_value("sk-test", master_key=Fernet.generate_key().decode())
    upsert_provider_key(holder, provider_name="anthropic-prod", encrypted_token=token)

    after = holder.current().provider_by_name("openai-prod")
    assert after is not None
    assert after.base_url == base_url_before
    assert after.tier == tier_before


def test_install_sighup_reload_no_op_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """When SIGHUP is unavailable, install_sighup_reload returns silently."""

    holder = type(  # minimal stub, never invoked
        "_Stub",
        (),
        {"config_path": Path("/dev/null"), "reload_from_disk": lambda self: None},
    )()
    monkeypatch.setattr(signal, "SIGHUP", None, raising=False)
    # Removing the attr so getattr returns None:
    if hasattr(signal, "SIGHUP"):
        monkeypatch.delattr(signal, "SIGHUP", raising=False)
    # Should not raise.
    install_sighup_reload(holder)  # type: ignore[arg-type]
