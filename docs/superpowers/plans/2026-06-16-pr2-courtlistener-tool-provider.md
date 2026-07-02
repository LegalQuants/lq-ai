# PR2 — CourtListener gateway tool-provider (WS3a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add the `courtlistener` gateway tool-provider type — three read tools (`verify_citations`, `search_case_law`, `get_cases`) as SSRF-guarded, audited egress operations on the CourtListener REST API v4. No caching, no `/api/v1/research` route, no chat/autonomous integration (those are PR3 / PR5).

**Architecture:** `CourtListenerToolAdapter(ToolProviderAdapter)` (the PR1 contract) makes outbound calls to `https://www.courtlistener.com/api/rest/v4/` through PR1's `validate_egress_target` SSRF primitive, authenticating with `Authorization: Token <COURTLISTENER_API_TOKEN>`. It's built into `app.state.tool_adapters` by `build_tool_adapter` and invoked via PR1's `Router.route_tool_call` (which adds the tier/rate-limit/audit envelope). The adapter is **stateless egress** — caching (object storage + DB) is PR3, api-side, because `storage.py`/the DB live in `api/`, not the gateway.

**Tech Stack:** Python 3.12, httpx, Pydantic v2, pytest + pytest-asyncio + **respx** (HTTP stubbing — the codebase convention; NOT vcrpy/cassettes, avoiding a new SBOM dep). Gateway mypy `--strict`.

**Branch:** `feat/courtlistener-tool-provider` (off `main`, which has PR1 at `49326fa`). **Security-reviewed** (`gateway/**`) → maintainer reviews + merges; do NOT self-merge.

## ⚠️ Test/lint runner (host venv, NOT docker compose — see PR1)
- Gateway unit tests: `cd ~/Code/lq-ai/gateway && .venv/bin/pytest tests/X.py -v`
- Gateway live test (PR2 Task 7): `cd ~/Code/lq-ai/gateway && COURTLISTENER_API_TOKEN=$(grep '^COURTLISTENER_API_TOKEN=' ~/Code/lq-ai/.env | cut -d= -f2) .venv/bin/pytest -m provider tests/test_courtlistener_live.py -v`
- Lint: `cd ~/Code/lq-ai/gateway && .venv/bin/ruff format <files> && .venv/bin/ruff check <files> && .venv/bin/mypy app` (--strict, must be clean). Run `ruff format --check .` over the whole tree before pushing (CI gate that bit PR1).

## CourtListener REST API v4 reference (verified against wiki.free.law, 2026-06-16)
- **Base:** `https://www.courtlistener.com/api/rest/v4/` · **Allowlist host:** `www.courtlistener.com` · **Auth:** `Authorization: Token <token>`.
- **verify_citations →** `POST /api/rest/v4/citation-lookup/`. Body: `text` (≤64,000 chars) OR structured `volume`/`reporter`/`page`. Limits: ≤250 citations/request, 60 valid citations/min. Response: JSON array; per item: `citation`, `normalized_citations` (array), `start_index`, `end_index`, `status` (200 found / 300 ambiguous / 400 bad reporter / 404 not in DB / 429 limit), `error_message`, `clusters` (array of `{id, case_name, citation…, absolute_url}`).
- **search_case_law →** `GET /api/rest/v4/search/?q=<q>&type=o`. `type=o` = opinion clusters (default). Response root: `count` (total), `next`/`previous` (cursor URLs), `results` (array). Per result: `cluster_id`, `caseName`, `court`, `dateFiled`, `citation`, `absolute_url`, `docketNumber`, `citeCount`, `status`, `snippet`, nested `opinions`. **Cursor pagination** (`next` is a full URL). Server-side cached 10 min; no hard documented rate limit.
- **get_cases →** `GET /api/rest/v4/clusters/{id}/` for cluster metadata + `GET /api/rest/v4/opinions/{id}/` for each opinion. Cluster fields: `id`, `case_name`, `case_name_short`, `date_filed`, `citations`, `court`, `absolute_url`, `sub_opinions` (array of opinion **API URLs**). Opinion text preference order (first non-empty wins): `html_with_citations` → `html_columbia` → `html_lawbox` → `xml_harvard` → `html_anon_2020` → `html` → `plain_text`. (Website opinion URLs carry a `cluster_id`, not opinion id.)

## File structure
**Gateway (new):**
- `gateway/app/providers/tool/courtlistener.py` — `CourtListenerToolAdapter` + the three tool methods + guarded `_request` helper + opinion-text selection.
- `gateway/tests/test_courtlistener_adapter.py` — respx unit tests (list_tools, from_config, error mapping, each tool, route-through-router).
- `gateway/tests/test_courtlistener_live.py` — one `@pytest.mark.provider` live test.

**Gateway (modified):**
- `gateway/app/providers/tool/base.py` — add `ToolProviderInvalidRequestError` (code `invalid_request`) to align with #155's upstream-4xx posture.
- `gateway/app/providers/tool/__init__.py` — re-export the new adapter + error.
- `gateway/app/main.py` — `build_tool_adapter`: add the `courtlistener` branch.
- `gateway.yaml.example` — uncomment-ready courtlistener example already exists (PR1); refine the comment to note it's now shipped.

**Docs / config:**
- `.env.example` — add `COURTLISTENER_API_TOKEN=` (empty, documented).

## Scope — what PR2 does NOT do (honest deferrals)
- **No caching** (object storage + DB metadata + per-turn cache + live-API fallback) — PR3, api-side.
- **No `/api/v1/research` HTTP route, no `find_in_case` / `read_case`** — PR3 (they operate on fetched/cached text).
- **No HTML→plaintext extraction** — `get_cases` returns the raw preferred text field + which field it used; extraction for citation grounding is PR3 (avoids a parser dependency here).
- **No chat tool-loop / ToolIntent** — PR5.
- Outbound anonymization stays deferred (ADR 0014 D5); CourtListener data is public, so results are marked `skip_anonymization=True` on the inbound side, matching the retrieval-context handling.

---

## Task 1: Align error hierarchy with the #155 upstream-4xx posture

Jaime's #155 reclassified upstream provider 4xx as `invalid_request` (not `*_unavailable`). Add the matching tool-provider error so the adapter maps non-auth 4xx correctly.

**Files:** Modify `gateway/app/providers/tool/base.py`, `gateway/app/providers/tool/__init__.py`; Test `gateway/tests/test_tool_provider_base.py` (extend).

- [ ] **Step 1: Add a failing test** to `gateway/tests/test_tool_provider_base.py`:

```python
@pytest.mark.unit
def test_invalid_request_error_code() -> None:
    from app.providers.tool.base import ToolProviderInvalidRequestError

    err = ToolProviderInvalidRequestError("bad reporter", upstream_status=400)
    assert err.code == "invalid_request"
    assert err.to_envelope()["error"]["details"]["upstream_status"] == 400
```

- [ ] **Step 2: Run, confirm ImportError.** `cd ~/Code/lq-ai/gateway && .venv/bin/pytest tests/test_tool_provider_base.py -v`

- [ ] **Step 3: Add the error class** in `base.py` after `ToolProviderHTTPError`:

```python
class ToolProviderInvalidRequestError(ToolProviderError):
    """Upstream rejected the request as malformed (non-auth 4xx).

    Aligns with the inference path's #155 posture: upstream 4xx is the
    caller's problem (bad citation/query), not a provider outage."""

    code = "invalid_request"

    def __init__(
        self, message: str, *, upstream_status: int, details: dict[str, object] | None = None
    ) -> None:
        merged: dict[str, object] = dict(details or {})
        merged["upstream_status"] = upstream_status
        super().__init__(message, details=merged)
        self.upstream_status = upstream_status
```

Add `ToolProviderInvalidRequestError` to `__init__.py`'s imports + `__all__`.

- [ ] **Step 4: Run** the test (passes) + the full base test file.

- [ ] **Step 5: Lint** (`ruff format`, `ruff check`, `mypy app` — clean).

- [ ] **Step 6: Commit:**
```bash
cd ~/Code/lq-ai && git add gateway/app/providers/tool/base.py gateway/app/providers/tool/__init__.py gateway/tests/test_tool_provider_base.py
git commit -s -m "feat(gateway): ToolProviderInvalidRequestError for upstream 4xx (align #155)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `CourtListenerToolAdapter` skeleton — from_config, list_tools, guarded `_request`, health_check, aclose

Build the adapter shell: credential resolution, the 3 tool specs, the SSRF-guarded request helper with error mapping, and lifecycle. `invoke_tool` dispatches to three private methods that Tasks 3–5 fill in (here they raise `NotImplementedError` so this task is independently testable).

**Files:** Create `gateway/app/providers/tool/courtlistener.py`; modify `gateway/app/providers/tool/__init__.py`; Test `gateway/tests/test_courtlistener_adapter.py`.

- [ ] **Step 1: Failing tests** (`gateway/tests/test_courtlistener_adapter.py`):

```python
import httpx
import pytest
import respx

from app.config import ToolProviderConfig
from app.providers.tool.base import (
    ToolProviderAuthError,
    ToolProviderInvalidRequestError,
)
from app.providers.tool.courtlistener import CourtListenerToolAdapter

BASE = "https://www.courtlistener.com/api/rest/v4"


def _cfg(**over) -> ToolProviderConfig:
    base = {
        "name": "courtlistener-prod",
        "type": "courtlistener",
        "base_url": BASE,
        "api_key_env": "COURTLISTENER_API_TOKEN",
        "egress_tier": 4,
        "allowlist": {"hosts": ["www.courtlistener.com"]},
    }
    base.update(over)
    return ToolProviderConfig.model_validate(base)


def _adapter(monkeypatch) -> CourtListenerToolAdapter:
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token-123")
    # DNS stub so validate_base_url passes without real resolution.
    monkeypatch.setattr(
        "app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"]
    )
    return CourtListenerToolAdapter.from_config(_cfg())


@pytest.mark.unit
async def test_lists_three_read_tools(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    try:
        names = {t.name for t in await adapter.list_tools()}
    finally:
        await adapter.aclose()
    assert names == {"verify_citations", "search_case_law", "get_cases"}
    assert all(t.read_only for t in await adapter.list_tools())


@pytest.mark.unit
async def test_request_sends_token_auth_header(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    with respx.mock:
        route = respx.get(f"{BASE}/clusters/1/").mock(
            return_value=httpx.Response(200, json={"id": 1})
        )
        try:
            await adapter._request("GET", "/clusters/1/")
        finally:
            await adapter.aclose()
    assert route.called
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Token test-token-123"


@pytest.mark.unit
async def test_request_maps_401_to_auth_error(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    with respx.mock:
        respx.get(f"{BASE}/clusters/1/").mock(return_value=httpx.Response(401))
        with pytest.raises(ToolProviderAuthError):
            try:
                await adapter._request("GET", "/clusters/1/")
            finally:
                await adapter.aclose()


@pytest.mark.unit
async def test_request_maps_400_to_invalid_request(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    with respx.mock:
        respx.get(f"{BASE}/clusters/1/").mock(return_value=httpx.Response(400))
        with pytest.raises(ToolProviderInvalidRequestError):
            try:
                await adapter._request("GET", "/clusters/1/")
            finally:
                await adapter.aclose()


@pytest.mark.unit
async def test_invoke_unknown_tool_raises(monkeypatch) -> None:
    from app.providers.tool.base import ToolProviderError

    adapter = _adapter(monkeypatch)
    try:
        with pytest.raises(ToolProviderError):
            await adapter.invoke_tool("nope", {}, request_id="r1")
    finally:
        await adapter.aclose()
```

- [ ] **Step 2: Run, confirm ModuleNotFoundError.**

- [ ] **Step 3: Implement `gateway/app/providers/tool/courtlistener.py`:**

```python
"""``courtlistener`` tool provider — case-law research egress (ADR 0014, WS3a).

Three read tools over the CourtListener REST API v4, brokered through the
gateway egress boundary. Stateless: caching/storage is api-side (PR3). Every
outbound call passes ``validate_egress_target`` (SSRF) and carries the
operator's token. CourtListener data is public, so results are marked
``skip_anonymization=True`` for verbatim citation grounding (ADR 0014 D5)."""

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

# Opinion text fields, most-reliable first (per CourtListener v4 docs).
_OPINION_TEXT_FIELDS = (
    "html_with_citations",
    "html_columbia",
    "html_lawbox",
    "xml_harvard",
    "html_anon_2020",
    "html",
    "plain_text",
)


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

    # --- guarded request -------------------------------------------------------

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None,
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
            raise ToolProviderHTTPError(
                "courtlistener rate limit", upstream_status=429
            )
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

    # --- tool surface ----------------------------------------------------------

    async def list_tools(self) -> list[ToolSpec]:
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

    async def invoke_tool(self, tool: str, args: dict[str, Any], *, request_id: str) -> ToolResult:
        if tool == "verify_citations":
            return await self._verify_citations(args)
        if tool == "search_case_law":
            return await self._search_case_law(args)
        if tool == "get_cases":
            return await self._get_cases(args)
        raise ToolProviderError(f"unknown tool {tool!r} for courtlistener provider")

    async def _verify_citations(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError  # Task 3

    async def _search_case_law(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError  # Task 4

    async def _get_cases(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError  # Task 5

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
```

Re-export `CourtListenerToolAdapter` in `__init__.py` (+ `__all__`).

- [ ] **Step 4: Run the 5 tests** (pass). Then **Step 5: lint clean.** **Step 6: commit** (`feat(gateway): CourtListener adapter skeleton + guarded request (WS3a)`, stage `courtlistener.py`, `__init__.py`, `test_courtlistener_adapter.py`).

---

## Task 3: implement `verify_citations`

**Files:** Modify `gateway/app/providers/tool/courtlistener.py`; extend `gateway/tests/test_courtlistener_adapter.py`.

- [ ] **Step 1: Failing test** (append):

```python
@pytest.mark.unit
async def test_verify_citations_shapes_payload(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    api_resp = [
        {
            "citation": "576 U.S. 644",
            "normalized_citations": ["576 U.S. 644"],
            "start_index": 0,
            "end_index": 12,
            "status": 200,
            "error_message": "",
            "clusters": [
                {"id": 2812209, "case_name": "Obergefell v. Hodges",
                 "absolute_url": "/opinion/2812209/obergefell-v-hodges/"}
            ],
        }
    ]
    with respx.mock:
        respx.post(f"{BASE}/citation-lookup/").mock(
            return_value=httpx.Response(200, json=api_resp)
        )
        try:
            result = await adapter.invoke_tool(
                "verify_citations", {"text": "576 U.S. 644"}, request_id="r1"
            )
        finally:
            await adapter.aclose()
    assert result.skip_anonymization is True
    cites = result.payload["citations"]
    assert cites[0]["citation"] == "576 U.S. 644"
    assert cites[0]["status"] == 200
    assert cites[0]["clusters"][0]["id"] == 2812209
    assert cites[0]["clusters"][0]["case_name"] == "Obergefell v. Hodges"
```

- [ ] **Step 2: Run, confirm it fails** (NotImplementedError).

- [ ] **Step 3: Implement `_verify_citations`:**

```python
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
        return self._result(
            "verify_citations", {"citations": citations}, sent=body, received=data
        )
```

- [ ] **Step 4: Run (pass). Step 5: lint. Step 6: commit** (`feat(gateway): CourtListener verify_citations (WS3a)`).

---

## Task 4: implement `search_case_law`

**Files:** Modify `courtlistener.py`; extend the test file.

- [ ] **Step 1: Failing test** (append):

```python
@pytest.mark.unit
async def test_search_case_law_returns_count_and_results(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    api_resp = {
        "count": 2,
        "next": "https://www.courtlistener.com/api/rest/v4/search/?cursor=abc&q=privacy",
        "previous": None,
        "results": [
            {"cluster_id": 111, "caseName": "Roe v. Wade", "court": "Supreme Court",
             "dateFiled": "1973-01-22", "citation": ["410 U.S. 113"],
             "absolute_url": "/opinion/111/roe-v-wade/", "snippet": "...privacy..."}
        ],
    }
    with respx.mock:
        route = respx.get(f"{BASE}/search/").mock(
            return_value=httpx.Response(200, json=api_resp)
        )
        try:
            result = await adapter.invoke_tool(
                "search_case_law", {"q": "privacy"}, request_id="r1"
            )
        finally:
            await adapter.aclose()
    assert route.calls.last.request.url.params["type"] == "o"
    assert route.calls.last.request.url.params["q"] == "privacy"
    assert result.payload["count"] == 2
    assert result.payload["results"][0]["cluster_id"] == 111
    assert result.payload["next_cursor"] == "abc"
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement `_search_case_law`** (and a small cursor helper):

```python
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
```

And module-level helper:

```python
from urllib.parse import parse_qs, urlparse


def _cursor_from(next_url: str | None) -> str | None:
    """Extract the opaque ``cursor`` value from a CourtListener ``next`` URL."""
    if not next_url:
        return None
    cursor = parse_qs(urlparse(next_url).query).get("cursor")
    return cursor[0] if cursor else None
```

- [ ] **Step 4–6: run, lint, commit** (`feat(gateway): CourtListener search_case_law (WS3a)`).

---

## Task 5: implement `get_cases`

Fetch the cluster, then each linked opinion, picking the first non-empty text field by preference. Returns raw preferred field + which field was used (HTML→plaintext is PR3).

**Files:** Modify `courtlistener.py`; extend the test file.

- [ ] **Step 1: Failing test** (append):

```python
@pytest.mark.unit
async def test_get_cases_fetches_cluster_and_opinion_text(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    cluster = {
        "id": 2812209, "case_name": "Obergefell v. Hodges", "case_name_short": "Obergefell",
        "date_filed": "2015-06-26", "citations": [{"volume": 576, "reporter": "U.S.", "page": "644"}],
        "court": "https://www.courtlistener.com/api/rest/v4/courts/scotus/",
        "absolute_url": "/opinion/2812209/obergefell-v-hodges/",
        "sub_opinions": ["https://www.courtlistener.com/api/rest/v4/opinions/3247759/"],
    }
    opinion = {"id": 3247759, "plain_text": "", "html_with_citations": "<p>Held: ...</p>"}
    with respx.mock:
        respx.get(f"{BASE}/clusters/2812209/").mock(return_value=httpx.Response(200, json=cluster))
        respx.get(f"{BASE}/opinions/3247759/").mock(return_value=httpx.Response(200, json=opinion))
        try:
            result = await adapter.invoke_tool(
                "get_cases", {"cluster_id": 2812209}, request_id="r1"
            )
        finally:
            await adapter.aclose()
    assert result.skip_anonymization is True
    assert result.payload["cluster"]["case_name"] == "Obergefell v. Hodges"
    op = result.payload["opinions"][0]
    assert op["id"] == 3247759
    assert op["text_field_used"] == "html_with_citations"
    assert "Held:" in op["text"]
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement `_get_cases` + `_select_opinion_text`:**

```python
    async def _get_cases(self, args: dict[str, Any]) -> ToolResult:
        cluster_id = args.get("cluster_id")
        if not isinstance(cluster_id, int):
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
```

Module-level:

```python
def _select_opinion_text(opinion: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (field_name, text) of the first non-empty opinion text field,
    by CourtListener's documented reliability order."""
    for field in _OPINION_TEXT_FIELDS:
        value = opinion.get(field)
        if isinstance(value, str) and value.strip():
            return field, value
    return None, None
```

- [ ] **Step 4–6: run, lint, commit** (`feat(gateway): CourtListener get_cases (WS3a)`).

---

## Task 6: wire `courtlistener` into the gateway + config/docs + route-through test

**Files:** Modify `gateway/app/main.py` (`build_tool_adapter`), `gateway.yaml.example`, `.env.example`; extend `gateway/tests/test_courtlistener_adapter.py` (route-through-router test) and `gateway/tests/test_tool_adapter_wiring.py`.

- [ ] **Step 1: Failing tests.**

(a) Route-through test in `test_courtlistener_adapter.py` — proves the audit envelope wraps a real (mocked) CourtListener call:

```python
@pytest.mark.unit
async def test_courtlistener_through_router_writes_audit(monkeypatch) -> None:
    from app.config import GatewayConfig
    from app.router import Router
    from app.tool_egress_log import RecordingToolEgressLogWriter

    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token-123")
    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])
    cfg = GatewayConfig.model_validate({"tool_providers": [_cfg().model_dump()]})
    adapter = CourtListenerToolAdapter.from_config(cfg.tool_providers[0])
    writer = RecordingToolEgressLogWriter()
    router = Router(config=cfg, adapters={},
                    tool_adapters={"courtlistener-prod": adapter}, tool_egress_log=writer)
    with respx.mock:
        respx.get(f"{BASE}/search/").mock(
            return_value=httpx.Response(200, json={"count": 0, "next": None, "results": []})
        )
        try:
            res = await router.route_tool_call(
                "courtlistener-prod", "search_case_law", {"q": "x"},
                request_id="r1", max_allowed_tier=4,
            )
        finally:
            await adapter.aclose()
    assert res.payload["count"] == 0
    assert writer.rows[-1].refused is False
    assert writer.rows[-1].bytes_in is not None
```

(b) Wiring test in `test_tool_adapter_wiring.py`:

```python
@pytest.mark.unit
def test_build_tool_adapter_courtlistener(monkeypatch) -> None:
    from app.main import build_tool_adapter
    from app.providers.tool.courtlistener import CourtListenerToolAdapter

    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "test-token-123")
    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])
    cfg = GatewayConfig.model_validate(
        {"tool_providers": [{
            "name": "cl", "type": "courtlistener",
            "base_url": "https://www.courtlistener.com/api/rest/v4",
            "api_key_env": "COURTLISTENER_API_TOKEN", "egress_tier": 4,
            "allowlist": {"hosts": ["www.courtlistener.com"]},
        }]}
    )
    adapter = build_tool_adapter(cfg.tool_providers[0])
    assert isinstance(adapter, CourtListenerToolAdapter)
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Add the `courtlistener` branch** to `build_tool_adapter` in `main.py` (after the `echo` branch), and import `CourtListenerToolAdapter`:

```python
    if provider.type == "courtlistener":
        adapter = CourtListenerToolAdapter.from_config(provider)
        adapter.validate_base_url()
        return adapter
```

- [ ] **Step 4:** Update `gateway.yaml.example` — change the courtlistener example comment from "PR2 (not yet shipped)" to a shipped note (keep it commented, since enabling requires a token). Add `COURTLISTENER_API_TOKEN=` (empty, with a one-line comment) to `.env.example`.

- [ ] **Step 5: Run** the two new tests + the FULL gateway suite (no regression). **Step 6: lint** including `ruff format --check .` over the whole tree. **Step 7: commit** (`feat(gateway): wire courtlistener tool-provider + config docs (WS3a)`, stage `main.py`, `gateway.yaml.example`, `.env.example`, the two test files).

---

## Task 7: live `@pytest.mark.provider` integration test

One real call against CourtListener using the operator token, skipped when the token is unset (mirrors `test_anthropic_provider.py`).

**Files:** Create `gateway/tests/test_courtlistener_live.py`.

- [ ] **Step 1: Write the test:**

```python
import os

import pytest

from app.config import ToolProviderConfig
from app.providers.tool.courtlistener import CourtListenerToolAdapter

BASE = "https://www.courtlistener.com/api/rest/v4"


@pytest.mark.provider
async def test_verify_citations_live() -> None:
    """Live CourtListener call — runs only when COURTLISTENER_API_TOKEN is set."""
    if not os.environ.get("COURTLISTENER_API_TOKEN"):
        pytest.skip("COURTLISTENER_API_TOKEN not set; skipping live test")
    cfg = ToolProviderConfig.model_validate({
        "name": "courtlistener-live", "type": "courtlistener", "base_url": BASE,
        "api_key_env": "COURTLISTENER_API_TOKEN", "egress_tier": 4,
        "allowlist": {"hosts": ["www.courtlistener.com"]},
    })
    adapter = CourtListenerToolAdapter.from_config(cfg)
    try:
        # Brown v. Board of Education, 347 U.S. 483 — a stable, famous citation.
        result = await adapter.invoke_tool(
            "verify_citations", {"text": "347 U.S. 483"}, request_id="live-1"
        )
    finally:
        await adapter.aclose()
    cites = result.payload["citations"]
    assert cites, "expected at least one citation result"
    assert cites[0]["status"] == 200
    assert any("Brown" in (c.get("case_name") or "") for c in cites[0]["clusters"])
```

- [ ] **Step 2: Run it live** (the controller runs this — the token is in `.env`):
```bash
cd ~/Code/lq-ai/gateway && COURTLISTENER_API_TOKEN=$(grep '^COURTLISTENER_API_TOKEN=' ~/Code/lq-ai/.env | cut -d= -f2) .venv/bin/pytest -m provider tests/test_courtlistener_live.py -v
```
Expected: PASS (real Brown v. Board lookup). If CourtListener's data differs (e.g. case_name formatting), adjust the assertion to match reality, not the reverse — and report what the live API actually returned.

- [ ] **Step 3: Confirm it SKIPS** without the token: `cd ~/Code/lq-ai/gateway && .venv/bin/pytest -m provider tests/test_courtlistener_live.py -v` → 1 skipped.

- [ ] **Step 4: lint. Step 5: commit** (`test(gateway): live CourtListener verify_citations (provider-marked)`).

---

## Task 8: final gates, push, PR

- [ ] **Step 1: Full gate sweep** — gateway `ruff format --check .`, `ruff check .`, `mypy app`, `pytest -q -m "not provider and not slow"` (all green); then the live provider test once more with the token.
- [ ] **Step 2: Push both remotes** (`git push origin feat/courtlistener-tool-provider && git push tucuxi feat/courtlistener-tool-provider`).
- [ ] **Step 3: Open the PR** (base `main`), title `WS3a/PR2: CourtListener gateway tool-provider (legal-research milestone)`. Body: link ADR 0014 + the mini-PRD; check the PR2 acceptance criteria; flag honest deferrals (no caching, no /research route, no find_in_case/read_case — PR3); note it's `gateway/**` security-reviewed. Watch CI to green. **Do NOT self-merge** — maintainer reviews + merges.

---

## Self-review (against the spec)
- **CourtListener provider as a gateway tool-provider type** → Tasks 2–6. ✓
- **Three tools** verify_citations / search_case_law / get_cases → Tasks 3/4/5. ✓
- **SSRF-guarded + token auth** → `_request` in Task 2 (validate_egress_target every call + `Authorization: Token`). ✓
- **Audited via tool_egress_log** → Task 6 route-through test (Router.route_tool_call). ✓
- **Live test gated `-m provider`** → Task 7. ✓
- **respx not VCR** (no new dep) → all unit tests. ✓
- **Error alignment with #155** → Task 1 (`ToolProviderInvalidRequestError`) + `_request` mapping. ✓
- **Honest deferrals** (caching, /research, find_in_case/read_case, HTML extraction) → Scope section; `get_cases` returns raw preferred field + `text_field_used`. ✓
- **Type consistency:** `CourtListenerToolAdapter`, `_request(method, path, *, params, json_body)`, `_result(...)`, `_cursor_from`, `_select_opinion_text`, `_OPINION_TEXT_FIELDS`, `ToolProviderInvalidRequestError` defined once, referenced consistently. ✓
- **Known seam:** `_get_cases` derives the opinion path from `sub_opinions` URLs by splitting on `/api/rest/v4`; the live test (Task 7) only exercises verify_citations — if get_cases' URL-splitting needs adjustment against real responses, the implementer should add a second live assertion or note it. (Acceptable: unit test covers the shape; live coverage of get_cases can be a follow-up.)
