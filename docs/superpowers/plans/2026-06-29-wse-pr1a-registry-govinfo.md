# WS-E PR1a — Content-source registry + GovInfo + DE-344 cost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The autonomous matter session can reach **GovInfo** (US federal statutes/regs) through the governed gateway egress via a new closed-set `retrieve_authority` intent, validated against a backend **content-source registry** (joined with the gateway's enabled providers), with a real **DE-344 per-provider cost model** so R4 throttles external tools — fetched authority captured as ledger **provenance** (`MessageToolSource`). (Char-fidelity verification + fiduciary-ledger-backing of fetched quotes is **PR1b**, mech-B.)

**Architecture:** Reuse, never fork (ADR 0014/0015/0016/0021). GovInfo is a new gateway tool-provider `type` (transport/auth/SSRF/cost stay gateway-side); the backend reaches it only via `gateway call_tool`. One generic `ToolIntent.retrieve_authority(source, op, args)` with model-generated/handler-validated args (the WS-D `validate_action_args` boundary); source/op validated against a backend registry that is the intersection of operator-enabled providers ∩ adapter-shipped types. `estimate_tool_cost` returns a configured per-provider rate (free → $0).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), httpx, respx, pytest, ruff, mypy. Subsystems: `gateway/app/`, `api/app/research/`, `api/app/autonomous/`, `api/app/tools/`.

## Global Constraints

- **Security-gated** (`gateway/**`, `api/app/autonomous/**`, `api/app/tools/governance.py`): security/maintainer merges; mirror `origin/main → tucuxi` after. Claude does NOT self-merge.
- **One egress (ADR 0014):** the backend NEVER calls GovInfo directly — only `get_gateway_client().call_tool(provider, op, args)`. Secrets/auth/SSRF-allowlist/rate-limit stay gateway-side.
- **Closed-set, validated (ADR 0015):** `retrieve_authority` is one closed `ToolIntent`; `source`/`op`/`args` are model-generated and **handler-validated against the live registry**. An unknown/disabled source or unsupported op or bad args is a **non-fatal failed observation** (a clean `ValueError` caught by the WS-D loop), NEVER an exception that escapes the governed path or poisons the session (the WS-D PR1-C1 lesson).
- **Honest unavailability (ADR 0021 D5):** a source registered but not enabled/configured in the gateway is surfaced unavailable-with-reason and is never selectable. Coverage strings never imply comprehensive coverage. GovInfo is BYO-key (`GOVINFO_API_KEY`) → unavailable when unset.
- **DE-344 (ADR 0021 D4):** `estimate_tool_cost` returns the configured per-provider rate for `retrieve_authority`/`retrieve_caselaw`/`call_mcp_tool`; free sources omit the field → `Decimal("0")` → R4 a no-op for them (correct). Realized cost on `tool_call_log.cost_usd`.
- **P3 (ADR 0016):** `GET /research/sources` and planner-visible source metadata carry name/type/jurisdiction/coverage/ids only — never auth/cost secrets or raw payloads.
- **`extra="allow"`:** `cost_per_call`/`cost_per_unit` ride `ToolProviderConfig`'s `extra="allow"` (`gateway/app/config.py:177`) as `model_extra` — NO `ToolProviderConfig` field addition, NO config-schema migration.
- **Tests:** api host venv `api/.venv` + throwaway pgvector `:55432`, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test`; gateway `gateway/.venv`. respx for upstream HTTP; stub DNS (`monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])`). No `-m provider`. **Run the api suite SOLO** (DE-368).
- **CI gate (repo root):** `ruff check api scripts` + `ruff format --check api scripts` + gateway equivalents; `mypy app` whole-app (api) + `mypy app --strict` (gateway); both full suites. Next migration = `0064` (UNUSED by PR1a — no schema change here; 0064 is PR1b). Next DE = DE-369.
- Commits: `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## File structure

| File | Change | Task |
|---|---|---|
| `gateway/app/config.py` | `ToolProviderType` Literal += `"govinfo"` | 1 |
| `gateway/app/providers/tool/govinfo.py` | NEW adapter (skeleton + transport) | 1 |
| `gateway/app/providers/tool/__init__.py`, `gateway/app/main.py` | register adapter | 1 |
| `gateway/app/providers/tool/govinfo.py` | ops `search_authority`/`get_authority` + dispatch | 2 |
| `gateway.yaml.example` | document a `govinfo` tool-provider entry (+ cost fields comment) | 2 |
| `api/app/research/registry.py` | NEW source registry + `resolve_available_sources` | 3 |
| `api/app/research/adapters.py` | NEW `SourceAdapter` + `GovInfoAdapter.from_response` | 3 |
| `api/app/api/research.py` (or existing research router) | `GET /research/sources` | 4 |
| `api/tests/test_openapi.py`, `api/tests/test_endpoints.py` | new path count + route | 4 |
| `api/app/autonomous/enums.py` | `ToolIntent.retrieve_authority` + grant | 5 |
| `api/app/autonomous/guard.py` | `_EXTERNAL_TOOL_INTENTS` + `_resolve_external_call` + `_handle_retrieve_authority` | 5 |
| `api/app/autonomous/planner.py` | `PLANNER_ALLOWLIST` += ; `validate_action_args` branch; `collect_evidence` authority kind | 5, 6 |
| `api/app/autonomous/cost.py`, `api/app/tools/governance.py` | DE-344 cost cache + estimate | 7 |

---

### Task 1: Gateway GovInfo adapter — type + transport skeleton + registration

**Files:**
- Modify: `gateway/app/config.py:150` (`ToolProviderType` Literal)
- Create: `gateway/app/providers/tool/govinfo.py`
- Modify: `gateway/app/providers/tool/__init__.py` (export), `gateway/app/main.py:180-200` (`build_tool_adapter` branch)
- Test: `gateway/tests/test_govinfo_adapter.py` (new)

**Interfaces:**
- Produces: `GovInfoToolAdapter(ToolProviderAdapter)` with `from_config(provider, *, key_resolver=None, client=None)`, `validate_base_url()`, `_request(method, path, *, params=None) -> dict`, `health_check()`. Auth header **`X-Api-Key: {api_key}`** (GovInfo uses DATA.GOV key style, NOT `Authorization: Token`). `_result(...)` builds `ToolResult(..., skip_anonymization=True)` (public statutory text reaches the verifier verbatim, ADR 0014 D5). `invoke_tool` raises `ToolProviderError("unknown tool ...")` for any tool (ops land in Task 2).

- [ ] **Step 1: Read the pattern.** Read `gateway/app/providers/tool/courtlistener.py` (`from_config:83`, `_request:114`, `_result:335`, `validate_base_url:111`, `health_check`) and `gateway/app/providers/tool/base.py` (`ToolProviderAdapter` ABC + the error types `ToolProviderError`/`ToolProviderAuthError`/`ToolProviderHTTPError`/`ToolProviderInvalidRequestError`). Mirror it. Note `validate_egress_target(url, allowlist=...)` import + usage.

- [ ] **Step 2: Write the failing test** (`gateway/tests/test_govinfo_adapter.py`):

```python
import pytest
import respx
import httpx
from app.config import ToolProviderConfig
from app.providers.tool.govinfo import GovInfoToolAdapter


def _adapter(monkeypatch):
    monkeypatch.setattr("app.providers.tool.egress._resolve_ips", lambda host: ["93.184.216.34"])
    monkeypatch.setenv("GOVINFO_API_KEY", "test-key")
    cfg = ToolProviderConfig.model_validate({
        "name": "govinfo-prod", "type": "govinfo",
        "base_url": "https://api.govinfo.gov",
        "api_key_env": "GOVINFO_API_KEY", "egress_tier": 4,
        "allowlist": {"hosts": ["api.govinfo.gov"]},
        "rate_limit": {"requests_per_minute": 60},
    })
    return GovInfoToolAdapter.from_config(cfg)


@pytest.mark.asyncio
async def test_from_config_type_check():
    cfg = ToolProviderConfig.model_validate({
        "name": "x", "type": "courtlistener", "base_url": "https://www.courtlistener.com",
        "egress_tier": 4, "allowlist": {"hosts": ["www.courtlistener.com"]},
        "rate_limit": {"requests_per_minute": 60},
    })
    with pytest.raises(ValueError):
        GovInfoToolAdapter.from_config(cfg)


@pytest.mark.asyncio
async def test_request_sends_x_api_key_header(monkeypatch):
    adapter = _adapter(monkeypatch)
    with respx.mock:
        route = respx.get("https://api.govinfo.gov/collections").mock(
            return_value=httpx.Response(200, json={"collections": []})
        )
        await adapter._request("GET", "/collections")
    assert route.calls.last.request.headers["X-Api-Key"] == "test-key"


@pytest.mark.asyncio
async def test_unknown_tool_raises(monkeypatch):
    from app.providers.tool.base import ToolProviderError
    adapter = _adapter(monkeypatch)
    with pytest.raises(ToolProviderError):
        await adapter.invoke_tool("nope", {}, request_id="r1")
```

- [ ] **Step 3: Run — expect failure**

Run: `cd gateway && .venv/bin/python -m pytest tests/test_govinfo_adapter.py -v`
Expected: FAIL — module/type missing.

- [ ] **Step 4: Add the type + implement the skeleton.** In `gateway/app/config.py:150` extend the Literal:
```python
ToolProviderType = Literal["echo", "courtlistener", "mcp", "govinfo"]
```
Create `gateway/app/providers/tool/govinfo.py` mirroring `courtlistener.py` — `from_config` (raise `ValueError` if `provider.type != "govinfo"`; resolve key via the same `key_resolver`/`ProviderKeyResolver`), `validate_base_url`, `_request` (the ONLY structural difference from CourtListener: header `headers["X-Api-Key"] = self._api_key` instead of `Authorization: Token`; same SSRF `validate_egress_target`, same status→error mapping 401/403→`ToolProviderAuthError`, 429→`ToolProviderHTTPError(upstream_status=429)`, 4xx→`ToolProviderInvalidRequestError`, 5xx→`ToolProviderHTTPError`), `health_check` (GET a cheap endpoint e.g. `/collections`), `_result(tool, payload, ...)` with `skip_anonymization=True`, and `invoke_tool` that raises `ToolProviderError(f"unknown tool {tool!r} for govinfo provider")` (ops in Task 2). Read `cost_per_call`/`cost_per_unit` are NOT needed gateway-side for dispatch (backend reads them from config) — do not add here.

In `gateway/app/providers/tool/__init__.py` add `GovInfoToolAdapter` to imports + `__all__`. In `gateway/app/main.py` `build_tool_adapter` (~line 180) add:
```python
    if provider.type == "govinfo":
        return GovInfoToolAdapter.from_config(provider)
```

- [ ] **Step 5: Run — expect pass + gateway regression**

Run: `cd gateway && .venv/bin/python -m pytest tests/test_govinfo_adapter.py tests/test_tools_route.py -v`
Expected: PASS.

- [ ] **Step 6: Gates + commit**

```bash
cd gateway && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app --strict
git add gateway/app/config.py gateway/app/providers/tool/govinfo.py gateway/app/providers/tool/__init__.py gateway/app/main.py gateway/tests/test_govinfo_adapter.py
git commit -s -m "feat(gateway): GovInfo tool-provider adapter skeleton + type (WS-E PR1a)"
```

---

### Task 2: Gateway GovInfo ops — `search_authority` + `get_authority`

**Files:**
- Modify: `gateway/app/providers/tool/govinfo.py` (`invoke_tool` dispatch + the two op methods)
- Modify: `gateway.yaml.example` (document a `govinfo` entry + cost-field comment)
- Test: `gateway/tests/test_govinfo_adapter.py` (extend) + a Router integration test

**Interfaces:**
- Produces: `invoke_tool("search_authority", {"collection","query","page_size?"})` → `{"results": [{"package_id"|"granule_id","title","collection","date?"}], "count"}`; `invoke_tool("get_authority", {"package_id"|"granule_id"})` → `{"package_id","title","citation?","url","text"}`. Routes to GovInfo REST (`/search` + `/packages/{id}/...`/`/related`); the EXACT GovInfo endpoints + response mapping are confirmed in Step 1.

- [ ] **Step 1: Confirm the GovInfo API shapes.** GovInfo REST is documented at `https://api.govinfo.gov/docs` (api.data.gov key via `X-Api-Key` or `?api_key=`). Confirm: the **search** endpoint (`POST /search` with a query payload, or `GET /search?query=...`) and its result fields (packageId, title, collectionCode, dateIssued); the **packages** endpoint to fetch a document's text/summary (`GET /packages/{packageId}/summary` for metadata; the text/granule retrieval path for USCODE/CFR). Record the exact endpoints + fields used in the task report. (Collections for PR1a: **USCODE**, **CFR**.) If the live API shape differs from assumptions, adapt the op methods and note it — the asserted contract is the normalized op output above, not GovInfo's raw shape.

- [ ] **Step 2: Write the failing tests** (extend `test_govinfo_adapter.py`) — mock the confirmed GovInfo endpoints with respx and assert the NORMALIZED op output:

```python
@pytest.mark.asyncio
async def test_search_authority_normalizes_results(monkeypatch):
    adapter = _adapter(monkeypatch)
    with respx.mock:
        respx.route(method__in=["GET", "POST"], host="api.govinfo.gov").mock(
            return_value=httpx.Response(200, json={  # shape per Step 1
                "results": [{"packageId": "USCODE-2022-title15", "title": "Title 15",
                             "collectionCode": "USCODE", "dateIssued": "2022-01-01"}],
                "count": 1,
            })
        )
        out = await adapter.invoke_tool("search_authority",
            {"collection": "USCODE", "query": "antitrust"}, request_id="r1")
    assert out["count"] == 1
    assert out["results"][0]["package_id"] == "USCODE-2022-title15"
    assert out["results"][0]["collection"] == "USCODE"


@pytest.mark.asyncio
async def test_get_authority_returns_text(monkeypatch):
    adapter = _adapter(monkeypatch)
    with respx.mock:
        respx.route(method__in=["GET"], host="api.govinfo.gov").mock(
            return_value=httpx.Response(200, json={  # shape per Step 1
                "packageId": "USCODE-2022-title15", "title": "Title 15 § 1",
                "download": {"txtLink": "https://api.govinfo.gov/packages/USCODE-2022-title15/htm"},
            })
        )
        # if get_authority follows a txt link, mock that too
        out = await adapter.invoke_tool("get_authority",
            {"package_id": "USCODE-2022-title15"}, request_id="r1")
    assert "text" in out and out["package_id"] == "USCODE-2022-title15"
```

Also add a Router integration test (pattern: `gateway/tests/test_courtlistener_adapter.py:265-298`) asserting `route_tool_call("govinfo-prod","search_authority",...)` writes an egress-log row with `refused=False`.

- [ ] **Step 3: Run — expect failure**

Run: `cd gateway && .venv/bin/python -m pytest tests/test_govinfo_adapter.py -v`
Expected: FAIL — ops not implemented.

- [ ] **Step 4: Implement the ops.** In `govinfo.py`, replace `invoke_tool`'s raise with dispatch:
```python
    async def invoke_tool(self, tool, args, *, request_id, user_token=None):
        if tool == "search_authority":
            return self._result(tool, await self._search_authority(args))
        if tool == "get_authority":
            return self._result(tool, await self._get_authority(args))
        raise ToolProviderError(f"unknown tool {tool!r} for govinfo provider")
```
Implement `_search_authority` (validate `collection` ∈ {USCODE, CFR}, `query` non-empty; call the confirmed search endpoint; normalize to `{results:[{package_id/granule_id,title,collection,date}], count}`) and `_get_authority` (fetch package/granule text via the confirmed path; normalize to `{package_id,title,citation?,url,text}`). Bad args → `ToolProviderInvalidRequestError`.

- [ ] **Step 5: Document the config.** In `gateway.yaml.example` add a commented `govinfo` `tool_providers` entry (mirroring the courtlistener block) with `type: govinfo`, `base_url: https://api.govinfo.gov`, `api_key_env: GOVINFO_API_KEY`, `egress_tier: 4`, `allowlist.hosts: [api.govinfo.gov]`, `rate_limit`, and a comment showing the optional DE-344 `cost_per_call: 0.0` / `cost_per_unit` fields (free source → omit or 0).

- [ ] **Step 6: Run — expect pass + gateway suite**

Run: `cd gateway && .venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 7: Gates + commit**

```bash
cd gateway && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app --strict
git add gateway/app/providers/tool/govinfo.py gateway.yaml.example gateway/tests/test_govinfo_adapter.py
git commit -s -m "feat(gateway): GovInfo search_authority + get_authority ops (WS-E PR1a)"
```

---

### Task 3: Backend content-source registry + GovInfo response adapter

**Files:**
- Create: `api/app/research/registry.py`, `api/app/research/adapters.py`
- Test: `api/tests/test_source_registry.py` (new)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) SourceSpec(type: str, jurisdiction: str, coverage: str, content_kinds: tuple[str,...], ops: tuple[str,...], adapter: SourceAdapter)`.
  - `SOURCE_REGISTRY: dict[str, SourceSpec]` (keys: `"courtlistener"`, `"govinfo"`).
  - `async resolve_available_sources(gateway) -> list[AvailableSource]` — `AvailableSource(name, type, jurisdiction, coverage, content_kinds, enabled, egress_tier)`; joins `gateway.list_tool_providers()` (operator-enabled, by type) with `SOURCE_REGISTRY` (adapter-shipped). A configured provider whose type is not in the registry is excluded; a registry type with no configured provider is reported `enabled=False` (unavailable). NO secrets/cost.
  - `SourceAdapter` Protocol + `GovInfoAdapter`: `from_response(op: str, payload: dict) -> FetchedAuthority` where `@dataclass FetchedAuthority(citable_text, label, subtitle, url, external_ref, content_kind)`.

- [ ] **Step 1: Write the failing tests** (`api/tests/test_source_registry.py`):

```python
import pytest
from unittest.mock import AsyncMock
from app.research.registry import SOURCE_REGISTRY, resolve_available_sources
from app.research.adapters import GovInfoAdapter, FetchedAuthority


def test_registry_has_courtlistener_and_govinfo():
    assert "courtlistener" in SOURCE_REGISTRY and "govinfo" in SOURCE_REGISTRY
    assert "search_authority" in SOURCE_REGISTRY["govinfo"].ops


@pytest.mark.asyncio
async def test_resolve_intersects_enabled_and_registered():
    gw = AsyncMock()
    gw.list_tool_providers.return_value = [
        {"name": "govinfo-prod", "type": "govinfo"},
        {"name": "mystery", "type": "not_in_registry"},  # excluded
    ]
    out = await resolve_available_sources(gw)
    by_type = {s.type: s for s in out}
    assert by_type["govinfo"].name == "govinfo-prod" and by_type["govinfo"].enabled is True
    assert "not_in_registry" not in by_type
    # a registry type with no configured provider is reported unavailable
    assert by_type["courtlistener"].enabled is False


def test_govinfo_adapter_from_response_get():
    fa = GovInfoAdapter().from_response("get_authority", {
        "package_id": "USCODE-2022-title15", "title": "15 U.S.C. § 1",
        "citation": "15 U.S.C. § 1", "url": "https://www.govinfo.gov/...",
        "text": "Every contract ... in restraint of trade ... is declared to be illegal.",
    })
    assert isinstance(fa, FetchedAuthority)
    assert fa.external_ref == "USCODE-2022-title15"
    assert "restraint of trade" in fa.citable_text
    assert fa.content_kind in {"statute", "regulation"}
```

- [ ] **Step 2: Run — expect failure**

Run: `cd api && .venv/bin/python -m pytest tests/test_source_registry.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement** `adapters.py` (`SourceAdapter` Protocol, `FetchedAuthority` dataclass, `GovInfoAdapter.from_response` mapping `search_authority`/`get_authority` payloads; `content_kind` from the collection: USCODE→`statute`, CFR→`regulation`), then `registry.py` (`SourceSpec`, `SOURCE_REGISTRY` with courtlistener {jurisdiction `us-federal`, coverage "U.S. federal & state appellate caselaw (operator CourtListener key)", content_kinds `("caselaw",)`, ops the research service exposes, adapter=a passthrough/None for caselaw} and govinfo {jurisdiction `us-federal`, coverage "U.S. Code + Code of Federal Regulations", content_kinds `("statute","regulation")`, ops `("search_authority","get_authority")`, adapter=`GovInfoAdapter()`}), and `resolve_available_sources(gateway)`).

- [ ] **Step 4: Run — expect pass**

Run: `cd api && .venv/bin/python -m pytest tests/test_source_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/research/registry.py api/app/research/adapters.py api/tests/test_source_registry.py
git commit -s -m "feat(research): content-source registry + GovInfo response adapter (WS-E PR1a)"
```

---

### Task 4: `GET /api/v1/research/sources` endpoint

**Files:**
- Modify/Create: the research router (grep `grep -rn "research" api/app/api/*.py` — reuse the existing research router if present, else create `api/app/api/research.py` and register it in the app)
- Modify: `api/tests/test_openapi.py` (path count + `EXPECTED_PATHS`), `api/tests/test_endpoints.py` (`IMPLEMENTED_ROUTES`)
- Test: `api/tests/test_research_sources_endpoint.py` (new)

**Interfaces:**
- Produces: `GET /api/v1/research/sources` (auth: any active user) → `{"sources": [AvailableSource serialized]}` — name/type/jurisdiction/coverage/content_kinds/enabled/egress_tier; NEVER auth/cost fields. Uses `resolve_available_sources(get_gateway_client())`.

- [ ] **Step 1: Write the failing test** (`api/tests/test_research_sources_endpoint.py`) — mirror an existing research/endpoint test's client+auth fixture; stub the gateway's `list_tool_providers` (monkeypatch `app.clients.gateway.get_gateway_client` or inject) to return a govinfo provider; assert 200, the govinfo source present with `enabled` + coverage, and NO `api_key`/`cost` keys in the response.

- [ ] **Step 2: Run — expect failure** (404 route missing).

- [ ] **Step 3: Implement** the handler (owner/active-user auth dependency matching sibling research endpoints; call `resolve_available_sources`; serialize to a Pydantic response model with only the safe fields). Register the route.

- [ ] **Step 4: Bump collision guards.** Add `/api/v1/research/sources` to `EXPECTED_PATHS` + the pinned path count in `test_openapi.py`; add to `IMPLEMENTED_ROUTES` in `test_endpoints.py`. (Off-by-one fails whole-suite collection — CLAUDE.md.)

- [ ] **Step 5: Run — expect pass + guards**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/test_research_sources_endpoint.py tests/test_openapi.py tests/test_endpoints.py -v`
Expected: PASS.

- [ ] **Step 6: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/api/ api/tests/test_research_sources_endpoint.py api/tests/test_openapi.py api/tests/test_endpoints.py
git commit -s -m "feat(research): GET /research/sources registry endpoint (WS-E PR1a)"
```

---

### Task 5: `ToolIntent.retrieve_authority` + governed dispatch + handler

**Files:**
- Modify: `api/app/autonomous/enums.py` (`ToolIntent` + `PHASE_GRANTS[analysis]`)
- Modify: `api/app/autonomous/guard.py` (`_EXTERNAL_TOOL_INTENTS`, `_resolve_external_call`, `_dispatch` → `_handle_retrieve_authority`)
- Modify: `api/app/autonomous/cost.py` (treat `retrieve_authority` like the other external intents — $0 until Task 7)
- Test: `api/tests/autonomous/test_retrieve_authority.py` (new)

**Interfaces:**
- Produces: `ToolIntent.retrieve_authority = "retrieve_authority"`, granted in `Phase.analysis`, ∈ `_EXTERNAL_TOOL_INTENTS`. `guarded_tool_call(session, ToolIntent.retrieve_authority, {"source","op","args"}, db, gateway)` → resolves the provider from the registry by `source`, `call_tool(provider, op, args)`, runs `GovInfoAdapter.from_response`, writes a `MessageToolSource` provenance row (`source_kind`=content_kind, provider/tool), returns `ToolResult(data={"authority": {text, external_ref, label, url, content_kind}})`.

- [ ] **Step 1: Write the failing tests** (`api/tests/autonomous/test_retrieve_authority.py`) — reuse the autonomous guard test fixtures (a running session, a scripted gateway whose `call_tool` returns a GovInfo `get_authority` payload). Assert: a `retrieve_authority` call routes through `guarded_tool_call` (a `tool_call` started audit row with tool `retrieve_authority`), produces a `MessageToolSource` row with the content_kind, and returns the fetched text + external_ref. Plus: an unknown/disabled `source` → the handler raises (caught upstream) and writes NO provenance row; `retrieve_authority` is granted ONLY in analysis.

- [ ] **Step 2: Run — expect failure.**

- [ ] **Step 3: Implement.** `enums.py`: add the member + grant in `PHASE_GRANTS[Phase.analysis]`. `guard.py`: add to `_EXTERNAL_TOOL_INTENTS`; in `_resolve_external_call`, for `retrieve_authority` resolve `provider` via `resolve_available_sources` filtered to `params["source"]` (enabled only; else raise `ValueError`) and `tool=params["op"]`; add `_handle_retrieve_authority(params, *, db, gateway)` to `_dispatch` (validate source enabled + op ∈ source.ops; `gateway.call_tool(provider, op, params["args"])`; `from_response`; write `MessageToolSource`; return `ToolResult`). `cost.py`: ensure `retrieve_authority` falls in the external/$0 branch (Task 7 makes it real).

- [ ] **Step 4: Run — expect pass + autonomous suite (SOLO).**

Run: `cd api && DATABASE_URL=... .venv/bin/python -m pytest tests/autonomous/test_retrieve_authority.py tests/autonomous -q`

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/enums.py api/app/autonomous/guard.py api/app/autonomous/cost.py api/tests/autonomous/test_retrieve_authority.py
git commit -s -m "feat(autonomous): retrieve_authority intent + governed GovInfo dispatch (WS-E PR1a)"
```

---

### Task 6: Planner integration — allowlist, arg-validation, evidence kind

**Files:**
- Modify: `api/app/autonomous/planner.py` (`PLANNER_ALLOWLIST`, `validate_action_args`, `collect_evidence`, `build_planner_messages` minimal source-awareness)
- Test: `api/tests/autonomous/test_planner_authority.py` (new)

**Interfaces:**
- Consumes: `resolve_available_sources` (Task 3), `retrieve_authority` (Task 5).
- Produces: `retrieve_authority` ∈ `PLANNER_ALLOWLIST`; `validate_action_args(ToolIntent.retrieve_authority, args)` raises `ValueError` on missing/wrong-typed `source`/`op`/`args` (the WS-D non-fatal-observation boundary); `collect_evidence` emits `EvidenceItem(kind="authority", ref=external_ref, content=fetched_text, ...)` for a `retrieve_authority` result; `build_planner_messages` lists the available source names/types (minimal, P3) so the planner can choose.

- [ ] **Step 1: Write the failing tests** (`test_planner_authority.py`): `retrieve_authority` in `PLANNER_ALLOWLIST`; `validate_action_args` accepts `{"source":"govinfo","op":"search_authority","args":{"collection":"USCODE","query":"x"}}` and raises on `{"source":"govinfo"}` (missing op), `{"op":"search_authority"}` (missing source), non-dict args, non-str source/op; `collect_evidence(ToolIntent.retrieve_authority, result, start_n)` yields a `kind="authority"` item with the external_ref + text.

- [ ] **Step 2: Run — expect failure.**

- [ ] **Step 3: Implement.** Add to `PLANNER_ALLOWLIST`; extend `validate_action_args` with a `retrieve_authority` branch (type-check source/op/args; do NOT hit the DB/gateway here — the handler does the registry-enabled check; this is the cheap structural guard); extend `collect_evidence` with a `retrieve_authority` branch (read the `ToolResult.data["authority"]`); add the available-source list to `build_planner_messages` (names + jurisdiction + coverage only — minimal source-awareness; richer matching is PR2).

- [ ] **Step 4: Run — expect pass + autonomous suite (SOLO).**

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/planner.py api/tests/autonomous/test_planner_authority.py
git commit -s -m "feat(autonomous): planner retrieve_authority allowlist + validation + evidence (WS-E PR1a)"
```

---

### Task 7: DE-344 — per-provider external-tool cost model

**Files:**
- Modify: `api/app/tools/governance.py` (cache `cost_per_call`/`cost_per_unit` alongside provider tier)
- Modify: `api/app/autonomous/cost.py` (`estimate_tool_cost` returns the configured rate for external intents)
- Test: `api/tests/autonomous/test_external_tool_cost.py` (new)

**Interfaces:**
- Produces: `resolve_provider_cost(provider) -> Decimal` (configured `cost_per_call`, default `Decimal("0")`, cached like the tier); `estimate_tool_cost(retrieve_authority|retrieve_caselaw|call_mcp_tool, params, db)` returns the per-provider rate; realized cost recorded on `tool_call_log.cost_usd` via the handler's `ToolResult.cost_usd`.

- [ ] **Step 1: Write the failing tests** (`test_external_tool_cost.py`): with a provider config carrying `cost_per_call: 0.05`, `estimate_tool_cost(retrieve_authority, {"source": <that provider>, ...}, db)` returns `Decimal("0.05")`; a free provider (no field) returns `Decimal("0")`; assert R4 would project the cost (cost flows into `guarded_tool_call`'s projected total). Stub the gateway `/admin/v1/config` to carry the cost field.

- [ ] **Step 2: Run — expect failure** (currently returns 0 for all external).

- [ ] **Step 3: Implement.** In `governance.py`, extend the provider-config cache loader (the one feeding `resolve_provider_tier`, ~line 98) to also capture `cost_per_call`/`cost_per_unit` from each `tool_providers` entry (`entry.get("cost_per_call")`); add `resolve_provider_cost(provider_name) -> Decimal`. In `cost.py` `estimate_tool_cost`, for the external intents, resolve the provider (caselaw → research provider; retrieve_authority → `params["source"]`'s provider; call_mcp_tool → `params["provider"]`) and return `resolve_provider_cost(provider)` (default 0). Ensure the handler's `ToolResult.cost_usd` carries the realized cost (the configured rate, or a gateway-reported cost if the payload includes one) so `governed_tool_invocation` records it on `tool_call_log`.

- [ ] **Step 4: Run — expect pass + autonomous suite (SOLO).**

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/tools/governance.py api/app/autonomous/cost.py api/tests/autonomous/test_external_tool_cost.py
git commit -s -m "feat(governance): DE-344 per-provider external-tool cost model (WS-E PR1a)"
```

---

## Final gate (before requesting review — CI scope, repo root, SOLO suite)

- [ ] **api full gates:**
```bash
cd /Users/kevinkeller/Code/lq-ai
api/.venv/bin/ruff check api scripts && api/.venv/bin/ruff format --check api scripts
cd api && .venv/bin/mypy app
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest -q   # SOLO (DE-368)
```
- [ ] **gateway full gates:** `cd gateway && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app --strict && .venv/bin/python -m pytest -q`
- [ ] **No migration in PR1a** (0064 is reserved for PR1b). Confirm no alembic version added.
- [ ] **PRD bookkeeping:** mark DE-344 status (cost model wired for external intents; realized-cost-from-response parsing follows on a source that reports it). No new DE unless one surfaces.
- [ ] **Opus whole-branch review** (SDD final) — required; it has caught a real gate-passing defect on every slice this milestone. Hunt: SSRF/allowlist correctness on the new adapter; bad-arg/disabled-source → non-fatal observation (no poison); P3 (no secrets in /sources or planner context); cost-cache staleness; egress-tier enforcement for govinfo.
- [ ] **Push origin + tucuxi → security-gated PR (NO self-merge) → mirror after merge.**

## Plan self-review (completed)
- **Spec coverage:** C1 gateway adapter → Tasks 1-2; C2 registry → Task 3; `GET /research/sources` → Task 4; C3 intent+handler → Task 5; planner integration → Task 6; C4 backend adapter → Task 3; C5 DE-344 cost → Task 7. C6 (verify+ledger, mech-B, migration 0064) is **PR1b** — out of scope here (fetched authority is provenance-only in PR1a).
- **Placeholder scan:** real code/commands throughout. Task 2 Step 1 (confirm live GovInfo endpoint shapes) and Task 4 (grep the research router) are explicit verify-against-reality steps, not logic placeholders — the asserted contract (normalized op output; safe `/sources` shape) is fixed.
- **Type consistency:** `SourceSpec`/`AvailableSource`/`FetchedAuthority(citable_text,label,subtitle,url,external_ref,content_kind)`, `resolve_available_sources(gateway)`, `ToolIntent.retrieve_authority` with `{source,op,args}`, `EvidenceItem(kind="authority")`, `resolve_provider_cost(provider)->Decimal` are consistent across Tasks 1-7.
