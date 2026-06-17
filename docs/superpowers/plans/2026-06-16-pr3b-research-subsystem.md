# PR3b — API research subsystem (WS3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship the user-facing case-law research surface: five `/api/v1/research/*` endpoints that call the gateway CourtListener tool-provider (through the PR3a `POST /v1/tools/...` transport), with persistent read-through caching of fetched opinions (object storage + DB metadata + live-API fallback) and stdlib HTML→plaintext extraction for `find_in_case` / `read_case`.

**Architecture:** `GatewayClient.call_tool` (new) → `app/research/service.py` (orchestration + caching) → `app/api/research.py` (5 REST handlers). `verify-citations` and `search` are stateless pass-throughs. `GET /clusters/{id}` (get_cases) is read-through cached: opinion plaintext → object storage (`courtlistener/opinions/by-cluster/{cluster_id}/{opinion_id}`), cluster+opinion metadata → DB (migration 0049). `find_in_case` and `read_case` operate ONLY on already-cached opinions (404 if a cluster wasn't fetched first — matching MikeOSS's "fetched-cluster" semantics). The backend never calls CourtListener directly — every call goes through the gateway boundary (ADR 0014).

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async, httpx, pytest + pytest-asyncio + **respx** (mock the gateway HTTP), Python stdlib `html.parser` (HTML→text — no new dependency). api mypy is standard mode.

**Branch:** `feat/research-api` (off `main` @ `b6c5c87`, which has PR1+PR2+PR3a). **api-only — no security review** (CLAUDE.md merge-gating: self-merge after CI green). The gateway transport it depends on (PR3a) is already merged.

## ⚠️ Test/lint runner (host venv + throwaway pg, NOT docker compose)
- api tests need a Postgres: a throwaway `pgvector` is on `:15433` (start if absent: `docker run -d --name lq-test-pg -p 15433:5432 -e POSTGRES_USER=lq_ai -e POSTGRES_PASSWORD=test -e POSTGRES_DB=lq_ai pgvector/pgvector:pg16`).
- Run: `cd ~/Code/lq-ai/api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest tests/X.py -v`
- Lint: `cd ~/Code/lq-ai/api && .venv/bin/ruff format . && .venv/bin/ruff check . && .venv/bin/mypy app`. CI runs `ruff format --check api scripts` — run `cd ~/Code/lq-ai && api/.venv/bin/ruff format --check api scripts` before pushing (the gate that bit PR1).
- **Object storage (MinIO) is NOT available in tests** — monkeypatch `app.storage.upload_bytes` / `app.storage.stream_download` in caching tests. **Gateway is NOT running in tests** — mock its HTTP with `respx` (api has `respx>=0.21`).
- NEVER host-side `alembic upgrade` the live dev DB; the test conftest migrates the throwaway DB.

## Confirmed patterns (verified 2026-06-16)
- `GatewayClient` (`api/app/clients/gateway.py`): per-method error flow — `_build_headers(request_id=...)`, POST via `self._client`, on `status_code >= 400` call `_raise_for_gateway_error(...)`, catch `httpx.TimeoutException`→`GatewayTimeout`, `httpx.HTTPError`→`GatewayUnreachable`. Process-global `get_gateway_client()`. No generic request helper — model `call_tool` on `list_models`.
- Routers: `api/app/api/__init__.py` has `api_router = APIRouter(prefix="/api/v1")`; authed routers added via `api_router.include_router(<mod>.router, dependencies=_active)` where `_active = [Depends(get_active_user)]`.
- Handlers: `async def h(payload: ReqSchema, user: ActiveUser, db: Annotated[AsyncSession, Depends(get_db)]) -> RespSchema`. Request schema `model_config = ConfigDict(extra="forbid")`; response `ConfigDict(from_attributes=True)`. Schemas in `api/app/schemas/`.
- Errors (`api/app/errors.py`): raise `NotFound` (404), `ValidationError` (400), `InternalError` (500); auto-enveloped by the app exception handler.
- DB: `get_db` in `api/app/db/session.py`; `await db.execute(select(Model).where(...))` → `.scalar_one_or_none()`. Models inherit `from app.db.base import Base`. Migration head `0048`; PR3b adds `0049`.
- Storage: `upload_bytes(*, storage_path, body: bytes, content_type)`; `stream_download(*, storage_path)` async ctx-mgr yielding an async byte-iterator.
- Collision guards: `EXPECTED_PATHS` in `api/tests/test_openapi.py` is **118**; PR3b adds 5 → **123**. `IMPLEMENTED_ROUTES` in `api/tests/test_endpoints.py` += the 5 routes.

## The five endpoints
| Method + path | Tool | Cached? |
|---|---|---|
| `POST /api/v1/research/verify-citations` | verify_citations | no (pass-through) |
| `POST /api/v1/research/search` | search_case_law | no (pass-through) |
| `GET /api/v1/research/clusters/{cluster_id}` | get_cases | **read-through** (storage + DB) |
| `POST /api/v1/research/find-in-case` | (cached text) | reads cache; 404 if not fetched |
| `GET /api/v1/research/opinions/{opinion_id}` | read_case (cached text) | reads cache; 404 if not fetched |

## Scope — NOT in PR3b (deferred)
- **Per-turn cluster cache** → PR5 (no "turn" in stateless REST handlers).
- **SSE case-law panel events + the web UI** → WS5/PR6.
- **Citation-engine grounding of fetched text** → WS5/PR6.
- **MCP** → PR4. **Chat tool-loop / ToolIntent** → PR5.

---

## Task 1: `GatewayClient.call_tool`

**Files:** Modify `api/app/clients/gateway.py`; Test `api/tests/test_gateway_call_tool.py`.

- [ ] **Step 1: Failing tests** (`api/tests/test_gateway_call_tool.py`):

```python
import httpx
import pytest
import respx

from app.clients.gateway import GatewayClient
from app.errors import NotFound, ValidationError

GW = "http://gw.test"


def _client() -> GatewayClient:
    return GatewayClient(base_url=GW, gateway_key="k")


@pytest.mark.asyncio
async def test_call_tool_happy_path() -> None:
    client = _client()
    payload = {"provider": "courtlistener-prod", "tool": "search_case_law",
               "payload": {"count": 0, "results": []}, "tier": 4}
    with respx.mock:
        route = respx.post(f"{GW}/v1/tools/courtlistener-prod/search_case_law").mock(
            return_value=httpx.Response(200, json=payload)
        )
        out = await client.call_tool("courtlistener-prod", "search_case_law", {"q": "x"})
    assert route.called
    assert route.calls.last.request.headers["X-LQ-AI-Gateway-Key"] == "k"
    import json as _json
    assert _json.loads(route.calls.last.request.content)["args"] == {"q": "x"}
    assert out["payload"]["count"] == 0


@pytest.mark.asyncio
async def test_call_tool_maps_gateway_invalid_request_to_validation_error() -> None:
    client = _client()
    with respx.mock:
        respx.post(f"{GW}/v1/tools/courtlistener-prod/verify_citations").mock(
            return_value=httpx.Response(
                400, json={"error": {"code": "invalid_request", "message": "bad", "details": {}}}
            )
        )
        with pytest.raises(ValidationError):
            await client.call_tool("courtlistener-prod", "verify_citations", {"text": ""})
```

(NOTE: confirm `map_gateway_error_code("invalid_request")` maps to `ValidationError`; if it maps elsewhere, adjust the test's expected exception to the real mapping and note it. The point is that a structured gateway 4xx envelope is parsed + mapped, reusing `_raise_for_gateway_error`.)

- [ ] **Step 2: Run, confirm fail** (`call_tool` missing).

- [ ] **Step 3: Add `call_tool`** to `GatewayClient` (model on `list_models`, lines ~618-685). Place near the other public methods:

```python
    async def call_tool(
        self,
        provider: str,
        tool: str,
        args: dict[str, Any],
        *,
        max_allowed_tier: int | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/tools/{provider}/{tool} on the gateway (ADR 0014 transport).

        Returns the gateway's ``{provider, tool, payload, tier}`` dict. Errors
        translate exactly like ``list_models``: timeout → GatewayTimeout,
        transport → GatewayUnreachable, structured 4xx → mapped LQAIError."""
        headers = self._build_headers(request_id=request_id)
        body: dict[str, Any] = {"args": args}
        if max_allowed_tier is not None:
            body["max_allowed_tier"] = max_allowed_tier
        op = f"call_tool:{provider}/{tool}"
        try:
            response = await self._client.post(
                f"/v1/tools/{provider}/{tool}", json=body, headers=headers
            )
        except httpx.TimeoutException as exc:
            raise GatewayTimeout(
                "Gateway did not respond within the configured timeout",
                details={"timeout_seconds": self._timeout},
            ) from exc
        except httpx.HTTPError as exc:
            raise GatewayUnreachable(
                "Could not reach the Inference Gateway",
                details={"transport_error": type(exc).__name__},
            ) from exc
        if response.status_code >= 400:
            self._raise_for_gateway_error(
                status_code=response.status_code,
                body_bytes=response.content,
                op=op,
                request_id=request_id,
            )
        try:
            payload: dict[str, Any] = response.json()
            return payload
        except json.JSONDecodeError as exc:
            raise GatewayInvalidResponse(
                "Gateway call_tool returned a non-JSON success response",
                details={"status_code": response.status_code},
            ) from exc
```

Ensure `Any` is imported (it is, used elsewhere). `json`, `GatewayTimeout`, `GatewayUnreachable`, `GatewayInvalidResponse` are already imported.

- [ ] **Step 4: Run tests** (pass). **Step 5: lint** (`ruff format`, `ruff check`, `mypy app` — clean). **Step 6: commit:**
```bash
cd ~/Code/lq-ai && git add api/app/clients/gateway.py api/tests/test_gateway_call_tool.py
git commit -s -m "feat(api): GatewayClient.call_tool — backend->gateway tool transport (WS3b)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: research metadata models + migration 0049

**Files:** Create `api/app/models/research.py`, `api/alembic/versions/0049_research_metadata.py`; modify `api/app/models/__init__.py`, `docs/db-schema.md`; Test `api/tests/test_research_models.py`.

- [ ] **Step 1: Failing test** (`api/tests/test_research_models.py`):

```python
import pytest

from app.models.research import ResearchClusterMetadata, ResearchOpinionMetadata


@pytest.mark.asyncio
async def test_research_metadata_roundtrips(db_session) -> None:
    cluster = ResearchClusterMetadata(
        cluster_id=2812209, case_name="Obergefell v. Hodges",
        court="scotus", date_filed="2015-06-26", absolute_url="/opinion/2812209/",
    )
    db_session.add(cluster)
    await db_session.flush()
    op = ResearchOpinionMetadata(
        opinion_id=3247759, cluster_id=2812209, text_field_used="html_with_citations",
        storage_path="courtlistener/opinions/by-cluster/2812209/3247759", char_length=1234,
    )
    db_session.add(op)
    await db_session.flush()
    assert op.opinion_id == 3247759
    assert cluster.case_name == "Obergefell v. Hodges"
```

(Match the marker style of `api/tests/test_tool_egress_log_model.py`.)

- [ ] **Step 2: Run, confirm ModuleNotFoundError.**

- [ ] **Step 3: Migration `api/alembic/versions/0049_research_metadata.py`** (revision "0049", down_revision "0048"):

```python
"""research metadata — cached CourtListener cluster + opinion metadata (WS3b)

Cluster/opinion metadata for fetched case law; opinion BODIES live in object
storage (storage_path), not here. Read-through cache for GET /research/
clusters/{id}; find_in_case/read_case read from these rows.

Revision ID: 0049
Revises: 0048
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_cluster_metadata",
        sa.Column("cluster_id", sa.BigInteger(), primary_key=True),
        sa.Column("case_name", sa.String(), nullable=True),
        sa.Column("court", sa.String(), nullable=True),
        sa.Column("date_filed", sa.String(), nullable=True),
        sa.Column("absolute_url", sa.String(), nullable=True),
        sa.Column(
            "cached_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "research_opinion_metadata",
        sa.Column("opinion_id", sa.BigInteger(), primary_key=True),
        sa.Column("cluster_id", sa.BigInteger(), nullable=False),
        sa.Column("text_field_used", sa.String(), nullable=True),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("char_length", sa.Integer(), nullable=False),
        sa.Column(
            "cached_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_research_opinion_metadata_cluster_id",
        "research_opinion_metadata", ["cluster_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_research_opinion_metadata_cluster_id", table_name="research_opinion_metadata")
    op.drop_table("research_opinion_metadata")
    op.drop_table("research_cluster_metadata")
```

(Confirm `0048` is the head first: `ls api/alembic/versions/ | sort | tail -1`.)

- [ ] **Step 4: Models `api/app/models/research.py`:**

```python
"""Cached CourtListener research metadata (WS3b).

Cluster + opinion metadata for fetched case law. Opinion BODIES (extracted
plaintext) live in object storage under ``storage_path``; only metadata is
here. Backs the read-through cache for GET /research/clusters/{id} and the
find_in_case/read_case reads. Schema authority: migration 0049."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResearchClusterMetadata(Base):
    __tablename__ = "research_cluster_metadata"

    cluster_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_name: Mapped[str | None] = mapped_column(String, nullable=True)
    court: Mapped[str | None] = mapped_column(String, nullable=True)
    date_filed: Mapped[str | None] = mapped_column(String, nullable=True)
    absolute_url: Mapped[str | None] = mapped_column(String, nullable=True)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ResearchOpinionMetadata(Base):
    __tablename__ = "research_opinion_metadata"

    opinion_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cluster_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    text_field_used: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    char_length: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
```

Register both in `api/app/models/__init__.py` (import + `__all__`, matching the file's pattern). Add a `research_cluster_metadata` + `research_opinion_metadata` section to `docs/db-schema.md`.

- [ ] **Step 5: Run the model test** (pass, throwaway pg). **Step 6: lint. Step 7: commit:**
```bash
cd ~/Code/lq-ai && git add api/app/models/research.py api/alembic/versions/0049_research_metadata.py api/app/models/__init__.py docs/db-schema.md api/tests/test_research_models.py
git commit -s -m "feat(api): research metadata tables (cluster + opinion) migration 0049 (WS3b)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: stdlib HTML→plaintext helper

**Files:** Create `api/app/research/__init__.py`, `api/app/research/html.py`; Test `api/tests/test_research_html.py`.

- [ ] **Step 1: Failing tests** (`api/tests/test_research_html.py`):

```python
import pytest

from app.research.html import html_to_text


@pytest.mark.parametrize(
    "html,expected_contains,expected_excludes",
    [
        ("<p>Held: the statute is <em>void</em>.</p>", "Held: the statute is void.", "<p>"),
        ("<div><p>One.</p><p>Two.</p></div>", "One.", "<div>"),
        ("<span class='citation'>347 U.S. 483</span> applies", "347 U.S. 483", "<span"),
        ("plain text already", "plain text already", "<"),
    ],
)
def test_html_to_text(html, expected_contains, expected_excludes) -> None:
    out = html_to_text(html)
    assert expected_contains in out
    assert expected_excludes not in out


def test_html_to_text_collapses_whitespace_and_keeps_paragraph_breaks() -> None:
    out = html_to_text("<p>One.</p>\n\n   <p>Two.</p>")
    assert "One." in out and "Two." in out
    assert "  " not in out  # runs of spaces collapsed


def test_html_to_text_handles_entities() -> None:
    assert "Smith & Jones" in html_to_text("<p>Smith &amp; Jones</p>")
```

- [ ] **Step 2: Run, confirm ModuleNotFoundError.**

- [ ] **Step 3: Implement** `api/app/research/__init__.py` (empty package marker with a one-line docstring) and `api/app/research/html.py`:

```python
"""Minimal HTML→plaintext for CourtListener opinion bodies (WS3b).

Court opinion HTML is simple (paragraphs, blockquotes, citation spans), so a
stdlib ``html.parser`` tag-stripper suffices — no DOM/parsing dependency. We
drop tags, decode entities, insert paragraph breaks for block elements, and
collapse runs of whitespace. Used to cache readable text for read_case and to
keyword-search for find_in_case."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "br", "li", "blockquote", "h1", "h2", "h3", "h4", "tr"}
_SKIP_CONTENT = {"script", "style"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SKIP_CONTENT:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_CONTENT and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    """Return readable plaintext from an HTML (or already-plain) string."""
    parser = _TextExtractor()
    parser.feed(html)
    raw = parser.text()
    # Collapse intra-line whitespace; keep at most single blank lines.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
    out: list[str] = []
    for line in lines:
        if line:
            out.append(line)
        elif out and out[-1] != "":
            out.append("")
    return "\n".join(out).strip()
```

- [ ] **Step 4: Run tests** (pass). **Step 5: lint. Step 6: commit** (`feat(api): stdlib HTML->plaintext for opinion text (WS3b)`, stage the 3 files).

---

## Task 4: research service — orchestration + read-through caching + find_in_case

**Files:** Create `api/app/research/service.py`; Test `api/tests/test_research_service.py`.

- [ ] **Step 1: Failing tests** (`api/tests/test_research_service.py`). Mock the gateway via respx and storage via monkeypatch:

```python
import httpx
import pytest
import respx
from sqlalchemy import select

from app.models.research import ResearchClusterMetadata, ResearchOpinionMetadata
from app.research import service

GW = "http://localhost:8001"  # default settings.lq_ai_gateway_url


@pytest.fixture
def fake_storage(monkeypatch):
    store: dict[str, bytes] = {}

    async def _upload(*, storage_path: str, body: bytes, content_type: str) -> None:
        store[storage_path] = body

    class _Reader:
        def __init__(self, data: bytes) -> None:
            self._data = data
        async def __aenter__(self):
            async def _gen():
                yield self._data
            return _gen()
        async def __aexit__(self, *a):
            return False

    def _download(*, storage_path: str):
        return _Reader(store[storage_path])

    monkeypatch.setattr("app.research.service.upload_bytes", _upload)
    monkeypatch.setattr("app.research.service.stream_download", _download)
    return store


@pytest.mark.asyncio
async def test_get_cluster_fetches_caches_and_then_serves_from_cache(db_session, fake_storage) -> None:
    cluster = {"id": 5, "case_name": "X v. Y", "case_name_short": "X",
               "date_filed": "2020-01-01", "citations": [], "court": "scotus",
               "absolute_url": "/opinion/5/",
               "sub_opinions": []}  # service uses gateway get_cases payload shape
    gw_payload = {"provider": "courtlistener-prod", "tool": "get_cases", "tier": 4,
                  "payload": {"cluster": cluster, "opinions": [
                      {"id": 9, "text_field_used": "html_with_citations",
                       "text": "<p>Held: it is so.</p>"}]}}
    with respx.mock:
        route = respx.post(f"{GW}/v1/tools/courtlistener-prod/get_cases").mock(
            return_value=httpx.Response(200, json=gw_payload)
        )
        out1 = await service.get_cluster(db_session, cluster_id=5)
        out2 = await service.get_cluster(db_session, cluster_id=5)  # second call: cache hit
    assert out1["cluster"]["case_name"] == "X v. Y"
    assert out1["opinions"][0]["opinion_id"] == 9
    assert route.call_count == 1  # second call served from cache, no gateway hit
    # opinion plaintext cached (HTML stripped)
    op = (await db_session.execute(
        select(ResearchOpinionMetadata).where(ResearchOpinionMetadata.opinion_id == 9)
    )).scalar_one()
    assert "Held: it is so." in fake_storage[op.storage_path].decode()
    assert "<p>" not in fake_storage[op.storage_path].decode()


@pytest.mark.asyncio
async def test_read_opinion_404_when_not_fetched(db_session, fake_storage) -> None:
    from app.errors import NotFound
    with pytest.raises(NotFound):
        await service.read_opinion(db_session, opinion_id=999)


@pytest.mark.asyncio
async def test_find_in_case_returns_matches(db_session, fake_storage) -> None:
    # seed a cached opinion
    fake_storage["k"] = b"The right to privacy is fundamental. Privacy again."
    db_session.add(ResearchOpinionMetadata(
        opinion_id=9, cluster_id=5, text_field_used="x", storage_path="k", char_length=51))
    await db_session.flush()
    matches = await service.find_in_case(db_session, opinion_id=9, query="privacy", max_matches=3)
    assert len(matches) >= 1
    assert "privacy" in matches[0]["snippet"].lower()
```

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Implement `api/app/research/service.py`:**

```python
"""Research orchestration: gateway tool calls + read-through opinion cache.

Stateless pass-throughs (verify_citations, search_case_law) just call the
gateway. get_cluster (get_cases) is read-through cached: opinion plaintext →
object storage, metadata → DB. find_in_case/read_opinion read the cache and
404 if the cluster was never fetched (MikeOSS "fetched-cluster" semantics).
The backend never calls CourtListener directly (ADR 0014)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import get_gateway_client
from app.errors import NotFound
from app.models.research import ResearchClusterMetadata, ResearchOpinionMetadata
from app.research.html import html_to_text
from app.storage import stream_download, upload_bytes

_PROVIDER = "courtlistener-prod"


async def verify_citations(text: str, *, request_id: str | None = None) -> dict[str, Any]:
    result = await get_gateway_client().call_tool(
        _PROVIDER, "verify_citations", {"text": text}, request_id=request_id
    )
    return result["payload"]


async def search_case_law(args: dict[str, Any], *, request_id: str | None = None) -> dict[str, Any]:
    result = await get_gateway_client().call_tool(
        _PROVIDER, "search_case_law", args, request_id=request_id
    )
    return result["payload"]


def _opinion_storage_path(cluster_id: int, opinion_id: int) -> str:
    return f"courtlistener/opinions/by-cluster/{cluster_id}/{opinion_id}"


async def get_cluster(
    db: AsyncSession, *, cluster_id: int, request_id: str | None = None
) -> dict[str, Any]:
    """Read-through: return cached cluster+opinions, else fetch via gateway, cache, return."""
    cached = (
        await db.execute(
            select(ResearchClusterMetadata).where(
                ResearchClusterMetadata.cluster_id == cluster_id
            )
        )
    ).scalar_one_or_none()
    if cached is not None:
        ops = (
            await db.execute(
                select(ResearchOpinionMetadata).where(
                    ResearchOpinionMetadata.cluster_id == cluster_id
                )
            )
        ).scalars().all()
        return _cluster_view(cached, list(ops))

    result = await get_gateway_client().call_tool(
        _PROVIDER, "get_cases", {"cluster_id": cluster_id}, request_id=request_id
    )
    payload = result["payload"]
    cluster = payload["cluster"]
    row = ResearchClusterMetadata(
        cluster_id=cluster_id,
        case_name=cluster.get("case_name"),
        court=cluster.get("court"),
        date_filed=cluster.get("date_filed"),
        absolute_url=cluster.get("absolute_url"),
    )
    await db.merge(row)
    op_rows: list[ResearchOpinionMetadata] = []
    for op in payload.get("opinions", []):
        opinion_id = op.get("id")
        if opinion_id is None:
            continue
        text = html_to_text(op.get("text") or "")
        path = _opinion_storage_path(cluster_id, opinion_id)
        await upload_bytes(
            storage_path=path, body=text.encode("utf-8"), content_type="text/plain; charset=utf-8"
        )
        op_row = ResearchOpinionMetadata(
            opinion_id=opinion_id, cluster_id=cluster_id,
            text_field_used=op.get("text_field_used"), storage_path=path,
            char_length=len(text),
        )
        await db.merge(op_row)
        op_rows.append(op_row)
    await db.flush()
    return _cluster_view(row, op_rows)


def _cluster_view(
    cluster: ResearchClusterMetadata, opinions: list[ResearchOpinionMetadata]
) -> dict[str, Any]:
    return {
        "cluster": {
            "cluster_id": cluster.cluster_id, "case_name": cluster.case_name,
            "court": cluster.court, "date_filed": cluster.date_filed,
            "absolute_url": cluster.absolute_url,
        },
        "opinions": [
            {"opinion_id": o.opinion_id, "text_field_used": o.text_field_used,
             "char_length": o.char_length}
            for o in opinions
        ],
    }


async def _load_opinion_text(db: AsyncSession, opinion_id: int) -> ResearchOpinionMetadata:
    row = (
        await db.execute(
            select(ResearchOpinionMetadata).where(
                ResearchOpinionMetadata.opinion_id == opinion_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFound(
            "opinion not fetched; GET /api/v1/research/clusters/{cluster_id} first",
            details={"opinion_id": opinion_id},
        )
    return row


async def _read_body(storage_path: str) -> str:
    chunks: list[bytes] = []
    async with stream_download(storage_path=storage_path) as stream:
        async for chunk in stream:
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


async def read_opinion(db: AsyncSession, *, opinion_id: int) -> dict[str, Any]:
    row = await _load_opinion_text(db, opinion_id)
    text = await _read_body(row.storage_path)
    return {
        "opinion_id": row.opinion_id, "cluster_id": row.cluster_id,
        "text_field_used": row.text_field_used, "text": text,
    }


async def find_in_case(
    db: AsyncSession, *, opinion_id: int, query: str, max_matches: int = 3
) -> list[dict[str, Any]]:
    row = await _load_opinion_text(db, opinion_id)
    text = await _read_body(row.storage_path)
    lowered = text.lower()
    needle = query.lower()
    matches: list[dict[str, Any]] = []
    start = 0
    while len(matches) < max_matches:
        idx = lowered.find(needle, start)
        if idx == -1:
            break
        lo = max(0, idx - 80)
        hi = min(len(text), idx + len(query) + 80)
        matches.append({"position": idx, "snippet": text[lo:hi]})
        start = idx + len(query)
    return matches
```

- [ ] **Step 4: Run tests** (pass). **Step 5: lint** (mypy: `db.merge` returns a coroutine in async — confirm the async-merge usage compiles; if mypy flags merge's return, `await db.merge(row)` is correct for AsyncSession). **Step 6: commit** (`feat(api): research service — gateway orchestration + read-through opinion cache (WS3b)`).

---

## Task 5: schemas + 5 route handlers + registration + collision guards + OpenAPI

**Files:** Create `api/app/schemas/research.py`, `api/app/api/research.py`; modify `api/app/api/__init__.py`, `api/tests/test_openapi.py`, `api/tests/test_endpoints.py`, `docs/api/backend-openapi.yaml`; Test `api/tests/test_research_endpoints.py`.

- [ ] **Step 1: Failing endpoint tests** (`api/tests/test_research_endpoints.py`) — use the api's authenticated test client (find the existing helper, e.g. an `auth_client`/token fixture other endpoint tests use; mirror them), respx-mock the gateway, monkeypatch storage. Cover: `POST /research/verify-citations` (200 passthrough), `POST /research/search` (200), `GET /research/clusters/{id}` (200 + caches), `GET /research/opinions/{id}` (404 when not fetched, 200 after a cluster fetch), `POST /research/find-in-case` (matches). (Model the auth setup on an existing `api/tests/test_*endpoints*.py`.)

- [ ] **Step 2: Run, confirm fail.**

- [ ] **Step 3: Schemas `api/app/schemas/research.py`** — request models `ConfigDict(extra="forbid")`, response models plain. Define: `VerifyCitationsRequest{text}`, `SearchRequest{q, court?, order_by?}`, `FindInCaseRequest{opinion_id:int, query, max_matches:int=3 (ge=1,le=10)}`, and response models `ClusterView`, `OpinionText`, `FindMatch`/`FindInCaseResponse`, plus pass-through responses typed loosely (`VerifyCitationsResponse{citations: list[dict]}`, `SearchResponse{count:int|None, results:list[dict], next_cursor:str|None}`). Keep field names matching the service output.

- [ ] **Step 4: Handlers `api/app/api/research.py`:**

```python
"""/api/v1/research — case-law research surface (WS3b).

Thin handlers over app.research.service. verify/search pass through to the
gateway CourtListener tools; clusters/opinions/find-in-case use the
read-through opinion cache. Auth + must-change gate applied at router
registration (dependencies=_active)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.db.session import get_db
from app.research import service
from app.schemas.research import (
    ClusterView, FindInCaseRequest, FindInCaseResponse, OpinionText,
    SearchRequest, SearchResponse, VerifyCitationsRequest, VerifyCitationsResponse,
)

router = APIRouter(prefix="/research", tags=["research"])


@router.post("/verify-citations", response_model=VerifyCitationsResponse)
async def verify_citations(payload: VerifyCitationsRequest, user: ActiveUser) -> VerifyCitationsResponse:
    result = await service.verify_citations(payload.text)
    return VerifyCitationsResponse(citations=result.get("citations", []))


@router.post("/search", response_model=SearchResponse)
async def search(payload: SearchRequest, user: ActiveUser) -> SearchResponse:
    result = await service.search_case_law(payload.model_dump(exclude_none=True))
    return SearchResponse(**result)


@router.get("/clusters/{cluster_id}", response_model=ClusterView)
async def get_cluster(
    cluster_id: int, user: ActiveUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> ClusterView:
    result = await service.get_cluster(db, cluster_id=cluster_id)
    await db.commit()
    return ClusterView(**result)


@router.get("/opinions/{opinion_id}", response_model=OpinionText)
async def read_opinion(
    opinion_id: int, user: ActiveUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> OpinionText:
    return OpinionText(**await service.read_opinion(db, opinion_id=opinion_id))


@router.post("/find-in-case", response_model=FindInCaseResponse)
async def find_in_case(
    payload: FindInCaseRequest, user: ActiveUser, db: Annotated[AsyncSession, Depends(get_db)]
) -> FindInCaseResponse:
    matches = await service.find_in_case(
        db, opinion_id=payload.opinion_id, query=payload.query, max_matches=payload.max_matches
    )
    return FindInCaseResponse(opinion_id=payload.opinion_id, matches=matches)
```

(Adjust `ClusterView`/response constructors to match your schema field names; `ClusterView` wraps `{cluster, opinions}`.)

- [ ] **Step 5: Register** in `api/app/api/__init__.py`: add `research` to the imports and `api_router.include_router(research.router, dependencies=_active)` in the `_active` block.

- [ ] **Step 6: Collision guards.** Add the 5 paths to `EXPECTED_PATHS` in `api/tests/test_openapi.py` and bump the count `118 → 123`:
`/api/v1/research/verify-citations`, `/api/v1/research/search`, `/api/v1/research/clusters/{cluster_id}`, `/api/v1/research/opinions/{opinion_id}`, `/api/v1/research/find-in-case`.
Add the 5 `(METHOD, path)` tuples to `IMPLEMENTED_ROUTES` in `api/tests/test_endpoints.py`. Document the 5 endpoints in `docs/api/backend-openapi.yaml` (run `test_openapi.py` as the authoritative conformance check — don't eyeball; it doesn't `safe_load`).

- [ ] **Step 7: Run** `test_research_endpoints.py` + `test_openapi.py` + `test_endpoints.py` (all pass). **Step 8: lint. Step 9: commit** (`feat(api): /api/v1/research endpoints + schemas (WS3b)`, stage all the above).

---

## Task 6: final gates, push, PR

- [ ] **Step 1: Full sweep** — `cd ~/Code/lq-ai && api/.venv/bin/ruff format --check api scripts`, `cd api && .venv/bin/ruff check . && .venv/bin/mypy app`, and the FULL api suite: `cd api && DATABASE_URL='postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai' .venv/bin/pytest -q -m "not provider and not slow"` (all green; confirm the `EXPECTED_PATHS` guard passes at 123).
- [ ] **Step 2: Push both remotes** (`git push origin feat/research-api && git push tucuxi feat/research-api`).
- [ ] **Step 3: Open the PR** (base `main`), title `WS3b/PR3b: API research subsystem (legal-research milestone)`. Body: the 5 endpoints, read-through caching design, stdlib HTML→text (no new dep), live-API fallback; deferrals (per-turn cache→PR5, UI/SSE + citation grounding→WS5, MCP→PR4); note **api-only, no security review → self-merge after CI green**. Watch CI; **self-merge once green** (api-only path). Report the squash SHA.

---

## Self-review (against the spec + decisions)
- **Distinct REST endpoints (5)** → Task 5. ✓ (Kevin's choice.)
- **Persistent read-through caching; per-turn cache deferred** → Task 4 (`get_cluster` read-through; find/read from cache); deferral in Scope. ✓ (Kevin's choice.)
- **Backend never calls CourtListener directly** → all calls via `GatewayClient.call_tool` → gateway (Task 1 + service). ✓
- **find_in_case/read_case on fetched opinions; 404 otherwise** → `_load_opinion_text` raises NotFound. ✓
- **HTML→text without a new dependency** → Task 3 stdlib. ✓
- **Collision guards bumped (118→123, IMPLEMENTED_ROUTES)** → Task 5 Step 6. ✓
- **Migration 0049 + models + db-schema** → Task 2. ✓
- **Type consistency:** `call_tool(provider, tool, args, *, max_allowed_tier, request_id)`, service fns `verify_citations`/`search_case_law`/`get_cluster`/`read_opinion`/`find_in_case`, `_opinion_storage_path`, `html_to_text`, model fields (`cluster_id`/`opinion_id`/`storage_path`/`char_length`/`text_field_used`) — consistent across tasks. ✓
- **Known seams to confirm at execution:** (a) `map_gateway_error_code("invalid_request")` target (Task 1 — adjust the test to the real mapping); (b) the api authenticated-test-client fixture name (Task 5 — mirror an existing endpoint test); (c) `await db.merge(...)` async usage + whether handlers should `commit` (get_cluster commits after caching). Implementers verify against the real code, don't guess.
