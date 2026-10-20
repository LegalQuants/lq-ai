# Runtime Tool/Authority-Provider Admin API + "Research sources" Card — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give operators a runtime, in-app path to enable/disable the four fiduciary-grade authority sources (CourtListener, GovInfo, EDGAR, EUR-Lex) and manage their keys — no `gateway.yaml` hand-edit, no restart — plus the API contract Donna's BFF needs.

**Architecture:** Mirror the proven inference-BYOK provider-key path one layer down into the gateway's `tool_providers:` block. The **gateway owns a tool-provider default registry** (base_url / allowlist / egress_tier / rate_limit / key_required per type) seeded from `gateway.yaml.example`, so the api can never inject an arbitrary egress target (SSRF-safe, ADR 0014). The api layer is a thin `AdminUser`-gated proxy; secrets are write-only and never returned. Hot-apply reuses the in-place `app.state.tool_adapters` swap the Router already shares by reference.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 (api standard mypy, gateway `--strict`), `cryptography` Fernet (ADR 0011), SvelteKit (OpenWebUI fork), pytest + respx.

---

## Global Constraints

- **Security-gated.** Touches `gateway/**` + secrets + admin authz → auto-routed to CODEOWNERS security reviewers. **Do NOT self-merge past the security review.**
- **Secrets write-only.** No endpoint or log ever returns a plaintext key or the Fernet ciphertext (`api_key_encrypted`). Status rows carry `has_key: bool` only — never `last4` for tool-providers (keys here are opaque operator tokens, not `sk-`-prefixed; a `last4` adds leak surface for no UX gain).
- **Gateway owns egress defaults.** The api passes only `{type, api_key?, enabled?}`. `base_url`, `allowlist`, `egress_tier`, `rate_limit`, canonical `name`, and `user_agent` come from the gateway's default registry — never from the api request body.
- **Audit writes.** POST/PATCH/DELETE on the api surface write an `audit_log` row via `audit_action` (tier_policy pattern). *(Decision D1 — deviates from provider-keys, which don't audit; DE-38x filed to backfill them.)*
- **Encryption.** Reuse `encrypt_value(plaintext, master_key=...)` from `gateway/app/secrets.py` and `MASTER_KEY_ENV = "LQ_AI_GATEWAY_MASTER_KEY"`. No new secret-storage mechanism.
- **Commits:** `git commit -s` (DCO) + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Imperative mood. Push BOTH remotes (`origin`, `tucuxi`) — but only after the PR merges (branch work stays on `origin` PR branch).
- **No new migration.** This is config-file writes, not schema. Do NOT run host `alembic upgrade` on the dev DB.
- **Lint/type gates run separately:** `ruff format` AND `ruff check`; `mypy` (gateway strict / api standard). Run both.
- **Test runner:** host venv + throwaway pgvector, NOT docker compose. See each task's Run lines. Restart the throwaway PG if stopped.

---

## Decisions (resolving spec §7 open items + discovered forks)

| # | Decision | Rationale |
|---|---|---|
| **D1** | **Writes are audited** (db + request + `audit_action`, `action="tool_provider.enabled/updated/disabled"`, `resource_type="tool_provider"`, `resource_id=type`). | Confirmed with maintainer. Fiduciary posture demands an audit trail on security-gated config mutations. File **DE-38x** to backfill provider-keys auditing (currently a gap). |
| **D2** | **Gateway owns the tool-provider default registry** (`TOOL_PROVIDER_DEFAULTS`, keyed by type). The api never sends `base_url`/`allowlist`. | Spec §7 recommendation; ADR 0014 SSRF safety. Verified: the api's `SOURCE_REGISTRY` has no base_url/key fields and `list_tool_providers` strips to `{name,type}`. |
| **D3** | **enable = upsert entry from defaults + build & in-place swap adapter into `app.state.tool_adapters`; disable/DELETE = remove entry + retire adapter.** `enabled` in status = live-adapter presence (mirrors `provider_key_status.configured = name in adapters`). | Makes the hot-apply proof work through the existing `/research/sources` join, which keys off entry **presence** (not the `enabled` flag). Single source of truth. |
| **D4** | **409 protects operator env-configured entries.** DELETE / PATCH-disable on an entry sourced from `api_key_env` → 409 (`conflict`); the runtime API only removes entries it can own (`api_key_encrypted` or keyless-runtime). **404** = type not in `SOURCE_REGISTRY`. **400** = master key unset (only on key-bearing writes). | Mirrors inference `delete_provider_key` env-key 409. Prevents the API from deleting an operator's hand-written env config. |
| **D5** | **Keyless sources get a generic operator-overridable default User-Agent** in `TOOL_PROVIDER_DEFAULTS` (`"LQ.AI legal-research (self-hosted; set user_agent in gateway.yaml)"`). | Confirmed with maintainer. SEC/EUR-Lex mandate a UA. One-click enable must work out of the box; operator can override by pre-adding the entry. Security review to confirm acceptable. |
| **D6** | **api keys the surface by `type`** (`courtlistener` / `govinfo` / `edgar` / `eurlex`); the gateway resolves `type → canonical name` via `TOOL_PROVIDER_DEFAULTS`. | Spec §7 name-vs-type; the api never needs to know provider names. |
| **D7** | **Deferred (DE-38x each):** (a) Router tool-rate-limiter is construction-time only — a hot-enabled provider's RPM won't throttle until restart (fail-open, not a security hole). (b) `resolve_available_sources` ignores the entry `enabled` flag (keys off presence) — pre-existing. (c) `_sanitized_config_payload` includes `api_key_encrypted` (Fernet ciphertext, not plaintext) in `GET /admin/v1/config` — we add a strip as cheap hardening in T2. | Out of scope for this build; log them so silent truncation doesn't read as "covered." |

---

## File Structure

**Gateway (`gateway/`)**
- `gateway/app/tool_provider_defaults.py` — **new.** `TOOL_PROVIDER_DEFAULTS: dict[str, ToolProviderDefault]` + `ToolProviderDefault` frozen dataclass. Single source of egress truth for the 4 types. (T1)
- `gateway/app/config_writer.py` — **modify.** Add `_find_tool_provider_entry`, `upsert_tool_provider`, `remove_tool_provider`, reuse `ProviderKeyMutationError`. (T1)
- `gateway/app/tool_provider_keys.py` — **new.** Service layer mirroring `provider_keys.py`: `list_tool_provider_status`, `apply_tool_provider`, `remove_tool_provider_entry`, `_swap_in_tool_adapter`. (T2)
- `gateway/app/api/admin.py` — **modify.** Add `/admin/v1/tool-providers[/{type}]` GET/POST/PATCH/DELETE + error-code map + strip `api_key_encrypted` in `_sanitized_config_payload`. (T2)
- `gateway/app/main.py` — **modify.** Add `app.state.tool_provider_key_lock` + `app.state.retired_tool_adapters` in the lifespan. (T2)

**API (`api/`)**
- `api/app/clients/gateway.py` — **modify.** Add `list_tool_providers_admin`, `set_tool_provider`, `patch_tool_provider`, `delete_tool_provider`. (T3)
- `api/app/api/admin.py` — **modify.** Add `/admin/tool-providers[/{type}]` handlers + request schemas. (T4)
- `api/tests/test_endpoints.py`, `api/tests/test_openapi.py` — **modify.** Collision guards. (T5)
- `docs/api/backend-openapi.generated.yaml` — **regenerated** via `make openapi`. (T5)

**Web (`web/`)**
- `web/src/lib/lq-ai/api/admin.ts` — **modify.** Add `ToolProviderStatus` type + `listToolProviders/setToolProvider/patchToolProvider/deleteToolProvider`. (T6)
- `web/src/routes/lq-ai/admin/research-sources/+page.svelte` — **new.** The card (mirrors `provider-keys/+page.svelte`). (T6)
- `web/src/routes/lq-ai/admin/+layout.svelte` — **modify.** Add the nav entry. (T6)

**Docs**
- `gateway.yaml.example` — **modify.** Add a one-line note pointing operators at the runtime path. (T2)
- `docs/PRD.md §9` — **modify.** File the DE-38x deferrals (D1 backfill, D7 a/b/c). (T5)

---

## Contract summary (the deliverable for Donna — spec §5)

| Verb | Path | Body | Success | Errors |
|---|---|---|---|---|
| GET | `/api/v1/admin/tool-providers` | — | `200` `[{type, enabled, name, has_key, key_required, egress_tier}]` (one per `SOURCE_REGISTRY` type) | 403 non-admin |
| POST | `/api/v1/admin/tool-providers` | `{type, api_key?}` | `200` single status row (enable/create from defaults; store key if given) | 400 no master key, 404 unknown type, 403 |
| PATCH | `/api/v1/admin/tool-providers/{type}` | `{api_key?, enabled?}` | `200` single status row (rotate key and/or toggle) | 400, 404, 409 env-key, 403 |
| DELETE | `/api/v1/admin/tool-providers/{type}` | — | `204` (remove entry + retire adapter) | 404, 409 env-key, 403 |

Gateway sibling routes: `GET/POST/PATCH/DELETE /admin/v1/tool-providers[/{type}]` (gateway-key guarded), returning `{tool_providers: [...]}` (GET) / single row (POST/PATCH) / 204 (DELETE).

---

## Task 1 — Gateway config_writer + default registry

**Files:**
- Create: `gateway/app/tool_provider_defaults.py`
- Modify: `gateway/app/config_writer.py` (add after `delete_provider_key`, before `__all__` at line ~540)
- Test: `gateway/tests/test_tool_provider_defaults.py` (new), `gateway/tests/test_config_writer_tool_providers.py` (new)

**Interfaces:**
- Consumes: `MutableConfigHolder` (`holder.config_path`, `holder.reload_from_disk`, `holder.current`), `ProviderKeyMutationError` (existing), `ConfigReloadError`, `_read_yaml_mapping`, `_atomic_write_yaml` (existing helpers).
- Produces:
  - `TOOL_PROVIDER_DEFAULTS: dict[str, ToolProviderDefault]` (keys: `"courtlistener"`, `"govinfo"`, `"edgar"`, `"eurlex"`).
  - `ToolProviderDefault(type: str, name: str, base_url: str, allowlist_hosts: tuple[str, ...], egress_tier: int, rate_limit_rpm: int, anonymize_outbound: bool, key_required: bool, api_key_env: str | None, user_agent: str | None)` — frozen dataclass.
  - `upsert_tool_provider(holder, *, provider_type: str, encrypted_token: str | None, enabled: bool = True) -> None`
  - `remove_tool_provider(holder, *, provider_type: str) -> None`
  - `_find_tool_provider_entry(raw, *, provider_type) -> dict | None` (None when absent — unlike the provider variant, absence is not 404 here because enable can create).

- [ ] **Step 1: Write the failing test for the default registry**

Create `gateway/tests/test_tool_provider_defaults.py`:

```python
"""TOOL_PROVIDER_DEFAULTS is the gateway-owned egress truth (ADR 0014)."""

from app.config import ToolProviderConfig
from app.tool_provider_defaults import TOOL_PROVIDER_DEFAULTS, ToolProviderDefault


def test_registry_covers_exactly_the_four_authority_types() -> None:
    assert set(TOOL_PROVIDER_DEFAULTS) == {"courtlistener", "govinfo", "edgar", "eurlex"}


def test_key_required_matches_source_semantics() -> None:
    assert TOOL_PROVIDER_DEFAULTS["courtlistener"].key_required is True
    assert TOOL_PROVIDER_DEFAULTS["govinfo"].key_required is True
    assert TOOL_PROVIDER_DEFAULTS["edgar"].key_required is False
    assert TOOL_PROVIDER_DEFAULTS["eurlex"].key_required is False


def test_keyless_sources_carry_a_default_user_agent() -> None:
    assert TOOL_PROVIDER_DEFAULTS["edgar"].user_agent
    assert TOOL_PROVIDER_DEFAULTS["eurlex"].user_agent


def test_every_default_builds_a_valid_tool_provider_config() -> None:
    # A default + a fake encrypted key (or keyless) must validate against
    # the real ToolProviderConfig model — proves the writer emits valid YAML.
    for d in TOOL_PROVIDER_DEFAULTS.values():
        entry: dict = {
            "name": d.name,
            "type": d.type,
            "base_url": d.base_url,
            "egress_tier": d.egress_tier,
            "allowlist": {"hosts": list(d.allowlist_hosts)},
            "rate_limit": {"requests_per_minute": d.rate_limit_rpm},
            "anonymize_outbound": d.anonymize_outbound,
        }
        if d.user_agent:
            entry["user_agent"] = d.user_agent
        if d.key_required:
            entry["api_key_encrypted"] = "gAAAAAB-fake"
        ToolProviderConfig.model_validate(entry)  # raises on malformation
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd gateway && .venv/bin/python -m pytest tests/test_tool_provider_defaults.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tool_provider_defaults'`.

- [ ] **Step 3: Create the default registry**

Create `gateway/app/tool_provider_defaults.py`. Values are copied verbatim from `gateway.yaml.example:207-258` (the shipped templates):

```python
"""Gateway-owned egress defaults for runtime-enableable tool providers.

The runtime admin API (`/admin/v1/tool-providers`) lets an operator enable a
registered authority source without hand-editing ``gateway.yaml``. To keep the
api service from ever setting an arbitrary egress target (SSRF, ADR 0014), the
**gateway** owns the base_url / allowlist / tier per type. The api passes only
``{type, api_key?, enabled?}``; this table fills everything else.

Values mirror the shipped ``gateway.yaml.example`` templates. An operator who
needs a different base_url / allowlist / User-Agent pre-adds the entry in
``gateway.yaml`` by hand; the writer then only touches the key fields on it.
"""

from __future__ import annotations

from dataclasses import dataclass

# Generic UA for the keyless sources (SEC fair-access / EUR-Lex both require a
# descriptive User-Agent, no API key). Operator-overridable via gateway.yaml.
_DEFAULT_USER_AGENT = "LQ.AI legal-research (self-hosted; set user_agent in gateway.yaml)"


@dataclass(frozen=True)
class ToolProviderDefault:
    """Immutable egress descriptor for one runtime-enableable tool provider."""

    type: str
    name: str  # canonical tool_providers[].name the writer creates
    base_url: str
    allowlist_hosts: tuple[str, ...]
    egress_tier: int
    rate_limit_rpm: int
    anonymize_outbound: bool
    key_required: bool
    api_key_env: str | None  # documented env var an operator MAY use instead
    user_agent: str | None


TOOL_PROVIDER_DEFAULTS: dict[str, ToolProviderDefault] = {
    "courtlistener": ToolProviderDefault(
        type="courtlistener",
        name="courtlistener-prod",
        base_url="https://www.courtlistener.com/api/rest/v4",
        allowlist_hosts=("www.courtlistener.com",),
        egress_tier=4,
        rate_limit_rpm=60,
        anonymize_outbound=True,
        key_required=True,
        api_key_env="COURTLISTENER_API_TOKEN",
        user_agent=None,
    ),
    "govinfo": ToolProviderDefault(
        type="govinfo",
        name="govinfo-prod",
        base_url="https://api.govinfo.gov",
        allowlist_hosts=("api.govinfo.gov",),
        egress_tier=4,
        rate_limit_rpm=60,
        anonymize_outbound=False,
        key_required=True,
        api_key_env="GOVINFO_API_KEY",
        user_agent=None,
    ),
    "edgar": ToolProviderDefault(
        type="edgar",
        name="edgar-prod",
        base_url="https://efts.sec.gov",
        allowlist_hosts=("efts.sec.gov", "www.sec.gov"),
        egress_tier=4,
        rate_limit_rpm=300,
        anonymize_outbound=False,
        key_required=False,
        api_key_env=None,
        user_agent=_DEFAULT_USER_AGENT,
    ),
    "eurlex": ToolProviderDefault(
        type="eurlex",
        name="eurlex-prod",
        base_url="https://publications.europa.eu",
        allowlist_hosts=("publications.europa.eu",),
        egress_tier=4,
        rate_limit_rpm=60,
        anonymize_outbound=False,
        key_required=False,
        api_key_env=None,
        user_agent=_DEFAULT_USER_AGENT,
    ),
}


__all__ = ["TOOL_PROVIDER_DEFAULTS", "ToolProviderDefault"]
```

- [ ] **Step 4: Run the registry test to green**

Run: `cd gateway && .venv/bin/python -m pytest tests/test_tool_provider_defaults.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Write the failing config_writer test**

Create `gateway/tests/test_config_writer_tool_providers.py`. Model it on the existing provider-key writer tests (find them: `grep -rl upsert_provider_key gateway/tests`). It needs a `MutableConfigHolder` over a temp `gateway.yaml`. Reuse the existing fixture that builds a holder from a temp file (grep `MutableConfigHolder(` in `gateway/tests`); if a `tmp_holder` fixture exists in `conftest.py`, use it — otherwise construct inline as below:

```python
import yaml
from app.config_holder import MutableConfigHolder
from app.config_writer import (
    ProviderKeyMutationError,
    remove_tool_provider,
    upsert_tool_provider,
)

_MINIMAL_CONFIG = {
    "providers": [
        {"name": "anthropic", "type": "anthropic", "base_url": "https://x",
         "api_key_env": "ANTHROPIC_API_KEY", "tier": 3, "models": ["claude"]},
    ],
    "model_aliases": {"fast": {"primary": {"provider": "anthropic", "model": "claude"},
                               "fallback": []}},
    "gateway_auth": {"enabled": False},
}


def _holder(tmp_path) -> MutableConfigHolder:
    p = tmp_path / "gateway.yaml"
    p.write_text(yaml.safe_dump(_MINIMAL_CONFIG), encoding="utf-8")
    return MutableConfigHolder(config_path=p)


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
    upsert_tool_provider(holder, provider_type="courtlistener",
                         encrypted_token="gAAAAAB-ciphertext")
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
    raw["tool_providers"] = [{
        "name": "courtlistener-prod", "type": "courtlistener",
        "base_url": "https://www.courtlistener.com/api/rest/v4",
        "api_key_env": "COURTLISTENER_API_TOKEN", "egress_tier": 4,
        "allowlist": {"hosts": ["www.courtlistener.com"]},
    }]
    holder.config_path.write_text(yaml.safe_dump(raw))
    holder.reload_from_disk()
    try:
        remove_tool_provider(holder, provider_type="courtlistener")
        raise AssertionError("expected 409")
    except ProviderKeyMutationError as exc:
        assert exc.http_status == 409
```

- [ ] **Step 6: Run it to confirm it fails**

Run: `cd gateway && .venv/bin/python -m pytest tests/test_config_writer_tool_providers.py -q`
Expected: FAIL — `ImportError: cannot import name 'upsert_tool_provider'`.

- [ ] **Step 7: Implement the writer functions**

In `gateway/app/config_writer.py`, add the import at the top (after the existing imports):

```python
from app.tool_provider_defaults import TOOL_PROVIDER_DEFAULTS
```

Add these functions after `delete_provider_key` (before `__all__`):

```python
# --- Tool-provider mutation API (runtime authority sources, ADR 0014) --------


def _find_tool_provider_entry(
    raw: dict[str, Any],
    *,
    provider_type: str,
) -> dict[str, Any] | None:
    """Return the ``tool_providers`` entry for ``provider_type``, or None.

    Unlike ``_find_provider_entry`` (inference), absence is NOT an error:
    the runtime enable path CREATES the entry when it's missing. We match on
    ``type`` (the admin surface is keyed by type; the writer owns the name).

    Raises :class:`ProviderKeyMutationError` 500 only when ``tool_providers``
    is present but not a list (malformed config).
    """

    providers = raw.get("tool_providers")
    if providers is None:
        return None
    if not isinstance(providers, list):
        raise ProviderKeyMutationError(
            "gateway.yaml tool_providers is malformed (expected a list)",
            http_status=500,
        )
    for entry in providers:
        if isinstance(entry, dict) and entry.get("type") == provider_type:
            return entry
    return None


def _tool_provider_entry_from_default(provider_type: str) -> dict[str, Any]:
    """Build a fresh ``tool_providers`` YAML block from the gateway defaults."""

    d = TOOL_PROVIDER_DEFAULTS[provider_type]
    entry: dict[str, Any] = {
        "name": d.name,
        "type": d.type,
        "base_url": d.base_url,
        "egress_tier": d.egress_tier,
        "allowlist": {"hosts": list(d.allowlist_hosts)},
        "rate_limit": {"requests_per_minute": d.rate_limit_rpm},
        "anonymize_outbound": d.anonymize_outbound,
    }
    if d.user_agent:
        entry["user_agent"] = d.user_agent
    return entry


def upsert_tool_provider(
    holder: MutableConfigHolder,
    *,
    provider_type: str,
    encrypted_token: str | None,
    enabled: bool = True,
) -> None:
    """Create/enable a tool-provider entry and set/rotate its runtime key.

    ``provider_type`` must be a key in ``TOOL_PROVIDER_DEFAULTS`` (else 404).
    If the entry is absent it's created from the gateway defaults (SSRF-safe;
    the api never supplies base_url/allowlist). ``encrypted_token`` is the
    Fernet ciphertext (set/rotate); ``None`` leaves the key untouched on an
    existing entry, or creates a keyless entry when none exists.

    Setting a runtime key switches the source to encrypted-at-rest: we set
    ``api_key_encrypted`` and drop ``api_key_env`` (the validator forbids
    both). Reload re-validates the whole file; on failure the file rolls back
    to the prior bytes and :class:`ConfigReloadError` re-raises.
    """

    if provider_type not in TOOL_PROVIDER_DEFAULTS:
        raise ProviderKeyMutationError(
            f"unknown tool-provider type {provider_type!r}",
            http_status=404,
        )

    raw = _read_yaml_mapping(holder.config_path)
    tool_providers = raw.get("tool_providers")
    if tool_providers is None:
        tool_providers = []
        raw["tool_providers"] = tool_providers
    elif not isinstance(tool_providers, list):
        raise ProviderKeyMutationError(
            "gateway.yaml tool_providers is malformed (expected a list)",
            http_status=500,
        )

    entry = _find_tool_provider_entry(raw, provider_type=provider_type)
    if entry is None:
        entry = _tool_provider_entry_from_default(provider_type)
        tool_providers.append(entry)

    entry["enabled"] = enabled
    if encrypted_token is not None:
        entry["api_key_encrypted"] = encrypted_token
        entry.pop("api_key_env", None)

    prior_bytes = holder.config_path.read_bytes()
    _atomic_write_yaml(holder.config_path, raw)
    try:
        holder.reload_from_disk()
    except ConfigReloadError:
        holder.config_path.write_bytes(prior_bytes)
        raise


def remove_tool_provider(
    holder: MutableConfigHolder,
    *,
    provider_type: str,
) -> None:
    """Remove a runtime-owned tool-provider entry and reload.

    404 if no entry of that type exists. 409 if the matched entry is
    env-sourced (``api_key_env`` set) — the runtime API only removes entries
    it owns (runtime-keyed or keyless); an operator's env-configured entry is
    theirs to remove in ``gateway.yaml``.
    """

    raw = _read_yaml_mapping(holder.config_path)
    entry = _find_tool_provider_entry(raw, provider_type=provider_type)
    if entry is None:
        raise ProviderKeyMutationError(
            f"tool provider of type {provider_type!r} not found",
            http_status=404,
        )
    if entry.get("api_key_env"):
        raise ProviderKeyMutationError(
            f"tool provider {provider_type!r} is env-configured and not "
            "runtime-revocable; edit gateway.yaml to remove it",
            http_status=409,
        )

    providers = raw["tool_providers"]
    raw["tool_providers"] = [e for e in providers if e is not entry]

    prior_bytes = holder.config_path.read_bytes()
    _atomic_write_yaml(holder.config_path, raw)
    try:
        holder.reload_from_disk()
    except ConfigReloadError:
        holder.config_path.write_bytes(prior_bytes)
        raise
```

Add the four names to `__all__`.

- [ ] **Step 8: Run both gateway writer test files to green**

Run: `cd gateway && .venv/bin/python -m pytest tests/test_tool_provider_defaults.py tests/test_config_writer_tool_providers.py -q`
Expected: PASS (all).

- [ ] **Step 9: Lint + type-check**

Run: `cd gateway && .venv/bin/ruff format app/tool_provider_defaults.py app/config_writer.py tests/test_tool_provider_defaults.py tests/test_config_writer_tool_providers.py && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/`
Expected: clean (gateway is `--strict`; annotate fully).

- [ ] **Step 10: Commit**

```bash
git add gateway/app/tool_provider_defaults.py gateway/app/config_writer.py \
        gateway/tests/test_tool_provider_defaults.py gateway/tests/test_config_writer_tool_providers.py
git commit -s -m "feat(gateway): tool-provider config writer + gateway-owned default registry

Runtime enable/disable of authority sources writes the tool_providers: block
from gateway-owned egress defaults (ADR 0014 SSRF-safe). Refs Donna #3.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2 — Gateway service layer + admin HTTP endpoints + hot-apply

**Files:**
- Create: `gateway/app/tool_provider_keys.py`
- Modify: `gateway/app/api/admin.py` (new endpoint block + error map + sanitizer strip), `gateway/app/main.py` (lifespan state)
- Modify: `gateway.yaml.example` (operator note)
- Test: `gateway/tests/test_tool_provider_keys.py` (new), `gateway/tests/test_admin_tool_providers.py` (new)

**Interfaces:**
- Consumes: `upsert_tool_provider` / `remove_tool_provider` (T1), `TOOL_PROVIDER_DEFAULTS` (T1), `encrypt_value` (`app.secrets`), `MASTER_KEY_ENV`, `build_tool_adapter` (`app.main`, lazy import), `app.state.tool_adapters`, `app.state.tool_provider_key_lock`, `app.state.retired_tool_adapters`.
- Produces:
  - `list_tool_provider_status(config, tool_adapters) -> list[dict]` — rows `{type, name, enabled, has_key, key_required, egress_tier, source}` for each `TOOL_PROVIDER_DEFAULTS` type.
  - `apply_tool_provider(*, holder, app_state, provider_type, encrypted_token, enabled) -> dict` — write + build + swap; returns the single status row.
  - `remove_tool_provider_entry(*, holder, app_state, provider_type) -> None` — remove + retire.
  - Gateway routes `GET/POST/PATCH/DELETE /admin/v1/tool-providers[/{type}]`.

- [ ] **Step 1: Add lifespan state (no test — infra)**

In `gateway/app/main.py`, in the lifespan next to the existing `provider_key_lock` / `retired_adapters` (around lines 300-308), add:

```python
    app.state.tool_provider_key_lock = asyncio.Lock()
    app.state.retired_tool_adapters = []
```

(Confirm `asyncio` is imported; the existing `provider_key_lock` already uses it.)

- [ ] **Step 2: Write the failing service-layer test**

Create `gateway/tests/test_tool_provider_keys.py`:

```python
"""Service layer: status rows + hot-apply for tool providers."""

from app.config import GatewayConfig
from app.tool_provider_keys import list_tool_provider_status


def _config_with(tool_providers: list[dict]) -> GatewayConfig:
    return GatewayConfig.model_validate({
        "providers": [{"name": "anthropic", "type": "anthropic", "base_url": "https://x",
                       "api_key_env": "ANTHROPIC_API_KEY", "tier": 3, "models": ["claude"]}],
        "model_aliases": {"fast": {"primary": {"provider": "anthropic", "model": "claude"},
                                   "fallback": []}},
        "gateway_auth": {"enabled": False},
        "tool_providers": tool_providers,
    })


def test_status_lists_all_four_types_even_when_none_configured() -> None:
    rows = list_tool_provider_status(_config_with([]), {})
    assert {r["type"] for r in rows} == {"courtlistener", "govinfo", "edgar", "eurlex"}
    assert all(r["enabled"] is False for r in rows)
    assert all(r["has_key"] is False for r in rows)
    # key_required flag comes from the gateway default registry
    by_type = {r["type"]: r for r in rows}
    assert by_type["courtlistener"]["key_required"] is True
    assert by_type["edgar"]["key_required"] is False


def test_status_enabled_reflects_live_adapter_presence() -> None:
    cfg = _config_with([{
        "name": "edgar-prod", "type": "edgar", "base_url": "https://efts.sec.gov",
        "egress_tier": 4, "allowlist": {"hosts": ["efts.sec.gov", "www.sec.gov"]},
        "user_agent": "x",
    }])
    # Adapter live in the registry (keyed by name) -> enabled True.
    rows = list_tool_provider_status(cfg, {"edgar-prod": object()})
    assert next(r for r in rows if r["type"] == "edgar")["enabled"] is True
    # Config present but no live adapter -> enabled False.
    rows2 = list_tool_provider_status(cfg, {})
    assert next(r for r in rows2 if r["type"] == "edgar")["enabled"] is False


def test_status_has_key_true_for_runtime_keyed_entry() -> None:
    cfg = _config_with([{
        "name": "courtlistener-prod", "type": "courtlistener",
        "base_url": "https://www.courtlistener.com/api/rest/v4",
        "egress_tier": 4, "allowlist": {"hosts": ["www.courtlistener.com"]},
        "api_key_encrypted": "gAAAAAB-x",
    }])
    row = next(r for r in list_tool_provider_status(cfg, {"courtlistener-prod": object()})
               if r["type"] == "courtlistener")
    assert row["has_key"] is True
    assert row["source"] == "runtime"


def test_status_never_contains_the_ciphertext() -> None:
    cfg = _config_with([{
        "name": "courtlistener-prod", "type": "courtlistener",
        "base_url": "https://www.courtlistener.com/api/rest/v4",
        "egress_tier": 4, "allowlist": {"hosts": ["www.courtlistener.com"]},
        "api_key_encrypted": "gAAAAAB-secret-ciphertext",
    }])
    text = repr(list_tool_provider_status(cfg, {}))
    for forbidden in ("api_key_encrypted", "gAAAAAB", "api_key"):
        assert forbidden not in text
```

- [ ] **Step 3: Run it to confirm it fails**

Run: `cd gateway && .venv/bin/python -m pytest tests/test_tool_provider_keys.py -q`
Expected: FAIL — module missing.

- [ ] **Step 4: Implement the service layer**

Create `gateway/app/tool_provider_keys.py`. Mirror `provider_keys.py` (`_swap_in_adapter`, `apply_provider_key`, `revoke_provider_key`, `provider_key_status`):

```python
"""Service layer for runtime tool-provider management (ADR 0014, Donna #3).

Mirrors ``provider_keys.py`` one layer down: it writes the ``tool_providers``
block via ``config_writer`` and hot-applies by rebuilding the tool adapter and
swapping it into ``app.state.tool_adapters`` in place. Because the Router holds
the SAME dict by reference, the swap is immediately live with no Router rebuild.

Secrets: status rows carry ``has_key: bool`` only — never the ciphertext or a
last4 (tool tokens are opaque; last4 would add leak surface for no UX gain).
"""

from __future__ import annotations

from typing import Any

from app.config import GatewayConfig
from app.config_writer import remove_tool_provider, upsert_tool_provider
from app.secrets import MASTER_KEY_ENV, encrypt_value
from app.tool_provider_defaults import TOOL_PROVIDER_DEFAULTS


def _source_of(entry: Any) -> str | None:
    if entry is None:
        return None
    if getattr(entry, "api_key_encrypted", None):
        return "runtime"
    if getattr(entry, "api_key_env", None):
        return "env"
    return None


def _status_row(
    *,
    provider_type: str,
    config: GatewayConfig,
    tool_adapters: dict[str, Any],
) -> dict[str, Any]:
    default = TOOL_PROVIDER_DEFAULTS[provider_type]
    entry = next(
        (tp for tp in config.tool_providers if tp.type == provider_type),
        None,
    )
    name = entry.name if entry is not None else default.name
    enabled = entry is not None and name in tool_adapters
    source = _source_of(entry)
    has_key = source is not None
    return {
        "type": provider_type,
        "name": name,
        "enabled": enabled,
        "has_key": has_key,
        "key_required": default.key_required,
        "egress_tier": entry.egress_tier if entry is not None else default.egress_tier,
        "source": source,
    }


def list_tool_provider_status(
    config: GatewayConfig,
    tool_adapters: dict[str, Any],
) -> list[dict[str, Any]]:
    """One secret-safe status row per registered authority type."""

    return [
        _status_row(provider_type=t, config=config, tool_adapters=tool_adapters)
        for t in TOOL_PROVIDER_DEFAULTS
    ]


def _swap_in_tool_adapter(
    *,
    app_state: Any,
    provider_name: str,
    new_adapter: Any | None,
) -> None:
    old = app_state.tool_adapters.pop(provider_name, None)
    if old is not None and old is not new_adapter:
        app_state.retired_tool_adapters.append(old)
    if new_adapter is not None:
        app_state.tool_adapters[provider_name] = new_adapter


def apply_tool_provider(
    *,
    holder: Any,
    app_state: Any,
    provider_type: str,
    encrypted_token: str | None,
    enabled: bool,
) -> dict[str, Any]:
    """Write the entry + hot-apply the adapter; return the status row."""

    upsert_tool_provider(
        holder,
        provider_type=provider_type,
        encrypted_token=encrypted_token,
        enabled=enabled,
    )

    from app.main import build_tool_adapter  # lazy — break main<->admin cycle

    config = holder.current()
    entry = next((tp for tp in config.tool_providers if tp.type == provider_type), None)
    new_adapter = None
    if entry is not None:
        try:
            new_adapter = build_tool_adapter(entry)
        except Exception:  # noqa: BLE001 — never leak key material into the log
            new_adapter = None
        _swap_in_tool_adapter(
            app_state=app_state, provider_name=entry.name, new_adapter=new_adapter
        )

    return _status_row(
        provider_type=provider_type, config=config, tool_adapters=app_state.tool_adapters
    )


def remove_tool_provider_entry(
    *,
    holder: Any,
    app_state: Any,
    provider_type: str,
) -> None:
    """Remove the entry + retire its live adapter."""

    config = holder.current()
    entry = next((tp for tp in config.tool_providers if tp.type == provider_type), None)
    remove_tool_provider(holder, provider_type=provider_type)  # 404/409 raise here
    if entry is not None:
        old = app_state.tool_adapters.pop(entry.name, None)
        if old is not None:
            app_state.retired_tool_adapters.append(old)


def encrypt_tool_provider_key(plaintext: str, *, master_key: str) -> str:
    """Thin wrapper over ``encrypt_value`` for symmetry with provider_keys."""

    return encrypt_value(plaintext, master_key=master_key)


__all__ = [
    "MASTER_KEY_ENV",
    "apply_tool_provider",
    "encrypt_tool_provider_key",
    "list_tool_provider_status",
    "remove_tool_provider_entry",
]
```

- [ ] **Step 5: Run service test to green**

Run: `cd gateway && .venv/bin/python -m pytest tests/test_tool_provider_keys.py -q`
Expected: PASS (4).

- [ ] **Step 6: Write the failing endpoint test**

Create `gateway/tests/test_admin_tool_providers.py`. Model it on the existing `test_admin_provider_keys` gateway test (grep for it: `grep -rl "admin/v1/provider-keys" gateway/tests`). Use the gateway app fixture (an httpx/ASGI test client with the gateway-key header) — reuse whatever the provider-key gateway test uses. Cover:

```python
# (Reuse the gateway test app + client fixture from the provider-key test.)
# All requests carry the X-LQ-AI-Gateway-Key header via that fixture.

def test_get_lists_four_types(client) -> None:
    r = client.get("/admin/v1/tool-providers")
    assert r.status_code == 200
    types = {row["type"] for row in r.json()["tool_providers"]}
    assert types == {"courtlistener", "govinfo", "edgar", "eurlex"}


def test_post_enable_keyless_hot_applies(client, monkeypatch) -> None:
    r = client.post("/admin/v1/tool-providers", json={"type": "edgar"})
    assert r.status_code == 200
    assert r.json()["type"] == "edgar"
    # enabled reflects the live adapter having been built + swapped in.
    g = client.get("/admin/v1/tool-providers").json()["tool_providers"]
    assert next(x for x in g if x["type"] == "edgar")["enabled"] is True


def test_post_keyed_without_master_key_is_400(client, monkeypatch) -> None:
    monkeypatch.delenv("LQ_AI_GATEWAY_MASTER_KEY", raising=False)
    r = client.post("/admin/v1/tool-providers", json={"type": "courtlistener",
                                                      "api_key": "cl-token"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "failed_precondition"


def test_post_unknown_type_is_404(client) -> None:
    r = client.post("/admin/v1/tool-providers", json={"type": "westlaw"})
    assert r.status_code == 404


def test_delete_removes_and_is_204(client) -> None:
    client.post("/admin/v1/tool-providers", json={"type": "edgar"})
    r = client.delete("/admin/v1/tool-providers/edgar")
    assert r.status_code == 204
    assert r.content == b""


def test_delete_absent_is_404(client) -> None:
    r = client.delete("/admin/v1/tool-providers/eurlex")
    assert r.status_code == 404


def test_no_response_ever_contains_ciphertext(client, monkeypatch) -> None:
    # Set a master key so the key path is exercised end-to-end.
    from app.secrets import generate_master_key
    monkeypatch.setenv("LQ_AI_GATEWAY_MASTER_KEY", generate_master_key())
    client.post("/admin/v1/tool-providers", json={"type": "govinfo", "api_key": "gv-secret"})
    body = client.get("/admin/v1/tool-providers").text
    for forbidden in ("gv-secret", "api_key_encrypted", "gAAAAAB"):
        assert forbidden not in body
```

- [ ] **Step 7: Implement the gateway endpoints + error map + sanitizer strip**

In `gateway/app/api/admin.py`:

(a) Extend the imports:

```python
from app.config_writer import (
    AliasMutationError,
    ProviderKeyMutationError,
    delete_alias,
    remove_tool_provider,   # noqa: F401 if only used via service layer
    update_tier_policy,
    upsert_alias,
    upsert_tool_provider,   # noqa: F401 if only used via service layer
)
from app.tool_provider_keys import (
    apply_tool_provider,
    list_tool_provider_status,
    remove_tool_provider_entry,
)
```

(b) Add request models near `ProviderKeySetRequest` (~line 196):

```python
class ToolProviderSetRequest(BaseModel):
    """``POST /admin/v1/tool-providers`` body."""

    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=1)
    api_key: str | None = Field(default=None, min_length=1)


class ToolProviderPatchRequest(BaseModel):
    """``PATCH /admin/v1/tool-providers/{type}`` body."""

    model_config = ConfigDict(extra="forbid")
    api_key: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None
```

(c) Add the endpoints after the provider-key block (reuse `_provider_key_error_code`, `_gateway_error`, `_resolved_master_key`, `MASTER_KEY_ENV`):

```python
@router.get("/tool-providers")
async def list_tool_providers_endpoint(request: Request) -> dict[str, Any]:
    config = _config(request)
    rows = list_tool_provider_status(config, request.app.state.tool_adapters)
    return {"tool_providers": rows}


async def _apply_tool_provider_request(
    request: Request,
    *,
    provider_type: str,
    plaintext: str | None,
    enabled: bool,
) -> dict[str, Any] | JSONResponse:
    encrypted_token: str | None = None
    if plaintext is not None:
        master_key = _resolved_master_key()
        if not master_key:
            return _gateway_error(
                code="failed_precondition",
                message=f"runtime key storage requires {MASTER_KEY_ENV} to be set",
                http_status=status.HTTP_400_BAD_REQUEST,
                details={"type": provider_type},
            )
        encrypted_token = encrypt_value(plaintext, master_key=master_key)

    holder = _holder(request)
    async with request.app.state.tool_provider_key_lock:
        try:
            return await run_in_threadpool(
                apply_tool_provider,
                holder=holder,
                app_state=request.app.state,
                provider_type=provider_type,
                encrypted_token=encrypted_token,
                enabled=enabled,
            )
        except ProviderKeyMutationError as exc:
            return _gateway_error(
                code=_provider_key_error_code(exc),
                message=str(exc),
                http_status=exc.http_status,
                details={"type": provider_type},
            )
        except ConfigReloadError as exc:
            return _gateway_error(
                code="invalid_request",
                message=str(exc),
                http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"type": provider_type},
            )


@router.post("/tool-providers", response_model=None)
async def enable_tool_provider(
    request: Request,
    body: ToolProviderSetRequest,
) -> dict[str, Any] | JSONResponse:
    return await _apply_tool_provider_request(
        request, provider_type=body.type, plaintext=body.api_key, enabled=True
    )


@router.patch("/tool-providers/{provider_type}", response_model=None)
async def patch_tool_provider(
    request: Request,
    provider_type: str,
    body: ToolProviderPatchRequest,
) -> dict[str, Any] | JSONResponse:
    # enabled=False routes to the remove path (D3: disable == remove entry).
    if body.enabled is False:
        return await _delete_tool_provider(request, provider_type=provider_type)
    return await _apply_tool_provider_request(
        request, provider_type=provider_type, plaintext=body.api_key, enabled=True
    )


async def _delete_tool_provider(
    request: Request,
    *,
    provider_type: str,
) -> Response | JSONResponse:
    holder = _holder(request)
    async with request.app.state.tool_provider_key_lock:
        try:
            await run_in_threadpool(
                remove_tool_provider_entry,
                holder=holder,
                app_state=request.app.state,
                provider_type=provider_type,
            )
        except ProviderKeyMutationError as exc:
            return _gateway_error(
                code=_provider_key_error_code(exc),
                message=str(exc),
                http_status=exc.http_status,
                details={"type": provider_type},
            )
        except ConfigReloadError as exc:
            return _gateway_error(
                code="invalid_request",
                message=str(exc),
                http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"type": provider_type},
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/tool-providers/{provider_type}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def disable_tool_provider(
    request: Request,
    provider_type: str,
) -> Response | JSONResponse:
    return await _delete_tool_provider(request, provider_type=provider_type)
```

> **Note on `run_in_threadpool`:** the writer does blocking file I/O + reload. If the existing provider-key path calls `apply_provider_key` directly under `async` (not via threadpool), match that — check `_apply_provider_key_request`; the agent's extract showed a direct `await apply_provider_key(...)`, so `apply_provider_key` is `async`. **Make `apply_tool_provider` / `remove_tool_provider_entry` `async def`** to match, and drop `run_in_threadpool` (call `await apply_tool_provider(...)`). Pick ONE style consistent with the provider-key path and delete the mismatched note. *(Implementer: verify against `provider_keys.py` and mirror exactly.)*

(d) Harden the sanitizer (D7c) — in `_sanitized_config_payload` (~line 145), strip `api_key_encrypted` from every provider list:

```python
def _sanitized_config_payload(config: GatewayConfig) -> dict[str, Any]:
    payload = config.model_dump(mode="json")
    for key in ("providers", "tool_providers"):
        for entry in payload.get(key, []) or []:
            if isinstance(entry, dict):
                entry.pop("api_key_encrypted", None)
    return payload
```

- [ ] **Step 8: Run the endpoint tests to green**

Run: `cd gateway && .venv/bin/python -m pytest tests/test_admin_tool_providers.py tests/test_tool_provider_keys.py -q`
Expected: PASS. If `build_tool_adapter` for `edgar` needs network at build time, stub it (monkeypatch `app.main.build_tool_adapter` to return a sentinel) — verify how the provider-key test handles `build_adapter`.

- [ ] **Step 9: Add the operator note to `gateway.yaml.example`**

In the `tool_providers:` comment header (line ~205), append one line:

```yaml
# Runtime alternative: enable these from the app (Settings → Research sources)
# or POST /api/v1/admin/tool-providers — no YAML edit or restart needed.
```

- [ ] **Step 10: Full gateway suite + lint + strict mypy**

Run: `cd gateway && .venv/bin/ruff format app/ tests/ && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/ && .venv/bin/python -m pytest -q`
Expected: PASS, no coverage decrease.

- [ ] **Step 11: Commit**

```bash
git add gateway/app/tool_provider_keys.py gateway/app/api/admin.py gateway/app/main.py \
        gateway.yaml.example gateway/tests/test_tool_provider_keys.py gateway/tests/test_admin_tool_providers.py
git commit -s -m "feat(gateway): /admin/v1/tool-providers endpoints + hot-apply

Enable/disable authority sources at runtime; rebuild + in-place swap the tool
adapter so the change is live with no restart. Strip api_key_encrypted from
GET /admin/v1/config. Refs Donna #3.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3 — GatewayClient methods (api → gateway)

**Files:**
- Modify: `api/app/clients/gateway.py` (add after `delete_provider_key`, ~line 957)
- Test: `api/tests/test_gateway_client_tool_providers.py` (new)

**Interfaces:**
- Consumes: `self._admin_request` (existing shared transport).
- Produces:
  - `async list_tool_providers_admin(*, request_id=None) -> dict[str, Any]` → `GET /admin/v1/tool-providers`.
  - `async set_tool_provider(body: dict, *, request_id=None) -> dict[str, Any]` → `POST /admin/v1/tool-providers`.
  - `async patch_tool_provider(provider_type: str, body: dict, *, request_id=None) -> dict[str, Any]` → `PATCH /admin/v1/tool-providers/{type}`.
  - `async delete_tool_provider(provider_type: str, *, request_id=None) -> None` → `DELETE …/{type}` (`allow_204=True`).

> **Naming note:** the existing `list_tool_providers` (returns `[{name,type}]` from `GET /admin/v1/config`) stays untouched — it's the capabilities-signal reader. The new admin method is `list_tool_providers_admin` to avoid a clash.

- [ ] **Step 1: Write the failing test** (respx-mocked, mirror `test_gateway_client` provider-key tests — grep `set_provider_key` in `api/tests`):

```python
import httpx
import pytest
import respx
from app.clients.gateway import GatewayClient

BASE = "http://gw"


@pytest.fixture
def client() -> GatewayClient:
    return GatewayClient(base_url=BASE, gateway_key="k")


@respx.mock
@pytest.mark.asyncio
async def test_list_tool_providers_admin(client: GatewayClient) -> None:
    route = respx.get(f"{BASE}/admin/v1/tool-providers").mock(
        return_value=httpx.Response(200, json={"tool_providers": [{"type": "edgar"}]})
    )
    out = await client.list_tool_providers_admin()
    assert route.called
    assert out["tool_providers"][0]["type"] == "edgar"


@respx.mock
@pytest.mark.asyncio
async def test_set_tool_provider_posts_body(client: GatewayClient) -> None:
    route = respx.post(f"{BASE}/admin/v1/tool-providers").mock(
        return_value=httpx.Response(200, json={"type": "courtlistener", "enabled": True})
    )
    out = await client.set_tool_provider({"type": "courtlistener", "api_key": "x"})
    assert route.called
    assert out["enabled"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_tool_provider_allows_204(client: GatewayClient) -> None:
    route = respx.delete(f"{BASE}/admin/v1/tool-providers/edgar").mock(
        return_value=httpx.Response(204)
    )
    await client.delete_tool_provider("edgar")
    assert route.called
```

- [ ] **Step 2: Run to confirm fail**

Run: `cd api && .venv/bin/python -m pytest tests/test_gateway_client_tool_providers.py -q`
Expected: FAIL — attribute missing.

- [ ] **Step 3: Implement the four methods** (after `delete_provider_key`, ~line 957):

```python
    # --- Admin: tool-provider CRUD (Donna #3) -------------------------------

    async def list_tool_providers_admin(
        self,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """GET /admin/v1/tool-providers. Secret-safe status per authority type.

        Rows: ``{type, name, enabled, has_key, key_required, egress_tier, source}``
        — never a key. Distinct from :meth:`list_tool_providers` (the sanitized
        capabilities reader off ``/admin/v1/config``).
        """

        return await self._admin_request(
            method="GET",
            path="/admin/v1/tool-providers",
            op="list_tool_providers_admin",
            request_id=request_id,
        )

    async def set_tool_provider(
        self,
        body: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /admin/v1/tool-providers. Enable a type + optionally set a key.

        400 (``failed_precondition``) when the gateway master key is unset and a
        key was supplied; 404 (``not_found``) for an unregistered type.
        """

        return await self._admin_request(
            method="POST",
            path="/admin/v1/tool-providers",
            op="set_tool_provider",
            request_id=request_id,
            body=body,
        )

    async def patch_tool_provider(
        self,
        provider_type: str,
        body: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """PATCH /admin/v1/tool-providers/{type}. Rotate key and/or toggle."""

        return await self._admin_request(
            method="PATCH",
            path=f"/admin/v1/tool-providers/{provider_type}",
            op="patch_tool_provider",
            request_id=request_id,
            body=body,
        )

    async def delete_tool_provider(
        self,
        provider_type: str,
        *,
        request_id: str | None = None,
    ) -> None:
        """DELETE /admin/v1/tool-providers/{type}. Remove entry + retire adapter.

        404 unknown/absent type; 409 when the entry is env-configured (not
        runtime-revocable). 204 on success.
        """

        await self._admin_request(
            method="DELETE",
            path=f"/admin/v1/tool-providers/{provider_type}",
            op="delete_tool_provider",
            request_id=request_id,
            allow_204=True,
        )
```

- [ ] **Step 4: Run to green**

Run: `cd api && .venv/bin/python -m pytest tests/test_gateway_client_tool_providers.py -q`
Expected: PASS (3).

- [ ] **Step 5: Lint + type-check**

Run: `cd api && .venv/bin/ruff format app/clients/gateway.py tests/test_gateway_client_tool_providers.py && .venv/bin/ruff check app/ && .venv/bin/mypy app/clients/gateway.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add api/app/clients/gateway.py api/tests/test_gateway_client_tool_providers.py
git commit -s -m "feat(api): GatewayClient tool-provider admin methods

Refs Donna #3.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4 — API admin endpoints (thin proxy + audit)

**Files:**
- Modify: `api/app/api/admin.py` (add after `revoke_provider_key`, ~line 648)
- Test: `api/tests/test_admin_tool_providers.py` (new) — mirror `api/tests/test_admin_provider_keys.py`

**Interfaces:**
- Consumes: `AdminUser`, `GatewayClient` methods from T3, `audit_action` (`app.audit`), `get_db`, `Request`.
- Produces: `GET/POST/PATCH/DELETE /api/v1/admin/tool-providers[/{type}]`. GET returns the reshaped list `[{type, enabled, name, has_key, key_required, egress_tier}]`; POST/PATCH return one row; DELETE 204.

**Validation:** POST/PATCH/DELETE pre-validate `type ∈ SOURCE_REGISTRY` for a fast, gateway-independent 404 (spec §5). Import the registry keys:

```python
from app.research.registry import SOURCE_REGISTRY
```

- [ ] **Step 1: Write the failing endpoint tests.** Mirror `test_admin_provider_keys.py` (reuse its app/client/admin-auth fixtures + `_assert_no_secret`). The gateway client is respx-mocked or a fake injected via `set_gateway_client`. Cover: admin-gated (non-admin → 403); GET shape; POST enable; 404 unknown type (before hitting the gateway); secret never returned; an **audit row written** on POST/PATCH/DELETE; DELETE → 204 empty body; hot-apply integration proof (see Step 5).

```python
def test_get_requires_admin(client, non_admin_token) -> None:
    r = client.get("/api/v1/admin/tool-providers", headers={"Authorization": f"Bearer {non_admin_token}"})
    assert r.status_code == 403


def test_post_unknown_type_is_404_without_calling_gateway(client, admin_headers, fake_gateway) -> None:
    r = client.post("/api/v1/admin/tool-providers", json={"type": "westlaw"}, headers=admin_headers)
    assert r.status_code == 404
    assert not fake_gateway.set_tool_provider.called  # short-circuited on the registry check


def test_post_enable_writes_audit_row(client, admin_headers, db_session, fake_gateway) -> None:
    fake_gateway.set_tool_provider.return_value = {"type": "edgar", "enabled": True,
        "name": "edgar-prod", "has_key": False, "key_required": False, "egress_tier": 4}
    r = client.post("/api/v1/admin/tool-providers", json={"type": "edgar"}, headers=admin_headers)
    assert r.status_code == 200
    _assert_no_secret(r.json())
    rows = db_session.execute(select(AuditLog).where(AuditLog.action == "tool_provider.enabled")).scalars().all()
    assert len(rows) == 1 and rows[0].resource_id == "edgar"


def test_delete_is_204_empty(client, admin_headers, fake_gateway) -> None:
    r = client.delete("/api/v1/admin/tool-providers/edgar", headers=admin_headers)
    assert r.status_code == 204
    assert r.content == b""
```

- [ ] **Step 2: Run to confirm fail**

Run: `cd api && .venv/bin/python -m pytest tests/test_admin_tool_providers.py -q`
Expected: FAIL — 404 routes (not yet registered).

- [ ] **Step 3: Add request schemas** near `ProviderKeySetRequest` (admin.py ~line 584):

```python
class ToolProviderSetRequest(BaseModel):
    """Request body for ``POST /api/v1/admin/tool-providers``."""

    type: str = Field(min_length=1)
    api_key: str | None = Field(default=None, min_length=1)


class ToolProviderPatchRequest(BaseModel):
    """Request body for ``PATCH /api/v1/admin/tool-providers/{type}``."""

    api_key: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None
```

- [ ] **Step 4: Add the four handlers** (after `revoke_provider_key`). Note: unlike provider-keys, these take `admin: AdminUser` (non-underscore, for the actor id), `request: Request`, and `db` for auditing (D1):

```python
def _reshape_tool_provider_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project the gateway status row to the public contract (spec §5)."""

    return {
        "type": row["type"],
        "enabled": row["enabled"],
        "name": row.get("name"),
        "has_key": row["has_key"],
        "key_required": row["key_required"],
        "egress_tier": row.get("egress_tier"),
    }


@router.get("/tool-providers")
async def list_tool_providers(
    _admin: AdminUser,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> dict[str, Any]:
    """List authority-source status via the gateway. No secret is returned."""

    result = await gateway.list_tool_providers_admin()
    return {
        "tool_providers": [
            _reshape_tool_provider_row(row) for row in result.get("tool_providers", [])
        ]
    }


@router.post("/tool-providers")
async def set_tool_provider(
    body: ToolProviderSetRequest,
    admin: AdminUser,
    request: Request,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Enable an authority source (+optional key). 400/404 propagate from gateway."""

    if body.type not in SOURCE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"unknown source type {body.type!r}")
    row = await gateway.set_tool_provider(body.model_dump(mode="json", exclude_none=True))
    from app.audit import audit_action

    await audit_action(
        db,
        user_id=admin.id,
        action="tool_provider.enabled",
        resource_type="tool_provider",
        resource_id=body.type,
        request=request,
        details={"has_key_supplied": body.api_key is not None},
    )
    await db.commit()
    return _reshape_tool_provider_row(row)


@router.patch("/tool-providers/{provider_type}")
async def patch_tool_provider(
    provider_type: str,
    body: ToolProviderPatchRequest,
    admin: AdminUser,
    request: Request,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Rotate key and/or toggle enabled. 400/404/409 propagate from gateway."""

    if provider_type not in SOURCE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"unknown source type {provider_type!r}")
    row = await gateway.patch_tool_provider(
        provider_type, body.model_dump(mode="json", exclude_none=True)
    )
    from app.audit import audit_action

    await audit_action(
        db,
        user_id=admin.id,
        action="tool_provider.updated",
        resource_type="tool_provider",
        resource_id=provider_type,
        request=request,
        details={
            "has_key_supplied": body.api_key is not None,
            "enabled": body.enabled,
        },
    )
    await db.commit()
    return _reshape_tool_provider_row(row)


@router.delete(
    "/tool-providers/{provider_type}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def disable_tool_provider(
    provider_type: str,
    admin: AdminUser,
    request: Request,
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Disable an authority source. 404/409 propagate from the gateway."""

    if provider_type not in SOURCE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"unknown source type {provider_type!r}")
    await gateway.delete_tool_provider(provider_type)
    from app.audit import audit_action

    await audit_action(
        db,
        user_id=admin.id,
        action="tool_provider.disabled",
        resource_type="tool_provider",
        resource_id=provider_type,
        request=request,
        details={},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

> **Audit-vs-gateway-failure ordering:** the audit row is written *after* the gateway call succeeds (a failed gateway call raises before the audit line, so we never record a change that didn't happen). This matches `update_tier_policy`.

- [ ] **Step 5: Add the hot-apply integration proof.** In `test_admin_tool_providers.py`, add a test that uses a **real (respx-backed) gateway** wired so that after `POST /api/v1/admin/tool-providers {type: courtlistener, api_key: X}`, a subsequent `GET /api/v1/research/sources` shows `courtlistener` `enabled=true`. If a full gateway round-trip isn't feasible in the api suite, assert the proxy called `gateway.set_tool_provider` with the right body AND add the true end-to-end proof to the gateway suite (T2 Step 6 already proves hot-apply at the gateway boundary). Document which layer proves it.

- [ ] **Step 6: Run to green + full api suite**

Run: `cd api && DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/postgres" .venv/bin/python -m pytest tests/test_admin_tool_providers.py -q`
Then the guard-sensitive files: `cd api && DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/postgres" .venv/bin/python -m pytest tests/test_endpoints.py tests/test_openapi.py -q`
Expected: `test_admin_tool_providers` PASS; the two guard files will **FAIL** here — that's T5's job. (If the throwaway PG on :55432 is down: `docker start lqai-test-pg`, or point DATABASE_URL at the running `tn-testpg` on :5432.)

- [ ] **Step 7: Commit**

```bash
git add api/app/api/admin.py api/tests/test_admin_tool_providers.py
git commit -s -m "feat(api): /api/v1/admin/tool-providers admin proxy (audited)

AdminUser-gated thin proxy to the gateway tool-provider surface; audit_log row
on every write (D1). Secrets write-only. Refs Donna #3.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5 — Collision guards + OpenAPI regen + DE filings

**Files:**
- Modify: `api/tests/test_endpoints.py` (`IMPLEMENTED_ROUTES`, `_PARAM_VALUES`)
- Modify: `api/tests/test_openapi.py` (count `137 → 139`, `EXPECTED_PATHS`)
- Regenerate: `docs/api/backend-openapi.generated.yaml` (via `make openapi`)
- Modify: `docs/PRD.md §9` (DE filings)

**Interfaces:** none (test + doc changes).

> **Path math:** 4 routes, **2 unique paths** (`/api/v1/admin/tool-providers`, `/api/v1/admin/tool-providers/{type}`). Count `137 → 139`.

- [ ] **Step 1: Add the four route tuples** to `IMPLEMENTED_ROUTES` (`api/tests/test_endpoints.py`, after the provider-keys block ~line 197):

```python
    # Donna #3 — runtime tool/authority-provider admin proxy
    ("GET", "/api/v1/admin/tool-providers"),
    ("POST", "/api/v1/admin/tool-providers"),
    ("PATCH", "/api/v1/admin/tool-providers/{type}"),
    ("DELETE", "/api/v1/admin/tool-providers/{type}"),
```

- [ ] **Step 2: Add the `{type}` param value** to `_PARAM_VALUES` (~lines 50-78) so `_materialise` can substitute it:

```python
    "type": "courtlistener",
```

(If `{type}` collides with another route's meaning, use the actual param name the handlers declare — the plan uses `{provider_type}` in code but the registered OpenAPI path renders as `{provider_type}`. **Match the tuple path string to the actual registered path** — if FastAPI registers `/tool-providers/{provider_type}`, the tuples and `EXPECTED_PATHS` must say `{provider_type}`, and `_PARAM_VALUES` needs `"provider_type"`. Verify with `app.routes` before pinning.)

- [ ] **Step 3: Bump the count + add paths** in `api/tests/test_openapi.py`:
  - Line 339: `assert len(actual) == 137` → `139`.
  - In `EXPECTED_PATHS` (after the provider-keys entries ~line 139):

```python
        # Donna #3 — runtime tool/authority-provider admin proxy
        "/api/v1/admin/tool-providers",
        "/api/v1/admin/tool-providers/{provider_type}",
```

  - Add a running-math comment in the block at lines 241-338: `# Donna #3 adds two new paths (137 -> 139)`.

- [ ] **Step 4: Regenerate the OpenAPI export**

Run: `cd /Users/kevinkeller/Code/lq-ai && make openapi`
Expected: `docs/api/backend-openapi.generated.yaml` updated with the two new paths.

- [ ] **Step 5: Run the guard + drift tests to green**

Run: `cd api && DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/postgres" .venv/bin/python -m pytest tests/test_endpoints.py tests/test_openapi.py tests/test_openapi_export.py -q`
Expected: PASS (count matches, paths present, no drift).

- [ ] **Step 6: File the DEs** in `docs/PRD.md §9`:
  - **DE-38x (D1 backfill):** provider-key admin writes don't emit audit rows; backfill to match tool-providers.
  - **DE-38x (D7a):** hot-enabled tool provider's rate limit isn't enforced until gateway restart (Router `_tool_rate_limiter` is construction-time).
  - **DE-38x (D7b):** `resolve_available_sources` reports `enabled` off entry presence, ignoring the entry `enabled` flag.

  Use the next free DE numbers (grep `DE-3` in `docs/PRD.md` for the max). One paragraph each.

- [ ] **Step 7: Commit**

```bash
git add api/tests/test_endpoints.py api/tests/test_openapi.py \
        docs/api/backend-openapi.generated.yaml docs/PRD.md
git commit -s -m "test(api): collision guards + OpenAPI for tool-providers; file DEs

Two new paths (137 -> 139). Regenerate backend-openapi.generated.yaml.
File DE-38x (provider-key audit backfill; rate-limit hot-refresh; enabled-flag).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6 — Web "Research sources" card

**Files:**
- Modify: `web/src/lib/lq-ai/api/admin.ts` (types + 4 functions)
- Create: `web/src/routes/lq-ai/admin/research-sources/+page.svelte`
- Modify: `web/src/routes/lq-ai/admin/+layout.svelte` (nav entry)

**Interfaces:**
- Consumes: `apiRequest` from `./client`; `adminApi` barrel.
- Produces: `ToolProviderStatus` type + `listToolProviders/setToolProvider/patchToolProvider/deleteToolProvider`; the route page; the nav link.

- [ ] **Step 1: Add the API client functions** to `web/src/lib/lq-ai/api/admin.ts` (after the provider-key block ~line 141):

```ts
export interface ToolProviderStatus {
	type: string;
	enabled: boolean;
	name: string | null;
	/** Whether a runtime/env key is present. Never the key itself. */
	has_key: boolean;
	/** Whether this source needs an API key (CourtListener/GovInfo) or is keyless (EDGAR/EUR-Lex). */
	key_required: boolean;
	egress_tier: number | null;
}

export interface ToolProviderListResponse {
	tool_providers: ToolProviderStatus[];
}

export async function listToolProviders(): Promise<ToolProviderListResponse> {
	return apiRequest<ToolProviderListResponse>('/admin/tool-providers');
}

/** Enable a source, optionally with a key. */
export async function setToolProvider(type: string, apiKey?: string): Promise<ToolProviderStatus> {
	const body: Record<string, unknown> = { type };
	if (apiKey) body.api_key = apiKey;
	return apiRequest<ToolProviderStatus>('/admin/tool-providers', { method: 'POST', body });
}

/** Rotate a source's key. */
export async function patchToolProvider(type: string, apiKey: string): Promise<ToolProviderStatus> {
	return apiRequest<ToolProviderStatus>(`/admin/tool-providers/${encodeURIComponent(type)}`, {
		method: 'PATCH',
		body: { api_key: apiKey }
	});
}

/** Disable a source (removes the entry + retires the live adapter). 204 on success. */
export async function deleteToolProvider(type: string): Promise<void> {
	return apiRequest<void>(`/admin/tool-providers/${encodeURIComponent(type)}`, {
		method: 'DELETE'
	});
}
```

- [ ] **Step 2: Create the card page** `web/src/routes/lq-ai/admin/research-sources/+page.svelte`. Mirror `provider-keys/+page.svelte` structure, tokens, and inline-string style. A source-label map gives lawyer-facing names:

```svelte
<script lang="ts">
	/**
	 * /lq-ai/admin/research-sources — in-app enable/disable of the fiduciary-grade
	 * authority sources (CourtListener, GovInfo, EDGAR, EUR-Lex). Mirrors the
	 * Provider keys card one layer down: hot-applied, secrets write-only.
	 */
	import { onMount } from 'svelte';
	import { adminApi } from '$lib/lq-ai/api';
	import { LQAIApiError } from '$lib/lq-ai/api/client';
	import type { ToolProviderStatus } from '$lib/lq-ai/api/admin';

	const LABELS: Record<string, string> = {
		courtlistener: 'CourtListener (U.S. case law)',
		govinfo: 'GovInfo (U.S. Code + CFR)',
		edgar: 'SEC EDGAR (company filings)',
		eurlex: 'EUR-Lex (EU law + CJEU)'
	};

	let rows: ToolProviderStatus[] = [];
	let loading = false;
	let listError: string | null = null;
	let actionError: string | null = null;
	let actionSuccess: string | null = null;

	let editing: string | null = null;
	let draftKey = '';
	let saving = false;
	let toggling: string | null = null;

	onMount(load);

	async function load(): Promise<void> {
		loading = true;
		listError = null;
		try {
			rows = (await adminApi.listToolProviders()).tool_providers;
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 403) {
				listError = 'You need admin access to manage research sources.';
			} else {
				listError = err instanceof Error ? err.message : String(err);
			}
		} finally {
			loading = false;
		}
	}

	function label(type: string): string {
		return LABELS[type] ?? type;
	}

	function startEdit(type: string): void {
		editing = type;
		draftKey = '';
		actionError = null;
		actionSuccess = null;
	}

	function cancelEdit(): void {
		editing = null;
		draftKey = '';
	}

	function describeError(err: unknown): string {
		if (err instanceof LQAIApiError) {
			if (err.status === 403) return 'You need admin access to manage research sources.';
			if (err.status === 400)
				return 'This gateway has runtime key storage disabled (no master key set).';
			if (err.status === 404) return 'That source is not available on this gateway.';
			if (err.status === 409)
				return 'That source is configured via the environment; edit gateway.yaml to change it.';
		}
		return err instanceof Error ? err.message : String(err);
	}

	async function enableKeyless(type: string): Promise<void> {
		toggling = type;
		actionError = null;
		actionSuccess = null;
		try {
			await adminApi.setToolProvider(type);
			actionSuccess = `Enabled ${label(type)}. It is hot-applied — research uses it now.`;
			await load();
		} catch (err) {
			actionError = describeError(err);
		} finally {
			toggling = null;
		}
	}

	async function saveKey(type: string): Promise<void> {
		const key = draftKey.trim();
		if (!key) {
			actionError = 'Paste a key first.';
			return;
		}
		if (/\s/.test(key)) {
			actionError = 'That key contains a space — paste just the key.';
			return;
		}
		saving = true;
		actionError = null;
		actionSuccess = null;
		try {
			await adminApi.setToolProvider(type, key);
			actionSuccess = `Saved a key for ${label(type)}. It is hot-applied.`;
			cancelEdit();
			await load();
		} catch (err) {
			actionError = describeError(err);
		} finally {
			saving = false;
		}
	}

	async function disable(type: string): Promise<void> {
		if (!confirm(`Disable ${label(type)}? Research will stop using it.`)) return;
		toggling = type;
		actionError = null;
		actionSuccess = null;
		try {
			await adminApi.deleteToolProvider(type);
			actionSuccess = `Disabled ${label(type)}.`;
			await load();
		} catch (err) {
			actionError = describeError(err);
		} finally {
			toggling = null;
		}
	}

	$: busy = saving || toggling !== null;
</script>

<div class="research-sources-page">
	<header class="page-header">
		<h1 class="lq-text-page-h">Research sources</h1>
		<p class="page-intro">
			Enable the authority sources LQ.AI can cite. Keys are stored encrypted and never shown.
			Changes apply immediately — no restart.
		</p>
	</header>

	{#if listError}<div class="error-banner" role="alert">{listError}</div>{/if}
	{#if actionError}<div class="error-banner" role="alert">{actionError}</div>{/if}
	{#if actionSuccess}<div class="success-banner" role="status">{actionSuccess}</div>{/if}

	{#if loading && rows.length === 0}<p class="loading">Loading research sources…</p>{/if}

	{#if rows.length > 0}
		<table class="keys-table">
			<thead>
				<tr>
					<th>Source</th>
					<th>Status</th>
					<th>Key</th>
					<th class="keys-table-actions">Actions</th>
				</tr>
			</thead>
			<tbody>
				{#each rows as row (row.type)}
					<tr>
						<td>{label(row.type)}</td>
						<td>
							{#if row.enabled}
								<span class="badge badge-runtime">Available</span>
							{:else}
								<span class="muted">Unavailable</span>
							{/if}
						</td>
						<td>
							{#if !row.key_required}
								<span class="muted">No key needed</span>
							{:else if row.has_key}
								<span class="badge badge-runtime">Key set</span>
							{:else}
								<span class="muted">No key</span>
							{/if}
						</td>
						<td class="keys-table-actions">
							{#if row.key_required}
								<button type="button" class="action-button" on:click={() => startEdit(row.type)} disabled={busy}>
									{row.has_key ? 'Replace key' : 'Set key'}
								</button>
							{:else if !row.enabled}
								<button type="button" class="action-button" on:click={() => enableKeyless(row.type)} disabled={busy}>
									{toggling === row.type ? 'Enabling…' : 'Enable'}
								</button>
							{/if}
							{#if row.enabled}
								<button type="button" class="action-button danger" on:click={() => disable(row.type)} disabled={busy}>
									{toggling === row.type ? 'Disabling…' : 'Disable'}
								</button>
							{/if}
						</td>
					</tr>
					{#if editing === row.type}
						<tr class="edit-row">
							<td colspan="4">
								<div class="edit-form">
									<label class="edit-label" for={`key-${row.type}`}>
										API key for {label(row.type)}
										<input
											id={`key-${row.type}`}
											type="password"
											autocomplete="off"
											placeholder="Paste the key"
											bind:value={draftKey}
											class="edit-input"
										/>
									</label>
									<div class="edit-actions">
										<button type="button" class="install-button" on:click={() => saveKey(row.type)} disabled={saving || !draftKey.trim()}>
											{saving ? 'Saving…' : 'Save key'}
										</button>
										<button type="button" class="action-button" on:click={cancelEdit} disabled={saving}>Cancel</button>
									</div>
								</div>
							</td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<style>
	/* Mirror provider-keys/+page.svelte styles: reuse the same --lq-* tokens and
	   class names (.page-header, .page-intro, .keys-table, .badge, .badge-runtime,
	   .muted, .error-banner, .success-banner, .edit-form, .edit-input, .action-button,
	   .install-button, .danger). Copy the <style> block from provider-keys verbatim
	   and rename the outer wrapper to .research-sources-page. */
</style>
```

> **Implementer:** copy the full `<style>` block from `provider-keys/+page.svelte:271-442` verbatim (rename the top-level `.provider-keys-page` selector to `.research-sources-page`) so the card is visually identical to the existing one.

- [ ] **Step 3: Add the nav entry** to `web/src/routes/lq-ai/admin/+layout.svelte` (in the `navLinks` array, after the provider-keys entry):

```svelte
		{ href: '/lq-ai/admin/research-sources', label: 'Research sources' },
```

- [ ] **Step 4: svelte-check clean**

Run: `cd web && npm run check:lq-ai`
Expected: no errors in the new/edited files.

- [ ] **Step 5: Structure smoke test (optional but recommended).** Use the headless-chromium render-smoke technique (see `project-de365-sub2-playgrounds` memory) OR a lightweight assertion that the masked input is `type="password"` and no response body surfaces a key. At minimum, manually verify the card renders in a `web` rebuild (the container serves a pre-built bundle — rebuild `web` before checking).

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/lq-ai/api/admin.ts \
        web/src/routes/lq-ai/admin/research-sources/+page.svelte \
        web/src/routes/lq-ai/admin/+layout.svelte
git commit -s -m "feat(web): Research sources admin card

In-app enable/disable of authority sources; masked write-only key input;
hot-applied. Mirrors the Provider keys card. Refs Donna #3.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification (before the PR)

- [ ] **Gateway:** `cd gateway && .venv/bin/ruff format app/ tests/ && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/ && .venv/bin/python -m pytest -q`
- [ ] **API:** `cd api && DATABASE_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/postgres" .venv/bin/python -m pytest -q && .venv/bin/ruff format app/ tests/ && .venv/bin/ruff check app/ tests/ && .venv/bin/mypy app/`
- [ ] **OpenAPI drift:** `make openapi` produces no diff (already committed in T5).
- [ ] **Web:** `cd web && npm run check:lq-ai`
- [ ] **Coverage:** no decrease vs `main` for `api/` + `gateway/`.
- [ ] **Whole-branch security-aware review** (subagent-driven-development final gate, most capable model): confirm (1) the api cannot set `base_url`/`allowlist` (gateway-owned defaults); (2) no plaintext key or ciphertext in any response or log; (3) admin-gated (403 for non-admin); (4) audit row on every write; (5) 400/404/409 semantics correct; (6) DELETE-204 empty body.

## PR + release (spec §9)

1. Push the branch to `origin`; open the PR (title: `feat: runtime tool/authority-provider admin API + Research sources card (Donna #3)`). It auto-routes to security reviewers (`gateway/**` + secret paths).
2. **Do not self-merge past the security review.** Address findings via `receiving-code-review`.
3. After merge: mirror `origin`→`tucuxi` on `main`; **reply to Donna's request doc** (`/Users/kevinkeller/Code/Donna/docs/upstream-requests/lq-ai-runtime-tool-provider-admin-api.md`) with the §5 contract table + the squash SHA.
4. **Then cut v0.6.1:** bump `api/app/__init__.py` 0.6.0→0.6.1 + `desktop/package.json` 0.6.0→0.6.1, `make openapi` re-gen, PR/merge → `git tag v0.6.1` (→GHCR) + `git tag desktop-v0.6.1` (→signed .dmg) → Kevin's real-Mac verify. Follow the release ritual (`project-fiduciary-release-gate`).

---

## Self-review (against the spec)

- **§3 Goals** — writer (T1) ✓, gateway endpoints (T2) ✓, api endpoints (T4) ✓, web card (T6) ✓, enable-not-yet-present-type (T1 create-from-defaults) ✓. **Non-goals** honored: no MCP admin (registry is the 4 authority types only); registry/adapter use-path unchanged; ADR 0011 reused; keyless sources get no key input (card branches on `key_required`).
- **§4 anchors** — every anchor mapped to a task.
- **§5 contract** — all four verbs, status codes 400/404/409, secret-safe, hot-apply proof (T2 Step 6 gateway boundary + T4 Step 5 proxy) ✓.
- **§6 web** — Available/Unavailable badge, masked write-only input, enable/disable, hot re-fetch, `lq-*` tokens, no secret shown ✓.
- **§7 open items** — D2 (gateway owns defaults), D6 (name vs type), D4 (env-key 409) all resolved.
- **§8 testing** — gateway unit + endpoint, api endpoint (verbs, codes, secret-never-returned, unregistered 404, hot-apply), web svelte-check + structure, security-review focus list, collision guards + OpenAPI regen ✓.
- **§10 risks** — SSRF (D2), secret leakage (write-only + strip), collision guards (T5), hot-apply (D3 + proof) all addressed.
