"""``eurlex`` tool provider — EU legal document search + retrieval (WS-E PR2b, DE-374).

Auth model mirrors EDGAR: the EU Publications Office's Cellar service has no
API-key scheme, so a descriptive ``User-Agent`` header is the only auth
posture. Every outbound call still passes ``validate_egress_target`` (SSRF)
against the configured host allowlist (``publications.europa.eu``).

Fetching a document is content negotiation against
``/resource/celex/{CELEX}``, which Cellar 303-redirects to a concrete
manifestation URL. That ``Location`` is served as ``http`` even though the
manifestation itself is also reachable over ``https`` — egress policy is
https-only (``validate_egress_target`` rejects non-https targets outright),
so this adapter follows redirects manually (``httpx.AsyncClient`` built with
``follow_redirects=False``), upgrades each hop's scheme to https before
touching it, and re-runs ``validate_egress_target`` on every hop. httpx is
never allowed to auto-follow a redirect: that would fetch an unvalidated (and
initially non-https) URL, bypassing the SSRF/allowlist guard entirely.

EUR-Lex document text is public, so results are marked
``skip_anonymization=True`` for verbatim verifier delivery (ADR 0014 D5),
mirroring the GovInfo/EDGAR adapters.

``search_authority`` (DE-374) queries the Cellar SPARQL endpoint
(``/webapi/rdf/sparql`` on the same host, so the allowlist is unchanged) for
English expression titles containing the keyword string, returning CELEX ids
with title and EUR-Lex page URL but NO document body — same fail-closed
contract as the GovInfo/EDGAR search ops: a search hit is never verified
content until ``get_authority`` fetches it. The user keyword is escaped as a
SPARQL string literal (never interpolated raw) so it cannot break out of the
``FILTER`` clause.

``get_authority`` validates the CELEX id against a full-CELEX shape regex
(``_VALID_CELEX_RE``) before any egress is attempted (DE-375): sector digit +
4-digit year + document-type letters, then either a treaty full-text suffix
(``12016E/TXT``), or a document number with optional consolidation date
(``02016R0679-20160504``) and optional corrigendum suffix (``32016R0679R(01)``).
Anything else — traversal sequences, lowercase, stray specials — is rejected
fail-closed with a 400. The id is URL-quoted (``quote(..., safe="")``) when
building the Cellar path so ``/`` and ``()`` never reach the URL raw; the
user-visible ``external_ref``/page URL keep the raw CELEX form. Search hits
whose CELEX the same regex rejects are dropped rather than surfaced with an
unfetchable ref (mirrors EDGAR's drop invariant)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

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
MAX_REDIRECTS = 5
DEFAULT_SEARCH_PAGE_SIZE = 10

_SPARQL_ACCEPT = "application/sparql-results+json"
# SPARQL string-literal escapes (SPARQL 1.1 grammar ECHAR) — the user keyword
# is only ever embedded through _sparql_string_literal, never raw.
_SPARQL_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "'": "\\'",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}

# Full-CELEX validation (DE-375): sector digit, 4-digit year, 1-2 letter
# document-type descriptor, then EITHER a treaty full-text suffix (/TXT, e.g.
# 12016E/TXT, 12012P/TXT) OR a document number ([0-9A-Z]*, possibly empty for
# bare treaty ids like 12016E) with an optional consolidation-date suffix
# (-YYYYMMDD, e.g. 02016R0679-20160504) and an optional corrigendum suffix
# (R(NN), e.g. 32016R0679R(01)). Anchored and conservative: no lowercase, no
# whitespace, no '..', no path segments beyond the single literal '/TXT'.
_VALID_CELEX_RE = re.compile(r"^\d\d{4}[A-Z]{1,2}(?:/TXT|[0-9A-Z]*(?:-\d{8})?(?:R\(\d{2}\))?)$")
_CELEX_RE = re.compile(r"^(?P<sector>\d)(?P<year>\d{4})(?P<type>[A-Z]{1,2})")
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _content_kind_from_celex(celex: str) -> str:
    """Classify a CELEX id's content kind from its sector/document-type digits.

    Sector 3 (secondary legislation) splits into regulation/directive/decision
    by document-type letter; sector 6 is CJEU case law. Anything else
    (treaties, unparseable ids) falls back to the generic ``eu_legislation``
    kind rather than guessing."""
    match = _CELEX_RE.match(celex)
    if not match:
        return "eu_legislation"
    sector, doc_type = match.group("sector"), match.group("type")
    if sector == "6":
        return "eu_caselaw"
    if sector == "3":
        if doc_type.startswith("R"):
            return "eu_regulation"
        if doc_type.startswith("L"):
            return "eu_directive"
        if doc_type.startswith("D"):
            return "eu_decision"
    return "eu_legislation"


def _sparql_string_literal(value: str) -> str:
    """Render ``value`` as a double-quoted SPARQL string literal.

    Escapes every SPARQL ECHAR (backslash, both quote kinds, control
    characters) so a user keyword can never terminate the literal and inject
    SPARQL syntax into the query."""
    return '"' + "".join(_SPARQL_ESCAPES.get(ch, ch) for ch in value) + '"'


def _eurlex_page_url(celex: str) -> str:
    """Canonical EUR-Lex page URL for a CELEX id (same form get_authority emits)."""
    return f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"


def _force_https(url: str) -> str:
    """Upgrade an ``http`` URL to ``https``; leave other schemes untouched.

    Cellar's 303 ``Location`` for a manifestation is served as plain
    ``http`` even though the same resource is also reachable over
    ``https`` — egress policy is https-only, so every redirect hop is
    upgraded before it is validated or fetched."""
    parsed = httpx.URL(url)
    if parsed.scheme == "http":
        return str(parsed.copy_with(scheme="https"))
    return url


class EurLexToolAdapter(ToolProviderAdapter):
    """Tool adapter for the EU Publications Office Cellar service.

    Auth: a descriptive ``User-Agent`` header (no API key). Supports two
    read-only operations: ``search_authority`` for keyword search of EU
    legal document titles via the Cellar SPARQL endpoint (DE-374), and
    ``get_authority`` for fetching an EU legal document's plaintext by
    CELEX id.
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
        # follow_redirects=False: we follow manually so every hop is
        # https-upgraded and re-validated against the allowlist.
        self._client = client or httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT_SECONDS, follow_redirects=False
        )

    @classmethod
    def from_config(
        cls,
        provider: ToolProviderConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> EurLexToolAdapter:
        if provider.type != "eurlex":
            raise ValueError(f"EurLexToolAdapter from non-eurlex provider {provider.type!r}")
        if not provider.user_agent:
            raise ValueError(
                f"Tool provider {provider.name!r}: type 'eurlex' requires a descriptive "
                f"user_agent (the EU Publications Office Cellar service has no API-key scheme)."
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

    async def list_tools(self, *, user_token: str | None = None) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="search_authority",
                description=(
                    "Keyword search of EU legal documents (regulations, "
                    "directives, decisions, CJEU judgments) by title via the "
                    "EUR-Lex/Cellar SPARQL endpoint. Returns matching CELEX "
                    "ids usable by get_authority; results carry no document "
                    "body."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Keyword(s) to match against document titles.",
                        },
                        "page_size": {
                            "type": "integer",
                            "description": "Maximum results to return (default 10).",
                        },
                    },
                    "required": ["query"],
                },
                read_only=True,
            ),
            ToolSpec(
                name="get_authority",
                description=(
                    "Retrieve the full text of an EU legal document (regulation, "
                    "directive, decision, or CJEU judgment) from EUR-Lex by its "
                    "CELEX id (e.g. 32016R0679 = GDPR)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "external_ref": {
                            "type": "string",
                            "description": "CELEX id, e.g. 32016R0679",
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
        raise ToolProviderError(f"unknown tool {tool!r} for eurlex provider")

    async def _search_authority(self, args: dict[str, Any]) -> ToolResult:
        """GET the Cellar SPARQL endpoint for title/keyword matches (DE-374).

        Selects distinct CELEX id + English expression title for works whose
        title contains the keyword string (case-insensitive). The keyword is
        embedded only as an escaped SPARQL string literal — no injection path
        out of the ``FILTER`` clause. Hits whose CELEX id would be rejected by
        ``get_authority``'s full-CELEX validation (``_VALID_CELEX_RE``,
        DE-375) are dropped rather than surfaced with an unfetchable ref;
        treaty (``12016E/TXT``) and corrigendum (``32016R0679R(01)``) shapes
        are valid and survive. Results carry NO body — same fail-closed
        contract as the GovInfo/EDGAR search ops."""
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolProviderInvalidRequestError(
                "search_authority requires non-empty 'query'", upstream_status=400
            )
        raw_page_size = args.get("page_size", DEFAULT_SEARCH_PAGE_SIZE)
        page_size: int = (
            raw_page_size
            if isinstance(raw_page_size, int)
            and not isinstance(raw_page_size, bool)
            and raw_page_size >= 1
            else DEFAULT_SEARCH_PAGE_SIZE
        )

        literal = _sparql_string_literal(query.strip())
        sparql = (
            "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n"
            "SELECT DISTINCT ?celex ?title\n"
            "WHERE {\n"
            "  ?work cdm:resource_legal_id_celex ?celex .\n"
            "  ?expression cdm:expression_belongs_to_work ?work .\n"
            "  ?expression cdm:expression_uses_language "
            "<http://publications.europa.eu/resource/authority/language/ENG> .\n"
            "  ?expression cdm:expression_title ?title .\n"
            f"  FILTER(CONTAINS(LCASE(STR(?title)), LCASE({literal})))\n"
            "}\n"
            f"LIMIT {page_size}"
        )
        url = str(httpx.URL(f"{self._base_url}/webapi/rdf/sparql", params={"query": sparql}))
        resp = await self._fetch_following_redirects(url, accept=_SPARQL_ACCEPT)

        data: dict[str, Any] = resp.json()
        bindings: list[dict[str, Any]] = data.get("results", {}).get("bindings", [])
        results: list[dict[str, Any]] = []
        for binding in bindings:
            celex = str((binding.get("celex") or {}).get("value") or "").strip()
            title = str((binding.get("title") or {}).get("value") or "").strip()
            if not celex or not _VALID_CELEX_RE.fullmatch(celex):
                # get_authority would refuse this ref (DE-375) — drop the hit
                # rather than hand back an unfetchable external_ref.
                continue
            results.append(
                {
                    "external_ref": celex,
                    "title": title or celex,
                    "url": _eurlex_page_url(celex),
                }
            )

        payload = {"results": results, "count": len(results)}
        return self._result("search_authority", payload, resp)

    async def _get_authority(self, args: dict[str, Any]) -> ToolResult:
        """GET the Cellar manifestation for a CELEX id; strip HTML to plaintext.

        Validates the id against the full-CELEX shape (``_VALID_CELEX_RE`` —
        including treaty ``12016E/TXT`` and corrigendum ``32016R0679R(01)``
        forms, DE-375) before any egress is attempted; an id that fails is
        rejected with a 400, never mangled. The validated id is URL-quoted
        into the Cellar path (``/`` and ``()`` never reach the URL raw);
        the payload's ``external_ref``/``url`` keep the raw CELEX form."""
        celex = args.get("external_ref")
        if not isinstance(celex, str) or not celex.strip():
            raise ToolProviderInvalidRequestError(
                "get_authority requires non-empty 'external_ref' (a CELEX id)",
                upstream_status=400,
            )
        if not _VALID_CELEX_RE.fullmatch(celex):
            raise ToolProviderInvalidRequestError(
                f"invalid CELEX {celex!r}: expected sector+year+type(+number) with "
                "optional /TXT (treaty) or R(NN) (corrigendum) suffix (DE-375)",
                upstream_status=400,
            )

        start_url = f"{self._base_url}/resource/celex/{quote(celex, safe='')}"
        resp = await self._fetch_following_redirects(start_url)
        text = _TAG_RE.sub(" ", resp.text)
        text = _WHITESPACE_RE.sub(" ", text).strip()

        payload = {
            "external_ref": celex,
            "title": celex,
            "url": _eurlex_page_url(celex),
            "text": text,
            "content_kind": _content_kind_from_celex(celex),
        }
        return self._result("get_authority", payload, resp)

    async def _fetch_following_redirects(
        self, url: str, *, accept: str = "application/xhtml+xml"
    ) -> httpx.Response:
        """Fetch ``url``, following redirects manually.

        Each hop is https-upgraded (Cellar's 303 ``Location`` is plain http)
        and re-validated against the egress allowlist before it is fetched —
        httpx's own redirect-following is disabled on the client so an
        unvalidated hop can never be dispatched."""
        headers = {
            "User-Agent": self._user_agent,
            "Accept": accept,
            "Accept-Language": "eng",
        }
        current = url
        for _ in range(MAX_REDIRECTS):
            current = _force_https(current)
            validate_egress_target(current, allowlist=self._allowlist)
            try:
                resp = await self._client.get(current, headers=headers)
            except EgressRefused:
                raise
            except httpx.HTTPError as exc:
                raise ToolProviderNetworkError(f"eurlex network error: {exc}") from exc
            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    break
                current = str(resp.url.join(location))
                continue
            if resp.status_code in (401, 403):
                raise ToolProviderAuthError("eurlex rejected the request (missing/bad User-Agent)")
            if resp.status_code == 429:
                raise ToolProviderHTTPError("eurlex rate limit", upstream_status=429)
            if 400 <= resp.status_code < 500:
                raise ToolProviderInvalidRequestError(
                    f"eurlex rejected the request ({resp.status_code})",
                    upstream_status=resp.status_code,
                )
            if resp.status_code >= 500:
                raise ToolProviderHTTPError(
                    "eurlex upstream error", upstream_status=resp.status_code
                )
            return resp
        raise ToolProviderHTTPError("eurlex: too many redirects", upstream_status=310)

    def _result(self, tool: str, payload: Any, resp: httpx.Response) -> ToolResult:
        """Build a ToolResult with byte counts; mark public document text verbatim."""
        return ToolResult(
            provider=self.name,
            tool=tool,
            payload=payload,
            bytes_out=len(resp.request.content or b""),
            bytes_in=len(resp.content or b""),
            skip_anonymization=True,
        )

    async def health_check(self) -> ProviderHealth:
        """Cheap reachability probe: re-run the SSRF/allowlist check.

        EUR-Lex has no unauthenticated ping endpoint worth spending a real
        request on, so — unlike EDGAR/GovInfo, which probe a live search
        endpoint — this only confirms the configured base url still clears
        egress policy."""
        try:
            self.validate_base_url()
        except (EgressRefused, ToolProviderError) as exc:
            return ProviderHealth(name=self.name, reachable=False, error=str(exc))
        return ProviderHealth(name=self.name, reachable=True, latency_ms=0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
