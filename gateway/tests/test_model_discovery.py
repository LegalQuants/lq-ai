"""Unit tests for D0 — model discovery + raw provider/model passthrough.

Covers:

* :class:`ModelDiscoverer` — Ollama tags discovery, Anthropic catalog
  discovery, TTL cache hit/miss/expiry, single-source-failure fallback.
* :func:`resolve_alias_chain` — raw ``provider/model`` passthrough,
  unknown-provider rejection, empty-model rejection.
* ``GET /v1/models`` end-to-end — merged response shape, per-source
  failure isolation.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.config import (
    GatewayConfig,
    InferenceTiersConfig,
    ModelAliasConfig,
    ModelTarget,
    ProviderConfig,
)
from app.model_discovery import (
    ANTHROPIC_CACHE_TTL_SECONDS,
    OLLAMA_CACHE_TTL_SECONDS,
    DiscoveredModel,
    ModelDiscoverer,
)
from app.router import ModelResolutionError, resolve_alias_chain


def _make_config() -> GatewayConfig:
    """Build a minimal config covering both ollama + anthropic paths."""

    providers = [
        ProviderConfig(
            name="anthropic-prod",
            type="anthropic",
            base_url="https://api.anthropic.com",
            api_key_env="ANTHROPIC_API_KEY",
            tier=4,
            models=["claude-opus-4-7", "claude-haiku-4-5"],
        ),
        ProviderConfig(
            name="ollama-local",
            type="ollama",
            base_url="http://ollama:11434",
            api_key_env="",
            tier=1,
            models=["llama3.1:8b"],
        ),
    ]
    aliases = {
        "smart": ModelAliasConfig(
            primary=ModelTarget(provider="anthropic-prod", model="claude-opus-4-7"),
            fallback=[],
        ),
        "fast": ModelAliasConfig(
            primary=ModelTarget(provider="anthropic-prod", model="claude-haiku-4-5"),
            fallback=[],
        ),
    }
    return GatewayConfig(
        providers=providers,
        model_aliases=aliases,
        inference_tiers=InferenceTiersConfig(defaults={"anthropic": 4, "ollama": 1}),
    )


# --- ModelDiscoverer — Ollama --------------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_discover_ollama_returns_pulled_models() -> None:
    config = _make_config()
    ollama = config.providers[1]
    respx.get("http://ollama:11434/api/tags").mock(
        return_value=httpx.Response(
            200,
            json={
                "models": [
                    {"name": "llama3.1:8b"},
                    {"name": "qwen2.5:7b"},
                ]
            },
        )
    )

    async with httpx.AsyncClient() as client:
        discoverer = ModelDiscoverer(client=client)
        rows = await discoverer.discover_ollama(ollama)

    ids = sorted(r.id for r in rows)
    assert ids == ["ollama-local/llama3.1:8b", "ollama-local/qwen2.5:7b"]
    assert all(r.lq_ai_kind == "provider_native" for r in rows)
    assert all(r.owned_by == "ollama-local" for r in rows)


@pytest.mark.unit
@respx.mock
async def test_discover_ollama_returns_empty_on_connection_error() -> None:
    """Connection refused / unreachable -> empty list, no exception."""

    config = _make_config()
    ollama = config.providers[1]
    respx.get("http://ollama:11434/api/tags").mock(side_effect=httpx.ConnectError("refused"))

    async with httpx.AsyncClient() as client:
        discoverer = ModelDiscoverer(client=client)
        rows = await discoverer.discover_ollama(ollama)

    assert rows == []


@pytest.mark.unit
@respx.mock
async def test_discover_ollama_returns_empty_on_500() -> None:
    config = _make_config()
    ollama = config.providers[1]
    respx.get("http://ollama:11434/api/tags").mock(return_value=httpx.Response(500, text="boom"))

    async with httpx.AsyncClient() as client:
        discoverer = ModelDiscoverer(client=client)
        rows = await discoverer.discover_ollama(ollama)

    assert rows == []


@pytest.mark.unit
@respx.mock
async def test_discover_ollama_caches_result_with_ttl() -> None:
    config = _make_config()
    ollama = config.providers[1]
    route = respx.get("http://ollama:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})
    )

    fake_now = [1000.0]
    async with httpx.AsyncClient() as client:
        discoverer = ModelDiscoverer(client=client)
        # Override the cache's clock to deterministically advance.
        discoverer.cache._clock = lambda: fake_now[0]  # type: ignore[method-assign]

        first = await discoverer.discover_ollama(ollama)
        assert len(first) == 1
        assert route.call_count == 1

        # Within TTL: cache hit, no second upstream call.
        fake_now[0] += OLLAMA_CACHE_TTL_SECONDS - 1
        second = await discoverer.discover_ollama(ollama)
        assert second == first
        assert route.call_count == 1

        # Past TTL: cache miss, second upstream call.
        fake_now[0] += 2
        third = await discoverer.discover_ollama(ollama)
        assert len(third) == 1
        assert route.call_count == 2


# --- ModelDiscoverer — Anthropic ----------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_discover_anthropic_returns_catalog() -> None:
    config = _make_config()
    anthropic = config.providers[0]

    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "claude-opus-4-7"},
                    {"id": "claude-haiku-4-5"},
                ]
            },
        )
    )

    async with httpx.AsyncClient() as client:
        discoverer = ModelDiscoverer(
            client=client,
            env={"ANTHROPIC_API_KEY": "sk-test-key"},
        )
        rows = await discoverer.discover_anthropic(anthropic)

    ids = sorted(r.id for r in rows)
    assert ids == ["anthropic-prod/claude-haiku-4-5", "anthropic-prod/claude-opus-4-7"]


@pytest.mark.unit
async def test_discover_anthropic_skipped_without_api_key() -> None:
    """No API key -> skip discovery (return [], no upstream call)."""

    config = _make_config()
    anthropic = config.providers[0]
    async with httpx.AsyncClient() as client:
        discoverer = ModelDiscoverer(client=client, env={})  # ANTHROPIC_API_KEY unset
        rows = await discoverer.discover_anthropic(anthropic)
    assert rows == []


@pytest.mark.unit
@respx.mock
async def test_discover_anthropic_returns_empty_on_401() -> None:
    """An invalid key returns 401 — log a warning, return []."""

    config = _make_config()
    anthropic = config.providers[0]
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )

    async with httpx.AsyncClient() as client:
        discoverer = ModelDiscoverer(
            client=client,
            env={"ANTHROPIC_API_KEY": "sk-bad"},
        )
        rows = await discoverer.discover_anthropic(anthropic)
    assert rows == []


@pytest.mark.unit
@respx.mock
async def test_discover_anthropic_uses_5min_cache() -> None:
    config = _make_config()
    anthropic = config.providers[0]
    route = respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "claude-opus-4-7"}]})
    )

    fake_now = [0.0]
    async with httpx.AsyncClient() as client:
        discoverer = ModelDiscoverer(
            client=client,
            env={"ANTHROPIC_API_KEY": "sk-test"},
        )
        discoverer.cache._clock = lambda: fake_now[0]  # type: ignore[method-assign]

        await discoverer.discover_anthropic(anthropic)
        # Just under TTL: still cached.
        fake_now[0] = ANTHROPIC_CACHE_TTL_SECONDS - 1
        await discoverer.discover_anthropic(anthropic)
        assert route.call_count == 1

        # Past TTL: re-fetch.
        fake_now[0] = ANTHROPIC_CACHE_TTL_SECONDS + 1
        await discoverer.discover_anthropic(anthropic)
        assert route.call_count == 2


# --- ModelDiscoverer — aggregator ---------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_list_all_merges_aliases_and_provider_native_rows() -> None:
    config = _make_config()
    respx.get("http://ollama:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})
    )
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "claude-opus-4-7"}]})
    )

    async with httpx.AsyncClient() as client:
        discoverer = ModelDiscoverer(client=client, env={"ANTHROPIC_API_KEY": "sk-test"})
        rows = await discoverer.list_all(config)

    ids = [r.id for r in rows]
    # Aliases come first (insertion order).
    assert ids[0:2] == ["smart", "fast"]
    assert {"anthropic-prod/claude-opus-4-7", "ollama-local/llama3.1:8b"}.issubset(set(ids))


@pytest.mark.unit
@respx.mock
async def test_list_all_isolates_per_source_failures() -> None:
    """If Ollama is down but Anthropic responds, the Anthropic rows still surface."""

    config = _make_config()
    respx.get("http://ollama:11434/api/tags").mock(side_effect=httpx.ConnectError("nope"))
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "claude-opus-4-7"}]})
    )

    async with httpx.AsyncClient() as client:
        discoverer = ModelDiscoverer(client=client, env={"ANTHROPIC_API_KEY": "sk-test"})
        rows = await discoverer.list_all(config)

    ids = {r.id for r in rows}
    assert "smart" in ids  # alias still surfaces
    assert "anthropic-prod/claude-opus-4-7" in ids
    # Ollama produced nothing.
    assert not any(i.startswith("ollama-local/") for i in ids)


@pytest.mark.unit
async def test_list_all_returns_aliases_when_no_providers_reachable() -> None:
    """All discovery sources down -> aliases-only response (never empty)."""

    config = _make_config()
    # No respx mocks; httpx will hit nothing — but each source method
    # handles errors and returns [] cleanly.
    async with httpx.AsyncClient() as client:
        discoverer = ModelDiscoverer(client=client, env={})
        rows = await discoverer.list_all(config)

    ids = [r.id for r in rows]
    assert ids == ["smart", "fast"]


@pytest.mark.unit
@respx.mock
async def test_list_all_annotates_tier_on_native_rows() -> None:
    config = _make_config()
    respx.get("http://ollama:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})
    )
    respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "claude-haiku-4-5"}]})
    )

    async with httpx.AsyncClient() as client:
        discoverer = ModelDiscoverer(client=client, env={"ANTHROPIC_API_KEY": "sk-test"})
        rows = await discoverer.list_all(config)

    by_id = {r.id: r for r in rows}
    assert by_id["ollama-local/llama3.1:8b"].routed_inference_tier == 1
    assert by_id["anthropic-prod/claude-haiku-4-5"].routed_inference_tier == 4
    # D0.5 closed the alias-tier gap: aliases now surface the tier of their
    # primary target so the picker badge is correct before the first send.
    assert by_id["smart"].routed_inference_tier is not None


@pytest.mark.unit
def test_discovered_model_payload_omits_optionals() -> None:
    """``to_payload`` drops ``routed_inference_tier`` / ``provider_type`` when None."""

    alias_row = DiscoveredModel(id="smart", owned_by="lq-ai-gateway", lq_ai_kind="alias")
    payload = alias_row.to_payload()
    assert payload["id"] == "smart"
    assert payload["lq_ai_kind"] == "alias"
    assert payload["owned_by"] == "lq-ai-gateway"
    assert payload["object"] == "model"
    assert "routed_inference_tier" not in payload
    assert "provider_type" not in payload

    native_row = DiscoveredModel(
        id="ollama-local/x:1",
        owned_by="ollama-local",
        lq_ai_kind="provider_native",
        routed_inference_tier=1,
        provider_type="ollama",
    )
    native_payload = native_row.to_payload()
    assert native_payload["routed_inference_tier"] == 1
    assert native_payload["provider_type"] == "ollama"


# --- Router — raw provider/model passthrough ----------------------------------


@pytest.mark.unit
def test_resolve_raw_provider_model_returns_single_target() -> None:
    config = _make_config()
    targets = resolve_alias_chain(requested_model="anthropic-prod/claude-haiku-4-5", config=config)
    assert len(targets) == 1
    target = targets[0]
    assert target.provider.name == "anthropic-prod"
    assert target.native_model == "claude-haiku-4-5"
    assert target.routed_inference_tier == 4
    assert target.role == "primary"


@pytest.mark.unit
def test_resolve_raw_provider_model_supports_colon_in_model_name() -> None:
    """Ollama tags often contain ``:`` (``llama3.1:8b``) — split on the first ``/`` only."""

    config = _make_config()
    targets = resolve_alias_chain(requested_model="ollama-local/llama3.1:8b", config=config)
    assert len(targets) == 1
    assert targets[0].provider.name == "ollama-local"
    assert targets[0].native_model == "llama3.1:8b"
    assert targets[0].routed_inference_tier == 1


@pytest.mark.unit
def test_resolve_raw_provider_model_rejects_unknown_provider() -> None:
    config = _make_config()
    with pytest.raises(ModelResolutionError) as exc_info:
        resolve_alias_chain(requested_model="not-a-provider/some-model", config=config)
    msg = str(exc_info.value)
    assert "not-a-provider" in msg
    # The message must enumerate the configured set so the operator can spot the typo.
    assert "anthropic-prod" in msg
    assert "ollama-local" in msg


@pytest.mark.unit
def test_resolve_raw_provider_model_rejects_empty_model() -> None:
    config = _make_config()
    with pytest.raises(ModelResolutionError) as exc_info:
        resolve_alias_chain(requested_model="anthropic-prod/", config=config)
    assert "empty" in str(exc_info.value).lower()


@pytest.mark.unit
def test_resolve_alias_still_works_unchanged() -> None:
    """Backwards compat: bare aliases continue to resolve through the alias map."""

    config = _make_config()
    targets = resolve_alias_chain(requested_model="smart", config=config)
    assert len(targets) == 1
    assert targets[0].provider.name == "anthropic-prod"
    assert targets[0].native_model == "claude-opus-4-7"


# --- Endpoint integration -----------------------------------------------------


@pytest.mark.unit
@respx.mock
async def test_v1_models_returns_merged_payload(client: AsyncClient) -> None:
    """End-to-end ``GET /v1/models`` with mocked Ollama + Anthropic discovery.

    The ``client`` fixture brings up the gateway lifespan against the
    example config. The lifespan constructs a ``ModelDiscoverer`` whose
    httpx client is the default — respx patches the global transport so
    our mocks apply to the discoverer's calls too.
    """

    respx.get("http://ollama:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}]})
    )
    # No ANTHROPIC_API_KEY in the test env -> Anthropic discovery skipped.
    response = await client.get("/v1/models")
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    ids = [e["id"] for e in body["data"]]
    # Aliases from the example config.
    for alias in ("smart", "fast", "budget", "local", "embedding"):
        assert alias in ids
    # Ollama-discovered row surfaces with provider/native form.
    assert "ollama-local/llama3.1:8b" in ids
    # Each entry carries the lq_ai_kind extension.
    for entry in body["data"]:
        assert entry["lq_ai_kind"] in ("alias", "provider_native")


@pytest.mark.unit
@respx.mock
async def test_v1_models_survives_ollama_outage(client: AsyncClient) -> None:
    """Ollama down -> response still surfaces aliases."""

    respx.get("http://ollama:11434/api/tags").mock(side_effect=httpx.ConnectError("refused"))
    response = await client.get("/v1/models")
    assert response.status_code == 200
    ids = {e["id"] for e in response.json()["data"]}
    assert "smart" in ids
    # No Ollama rows.
    assert not any(i.startswith("ollama-local/") for i in ids)


# --- ModelDiscoverer — OpenAI (wave-3 / ADR 0011) -----------------------------


def _make_config_with_openai() -> GatewayConfig:
    providers = [
        ProviderConfig(
            name="openai-prod",
            type="openai",
            base_url="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            tier=4,
            models=["gpt-4o"],
        ),
    ]
    aliases = {
        "smart": ModelAliasConfig(
            primary=ModelTarget(provider="openai-prod", model="gpt-4o"),
            fallback=[],
        ),
    }
    return GatewayConfig(
        providers=providers,
        model_aliases=aliases,
        inference_tiers=InferenceTiersConfig(defaults={"openai": 4}),
    )


@pytest.mark.unit
@respx.mock
async def test_discover_openai_returns_catalog() -> None:
    """``GET <base_url>/models`` is parsed and surfaces as provider/native rows."""

    config = _make_config_with_openai()
    discoverer = ModelDiscoverer(env={"OPENAI_API_KEY": "sk-test"})
    try:
        respx.get("https://api.openai.com/v1/models").mock(
            return_value=httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {"id": "gpt-4o", "object": "model"},
                        {"id": "gpt-4o-mini", "object": "model"},
                    ],
                },
            )
        )
        rows = await discoverer.discover_openai(config.providers[0])
        ids = {r.id for r in rows}
        assert "openai-prod/gpt-4o" in ids
        assert "openai-prod/gpt-4o-mini" in ids
        # Each row carries lq_ai_kind + provider_type.
        assert all(r.lq_ai_kind == "provider_native" for r in rows)
        assert all(r.provider_type == "openai" for r in rows)
    finally:
        await discoverer.aclose()


@pytest.mark.unit
@respx.mock
async def test_discover_openai_skips_when_no_key() -> None:
    """No key → []; logs at INFO, never raises."""

    config = _make_config_with_openai()
    # Empty env → no OPENAI_API_KEY.
    discoverer = ModelDiscoverer(env={})
    try:
        rows = await discoverer.discover_openai(config.providers[0])
        assert rows == []
    finally:
        await discoverer.aclose()


@pytest.mark.unit
@respx.mock
async def test_discover_openai_returns_empty_on_401() -> None:
    config = _make_config_with_openai()
    discoverer = ModelDiscoverer(env={"OPENAI_API_KEY": "sk-bad"})
    try:
        respx.get("https://api.openai.com/v1/models").mock(
            return_value=httpx.Response(401, json={"error": "invalid"})
        )
        rows = await discoverer.discover_openai(config.providers[0])
        assert rows == []
    finally:
        await discoverer.aclose()


@pytest.mark.unit
@respx.mock
async def test_discover_openai_compatible_works_without_key() -> None:
    """Local OpenAI-compatible servers (vLLM) often serve /models without auth."""

    provider = ProviderConfig(
        name="vllm-local",
        type="openai_compatible",
        base_url="http://vllm:8000/v1",
        api_key_env=None,
        tier=1,
        models=[],
    )
    discoverer = ModelDiscoverer(env={})
    try:
        respx.get("http://vllm:8000/v1/models").mock(
            return_value=httpx.Response(
                200,
                json={"object": "list", "data": [{"id": "llama3.1-70b", "object": "model"}]},
            )
        )
        rows = await discoverer.discover_openai(provider)
        assert any(r.id == "vllm-local/llama3.1-70b" for r in rows)
    finally:
        await discoverer.aclose()


@pytest.mark.unit
@respx.mock
async def test_discover_anthropic_uses_encrypted_key_when_set() -> None:
    """ADR 0011: api_key_encrypted resolves through the master key."""

    from app.secrets import (
        ProviderKeyResolver,
        encrypt_value,
        generate_master_key,
    )

    master = generate_master_key()
    token = encrypt_value("sk-ant-encrypted-test-key", master_key=master)
    provider = ProviderConfig(
        name="anthropic-prod",
        type="anthropic",
        base_url="https://api.anthropic.com",
        api_key_encrypted=token,
        tier=4,
        models=["claude-opus-4-7"],
    )
    resolver = ProviderKeyResolver(master_key=master, env={})
    discoverer = ModelDiscoverer(env={}, key_resolver=resolver)
    try:
        # The respx route asserts the request's x-api-key matches the
        # decrypted plaintext, proving the resolver was used.
        route = respx.get("https://api.anthropic.com/v1/models").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "claude-opus-4-7", "object": "model"},
                    ]
                },
            )
        )
        rows = await discoverer.discover_anthropic(provider)
        assert len(rows) == 1
        assert rows[0].id == "anthropic-prod/claude-opus-4-7"
        # Verify the decrypted key reached the upstream call.
        assert route.calls.last.request.headers["x-api-key"] == "sk-ant-encrypted-test-key"
    finally:
        await discoverer.aclose()


# --- Wave-3 alias resolution surfacing (ADR 0011) -----------------------------


@pytest.mark.unit
async def test_alias_entries_carry_resolves_to() -> None:
    """ADR 0011: each alias entry exposes its resolved primary target.

    The picker UI renders 'smart → anthropic-prod/claude-opus-4-7' so
    aliases are convenience defaults rather than opacity. Verifying
    this at the discoverer layer pins the contract; the web side has
    its own unit tests against the API client typing.
    """

    config = _make_config()
    discoverer = ModelDiscoverer(env={})  # No keys → no live discovery, just aliases.
    try:
        rows = await discoverer.list_all(config)
    finally:
        await discoverer.aclose()
    aliases = {row.id: row for row in rows if row.lq_ai_kind == "alias"}
    assert aliases["smart"].resolves_to == "anthropic-prod/claude-opus-4-7"
    assert aliases["fast"].resolves_to == "anthropic-prod/claude-haiku-4-5"
    # No fallbacks configured in _make_config, so count is 0 (omitted in
    # the serialized payload but present on the dataclass).
    assert aliases["smart"].fallback_count == 0


@pytest.mark.unit
def test_to_payload_omits_resolves_to_for_provider_native() -> None:
    """Provider-native rows already encode their concrete provider/model
    in `id`; surfacing `lq_ai_resolves_to` would be redundant."""

    row = DiscoveredModel(
        id="anthropic-prod/claude-opus-4-7",
        owned_by="anthropic-prod",
        lq_ai_kind="provider_native",
        provider_type="anthropic",
        routed_inference_tier=4,
    )
    payload = row.to_payload()
    assert "lq_ai_resolves_to" not in payload
    assert "lq_ai_fallback_count" not in payload


@pytest.mark.unit
def test_to_payload_includes_resolves_to_for_alias() -> None:
    row = DiscoveredModel(
        id="smart",
        owned_by="lq-ai-gateway",
        lq_ai_kind="alias",
        routed_inference_tier=4,
        resolves_to="anthropic-prod/claude-opus-4-7",
        fallback_count=2,
    )
    payload = row.to_payload()
    assert payload["lq_ai_resolves_to"] == "anthropic-prod/claude-opus-4-7"
    assert payload["lq_ai_fallback_count"] == 2


@pytest.mark.unit
def test_to_payload_keys_declared_in_openapi_modelentry() -> None:
    """Every key the live ``GET /v1/models`` emits is a declared property
    on the ``ModelEntry`` schema in ``docs/api/gateway-openapi.yaml``.

    Pins the hand-written OpenAPI sketch to the live ``to_payload`` shape so
    the doc can't silently drift behind the gateway (the inverse of the
    field-presence tests above, which pin the live side). This is a
    property-*superset* check rather than ``additionalProperties: false`` on
    the schema, so the contract still tolerates other valid runtime fields.
    """
    from pathlib import Path

    import yaml

    repo_root = Path(__file__).resolve().parents[2]
    spec = yaml.safe_load(
        (repo_root / "docs" / "api" / "gateway-openapi.yaml").read_text(encoding="utf-8")
    )
    declared = set(spec["components"]["schemas"]["ModelEntry"]["properties"].keys())

    # Both row kinds the gateway emits, with every optional field populated.
    alias = DiscoveredModel(
        id="smart",
        owned_by="lq-ai-gateway",
        lq_ai_kind="alias",
        routed_inference_tier=4,
        resolves_to="anthropic-prod/claude-opus-4-7",
        fallback_count=2,
    ).to_payload()
    native = DiscoveredModel(
        id="anthropic-prod/claude-opus-4-7",
        owned_by="anthropic-prod",
        lq_ai_kind="provider_native",
        provider_type="anthropic",
        routed_inference_tier=4,
    ).to_payload()

    for payload in (alias, native):
        undeclared = set(payload) - declared
        assert not undeclared, (
            "GET /v1/models emits keys not declared on ModelEntry in "
            f"docs/api/gateway-openapi.yaml: {sorted(undeclared)}"
        )
    # The alias-only extensions added in this doc fix are explicitly declared.
    assert {"lq_ai_resolves_to", "lq_ai_fallback_count"} <= declared
