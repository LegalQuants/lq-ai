"""``govinfo`` tool provider — statutory / regulatory text egress (WS-E PR1a).

Skeleton adapter: transport, auth header, and registration only. The two
operational tools (``search_authority`` / ``get_authority``) land in Task 2.
Every outbound call passes ``validate_egress_target`` (SSRF) and carries the
operator's DATA.GOV key (``X-Api-Key`` header). GovInfo data is public, so
results are marked ``skip_anonymization=True`` for verbatim verifier delivery
(ADR 0014 D5)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import ToolProviderConfig
from app.providers.base import ProviderHealth
from app.providers.tool.base import (
    ToolProviderAdapter,
    ToolProviderAuthError,
    ToolProviderError,
    ToolProviderHTTPError,
    ToolProviderInvalidRequestError,
    ToolProviderNetworkError,
    ToolResult,
    ToolSpec,
)
from app.providers.tool.egress import EgressRefused, validate_egress_target
from app.secrets import ProviderKeyResolver

DEFAULT_TIMEOUT_SECONDS = 30.0


class GovInfoToolAdapter(ToolProviderAdapter):
    """Tool adapter for the GovInfo REST API (api.govinfo.gov).

    Auth: ``X-Api-Key`` header (api.data.gov key style — NOT ``Authorization:
    Token``). Skeleton only; invoke_tool raises ToolProviderError for any tool
    until Task 2 lands the operational tool implementations.
    """

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        allowlist: list[str],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._allowlist = allowlist
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)

    @classmethod
    def from_config(
        cls,
        provider: ToolProviderConfig,
        *,
        key_resolver: ProviderKeyResolver | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> GovInfoToolAdapter:
        if provider.type != "govinfo":
            raise ValueError(f"GovInfoToolAdapter from non-govinfo provider {provider.type!r}")
        resolver = key_resolver or ProviderKeyResolver.from_environ()
        api_key = resolver.resolve(
            provider_name=provider.name,
            api_key_env=provider.api_key_env,
            api_key_encrypted=provider.api_key_encrypted,
        )
        if not api_key:
            raise ValueError(
                f"Tool provider {provider.name!r}: no GovInfo API key resolved "
                f"(set {provider.api_key_env or 'GOVINFO_API_KEY'})."
            )
        return cls(
            name=provider.name,
            base_url=provider.base_url,
            api_key=api_key,
            allowlist=provider.allowlist.hosts,
            client=client,
        )

    def validate_base_url(self) -> None:
        validate_egress_target(self._base_url + "/", allowlist=self._allowlist)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """SSRF-guard + issue one request with api.data.gov key auth; map errors."""
        url = f"{self._base_url}{path}"
        validate_egress_target(url, allowlist=self._allowlist)
        headers: dict[str, str] = {"X-Api-Key": self._api_key}
        try:
            resp = await self._client.request(
                method, url, params=params, json=json_body, headers=headers
            )
        except EgressRefused:
            raise
        except httpx.HTTPError as exc:
            raise ToolProviderNetworkError(f"govinfo network error: {exc}") from exc
        if resp.status_code in (401, 403):
            raise ToolProviderAuthError("govinfo rejected the API key")
        if resp.status_code == 429:
            raise ToolProviderHTTPError("govinfo rate limit", upstream_status=429)
        if 400 <= resp.status_code < 500:
            raise ToolProviderInvalidRequestError(
                f"govinfo rejected the request ({resp.status_code})",
                upstream_status=resp.status_code,
            )
        if resp.status_code >= 500:
            raise ToolProviderHTTPError("govinfo upstream error", upstream_status=resp.status_code)
        return resp

    async def list_tools(self, *, user_token: str | None = None) -> list[ToolSpec]:
        # Task 2 lands search_authority + get_authority; skeleton returns empty.
        return []

    async def invoke_tool(
        self, tool: str, args: dict[str, Any], *, request_id: str, user_token: str | None = None
    ) -> ToolResult:
        raise ToolProviderError(f"unknown tool {tool!r} for govinfo provider")

    def _result(self, tool: str, payload: Any, *, sent: Any, received: Any) -> ToolResult:
        """Build a ToolResult with byte counts; mark public statutory text verbatim."""
        return ToolResult(
            provider=self.name,
            tool=tool,
            payload=payload,
            bytes_out=len(json.dumps(sent).encode("utf-8")),
            bytes_in=len(json.dumps(received).encode("utf-8")),
            skip_anonymization=True,
        )

    async def health_check(self) -> ProviderHealth:
        try:
            await self._request("GET", "/collections")
        except ToolProviderError as exc:
            return ProviderHealth(name=self.name, reachable=False, error=str(exc))
        return ProviderHealth(name=self.name, reachable=True, latency_ms=0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
