# WS-E PR2b — EUR-Lex authority source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add EUR-Lex (EU legislation + CJEU case law) as the third free authority source — retrieve-and-verify by CELEX id — on the generic ADR-0021 registry + `retrieve_authority` + verify path.

**Architecture:** A new gateway `EurLexToolAdapter` fetches document text from the EU Cellar service by CELEX via content-negotiation (User-Agent auth, no key), following the 303 redirect to the manifestation with per-hop SSRF validation and an http→https upgrade. A backend `EurLexAdapter` + `SOURCE_REGISTRY["eurlex"]` entry (`ops=("get_authority",)`) plug into the registry-driven chat/autonomous wiring PR2a generalized. The chat tool schemas are refined to per-op so a get-only source is exposed honestly. `sec_filing`-style verify wiring gains the `eu_*` content kinds.

**Tech Stack:** Python 3.12, httpx (async), FastAPI, SQLAlchemy, pytest. Gateway (`gateway/`) + api (`api/`).

## Global Constraints

Copied from the spec — every task implicitly includes these:

- **No new ADR** (ADR 0021 D6 scopes EUR-Lex). **No migration** — reuses `message_authority_citations` + `authority_text_cache` (mig 0064); `content_kind` is free Text.
- **`gate.py`, `ledger.py`, `alembic/**` untouched** — provable via `git diff --name-only main..HEAD`.
- **Reuse / never bypass:** every EUR-Lex call goes through `guarded_tool_call` → R5/R6/R4 → `governed_tool_invocation` → gateway.
- **EUR-Lex auth = descriptive `User-Agent`, NO API key.** Host allowlist `[publications.europa.eu]`. `skip_anonymization=True`. `read_only=True`. Free → no `cost_per_call` → R4 no-op.
- **`external_ref` = the plain CELEX**, validated against `^[A-Za-z0-9._-]+$` (the `authority_text_cache` key charset). Unsafe CELEX (treaty/corrigendum with `/`,`()`) rejected at the gateway with a 400 before egress (DE-375).
- **`get_authority` only** — `ops=("get_authority",)`. No `search_authority` (DE-374).
- **content-kind taxonomy** parsed from the CELEX descriptor: `eu_regulation` (sector 3, type R), `eu_directive` (3, L), `eu_decision` (3, D), `eu_caselaw` (sector 6), fallback `eu_legislation`. All added to `_VERIFIABLE_CONTENT_KINDS`.
- **Egress is https-only** (`validate_egress_target` refuses non-https). The Cellar 303 target is http → the adapter upgrades it to https before validating/fetching. **Every URL actually fetched is validated (host allowlist + public-IP) and https.**
- **Per-op chat schemas** — behavior-preserving for GovInfo/EDGAR (both support both ops).
- **Security-gated** (gateway egress + citation surface + shared chat schema) → Kevin/security merges, NO self-merge; mirror `origin`→`tucuxi` after.
- **Gates (repo ROOT, CI scope):** full DB-backed SOLO api suite with `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test` (the real gate; unset = hollow skip-green); `ruff check` + `ruff format --check api scripts`; `mypy app`; gateway suite + `mypy --strict` + `ruff format --check gateway`. Never run concurrent pytest against the shared DB (DE-368).

### Verified live EUR-Lex shapes (2026-07-01 — use in adapter + fixtures)
- `GET https://publications.europa.eu/resource/celex/{CELEX}` + `Accept: application/xhtml+xml` + `Accept-Language: eng` + `User-Agent: <descriptive>` → **303**, `Location: http://publications.europa.eu/resource/cellar/<uuid>/DOC_n`.
- Upgrading that Location to **https** and GETting it → **200 `application/xhtml+xml;charset=UTF-8`** (GDPR `32016R0679` ~806 KB; directive `32011L0083` ~299 KB; caselaw `62014CJ0362` ~205 KB). Nonexistent CELEX (`99999X9999`) → **404**. Omitting `Accept-Language` → **404**.
- CELEX types verified: `32016R0679`→regulation (sector 3, R), `32011L0083`→directive (3, L), `62014CJ0362`→caselaw (sector 6, CJ).

---

## Task 1: Gateway `EurLexToolAdapter`

**Files:**
- Modify: `gateway/app/config.py` (`ToolProviderType` — add `"eurlex"`)
- Create: `gateway/app/providers/tool/eurlex.py`
- Modify: `gateway/app/providers/tool/__init__.py` (export)
- Modify: `gateway/app/main.py` (`build_tool_adapter` dispatch + import)
- Test: `gateway/tests/test_eurlex_adapter.py` (create)

**Interfaces:**
- Consumes: `ToolProviderAdapter` base + error types + `ToolResult`/`ToolSpec` (mirror `gateway/app/providers/tool/edgar.py`), `validate_egress_target` (`gateway/app/providers/tool/egress.py`), the existing `user_agent` field on `ToolProviderConfig`.
- Produces: `EurLexToolAdapter.from_config(provider)`, `.list_tools()` (only `get_authority`), `.invoke_tool("get_authority", {"external_ref": <celex>})` → `ToolResult` with `.payload = {"external_ref": str, "title": str, "url": str, "text": str, "content_kind": str}`.

- [ ] **Step 1: Write failing tests**

Create `gateway/tests/test_eurlex_adapter.py` (mirror `test_edgar_adapter.py` structure — `respx` mocks, `@pytest.mark.unit`):
```python
import httpx
import pytest
import respx

from gateway.app.config import ToolProviderConfig
from gateway.app.providers.tool.eurlex import EurLexToolAdapter, _content_kind_from_celex


def _adapter(monkeypatch=None):
    return EurLexToolAdapter.from_config(
        ToolProviderConfig(
            name="eurlex-prod", type="eurlex", base_url="https://publications.europa.eu",
            egress_tier=4, allowlist={"hosts": ["publications.europa.eu"]},
            user_agent="LQ.AI test ops@lq.ai",
        )
    )


@pytest.mark.unit
def test_from_config_requires_user_agent_no_key():
    with pytest.raises(ValueError, match="user_agent"):
        EurLexToolAdapter.from_config(
            ToolProviderConfig(name="e", type="eurlex", base_url="https://publications.europa.eu",
                               egress_tier=4, allowlist={"hosts": ["publications.europa.eu"]})
        )


@pytest.mark.unit
@pytest.mark.parametrize("celex,kind", [
    ("32016R0679", "eu_regulation"),
    ("32011L0083", "eu_directive"),
    ("32014D0123", "eu_decision"),
    ("62014CJ0362", "eu_caselaw"),
    ("12016E", "eu_legislation"),       # sector 1 treaty-ish → fallback
    ("garbage", "eu_legislation"),      # unparseable → fallback
])
def test_content_kind_from_celex(celex, kind):
    assert _content_kind_from_celex(celex) == kind


@pytest.mark.unit
def test_list_tools_only_get_authority():
    tools = _adapter().list_tools()
    assert [t.name for t in tools] == ["get_authority"]
    assert all(t.read_only for t in tools)


@pytest.mark.unit
async def test_get_authority_follows_redirect_upgrades_https_strips_html():
    adapter = _adapter()
    celex_url = "https://publications.europa.eu/resource/celex/32016R0679"
    doc_http = "http://publications.europa.eu/resource/cellar/abc/DOC_1"   # 303 target is http
    doc_https = "https://publications.europa.eu/resource/cellar/abc/DOC_1"
    with respx.mock:
        respx.get(celex_url).mock(
            return_value=httpx.Response(303, headers={"location": doc_http})
        )
        doc_route = respx.get(doc_https).mock(
            return_value=httpx.Response(200, text="<html><body>Article 6  lawful</body></html>")
        )
        out = await adapter.invoke_tool("get_authority", {"external_ref": "32016R0679"}, request_id="r1")
    assert doc_route.called                          # fetched the HTTPS-upgraded manifestation
    assert out.payload["text"] == "Article 6 lawful"  # tag-stripped, whitespace-collapsed
    assert out.payload["content_kind"] == "eu_regulation"
    assert out.payload["external_ref"] == "32016R0679"
    assert out.skip_anonymization is True
    # Accept-Language + User-Agent sent on the first request
    req = respx.calls[0].request
    assert req.headers["accept-language"] == "eng"
    assert req.headers["user-agent"] == "LQ.AI test ops@lq.ai"


@pytest.mark.unit
async def test_get_authority_rejects_unsafe_celex_before_egress():
    adapter = _adapter()
    with respx.mock:
        route = respx.get(url__regex=r".*").mock(return_value=httpx.Response(200, text="x"))
        for bad in ("12016E/TXT", "32016R0679R(01)"):
            with pytest.raises(Exception):  # ToolProviderInvalidRequestError, upstream_status=400
                await adapter.invoke_tool("get_authority", {"external_ref": bad}, request_id="r1")
        assert not route.called   # rejected before any egress


@pytest.mark.unit
async def test_get_authority_missing_celex_404_maps_error():
    adapter = _adapter()
    url = "https://publications.europa.eu/resource/celex/99999X9999"
    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(404))
        with pytest.raises(Exception):   # not-found → InvalidRequest/HTTP error mapping
            await adapter.invoke_tool("get_authority", {"external_ref": "99999X9999"}, request_id="r1")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd gateway && .venv/bin/python -m pytest tests/test_eurlex_adapter.py -q`
Expected: FAIL — `ModuleNotFoundError: gateway.app.providers.tool.eurlex`.

- [ ] **Step 3: Add `"eurlex"` to `ToolProviderType`** (`gateway/app/config.py`):
```python
ToolProviderType = Literal["echo", "courtlistener", "mcp", "govinfo", "edgar", "eurlex"]
```

- [ ] **Step 4: Implement `gateway/app/providers/tool/eurlex.py`**

Mirror `edgar.py` (match the real base class / error types / `ToolResult`/`ToolSpec` fields — read edgar.py first). Complete implementation:
```python
"""EUR-Lex tool adapter — retrieve EU legal documents by CELEX id.

Fetches from the EU Publications Office Cellar service via content-negotiation.
Auth = descriptive User-Agent (no key), same posture as EDGAR. Cellar 303-
redirects the /resource/celex/{CELEX} URL to a concrete manifestation whose
Location is http; egress policy is https-only, and the manifestation is served
over https too, so we upgrade the redirect target to https and re-validate every
hop against the allowlist before fetching. get_authority only (DE-374 = search).
"""
from __future__ import annotations

import re

import httpx

from gateway.app.config import ToolProviderConfig
from gateway.app.providers.tool.base import ToolProviderAdapter, ToolResult, ToolSpec
from gateway.app.providers.tool.egress import validate_egress_target
from gateway.app.providers.tool.errors import (  # match edgar.py's real imports
    ToolProviderAuthError,
    ToolProviderHTTPError,
    ToolProviderInvalidRequestError,
)

_SAFE_CELEX_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_CELEX_RE = re.compile(r"^(?P<sector>\d)(?P<year>\d{4})(?P<type>[A-Z]{1,2})")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_MAX_REDIRECTS = 5


def _content_kind_from_celex(celex: str) -> str:
    m = _CELEX_RE.match(celex)
    if not m:
        return "eu_legislation"
    sector, typ = m.group("sector"), m.group("type")
    if sector == "6":
        return "eu_caselaw"
    if sector == "3":
        if typ.startswith("R"):
            return "eu_regulation"
        if typ.startswith("L"):
            return "eu_directive"
        if typ.startswith("D"):
            return "eu_decision"
    return "eu_legislation"


def _force_https(url: str) -> str:
    parsed = httpx.URL(url)
    return str(parsed.copy_with(scheme="https")) if parsed.scheme == "http" else url


class EurLexToolAdapter(ToolProviderAdapter):
    def __init__(self, name, base_url, user_agent, allowlist, client=None):
        self._name = name
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._allowlist = allowlist
        # follow_redirects=False: we follow manually so every hop is validated.
        self._client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)

    @classmethod
    def from_config(cls, provider: ToolProviderConfig) -> "EurLexToolAdapter":
        assert provider.type == "eurlex"
        if not provider.user_agent:
            raise ValueError("eurlex provider requires a descriptive user_agent")
        return cls(
            name=provider.name,
            base_url=provider.base_url,
            user_agent=provider.user_agent,
            allowlist=list((provider.allowlist or {}).get("hosts", [])),
        )

    def validate_base_url(self) -> None:
        validate_egress_target(self._base_url, allowlist=self._allowlist)

    def list_tools(self, *, user_token=None) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="get_authority",
                description=(
                    "Retrieve the full text of an EU legal document (regulation, "
                    "directive, decision, or CJEU judgment) from EUR-Lex by its "
                    "CELEX id (e.g. 32016R0679 = GDPR). No keyword search — provide a CELEX."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "external_ref": {"type": "string", "description": "CELEX id, e.g. 32016R0679"}
                    },
                    "required": ["external_ref"],
                },
                read_only=True,
            )
        ]

    async def invoke_tool(self, tool, args, *, request_id, user_token=None) -> ToolResult:
        if tool == "get_authority":
            return await self._get_authority(args)
        raise ToolProviderInvalidRequestError(f"unknown eurlex tool: {tool}", upstream_status=400)

    async def _get_authority(self, args: dict) -> ToolResult:
        celex = (args or {}).get("external_ref") or ""
        if not celex:
            raise ToolProviderInvalidRequestError(
                "get_authority requires 'external_ref' (a CELEX id)", upstream_status=400
            )
        if not _SAFE_CELEX_RE.match(celex):
            raise ToolProviderInvalidRequestError(
                f"unsupported CELEX {celex!r}: treaty/corrigendum ids with '/' or '()' "
                "are not yet supported (DE-375)",
                upstream_status=400,
            )
        start = f"{self._base_url}/resource/celex/{celex}"
        resp = await self._fetch_following_redirects(start)
        text = _WS_RE.sub(" ", _TAG_RE.sub(" ", resp.text)).strip()
        payload = {
            "external_ref": celex,
            "title": celex,
            "url": f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
            "text": text,
            "content_kind": _content_kind_from_celex(celex),
        }
        return self._result("get_authority", payload, resp)

    async def _fetch_following_redirects(self, url: str) -> httpx.Response:
        headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/xhtml+xml",
            "Accept-Language": "eng",
        }
        current = url
        for _ in range(_MAX_REDIRECTS):
            current = _force_https(current)               # Cellar 303 targets are http
            validate_egress_target(current, allowlist=self._allowlist)   # per-hop SSRF + https
            resp = await self._client.get(current, headers=headers)
            if resp.is_redirect:
                loc = resp.headers.get("location")
                if not loc:
                    break
                current = str(resp.url.join(loc))
                continue
            if resp.status_code in (401, 403):
                raise ToolProviderAuthError(f"eurlex auth failed: {resp.status_code}")
            if 400 <= resp.status_code < 500:
                raise ToolProviderInvalidRequestError(
                    f"eurlex {resp.status_code} for {url}", upstream_status=resp.status_code
                )
            if resp.status_code >= 500:
                raise ToolProviderHTTPError(f"eurlex {resp.status_code}")
            return resp
        raise ToolProviderHTTPError("eurlex: too many redirects")

    def _result(self, tool: str, payload: dict, resp: httpx.Response) -> ToolResult:
        return ToolResult(
            provider=self._name,
            tool=tool,
            payload=payload,
            bytes_out=len(resp.request.content or b""),
            bytes_in=len(resp.content or b""),
            skip_anonymization=True,
        )

    async def health_check(self):
        return True

    async def aclose(self) -> None:
        await self._client.aclose()
```
> Match the exact base method signatures / error class names / `ToolResult`/`ToolSpec` fields / `health_check` return type to the real `edgar.py` + `base.py` (e.g. `ProviderHealth`). The brief's error imports are illustrative — use whatever `edgar.py` imports.

- [ ] **Step 5: Register the adapter**

`gateway/app/providers/tool/__init__.py` — import `EurLexToolAdapter` + add to `__all__`.
`gateway/app/main.py` — import it (near the edgar import) and add to `build_tool_adapter`:
```python
    if provider.type == "eurlex":
        adapter = EurLexToolAdapter.from_config(provider)
        adapter.validate_base_url()
        return adapter
```

- [ ] **Step 6: Run tests + gateway gates**

Run: `cd gateway && .venv/bin/python -m pytest tests/test_eurlex_adapter.py -q` → PASS.
Then: `cd gateway && ruff format --check . && ruff check . && .venv/bin/python -m mypy --strict app && .venv/bin/python -m pytest -q` → all green.

- [ ] **Step 7: Commit**
```bash
git add gateway/app/config.py gateway/app/providers/tool/eurlex.py \
        gateway/app/providers/tool/__init__.py gateway/app/main.py \
        gateway/tests/test_eurlex_adapter.py
git commit -s -m "feat(gateway): EUR-Lex tool adapter (get_authority by CELEX)

Cellar content-negotiation; User-Agent auth (no key); follows the 303 to the
manifestation, upgrading http->https and re-validating each hop against the
allowlist; rejects unsafe (treaty/corrigendum) CELEX before egress. Refs DE-374, DE-375"
```

---

## Task 2: Backend `EurLexAdapter` + registry entry

**Files:**
- Modify: `api/app/research/adapters.py` (add `EurLexAdapter`)
- Modify: `api/app/research/registry.py` (add `SOURCE_REGISTRY["eurlex"]`)
- Test: `api/tests/research/test_adapters.py` + `api/tests/test_source_registry.py` (append; match the real test file locations used by EDGAR — confirm from the repo)

**Interfaces:**
- Consumes: `FetchedAuthority` + `SourceAdapter` protocol (`adapters.py`), `SourceSpec` (`registry.py`).
- Produces: `EurLexAdapter().from_response(op, payload) -> FetchedAuthority`; `SOURCE_REGISTRY["eurlex"]` with `content_kinds=("eu_regulation","eu_directive","eu_decision","eu_caselaw","eu_legislation")`, `ops=("get_authority",)`.

- [ ] **Step 1: Write failing test** (append to the EDGAR adapter test file):
```python
from app.research.adapters import EurLexAdapter


def test_eurlex_get_authority_maps_to_fetched_authority():
    payload = {"external_ref": "32016R0679", "title": "32016R0679",
               "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679",
               "text": "Article 6 lawfulness of processing ...", "content_kind": "eu_regulation"}
    fa = EurLexAdapter().from_response("get_authority", payload)
    assert fa.content_kind == "eu_regulation"
    assert fa.external_ref == "32016R0679"
    assert fa.citable_text.startswith("Article 6")
    assert "CELEX:32016R0679" in fa.url
```

- [ ] **Step 2: Run → fail** (`ImportError: EurLexAdapter`).
Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/research/test_adapters.py -q -k eurlex`

- [ ] **Step 3: Implement `EurLexAdapter`** (`api/app/research/adapters.py`, mirror `EdgarAdapter` — thin carry-through since the gateway derives content_kind):
```python
class EurLexAdapter:
    """Normalizes gateway EUR-Lex payloads into FetchedAuthority. content_kind is
    derived from the CELEX descriptor by the gateway adapter and carried through."""

    def from_response(self, op: str, payload: dict) -> FetchedAuthority:
        if op == "get_authority":
            return FetchedAuthority(
                citable_text=payload.get("text", ""),
                label=payload.get("title", ""),
                subtitle=payload.get("content_kind"),
                url=payload.get("url"),
                external_ref=payload.get("external_ref", ""),
                content_kind=payload.get("content_kind", "eu_legislation"),
            )
        raise ValueError(f"unsupported eurlex op: {op}")
```
> Match `FetchedAuthority`'s real fields/order (`citable_text, label, subtitle, url, external_ref, content_kind`).

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Add registry entry + test.** In `registry.py` import `EurLexAdapter`, add after the `"edgar"` entry:
```python
    "eurlex": SourceSpec(
        type="eurlex",
        jurisdiction="eu",
        coverage="EU legislation & CJEU case law via EUR-Lex/Cellar — retrieve by CELEX id",
        content_kinds=("eu_regulation", "eu_directive", "eu_decision", "eu_caselaw", "eu_legislation"),
        ops=("get_authority",),
        adapter=EurLexAdapter(),
    ),
```
Append to `api/tests/test_source_registry.py`:
```python
def test_eurlex_registered_get_only():
    spec = SOURCE_REGISTRY["eurlex"]
    assert spec.type == "eurlex"
    assert spec.ops == ("get_authority",)
    assert "eu_regulation" in spec.content_kinds
    assert spec.adapter is not None
```

- [ ] **Step 6: Run registry test → pass.**

- [ ] **Step 7: Commit**
```bash
git add api/app/research/adapters.py api/app/research/registry.py \
        api/tests/research/test_adapters.py api/tests/test_source_registry.py
git commit -s -m "feat(research): EurLexAdapter + SOURCE_REGISTRY eurlex entry (get-only). Refs DE-374"
```

---

## Task 3: Per-op chat tool schemas (honest get-only exposure)

**Files:**
- Modify: `api/app/chat/tool_schemas.py` (`build_authority_tool_schemas` / `assemble_allowlist`)
- Test: `api/tests/chat/test_tool_schemas.py` (append)

**Interfaces:**
- Consumes: `SOURCE_REGISTRY`, `AUTHORITY_OPS`, the current `build_authority_tool_schemas` / `assemble_allowlist`.
- Produces: authority tool schemas where each op's `source` enum contains only sources whose registry `ops` include that op. A tool with an empty enum is omitted.

- [ ] **Step 1: Read the current implementation.** Read `api/app/chat/tool_schemas.py` `build_authority_tool_schemas` and `assemble_allowlist` (from PR2a). Determine whether the `source` enum is currently built ONCE and shared across both `search_authority` and `get_authority` (assuming all authority sources support both ops).

- [ ] **Step 2: Write the failing test** (append to `api/tests/chat/test_tool_schemas.py`):
```python
def test_authority_source_enum_is_per_op():
    # govinfo+edgar support both ops; eurlex supports only get_authority.
    schemas = build_authority_tool_schemas(
        enabled_sources=["govinfo", "edgar", "eurlex"]
    )
    by_name = {s["name"]: s for s in schemas}
    assert set(by_name["get_authority"]["parameters"]["properties"]["source"]["enum"]) == {
        "govinfo", "edgar", "eurlex"
    }
    assert set(by_name["search_authority"]["parameters"]["properties"]["source"]["enum"]) == {
        "govinfo", "edgar"
    }


def test_authority_search_omitted_when_no_search_source():
    # only a get-only source enabled → no search_authority tool at all
    schemas = build_authority_tool_schemas(enabled_sources=["eurlex"])
    assert [s["name"] for s in schemas] == ["get_authority"]
```

- [ ] **Step 3: Run → fail** (shared enum includes eurlex under search, or signature mismatch).
Run: `cd api && DATABASE_URL=...lqai_test .venv/bin/python -m pytest tests/chat/test_tool_schemas.py -q -k per_op`

- [ ] **Step 4: Refactor `build_authority_tool_schemas` to per-op.** Compute each op's source list by intersecting the op against each source's `SOURCE_REGISTRY[src].ops`; build the tool for an op only if ≥1 source supports it; set that tool's `source` enum to the op-specific list. Concrete shape (adapt to the real current code):
```python
def build_authority_tool_schemas(enabled_sources: list[str]) -> list[dict]:
    if not enabled_sources:
        return []
    def _sources_for(op: str) -> list[str]:
        return [s for s in enabled_sources if op in SOURCE_REGISTRY[s].ops]
    schemas: list[dict] = []
    search_sources = _sources_for("search_authority")
    if search_sources:
        schemas.append(_search_schema(search_sources))   # source enum = search_sources
    get_sources = _sources_for("get_authority")
    if get_sources:
        schemas.append(_get_schema(get_sources))          # source enum = get_sources
    return schemas
```
Keep `assemble_allowlist`'s existing enabled-authority derivation; it already computes the enabled authority source types — pass them in and let the per-op split happen here. GovInfo/EDGAR (both ops) are unaffected.

- [ ] **Step 5: Run the new tests + the pre-existing authority-schema tests → all pass** (GovInfo/EDGAR behavior unchanged).
Run: `cd api && DATABASE_URL=...lqai_test .venv/bin/python -m pytest tests/chat/test_tool_schemas.py -q`

- [ ] **Step 6: Commit**
```bash
git add api/app/chat/tool_schemas.py api/tests/chat/test_tool_schemas.py
git commit -s -m "feat(chat): per-op authority source enums (honest get-only sources)

A source appears under search_authority/get_authority only if its registry ops
include that op; a get-only source (EUR-Lex) exposes only get_authority. GovInfo/
EDGAR unchanged. Refs DE-374"
```

---

## Task 4: Verify content-kind set (eu_* kinds)

**Files:**
- Modify: `api/app/citation/authority.py` (`_VERIFIABLE_CONTENT_KINDS`)
- Test: `api/tests/citation/test_authority_verify.py` (append)

**Interfaces:** Consumes `verify_and_persist_authority_citations`. Produces: `eu_*` kinds are verifiable.

- [ ] **Step 1: Write failing test** — mirror the existing `sec_filing` verify test with `content_kind="eu_regulation"` and a cached EUR-Lex body; assert a `MessageAuthorityCitation` row with `content_kind="eu_regulation"`, `verified=True`, `verification_method="exact_match"`. (Reuse the harness; swap the kind + body.)

- [ ] **Step 2: Run → fail** (ref filtered out → 0 rows).
Run: `cd api && DATABASE_URL=...lqai_test .venv/bin/python -m pytest tests/citation/test_authority_verify.py -q -k eu_regulation`

- [ ] **Step 3: Extend the set** (`api/app/citation/authority.py`):
```python
    _VERIFIABLE_CONTENT_KINDS = {
        "statute", "regulation", "sec_filing",
        "eu_regulation", "eu_directive", "eu_decision", "eu_caselaw", "eu_legislation",
    }
```
Update the adjacent comment (EUR-Lex now covered; DE-375 treaty/corrigendum still pending).

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Commit**
```bash
git add api/app/citation/authority.py api/tests/citation/test_authority_verify.py
git commit -s -m "feat(citation): verify EUR-Lex (eu_*) content kinds. Refs DE-374"
```

---

## Task 5: `gateway.yaml.example` + PRD docs

**Files:**
- Modify: `gateway.yaml.example` (commented `eurlex-prod` block after the edgar block)
- Modify: `docs/PRD.md` (WS-E status; file DE-374, DE-375)

- [ ] **Step 1: Add the provider block** (`gateway.yaml.example`, mirror the edgar block):
```yaml
#   - name: eurlex-prod
#     type: eurlex                 # shipped in WS-E PR2b; uncomment to enable
#     base_url: https://publications.europa.eu    # EU Cellar (content-negotiation by CELEX)
#     user_agent: "YourOrg legal-ops@yourorg.example"   # descriptive UA — REQUIRED, no API key
#     egress_tier: 4               # public EU legal text (ADR 0014 D4)
#     allowlist:
#       hosts: [publications.europa.eu]
#     rate_limit:
#       requests_per_minute: 60
#     anonymize_outbound: false    # public legal text; skip_anonymization=True on results
#     # (no api_key_env — EUR-Lex Cellar needs only a User-Agent)
#     # (no cost_per_call — free source; R4 stays a no-op)
```

- [ ] **Step 2: Update PRD** — mark WS-E EUR-Lex shipped (PR2b), completing WS-E PR2's ≥2-free-sources goal (GovInfo + EDGAR + EUR-Lex = three); note get-only + English + safe-CELEX scope. Add two DE entries in §9 (after DE-373), matching the existing DE format:
  - **DE-374 — EUR-Lex full-text search via Cellar SPARQL** (the deferred `search_authority`; structured metadata query surface).
  - **DE-375 — EUR-Lex treaty/corrigendum CELEX support** (reversible `external_ref` encoding for `/`,`()`).

- [ ] **Step 3: Commit**
```bash
git add gateway.yaml.example docs/PRD.md
git commit -s -m "docs(WS-E): EUR-Lex gateway.yaml example + PRD status; file DE-374, DE-375"
```

---

## Final gates (before PR)

- [ ] **Prove untouched:** `git diff --name-only main..HEAD` shows NO `api/app/citation/gate.py`, `api/app/citation/ledger.py`, `api/alembic/**`.
- [ ] **api full DB-backed SOLO suite:** `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest -p no:randomly -q` → all pass / 1 skip (NOT a hollow skip-green).
- [ ] **api static (root):** `ruff check api scripts && ruff format --check api scripts && (cd api && .venv/bin/python -m mypy app)`
- [ ] **gateway:** `cd gateway && ruff format --check . && ruff check . && .venv/bin/python -m mypy --strict app && .venv/bin/python -m pytest -q`
- [ ] **No new route** → `test_openapi`/`test_endpoints` path counts unchanged; **DE-373 drift-guard `test_openapi_export` stays green** (no route/schema change).
- [ ] **Opus whole-branch review** → fix Critical/Important → re-review; record Minors.
- [ ] **Ship:** push `origin` + `tucuxi`, open the security-gated PR (Kevin/security merges, NO self-merge), watch CI, mirror `origin`→`tucuxi`, delete branch.

---

## Self-review notes (plan ↔ spec)

- **Spec coverage:** §4 gateway adapter → Task 1 (incl. redirect+https-upgrade+per-hop SSRF, unsafe-CELEX reject, CELEX→content_kind); §5 backend adapter+registry → Task 2; §6 per-op schemas → Task 3; §7 verify set → Task 4; §8 config/docs+DEs → Task 5; §9 testing folded into each task + Final gates; §2 invariants → Global Constraints + `git diff` proof.
- **Placeholder scan:** Task 3's refactor code is "adapt to the real current signature" (concrete target behavior + tests given) — the only signature-dependent spot, unavoidable without the current file inline. All other code is complete.
- **Type consistency:** `_content_kind_from_celex`, `EurLexToolAdapter.get_authority` payload keys (`external_ref/title/url/text/content_kind`) → consumed by `EurLexAdapter.from_response`; `ops=("get_authority",)` consistent across gateway `list_tools`, registry, and the per-op schema logic; `eu_*` kinds identical in registry `content_kinds`, `_content_kind_from_celex` outputs, and `_VERIFIABLE_CONTENT_KINDS`.
