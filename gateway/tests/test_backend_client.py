"""Unit tests for the gateway-side backend HTTP client and skill cache (C2).

Covers:

* :class:`SkillCache` — TTL, hit/miss, expiry, invalidate, clear.
* :class:`BackendClient.get_skill` — happy path / 404 / 401 / 5xx /
  network failure / timeout / malformed body / non-JSON / schema
  drift, plus cache integration.

All tests use respx-mocked httpx; no real backend involved. The
``configure_backend_client`` env-var path is exercised via
:mod:`pytest.MonkeyPatch`.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.clients.backend import (
    ORGANIZATION_PROFILE_CACHE_KEY,
    BackendClient,
    BackendUnreachable,
    Skill as ClientSkill,
    SkillCache,
    SkillFetchFailed,
    SkillNotFound,
    configure_backend_client,
    set_backend_client,
)

# --- SkillCache --------------------------------------------------------------


class _FakeClock:
    """Manually-advanced clock for deterministic TTL testing."""

    def __init__(self, *, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _make_skill(name: str = "alpha") -> ClientSkill:
    return ClientSkill(
        name=name,
        version="1.0.0",
        scope="builtin",
        title=name.title(),
        content_md=f"# {name}\n\nbody",
        content_yaml=f"name: {name}\n",
    )


@pytest.mark.unit
async def test_cache_miss_returns_none() -> None:
    cache = SkillCache(ttl_seconds=60.0)
    assert await cache.get("alpha") is None


@pytest.mark.unit
async def test_cache_put_then_get_returns_skill() -> None:
    cache = SkillCache(ttl_seconds=60.0)
    skill = _make_skill()
    await cache.put("alpha", skill)
    fetched = await cache.get("alpha")
    assert fetched is not None
    assert fetched.name == "alpha"


@pytest.mark.unit
async def test_cache_expiry_drops_entry() -> None:
    clock = _FakeClock()
    cache = SkillCache(ttl_seconds=60.0, clock=clock)
    await cache.put("alpha", _make_skill())
    # Within TTL: hit.
    clock.now = 30.0
    assert await cache.get("alpha") is not None
    # Past TTL: miss.
    clock.now = 61.0
    assert await cache.get("alpha") is None
    # And the entry is gone, not just expired-but-still-there.
    assert await cache.size() == 0


@pytest.mark.unit
async def test_cache_invalidate_drops_only_named_entry() -> None:
    cache = SkillCache(ttl_seconds=60.0)
    await cache.put("alpha", _make_skill("alpha"))
    await cache.put("beta", _make_skill("beta"))
    await cache.invalidate("alpha")
    assert await cache.get("alpha") is None
    assert await cache.get("beta") is not None


@pytest.mark.unit
async def test_cache_clear_drops_all_entries() -> None:
    cache = SkillCache(ttl_seconds=60.0)
    await cache.put("alpha", _make_skill("alpha"))
    await cache.put("beta", _make_skill("beta"))
    await cache.clear()
    assert await cache.size() == 0


# --- BackendClient.get_skill -------------------------------------------------


def _client_with_respx() -> BackendClient:
    """Construct a BackendClient with a mounted respx-mocked transport.

    Uses a base_url respx will match (any URL works as long as the
    test's respx.mock decorator matches the same path).
    """

    return BackendClient(
        base_url="http://api.test",
        gateway_key="test-secret",
        cache=SkillCache(ttl_seconds=60.0),
    )


@pytest.mark.unit
@respx.mock
async def test_get_skill_happy_path() -> None:
    route = respx.get("http://api.test/api/v1/internal/skills/alpha").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "alpha",
                "version": "1.0.0",
                "scope": "builtin",
                "title": "Alpha",
                "description": "desc",
                "content_md": "# Alpha",
                "content_yaml": "name: alpha\n",
                "minimum_inference_tier": 2,
                "tags": ["test"],
                "reference_files": [{"path": "reference/note.md", "content": "ref"}],
            },
        )
    )

    client = _client_with_respx()
    skill = await client.get_skill("alpha")

    assert route.called
    assert skill.name == "alpha"
    assert skill.minimum_inference_tier == 2
    assert skill.tags == ["test"]
    assert skill.reference_files[0].path == "reference/note.md"


@pytest.mark.unit
@respx.mock
async def test_get_skill_sends_gateway_key_header() -> None:
    captured: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["gateway_key"] = request.headers.get("X-LQ-AI-Gateway-Key", "")
        return httpx.Response(
            200,
            json={"name": "alpha", "content_md": "x", "content_yaml": "y"},
        )

    respx.get("http://api.test/api/v1/internal/skills/alpha").mock(side_effect=_capture)
    client = _client_with_respx()
    await client.get_skill("alpha")
    assert captured["gateway_key"] == "test-secret"


@pytest.mark.unit
@respx.mock
async def test_get_skill_forwards_request_id_header() -> None:
    captured: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["request_id"] = request.headers.get("X-Request-Id", "")
        return httpx.Response(200, json={"name": "alpha", "content_md": "x", "content_yaml": "y"})

    respx.get("http://api.test/api/v1/internal/skills/alpha").mock(side_effect=_capture)
    client = _client_with_respx()
    await client.get_skill("alpha", request_id="req_123")
    assert captured["request_id"] == "req_123"


@pytest.mark.unit
@respx.mock
async def test_get_skill_404_raises_skill_not_found() -> None:
    respx.get("http://api.test/api/v1/internal/skills/nope").mock(
        return_value=httpx.Response(
            404,
            json={
                "detail": {
                    "code": "not_found",
                    "message": "Skill 'nope' is not in the registry.",
                    "details": {"skill_name": "nope"},
                }
            },
        )
    )

    client = _client_with_respx()
    with pytest.raises(SkillNotFound) as exc_info:
        await client.get_skill("nope")
    assert exc_info.value.details["skill_name"] == "nope"


@pytest.mark.unit
@respx.mock
async def test_get_skill_401_raises_skill_fetch_failed_and_logs() -> None:
    respx.get("http://api.test/api/v1/internal/skills/alpha").mock(
        return_value=httpx.Response(401, json={"detail": {"code": "unauthorized"}})
    )

    client = _client_with_respx()
    with pytest.raises(SkillFetchFailed) as exc_info:
        await client.get_skill("alpha")
    # The user-facing detail must NOT leak "key is wrong" — the public
    # message still implicates the operator's gateway key in a generic
    # way, but the structured details surface the operational reason.
    assert exc_info.value.details.get("reason") == "operator-configuration"


@pytest.mark.unit
@respx.mock
async def test_get_skill_500_raises_skill_fetch_failed() -> None:
    respx.get("http://api.test/api/v1/internal/skills/alpha").mock(
        return_value=httpx.Response(500, text="boom")
    )

    client = _client_with_respx()
    with pytest.raises(SkillFetchFailed) as exc_info:
        await client.get_skill("alpha")
    assert exc_info.value.details["status_code"] == 500


@pytest.mark.unit
@respx.mock
async def test_get_skill_503_raises_skill_fetch_failed() -> None:
    respx.get("http://api.test/api/v1/internal/skills/alpha").mock(
        return_value=httpx.Response(503, text="unavailable")
    )

    client = _client_with_respx()
    with pytest.raises(SkillFetchFailed):
        await client.get_skill("alpha")


@pytest.mark.unit
@respx.mock
async def test_get_skill_timeout_raises_backend_unreachable() -> None:
    respx.get("http://api.test/api/v1/internal/skills/alpha").mock(
        side_effect=httpx.ConnectTimeout("timeout")
    )

    client = _client_with_respx()
    with pytest.raises(BackendUnreachable) as exc_info:
        await client.get_skill("alpha")
    assert exc_info.value.details["skill_name"] == "alpha"


@pytest.mark.unit
@respx.mock
async def test_get_skill_network_error_raises_backend_unreachable() -> None:
    respx.get("http://api.test/api/v1/internal/skills/alpha").mock(
        side_effect=httpx.ConnectError("dns")
    )

    client = _client_with_respx()
    with pytest.raises(BackendUnreachable) as exc_info:
        await client.get_skill("alpha")
    assert "transport_error" in exc_info.value.details


@pytest.mark.unit
@respx.mock
async def test_get_skill_non_json_body_raises_skill_fetch_failed() -> None:
    respx.get("http://api.test/api/v1/internal/skills/alpha").mock(
        return_value=httpx.Response(
            200, content=b"<html>not json</html>", headers={"content-type": "text/html"}
        )
    )

    client = _client_with_respx()
    with pytest.raises(SkillFetchFailed):
        await client.get_skill("alpha")


@pytest.mark.unit
@respx.mock
async def test_get_skill_schema_drift_raises_skill_fetch_failed() -> None:
    respx.get("http://api.test/api/v1/internal/skills/alpha").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )
    client = _client_with_respx()
    with pytest.raises(SkillFetchFailed) as exc_info:
        await client.get_skill("alpha")
    # Pydantic surfaced the missing required `name` field.
    assert "validation_errors" in exc_info.value.details


@pytest.mark.unit
@respx.mock
async def test_get_skill_caches_successful_fetch() -> None:
    route = respx.get("http://api.test/api/v1/internal/skills/alpha").mock(
        return_value=httpx.Response(
            200, json={"name": "alpha", "content_md": "x", "content_yaml": "y"}
        )
    )

    client = _client_with_respx()
    a = await client.get_skill("alpha")
    b = await client.get_skill("alpha")
    assert a.name == b.name
    # The second call hit the cache, not the wire.
    assert route.call_count == 1
    assert await client.cache.size() == 1


@pytest.mark.unit
@respx.mock
async def test_user_resolved_skill_replacement_is_fresh_within_cache_ttl() -> None:
    route = respx.get("http://api.test/api/v1/internal/skills/alpha").mock(
        side_effect=[
            httpx.Response(
                200, json={"name": "alpha", "scope": "builtin", "content_md": "builtin"}
            ),
            httpx.Response(200, json={"name": "alpha", "scope": "team", "content_md": "team"}),
            httpx.Response(200, json={"name": "alpha", "scope": "user", "content_md": "user"}),
            httpx.Response(404, json={"detail": "access revoked"}),
        ]
    )
    client = _client_with_respx()
    for body in ("builtin", "team", "user"):
        skill = await client.get_skill("alpha", user_id="user-a")
        assert skill.content_md == body
    with pytest.raises(SkillNotFound):
        await client.get_skill("alpha", user_id="user-a")
    assert route.call_count == 4
    assert all(call.request.url.params["user_id"] == "user-a" for call in route.calls)
    assert await client.cache.size() == 0


@pytest.mark.unit
@respx.mock
async def test_get_skill_does_not_cache_failure() -> None:
    route = respx.get("http://api.test/api/v1/internal/skills/alpha").mock(
        return_value=httpx.Response(500, text="boom")
    )

    client = _client_with_respx()
    with pytest.raises(SkillFetchFailed):
        await client.get_skill("alpha")
    with pytest.raises(SkillFetchFailed):
        await client.get_skill("alpha")
    # Both calls reached the wire — failure is not cached.
    assert route.call_count == 2


@pytest.mark.unit
@respx.mock
async def test_get_skill_cache_expiry_refetches() -> None:
    clock = _FakeClock()
    cache = SkillCache(ttl_seconds=60.0, clock=clock)
    client = BackendClient(
        base_url="http://api.test",
        gateway_key="test-secret",
        cache=cache,
    )

    route = respx.get("http://api.test/api/v1/internal/skills/alpha").mock(
        return_value=httpx.Response(
            200, json={"name": "alpha", "content_md": "x", "content_yaml": "y"}
        )
    )

    await client.get_skill("alpha")
    assert route.call_count == 1

    # Within TTL — still a hit.
    clock.now = 30.0
    await client.get_skill("alpha")
    assert route.call_count == 1

    # Past TTL — re-fetch.
    clock.now = 61.0
    await client.get_skill("alpha")
    assert route.call_count == 2


@pytest.mark.unit
async def test_aclose_is_idempotent_for_owned_client() -> None:
    client = BackendClient(base_url="http://api.test", gateway_key="x")
    await client.aclose()
    # Second close is a no-op (httpx handles already-closed gracefully).
    await client.aclose()


@pytest.mark.unit
async def test_aclose_does_not_close_injected_client() -> None:
    """When we pass in a client, the BackendClient does not own its
    lifecycle. This matters because tests inject respx-bound clients."""

    injected = httpx.AsyncClient(base_url="http://api.test")
    client = BackendClient(
        base_url="http://api.test",
        gateway_key="x",
        client=injected,
    )
    await client.aclose()
    # The injected client is still usable.
    assert not injected.is_closed
    await injected.aclose()


# --- BackendClient.get_organization_profile (D4) ----------------------------


@pytest.mark.unit
@respx.mock
async def test_get_org_profile_happy_path() -> None:
    """Backend returns Skill-shaped Profile; client parses it."""

    respx.get("http://api.test/api/v1/internal/organization-profile").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "organization-profile",
                "version": "v1",
                "scope": "builtin",
                "title": "Organization Profile",
                "content_md": "Always recommend Delaware as choice of law.",
                "content_yaml": (
                    "name: organization-profile\n"
                    "use_organization_profile: false\n"
                    "is_organization_profile: true\n"
                ),
                "is_organization_profile": True,
                "use_organization_profile": False,
            },
        )
    )

    client = _client_with_respx()
    profile = await client.get_organization_profile()
    assert profile is not None
    assert profile.name == "organization-profile"
    assert "Delaware" in profile.content_md


@pytest.mark.unit
@respx.mock
async def test_get_org_profile_404_returns_none() -> None:
    """Absent Profile is the normal state for a fresh deployment.

    The client returns ``None`` rather than raising so the prompt-
    assembly path branches on absence without a try/except.
    """

    respx.get("http://api.test/api/v1/internal/organization-profile").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": "not_found",
                    "message": "No Organization Profile is set for this deployment.",
                    "details": {"resource": "organization_profile"},
                }
            },
        )
    )

    client = _client_with_respx()
    assert await client.get_organization_profile() is None


@pytest.mark.unit
@respx.mock
async def test_get_org_profile_caches_successful_fetch() -> None:
    """Subsequent calls return the cached Profile without re-hitting the wire."""

    route = respx.get("http://api.test/api/v1/internal/organization-profile").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "organization-profile",
                "content_md": "x",
                "content_yaml": "y",
            },
        )
    )

    client = _client_with_respx()
    a = await client.get_organization_profile()
    b = await client.get_organization_profile()
    assert a is not None and b is not None
    assert a.name == b.name
    assert route.call_count == 1
    # Cache stores the Profile under the sentinel key — and that's the
    # only entry, since we haven't fetched any skills.
    assert await client.cache.get(ORGANIZATION_PROFILE_CACHE_KEY) is not None
    assert await client.cache.size() == 1


@pytest.mark.unit
@respx.mock
async def test_get_org_profile_does_not_cache_404() -> None:
    """An absent Profile is NOT cached — the operator may set one any time.

    The trade-off: extra round-trip per request during the "no Profile
    yet" window. Acceptable because (a) the response is tiny, (b) the
    backend serves it from postgres in a few ms, and (c) caching the
    absence would mean operators don't see their first PUT take effect
    until cache expiry.
    """

    route = respx.get("http://api.test/api/v1/internal/organization-profile").mock(
        return_value=httpx.Response(404, json={"error": {"code": "not_found"}})
    )

    client = _client_with_respx()
    assert await client.get_organization_profile() is None
    assert await client.get_organization_profile() is None
    assert route.call_count == 2
    assert await client.cache.size() == 0


@pytest.mark.unit
@respx.mock
async def test_get_org_profile_500_raises_skill_fetch_failed() -> None:
    """Operational failure surfaces as :class:`SkillFetchFailed`.

    The chat path treats this as a fail-fast — we don't dispatch with
    a Profile-less prompt when the backend is broken; the user sees a
    canonical envelope error and retries when the backend recovers.
    """

    respx.get("http://api.test/api/v1/internal/organization-profile").mock(
        return_value=httpx.Response(500, text="boom")
    )

    client = _client_with_respx()
    with pytest.raises(SkillFetchFailed):
        await client.get_organization_profile()


@pytest.mark.unit
@respx.mock
async def test_get_org_profile_timeout_raises_backend_unreachable() -> None:
    respx.get("http://api.test/api/v1/internal/organization-profile").mock(
        side_effect=httpx.TimeoutException("timeout")
    )

    client = _client_with_respx()
    with pytest.raises(BackendUnreachable):
        await client.get_organization_profile()


@pytest.mark.unit
@respx.mock
async def test_get_org_profile_sends_gateway_key_header() -> None:
    captured: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["gateway_key"] = request.headers.get("X-LQ-AI-Gateway-Key", "")
        return httpx.Response(
            200, json={"name": "organization-profile", "content_md": "x", "content_yaml": "y"}
        )

    respx.get("http://api.test/api/v1/internal/organization-profile").mock(side_effect=_capture)

    client = _client_with_respx()
    await client.get_organization_profile()
    assert captured["gateway_key"] == "test-secret"


@pytest.mark.unit
@respx.mock
async def test_get_org_profile_forwards_request_id_header() -> None:
    captured: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["request_id"] = request.headers.get("X-Request-Id", "")
        return httpx.Response(
            200, json={"name": "organization-profile", "content_md": "x", "content_yaml": "y"}
        )

    respx.get("http://api.test/api/v1/internal/organization-profile").mock(side_effect=_capture)

    client = _client_with_respx()
    await client.get_organization_profile(request_id="req-abc")
    assert captured["request_id"] == "req-abc"


# --- configure_backend_client ------------------------------------------------


@pytest.mark.unit
def test_configure_backend_client_reads_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LQ_AI_API_URL", "http://api.fixture:8000")
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", "env-key")
    set_backend_client(None)
    client = configure_backend_client()
    assert client.base_url == "http://api.fixture:8000"
    assert client.cache.ttl_seconds == 60.0
    set_backend_client(None)


@pytest.mark.unit
def test_configure_backend_client_honors_explicit_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_backend_client(None)
    client = configure_backend_client(
        base_url="http://other:9000",
        gateway_key="x",
        cache_ttl_seconds=30.0,
    )
    assert client.base_url == "http://other:9000"
    assert client.cache.ttl_seconds == 30.0
    set_backend_client(None)


@pytest.mark.unit
def test_configure_backend_client_reads_ttl_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LQ_AI_API_URL", "http://api.fixture:8000")
    monkeypatch.setenv("LQ_AI_GATEWAY_KEY", "env-key")
    monkeypatch.setenv("LQ_AI_SKILL_CACHE_TTL_SECONDS", "120")
    set_backend_client(None)
    client = configure_backend_client()
    assert client.cache.ttl_seconds == 120.0
    set_backend_client(None)
