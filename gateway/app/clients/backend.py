"""HTTP client + cache for the backend's internal-skills endpoint (C2).

Per ADR 0007 the gateway fetches skill content from the backend's
``GET /api/v1/internal/skills/{name}`` endpoint during prompt assembly.
This module owns:

* :class:`BackendClient` — long-lived ``httpx.AsyncClient`` pool wired
  to the ``LQ_AI_API_URL`` base; stamps the shared
  ``X-LQ-AI-Gateway-Key`` header on every outbound call.
* :class:`SkillCache` — process-local TTL cache keyed by skill name.
  Default TTL is 60s. Invalidation is implicit (TTL expiry); the
  human-attestation pipeline tolerates seconds-to-minutes of staleness.
* :func:`get_backend_client` / :func:`set_backend_client` —
  dependency-injection seam for tests; the lifespan in
  ``app/main.py`` constructs the singleton at startup.

Error translation
-----------------

Failures from the backend are translated to the gateway's typed error
hierarchy (per ADR 0003 and the C2 additions):

* HTTP 404 → :class:`SkillNotFound` (the named skill is not in the
  registry).
* HTTP 5xx, 4xx-non-404, network errors, timeouts, malformed bodies →
  :class:`SkillFetchFailed` (operational failure).
* HTTP 401 → :class:`SkillFetchFailed` plus an ERROR log naming the
  misconfiguration (the operator must rotate / sync the gateway key).

The gateway's exception handler (``app.main._lqai_error_handler``)
serializes each to the canonical envelope; the backend's GatewayClient
maps the codes back through ``map_gateway_error_code``.

Caching
-------

The cache is a small ``dict[str, _CacheEntry]`` guarded by an
``asyncio.Lock``. On hit, returns the cached :class:`Skill`. On miss
or expiry, fetches fresh from the backend and replaces the entry. The
cache holds ``Skill`` Pydantic models — the same shape ``api/`` serves
over the wire.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.errors import (
    SkillFetchFailed,
    SkillNotFound,
)

log = logging.getLogger(__name__)

# Operator-configurable env vars. ``LQ_AI_API_URL`` already exists in
# ``.env.example`` and ``docker-compose.yml`` (the web service uses it
# for delegated auth); we read the same var so operators only configure
# one URL.
ENV_API_URL: Final[str] = "LQ_AI_API_URL"
ENV_GATEWAY_KEY: Final[str] = "LQ_AI_GATEWAY_KEY"
ENV_CACHE_TTL: Final[str] = "LQ_AI_SKILL_CACHE_TTL_SECONDS"

DEFAULT_API_URL: Final[str] = "http://api:8000"
"""Default backend URL for the Compose stack."""

DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0
"""Per-request timeout. Skill fetches are tiny JSON payloads on the
intra-cluster network; 10s is generous. Smaller than the chat-completion
timeout because we want the assembler to fail fast if the backend is
struggling."""

DEFAULT_CACHE_TTL_SECONDS: Final[float] = 60.0
"""Default TTL for the skill cache; tunable via LQ_AI_SKILL_CACHE_TTL_SECONDS."""

GATEWAY_KEY_HEADER: Final[str] = "X-LQ-AI-Gateway-Key"
"""Shared-secret header sent on every gateway → backend call (ADR 0007)."""

ORGANIZATION_PROFILE_CACHE_KEY: Final[str] = "__organization_profile__"
"""Sentinel key under which the singleton Organization Profile is cached.

Re-uses the :class:`SkillCache` machinery so the Profile gets the same
TTL and locking as skill fetches. The double-underscore prefix can never
collide with a real skill name (skills are filesystem-canonical and the
loader validates folder names against a kebab-case identifier shape)."""


def _skill_cache_key(name: str, user_id: str | None) -> str:
    """Encode (skill name, user_id) into a single cache key.

    Per ADR 0012 the gateway must hold user-scope shadows in a
    per-user cache slot so user A's edits never bleed into user B's
    chats. The encoding uses ``|`` as a separator — skill names are
    kebab-case and UUIDs use dashes, so the separator is unambiguous.
    A missing ``user_id`` becomes ``__none__`` so the registry-only
    view gets its own slot distinct from any user's shadow at the
    same skill name.
    """

    return f"{name}|{user_id or '__none__'}"


# --- Skill response shape ----------------------------------------------------


class SkillFile(BaseModel):
    """One reference or example file the backend surfaces in a Skill response.

    Mirrors ``SkillFile`` in ``docs/api/backend-openapi.yaml`` (and the
    api/ side's ``app.skills.schema.SkillFile``).
    """

    model_config = ConfigDict(extra="allow")

    path: str
    content: str


class Skill(BaseModel):
    """Cached skill content, mirroring ``api/`` 's ``Skill`` shape.

    Subset of fields that the prompt assembler actually consumes plus
    the metadata that flows through to the audit log. Permissive
    (``extra="allow"``) so backend-side schema additions don't break
    the gateway's parser.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    version: str = "unversioned"
    scope: str = "builtin"
    title: str = ""
    description: str | None = None
    content_md: str = ""
    content_yaml: str = ""
    minimum_inference_tier: int | None = None
    tags: list[str] = Field(default_factory=list)
    jurisdiction: str | None = None
    output_format: str | None = None
    reference_files: list[SkillFile] = Field(default_factory=list)
    example_files: list[SkillFile] = Field(default_factory=list)


# --- Cache -------------------------------------------------------------------


@dataclass
class _CacheEntry:
    skill: Skill
    fetched_at: float


class SkillCache:
    """In-memory TTL cache for skill content.

    Process-local; a multi-replica gateway holds independent caches.
    The TTL (default 60s) is comfortably below any operationally
    meaningful staleness window for the human-attestation pipeline.

    The cache also exposes :meth:`invalidate` (single key) and
    :meth:`clear` (whole cache) for tests and admin workflows. The
    monotonic clock is used so wall-clock changes don't cause the
    cache to stutter; tests inject a fake clock for determinism.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic
        self._entries: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    async def get(self, name: str) -> Skill | None:
        """Return the cached skill or ``None`` on miss / expiry."""

        async with self._lock:
            entry = self._entries.get(name)
            if entry is None:
                return None
            if self._clock() - entry.fetched_at > self._ttl:
                # Expired — drop it so the next get sees an honest miss.
                del self._entries[name]
                return None
            return entry.skill

    async def put(self, name: str, skill: Skill) -> None:
        async with self._lock:
            self._entries[name] = _CacheEntry(skill=skill, fetched_at=self._clock())

    async def invalidate(self, name: str) -> None:
        async with self._lock:
            self._entries.pop(name, None)

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()

    async def size(self) -> int:
        async with self._lock:
            return len(self._entries)


# --- HTTP client -------------------------------------------------------------


class BackendUnreachable(SkillFetchFailed):
    """Convenience subclass for transport-level failures.

    Same wire code as :class:`SkillFetchFailed`; subclassing helps
    callers (and tests) branch on "transport problem" vs "structured
    backend error" when that's useful.
    """


class BackendClient:
    """Async HTTP client wrapping calls to the LQ.AI backend.

    Construct once at gateway startup. The underlying
    ``httpx.AsyncClient`` is reused across all calls (per CLAUDE.md
    "reuse the same client across calls"). Closing happens at shutdown
    via :meth:`aclose`.
    """

    def __init__(
        self,
        *,
        base_url: str,
        gateway_key: str,
        cache: SkillCache | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._gateway_key = gateway_key
        self._timeout = timeout
        self._cache = cache if cache is not None else SkillCache()
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            default_headers = {GATEWAY_KEY_HEADER: gateway_key} if gateway_key else {}
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=timeout,
                headers=default_headers,
            )
            self._owns_client = True

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def cache(self) -> SkillCache:
        return self._cache

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Expose the underlying client (used by tests for respx hooks)."""

        return self._client

    async def aclose(self) -> None:
        """Close the owned httpx client. Idempotent."""

        if self._owns_client:
            await self._client.aclose()

    # --- Skill fetching ------------------------------------------------------

    async def get_skill(
        self,
        name: str,
        *,
        request_id: str | None = None,
        user_id: str | None = None,
    ) -> Skill:
        """Fetch a skill from the backend's internal-skills endpoint.

        Cache-aware: a hit returns immediately. A miss fetches over
        HTTP and populates the cache before returning. Failures raise
        the appropriate typed exception; nothing is cached on failure.

        When ``user_id`` is set, the backend resolves a user-scope
        shadow before the filesystem-canonical registry (ADR 0012).
        The cache keys on ``(name, user_id)`` so user A's shadow
        doesn't bleed into user B's chats — and the
        registry-only view (when ``user_id`` is omitted) gets its
        own cache slot too.
        """

        key = _skill_cache_key(name, user_id)
        cached = await self._cache.get(key)
        if cached is not None:
            return cached

        skill = await self._fetch_skill(name, request_id=request_id, user_id=user_id)
        await self._cache.put(key, skill)
        return skill

    async def get_organization_profile(
        self,
        *,
        request_id: str | None = None,
    ) -> Skill | None:
        """Fetch the deployment's Organization Profile, or None if unset.

        Cache-aware on the same :class:`SkillCache` instance under the
        :data:`ORGANIZATION_PROFILE_CACHE_KEY` sentinel; the TTL is the
        skill cache's TTL because the Profile shapes the same prompt
        path and the same staleness window applies. Returns ``None``
        when the backend reports 404 (no row, or the row's body is
        empty) — the prompt-assembly path branches on absence rather
        than catching exceptions, since "no Profile" is the normal
        operating state for a fresh deployment.

        Other failures (network, 5xx, schema-validation) raise the
        usual :class:`SkillFetchFailed` / :class:`BackendUnreachable`
        so the caller fails-fast on real outages.
        """

        cached = await self._cache.get(ORGANIZATION_PROFILE_CACHE_KEY)
        if cached is not None:
            return cached

        path = "/api/v1/internal/organization-profile"
        headers: dict[str, str] | None = None
        if request_id is not None:
            headers = {"X-Request-Id": request_id}

        try:
            response = await self._client.get(path, headers=headers)
        except httpx.TimeoutException as exc:
            log.warning(
                "backend organization-profile fetch timed out: request_id=%s",
                request_id,
            )
            raise BackendUnreachable(
                "Backend organization-profile fetch timed out",
                details={"timeout_seconds": self._timeout},
            ) from exc
        except httpx.HTTPError as exc:
            log.warning(
                "backend organization-profile fetch transport failure: error=%s",
                type(exc).__name__,
            )
            raise BackendUnreachable(
                "Could not reach the backend to fetch the Organization Profile",
                details={"transport_error": type(exc).__name__},
            ) from exc

        # 404 is the "no Profile" path — cache the absence so we don't
        # re-hit the backend on every chat request. We can't store
        # ``None`` directly in the SkillCache (the type contract is
        # ``Skill | None`` on get / ``Skill`` on put), so we leave the
        # cache untouched on absence. The TTL is short enough (60s
        # default) that operators editing the Profile see their first
        # post-save chat pick it up; the trade-off vs. caching absence
        # is at most one extra HTTP roundtrip per request during the
        # first minute of a deployment-with-no-Profile, which is fine.
        if response.status_code == 404:
            return None

        skill = _parse_skill_response("organization-profile", response)
        await self._cache.put(ORGANIZATION_PROFILE_CACHE_KEY, skill)
        return skill

    async def _fetch_skill(
        self,
        name: str,
        *,
        request_id: str | None,
        user_id: str | None = None,
    ) -> Skill:
        """Issue the HTTP call and parse the response.

        Threads ``user_id`` as a ``?user_id=`` query param so the
        backend's resolver checks for a user-scope shadow first per
        ADR 0012. When ``user_id`` is ``None`` the param is omitted
        and the backend returns the filesystem-canonical row.
        """

        path = f"/api/v1/internal/skills/{name}"
        headers: dict[str, str] | None = None
        if request_id is not None:
            headers = {"X-Request-Id": request_id}
        params: dict[str, str] | None = None
        if user_id is not None:
            params = {"user_id": user_id}

        try:
            response = await self._client.get(path, headers=headers, params=params)
        except httpx.TimeoutException as exc:
            log.warning(
                "backend skill fetch timed out: name=%s request_id=%s",
                name,
                request_id,
            )
            raise BackendUnreachable(
                f"Backend skill fetch timed out for {name!r}",
                details={"skill_name": name, "timeout_seconds": self._timeout},
            ) from exc
        except httpx.HTTPError as exc:
            log.warning(
                "backend skill fetch transport failure: name=%s error=%s",
                name,
                type(exc).__name__,
            )
            raise BackendUnreachable(
                f"Could not reach the backend to fetch skill {name!r}",
                details={"skill_name": name, "transport_error": type(exc).__name__},
            ) from exc

        return _parse_skill_response(name, response)


def _parse_skill_response(name: str, response: httpx.Response) -> Skill:
    """Translate the backend response into a Skill or a typed error."""

    status_code = response.status_code

    if status_code == 200:
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise SkillFetchFailed(
                f"Backend returned non-JSON success body for skill {name!r}",
                details={"skill_name": name},
            ) from exc
        try:
            return Skill.model_validate(payload)
        except ValidationError as exc:
            raise SkillFetchFailed(
                f"Backend skill response failed schema validation for {name!r}",
                details={"skill_name": name, "validation_errors": exc.errors()},
            ) from exc

    if status_code == 404:
        raise SkillNotFound(
            f"Skill {name!r} is not in the backend's registry",
            details={"skill_name": name},
        )

    if status_code == 401:
        log.error(
            "backend rejected gateway-key header (401) on skill fetch: name=%s. "
            "Check that LQ_AI_GATEWAY_KEY matches between api/ and gateway/.",
            name,
        )
        raise SkillFetchFailed(
            f"Backend rejected the gateway-key header while fetching skill {name!r}",
            details={"skill_name": name, "reason": "operator-configuration"},
        )

    # All other statuses (500, 502, 503, etc.) — operational failure.
    log.warning(
        "backend skill fetch returned %s for name=%s",
        status_code,
        name,
    )
    raise SkillFetchFailed(
        f"Backend returned HTTP {status_code} fetching skill {name!r}",
        details={"skill_name": name, "status_code": status_code},
    )


# --- Process-global handle ---------------------------------------------------


_client: BackendClient | None = None


def configure_backend_client(
    *,
    base_url: str | None = None,
    gateway_key: str | None = None,
    cache_ttl_seconds: float | None = None,
) -> BackendClient:
    """Construct (or reconstruct) the process-global backend client.

    Reads ``LQ_AI_API_URL`` and ``LQ_AI_GATEWAY_KEY`` (or
    ``LQ_AI_GATEWAY_KEY_FILE``) from the environment when arguments are
    not supplied. Returns the new instance and stores it as the
    process-global handle. Callers that need to swap out an existing
    client should call :func:`close_backend_client` first.
    """

    global _client

    from app.secrets import resolve_secret

    resolved_url = base_url or os.environ.get(ENV_API_URL) or DEFAULT_API_URL
    resolved_key = gateway_key if gateway_key is not None else resolve_secret(ENV_GATEWAY_KEY) or ""
    if cache_ttl_seconds is None:
        env_ttl = os.environ.get(ENV_CACHE_TTL)
        cache_ttl_seconds = float(env_ttl) if env_ttl else DEFAULT_CACHE_TTL_SECONDS
    cache = SkillCache(ttl_seconds=cache_ttl_seconds)

    _client = BackendClient(
        base_url=resolved_url,
        gateway_key=resolved_key,
        cache=cache,
    )
    log.info(
        "backend client configured: base_url=%s cache_ttl_seconds=%s key_set=%s",
        resolved_url,
        cache_ttl_seconds,
        bool(resolved_key),
    )
    return _client


def get_backend_client() -> BackendClient:
    """Return the process-global backend client, building it on first call.

    The lifespan handler calls :func:`configure_backend_client` at
    startup; tests that bypass lifespan get a default-configured
    client on the first call.
    """

    global _client
    if _client is None:
        _client = configure_backend_client()
    return _client


def set_backend_client(client: BackendClient | None) -> None:
    """Override the process-global backend client (used by tests)."""

    global _client
    _client = client


async def close_backend_client() -> None:
    """Close the process-global backend client on shutdown."""

    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


__all__ = [
    "DEFAULT_API_URL",
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "ENV_API_URL",
    "ENV_CACHE_TTL",
    "ENV_GATEWAY_KEY",
    "GATEWAY_KEY_HEADER",
    "ORGANIZATION_PROFILE_CACHE_KEY",
    "BackendClient",
    "BackendUnreachable",
    "Skill",
    "SkillCache",
    "SkillFetchFailed",
    "SkillFile",
    "SkillNotFound",
    "close_backend_client",
    "configure_backend_client",
    "get_backend_client",
    "set_backend_client",
]
