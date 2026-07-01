"""``edgar`` tool provider — SEC EDGAR filing search + retrieval (WS-E PR2a).

Auth model differs from GovInfo/CourtListener: SEC's fair-access policy
requires a descriptive ``User-Agent`` header identifying the requester, and
issues NO API key. Every outbound call still passes ``validate_egress_target``
(SSRF) against the configured host allowlist (``efts.sec.gov`` for full-text
search, ``www.sec.gov`` for filing archives). EDGAR filing text is public, so
results are marked ``skip_anonymization=True`` for verbatim verifier delivery
(ADR 0014 D5), mirroring the GovInfo/CourtListener adapters.

``external_ref`` is encoded as ``{cik}_{accession_no_dashes}_{document}``
(digits/letters/``.``/``_``/``-`` only) rather than a URL or a ``:``/``/``
delimited triple: a downstream cache-key guard rejects ``:`` and ``/`` in
``external_ref`` values (WS-E PR1b substrate), so this adapter never emits
either character in the ref it hands back to callers."""

from __future__ import annotations

import re
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

DEFAULT_TIMEOUT_SECONDS = 30.0

_EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class EdgarToolAdapter(ToolProviderAdapter):
    """Tool adapter for the SEC EDGAR full-text search + archives APIs.

    Auth: a descriptive ``User-Agent`` header (no API key). Supports two
    read-only operations: ``search_authority`` for full-text search across
    company filings, and ``get_authority`` for fetching one filing document's
    plaintext by ``external_ref``.
    """

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        user_agent: str,
        allowlist: list[str],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._allowlist = allowlist
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)

    @classmethod
    def from_config(
        cls,
        provider: ToolProviderConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> EdgarToolAdapter:
        if provider.type != "edgar":
            raise ValueError(f"EdgarToolAdapter from non-edgar provider {provider.type!r}")
        if not provider.user_agent:
            raise ValueError(
                f"Tool provider {provider.name!r}: type 'edgar' requires a descriptive "
                f"user_agent (SEC fair-access policy substitutes for an API key)."
            )
        return cls(
            name=provider.name,
            base_url=provider.base_url,
            user_agent=provider.user_agent,
            allowlist=provider.allowlist.hosts,
            client=client,
        )

    def validate_base_url(self) -> None:
        validate_egress_target(self._base_url + "/", allowlist=self._allowlist)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """SSRF-guard + issue one request with User-Agent auth; map errors."""
        validate_egress_target(url, allowlist=self._allowlist)
        headers = {"User-Agent": self._user_agent}
        try:
            resp = await self._client.request(method, url, params=params, headers=headers)
        except EgressRefused:
            raise
        except httpx.HTTPError as exc:
            raise ToolProviderNetworkError(f"edgar network error: {exc}") from exc
        if resp.status_code in (401, 403):
            raise ToolProviderAuthError("edgar rejected the request (missing/bad User-Agent)")
        if resp.status_code == 429:
            raise ToolProviderHTTPError("edgar rate limit", upstream_status=429)
        if 400 <= resp.status_code < 500:
            raise ToolProviderInvalidRequestError(
                f"edgar rejected the request ({resp.status_code})",
                upstream_status=resp.status_code,
            )
        if resp.status_code >= 500:
            raise ToolProviderHTTPError("edgar upstream error", upstream_status=resp.status_code)
        return resp

    async def list_tools(self, *, user_token: str | None = None) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="search_authority",
                description=(
                    "Full-text search SEC EDGAR company filings (10-K, 8-K, S-1, etc). "
                    "Returns filings with an external_ref usable by get_authority."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query string."},
                        "forms": {
                            "type": "string",
                            "description": (
                                "Optional comma-separated form types to filter by, e.g. '10-K,8-K'."
                            ),
                        },
                    },
                    "required": ["query"],
                },
                read_only=True,
            ),
            ToolSpec(
                name="get_authority",
                description="Fetch the full text of a specific SEC EDGAR filing document by external_ref.",
                parameters={
                    "type": "object",
                    "properties": {
                        "external_ref": {
                            "type": "string",
                            "description": "external_ref returned by search_authority.",
                        }
                    },
                    "required": ["external_ref"],
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
        raise ToolProviderError(f"unknown tool {tool!r} for edgar provider")

    async def _search_authority(self, args: dict[str, Any]) -> ToolResult:
        """GET efts.sec.gov full-text search — normalize hits to snake_case output.

        Builds ``external_ref`` as ``{cik}_{accession_no_dashes}_{document}``
        from each hit's ``_id`` (``{accession}:{document}``) and
        ``_source.ciks``/``_source.adsh``. Hits missing any of the three
        components are dropped rather than surfaced with a broken ref.
        """
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolProviderInvalidRequestError(
                "search_authority requires non-empty 'query'", upstream_status=400
            )
        params: dict[str, Any] = {"q": query}
        forms = args.get("forms")
        if isinstance(forms, str) and forms.strip():
            params["forms"] = forms

        resp = await self._request("GET", _EFTS_SEARCH_URL, params=params)
        body: dict[str, Any] = resp.json()
        hits: dict[str, Any] = body.get("hits", {})

        results: list[dict[str, Any]] = []
        for hit in hits.get("hits", []):
            source: dict[str, Any] = hit.get("_source", {})
            hit_id: str = hit.get("_id", "")
            accession: str = source.get("adsh", "")
            document = hit_id.split(":", 1)[1] if ":" in hit_id else ""
            ciks = source.get("ciks") or []
            cik = ciks[0] if ciks else ""
            external_ref = ""
            if cik and accession and document:
                external_ref = f"{int(cik)}_{accession.replace('-', '')}_{document}"
            if not external_ref:
                continue
            names = source.get("display_names") or []
            company = names[0].strip() if names else ""
            form_type = source.get("form", "")
            filed_date = source.get("file_date", "")
            title = f"{company} — {form_type} ({filed_date})".strip(" —")
            results.append(
                {
                    "external_ref": external_ref,
                    "form_type": form_type,
                    "company": company,
                    "filed_date": filed_date,
                    "title": title,
                }
            )

        payload = {
            "results": results,
            "count": hits.get("total", {}).get("value", len(results)),
        }
        return self._result("search_authority", payload, resp)

    async def _get_authority(self, args: dict[str, Any]) -> ToolResult:
        """GET www.sec.gov/Archives filing document; strip HTML to plaintext.

        Accepts ``external_ref`` in the ``{cik}_{accession}_{document}`` shape
        produced by :meth:`_search_authority`. Raises
        :class:`~app.providers.tool.base.ToolProviderInvalidRequestError` for
        any ref that doesn't split into exactly three ``_``-delimited parts.
        """
        ref = args.get("external_ref")
        if not isinstance(ref, str) or not ref.strip():
            raise ToolProviderInvalidRequestError(
                "get_authority requires non-empty 'external_ref'", upstream_status=400
            )
        try:
            cik, accession, document = ref.split("_", 2)
        except ValueError as exc:
            raise ToolProviderInvalidRequestError(
                f"get_authority: malformed external_ref {ref!r}", upstream_status=400
            ) from exc
        if not (cik and accession and document):
            raise ToolProviderInvalidRequestError(
                f"get_authority: malformed external_ref {ref!r}", upstream_status=400
            )

        url = f"{_ARCHIVES_BASE}/{cik}/{accession}/{document}"
        resp = await self._request("GET", url)
        text = _TAG_RE.sub(" ", resp.text)
        text = _WHITESPACE_RE.sub(" ", text).strip()

        payload = {
            "external_ref": ref,
            "title": document,
            "url": url,
            "text": text,
            "content_kind": "sec_filing",
        }
        return self._result("get_authority", payload, resp)

    def _result(self, tool: str, payload: Any, resp: httpx.Response) -> ToolResult:
        """Build a ToolResult with byte counts; mark public filing text verbatim."""
        return ToolResult(
            provider=self.name,
            tool=tool,
            payload=payload,
            bytes_out=len(resp.request.content or b""),
            bytes_in=len(resp.content or b""),
            skip_anonymization=True,
        )

    async def health_check(self) -> ProviderHealth:
        try:
            await self._request("GET", _EFTS_SEARCH_URL, params={"q": "a"})
        except ToolProviderError as exc:
            return ProviderHealth(name=self.name, reachable=False, error=str(exc))
        return ProviderHealth(name=self.name, reachable=True, latency_ms=0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
