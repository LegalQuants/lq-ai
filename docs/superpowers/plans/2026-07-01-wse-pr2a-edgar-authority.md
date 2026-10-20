# WS-E PR2a — SEC EDGAR authority source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add SEC EDGAR as the second free authoritative research source (quote-verifiable in autonomous sessions and chat) on the existing ADR-0021 registry + `retrieve_authority` + verify path.

**Architecture:** A new gateway `EdgarToolAdapter` (User-Agent auth, no key; SSRF-guarded egress to `efts.sec.gov` + `www.sec.gov`) exposes `search_authority`/`get_authority`. A backend `EdgarAdapter` + `SOURCE_REGISTRY["edgar"]` entry normalize responses into the existing `FetchedAuthority`/verify pipeline. The chat authority tools are generalized from GovInfo-hardcoded to registry-driven (a `source` argument). The verify content-kind set gains `sec_filing`. No new migration, route, ADR, or brake.

**Tech Stack:** Python 3.12, FastAPI, httpx (async), SQLAlchemy, pytest. Gateway service (`gateway/`) + api backend (`api/`).

## Global Constraints

Copied verbatim from the spec — every task implicitly includes these:

- **No new ADR** (ADR 0021 D6 already scopes EDGAR). **No new migration** — reuses `message_authority_citations` + `authority_text_cache` (mig 0064); `content_kind` is free Text (no DB CHECK).
- **`gate.py`, `ledger.py`, and `alembic/` remain untouched** — provable via `git diff --name-only main..HEAD`.
- **Reuse / never bypass:** every EDGAR call goes through `guarded_tool_call` → R5/R6/R4 → `governed_tool_invocation` → gateway. No new egress path or verifier.
- **Chat generalization is behavior-preserving for GovInfo** — GovInfo becomes `source:"govinfo"`; existing GovInfo chat tests stay green.
- **Conservative posture:** honest `coverage` string (no overclaiming); unmatched quotes dropped never asserted; a content kind outside `_VERIFIABLE_CONTENT_KINDS` is silently not verified (hence we add `sec_filing`).
- **EDGAR is free:** no `cost_per_call` → `estimate_tool_cost` returns `Decimal("0")` → R4 stays a no-op (DE-344 unchanged).
- **EDGAR auth = descriptive `User-Agent`, NO API key** (SEC fair-access policy). Hosts allowlist `[efts.sec.gov, www.sec.gov]`. `skip_anonymization=True` on results (public filing text must reach the verifier verbatim). `read_only=True`.
- **`external_ref` charset:** the `authority_text_cache` key guard only permits `[A-Za-z0-9._-]`. EDGAR `external_ref` is encoded `{cik}_{accession_no_dashes}_{document}` (all chars in-set; parseable via `split("_", 2)`).
- **Security-gated** (citation surface + governed egress + touches shipped chat code) → Kevin/security merges, NO self-merge; mirror `origin`→`tucuxi` after.
- **Gates (from repo ROOT, CI scope):** full DB-backed SOLO api suite with `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test` set (the REAL gate — an unset DATABASE_URL is a hollow skip-green); `ruff check` + `ruff format --check api scripts`; `mypy app`; gateway suite + `mypy --strict` + `ruff format --check gateway`. Never run concurrent pytest against the shared test DB (DE-368).

### Verified live EDGAR shapes (captured 2026-07-01, use in adapter + test fixtures)

**Search** `GET https://efts.sec.gov/LATEST/search-index?q="revenue recognition"&forms=10-K` (header `User-Agent: <descriptive>`):
```json
{"hits":{"total":{"value":10000,"relation":"gte"},
  "hits":[{"_id":"0001193125-09-237465:dex992.htm",
    "_source":{"ciks":["0001005010"],"display_names":["ARTHROCARE CORP  (CIK 0001005010)"],
      "form":"10-K","adsh":"0001193125-09-237465","file_date":"2009-11-18",
      "file_type":"EX-99.2","file_description":"MANAGEMENT'S DISCUSSION AND ANALYSIS ..."}}]}}
```
**Retrieve** `GET https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh.replace("-","")}/{doc}` → `200 text/html` (the filing document; strip to plaintext for offset matching). `doc` = the part of `_id` after `:`; `cik` = `_source.ciks[0]`.

---

## Task 1: Gateway EDGAR adapter

**Files:**
- Modify: `gateway/app/config.py` (add `"edgar"` to `ToolProviderType` ~line 150; add optional `user_agent` field to `ToolProviderConfig` ~lines 178-210)
- Create: `gateway/app/providers/tool/edgar.py`
- Modify: `gateway/app/providers/tool/__init__.py` (export `EdgarToolAdapter`)
- Modify: `gateway/app/main.py` (import + dispatch branch in `build_tool_adapter` ~lines 181-205)
- Test: `gateway/tests/providers/tool/test_edgar.py` (create)

**Interfaces:**
- Consumes: `ToolProviderAdapter` base (`gateway/app/providers/tool/base.py`), `ToolSpec`, `ToolResult`, `validate_egress_target`, the gateway error types (`ToolProviderAuthError`, rate-limit, `InvalidRequest`, `HTTPError`) — mirror `gateway/app/providers/tool/govinfo.py`.
- Produces: `EdgarToolAdapter.from_config(provider) -> EdgarToolAdapter`, `.list_tools() -> list[ToolSpec]` declaring `search_authority`/`get_authority`, `.invoke_tool(tool, args) -> ToolResult` whose `.payload` is:
  - `search_authority` → `{"results": [{"external_ref": str, "form_type": str, "company": str, "filed_date": str, "title": str}], "count": int}`
  - `get_authority` → `{"external_ref": str, "title": str, "url": str, "text": str, "content_kind": "sec_filing"}`

- [ ] **Step 1: Write the failing test for `from_config` (no key, User-Agent required)**

Create `gateway/tests/providers/tool/test_edgar.py`:
```python
import pytest
from gateway.app.config import ToolProviderConfig
from gateway.app.providers.tool.edgar import EdgarToolAdapter


def _cfg(**over):
    base = dict(
        name="edgar-prod", type="edgar", base_url="https://efts.sec.gov",
        egress_tier=4, allowlist={"hosts": ["efts.sec.gov", "www.sec.gov"]},
        user_agent="LQ.AI test ops@lq.ai",
    )
    base.update(over)
    return ToolProviderConfig(**base)


def test_from_config_requires_no_api_key_and_sets_user_agent():
    adapter = EdgarToolAdapter.from_config(_cfg())
    assert adapter._user_agent == "LQ.AI test ops@lq.ai"


def test_from_config_rejects_missing_user_agent():
    with pytest.raises(ValueError, match="user_agent"):
        EdgarToolAdapter.from_config(_cfg(user_agent=None))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd gateway && python -m pytest tests/providers/tool/test_edgar.py -v`
Expected: FAIL — `ModuleNotFoundError: gateway.app.providers.tool.edgar` (and `ToolProviderConfig` has no `user_agent`).

- [ ] **Step 3: Add `"edgar"` type + `user_agent` field in `gateway/app/config.py`**

In `ToolProviderType` (~line 150) add `"edgar"`:
```python
ToolProviderType = Literal["echo", "courtlistener", "mcp", "govinfo", "edgar"]
```
In `ToolProviderConfig` (~lines 178-210) add an optional field (keep the existing "exactly one of api_key_env/api_key_encrypted, or neither" validator — EDGAR uses neither):
```python
    user_agent: str | None = None  # required for type=edgar (SEC fair-access); unused by others
```

- [ ] **Step 4: Implement `EdgarToolAdapter` in `gateway/app/providers/tool/edgar.py`**

Mirror `govinfo.py`. Real, complete implementation:
```python
"""SEC EDGAR tool adapter — full-text search + filing retrieval.

Auth model differs from GovInfo: SEC requires a descriptive User-Agent header
and no API key (fair-access policy). Public filing text; skip_anonymization=True.
"""
from __future__ import annotations

import re

import httpx

from gateway.app.config import ToolProviderConfig
from gateway.app.egress import validate_egress_target
from gateway.app.providers.tool.base import (
    ToolProviderAdapter,
    ToolResult,
    ToolSpec,
)
from gateway.app.providers.tool.errors import (  # match govinfo's imports
    ToolProviderAuthError,
    ToolProviderHTTPError,
    ToolProviderInvalidRequest,
    ToolProviderRateLimited,
)

_EFTS_SEARCH = "https://efts.sec.gov/LATEST/search-index"
_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
_TAG_RE = re.compile(r"<[^>]+>")


class EdgarToolAdapter(ToolProviderAdapter):
    def __init__(self, name, base_url, user_agent, allowlist, client=None):
        self._name = name
        self._base_url = base_url
        self._user_agent = user_agent
        self._allowlist = allowlist
        self._client = client or httpx.AsyncClient(timeout=30.0)

    @classmethod
    def from_config(cls, provider: ToolProviderConfig) -> "EdgarToolAdapter":
        assert provider.type == "edgar"
        if not provider.user_agent:
            raise ValueError("edgar provider requires a descriptive user_agent")
        return cls(
            name=provider.name,
            base_url=provider.base_url,
            user_agent=provider.user_agent,
            allowlist=list((provider.allowlist or {}).get("hosts", [])),
        )

    def validate_base_url(self) -> None:
        validate_egress_target(self._base_url, allowlist=self._allowlist)

    async def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        validate_egress_target(url, allowlist=self._allowlist)
        resp = await self._client.get(
            url, params=params, headers={"User-Agent": self._user_agent}
        )
        if resp.status_code in (401, 403):
            raise ToolProviderAuthError(f"edgar auth failed: {resp.status_code}")
        if resp.status_code == 429:
            raise ToolProviderRateLimited("edgar rate limited")
        if 400 <= resp.status_code < 500:
            raise ToolProviderInvalidRequest(f"edgar 4xx: {resp.status_code}")
        if resp.status_code >= 500:
            raise ToolProviderHTTPError(f"edgar 5xx: {resp.status_code}")
        return resp

    def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="search_authority",
                description=(
                    "Full-text search SEC EDGAR company filings (10-K, 8-K, S-1, "
                    "etc.). Returns filings with an external_ref usable by get_authority."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "forms": {"type": "string", "description": "optional comma-separated form types, e.g. '10-K,8-K'"},
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
                    "properties": {"external_ref": {"type": "string"}},
                    "required": ["external_ref"],
                },
                read_only=True,
            ),
        ]

    async def invoke_tool(self, tool: str, args: dict) -> ToolResult:
        if tool == "search_authority":
            return await self._search_authority(args)
        if tool == "get_authority":
            return await self._get_authority(args)
        raise ToolProviderInvalidRequest(f"unknown edgar tool: {tool}")

    async def _search_authority(self, args: dict) -> ToolResult:
        params = {"q": args["query"]}
        if args.get("forms"):
            params["forms"] = args["forms"]
        resp = await self._get(_EFTS_SEARCH, params=params)
        body = resp.json()
        hits = body.get("hits", {})
        results = []
        for h in hits.get("hits", []):
            src = h.get("_source", {})
            _id = h.get("_id", "")
            adsh = src.get("adsh", "")
            doc = _id.split(":", 1)[1] if ":" in _id else ""
            cik = (src.get("ciks") or [""])[0]
            external_ref = f"{int(cik)}_{adsh.replace('-', '')}_{doc}" if cik and adsh and doc else ""
            company = (src.get("display_names") or [""])[0].strip()
            results.append({
                "external_ref": external_ref,
                "form_type": src.get("form", ""),
                "company": company,
                "filed_date": src.get("file_date", ""),
                "title": f"{company} — {src.get('form', '')} ({src.get('file_date', '')})".strip(" —"),
            })
        payload = {"results": [r for r in results if r["external_ref"]],
                   "count": hits.get("total", {}).get("value", 0)}
        return self._result("search_authority", payload, resp)

    async def _get_authority(self, args: dict) -> ToolResult:
        ref = args["external_ref"]
        try:
            cik, adsh, doc = ref.split("_", 2)
        except ValueError as exc:
            raise ToolProviderInvalidRequest(f"bad edgar external_ref: {ref!r}") from exc
        url = f"{_ARCHIVES}/{cik}/{adsh}/{doc}"
        resp = await self._get(url)
        text = _TAG_RE.sub(" ", resp.text)  # strip HTML tags → plaintext for offset matching
        text = re.sub(r"\s+", " ", text).strip()
        payload = {
            "external_ref": ref,
            "title": doc,
            "url": url,
            "text": text,
            "content_kind": "sec_filing",
        }
        return self._result("get_authority", payload, resp)

    def _result(self, tool: str, payload: dict, resp: httpx.Response) -> ToolResult:
        return ToolResult(
            provider=self._name,
            tool=tool,
            payload=payload,
            bytes_out=len(resp.request.content or b""),
            bytes_in=len(resp.content or b""),
            skip_anonymization=True,
        )

    async def health_check(self) -> bool:
        return True

    async def aclose(self) -> None:
        await self._client.aclose()
```
> NOTE: match the exact import paths/constructor signatures to `govinfo.py` in this repo (error class names, `ToolResult`/`ToolSpec` fields, base method names). Adjust the imports above if `govinfo.py` differs — the logic is what matters.

- [ ] **Step 5: Register the adapter**

`gateway/app/providers/tool/__init__.py` — add import + `__all__` entry (mirror the govinfo line ~20/25):
```python
from gateway.app.providers.tool.edgar import EdgarToolAdapter
# ... add "EdgarToolAdapter" to __all__
```
`gateway/app/main.py` — import (near line 78-80) and add a dispatch branch in `build_tool_adapter` (near the govinfo branch ~201-204):
```python
    if provider.type == "edgar":
        adapter = EdgarToolAdapter.from_config(provider)
        adapter.validate_base_url()
        return adapter
```

- [ ] **Step 6: Add adapter behavior tests (mock httpx with the verified shapes)**

Append to `gateway/tests/providers/tool/test_edgar.py`:
```python
import httpx


class _MockClient:
    def __init__(self, response):
        self._response = response
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        return self._response


def _resp(json_body=None, text=None, status=200):
    request = httpx.Request("GET", "https://efts.sec.gov/LATEST/search-index")
    return httpx.Response(status, json=json_body, text=text, request=request)


_SEARCH_BODY = {"hits": {"total": {"value": 42, "relation": "eq"}, "hits": [
    {"_id": "0001193125-09-237465:dex992.htm", "_source": {
        "ciks": ["0001005010"], "display_names": ["ARTHROCARE CORP  (CIK 0001005010)"],
        "form": "10-K", "adsh": "0001193125-09-237465", "file_date": "2009-11-18"}}]}}


@pytest.mark.asyncio
async def test_search_normalizes_hits_and_builds_external_ref():
    adapter = EdgarToolAdapter("edgar", "https://efts.sec.gov",
                               "LQ.AI test ops@lq.ai",
                               ["efts.sec.gov", "www.sec.gov"],
                               client=_MockClient(_resp(json_body=_SEARCH_BODY)))
    result = await adapter.invoke_tool("search_authority", {"query": "revenue"})
    assert result.payload["count"] == 42
    r0 = result.payload["results"][0]
    assert r0["external_ref"] == "1005010_000119312509237465_dex992.htm"
    assert r0["form_type"] == "10-K"


@pytest.mark.asyncio
async def test_get_authority_builds_archives_url_and_strips_html():
    client = _MockClient(_resp(text="<html><body>Hello  world</body></html>"))
    adapter = EdgarToolAdapter("edgar", "https://efts.sec.gov",
                               "LQ.AI test ops@lq.ai",
                               ["efts.sec.gov", "www.sec.gov"], client=client)
    result = await adapter.invoke_tool(
        "get_authority", {"external_ref": "1005010_000119312509237465_dex992.htm"})
    assert result.payload["url"] == (
        "https://www.sec.gov/Archives/edgar/data/1005010/000119312509237465/dex992.htm")
    assert result.payload["text"] == "Hello world"
    assert result.payload["content_kind"] == "sec_filing"
    assert result.skip_anonymization is True
    # User-Agent sent on the request
    assert client.calls[-1][2]["User-Agent"] == "LQ.AI test ops@lq.ai"


@pytest.mark.asyncio
async def test_get_authority_rejects_malformed_ref():
    adapter = EdgarToolAdapter("edgar", "https://efts.sec.gov",
                               "LQ.AI test ops@lq.ai",
                               ["efts.sec.gov", "www.sec.gov"],
                               client=_MockClient(_resp(text="x")))
    with pytest.raises(Exception):
        await adapter.invoke_tool("get_authority", {"external_ref": "nodelimiters"})
```

- [ ] **Step 7: Run the gateway tests**

Run: `cd gateway && python -m pytest tests/providers/tool/test_edgar.py -v`
Expected: PASS (all cases). Fix import mismatches against the real `govinfo.py`/`base.py` if any surface.

- [ ] **Step 8: Gateway gates**

Run: `cd gateway && ruff format --check . && ruff check . && python -m mypy --strict app && python -m pytest -q`
Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add gateway/app/config.py gateway/app/providers/tool/edgar.py \
        gateway/app/providers/tool/__init__.py gateway/app/main.py \
        gateway/tests/providers/tool/test_edgar.py
git commit -s -m "feat(gateway): SEC EDGAR tool adapter (search_authority + get_authority)

User-Agent auth (no key), SSRF-guarded egress to efts.sec.gov + www.sec.gov,
skip_anonymization on public filing text. Refs DE-371"
```

---

## Task 2: Backend EdgarAdapter + registry entry

**Files:**
- Modify: `api/app/research/adapters.py` (add `EdgarAdapter`)
- Modify: `api/app/research/registry.py` (add `SOURCE_REGISTRY["edgar"]` ~lines 54-73)
- Test: `api/tests/research/test_adapters.py` (append) and `api/tests/research/test_registry.py` (append) — create files if absent.

**Interfaces:**
- Consumes: `FetchedAuthority` dataclass and the `SourceAdapter` protocol (`api/app/research/adapters.py:18-48`), `SourceSpec` (`api/app/research/registry.py:30-47`).
- Produces: `EdgarAdapter().from_response(op: str, payload: dict) -> FetchedAuthority`; `SOURCE_REGISTRY["edgar"]` with `content_kinds=("sec_filing",)`, `ops=("search_authority","get_authority")`.

- [ ] **Step 1: Write the failing test for `EdgarAdapter.from_response`**

Append to `api/tests/research/test_adapters.py`:
```python
from app.research.adapters import EdgarAdapter


def test_edgar_get_authority_maps_to_fetched_authority():
    payload = {"external_ref": "1005010_000119312509237465_dex992.htm",
               "title": "dex992.htm", "url": "https://www.sec.gov/Archives/edgar/data/1005010/000119312509237465/dex992.htm",
               "text": "Revenue recognition policy ...", "content_kind": "sec_filing"}
    fa = EdgarAdapter().from_response("get_authority", payload)
    assert fa.content_kind == "sec_filing"
    assert fa.external_ref == "1005010_000119312509237465_dex992.htm"
    assert fa.citable_text == "Revenue recognition policy ..."
    assert fa.url.endswith("dex992.htm")


def test_edgar_search_authority_is_title_only_body():
    payload = {"results": [{"external_ref": "1005010_000119312509237465_dex992.htm",
               "form_type": "10-K", "company": "ARTHROCARE CORP", "filed_date": "2009-11-18",
               "title": "ARTHROCARE CORP — 10-K (2009-11-18)"}], "count": 1}
    fa = EdgarAdapter().from_response("search_authority", payload)
    assert fa.content_kind == "sec_filing"
    # search bodies are NOT quotable full text — citable_text is the title/label only
    assert "ARTHROCARE" in fa.citable_text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/research/test_adapters.py -v -k edgar`
Expected: FAIL — `ImportError: cannot import name 'EdgarAdapter'`.

- [ ] **Step 3: Implement `EdgarAdapter` in `api/app/research/adapters.py`**

Follow the `GovInfoAdapter` pattern (dispatch on op):
```python
class EdgarAdapter:
    """Normalizes gateway EDGAR payloads into FetchedAuthority. content_kind is
    always 'sec_filing' (form type is carried in label/subtitle)."""

    def from_response(self, op: str, payload: dict) -> FetchedAuthority:
        if op == "get_authority":
            return self._from_get(payload)
        if op == "search_authority":
            return self._from_search(payload)
        raise ValueError(f"unsupported edgar op: {op}")

    def _from_get(self, payload: dict) -> FetchedAuthority:
        return FetchedAuthority(
            citable_text=payload.get("text", ""),
            label=payload.get("title", ""),
            subtitle=None,
            url=payload.get("url"),
            external_ref=payload.get("external_ref", ""),
            content_kind=payload.get("content_kind", "sec_filing"),
        )

    def _from_search(self, payload: dict) -> FetchedAuthority:
        results = payload.get("results", [])
        first = results[0] if results else {}
        title = first.get("title", "")
        return FetchedAuthority(
            citable_text=title,      # search has no quotable body; only get_authority does
            label=title,
            subtitle=f"{first.get('form_type', '')} · {first.get('filed_date', '')}".strip(" ·") or None,
            url=None,
            external_ref=first.get("external_ref", ""),
            content_kind="sec_filing",
        )
```
> Match `FetchedAuthority`'s exact field names/order to `adapters.py:18-35` (the recon confirms: `citable_text, label, subtitle, url, external_ref, content_kind`). Adjust if the real dataclass differs.

- [ ] **Step 4: Run the adapter test**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/research/test_adapters.py -v -k edgar`
Expected: PASS.

- [ ] **Step 5: Add the registry entry + test**

In `api/app/research/registry.py`, import `EdgarAdapter` and add to `SOURCE_REGISTRY` (after the `"govinfo"` entry):
```python
    "edgar": SourceSpec(
        type="edgar",
        jurisdiction="us-federal",
        coverage="U.S. SEC EDGAR company filings (10-K, 8-K, S-1, etc.) — full-text search + retrieval",
        content_kinds=("sec_filing",),
        ops=("search_authority", "get_authority"),
        adapter=EdgarAdapter(),
    ),
```
Append to `api/tests/research/test_registry.py`:
```python
from app.research.registry import SOURCE_REGISTRY


def test_edgar_registered_with_sec_filing_kind():
    spec = SOURCE_REGISTRY["edgar"]
    assert spec.type == "edgar"
    assert spec.content_kinds == ("sec_filing",)
    assert spec.ops == ("search_authority", "get_authority")
    assert spec.adapter is not None
```

- [ ] **Step 6: Run registry test**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/research/test_registry.py -v -k edgar`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add api/app/research/adapters.py api/app/research/registry.py \
        api/tests/research/test_adapters.py api/tests/research/test_registry.py
git commit -s -m "feat(research): EdgarAdapter + SOURCE_REGISTRY edgar entry (sec_filing)

Refs DE-371"
```

---

## Task 3: Generalize chat authority wiring (registry-driven, source arg)

**Files:**
- Modify: `api/app/chat/tool_schemas.py` (`AUTHORITY_TOOL_SCHEMAS`/`AUTHORITY_OPS` ~86-126; `assemble_allowlist` govinfo hardcode ~201-226)
- Modify: `api/app/chat/tool_loop.py` (`_dispatch_authority` `GovInfoAdapter()` hardcode ~line 393)
- Test: `api/tests/chat/test_tool_schemas.py` (append), `api/tests/chat/test_tool_loop.py` (append)

**Interfaces:**
- Consumes: `SOURCE_REGISTRY` (`api/app/research/registry.py`), `resolve_available_sources` (to know which authority sources are enabled), the existing `assemble_allowlist(...)` signature, `_dispatch_authority(...)` signature in `tool_loop.py`.
- Produces: chat authority tools `search_authority`/`get_authority` that take a `source` argument (enum = enabled authority source types); `_dispatch_authority` resolves the adapter via `SOURCE_REGISTRY[source].adapter`.

- [ ] **Step 1: Write the failing test — the `source` enum is built from enabled authority sources**

Append to `api/tests/chat/test_tool_schemas.py`:
```python
from app.chat.tool_schemas import build_authority_tool_schemas


def test_authority_source_enum_lists_enabled_sources():
    # both govinfo + edgar enabled → source enum has both
    schemas = build_authority_tool_schemas(enabled_sources=["govinfo", "edgar"])
    search = next(s for s in schemas if s["name"] == "search_authority")
    source_prop = search["parameters"]["properties"]["source"]
    assert set(source_prop["enum"]) == {"govinfo", "edgar"}


def test_authority_schemas_empty_when_no_sources():
    assert build_authority_tool_schemas(enabled_sources=[]) == []


def test_govinfo_only_still_works():
    schemas = build_authority_tool_schemas(enabled_sources=["govinfo"])
    search = next(s for s in schemas if s["name"] == "search_authority")
    assert search["parameters"]["properties"]["source"]["enum"] == ["govinfo"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/chat/test_tool_schemas.py -v -k authority_source`
Expected: FAIL — `build_authority_tool_schemas` not defined.

- [ ] **Step 3: Replace the GovInfo-specific schemas with a registry-driven builder**

In `api/app/chat/tool_schemas.py`, add a `source` param and generalize. Replace the hardcoded `AUTHORITY_TOOL_SCHEMAS` with a builder:
```python
def build_authority_tool_schemas(enabled_sources: list[str]) -> list[dict]:
    """Authority tools parameterized by source. `source` enum = enabled authority
    sources (registry types whose ops include the authority ops). Empty list → []."""
    if not enabled_sources:
        return []
    source_enum = {"type": "string", "enum": list(enabled_sources)}
    return [
        {
            "name": "search_authority",
            "description": (
                "Full-text search an authoritative source (e.g. govinfo = U.S. Code/CFR; "
                "edgar = SEC company filings). Returns items with an external_ref."
            ),
            "parameters": {
                "type": "object",
                "properties": {"source": source_enum, "query": {"type": "string"},
                               "forms": {"type": "string"}},
                "required": ["source", "query"],
            },
        },
        {
            "name": "get_authority",
            "description": "Fetch the full text of a specific authority item by source + external_ref.",
            "parameters": {
                "type": "object",
                "properties": {"source": source_enum, "external_ref": {"type": "string"}},
                "required": ["source", "external_ref"],
            },
        },
    ]


AUTHORITY_OPS = ("search_authority", "get_authority")
```

- [ ] **Step 4: Generalize `assemble_allowlist` to iterate enabled authority sources**

Replace the `type == "govinfo"` / `provider="govinfo"` hardcode (~201-226) with registry iteration. The authority sources are the registry entries whose `ops` include the authority ops AND that are enabled in the gateway. Pattern:
```python
    # authority sources: registry entries exposing authority ops, enabled in the gateway
    authority_types = [
        t for t, spec in SOURCE_REGISTRY.items()
        if set(AUTHORITY_OPS) & set(spec.ops)
    ]
    enabled_authority = [t for t in authority_types if t in enabled_provider_types]
    for schema in build_authority_tool_schemas(enabled_authority):
        specs.append(ToolSpec(kind="authority", tool=schema["name"],
                              provider=None, schema=schema))  # provider resolved per-call from `source` arg
```
> Adapt to the real `ToolSpec` construction + how `assemble_allowlist` already learns `enabled_provider_types` (it calls `resolve_available_sources`/`list_tool_providers`). The KEY change: `provider` is no longer pinned to `"govinfo"`; the source comes from the tool call's `source` argument at dispatch.

- [ ] **Step 5: Write the failing test for `_dispatch_authority` registry-driven adapter**

Append to `api/tests/chat/test_tool_loop.py`:
```python
import pytest


@pytest.mark.asyncio
async def test_dispatch_authority_uses_registry_adapter_for_edgar(monkeypatch):
    # a get_authority call with source=edgar must normalize via EdgarAdapter →
    # content_kind sec_filing in the ToolResult.data["authority"]
    from app.chat import tool_loop

    async def fake_call_tool(provider, op, args):
        return {"payload": {"external_ref": "1005010_00011_dex.htm", "title": "dex.htm",
                            "url": "https://www.sec.gov/x", "text": "Body text",
                            "content_kind": "sec_filing"}}

    # ... construct the ToolSpec(kind="authority", tool="get_authority"), gateway stub
    # with fake_call_tool, args {"source": "edgar", "external_ref": "1005010_00011_dex.htm"}
    result = await tool_loop._dispatch_authority(...)  # fill per real signature
    assert result.data["authority"]["content_kind"] == "sec_filing"
```
> This test's scaffolding depends on `_dispatch_authority`'s real signature — the implementer fills the `...` from the function at `tool_loop.py:377-433`. The assertion (edgar payload → sec_filing via the registry adapter) is the contract.

- [ ] **Step 6: Make `_dispatch_authority` registry-driven**

In `api/app/chat/tool_loop.py` (~line 393) replace `GovInfoAdapter()` with a registry lookup keyed on the call's `source` arg:
```python
    source = args["source"]
    spec_entry = SOURCE_REGISTRY.get(source)
    if spec_entry is None or spec_entry.adapter is None:
        # non-fatal failed observation, mirror the existing unknown-source handling
        ...
    adapter = spec_entry.adapter
    provider_name = _resolve_authority_provider_name(source)  # type→configured gateway name
    payload = (await gateway.call_tool(provider_name, op, tool_args))["payload"]
    fetched = adapter.from_response(op, payload)
```
Provider-name resolution reuses the same registry→gateway mapping the autonomous path uses (`resolve_available_sources` / `resolve_provider_name_by_type`). Keep the cache write (`store_authority_text`) for `get_authority`, unchanged.

- [ ] **Step 7: Run chat tests + confirm GovInfo unchanged**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/chat/test_tool_schemas.py tests/chat/test_tool_loop.py -v`
Expected: PASS, including the pre-existing GovInfo cases (now expressed as `source:"govinfo"`).

- [ ] **Step 8: Commit**

```bash
git add api/app/chat/tool_schemas.py api/app/chat/tool_loop.py \
        api/tests/chat/test_tool_schemas.py api/tests/chat/test_tool_loop.py
git commit -s -m "feat(chat): registry-driven authority tools (source arg), unhardcode GovInfo

search_authority/get_authority take a source enum built from enabled authority
sources; _dispatch_authority resolves the adapter from SOURCE_REGISTRY. GovInfo
behavior preserved as source=govinfo. Refs DE-371"
```

---

## Task 4: Verify content-kind set (DE-371) + autonomous carry-through

**Files:**
- Modify: `api/app/citation/authority.py` (`_VERIFIABLE_CONTENT_KINDS` ~line 269)
- Modify: `api/app/autonomous/ledger_bridge.py` (content_kind default ~line 521 — carry adapter kind, don't force `"statute"`)
- Test: `api/tests/citation/test_authority_verify.py` (append), `api/tests/autonomous/` ledger-bridge test (append/create)

**Interfaces:**
- Consumes: `verify_and_persist_authority_citations` (`authority.py:244+`), `build_authority_citations` (`ledger_bridge.py:331+`).
- Produces: `sec_filing` is a verifiable content kind; autonomous EDGAR citations carry `content_kind="sec_filing"` end to end.

- [ ] **Step 1: Write the failing test — a sec_filing quote is verified & persisted**

Append to `api/tests/citation/test_authority_verify.py` a case mirroring the existing statute verify test but with `content_kind="sec_filing"` and a cached EDGAR body, asserting a `MessageAuthorityCitation` row is written with `content_kind="sec_filing"`, `verified=True`, `verification_method="exact_match"`. (Reuse the existing test's fixtures/harness; swap the content kind + body.)

- [ ] **Step 2: Run it to verify it fails**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/citation/test_authority_verify.py -v -k sec_filing`
Expected: FAIL — the ref is filtered out by `_VERIFIABLE_CONTENT_KINDS` → 0 rows.

- [ ] **Step 3: Extend the verifiable set**

`api/app/citation/authority.py` ~line 269:
```python
    _VERIFIABLE_CONTENT_KINDS = {"statute", "regulation", "sec_filing"}
```
Update the adjacent comment to note EDGAR `sec_filing` is now covered; EUR-Lex kinds still pending (PR2b).

- [ ] **Step 4: Run the verify test**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/citation/test_authority_verify.py -v -k sec_filing`
Expected: PASS.

- [ ] **Step 5: Write the failing test — autonomous carry-through keeps sec_filing**

Append an autonomous ledger-bridge test: an EDGAR EvidenceItem/authority target with `content_kind="sec_filing"` flows through `build_authority_citations` and the persisted `MessageAuthorityCitation.content_kind == "sec_filing"` (NOT defaulted to `"statute"`).

- [ ] **Step 6: Run it to verify it fails**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/autonomous -v -k authority_content_kind`
Expected: FAIL if `ledger_bridge.py:~521` hardcodes `"statute"` — the row comes back `statute`.

- [ ] **Step 7: Thread the real content_kind through `build_authority_citations`**

`api/app/autonomous/ledger_bridge.py` ~line 521: replace the `"statute"` default with the content_kind carried on the evidence/authority target (fall back to `"statute"` only when genuinely absent, or better `"unknown"`). Confirm the EvidenceItem carries `content_kind` from the adapter (PR1a threaded `source`/`content_kind` onto EvidenceItem).

- [ ] **Step 8: Run it to verify it passes**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/autonomous -v -k authority_content_kind`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add api/app/citation/authority.py api/app/autonomous/ledger_bridge.py \
        api/tests/citation/test_authority_verify.py api/tests/autonomous/
git commit -s -m "feat(citation): verify sec_filing quotes; carry EDGAR content_kind (DE-371)

Add sec_filing to _VERIFIABLE_CONTENT_KINDS; autonomous build_authority_citations
no longer defaults content_kind to statute. Refs DE-371"
```

---

## Task 5: gateway.yaml.example block + docs

**Files:**
- Modify: `gateway.yaml.example` (add commented `edgar-prod` block near the govinfo block ~219-232)
- Modify: `docs/PRD.md` (WS-E status: EDGAR shipped in PR2a; DE-371 partially addressed — `sec_filing` covered, EUR-Lex kinds + autonomous SUPPORTED-tier still open)

**Interfaces:** none (config example + docs).

- [ ] **Step 1: Add the EDGAR provider block to `gateway.yaml.example`**

```yaml
#   - name: edgar-prod
#     type: edgar                  # shipped in WS-E PR2a; uncomment to enable
#     base_url: https://efts.sec.gov          # full-text search host; get_authority reaches www.sec.gov
#     user_agent: "YourOrg legal-ops@yourorg.example"   # SEC fair-access policy — REQUIRED, no API key
#     egress_tier: 4               # public filing data (ADR 0014 D4)
#     allowlist:
#       hosts: [efts.sec.gov, www.sec.gov]
#     rate_limit:
#       requests_per_minute: 300   # SEC allows ~10 req/s
#     anonymize_outbound: false    # public filings; skip_anonymization=True on results
#     # (no api_key_env — EDGAR needs only a User-Agent)
#     # (no cost_per_call — free source; R4 stays a no-op)
```

- [ ] **Step 2: Update the PRD WS-E status + DE-371**

In `docs/PRD.md`, mark WS-E PR2a (SEC EDGAR) shipped, note EDGAR available in chat + autonomous, and update DE-371 to "partially addressed (sec_filing verifiable); EUR-Lex kinds + autonomous SUPPORTED-tier remain."

- [ ] **Step 3: Commit**

```bash
git add gateway.yaml.example docs/PRD.md
git commit -s -m "docs(WS-E): EDGAR gateway.yaml example + PRD status (PR2a)

Refs DE-371"
```

---

## Final gates (before PR)

- [ ] **Prove untouched surfaces:** `git diff --name-only main..HEAD` shows NO `api/app/citation/gate.py`, `api/app/citation/ledger.py`, or `api/alembic/**`.
- [ ] **api full DB-backed SOLO suite (the REAL gate):**
  `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest -p no:randomly -q` → expect all pass / 1 skip (NOT a 1500-skip hollow green).
- [ ] **api static (from repo root):** `ruff check api scripts && ruff format --check api scripts && (cd api && python -m mypy app)`
- [ ] **gateway:** `cd gateway && ruff format --check . && ruff check . && python -m mypy --strict app && python -m pytest -q`
- [ ] **No new route** → `test_openapi`/`test_endpoints` path counts unchanged (verify they pass; do NOT bump counts).
- [ ] **Opus whole-branch review** (has caught a gate-passing defect on every slice this milestone) → fix any Critical/Important → re-review.
- [ ] **Ship:** push `origin` + `tucuxi`, open the security-gated PR (Kevin/security merges, NO self-merge), watch CI, mirror `origin`→`tucuxi`, delete the branch.

---

## Self-review notes (plan ↔ spec)

- **Spec coverage:** §4 gateway adapter → Task 1; §5 backend adapter+registry → Task 2; §6 chat generalization → Task 3; §7 verify set + autonomous carry-through → Task 4; §8 config/flag → Task 5; §9 testing folded into each task + Final gates; §2 invariants → Global Constraints + Final-gates `git diff --name-only` proof.
- **Placeholder scan:** the two `...` spots (Task 3 Step 5, Task 3 Step 6) are explicitly flagged as "fill from the real signature at `tool_loop.py:377-433`" — the *contract/assertion* is concrete; only the call scaffolding is signature-dependent (unavoidable without the exact current source in hand). Everything else is complete code.
- **Type consistency:** `build_authority_tool_schemas(enabled_sources)`, `AUTHORITY_OPS`, `EdgarAdapter().from_response(op, payload)`, `FetchedAuthority(citable_text,label,subtitle,url,external_ref,content_kind)`, `external_ref` = `{cik}_{accession_no_dashes}_{document}` used consistently across gateway (produces) → backend adapter (consumes) → verify/ledger.
