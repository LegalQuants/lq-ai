"""``courtlistener`` tool provider — case-law research egress (ADR 0014, WS3a).

Three read tools over the CourtListener REST API v4, brokered through the
gateway egress boundary. Stateless: caching/storage is api-side (PR3). Every
outbound call passes ``validate_egress_target`` (SSRF) and carries the
operator's token. CourtListener data is public, so results are marked
``skip_anonymization=True`` for verbatim citation grounding (ADR 0014 D5)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

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

_OPINION_TEXT_FIELDS = (
    "html_with_citations",
    "html_columbia",
    "html_lawbox",
    "xml_harvard",
    "html_anon_2020",
    "html",
    "plain_text",
)


def _cursor_from(next_url: str | None) -> str | None:
    """Extract the opaque ``cursor`` value from a CourtListener ``next`` URL."""
    if not next_url:
        return None
    cursor = parse_qs(urlparse(next_url).query).get("cursor")
    return cursor[0] if cursor else None


def _select_opinion_text(opinion: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (field_name, text) of the first non-empty opinion text field,
    by CourtListener's documented reliability order."""
    for field in _OPINION_TEXT_FIELDS:
        value = opinion.get(field)
        if isinstance(value, str) and value.strip():
            return field, value
    return None, None


class CourtListenerToolAdapter(ToolProviderAdapter):
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
    ) -> CourtListenerToolAdapter:
        if provider.type != "courtlistener":
            raise ValueError(f"CourtListenerToolAdapter from non-courtlistener {provider.type!r}")
        resolver = key_resolver or ProviderKeyResolver.from_environ()
        api_key = resolver.resolve(
            provider_name=provider.name,
            api_key_env=provider.api_key_env,
            api_key_encrypted=provider.api_key_encrypted,
        )
        if not api_key:
            raise ValueError(
                f"Tool provider {provider.name!r}: no CourtListener token resolved "
                f"(set {provider.api_key_env or 'COURTLISTENER_API_TOKEN'})."
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
        """SSRF-guard + issue one request with token auth; map errors."""
        url = f"{self._base_url}{path}"
        validate_egress_target(url, allowlist=self._allowlist)
        headers = {"Authorization": f"Token {self._api_key}"}
        try:
            resp = await self._client.request(
                method, url, params=params, json=json_body, headers=headers
            )
        except EgressRefused:
            raise
        except httpx.HTTPError as exc:
            raise ToolProviderNetworkError(f"courtlistener network error: {exc}") from exc
        if resp.status_code in (401, 403):
            raise ToolProviderAuthError("courtlistener rejected the token")
        if resp.status_code == 429:
            raise ToolProviderHTTPError("courtlistener rate limit", upstream_status=429)
        if 400 <= resp.status_code < 500:
            raise ToolProviderInvalidRequestError(
                f"courtlistener rejected the request ({resp.status_code})",
                upstream_status=resp.status_code,
            )
        if resp.status_code >= 500:
            raise ToolProviderHTTPError(
                "courtlistener upstream error", upstream_status=resp.status_code
            )
        return resp

    async def list_tools(self, *, user_token: str | None = None) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="verify_citations",
                description="Verify reporter citations (e.g. '576 U.S. 644') against "
                "CourtListener; returns matched clusters + status per citation.",
                parameters={
                    "type": "object",
                    "properties": {"text": {"type": "string", "maxLength": 64000}},
                    "required": ["text"],
                },
                read_only=True,
            ),
            ToolSpec(
                name="search_case_law",
                description="Full-text search of case-law opinion clusters. Returns "
                "total count + a page of minimal result metadata.",
                parameters={
                    "type": "object",
                    "properties": {
                        "q": {"type": "string"},
                        "court": {"type": "string"},
                        "order_by": {"type": "string"},
                    },
                    "required": ["q"],
                },
                read_only=True,
            ),
            ToolSpec(
                name="get_cases",
                description="Fetch one opinion cluster's metadata + its opinion "
                "texts by cluster id.",
                parameters={
                    "type": "object",
                    "properties": {"cluster_id": {"type": "integer"}},
                    "required": ["cluster_id"],
                },
                read_only=True,
            ),
        ]

    async def invoke_tool(
        self, tool: str, args: dict[str, Any], *, request_id: str, user_token: str | None = None
    ) -> ToolResult:
        if tool == "verify_citations":
            return await self._verify_citations(args)
        if tool == "search_case_law":
            return await self._search_case_law(args)
        if tool == "get_cases":
            return await self._get_cases(args)
        raise ToolProviderError(f"unknown tool {tool!r} for courtlistener provider")

    async def _verify_citations(self, args: dict[str, Any]) -> ToolResult:
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ToolProviderInvalidRequestError(
                "verify_citations requires non-empty 'text'", upstream_status=400
            )
        body = {"text": text[:64000]}
        resp = await self._request("POST", "/citation-lookup/", json_body=body)
        data = resp.json()
        citations = [
            {
                "citation": item.get("citation"),
                "normalized_citations": item.get("normalized_citations", []),
                "status": item.get("status"),
                "error_message": item.get("error_message") or None,
                "clusters": [
                    {
                        "id": c.get("id"),
                        "case_name": c.get("case_name"),
                        "absolute_url": c.get("absolute_url"),
                    }
                    for c in item.get("clusters", [])
                ],
            }
            for item in data
        ]
        return self._result("verify_citations", {"citations": citations}, sent=body, received=data)

    async def _search_case_law(self, args: dict[str, Any]) -> ToolResult:
        q = args.get("q")
        if not isinstance(q, str) or not q.strip():
            raise ToolProviderInvalidRequestError(
                "search_case_law requires non-empty 'q'", upstream_status=400
            )
        params: dict[str, Any] = {"q": q, "type": "o"}
        if isinstance(args.get("court"), str):
            params["court"] = args["court"]
        if isinstance(args.get("order_by"), str):
            params["order_by"] = args["order_by"]
        if isinstance(args.get("cursor"), str) and args["cursor"]:
            params["cursor"] = args["cursor"]
        resp = await self._request("GET", "/search/", params=params)
        data = resp.json()
        results = [
            {
                "cluster_id": r.get("cluster_id"),
                "case_name": r.get("caseName"),
                "court": r.get("court"),
                "date_filed": r.get("dateFiled"),
                "citation": r.get("citation"),
                "absolute_url": r.get("absolute_url"),
                "snippet": r.get("snippet"),
            }
            for r in data.get("results", [])
        ]
        payload = {
            "count": data.get("count"),
            "results": results,
            "next_cursor": _cursor_from(data.get("next")),
        }
        return self._result("search_case_law", payload, sent=params, received=data)

    async def _get_cases(self, args: dict[str, Any]) -> ToolResult:
        cluster_id = args.get("cluster_id")
        if not isinstance(cluster_id, int) or isinstance(cluster_id, bool):
            raise ToolProviderInvalidRequestError(
                "get_cases requires integer 'cluster_id'", upstream_status=400
            )
        cluster_resp = await self._request("GET", f"/clusters/{cluster_id}/")
        cluster = cluster_resp.json()
        opinions: list[dict[str, Any]] = []
        for op_url in cluster.get("sub_opinions", []):
            path = op_url.split("/api/rest/v4", 1)[-1] if "/api/rest/v4" in op_url else op_url
            op_resp = await self._request("GET", path)
            op = op_resp.json()
            field, text = _select_opinion_text(op)
            opinions.append({"id": op.get("id"), "text_field_used": field, "text": text})
        payload = {
            "cluster": {
                "id": cluster.get("id"),
                "case_name": cluster.get("case_name"),
                "case_name_short": cluster.get("case_name_short"),
                "date_filed": cluster.get("date_filed"),
                "citations": cluster.get("citations"),
                "court": cluster.get("court"),
                "absolute_url": cluster.get("absolute_url"),
            },
            "opinions": opinions,
        }
        return self._result("get_cases", payload, sent={"cluster_id": cluster_id}, received=cluster)

    def _result(self, tool: str, payload: Any, *, sent: Any, received: Any) -> ToolResult:
        """Build a ToolResult with byte counts; mark public data verbatim."""
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
            await self._request("GET", "/courts/", params={"page_size": 1})
        except ToolProviderError as exc:
            return ProviderHealth(name=self.name, reachable=False, error=str(exc))
        return ProviderHealth(name=self.name, reachable=True, latency_ms=0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
