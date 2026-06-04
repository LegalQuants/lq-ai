"""Acceptance + unit tests for runtime provider-key management (Donna #7).

These exercise the ``/admin/v1/provider-keys`` endpoints end-to-end through
the ASGI client AND the service layer directly. The hard requirements
verified here:

* A POST activates a previously-keyless provider's adapter *in the live
  registry* with no restart (hot-apply).
* No endpoint ever returns a full key or the encrypted token — only
  ``last4`` (capped at 4 chars) escapes.
* The encrypted token written to disk is not the plaintext.
* Revoke pops the adapter (provider would route 503 afterward).
* A rotation on an already-keyed provider MOVES the displaced adapter into
  ``retired_adapters`` (never double-held).
* Master-key precondition (400) and unknown-provider / env-only error
  mapping (404 / 409).

We never mutate the committed ``gateway.yaml.example`` — every fixture
copies it to a writable temp path first.
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import ProviderConfig
from app.provider_keys import apply_provider_key, revoke_provider_key

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = REPO_ROOT / "gateway.yaml.example"

# A provider that is env-sourced but whose env var is NOT set by the
# ``example_env`` fixture, so it has no adapter at startup. POSTing a
# runtime key must activate it — proving hot-apply without restart.
KEYLESS_PROVIDER = "openai-prod"

# A clearly-fake key whose last 4 chars are assertable.
FAKE_KEY = "sk-test-ABCDwxyz"
FAKE_KEY_LAST4 = "wxyz"


@asynccontextmanager
async def _run_lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with app.router.lifespan_context(app):
        yield


def _set_example_env(monkeypatch: pytest.MonkeyPatch, tmp_config: Path) -> None:
    """Set the ``${VAR}`` placeholders the example config references."""

    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AZURE_OPENAI_RESOURCE", "test-openai")
    monkeypatch.setenv("LQ_AI_VERSION", "0.1.0-test")
    monkeypatch.setenv("GATEWAY_CONFIG_PATH", str(tmp_config))


@pytest_asyncio.fixture
async def writable_config(tmp_path: Path) -> Path:
    """Copy the committed example config to a writable temp path."""

    dest = tmp_path / "gateway.yaml"
    shutil.copyfile(EXAMPLE_CONFIG, dest)
    return dest


@pytest_asyncio.fixture
async def keyed_app(
    monkeypatch: pytest.MonkeyPatch, writable_config: Path
) -> AsyncIterator[FastAPI]:
    """Gateway app with a fresh master key + writable temp config."""

    _set_example_env(monkeypatch, writable_config)
    monkeypatch.setenv("LQ_AI_GATEWAY_MASTER_KEY", Fernet.generate_key().decode())

    from app.main import app

    async with _run_lifespan(app):
        yield app


@pytest_asyncio.fixture
async def keyed_client(keyed_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=keyed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest_asyncio.fixture
async def no_master_key_app(
    monkeypatch: pytest.MonkeyPatch, writable_config: Path
) -> AsyncIterator[FastAPI]:
    """Gateway app WITHOUT a master key — POST/PATCH must 400."""

    _set_example_env(monkeypatch, writable_config)
    monkeypatch.delenv("LQ_AI_GATEWAY_MASTER_KEY", raising=False)

    from app.main import app

    async with _run_lifespan(app):
        yield app


@pytest_asyncio.fixture
async def no_master_key_client(no_master_key_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=no_master_key_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


def _assert_no_secret(body: object, *, plaintext: str) -> None:
    """Assert the full plaintext key never appears anywhere in a response."""

    import json

    blob = json.dumps(body)
    assert plaintext not in blob, "full key leaked into response body"
    # Belt-and-suspenders: also reject the longer prefix so a partial leak
    # beyond last4 is caught.
    assert plaintext[:-4] not in blob


# ---------------------------------------------------------------------------
# Acceptance — end-to-end through the ASGI client
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_post_activates_keyless_provider(
    keyed_client: AsyncClient, keyed_app: FastAPI
) -> None:
    """POST a key → 200, configured, last4, source=runtime, adapter live."""

    # Precondition: the env-sourced provider has no adapter at startup.
    assert KEYLESS_PROVIDER not in keyed_app.state.adapters

    resp = await keyed_client.post(
        "/admin/v1/provider-keys",
        json={"provider": KEYLESS_PROVIDER, "api_key": FAKE_KEY},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == KEYLESS_PROVIDER
    assert body["configured"] is True
    assert body["last4"] == FAKE_KEY_LAST4
    assert body["source"] == "runtime"
    _assert_no_secret(body, plaintext=FAKE_KEY)

    # Hot-apply: the adapter is now live without a restart.
    assert KEYLESS_PROVIDER in keyed_app.state.adapters


@pytest.mark.unit
async def test_list_provider_keys_is_secret_safe(
    keyed_client: AsyncClient,
) -> None:
    """GET lists runtime + env sources; never leaks a full key."""

    # Apply a runtime key first.
    await keyed_client.post(
        "/admin/v1/provider-keys",
        json={"provider": KEYLESS_PROVIDER, "api_key": FAKE_KEY},
    )

    resp = await keyed_client.get("/admin/v1/provider-keys")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = {row["provider"]: row for row in body["provider_keys"]}

    runtime_row = rows[KEYLESS_PROVIDER]
    assert runtime_row["configured"] is True
    assert runtime_row["source"] == "runtime"
    assert runtime_row["last4"] == FAKE_KEY_LAST4

    # An env-sourced provider (ollama uses api_key_env='', so it's None;
    # anthropic-prod uses api_key_env=ANTHROPIC_API_KEY → source 'env').
    assert rows["anthropic-prod"]["source"] == "env"

    _assert_no_secret(body, plaintext=FAKE_KEY)
    # No field anywhere should carry the encrypted token either; last4 is
    # the only key fragment, capped at 4 chars.
    for row in body["provider_keys"]:
        if row["last4"] is not None:
            assert len(row["last4"]) == 4


@pytest.mark.unit
async def test_delete_revokes_and_pops_adapter(
    keyed_client: AsyncClient, keyed_app: FastAPI
) -> None:
    """DELETE → 204; provider configured=false, adapter gone."""

    await keyed_client.post(
        "/admin/v1/provider-keys",
        json={"provider": KEYLESS_PROVIDER, "api_key": FAKE_KEY},
    )
    assert KEYLESS_PROVIDER in keyed_app.state.adapters

    resp = await keyed_client.delete(f"/admin/v1/provider-keys/{KEYLESS_PROVIDER}")
    assert resp.status_code == 204, resp.text
    # Per the CLAUDE.md DELETE-204 recipe the 204 carries a genuinely empty
    # body (response_class=Response). Assert it's empty — and so trivially
    # secret-free.
    assert resp.content == b""

    assert KEYLESS_PROVIDER not in keyed_app.state.adapters

    listing = await keyed_client.get("/admin/v1/provider-keys")
    rows = {row["provider"]: row for row in listing.json()["provider_keys"]}
    assert rows[KEYLESS_PROVIDER]["configured"] is False


@pytest.mark.unit
async def test_post_without_master_key_returns_400(
    no_master_key_client: AsyncClient,
) -> None:
    """POST with no master key → 400 failed_precondition."""

    resp = await no_master_key_client.post(
        "/admin/v1/provider-keys",
        json={"provider": KEYLESS_PROVIDER, "api_key": FAKE_KEY},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "failed_precondition"


@pytest.mark.unit
async def test_patch_without_master_key_returns_400(
    no_master_key_client: AsyncClient,
) -> None:
    resp = await no_master_key_client.patch(
        f"/admin/v1/provider-keys/{KEYLESS_PROVIDER}",
        json={"api_key": FAKE_KEY},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "failed_precondition"


@pytest.mark.unit
async def test_post_unknown_provider_returns_404(keyed_client: AsyncClient) -> None:
    resp = await keyed_client.post(
        "/admin/v1/provider-keys",
        json={"provider": "does-not-exist", "api_key": FAKE_KEY},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.unit
async def test_patch_unknown_provider_returns_404(keyed_client: AsyncClient) -> None:
    resp = await keyed_client.patch(
        "/admin/v1/provider-keys/does-not-exist",
        json={"api_key": FAKE_KEY},
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.unit
async def test_delete_unknown_provider_returns_404(keyed_client: AsyncClient) -> None:
    resp = await keyed_client.delete("/admin/v1/provider-keys/does-not-exist")
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.unit
async def test_delete_env_only_provider_returns_409(keyed_client: AsyncClient) -> None:
    """Revoking an env-sourced provider (no runtime key) → 409 conflict."""

    resp = await keyed_client.delete("/admin/v1/provider-keys/anthropic-prod")
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "conflict"


@pytest.mark.unit
async def test_encrypted_token_written_not_plaintext(
    keyed_client: AsyncClient, writable_config: Path
) -> None:
    """The on-disk YAML holds api_key_encrypted, never the plaintext."""

    resp = await keyed_client.post(
        "/admin/v1/provider-keys",
        json={"provider": KEYLESS_PROVIDER, "api_key": FAKE_KEY},
    )
    assert resp.status_code == 200, resp.text

    disk = writable_config.read_text(encoding="utf-8")
    assert FAKE_KEY not in disk, "plaintext key written to disk"
    assert "api_key_encrypted" in disk


# A provider whose ``type`` has no adapter implementation (build_adapter
# returns None): a runtime key is stored on disk but the provider is never
# live-routable. ``vertex`` is such a type in the example config.
UNSUPPORTED_PROVIDER = "vertex-anthropic"
ROTATE_KEY = "sk-test-ROTATEmnop"
ROTATE_KEY_LAST4 = "mnop"


@pytest.mark.unit
async def test_patch_rotates_keyed_provider_through_endpoint(
    keyed_client: AsyncClient, keyed_app: FastAPI
) -> None:
    """PATCH rotates a key end-to-end → 200, new last4, source=runtime, live.

    Covers the thin PATCH endpoint wiring: first POST a key (provider goes
    live), then PATCH a *different* key on the same provider. The response
    reflects the new key's last4, source stays ``runtime``, and the
    provider's live adapter is a NEW object (the rotation rebuilt + swapped
    it, retiring the displaced one).
    """

    # Bring the provider live via POST.
    resp = await keyed_client.post(
        "/admin/v1/provider-keys",
        json={"provider": KEYLESS_PROVIDER, "api_key": FAKE_KEY},
    )
    assert resp.status_code == 200, resp.text
    adapter_before = keyed_app.state.adapters[KEYLESS_PROVIDER]

    # Rotate via PATCH (provider from the path).
    resp = await keyed_client.patch(
        f"/admin/v1/provider-keys/{KEYLESS_PROVIDER}",
        json={"api_key": ROTATE_KEY},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == KEYLESS_PROVIDER
    assert body["configured"] is True
    assert body["last4"] == ROTATE_KEY_LAST4
    assert body["source"] == "runtime"
    _assert_no_secret(body, plaintext=ROTATE_KEY)

    # Hot-apply on rotate: still routable, and a fresh adapter object.
    assert KEYLESS_PROVIDER in keyed_app.state.adapters
    assert keyed_app.state.adapters[KEYLESS_PROVIDER] is not adapter_before


@pytest.mark.unit
async def test_post_unsupported_provider_stored_but_not_live(
    keyed_client: AsyncClient, keyed_app: FastAPI, writable_config: Path
) -> None:
    """POST to a no-adapter provider type → 200, stored on disk, NOT live.

    A provider whose ``type`` has no adapter (``vertex``) still accepts a
    runtime key: the write SUCCEEDS (200) and ``api_key_encrypted`` lands on
    disk, but ``build_adapter`` returns None so the provider is reported
    ``configured: false`` and is absent from the live adapter registry. This
    is the documented "stored but not live-routable" branch.
    """

    assert UNSUPPORTED_PROVIDER not in keyed_app.state.adapters

    resp = await keyed_client.post(
        "/admin/v1/provider-keys",
        json={"provider": UNSUPPORTED_PROVIDER, "api_key": FAKE_KEY},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == UNSUPPORTED_PROVIDER
    # No adapter was built → not configured, no last4 surfaced.
    assert body["configured"] is False
    assert body["last4"] is None
    _assert_no_secret(body, plaintext=FAKE_KEY)

    # The key IS persisted (the write half succeeded)...
    disk = writable_config.read_text(encoding="utf-8")
    assert FAKE_KEY not in disk, "plaintext key written to disk"
    assert "api_key_encrypted" in disk
    # ...but the provider is NOT live-routable.
    assert UNSUPPORTED_PROVIDER not in keyed_app.state.adapters


# ---------------------------------------------------------------------------
# Hot-swap unit test — service layer, no HTTP
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Minimal stand-in identified by a label."""

    def __init__(self, label: str) -> None:
        self.label = label

    async def aclose(self) -> None:  # pragma: no cover - not exercised here
        return None


class _FakeState:
    """Stand-in for ``app.state`` with the three attrs the service reads."""

    def __init__(self) -> None:
        self.adapters: dict[str, object] = {}
        self.retired_adapters: list[object] = []


@pytest.mark.unit
async def test_rotation_retires_displaced_adapter(
    monkeypatch: pytest.MonkeyPatch, writable_config: Path
) -> None:
    """Rotating an already-keyed provider MOVES the old adapter to retired.

    Drives the service layer directly against a real holder, with a stubbed
    ``build_adapter`` so we control adapter identity and don't need live
    provider credentials. Asserts the displaced adapter ends up in
    ``retired_adapters`` exactly once and is not double-held.
    """

    monkeypatch.setenv("LQ_AI_GATEWAY_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("AZURE_OPENAI_RESOURCE", "test-openai")
    monkeypatch.setenv("LQ_AI_VERSION", "0.1.0-test")

    from app.config_holder import MutableConfigHolder
    from app.config_loader import load_config

    holder = MutableConfigHolder(load_config(writable_config), config_path=writable_config)
    state = _FakeState()
    master_key = Fernet.generate_key().decode()
    monkeypatch.setenv("LQ_AI_GATEWAY_MASTER_KEY", master_key)

    # Stub build_adapter so each call yields a fresh, distinguishable
    # adapter regardless of real provider credentials.
    counter = {"n": 0}

    def _fake_build(provider: ProviderConfig) -> _FakeAdapter:
        counter["n"] += 1
        return _FakeAdapter(f"{provider.name}-{counter['n']}")

    monkeypatch.setattr("app.main.build_adapter", _fake_build)

    # First apply → adapter v1 installed.
    await apply_provider_key(
        holder=holder,
        app_state=state,  # type: ignore[arg-type]
        provider_name=KEYLESS_PROVIDER,
        plaintext="sk-test-first0",
        master_key=master_key,
    )
    first = state.adapters[KEYLESS_PROVIDER]
    assert isinstance(first, _FakeAdapter)
    assert state.retired_adapters == []

    # Rotate → adapter v2 installed, v1 retired (moved, not copied).
    await apply_provider_key(
        holder=holder,
        app_state=state,  # type: ignore[arg-type]
        provider_name=KEYLESS_PROVIDER,
        plaintext="sk-test-second",
        master_key=master_key,
    )
    second = state.adapters[KEYLESS_PROVIDER]
    assert second is not first
    assert state.retired_adapters == [first]
    # Not double-held: the displaced adapter lives only in retired.
    assert state.adapters[KEYLESS_PROVIDER] is not first


@pytest.mark.unit
async def test_revoke_retires_live_adapter(
    monkeypatch: pytest.MonkeyPatch, writable_config: Path
) -> None:
    """revoke_provider_key pops the live adapter into retired_adapters."""

    master_key = Fernet.generate_key().decode()
    monkeypatch.setenv("LQ_AI_GATEWAY_MASTER_KEY", master_key)

    from app.config_holder import MutableConfigHolder
    from app.config_loader import load_config

    holder = MutableConfigHolder(load_config(writable_config), config_path=writable_config)
    state = _FakeState()

    def _fake_build(provider: ProviderConfig) -> _FakeAdapter:
        return _FakeAdapter(provider.name)

    monkeypatch.setattr("app.main.build_adapter", _fake_build)

    await apply_provider_key(
        holder=holder,
        app_state=state,  # type: ignore[arg-type]
        provider_name=KEYLESS_PROVIDER,
        plaintext="sk-test-ABCDwxyz",
        master_key=master_key,
    )
    live = state.adapters[KEYLESS_PROVIDER]

    await revoke_provider_key(
        holder=holder,
        app_state=state,  # type: ignore[arg-type]
        provider_name=KEYLESS_PROVIDER,
    )
    assert KEYLESS_PROVIDER not in state.adapters
    assert state.retired_adapters == [live]
