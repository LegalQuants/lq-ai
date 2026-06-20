# PR6c — External-source citations (case-law provenance) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record which case-law sources a chat turn consulted (retrieval-provenance) in a new `message_tool_sources` table, expose them via a read endpoint, and surface them in the chat as an inline "Sources consulted" sidecar + provenance pill; then flip the 6a/6b narrative's case-law-provenance claim to "shipped."

**Architecture:** Backend — the governed tool-loop already gets structured case metadata back from research dispatch; a pure `extract_tool_sources` helper maps each research result into source records, the loop accumulates them on `LoopFinal`, and a new `_persist_message_tool_sources` writes them tied to the assistant message wherever citations are persisted. A read endpoint mirrors the citations GET. Frontend — `MessageBubble` lazy-fetches sources post-stream (like citations) and renders a `ToolSourcesPanel` + a `caselaw` `ProvenancePill`. No SSE/protocol change.

**Tech Stack:** Python (FastAPI, SQLAlchemy async, Alembic), Postgres; TypeScript/SvelteKit (Svelte 4 `export let`, Vitest), Tailwind/design-system primitives.

## Global Constraints

- **Branch:** `feat/pr6c-external-source-citations` off `main` (`47d9bed`). Push `origin` + `tucuxi`. `origin/main` PROTECTED — PR + GitHub merge only; sync tucuxi after. **Not security-gated** (new product table + read endpoint in `api/`, plus `web/` + docs; no `gateway/**`, no `docs/security/**`, no audit-log/auth/crypto) → self-merge after CI green.
- **Retrieval-provenance only.** Persist every case the case-law tool *returned*; no claim-level marker grounding; no verification path. `message_citations` is NOT modified.
- **Case-law tools only:** `search_case_law` and `get_cluster` produce sources (they carry full cluster metadata: `case_name`, `court`, `date_filed`, `absolute_url`, `cluster_id`). `read_opinion`/`find_in_case`/`verify_citations`/MCP → no sources (DE-350 defers generic MCP).
- **No new SSE frames.** Frontend fetches sources post-stream (`!isStreaming`), exactly like `fetchedCitations`.
- **Migration head is 0054 → new migration is 0055.** Verify on a throwaway `pgvector/pgvector:pg16` (conftest auto-migrates) — **NEVER** host-side `alembic upgrade` on the live dev DB. When 0055 lands, rebuild `api` + `arq-worker` + `ingest-worker` together.
- **Test-suite collision guards (crash the whole api suite at collection if wrong):** add the new route to `IMPLEMENTED_ROUTES` (`api/tests/test_endpoints.py`); bump the pinned path count `133 → 134` (`api/tests/test_openapi.py:325`) AND add the path to `EXPECTED_PATHS` (`api/tests/test_openapi.py:18`); add the path to `docs/api/backend-openapi.yaml`. `test_openapi.py` is the authoritative conformance check — run it, don't eyeball.
- **Run BOTH `ruff format` and `ruff check`** (CI runs them as separate gates); `mypy` standard for `api/`. Web: `npm run check:lq-ai` + Vitest.
- **Test runner = host venv at `api/.venv`, run from `api/`** (per the milestone convention — compose bakes code). All pytest/mypy commands are `cd ~/Code/lq-ai/api && .venv/bin/pytest tests/<file>` (note: paths are `tests/…`, NOT `api/tests/…`, when cwd is `api/`). `ruff` runs from the repo root (`ruff format api/`). `conftest.py` auto-applies migrations to a throwaway pg and ROLLBACKs per test.
- **No shared row-factory fixtures.** There is no `make_message`/`auth_header`/`client` in `conftest.py` — each test file builds its own, mirroring `tests/test_chat_citations.py` / `tests/test_chat_rag.py`. The integration tests in this plan COPY that file's `client` fixture (the `get_db` override + gateway-client set) and `owner_user` fixture verbatim, and build `Chat`/`Message` rows inline. Auth header: `create_access_token(user_id=user.id, email=user.email, is_admin=user.is_admin)` from `app.security` → `{"Authorization": f"Bearer {token}"}`.
- **No `@testing-library/svelte`** (not a project dep). Svelte components are Svelte 4 (`export let` + `on:click`); test pure logic via `<script context="module">` helpers (RefusalMessageBubble / ToolGatePrompt / M2Citations pattern).
- **Commit (every commit):** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Stage explicitly — never `git add -A`.

## TDD note

Backend Tasks 1–4 are clean pytest red/green (model round-trip, pure `extract_tool_sources`, persist integration, endpoint integration + OpenAPI conformance). Frontend Tasks 5–6 are Vitest red/green on pure helpers; Task 7 (MessageBubble wiring) + Task 8 (docs) verify via `svelte-check` + a headless static render. Task 9 ships.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `api/app/models/message_tool_source.py` | Create | `MessageToolSource` ORM model. |
| `api/app/models/__init__.py` | Modify | Export `MessageToolSource`. |
| `api/alembic/versions/0055_message_tool_sources.py` | Create | Migration 0055 (table + index). |
| `api/app/chat/tool_loop.py` | Modify | `ToolSourceRecord` dataclass + `extract_tool_sources` pure helper; `LoopFinal.tool_sources` field; accumulate in `run_chat_tool_loop`. |
| `api/app/api/chats.py` | Modify | `_persist_message_tool_sources`; call it at the 3 `LoopFinal` persist sites; `GET …/sources` endpoint. |
| `api/tests/test_message_tool_sources.py` | Create | Model + extractor + persist + endpoint tests. |
| `api/tests/test_endpoints.py`, `api/tests/test_openapi.py` | Modify | Collision guards. |
| `docs/api/backend-openapi.yaml`, `docs/db-schema.md` | Modify | Endpoint + schema + table docs. |
| `web/src/lib/lq-ai/types.ts` | Modify | `ToolSource` interface. |
| `web/src/lib/lq-ai/api/sources.ts` | Create | `getMessageSources`. |
| `web/src/lib/lq-ai/api/index.ts` | Modify | Export `sourcesApi`. |
| `web/src/lib/lq-ai/components/ProvenancePill.svelte` | Modify | Add `caselaw` kind. |
| `web/src/lib/lq-ai/components/ToolSourcesPanel.svelte` | Create | The inline "Sources consulted" sidecar. |
| `web/src/lib/lq-ai/components/MessageBubble.svelte` | Modify | Lazy-fetch sources; render pill + panel. |
| `web/src/lib/lq-ai/__tests__/ToolSourcesPanel.test.ts`, `sources-api.test.ts` | Create | Vitest on pure helpers. |
| `web/static/learn/playgrounds/governed-tool-flow.html`, `web/src/routes/lq-ai/learn/how/+page.svelte`, `README.md` | Modify | D6 narrative flip. |

---

## Task 1: `MessageToolSource` model + migration 0055

**Files:**
- Create: `api/app/models/message_tool_source.py`
- Modify: `api/app/models/__init__.py` (mirror the `ChatPendingToolCall` export at lines 23 + 56)
- Create: `api/alembic/versions/0055_message_tool_sources.py`
- Create: `api/tests/test_message_tool_sources.py`
- Modify: `docs/db-schema.md`

**Interfaces:**
- Produces: `MessageToolSource` ORM model with columns `id, message_id, source_kind, label, subtitle, url, external_ref, provider, tool, created_at` (consumed by Tasks 3–4).

**Gate:** pytest — the model inserts + round-trips against the conftest-migrated throwaway pg; the migration is at head.

- [ ] **Step 1: Write the failing model test** (`api/tests/test_message_tool_sources.py`). Build rows inline (no shared fixtures); a module-local `_assistant_message` helper creates a User + Chat + assistant Message and is reused by later tasks:
```python
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MessageToolSource
from app.models.chat import Chat, Message
from app.models.user import User
from app.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"src-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Sources Test Owner",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _assistant_message(db_session: AsyncSession, owner: User) -> tuple[Chat, Message]:
    chat = Chat(owner_id=owner.id, project_id=None, title="src-chat")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="answer")
    db_session.add(msg)
    await db_session.flush()
    return chat, msg


@pytest.mark.asyncio
async def test_message_tool_source_roundtrips(db_session: AsyncSession, owner_user: User):
    _chat, msg = await _assistant_message(db_session, owner_user)
    row = MessageToolSource(
        message_id=msg.id,
        source_kind="caselaw",
        label="Roe v. Wade",
        subtitle="scotus · 1973-01-22",
        url="https://www.courtlistener.com/opinion/42/",
        external_ref="42",
        provider="courtlistener",
        tool="search_case_law",
    )
    db_session.add(row)
    await db_session.flush()
    got = (
        await db_session.execute(
            select(MessageToolSource).where(MessageToolSource.message_id == msg.id)
        )
    ).scalar_one()
    assert got.label == "Roe v. Wade"
    assert got.source_kind == "caselaw"
    assert got.external_ref == "42"
    assert got.created_at is not None
```
Before running, confirm `Message`'s required columns (`grep -n "nullable=False" app/models/chat.py` within the `Message` class) — if `kind`/`content` differ from the above, match the model. The `Chat` constructor mirrors `tests/test_chat_citations.py:chat_with_kb_attached` (here with `project_id=None`).

- [ ] **Step 2: Run; expect FAIL** (`ImportError: cannot import name 'MessageToolSource'`).
```bash
cd ~/Code/lq-ai/api && .venv/bin/pytest tests/test_message_tool_sources.py::test_message_tool_source_roundtrips -q
```

- [ ] **Step 3: Create the model** (`api/app/models/message_tool_source.py`), mirroring `app/models/chat_pending_tool_call.py`'s style (Base, UUID pk, FK, `Mapped`/`mapped_column`):
```python
"""message_tool_sources — retrieval-provenance for external sources a chat turn consulted.

One row per external source (a case-law cluster) that a research tool *returned*
during an assistant turn. This is retrieval-provenance — "sources consulted" —
NOT quote-verification: it deliberately lives apart from ``message_citations``
(which is byte-offset quote-matching against uploaded documents). Case-law only
in PR6c (``source_kind='caselaw'``); generic MCP results are DE-350.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MessageToolSource(Base):
    __tablename__ = "message_tool_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE", name="fk_message_tool_sources_message"),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_message_tool_sources_message_id", "message_id"),)
```
Confirm the actual `Base` import path + the timestamp column convention by reading `app/models/chat_pending_tool_call.py` first and matching it exactly (e.g. `TIMESTAMP(timezone=True)` if that file uses it).

- [ ] **Step 4: Export it** — in `api/app/models/__init__.py` add `from app.models.message_tool_source import MessageToolSource` next to the `ChatPendingToolCall` import (line ~23) and add `"MessageToolSource",` to `__all__` (line ~56).

- [ ] **Step 5: Create migration 0055** (`api/alembic/versions/0055_message_tool_sources.py`), mirroring `0054_chat_pending_tool_call.py`:
```python
"""message_tool_sources — retrieval-provenance for external sources consulted in a turn

Revision ID: 0055
Revises: 0054
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_tool_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE", name="fk_message_tool_sources_message"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("subtitle", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("external_ref", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_message_tool_sources_message_id", "message_tool_sources", ["message_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_message_tool_sources_message_id", table_name="message_tool_sources")
    op.drop_table("message_tool_sources")
```

- [ ] **Step 6: Run; expect PASS** (conftest auto-applies migrations to the throwaway pg). Also assert a single head:
```bash
cd ~/Code/lq-ai/api && .venv/bin/pytest tests/test_message_tool_sources.py::test_message_tool_source_roundtrips -q
.venv/bin/alembic heads  # expect exactly 0055 (single head; do NOT run `upgrade` against the dev DB)
```

- [ ] **Step 7: Document the table** in `docs/db-schema.md` — add a `message_tool_sources` section: the columns, the `(message_id)` index, the retrieval-provenance semantics (contrast with `message_citations` quote-verification), and the case-law-only scope.

- [ ] **Step 8: ruff + commit.**
```bash
cd ~/Code/lq-ai && ruff format api/ && ruff check api/
git add api/app/models/message_tool_source.py api/app/models/__init__.py api/alembic/versions/0055_message_tool_sources.py api/tests/test_message_tool_sources.py docs/db-schema.md
git commit -s -m "feat(api): message_tool_sources model + migration 0055 (PR6c)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `extract_tool_sources` + `LoopFinal.tool_sources` accumulation

**Files:**
- Modify: `api/app/chat/tool_loop.py` (add `ToolSourceRecord` near the outcome dataclasses ~line 60; add `extract_tool_sources` near `_dispatch_research` ~line 155; add `tool_sources` field to `LoopFinal` ~line 67; accumulate in `run_chat_tool_loop`)
- Modify (extend): `api/tests/test_message_tool_sources.py`

**Interfaces:**
- Consumes: research dispatch payloads — `search_case_law` → `{"count", "results": [{"cluster_id","case_name","court","date_filed","absolute_url",...}]}`; `get_cluster` → `{"cluster": {"cluster_id","case_name","court","date_filed","absolute_url"}, "opinions":[...]}`.
- Produces (consumed by Task 3): `ToolSourceRecord(source_kind, label, subtitle, url, external_ref, provider, tool)`; `extract_tool_sources(tool_name: str, data: Any) -> list[ToolSourceRecord]`; `LoopFinal.tool_sources: list[ToolSourceRecord]`.

**Gate:** pytest — `extract_tool_sources` over representative search/get_cluster payloads, the empty/non-research cases, and the relative-URL absolutize.

- [ ] **Step 1: Write the failing extractor tests** (append to `api/tests/test_message_tool_sources.py`):
```python
from app.chat.tool_loop import extract_tool_sources


def test_extract_from_search_case_law():
    data = {
        "count": 1,
        "results": [
            {
                "cluster_id": 42,
                "case_name": "Roe v. Wade",
                "court": "scotus",
                "date_filed": "1973-01-22",
                "absolute_url": "/opinion/42/",
                "snippet": "…",
            }
        ],
    }
    recs = extract_tool_sources("search_case_law", data)
    assert len(recs) == 1
    r = recs[0]
    assert r.source_kind == "caselaw"
    assert r.label == "Roe v. Wade"
    assert r.subtitle == "scotus · 1973-01-22"
    assert r.url == "https://www.courtlistener.com/opinion/42/"  # absolutized
    assert r.external_ref == "42"
    assert r.provider == "courtlistener"
    assert r.tool == "search_case_law"


def test_extract_from_get_cluster():
    data = {
        "cluster": {
            "cluster_id": 7,
            "case_name": "X v. Y",
            "court": "ca9",
            "date_filed": "2001-05-05",
            "absolute_url": "https://www.courtlistener.com/opinion/7/",
        },
        "opinions": [],
    }
    recs = extract_tool_sources("get_cluster", data)
    assert len(recs) == 1
    assert recs[0].label == "X v. Y"
    assert recs[0].external_ref == "7"
    assert recs[0].url == "https://www.courtlistener.com/opinion/7/"  # already absolute → unchanged


def test_extract_non_research_and_empty():
    assert extract_tool_sources("read_opinion", {"opinion_id": 1}) == []
    assert extract_tool_sources("find_in_case", {"matches": []}) == []
    assert extract_tool_sources("some_mcp_tool", {"payload": {}}) == []
    assert extract_tool_sources("search_case_law", {"results": []}) == []
    assert extract_tool_sources("search_case_law", None) == []
```

- [ ] **Step 2: Run; expect FAIL** (`ImportError: extract_tool_sources`).
```bash
cd ~/Code/lq-ai/api && .venv/bin/pytest tests/test_message_tool_sources.py -k extract -q
```

- [ ] **Step 3: Add `ToolSourceRecord`** near the outcome dataclasses (after `LoopFinal`, ~line 84 in `tool_loop.py`):
```python
_COURTLISTENER_BASE = "https://www.courtlistener.com"


@dataclass
class ToolSourceRecord:
    """One external source (a case-law cluster) a research tool returned this turn."""

    source_kind: str
    label: str
    subtitle: str | None
    url: str | None
    external_ref: str | None
    provider: str
    tool: str
```

- [ ] **Step 4: Add `tool_sources` to `LoopFinal`** (the `@dataclass` at ~line 67) — append a field after `calls_used`:
```python
    tool_sources: list["ToolSourceRecord"] = field(default_factory=list)
```

- [ ] **Step 5: Implement `extract_tool_sources`** (near `_dispatch_research`, ~line 155):
```python
def _absolutize_cl_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"{_COURTLISTENER_BASE}{url}"


def _cluster_record(cluster: dict[str, Any], tool: str) -> ToolSourceRecord | None:
    """Map a CourtListener cluster dict → a ToolSourceRecord (None if no identity)."""
    cluster_id = cluster.get("cluster_id")
    case_name = cluster.get("case_name")
    if cluster_id is None and not case_name:
        return None
    court = cluster.get("court")
    date_filed = cluster.get("date_filed")
    subtitle_parts = [p for p in (court, date_filed) if p]
    return ToolSourceRecord(
        source_kind="caselaw",
        label=case_name or f"Cluster {cluster_id}",
        subtitle=" · ".join(subtitle_parts) if subtitle_parts else None,
        url=_absolutize_cl_url(cluster.get("absolute_url")),
        external_ref=str(cluster_id) if cluster_id is not None else None,
        provider="courtlistener",
        tool=tool,
    )


def extract_tool_sources(tool_name: str, data: Any) -> list[ToolSourceRecord]:
    """Map a research tool's structured result into retrieval-provenance records.

    Only ``search_case_law`` (each returned cluster) and ``get_cluster`` (the one
    cluster) carry full case identity, so only they produce sources. All other
    tools (read_opinion / find_in_case / verify_citations / MCP) → ``[]``.
    """
    if not isinstance(data, dict):
        return []
    out: list[ToolSourceRecord] = []
    if tool_name == "search_case_law":
        for item in data.get("results", []) or []:
            if isinstance(item, dict):
                rec = _cluster_record(item, tool_name)
                if rec is not None:
                    out.append(rec)
    elif tool_name == "get_cluster":
        cluster = data.get("cluster")
        if isinstance(cluster, dict):
            rec = _cluster_record(cluster, tool_name)
            if rec is not None:
                out.append(rec)
    return out
```

- [ ] **Step 6: Accumulate in `run_chat_tool_loop`.** After a successful `execute_tool` call returns its `ToolResult` (the read_only inline path, branch (d) in the loop docstring), record sources from the result. Find where the loop appends the tool result message (`tool_result_message(...)`); immediately alongside it add:
```python
            # PR6c — retrieval-provenance: record case-law sources this call surfaced.
            for rec in extract_tool_sources(spec.tool, result.data):
                if rec.external_ref is None or rec.external_ref not in _seen_source_refs:
                    if rec.external_ref is not None:
                        _seen_source_refs.add(rec.external_ref)
                    collected_sources.append(rec)
```
Initialise `collected_sources: list[ToolSourceRecord] = []` and `_seen_source_refs: set[str] = set()` once, near the top of `run_chat_tool_loop` (alongside `messages = [...]`). Then in **every** `return LoopFinal(...)` in this function, pass `tool_sources=collected_sources`. (Grep `LoopFinal(` within `run_chat_tool_loop` — there are the cap-reached final round and the normal `finish_reason != "tool_calls"` return; both must carry it.) `LoopConfirmation`/`LoopMcpAuth` do NOT carry sources (the turn paused; sources persist only on final completion).

- [ ] **Step 7: Run; expect PASS.**
```bash
cd ~/Code/lq-ai/api && .venv/bin/pytest tests/test_message_tool_sources.py -k extract -q
```

- [ ] **Step 8: ruff + mypy + commit.**
```bash
cd ~/Code/lq-ai && ruff format api/ && ruff check api/ && (cd api && .venv/bin/mypy app/chat/tool_loop.py)
git add api/app/chat/tool_loop.py api/tests/test_message_tool_sources.py
git commit -s -m "feat(api): extract_tool_sources + LoopFinal.tool_sources accumulation (PR6c)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `_persist_message_tool_sources` + wire into the LoopFinal persist sites

**Files:**
- Modify: `api/app/api/chats.py` (add `_persist_message_tool_sources` near `_persist_message_citations` ~line 2408; call it after each `_persist_message_citations` call — sites at ~2749, ~2958, ~3287)
- Modify (extend): `api/tests/test_message_tool_sources.py`

**Interfaces:**
- Consumes: Task 2 `ToolSourceRecord`, `LoopFinal.tool_sources`; Task 1 `MessageToolSource`.
- Produces (consumed by Task 4): persisted `message_tool_sources` rows keyed by `message_id`.

**Gate:** pytest integration — a turn that runs a case-law tool persists rows; the helper no-ops on empty.

- [ ] **Step 1: Write the failing persist test** (append to `api/tests/test_message_tool_sources.py`):
```python
@pytest.mark.asyncio
async def test_persist_message_tool_sources_writes_rows(db_session: AsyncSession, owner_user: User):
    from app.api.chats import _persist_message_tool_sources
    from app.chat.tool_loop import ToolSourceRecord

    _chat, msg = await _assistant_message(db_session, owner_user)
    recs = [
        ToolSourceRecord("caselaw", "Roe v. Wade", "scotus · 1973-01-22",
                         "https://www.courtlistener.com/opinion/42/", "42",
                         "courtlistener", "search_case_law"),
    ]
    await _persist_message_tool_sources(db_session, message_id=msg.id, records=recs)
    rows = (
        await db_session.execute(
            select(MessageToolSource).where(MessageToolSource.message_id == msg.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].label == "Roe v. Wade"

    # No-op on empty.
    _chat2, msg2 = await _assistant_message(db_session, owner_user)
    await _persist_message_tool_sources(db_session, message_id=msg2.id, records=[])
    rows2 = (
        await db_session.execute(
            select(MessageToolSource).where(MessageToolSource.message_id == msg2.id)
        )
    ).scalars().all()
    assert rows2 == []
```

- [ ] **Step 2: Run; expect FAIL** (`ImportError: _persist_message_tool_sources`).

- [ ] **Step 3: Implement `_persist_message_tool_sources`** in `chats.py` (place it right after `_persist_message_citations`, and import `MessageToolSource` + `ToolSourceRecord` at the top with the other model/tool_loop imports):
```python
async def _persist_message_tool_sources(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    records: list["ToolSourceRecord"],
) -> None:
    """Persist retrieval-provenance rows for the external sources a turn consulted.

    Runs after :func:`_persist_assistant_message` (so ``message_id`` is a real FK
    target). No-op when ``records`` is empty. Retrieval-provenance only — these
    rows are NOT verified (contrast ``message_citations``).
    """
    if not records:
        return
    db.add_all(
        [
            MessageToolSource(
                message_id=message_id,
                source_kind=r.source_kind,
                label=r.label,
                subtitle=r.subtitle,
                url=r.url,
                external_ref=r.external_ref,
                provider=r.provider,
                tool=r.tool,
            )
            for r in records
        ]
    )
    await db.flush()
```
Add the import: at the `from app.chat.tool_loop import ...` line (currently line 77) append `ToolSourceRecord`; add `MessageToolSource` to the models import block.

- [ ] **Step 4: Wire into the 3 LoopFinal persist sites.** After each `await _persist_message_citations(...)` call (sites ~2749, ~2958, ~3287), add — using the outcome variable in scope at that site (`outcome` at 2749/2958, `loop_outcome` at 3287):
```python
            await _persist_message_tool_sources(
                db, message_id=assistant_message_id, records=outcome.tool_sources
            )
```
(At the resume site ~3287 use `loop_outcome.tool_sources`.) Grep to confirm exactly three call sites:
```bash
cd ~/Code/lq-ai && grep -n "_persist_message_citations(" api/app/api/chats.py
```
There must be a matching `_persist_message_tool_sources` after each.

- [ ] **Step 5: Run; expect PASS.**
```bash
cd ~/Code/lq-ai/api && .venv/bin/pytest tests/test_message_tool_sources.py -k persist -q
```

- [ ] **Step 6: ruff + mypy + commit.**
```bash
cd ~/Code/lq-ai && ruff format api/ && ruff check api/ && (cd api && .venv/bin/mypy app/api/chats.py)
git add api/app/api/chats.py api/tests/test_message_tool_sources.py
git commit -s -m "feat(api): persist message_tool_sources at the LoopFinal sites (PR6c)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `GET …/sources` endpoint + collision guards

**Files:**
- Modify: `api/app/api/chats.py` (add the GET endpoint next to `get_citations` ~line 1621)
- Modify: `api/tests/test_endpoints.py` (`IMPLEMENTED_ROUTES` ~line 100), `api/tests/test_openapi.py` (count `133 → 134` at line 325; `EXPECTED_PATHS` at line 18)
- Modify: `docs/api/backend-openapi.yaml`
- Modify (extend): `api/tests/test_message_tool_sources.py`

**Interfaces:**
- Consumes: Task 1 `MessageToolSource`.
- Produces: `GET /api/v1/chats/{chat_id}/messages/{message_id}/sources` → `list[dict]` (the serialized rows, retrieval order).

**Gate:** pytest — endpoint returns rows in order, `[]` for none, 404 for foreign chat/message; OpenAPI conformance green at 134.

- [ ] **Step 1: Add the `client` fixture** by copying it verbatim from `tests/test_chat_citations.py` (the `_override_get_db` helper + the `client` `pytest_asyncio.fixture` that overrides `get_db` with `db_session`, sets a `GatewayClient`, and yields an `httpx.AsyncClient` over `ASGITransport(app=app)`). Add the matching imports (`from httpx import ASGITransport, AsyncClient`, `from app.clients.gateway import GatewayClient, set_gateway_client`, `from app.db.session import get_db`, `from app.main import app`). Then write the failing endpoint test (append to `tests/test_message_tool_sources.py`):
```python
@pytest.mark.asyncio
async def test_get_sources_endpoint(
    client: AsyncClient, db_session: AsyncSession, owner_user: User
):
    chat, msg = await _assistant_message(db_session, owner_user)
    db_session.add(
        MessageToolSource(
            message_id=msg.id, source_kind="caselaw", label="Roe v. Wade",
            subtitle="scotus · 1973-01-22", url="https://www.courtlistener.com/opinion/42/",
            external_ref="42", provider="courtlistener", tool="search_case_law",
        )
    )
    await db_session.flush()

    token = create_access_token(user_id=owner_user.id, email=owner_user.email, is_admin=False)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get(
        f"/api/v1/chats/{chat.id}/messages/{msg.id}/sources", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["label"] == "Roe v. Wade"
    assert body[0]["url"] == "https://www.courtlistener.com/opinion/42/"
    assert body[0]["source_kind"] == "caselaw"

    # Unknown message → 404.
    resp404 = await client.get(
        f"/api/v1/chats/{chat.id}/messages/{uuid.uuid4()}/sources", headers=headers
    )
    assert resp404.status_code == 404
```

- [ ] **Step 2: Run; expect FAIL** (404 route-not-found / fixture mismatch).

- [ ] **Step 3: Add the endpoint** in `chats.py` right after `get_citations` (mirror its body exactly — validate chat id, `_load_visible_chat`, confirm message belongs to chat, then select + serialize):
```python
@router.get(
    "/{chat_id}/messages/{message_id}/sources",
    summary="Get external-source provenance (case law consulted) for a message (PR6c)",
)
async def get_message_sources(
    chat_id: str,
    message_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, Any]]:
    """Return the external sources (case-law clusters) a message's turn consulted.

    Retrieval-provenance from ``message_tool_sources`` — "sources consulted,"
    distinct from the verified quote rows of ``message_citations``. Returns ``[]``
    for a turn that consulted nothing; 404 when the message doesn't exist in the
    chat. Chat ownership enforced as in :func:`get_citations`.
    """
    cid = _validate_chat_id(chat_id)
    try:
        mid = uuid.UUID(message_id)
    except ValueError as exc:
        raise ValidationError(
            "message_id must be a UUID", details={"message_id": message_id}
        ) from exc

    await _load_visible_chat(db, cid, user.id, include_archived=True)

    msg_stmt = select(Message.id).where(Message.id == mid, Message.chat_id == cid)
    if (await db.execute(msg_stmt)).scalar_one_or_none() is None:
        raise NotFound(f"Message {mid} not found.", details={"message_id": str(mid)})

    src_stmt = (
        select(MessageToolSource)
        .where(MessageToolSource.message_id == mid)
        .order_by(MessageToolSource.created_at, MessageToolSource.id)
    )
    rows = (await db.execute(src_stmt)).scalars().all()
    return [
        {
            "id": str(s.id),
            "message_id": str(s.message_id),
            "source_kind": s.source_kind,
            "label": s.label,
            "subtitle": s.subtitle,
            "url": s.url,
            "external_ref": s.external_ref,
            "provider": s.provider,
            "tool": s.tool,
            "created_at": s.created_at.isoformat(),
        }
        for s in rows
    ]
```

- [ ] **Step 4: Collision guards.**
  - `api/tests/test_endpoints.py` `IMPLEMENTED_ROUTES` — add `("GET", "/api/v1/chats/{chat_id}/messages/{message_id}/sources"),` next to the citations tuple (line ~132).
  - `api/tests/test_openapi.py` — bump `assert len(actual) == 133` → `134` (line 325); add `"/api/v1/chats/{chat_id}/messages/{message_id}/sources"` to the `EXPECTED_PATHS` frozenset (line 18).
  - `docs/api/backend-openapi.yaml` — add the path + an inline response schema (array of objects with the serialized fields above). Copy the citations path entry as the template and adapt fields. (Conformance is checked by `test_openapi.py`, not by eyeball.)

- [ ] **Step 5: Run the endpoint + OpenAPI + collision tests; expect PASS.**
```bash
cd ~/Code/lq-ai/api && .venv/bin/pytest tests/test_message_tool_sources.py tests/test_openapi.py tests/test_endpoints.py -q
```

- [ ] **Step 6: Full api gate + commit.**
```bash
cd ~/Code/lq-ai && ruff format api/ && ruff check api/ && (cd api && .venv/bin/mypy app/api/chats.py)
cd ~/Code/lq-ai/api && .venv/bin/pytest tests/test_message_tool_sources.py -q && cd ~/Code/lq-ai
git add api/app/api/chats.py api/tests/test_endpoints.py api/tests/test_openapi.py docs/api/backend-openapi.yaml api/tests/test_message_tool_sources.py
git commit -s -m "feat(api): GET messages/{id}/sources endpoint + OpenAPI/collision guards (PR6c)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `ToolSource` type + `sourcesApi`

**Files:**
- Modify: `web/src/lib/lq-ai/types.ts` (add `ToolSource` near `Citation` ~line 229)
- Create: `web/src/lib/lq-ai/api/sources.ts`
- Modify: `web/src/lib/lq-ai/api/index.ts` (export `sourcesApi`, mirror `citationsApi`)
- Create: `web/src/lib/lq-ai/__tests__/sources-api.test.ts`

**Interfaces:**
- Produces (consumed by Tasks 6–7): `ToolSource` interface; `sourcesApi.getMessageSources(chatId, messageId): Promise<ToolSource[]>`.

**Gate:** Vitest — `getMessageSources` calls the right path + returns the array (mock the api client like the existing citations-api test does); `svelte-check` clean.

- [ ] **Step 1: Read `web/src/lib/lq-ai/api/citations.ts`** and its test (`grep -rl "getMessageCitations" web/src/lib/lq-ai/__tests__/`) to mirror the request helper + the test's client-mock pattern exactly.

- [ ] **Step 2: Write the failing api test** (`__tests__/sources-api.test.ts`), mirroring the citations-api test. If citations has no standalone api test, write a minimal one asserting the URL:
```ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as client from '../api/client';
import { sourcesApi } from '../api/sources';

describe('sourcesApi.getMessageSources', () => {
	beforeEach(() => vi.restoreAllMocks());
	it('GETs the sources path and returns the array', async () => {
		const rows = [{ id: 's1', message_id: 'm1', source_kind: 'caselaw', label: 'Roe v. Wade', subtitle: null, url: null, external_ref: '42', provider: 'courtlistener', tool: 'search_case_law', created_at: '2026-01-01T00:00:00Z' }];
		const spy = vi.spyOn(client, 'apiRequest').mockResolvedValue(rows as never);
		const out = await sourcesApi.getMessageSources('c1', 'm1');
		expect(spy).toHaveBeenCalledWith('/chats/c1/messages/m1/sources');
		expect(out).toEqual(rows);
	});
});
```
Adjust the import + the asserted call signature to match how `citations.ts` actually invokes `apiRequest` (path encoding, options object) — copy its exact shape.

- [ ] **Step 3: Run; expect FAIL** (module missing).

- [ ] **Step 4: Add the `ToolSource` type** (`types.ts`, near `Citation`):
```ts
export interface ToolSource {
	id: string;
	message_id: string;
	source_kind: string;
	label: string;
	subtitle?: string | null;
	url?: string | null;
	external_ref?: string | null;
	provider: string;
	tool: string;
	created_at?: string;
}
```

- [ ] **Step 5: Implement `api/sources.ts`** (mirror `citations.ts` exactly — same `apiRequest` call style + encodeURIComponent):
```ts
/** /api/v1/chats/{chat_id}/messages/{message_id}/sources — external-source provenance (PR6c). */
import { apiRequest } from './client';
import type { ToolSource } from '../types';

export const sourcesApi = {
	getMessageSources(chatId: string, messageId: string): Promise<ToolSource[]> {
		return apiRequest<ToolSource[]>(
			`/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(messageId)}/sources`
		);
	}
};
```
Match `citations.ts`'s actual export style (object vs bare function) — if `citationsApi` is assembled in `api/index.ts`, follow that instead and adapt this test's import.

- [ ] **Step 6: Export** `sourcesApi` from `web/src/lib/lq-ai/api/index.ts` alongside `citationsApi`.

- [ ] **Step 7: Run; expect PASS** + `svelte-check`.
```bash
cd ~/Code/lq-ai/web && npx vitest run src/lib/lq-ai/__tests__/sources-api.test.ts && npm run check:lq-ai 2>&1 | tail -3
```

- [ ] **Step 8: Commit** (`git add web/src/lib/lq-ai/types.ts web/src/lib/lq-ai/api/sources.ts web/src/lib/lq-ai/api/index.ts web/src/lib/lq-ai/__tests__/sources-api.test.ts`).

---

## Task 6: `ProvenancePill` caselaw kind + `ToolSourcesPanel.svelte`

**Files:**
- Modify: `web/src/lib/lq-ai/components/ProvenancePill.svelte` (add `caselaw` to the kind union + its label/style)
- Create: `web/src/lib/lq-ai/components/ToolSourcesPanel.svelte`
- Reference (mirror chrome): `web/src/lib/lq-ai/components/M2Citations.svelte`
- Create: `web/src/lib/lq-ai/__tests__/ToolSourcesPanel.test.ts`

**Interfaces:**
- Consumes: Task 5 `ToolSource`.
- Produces (consumed by Task 7): `ToolSourcesPanel` props `sources: ToolSource[]`; `ProvenancePill` `kind="caselaw"`.

**Gate:** Vitest on the panel's `<script context="module">` copy helper (`sourcesPillLabel(n)` singular/plural); `svelte-check` clean.

- [ ] **Step 1: Read `ProvenancePill.svelte`** — note its `kind` union (`'skill'|'tier'|'provider'|'kb'|'audit'|'enhanced'`) and how each kind maps to an icon/label/class. Read `M2Citations.svelte` for the sidecar chrome (container classes, header, list rows, `data-testid`s).

- [ ] **Step 2: Write the failing helper test** (`__tests__/ToolSourcesPanel.test.ts`):
```ts
import { describe, expect, it } from 'vitest';
import { sourcesPillLabel } from '../components/ToolSourcesPanel.svelte';

describe('sourcesPillLabel', () => {
	it('singular vs plural', () => {
		expect(sourcesPillLabel(1)).toBe('1 source consulted');
		expect(sourcesPillLabel(3)).toBe('3 sources consulted');
	});
});
```

- [ ] **Step 3: Run; expect FAIL** (module missing).

- [ ] **Step 4: Add the `caselaw` kind to `ProvenancePill.svelte`** — extend the `kind` union type with `'caselaw'`, and add its branch to the icon/label/class maps (icon `⚖`, neutral/indigo styling consistent with the others). Keep existing kinds untouched.

- [ ] **Step 5: Implement `ToolSourcesPanel.svelte`** (mirror `M2Citations.svelte` chrome; Svelte 4 `export let`):
```svelte
<script context="module" lang="ts">
	/** Pill copy helper (tested without @testing-library, per house pattern). */
	export function sourcesPillLabel(n: number): string {
		return `${n} source${n === 1 ? '' : 's'} consulted`;
	}
</script>

<script lang="ts">
	import type { ToolSource } from '../types';
	export let sources: ToolSource[] = [];
	let expanded = false;
</script>

{#if sources.length > 0}
	<div class="lq-sources" data-testid="lq-ai-tool-sources">
		<button
			type="button"
			class="lq-sources-header"
			data-testid="lq-ai-tool-sources-toggle"
			on:click={() => (expanded = !expanded)}
		>
			⚖ Sources consulted ({sources.length})
		</button>
		{#if expanded}
			<ul class="lq-sources-list">
				{#each sources as s (s.id)}
					<li class="lq-source-row" data-testid="lq-ai-tool-source-row">
						<span class="lq-source-label">{s.label}</span>
						{#if s.subtitle}<span class="lq-source-sub">{s.subtitle}</span>{/if}
						{#if s.url}
							<a class="lq-source-link" href={s.url} target="_blank" rel="noopener">View on CourtListener ↗</a>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</div>
{/if}

<style>
	/* Mirror M2Citations' sidecar styling — copy its container/header/list classes
	   and adapt names. Keep the link as plain text (never @html). */
</style>
```
Fill the `<style>` by copying `M2Citations.svelte`'s sidecar look (muted card, small text). Render `s.label`/`s.subtitle` as plain interpolation — never `{@html}`. Default `expanded=false` so it starts collapsed.

- [ ] **Step 6: Run; expect PASS** + `svelte-check`.
```bash
cd ~/Code/lq-ai/web && npx vitest run src/lib/lq-ai/__tests__/ToolSourcesPanel.test.ts && npm run check:lq-ai 2>&1 | tail -3
```

- [ ] **Step 7: Commit** (`git add web/src/lib/lq-ai/components/ProvenancePill.svelte web/src/lib/lq-ai/components/ToolSourcesPanel.svelte web/src/lib/lq-ai/__tests__/ToolSourcesPanel.test.ts`).

---

## Task 7: `MessageBubble` lazy-fetch + render

**Files:**
- Modify: `web/src/lib/lq-ai/components/MessageBubble.svelte` (mirror the `fetchedCitations` lazy-fetch ~lines 85-115; render in the assistant branch)
- Test: none new (covered by Tasks 5–6 units + Task 9 visual)

**Interfaces:**
- Consumes: Task 5 `sourcesApi`/`ToolSource`; Task 6 `ToolSourcesPanel` + `ProvenancePill` caselaw kind.

**Gate:** `svelte-check` clean; Task 9 build + headless render confirms the panel + pill.

- [ ] **Step 1: Add imports + state.** In `MessageBubble.svelte`, import `ToolSourcesPanel`, `sourcesApi`, and `type ToolSource`. Add state mirroring citations:
```ts
	let fetchedSources: ToolSource[] | null = null;
	let sourcesFetchInflight = false;

	async function loadSources(chatId: string, messageId: string): Promise<void> {
		sourcesFetchInflight = true;
		try {
			fetchedSources = await sourcesApi.getMessageSources(chatId, messageId);
		} catch (err) {
			if (!(err instanceof LQAIApiError) || err.status !== 404) {
				console.warn('[PR6c] failed to load tool sources', err);
			}
			fetchedSources = [];
		} finally {
			sourcesFetchInflight = false;
		}
	}
```
(`LQAIApiError` is already imported for citations.)

- [ ] **Step 2: Add the guarded reactive fetch** next to the citations one (~line 106):
```ts
	$: if (
		message.role === 'assistant' &&
		message.id &&
		message.chat_id &&
		!isStreaming &&
		fetchedSources === null &&
		!sourcesFetchInflight
	) {
		void loadSources(message.chat_id, message.id);
	}
```

- [ ] **Step 3: Render the pill + panel** in the assistant branch. Add a `caselaw` pill into the metadata row (near the `AppliedSkillsChip`, ~line 197) when sources exist, and the panel after the citations sidecar (~after line 272):
```svelte
			{#if fetchedSources && fetchedSources.length > 0}
				<ProvenancePill kind="caselaw" summary={sourcesPillLabel(fetchedSources.length)} />
			{/if}
```
```svelte
		{#if fetchedSources && fetchedSources.length > 0}
			<ToolSourcesPanel sources={fetchedSources} />
		{/if}
```
Import `sourcesPillLabel` from `ToolSourcesPanel.svelte` (module-context export) and `ProvenancePill` is already imported. If `ProvenancePill`'s `summary` prop differs, match its actual prop name (read it in Task 6 Step 1).

- [ ] **Step 4: `svelte-check` clean** (`cd ~/Code/lq-ai/web && npm run check:lq-ai 2>&1 | tail -5`). Run the full lq-ai Vitest suite to confirm no regression: `npx vitest run src/lib/lq-ai/__tests__/ 2>&1 | tail -4`.

- [ ] **Step 5: Commit** (`git add web/src/lib/lq-ai/components/MessageBubble.svelte`).

---

## Task 8: D6 narrative flip — case-law provenance "shipped"

**Files:**
- Modify: `web/static/learn/playgrounds/governed-tool-flow.html` (the `Availability` block)
- Modify: `web/src/routes/lq-ai/learn/how/+page.svelte` (section 17 sentence)
- Modify: `README.md` (legal-research+MCP paragraph availability sentence)

**Gate:** the three availability claims now say case-law provenance ships; "coming next" points to 6d (case-law skill + retiring the MCP stub); `svelte-check` clean.

- [ ] **Step 1: Explorer `Availability` block** (`governed-tool-flow.html`, ~lines 257-265). Move case-law provenance into "Available today"; change "Coming in the next release" to point to **6d**: "the case-law research skill + retiring the legacy OpenWebUI MCP stub."

- [ ] **Step 2: Learn section 17 sentence** (`how/+page.svelte`, ~lines 836-839). Fold "rich case-law provenance" into "Available today"; repoint "Coming next" to 6d.

- [ ] **Step 3: README sentence** (the legal-research+MCP paragraph, ~line 83). Same flip: provenance shipped; "Coming next" → 6d.

- [ ] **Step 4: Grep gate.**
```bash
cd ~/Code/lq-ai && grep -rn "next release\|coming next\|Coming next\|Coming in the next" web/static/learn/playgrounds/governed-tool-flow.html web/src/routes/lq-ai/learn/how/+page.svelte README.md
```
Confirm every remaining hit refers to **6d** (case-law skill / MCP-stub retirement), not provenance.

- [ ] **Step 5: `svelte-check` clean; commit** (`git add` the three files).

---

## Task 9: Verification + ship

**Files:** none (verification + ship).

- [ ] **Step 1: Full backend gate.**
```bash
cd ~/Code/lq-ai && ruff format api/ && ruff check api/
cd ~/Code/lq-ai/api && .venv/bin/mypy app && .venv/bin/pytest tests/test_message_tool_sources.py tests/test_openapi.py tests/test_endpoints.py -q
```
Expected: ruff clean, mypy clean, pytest green (incl. OpenAPI conformance at 134 paths).

- [ ] **Step 2: Full web gate.**
```bash
cd ~/Code/lq-ai/web && npx vitest run src/lib/lq-ai/__tests__/ 2>&1 | tail -5 && npm run check:lq-ai 2>&1 | tail -3
```
Expected: Vitest green; svelte-check 0 errors.

- [ ] **Step 3: Build + visual check.** Rebuild `web` (pre-built bundle) and the api trio together (revision-mismatch guard):
```bash
cd ~/Code/lq-ai && docker compose up -d --build web api arq-worker ingest-worker 2>&1 | tail -6
```
Then in a chat, run a case-law lookup (or inject `message_tool_sources` rows for an assistant message) and confirm: the assistant turn shows the `⚖ N sources consulted` pill + the collapsible "Sources consulted" panel listing each case (label, court·date, CourtListener link); a turn with no sources is unchanged. A headless static render of `ToolSourcesPanel` (populated + empty) is an acceptable substitute screenshot (mirror the 6a/6b harness with the cached `chrome-headless-shell`). Capture for the PR.

- [ ] **Step 4: Independent review.** Dispatch an adversarial reviewer on `git diff main...HEAD` — focus: dedup correctness across rounds, the 3 persist sites all wired, ownership 404, no `{@html}` on source fields, OpenAPI conformance. Apply material findings.

- [ ] **Step 5: Push both remotes + open the PR.**
```bash
cd ~/Code/lq-ai && git push -u origin feat/pr6c-external-source-citations && git push -u tucuxi feat/pr6c-external-source-citations
gh pr create --repo LegalQuants/lq-ai --base main --head feat/pr6c-external-source-citations \
  --title "PR6c/WS5: external-source citations — case-law retrieval provenance" \
  --body-file <(printf '%s\n' "<PR body: the new message_tool_sources table + 0055; retrieval-provenance capture in the tool-loop; the read endpoint; the inline Sources-consulted sidecar + caselaw pill; the D6 flip; not security-gated (product table + read endpoint); screenshots; DE-350 (generic MCP) deferred>")
```
Frontend + api product code → **self-merge after CI green**. After merge, sync tucuxi main. The D6 obligation for 6c is discharged by Task 8.

---

## Self-Review (run before dispatching execution)

**Spec coverage:** New `message_tool_sources` table + migration 0055 (spec §Data model) → Task 1 ✓. `extract_tool_sources` case-law-only + dedup + retrieval-provenance (§Backend/Capture, §Non-goals) → Task 2 ✓. Persist at turn-end mirroring citations (§Backend/Persist) → Task 3 ✓. Read endpoint + collision guards + OpenAPI (§Backend/Endpoint) → Task 4 ✓. `ToolSource` type + api (§Frontend) → Task 5 ✓. `caselaw` pill + inline `ToolSourcesPanel` sidecar (§Frontend, §Panel placement) → Task 6 ✓. `MessageBubble` lazy-fetch like citations, no SSE change (§Architecture) → Task 7 ✓. D6 flip → 6d (§D6) → Task 8 ✓. Non-goals respected: case-law-only (Task 2 returns [] for other tools), no marker grounding, no drawer, no SSE frame, `message_citations` untouched, no cost model. DE-350 noted (§9).

**Placeholder scan:** Deterministic backend code (model, migration, extractor, persist, endpoint) is verbatim. Test setup uses a module-local `owner_user` fixture + `_assistant_message` helper + a `client` fixture copied verbatim from `tests/test_chat_citations.py` (no fictional shared fixtures — there are none in `conftest.py`); the auth token uses the real `create_access_token(user_id, email, is_admin)` signature. Svelte components are concrete skeletons that name the file to mirror (`M2Citations`, `ProvenancePill`) and the exact data-testids — the house-style classes are copied from the live files (as 6a/6b did). PR body is a ship-time fill-in.

**Type/signature consistency:** `ToolSourceRecord(source_kind, label, subtitle, url, external_ref, provider, tool)` identical across Tasks 2 (def), 3 (persist), and the model columns in Task 1. `extract_tool_sources(tool_name, data) -> list[ToolSourceRecord]` consistent Tasks 2↔(loop). `LoopFinal.tool_sources` set in Task 2, read in Task 3. `MessageToolSource` columns identical across Task 1 (model + migration), Task 3 (persist), Task 4 (serialize). `ToolSource` TS fields mirror the endpoint's serialized dict (Task 4 ↔ Task 5). `sourcesApi.getMessageSources(chatId, messageId)` consistent Tasks 5↔7. `sourcesPillLabel(n)` consistent Tasks 6↔7. Path string identical across the endpoint, `IMPLEMENTED_ROUTES`, `EXPECTED_PATHS`, and `backend-openapi.yaml`.

**Execution note:** Backend Tasks 1–4 are clean subagent-driven TDD (pytest red/green); frontend Tasks 5–7 + docs Task 8 are inline-friendly (Vitest + svelte-check + headless visual). The plan's anchors (file:line) were verified against the tree at write time (`main` = `47d9bed`); the executor must re-grep the three `_persist_message_citations(` sites and the citations-test fixture names before editing, since those are the load-bearing "mirror this" anchors.
