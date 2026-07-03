# Referenced Files in Chat — Backend (Phase 1 MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a chat message carry a user-selected set of matter documents (`referenced_file_ids`) that are retrieved as grounding chunks so the assistant's answer returns verified, deep-linkable citations.

**Architecture:** Add a `referenced_file_ids` field to the message-send request. Validate each id is caller-owned, `ready`, and in a Knowledge Base attached to the chat's project (matter scope, KB-only MVP). Retrieve chunks for those files via a new file-scoped hybrid search, merge them into the existing `retrieved_chunks` local in `send_message` so the shipped context-block + Citation Engine path cite them unchanged. Write a counts-only audit row.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, Postgres + pgvector, pytest (unit + integration against real Postgres in Docker).

**Companion docs:** spec `docs/superpowers/specs/2026-07-02-chat-at-mention-file-retrieval-design.md`; scope `summary_scope.md`; overlap/compliance `docpicker.md`. Frontend (composer picker + `@`-mention) is a **separate plan** — this plan is backend-only and independently testable via the API.

## Global Constraints

- Python: `ruff format` + `ruff check` both pass (separate CI gates). Type annotations on all public functions. `async def` for I/O. Raise from `app.errors` hierarchy, never bare `Exception`. (CLAUDE.md → Code style)
- Coverage target 80%; every new endpoint/handler path gets unit + integration tests; this is a feature so it also gets an integration regression for the citation wiring. (CLAUDE.md → Testing)
- **No raw payloads in audit/log rows (P3):** audit rows carry ids/counts/digests only — never file content or the query text.
- **Fail restrictive (P4):** an unauthorized / out-of-matter / not-`ready` referenced id is dropped or 404'd (id-probing-safe), never an error-open or broad-search fallback.
- **Atomic audit (P5):** audit writes flush inside the caller's transaction; the audit row for referenced files commits on its own boundary exactly like `inference.message_files_attached`.
- **Contract is truth (P10):** update `docs/api/backend-openapi.yaml`, `docs/PRD.md`, and add an ADR in the same PR. No new route in this plan (reuses `GET /kb/{id}/files`), so `IMPLEMENTED_ROUTES` / `EXPECTED_PATHS` are unchanged.
- **New field is additive/non-breaking:** omitting `referenced_file_ids` reproduces today's behavior exactly.
- Dev-env hard rules (CLAUDE.md): never host-side `alembic upgrade` on the dev DB; never `docker compose down -v`; conftest auto-migrates a throwaway `pgvector/pgvector:pg16` container for integration tests.

## File Structure

- `api/app/schemas/chats.py` — add `MESSAGE_REFERENCED_FILES_MAX_LEN`, `MessageCreateRequest.referenced_file_ids`, `MessagePostResponse.applied_referenced_file_ids`. (Request/response surface; one responsibility.)
- `api/app/knowledge/retrieval.py` — refactor the combine+hydrate tail of `hybrid_search` into a shared helper; add `hybrid_search_files` (file-id-scoped) reusing it. (Retrieval primitives.)
- `api/app/api/chats.py` — add `_validate_referenced_file_ids`, `_retrieve_referenced_file_context`, `_merge_retrieved_chunks`; wire them into `send_message`. (Chat handler.)
- `api/tests/unit/test_chats_schema.py` (or existing schema test module) — schema validation tests.
- `api/tests/integration/test_referenced_files_send.py` — new integration test module for the end-to-end send + citation wiring.
- `api/tests/unit/test_retrieval_files.py` — unit/integration for `hybrid_search_files`.
- `docs/api/backend-openapi.yaml`, `docs/PRD.md`, `docs/adr/00NN-referenced-file-ids-chat.md` — contract + docs.

---

### Task 1: Add `referenced_file_ids` to the message schema

**Files:**
- Modify: `api/app/schemas/chats.py` (constants block ~86-94; `MessageCreateRequest` ~343-433; `MessagePostResponse` ~563-609; `__all__` ~634-662)
- Test: `api/tests/unit/test_chats_schema.py`

**Interfaces:**
- Produces: `MESSAGE_REFERENCED_FILES_MAX_LEN: int`; `MessageCreateRequest.referenced_file_ids: list[str]` (default `[]`, capped); `MessagePostResponse.applied_referenced_file_ids: list[str]` (default `[]`).

- [ ] **Step 1: Write the failing test**

```python
# api/tests/unit/test_chats_schema.py
import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.chats import (
    MESSAGE_REFERENCED_FILES_MAX_LEN,
    MessageCreateRequest,
    MessagePostResponse,
    MessageResponse,
)


def test_referenced_file_ids_defaults_empty():
    req = MessageCreateRequest(content="hi")
    assert req.referenced_file_ids == []


def test_referenced_file_ids_accepts_list():
    ids = ["11111111-1111-1111-1111-111111111111"]
    req = MessageCreateRequest(content="hi", referenced_file_ids=ids)
    assert req.referenced_file_ids == ids


def test_referenced_file_ids_over_cap_rejected():
    ids = ["11111111-1111-1111-1111-111111111111"] * (MESSAGE_REFERENCED_FILES_MAX_LEN + 1)
    with pytest.raises(PydanticValidationError):
        MessageCreateRequest(content="hi", referenced_file_ids=ids)


def test_applied_referenced_file_ids_defaults_empty():
    # minimal MessageResponse to satisfy the required nested field
    msg = MessageResponse(
        id="11111111-1111-1111-1111-111111111111",
        chat_id="22222222-2222-2222-2222-222222222222",
        role="assistant",
        content="ok",
        created_at="2026-07-02T00:00:00Z",
    )
    resp = MessagePostResponse(message=msg)
    assert resp.applied_referenced_file_ids == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/unit/test_chats_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'MESSAGE_REFERENCED_FILES_MAX_LEN'`.

- [ ] **Step 3: Add the constant** (in `api/app/schemas/chats.py`, after `MESSAGE_FILE_IDS_MAX_LEN` ~line 94)

```python
MESSAGE_REFERENCED_FILES_MAX_LEN: int = 16
"""Hard cap on ``MessageCreateRequest.referenced_file_ids``.

Referenced files drive file-scoped retrieval for a single turn: each id
triggers an ownership + matter-KB validation SELECT and a per-file
hybrid-search call. Without a cap a single message could reference
thousands of files — workload-multiplication DoS available to any
authenticated user. 16 matches :data:`MESSAGE_FILE_IDS_MAX_LEN`;
realistic per-turn document references are a handful. Over the cap 422s
at schema time."""
```

- [ ] **Step 4: Add the request field** (in `MessageCreateRequest`, after `file_ids` ~line 429)

```python
    referenced_file_ids: list[str] = Field(
        default_factory=list, max_length=MESSAGE_REFERENCED_FILES_MAX_LEN
    )
    """referenced-files: caller-selected matter documents to ground THIS turn via
    file-scoped retrieval. Distinct from :attr:`file_ids` (which injects
    a file's full text verbatim with no citations): referenced files are
    retrieved as chunks and merged into the turn's ``retrieved_chunks``
    so the Citation Engine mints verified, deep-linkable citations for
    them. KB-only MVP: each id must be caller-owned, ``ready``, and in a
    Knowledge Base attached to the chat's project (matter scope);
    otherwise it 404s id-probing-safe. Echoed back as
    ``applied_referenced_file_ids``. Empty/omitted is a back-compatible
    no-op."""
```

- [ ] **Step 5: Add the response echo** (in `MessagePostResponse`, after `applied_file_ids` ~line 581)

```python
    applied_referenced_file_ids: list[str] = Field(default_factory=list)
    """referenced-files: caller-selected file ids that were validated (owned +
    matter-KB + ready) and whose chunks were retrieved to ground this
    turn — the echo of :attr:`MessageCreateRequest.referenced_file_ids`.
    Turn-scoped (no ``messages.referenced_file_ids`` column): surfaces on
    the send response and the SSE ``complete`` frame only. Empty when
    none were referenced or none validated."""
```

- [ ] **Step 6: Export the constant** (add to `__all__` ~line 642, keeping alpha order)

```python
    "MESSAGE_REFERENCED_FILES_MAX_LEN",
```

- [ ] **Step 7: Run tests + linters to verify pass**

Run: `cd api && python -m pytest tests/unit/test_chats_schema.py -v && ruff format --check app/schemas/chats.py && ruff check app/schemas/chats.py`
Expected: PASS; ruff clean.

- [ ] **Step 8: Commit**

```bash
git add api/app/schemas/chats.py api/tests/unit/test_chats_schema.py
git commit -s -m "feat(chats): add referenced_file_ids to message schema (referenced-files)"
```

---

### Task 2: File-scoped hybrid retrieval (`hybrid_search_files`)

**Files:**
- Modify: `api/app/knowledge/retrieval.py` (factor combine+hydrate out of `hybrid_search` ~127-180; add file-scoped side queries + `hybrid_search_files`)
- Test: `api/tests/unit/test_retrieval_files.py`

**Interfaces:**
- Consumes: existing `HybridSearchResult`, `_min_max_normalize`, `_format_vector`, `_hydrate_chunks`.
- Produces: `async def hybrid_search_files(db, *, file_ids: list[uuid.UUID], query: str, query_embedding: list[float] | None, top_k: int, alpha: float) -> list[HybridSearchResult]`.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/unit/test_retrieval_files.py
import uuid
import pytest

from app.knowledge.retrieval import hybrid_search_files

pytestmark = pytest.mark.asyncio


async def test_hybrid_search_files_scopes_to_given_files(seeded_two_ready_files):
    """Two ready+embedded files exist; searching one file's id returns
    only that file's chunks."""
    db, file_a, file_b, query = seeded_two_ready_files
    results = await hybrid_search_files(
        db,
        file_ids=[file_a],
        query=query,
        query_embedding=None,  # FTS-only path, deterministic
        top_k=10,
        alpha=1.0,
    )
    assert results, "expected at least one chunk from file_a"
    assert {r.file_id for r in results} == {file_a}


async def test_hybrid_search_files_empty_ids_returns_empty(db_session):
    results = await hybrid_search_files(
        db_session, file_ids=[], query="x", query_embedding=None, top_k=5, alpha=1.0
    )
    assert results == []
```

> Fixture note: `seeded_two_ready_files` inserts two `files` rows
> (`ingestion_status='ready'`), a `documents` row each, and a few
> `document_chunks` with `content` + `content_tsv` populated (embedding may
> be NULL — FTS path is exercised). Model it on the existing KB-retrieval
> integration fixtures in `api/tests/` (search for `hybrid_search` usages).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/unit/test_retrieval_files.py -v`
Expected: FAIL — `ImportError: cannot import name 'hybrid_search_files'`.

- [ ] **Step 3: Factor the combine+hydrate tail into a shared helper** (in `retrieval.py`, extract lines ~127-180 of `hybrid_search` into a new function and call it from `hybrid_search`)

```python
async def _combine_and_hydrate(
    db: AsyncSession,
    *,
    vector_rows: list[tuple[uuid.UUID, float]],
    fts_rows: list[tuple[uuid.UUID, float]],
    top_k: int,
    alpha: float,
) -> list[HybridSearchResult]:
    """Min-max normalize, linearly combine, take top_k, hydrate.

    Shared by :func:`hybrid_search` (KB-scoped) and
    :func:`hybrid_search_files` (file-scoped) — the only difference
    between the two is which candidate SQL produced ``vector_rows`` /
    ``fts_rows``.
    """
    if not vector_rows and not fts_rows:
        return []

    candidate_ids: set[uuid.UUID] = set()
    candidate_ids.update(cid for cid, _ in vector_rows)
    candidate_ids.update(cid for cid, _ in fts_rows)

    vector_norm = _min_max_normalize(dict(vector_rows))
    fts_norm = _min_max_normalize(dict(fts_rows))

    combined: list[tuple[uuid.UUID, float, float, float]] = []
    for cid in candidate_ids:
        v_score = vector_norm.get(cid, 0.0)
        f_score = fts_norm.get(cid, 0.0)
        hybrid = (1.0 - alpha) * v_score + alpha * f_score
        combined.append((cid, v_score, f_score, hybrid))

    combined.sort(key=lambda row: row[3], reverse=True)
    top = combined[:top_k]
    if not top:
        return []

    score_map = {cid: (v, f, h) for cid, v, f, h in top}
    rows = await _hydrate_chunks(db, [cid for cid, _, _, _ in top])

    results: list[HybridSearchResult] = []
    for row in rows:
        cid = row["chunk_id"]
        scores = score_map.get(cid)
        if scores is None:
            continue
        v_score, f_score, hybrid_score = scores
        results.append(
            HybridSearchResult(
                chunk_id=cid,
                document_id=row["document_id"],
                file_id=row["file_id"],
                file_name=row["file_name"],
                content=row["content"],
                page_start=row["page_start"],
                page_end=row["page_end"],
                char_offset_start=row["char_offset_start"],
                char_offset_end=row["char_offset_end"],
                vector_score=v_score,
                fts_score=f_score,
                hybrid_score=hybrid_score,
            )
        )
    results.sort(key=lambda r: r.hybrid_score, reverse=True)
    return results
```

Then replace the body of `hybrid_search` from `# --- Combine ---` (line ~127) through the end with:

```python
    return await _combine_and_hydrate(
        db, vector_rows=vector_rows, fts_rows=fts_rows, top_k=top_k, alpha=alpha
    )
```

- [ ] **Step 4: Add the file-scoped side queries + entry point** (append to `retrieval.py`)

```python
_VECTOR_SQL_FILES = text(
    """
    SELECT dc.id AS chunk_id,
           1.0 - (dc.embedding <=> CAST(:q_emb AS vector)) AS vec_score
      FROM document_chunks dc
      JOIN documents d ON d.id = dc.document_id
      JOIN files f ON f.id = d.file_id
     WHERE f.id = ANY(:file_ids)
       AND f.deleted_at IS NULL
       AND f.ingestion_status = 'ready'
       AND dc.embedding IS NOT NULL
     ORDER BY dc.embedding <=> CAST(:q_emb AS vector)
     LIMIT :limit
    """
)

_FTS_SQL_FILES = text(
    """
    SELECT dc.id AS chunk_id,
           ts_rank_cd(dc.content_tsv, plainto_tsquery('english', :q)) AS fts_rank
      FROM document_chunks dc
      JOIN documents d ON d.id = dc.document_id
      JOIN files f ON f.id = d.file_id
     WHERE f.id = ANY(:file_ids)
       AND f.deleted_at IS NULL
       AND f.ingestion_status = 'ready'
       AND dc.content_tsv @@ plainto_tsquery('english', :q)
     ORDER BY fts_rank DESC
     LIMIT :limit
    """
)


async def hybrid_search_files(
    db: AsyncSession,
    *,
    file_ids: list[uuid.UUID],
    query: str,
    query_embedding: list[float] | None,
    top_k: int,
    alpha: float,
) -> list[HybridSearchResult]:
    """Hybrid search scoped to an explicit set of file ids.

    Same score model as :func:`hybrid_search` (pgvector cosine + FTS,
    min-max normalized, ``(1-alpha)*vec + alpha*fts``) but the candidate
    set is ``document_chunks`` whose owning file is in ``file_ids`` (not
    a KB join). Callers MUST have already authorized ``file_ids`` — this
    primitive does no ownership check, matching :func:`hybrid_search`'s
    contract (the handler enforces scope).
    """
    if not file_ids:
        return []
    alpha = max(0.0, min(1.0, alpha))
    candidate_limit = top_k * CANDIDATE_OVERSHOOT
    ids = [str(fid) for fid in file_ids]

    vector_rows: list[tuple[uuid.UUID, float]] = []
    if query_embedding is not None and alpha < 1.0:
        result = await db.execute(
            _VECTOR_SQL_FILES,
            {"file_ids": ids, "q_emb": _format_vector(query_embedding), "limit": candidate_limit},
        )
        vector_rows = [
            (uuid.UUID(str(r["chunk_id"])), float(r["vec_score"])) for r in result.mappings().all()
        ]

    fts_rows: list[tuple[uuid.UUID, float]] = []
    if alpha > 0.0:
        result = await db.execute(
            _FTS_SQL_FILES, {"file_ids": ids, "q": query, "limit": candidate_limit}
        )
        fts_rows = [
            (uuid.UUID(str(r["chunk_id"])), float(r["fts_rank"])) for r in result.mappings().all()
        ]

    return await _combine_and_hydrate(
        db, vector_rows=vector_rows, fts_rows=fts_rows, top_k=top_k, alpha=alpha
    )
```

- [ ] **Step 5: Run tests + linters to verify pass**

Run: `cd api && python -m pytest tests/unit/test_retrieval_files.py tests/ -k "hybrid_search" -v && ruff format --check app/knowledge/retrieval.py && ruff check app/knowledge/retrieval.py`
Expected: PASS (new file-scoped tests + existing KB `hybrid_search` tests still green after the refactor).

- [ ] **Step 6: Commit**

```bash
git add api/app/knowledge/retrieval.py api/tests/unit/test_retrieval_files.py
git commit -s -m "feat(retrieval): add file-scoped hybrid_search_files (referenced-files)"
```

---

### Task 3: Validate referenced ids are owned + matter-KB + ready

**Files:**
- Modify: `api/app/api/chats.py` (add helper near `_validate_owned_file_ids` ~355; imports for `KnowledgeBaseFile`, `ProjectKnowledgeBase` if not present)
- Test: `api/tests/integration/test_referenced_files_send.py`

**Interfaces:**
- Consumes: `File`, `KnowledgeBaseFile` (`app.models.knowledge`), `ProjectKnowledgeBase` (`app.models.project_knowledge_base`), `NotFound`.
- Produces: `async def _validate_referenced_file_ids(db, referenced_file_ids: list[str], *, owner_id: uuid.UUID, project_id: uuid.UUID | None) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/integration/test_referenced_files_send.py
import uuid
import pytest

from app.api.chats import _validate_referenced_file_ids
from app.errors import NotFound

pytestmark = pytest.mark.asyncio


async def test_validate_referenced_ok(matter_with_kb_file):
    """A ready file in a KB attached to the project validates."""
    db, owner_id, project_id, file_id = matter_with_kb_file
    out = await _validate_referenced_file_ids(
        db, [str(file_id)], owner_id=owner_id, project_id=project_id
    )
    assert out == [str(file_id)]


async def test_validate_referenced_projectless_404(matter_with_kb_file):
    """Referencing anything from a projectless chat is a 404 (no matter)."""
    db, owner_id, _project_id, file_id = matter_with_kb_file
    with pytest.raises(NotFound):
        await _validate_referenced_file_ids(
            db, [str(file_id)], owner_id=owner_id, project_id=None
        )


async def test_validate_referenced_foreign_file_404(matter_with_kb_file):
    db, owner_id, project_id, _file_id = matter_with_kb_file
    with pytest.raises(NotFound):
        await _validate_referenced_file_ids(
            db, [str(uuid.uuid4())], owner_id=owner_id, project_id=project_id
        )
```

> Fixture note: `matter_with_kb_file` seeds a user, a project, a KB
> attached to the project (`project_knowledge_bases`), a `ready` file
> attached to that KB (`knowledge_base_files`), and its `documents` row.
> Reuse the KB/project fixtures already in `api/tests/` (grep for
> `ProjectKnowledgeBase` and `KnowledgeBaseFile` in existing tests).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/integration/test_referenced_files_send.py -v`
Expected: FAIL — `ImportError: cannot import name '_validate_referenced_file_ids'`.

- [ ] **Step 3: Add the validator** (in `api/app/api/chats.py`, after `_validate_owned_file_ids` ~line 412; ensure `KnowledgeBaseFile` and `ProjectKnowledgeBase` are imported at the top of the module)

```python
async def _validate_referenced_file_ids(
    db: AsyncSession,
    referenced_file_ids: list[str],
    *,
    owner_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> list[str]:
    """Validate caller-referenced files for file-scoped retrieval (referenced-files).

    KB-only MVP + matter scope: each id must (1) parse as a UUID, (2)
    resolve to a caller-owned, non-deleted, ``ingestion_status='ready'``
    file that (3) is attached to a Knowledge Base which is itself
    attached to the chat's ``project_id``. Any id failing any check —
    including a projectless chat (no matter, so nothing is referenceable)
    — raises :class:`NotFound` (404), id-probing-safe and consistent with
    :func:`_validate_owned_file_ids`.

    Returns validated ids as strings (deduped, order-preserving). Empty
    input returns an empty list without a DB round-trip.
    """
    if not referenced_file_ids:
        return []

    parsed: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for raw in referenced_file_ids:
        try:
            fid = uuid.UUID(raw)
        except (ValueError, AttributeError) as exc:
            raise NotFound(f"File {raw} not found.", details={"file_id": str(raw)}) from exc
        if fid not in seen:
            seen.add(fid)
            parsed.append(fid)

    # Projectless chat has no matter → nothing is referenceable. Fail
    # restrictive (P4): 404 every id rather than silently returning none.
    if project_id is None:
        raise NotFound(
            f"File {parsed[0]} not found.", details={"file_id": str(parsed[0])}
        )

    # One SELECT: owned + ready + in a KB attached to this project.
    stmt = (
        select(File.id)
        .join(KnowledgeBaseFile, KnowledgeBaseFile.file_id == File.id)
        .join(
            ProjectKnowledgeBase,
            ProjectKnowledgeBase.knowledge_base_id == KnowledgeBaseFile.kb_id,
        )
        .where(
            File.id.in_(parsed),
            File.owner_id == owner_id,
            File.deleted_at.is_(None),
            File.ingestion_status == "ready",
            ProjectKnowledgeBase.project_id == project_id,
        )
        .distinct()
    )
    found = set((await db.execute(stmt)).scalars().all())
    for fid in parsed:
        if fid not in found:
            raise NotFound(f"File {fid} not found.", details={"file_id": str(fid)})

    return [str(fid) for fid in parsed]
```

- [ ] **Step 4: Run tests + linters to verify pass**

Run: `cd api && python -m pytest tests/integration/test_referenced_files_send.py -k validate -v && ruff format --check app/api/chats.py && ruff check app/api/chats.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/api/chats.py api/tests/integration/test_referenced_files_send.py
git commit -s -m "feat(chats): validate referenced_file_ids (owned + matter-KB + ready) (referenced-files)"
```

---

### Task 4: Retrieve, merge, audit, and echo referenced-file context in `send_message`

**Files:**
- Modify: `api/app/api/chats.py` (RAG constants ~948-952; `send_message` validation site ~1233; retrieval/injection block ~1427-1480; the `MessagePostResponse`/SSE `complete` assembly where `applied_file_ids` is set — grep `applied_file_ids=`)
- Test: `api/tests/integration/test_referenced_files_send.py`

**Interfaces:**
- Consumes: `hybrid_search_files` (Task 2), `_validate_referenced_file_ids` (Task 3), `request_embedding_vector`, `DEFAULT_EMBEDDING_MODEL`, `_format_retrieval_context_block`, `_persist_message_citations` (unchanged — consumes the merged `retrieved_chunks`).
- Produces: `_retrieve_referenced_file_context(...)`, `_merge_retrieved_chunks(...)`; `send_message` now grounds + cites referenced files and echoes `applied_referenced_file_ids`.

- [ ] **Step 1: Write the failing end-to-end test**

```python
# api/tests/integration/test_referenced_files_send.py  (append)
async def test_send_with_referenced_file_produces_citation(client, matter_with_kb_file, chat_in_project, stub_gateway_quoting_source):
    """Referencing a matter-KB file and asking about it yields a persisted,
    verified citation whose source_file_id is the referenced file."""
    _db, _owner, _project, file_id = matter_with_kb_file
    chat_id = chat_in_project  # a chat whose project_id == the matter project

    resp = await client.post(
        f"/api/v1/chats/{chat_id}/messages",
        json={"content": "What does the contract say about liability?",
              "referenced_file_ids": [str(file_id)]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied_referenced_file_ids"] == [str(file_id)]

    msg_id = body["message"]["id"]
    cites = await client.get(f"/api/v1/chats/{chat_id}/messages/{msg_id}/citations")
    assert cites.status_code == 200
    rows = cites.json()
    assert any(c["source_file_id"] == str(file_id) for c in rows)


async def test_send_with_foreign_referenced_file_404(client, chat_in_project):
    resp = await client.post(
        f"/api/v1/chats/{chat_in_project}/messages",
        json={"content": "hi", "referenced_file_ids": [str(uuid.uuid4())]},
    )
    assert resp.status_code == 404
```

> Fixture note: `stub_gateway_quoting_source` returns an assistant
> message that quotes a chunk verbatim in the required
> `"..." (Source: [1])` format so the Stage-1 verifier persists a row —
> mirror the existing citation integration stubs (grep
> `get_citation_engine_judge_model` / `_persist_message_citations` in
> `api/tests/`). `chat_in_project` creates a chat with `project_id` set to
> the matter project.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest tests/integration/test_referenced_files_send.py -k "citation or foreign" -v`
Expected: FAIL — `applied_referenced_file_ids` KeyError / referenced chunks not retrieved / 200 instead of 404.

- [ ] **Step 3: Add RAG constants for referenced files** (in `chats.py`, after `RAG_MAX_TOTAL_CHUNKS` ~line 952)

```python
# referenced-files — file-scoped retrieval for explicitly referenced files. A
# referenced file usually means "answer over THIS document", so we pull
# more chunks per file than the KB-wide top_k and give referenced chunks
# priority in the merged context set.
REFERENCED_TOP_K_PER_FILE: int = 8
REFERENCED_MAX_CHUNKS: int = 16
# Alpha for file-scoped search. Balanced default; align with the
# KnowledgeBase.hybrid_alpha server default if it differs.
REFERENCED_FILE_ALPHA: float = 0.5
```

- [ ] **Step 4: Add the retrieval + merge helpers** (in `chats.py`, after `_retrieve_kb_context_for_chat` ~line 1072)

```python
async def _retrieve_referenced_file_context(
    db: AsyncSession,
    *,
    referenced_file_ids: list[str],
    query: str,
    gateway: GatewayClient,
    request_id: str | None,
) -> list[HybridSearchResult]:
    """Hybrid-search chunks for explicitly referenced files (referenced-files).

    Ids are assumed already validated (owned + matter-KB + ready) by
    :func:`_validate_referenced_file_ids`. Embeds the query once (FTS-only
    fallback on embed failure, mirroring the KB path) and runs one
    :func:`hybrid_search_files` call over the whole set.
    """
    if not referenced_file_ids:
        return []
    file_uuids = [uuid.UUID(fid) for fid in referenced_file_ids]

    query_embedding: list[float] | None = None
    if REFERENCED_FILE_ALPHA < 1.0:
        try:
            query_embedding = await request_embedding_vector(
                query,
                model=DEFAULT_EMBEDDING_MODEL,
                gateway=gateway,
                request_id=request_id,
            )
        except LQAIError as exc:
            log.warning(
                "chat-send referenced-files: query-embedding fetch failed; FTS-only fallback",
                extra={"event": "chat_ref_embed_fetch_failed", "error_code": exc.effective_code},
            )
            query_embedding = None

    return await hybrid_search_files(
        db,
        file_ids=file_uuids,
        query=query,
        query_embedding=query_embedding,
        top_k=min(REFERENCED_TOP_K_PER_FILE * len(file_uuids), REFERENCED_MAX_CHUNKS),
        alpha=REFERENCED_FILE_ALPHA,
    )


def _merge_retrieved_chunks(
    referenced: list[HybridSearchResult],
    kb: list[HybridSearchResult],
) -> list[HybridSearchResult]:
    """Merge referenced-file chunks (priority) with KB-RAG chunks.

    Referenced chunks come first (explicit user intent), then KB chunks
    not already present (deduped by ``chunk_id``), capped at
    :data:`RAG_MAX_TOTAL_CHUNKS`. Order determines the ``[N]`` citation
    indices in the context block.
    """
    out: list[HybridSearchResult] = []
    seen: set[uuid.UUID] = set()
    for chunk in [*referenced, *kb]:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        out.append(chunk)
        if len(out) >= RAG_MAX_TOTAL_CHUNKS:
            break
    return out
```

- [ ] **Step 5: Validate referenced ids in `send_message`** (in `chats.py`, right after the `effective_file_ids` validation ~line 1233)

```python
    # referenced-files — validate caller-referenced matter files (owned + in a KB
    # attached to the chat's project + ready). 404 id-probing-safe on any
    # miss; empty/omitted is a no-op.
    effective_referenced_file_ids = await _validate_referenced_file_ids(
        db,
        payload.referenced_file_ids,
        owner_id=user.id,
        project_id=chat.project_id,
    )
```

- [ ] **Step 6: Retrieve + merge + audit** (replace the block at ~lines 1427-1480, i.e. from the `retrieved_chunks, kb_ids_searched = await _retrieve_kb_context_for_chat(...)` call through the KB-audit `await db.commit()`, with the following)

```python
    # Wave D.1 T7b — KB RAG across the project's attached KBs.
    kb_chunks, kb_ids_searched = await _retrieve_kb_context_for_chat(
        db,
        chat=chat,
        query=effective_content,
        gateway=gateway,
        request_id=request.headers.get("x-request-id"),
    )

    # referenced-files — file-scoped retrieval for explicitly referenced files.
    referenced_chunks = await _retrieve_referenced_file_context(
        db,
        referenced_file_ids=effective_referenced_file_ids,
        query=effective_content,
        gateway=gateway,
        request_id=request.headers.get("x-request-id"),
    )

    # Merge: referenced first (explicit intent), then KB, deduped + capped.
    # The single ``retrieved_chunks`` local flows to the context block AND
    # to every _persist_message_citations call site, so both KB and
    # referenced chunks become citable with no change to the citation path.
    retrieved_chunks = _merge_retrieved_chunks(referenced_chunks, kb_chunks)

    gw_messages: list[ChatCompletionMessage] = []
    if retrieved_chunks:
        context_block = _format_retrieval_context_block(retrieved_chunks)
        gw_messages.append(
            ChatCompletionMessage(
                role="system",
                content=context_block,
                lq_ai_skip_anonymization=True,
            )
        )

    # T7-shape audit for KB retrieval (unchanged semantics: KB chunks only).
    if kb_chunks:
        await audit_action(
            db,
            user_id=user.id,
            action="inference.kb_chunks_retrieved",
            resource_type="chat",
            resource_id=str(cid),
            project_id=chat.project_id,
            request=request,
            details={
                "kb_ids": [str(k) for k in kb_ids_searched],
                "chunk_count": len(kb_chunks),
                "chunk_ids": [str(c.chunk_id) for c in kb_chunks],
                "query_token_estimate": len(effective_content.split()),
            },
        )
        await db.commit()

    # referenced-files audit — counts/ids only (P3), own commit boundary (P5).
    if effective_referenced_file_ids:
        await audit_action(
            db,
            user_id=user.id,
            action="inference.message_referenced_files",
            resource_type="chat",
            resource_id=str(cid),
            project_id=chat.project_id,
            request=request,
            details={
                "file_ids": list(effective_referenced_file_ids),
                "referenced_count": len(effective_referenced_file_ids),
                "chunk_count": len(referenced_chunks),
                "chunk_ids": [str(c.chunk_id) for c in referenced_chunks],
            },
        )
        await db.commit()
```

> Note: the subsequent per-message `file_ids` verbatim block (~1482-1528)
> and everything downstream stay as-is. Confirm the merged `retrieved_chunks`
> local is the same variable passed to `_persist_message_citations` at the
> three call sites (grep `retrieved_chunks=retrieved_chunks`).

- [ ] **Step 7: Echo `applied_referenced_file_ids`** (grep `applied_file_ids=` in `chats.py`; at each site — the `MessagePostResponse(...)` build and the SSE `complete` frame payload — add the sibling)

```python
        applied_referenced_file_ids=list(effective_referenced_file_ids),
```

- [ ] **Step 8: Run the full new integration module + linters**

Run: `cd api && python -m pytest tests/integration/test_referenced_files_send.py -v && ruff format --check app/api/chats.py && ruff check app/api/chats.py`
Expected: PASS (citation persisted; foreign id 404; projectless 404 from Task 3).

- [ ] **Step 9: Commit**

```bash
git add api/app/api/chats.py api/tests/integration/test_referenced_files_send.py
git commit -s -m "feat(chats): ground + cite referenced files in send_message (referenced-files)"
```

---

### Task 5: Contract + docs (OpenAPI, PRD, ADR) and full-suite gate

**Files:**
- Modify: `docs/api/backend-openapi.yaml` (`MessageCreate` + `MessagePostResponse` schemas)
- Modify: `docs/PRD.md` (§3.1 chat API surface note; §3.3 citation source note)
- Create: `docs/adr/00NN-referenced-file-ids-chat.md`

**Interfaces:** none (documentation + conformance).

- [ ] **Step 1: Update the OpenAPI sketch** — add to the `MessageCreate` schema:

```yaml
        referenced_file_ids:
          type: array
          maxItems: 16
          items:
            type: string
            format: uuid
          description: >
            referenced-files. Caller-selected matter documents to ground this turn
            via file-scoped retrieval; retrieved chunks are cited by the
            Citation Engine. KB-only MVP: each id must be caller-owned,
            ready, and in a Knowledge Base attached to the chat's project
            (else 404). Distinct from file_ids (verbatim, uncited).
```

and to the send response (`MessagePostResponse`):

```yaml
        applied_referenced_file_ids:
          type: array
          items:
            type: string
            format: uuid
          description: referenced-files echo of the validated referenced_file_ids.
```

- [ ] **Step 2: Verify OpenAPI conformance** (the authoritative check per CLAUDE.md — do not eyeball the YAML)

Run: `cd api && python -m pytest tests/test_openapi.py -v`
Expected: PASS. (No new path → `EXPECTED_PATHS` / path count unchanged; the schema-shape conformance for `MessageCreate` picks up the new optional field.)

- [ ] **Step 3: Update the PRD** — in §3.1 (chat API surface), add one line after the `file_ids` description:

```markdown
  A parallel `referenced_file_ids` list (referenced-files) references matter documents that are **retrieved and cited** (KB-only MVP), as opposed to `file_ids` which injects verbatim text without citations.
```

and in §3.3 (Citation Engine), note that citations may be grounded in explicitly referenced files, not only project-wide KB retrieval.

- [ ] **Step 4: Write the ADR** — `docs/adr/00NN-referenced-file-ids-chat.md` recording: the new-field-vs-overload decision, the matter-KB scope (KB-only MVP, embed-on-reference deferred to Phase 3), the P9 rationale (retrieval-grounded not verbatim), and the P2 rationale (UI-selected set, not a model tool). Follow the existing ADR template in `docs/adr/`.

- [ ] **Step 5: Run the full api suite + both linters (the gate)**

Run: `cd api && ruff format --check . && ruff check . && python -m pytest`
Expected: PASS across the suite (collision guards `test_endpoints.py` / `test_openapi.py` green — no route added).

- [ ] **Step 6: Commit**

```bash
git add docs/api/backend-openapi.yaml docs/PRD.md docs/adr/00NN-referenced-file-ids-chat.md
git commit -s -m "docs(chats): document referenced_file_ids channel + ADR (referenced-files)"
```

---

## Self-Review

**Spec coverage** (against the design spec's Phase-1 backend scope):
- New `referenced_file_ids` field → Task 1. ✓
- File-scoped retrieval into `retrieved_chunks` → Tasks 2 + 4. ✓
- Matter-KB + owned + ready validation (KB-only MVP, matter scope) → Task 3. ✓
- Citations mint for referenced files → Task 4 (merge into the citation-fed local) + integration test. ✓
- Audit counts-only (P3), atomic (P5) → Task 4. ✓
- Fail restrictive (P4) → Task 3 (404 on miss / projectless). ✓
- Contract/PRD/ADR in-PR (P10) → Task 5. ✓
- `GET /api/v1/files` — **intentionally out of this plan**: KB-only MVP reuses `GET /kb/{id}/files`; the DE-296 endpoint is only needed for Phase-3 (non-KB files) / the frontend's unified picker. Logged here so it isn't a silent gap.
- Embed-on-reference — **deferred to Phase 3** per locked decision; `hybrid_search_files` already works for any embedded file, so Phase 3 only adds the on-demand embed trigger.

**Placeholder scan:** no TBD/TODO; every code step carries real code; SQL, constants, and signatures are concrete. The two "grep to confirm the call site" notes (Task 4 Steps 6–7) are verification steps, not placeholders — the code to add is given verbatim.

**Type consistency:** `hybrid_search_files` / `_combine_and_hydrate` / `_retrieve_referenced_file_context` all traffic in `HybridSearchResult`; `_validate_referenced_file_ids` and the schema field both use `list[str]` UUID strings; `effective_referenced_file_ids` (validated strings) is the single name threaded through retrieval, audit, and the response echo.

**Open items carried to other work (not this plan):** frontend picker + `@`-mention (separate plan); the orthogonal projectless/KB-not-attached passive-citation bug (separate bug); embed-on-reference (Phase 3).
