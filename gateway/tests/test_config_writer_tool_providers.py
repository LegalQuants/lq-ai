import yaml

from app.config_holder import MutableConfigHolder
from app.config_loader import load_config
from app.config_writer import (
    ProviderKeyMutationError,
    remove_tool_provider,
    upsert_tool_provider,
)

_MINIMAL_CONFIG = {
    "providers": [
        {
            "name": "anthropic",
            "type": "anthropic",
            "base_url": "https://x",
            "api_key_env": "ANTHROPIC_API_KEY",
            "tier": 3,
            "models": ["claude"],
        },
    ],
    "model_aliases": {
        "fast": {"primary": {"provider": "anthropic", "model": "claude"}, "fallback": []}
    },
    "gateway_auth": {"enabled": False},
}


def _holder(tmp_path) -> MutableConfigHolder:
    p = tmp_path / "gateway.yaml"
    p.write_text(yaml.safe_dump(_MINIMAL_CONFIG), encoding="utf-8")
    return MutableConfigHolder(load_config(p), config_path=p)


def _load(holder) -> dict:
    return yaml.safe_load(holder.config_path.read_text())


def test_upsert_creates_a_keyless_entry_from_defaults(tmp_path) -> None:
    holder = _holder(tmp_path)
    upsert_tool_provider(holder, provider_type="edgar", encrypted_token=None)
    raw = _load(holder)
    entry = next(e for e in raw["tool_providers"] if e["type"] == "edgar")
    assert entry["name"] == "edgar-prod"
    assert entry["base_url"] == "https://efts.sec.gov"
    assert entry["allowlist"]["hosts"] == ["efts.sec.gov", "www.sec.gov"]
    assert entry["user_agent"]  # keyless default UA present
    assert "api_key_encrypted" not in entry
    assert "api_key_env" not in entry


def test_upsert_creates_a_keyed_entry_and_encrypts(tmp_path) -> None:
    holder = _holder(tmp_path)
    upsert_tool_provider(
        holder, provider_type="courtlistener", encrypted_token="gAAAAAB-ciphertext"
    )
    entry = next(e for e in _load(holder)["tool_providers"] if e["type"] == "courtlistener")
    assert entry["api_key_encrypted"] == "gAAAAAB-ciphertext"
    assert "api_key_env" not in entry  # runtime source; validator forbids both


def test_upsert_rotates_key_on_existing_entry(tmp_path) -> None:
    holder = _holder(tmp_path)
    upsert_tool_provider(holder, provider_type="govinfo", encrypted_token="gAAAAAB-one")
    upsert_tool_provider(holder, provider_type="govinfo", encrypted_token="gAAAAAB-two")
    entries = [e for e in _load(holder)["tool_providers"] if e["type"] == "govinfo"]
    assert len(entries) == 1  # rotated in place, not duplicated
    assert entries[0]["api_key_encrypted"] == "gAAAAAB-two"


def test_upsert_unknown_type_raises_404(tmp_path) -> None:
    holder = _holder(tmp_path)
    try:
        upsert_tool_provider(holder, provider_type="westlaw", encrypted_token=None)
        raise AssertionError("expected ProviderKeyMutationError")
    except ProviderKeyMutationError as exc:
        assert exc.http_status == 404


def test_remove_deletes_a_runtime_entry(tmp_path) -> None:
    holder = _holder(tmp_path)
    upsert_tool_provider(holder, provider_type="edgar", encrypted_token=None)
    remove_tool_provider(holder, provider_type="edgar")
    assert not any(e["type"] == "edgar" for e in _load(holder).get("tool_providers", []))


def test_remove_absent_type_raises_404(tmp_path) -> None:
    holder = _holder(tmp_path)
    try:
        remove_tool_provider(holder, provider_type="edgar")
        raise AssertionError("expected 404")
    except ProviderKeyMutationError as exc:
        assert exc.http_status == 404


def test_remove_env_sourced_entry_raises_409(tmp_path) -> None:
    # Operator hand-wrote an env-sourced entry; the runtime API must not delete it.
    holder = _holder(tmp_path)
    raw = _load(holder)
    raw["tool_providers"] = [
        {
            "name": "courtlistener-prod",
            "type": "courtlistener",
            "base_url": "https://www.courtlistener.com/api/rest/v4",
            "api_key_env": "COURTLISTENER_API_TOKEN",
            "egress_tier": 4,
            "allowlist": {"hosts": ["www.courtlistener.com"]},
        }
    ]
    holder.config_path.write_text(yaml.safe_dump(raw))
    holder.reload_from_disk()
    try:
        remove_tool_provider(holder, provider_type="courtlistener")
        raise AssertionError("expected 409")
    except ProviderKeyMutationError as exc:
        assert exc.http_status == 409
