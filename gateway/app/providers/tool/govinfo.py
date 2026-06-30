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
from urllib.parse import urlparse

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

# PR1a supports USCODE and CFR; additional collections land in later PRs (DE-344 scope).
_SUPPORTED_COLLECTIONS: frozenset[str] = frozenset({"USCODE", "CFR"})


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
        return [
            ToolSpec(
                name="search_authority",
                description=(
                    "Full-text search of US statutory (USCODE) and regulatory (CFR) text "
                    "via GovInfo. Returns a list of matching package identifiers with "
                    "title, collection, and date metadata."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "collection": {
                            "type": "string",
                            "enum": sorted(_SUPPORTED_COLLECTIONS),
                            "description": "The GovInfo collection to search (USCODE or CFR).",
                        },
                        "query": {
                            "type": "string",
                            "description": "Search query string.",
                        },
                        "page_size": {
                            "type": "integer",
                            "description": "Maximum results to return (default 10).",
                        },
                    },
                    "required": ["collection", "query"],
                },
                read_only=True,
            ),
            ToolSpec(
                name="get_authority",
                description=(
                    "Fetch the full text and metadata of a GovInfo package (e.g. a "
                    "USCODE title or CFR part) by its packageId."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "package_id": {
                            "type": "string",
                            "description": "GovInfo packageId (e.g. USCODE-2023-title15).",
                        },
                    },
                    "required": ["package_id"],
                },
                read_only=True,
            ),
        ]

    async def invoke_tool(
        self, tool: str, args: dict[str, Any], *, request_id: str, user_token: str | None = None
    ) -> ToolResult:
        if tool == "search_authority":
            return await self._search_authority(args)
        if tool == "get_authority":
            return await self._get_authority(args)
        raise ToolProviderError(f"unknown tool {tool!r} for govinfo provider")

    async def _search_authority(self, args: dict[str, Any]) -> ToolResult:
        """POST /search — normalize GovInfo results to snake_case output.

        Validates that ``collection`` is one of the PR1a-supported codes
        (USCODE, CFR) and that ``query`` is non-empty. Raises
        :class:`~app.providers.tool.base.ToolProviderInvalidRequestError`
        on bad input so the router can log a clean refusal.
        """
        collection = args.get("collection")
        query = args.get("query")
        raw_page_size = args.get("page_size", 10)
        page_size: int = (
            raw_page_size
            if isinstance(raw_page_size, int)
            and not isinstance(raw_page_size, bool)
            and raw_page_size >= 1
            else 10
        )

        if collection not in _SUPPORTED_COLLECTIONS:
            raise ToolProviderInvalidRequestError(
                f"search_authority: 'collection' must be one of "
                f"{sorted(_SUPPORTED_COLLECTIONS)}; got {collection!r}",
                upstream_status=400,
            )
        if not isinstance(query, str) or not query.strip():
            raise ToolProviderInvalidRequestError(
                "search_authority: 'query' must be a non-empty string",
                upstream_status=400,
            )

        body: dict[str, Any] = {
            "query": query,
            "pageSize": page_size,
            "offsetMark": "*",
            "collections": [collection],
        }
        resp = await self._request("POST", "/search", json_body=body)
        data: dict[str, Any] = resp.json()

        results = [
            {
                "package_id": r.get("packageId"),
                "title": r.get("title"),
                "collection": r.get("collectionCode"),
                "date": r.get("dateIssued"),
            }
            for r in data.get("results", [])
        ]
        payload: dict[str, Any] = {
            "results": results,
            "count": data.get("count", len(results)),
        }
        return self._result("search_authority", payload, sent=body, received=data)

    async def _get_authority(self, args: dict[str, Any]) -> ToolResult:
        """GET /packages/{packageId}/summary then follow txtLink for text content.

        Accepts ``package_id`` (primary) or ``granule_id`` (alias). Fetches
        the GovInfo package summary for metadata and the ``download.txtLink``
        URL for the full statutory/regulatory text. Both requests go through
        :meth:`_request` so SSRF validation is applied to each outbound call.
        """
        package_id = args.get("package_id") or args.get("granule_id")
        if not isinstance(package_id, str) or not package_id.strip():
            raise ToolProviderInvalidRequestError(
                "get_authority: 'package_id' (or 'granule_id') must be a non-empty string",
                upstream_status=400,
            )

        # 1. Fetch package summary → metadata + download links
        resp = await self._request("GET", f"/packages/{package_id}/summary")
        summary: dict[str, Any] = resp.json()

        # 2. Follow txtLink (HTML format) for the statutory/regulatory text.
        #    txtLink is absolute (e.g. https://api.govinfo.gov/packages/{id}/htm);
        #    extract the path so _request handles SSRF validation.
        download: dict[str, Any] = summary.get("download") or {}
        txt_link: str | None = download.get("txtLink") or None
        text: str | None = None
        if txt_link:
            path = urlparse(txt_link).path
            text_resp = await self._request("GET", path)
            text = text_resp.text

        url = txt_link or f"{self._base_url}/packages/{package_id}/summary"
        payload: dict[str, Any] = {
            "package_id": summary.get("packageId", package_id),
            "title": summary.get("title"),
            "citation": summary.get("suDocClassNumber") or None,
            "url": url,
            "text": text,
        }
        return self._result(
            "get_authority", payload, sent={"package_id": package_id}, received=summary
        )

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
