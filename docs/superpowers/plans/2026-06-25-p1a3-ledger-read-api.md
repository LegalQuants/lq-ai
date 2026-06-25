# P1-A3 — Citation Ledger read API + one-click trace — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the populated Citation Ledger as a read endpoint — `GET /api/v1/chats/{chat_id}/ledger` — that resolves each `citation_ledger_entry` to its source identity, the passage(s) read, verification status, and provenance, in one call (ADR 0018 D4).

**Architecture:** A pure-DB read-side resolver (`resolve_ledger_entries`) batch-loads the three referenced artifact tables and shapes plain dicts; a thin chat-scoped GET endpoint adds auth/ownership and an optional `?message_id` turn filter, mirroring the existing `get_citations`/`get_message_sources` siblings. No new egress; no migration.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Pydantic-free plain-dict responses (matching siblings), pytest (`integration` marker) against a throwaway pgvector.

## Global Constraints

- **No new egress** — pure DB reads; no gateway/LLM call. (ADR 0018; P1.)
- **No content in the ledger row** — passages are resolved from the content layer (`MessageCitation.source_text`, `MessageCaselawCitation.source_text`) at read time; `citation_ledger_entry` holds none. (P3.)
- **Ownership parity** — use `_validate_chat_id` + `_load_visible_chat(..., include_archived=True)` exactly as `get_citations`; cross-user/unknown chat → 404; unknown `message_id` in a visible chat → 404; non-UUID → `ValidationError`.
- **Conservative posture** — a dangling/missing referenced row is skipped with a logged warning, never a 500.
- **P10 collision guards land in the same task as the route** (they crash the whole suite at collection if out of sync): `IMPLEMENTED_ROUTES`, `EXPECTED_PATHS`, the pinned count `134 → 135`, and the OpenAPI sketch.
- **Tests:** host venv + throwaway pgvector (`DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test`), conftest auto-migrates. Run `ruff format` + `ruff check` + `mypy app` + `pytest` (coverage no-decrease). No `-m provider`.
- **Commits:** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Read-side resolver `resolve_ledger_entries`

**Files:**
- Modify: `api/app/citation/ledger.py` (add the resolver + a private `_resolve_source` helper alongside the existing `assemble_ledger_entries`)
- Test: `api/tests/integration/test_citation_ledger.py` (add resolver cases to the existing file)

**Interfaces:**
- Consumes: `CitationLedgerEntry`, `MessageCitation`, `MessageCaselawCitation`, `MessageToolSource` ORM models (already importable; `MessageCitation` is in `app.models.chat`).
- Produces: `async def resolve_ledger_entries(db: AsyncSession, *, chat_id: uuid.UUID, message_id: uuid.UUID | None = None) -> list[dict[str, Any]]` — used by Task 2's endpoint.

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/integration/test_citation_ledger.py` (it already imports `select`, the models, `uuid`, and defines the `seeded_message` fixture + `db_session`):

```python
from app.citation.ledger import resolve_ledger_entries  # add to existing imports
from app.models.chat import MessageCitation  # add to existing imports
from app.models.file import File as FileModel  # add to existing imports
from app.models.user import User  # already imported


@pytest.mark.asyncio
async def test_resolve_shapes_all_three_source_kinds(db_session, seeded_message):
    """Each entry resolves to its source block; passages present for quote kinds."""
    mid = seeded_message
    chat_id = (
        await db_session.execute(select(Message.chat_id).where(Message.id == mid))
    ).scalar_one()
    # caselaw citation + its provenance row + a KB-document citation (needs a File FK)
    owner_id = (
        await db_session.execute(select(Chat.owner_id).where(Chat.id == chat_id))
    ).scalar_one()
    f = FileModel(
        owner_id=owner_id,
        filename="doc.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256="0" * 64,
        storage_path=f"k/{uuid.uuid4().hex}",
    )
    db_session.add(f)
    await db_session.flush()
    doc_cite = MessageCitation(
        message_id=mid,
        source_file_id=f.id,
        source_offset_start=0,
        source_offset_end=5,
        source_page=3,
        source_text="hello",
        verified=True,
        verification_method="exact_match",
        verification_confidence=1.0,
    )
    caselaw_cite = MessageCaselawCitation(
        message_id=mid,
        opinion_id=11,
        cluster_id=22,
        source_offset_start=0,
        source_offset_end=5,
        source_text="world",
        verified=True,
        verification_method="tolerant_match",
        verification_confidence=0.95,
    )
    tool_src = MessageToolSource(
        message_id=mid,
        source_kind="caselaw",
        label="Cluster 22",
        subtitle=None,
        url="https://courtlistener.test/22",
        external_ref="22",
        provider="courtlistener",
        tool="get_cluster",
    )
    db_session.add_all([doc_cite, caselaw_cite, tool_src])
    await db_session.flush()
    await assemble_ledger_entries(db_session, message_id=mid)
    await db_session.flush()

    out = await resolve_ledger_entries(db_session, chat_id=chat_id)
    by_kind = {e["source_kind"]: e for e in out}
    assert set(by_kind) == {"kb_document", "caselaw"}  # tool source has source_kind "caselaw"
    # there are three entries (two share source_kind "caselaw"); assert count
    assert len(out) == 3

    kb = next(e for e in out if e["source"]["kind"] == "kb_document")
    assert kb["verification_status"] == "exact_match"
    assert kb["source"]["source_file_id"] == str(f.id)
    assert kb["source"]["passages"] == [
        {"text": "hello", "offset_start": 0, "offset_end": 5, "page": 3}
    ]

    case = next(e for e in out if e["source"]["kind"] == "caselaw")
    assert case["source"]["opinion_id"] == 11
    assert case["source"]["passages"][0]["text"] == "world"
    assert case["confidence"] == 0.95

    prov = next(e for e in out if "passages" not in e["source"])
    assert prov["verification_status"] == "provenance"
    assert prov["source"]["url"] == "https://courtlistener.test/22"
    assert prov["source"]["external_ref"] == "22"


@pytest.mark.asyncio
async def test_resolve_message_id_filter_and_empty(db_session, seeded_message):
    chat_id = (
        await db_session.execute(select(Message.chat_id).where(Message.id == seeded_message))
    ).scalar_one()
    assert await resolve_ledger_entries(db_session, chat_id=chat_id) == []
    # entry under a different message id is excluded by the filter
    src = MessageToolSource(
        message_id=seeded_message, source_kind="mcp", label="x", provider="srv", tool="t"
    )
    db_session.add(src)
    await db_session.flush()
    db_session.add(
        CitationLedgerEntry(
            chat_id=chat_id,
            message_id=seeded_message,
            source_kind="mcp",
            message_tool_source_id=src.id,
            verification_status="provenance",
        )
    )
    await db_session.flush()
    assert len(await resolve_ledger_entries(db_session, chat_id=chat_id, message_id=seeded_message)) == 1
    assert await resolve_ledger_entries(db_session, chat_id=chat_id, message_id=uuid.uuid4()) == []


@pytest.mark.asyncio
async def test_resolve_skips_dangling_reference(db_session, seeded_message, caplog):
    """An entry whose referenced row is absent is skipped, not fatal."""
    chat_id = (
        await db_session.execute(select(Message.chat_id).where(Message.id == seeded_message))
    ).scalar_one()
    # Insert an entry pointing at a tool-source id that does not exist by
    # creating then deleting the row it referenced (FK is ON DELETE CASCADE,
    # so instead point a fresh entry at a random id via raw construction).
    # Simplest: build a valid entry, then None-out the in-memory map by
    # referencing a tool source we never persisted is impossible (FK). So
    # delete the source after the entry to force the resolver's miss path is
    # also blocked by CASCADE. We therefore test the resolver helper directly:
    from app.citation.ledger import _resolve_source

    class _E:
        message_citation_id = uuid.uuid4()
        message_caselaw_citation_id = None
        message_tool_source_id = None
        id = uuid.uuid4()

    assert _resolve_source(_E(), {}, {}, {}) is None
```

(The FK constraints make a truly dangling row hard to persist, so the dangling-reference path is asserted at the helper level — that is the unit the resolver delegates to, and it is what runs in the conservative skip branch.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_citation_ledger.py -v`
Expected: the three new tests FAIL with `ImportError: cannot import name 'resolve_ledger_entries'` (and `_resolve_source`).

- [ ] **Step 3: Implement the resolver**

Add to `api/app/citation/ledger.py`. First extend the imports at the top:

```python
import logging
from typing import Any

from app.models.chat import Message, MessageCitation  # Message already imported; add MessageCitation
```

Add a module logger if not present: `log = logging.getLogger(__name__)`.

Then append:

```python
def _resolve_source(
    entry: CitationLedgerEntry,
    docs: dict[uuid.UUID, MessageCitation],
    caselaw: dict[uuid.UUID, MessageCaselawCitation],
    tools: dict[uuid.UUID, MessageToolSource],
) -> dict[str, Any] | None:
    """Resolve an entry's single referenced row to a source block, or None if absent."""
    if entry.message_citation_id is not None:
        c = docs.get(entry.message_citation_id)
        if c is None:
            return None
        return {
            "kind": "kb_document",
            "source_file_id": str(c.source_file_id),
            "passages": [
                {
                    "text": c.source_text,
                    "offset_start": c.source_offset_start,
                    "offset_end": c.source_offset_end,
                    "page": c.source_page,
                }
            ],
        }
    if entry.message_caselaw_citation_id is not None:
        cc = caselaw.get(entry.message_caselaw_citation_id)
        if cc is None:
            return None
        return {
            "kind": "caselaw",
            "opinion_id": cc.opinion_id,
            "cluster_id": cc.cluster_id,
            "passages": [
                {
                    "text": cc.source_text,
                    "offset_start": cc.source_offset_start,
                    "offset_end": cc.source_offset_end,
                }
            ],
        }
    if entry.message_tool_source_id is not None:
        ts = tools.get(entry.message_tool_source_id)
        if ts is None:
            return None
        return {
            "kind": ts.source_kind,
            "label": ts.label,
            "subtitle": ts.subtitle,
            "url": ts.url,
            "external_ref": ts.external_ref,
            "tool": ts.tool,
        }
    return None


async def resolve_ledger_entries(
    db: AsyncSession, *, chat_id: uuid.UUID, message_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """Return ledger entries for a chat (optionally one turn), each resolved to its
    source identity + passage(s) read + status + provenance. Pure DB; no egress.

    Passage text is resolved from the content layer at read time; the ledger row
    itself holds no content (ADR 0018 D4/D5).
    """
    stmt = select(CitationLedgerEntry).where(CitationLedgerEntry.chat_id == chat_id)
    if message_id is not None:
        stmt = stmt.where(CitationLedgerEntry.message_id == message_id)
    stmt = stmt.order_by(CitationLedgerEntry.created_at, CitationLedgerEntry.id)
    entries = (await db.execute(stmt)).scalars().all()
    if not entries:
        return []

    doc_ids = {e.message_citation_id for e in entries if e.message_citation_id is not None}
    case_ids = {
        e.message_caselaw_citation_id for e in entries if e.message_caselaw_citation_id is not None
    }
    tool_ids = {e.message_tool_source_id for e in entries if e.message_tool_source_id is not None}

    docs: dict[uuid.UUID, MessageCitation] = {}
    if doc_ids:
        docs = {
            r.id: r
            for r in (
                await db.execute(select(MessageCitation).where(MessageCitation.id.in_(doc_ids)))
            )
            .scalars()
            .all()
        }
    caselaw: dict[uuid.UUID, MessageCaselawCitation] = {}
    if case_ids:
        caselaw = {
            r.id: r
            for r in (
                await db.execute(
                    select(MessageCaselawCitation).where(MessageCaselawCitation.id.in_(case_ids))
                )
            )
            .scalars()
            .all()
        }
    tools: dict[uuid.UUID, MessageToolSource] = {}
    if tool_ids:
        tools = {
            r.id: r
            for r in (
                await db.execute(
                    select(MessageToolSource).where(MessageToolSource.id.in_(tool_ids))
                )
            )
            .scalars()
            .all()
        }

    out: list[dict[str, Any]] = []
    for e in entries:
        source = _resolve_source(e, docs, caselaw, tools)
        if source is None:
            log.warning("ledger entry %s references a missing source row; skipping", e.id)
            continue
        out.append(
            {
                "id": str(e.id),
                "message_id": str(e.message_id),
                "source_kind": e.source_kind,
                "verification_status": e.verification_status,
                "confidence": e.confidence,
                "provider": e.provider,
                "retrieved_at": e.retrieved_at.isoformat() if e.retrieved_at else None,
                "treatment_id": str(e.treatment_id) if e.treatment_id else None,
                "created_at": e.created_at.isoformat(),
                "source": source,
            }
        )
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_citation_ledger.py -v`
Expected: all tests PASS (the 4 pre-existing assembler tests + the 3 new resolver tests).

- [ ] **Step 5: Lint + type-check**

Run: `cd api && .venv/bin/ruff format app/citation/ledger.py tests/integration/test_citation_ledger.py && .venv/bin/ruff check app/citation/ledger.py && .venv/bin/mypy app/citation/ledger.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add api/app/citation/ledger.py api/tests/integration/test_citation_ledger.py
git commit -s -m "feat(citation): ledger read-side resolver (P1-A3)

resolve_ledger_entries batch-loads the three referenced artifact tables
and shapes each entry to source identity + passage(s) read + status +
provenance. Pure DB; passages resolved from the content layer at read
time so the ledger row holds no content (ADR 0018 D4/D5).

Refs ADR 0018 D4.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `GET /chats/{chat_id}/ledger` endpoint + P10 collision guards + OpenAPI

**Files:**
- Modify: `api/app/api/chats.py` (add the endpoint near `get_message_sources` ~line 1780; extend the `app.citation.ledger` import; add `get_chat_ledger` to `__all__`)
- Modify: `api/tests/test_endpoints.py` (add the route to `IMPLEMENTED_ROUTES`)
- Modify: `api/tests/test_openapi.py` (add the path to `EXPECTED_PATHS`; bump count 134 → 135)
- Modify: `docs/api/backend-openapi.yaml` (add the path block + a `LedgerEntry` schema)
- Test: `api/tests/integration/test_ledger_endpoint.py` (new)

**Interfaces:**
- Consumes: `resolve_ledger_entries` (Task 1); existing `_validate_chat_id`, `_load_visible_chat`, `ActiveUser`, `get_db`, `Message`, `ValidationError`, `NotFound` (all already in `chats.py`).
- Produces: `GET /api/v1/chats/{chat_id}/ledger` → `{"chat_id": str, "entries": [...]}`.

- [ ] **Step 1: Write the failing endpoint test**

Create `api/tests/integration/test_ledger_endpoint.py`:

```python
"""GET /api/v1/chats/{chat_id}/ledger — one-click trace read surface (P1-A3)."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.citation.ledger import assemble_ledger_entries
from app.db.session import get_db
from app.main import app
from app.models.chat import Chat, Message, MessageCitation
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.file import File as FileModel
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User
from app.security import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _override_get_db(session):
    async def _dep():
        yield session

    return _dep


@pytest_asyncio.fixture
async def seeded(db_session):
    user = User(
        email=f"led-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        role="member",
    )
    db_session.add(user)
    await db_session.flush()
    chat = Chat(owner_id=user.id, title="ledger")
    db_session.add(chat)
    await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="a")
    db_session.add(msg)
    await db_session.flush()
    f = FileModel(
        owner_id=user.id,
        filename="d.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        hash_sha256="0" * 64,
        storage_path=f"k/{uuid.uuid4().hex}",
    )
    db_session.add(f)
    await db_session.flush()
    db_session.add(
        MessageCitation(
            message_id=msg.id,
            source_file_id=f.id,
            source_offset_start=0,
            source_offset_end=5,
            source_text="hello",
            verified=True,
            verification_method="exact_match",
            verification_confidence=1.0,
        )
    )
    await db_session.flush()
    await assemble_ledger_entries(db_session, message_id=msg.id)
    await db_session.flush()
    return user, chat, msg


@pytest_asyncio.fixture
async def client(db_session):
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


def _auth(user):
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_ledger_returns_resolved_entries(client, seeded):
    user, chat, msg = seeded
    r = await client.get(f"/api/v1/chats/{chat.id}/ledger", headers=_auth(user))
    assert r.status_code == 200
    body = r.json()
    assert body["chat_id"] == str(chat.id)
    assert len(body["entries"]) == 1
    e = body["entries"][0]
    assert e["source"]["kind"] == "kb_document"
    assert e["source"]["passages"][0]["text"] == "hello"
    assert e["verification_status"] == "exact_match"


@pytest.mark.asyncio
async def test_ledger_message_id_filter(client, seeded):
    user, chat, msg = seeded
    r = await client.get(
        f"/api/v1/chats/{chat.id}/ledger?message_id={msg.id}", headers=_auth(user)
    )
    assert r.status_code == 200
    assert len(r.json()["entries"]) == 1
    r2 = await client.get(
        f"/api/v1/chats/{chat.id}/ledger?message_id={uuid.uuid4()}", headers=_auth(user)
    )
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_ledger_cross_user_404(client, db_session, seeded):
    _, chat, _ = seeded
    other = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        role="member",
    )
    db_session.add(other)
    await db_session.flush()
    r = await client.get(f"/api/v1/chats/{chat.id}/ledger", headers=_auth(other))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_ledger_non_uuid_422(client, seeded):
    user, _, _ = seeded
    r = await client.get("/api/v1/chats/not-a-uuid/ledger", headers=_auth(user))
    assert r.status_code == 422
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_ledger_endpoint.py -v`
Expected: FAIL — all return 404 (route not registered) or the suite errors at collection until guards are updated. (`test_ledger_non_uuid_422` will currently 404, not 422.)

- [ ] **Step 3: Add the endpoint**

In `api/app/api/chats.py`, extend the existing ledger import (it imports `assemble_ledger_entries`):

```python
from app.citation.ledger import assemble_ledger_entries, resolve_ledger_entries
```

Add the endpoint immediately after `get_message_sources` (after ~line 1780):

```python
@router.get(
    "/{chat_id}/ledger",
    summary="Citation Ledger for a chat (one-click trace) — P1-A3",
)
async def get_chat_ledger(
    chat_id: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    message_id: str | None = None,
) -> dict[str, Any]:
    """Return the Citation Ledger for a chat, each entry resolved to its source
    identity + passage(s) read + verification status + provenance (ADR 0018 D4).

    Chat-scoped; ``?message_id=`` narrows to a single assistant turn. Ownership is
    enforced as in :func:`get_citations` (cross-user → 404). The ledger row holds
    no content — passages are resolved from the content layer at read time (P3).
    """
    cid = _validate_chat_id(chat_id)
    mid: uuid.UUID | None = None
    if message_id is not None:
        try:
            mid = uuid.UUID(message_id)
        except ValueError as exc:
            raise ValidationError(
                "message_id must be a UUID", details={"message_id": message_id}
            ) from exc

    await _load_visible_chat(db, cid, user.id, include_archived=True)

    if mid is not None:
        msg_stmt = select(Message.id).where(Message.id == mid, Message.chat_id == cid)
        if (await db.execute(msg_stmt)).scalar_one_or_none() is None:
            raise NotFound(f"Message {mid} not found.", details={"message_id": str(mid)})

    entries = await resolve_ledger_entries(db, chat_id=cid, message_id=mid)
    return {"chat_id": str(cid), "entries": entries}
```

Add `"get_chat_ledger"` to the module's `__all__` list (near the bottom where `"get_citations"` appears ~line 3674).

- [ ] **Step 4: Update the P10 collision guards**

In `api/tests/test_endpoints.py`, after the `("GET", "/api/v1/chats/{chat_id}/messages/{message_id}/sources"),` line, add:

```python
    ("GET", "/api/v1/chats/{chat_id}/ledger"),
```

In `api/tests/test_openapi.py`, after `"/api/v1/chats/{chat_id}/messages/{message_id}/sources",` (line ~55) add:

```python
        "/api/v1/chats/{chat_id}/ledger",
```

And update the count block (line ~328): add a comment and bump the assertion:

```python
    # P1-A3 adds one new path (134 -> 135):
    # /api/v1/chats/{chat_id}/ledger
    assert len(actual) == 135
```

- [ ] **Step 5: Update the OpenAPI sketch**

In `docs/api/backend-openapi.yaml`, add this path (mirroring the `/sources` block style):

```yaml
  /api/v1/chats/{chat_id}/ledger:
    parameters:
      - name: chat_id
        in: path
        required: true
        schema: {type: string, format: uuid}
      - name: message_id
        in: query
        required: false
        schema: {type: string, format: uuid}
        description: Narrow to a single assistant turn.
    get:
      tags: [messages]
      summary: Citation Ledger for a chat — one-click trace (P1-A3)
      responses:
        '200':
          description: Ledger entries resolved to source + passage(s) + status + provenance
          content:
            application/json:
              schema:
                type: object
                properties:
                  chat_id: {type: string, format: uuid}
                  entries:
                    type: array
                    items: {$ref: '#/components/schemas/LedgerEntry'}
        '404':
          description: Chat (or filtered message) does not exist
          content:
            application/json:
              schema: {$ref: '#/components/schemas/Error'}
```

And add to `components/schemas`:

```yaml
    LedgerEntry:
      type: object
      description: One citation-ledger entry resolved to its source (ADR 0018 D4).
      properties:
        id: {type: string, format: uuid}
        message_id: {type: string, format: uuid}
        source_kind: {type: string, enum: [kb_document, caselaw, mcp]}
        verification_status: {type: string}
        confidence: {type: number, nullable: true}
        provider: {type: string, nullable: true}
        retrieved_at: {type: string, format: date-time, nullable: true}
        treatment_id: {type: string, format: uuid, nullable: true}
        created_at: {type: string, format: date-time}
        source:
          type: object
          description: Resolved source block; shape varies by kind. Quote kinds carry passages[].
```

- [ ] **Step 6: Run the endpoint tests + the guard tests**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest tests/integration/test_ledger_endpoint.py tests/test_endpoints.py tests/test_openapi.py -v`
Expected: all PASS (endpoint 200/404/422 cases; `test_openapi` count = 135; `test_endpoints` route present).

- [ ] **Step 7: Full gate**

Run: `cd api && .venv/bin/ruff format app tests && .venv/bin/ruff check app tests && .venv/bin/mypy app && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest -q`
Expected: ruff + mypy clean; full suite green (no decrease).

- [ ] **Step 8: Commit**

```bash
git add api/app/api/chats.py api/tests/test_endpoints.py api/tests/test_openapi.py docs/api/backend-openapi.yaml api/tests/integration/test_ledger_endpoint.py
git commit -s -m "feat(citation): GET /chats/{id}/ledger one-click trace endpoint (P1-A3)

Chat-scoped Citation Ledger read surface resolving each entry to source
identity + passage(s) read + status + provenance, with an optional
?message_id turn filter (ADR 0018 D4). Ownership parity with
get_citations; P10 guards updated (route, EXPECTED_PATHS 134->135,
OpenAPI sketch + LedgerEntry schema).

Refs ADR 0018 D4/D5.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- D4 one-click trace, embedded resolution → Task 1 resolver + Task 2 endpoint. ✓
- Chat-scoped + `?message_id` filter → Task 2. ✓
- Plain-dict object response (`{entries:[...]}`, B1 adds `gates` later) → Task 2. ✓
- P3 no content in ledger row (resolve at read time) → Task 1 (passages from content rows). ✓
- Ownership parity / 404 / 422 → Task 2 tests. ✓
- Dangling-reference skip → Task 1 `_resolve_source` + test. ✓
- P10 guards (route, EXPECTED_PATHS, count 134→135, OpenAPI) → Task 2 Steps 4–5. ✓
- No new egress; no migration → both tasks pure DB. ✓

**Placeholder scan:** No TBD/TODO; every code step shows code; commands have expected output. ✓

**Type consistency:** `resolve_ledger_entries(db, *, chat_id, message_id=None) -> list[dict]` and `_resolve_source(entry, docs, caselaw, tools) -> dict | None` are used identically in Task 1 (definition + tests) and Task 2 (endpoint call). Response object `{"chat_id", "entries"}` matches the endpoint test assertions. ✓

**Note for executor:** the `File` model constructor kwargs are verified against `api/app/models/file.py` (`owner_id`, `filename`, `mime_type`, `size_bytes`, `hash_sha256`, `storage_path`; `ingestion_status` has a server default). The KB-document case needs a real `files` row because `message_citations.source_file_id` is a non-null FK. Confirm the `User` model accepts `hashed_password` / `role` (the existing `seeded_message` fixture in `test_citation_ledger.py` uses exactly these).
