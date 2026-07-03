# Referenced Files in Chat — Backend (Phase 1 MVP) Implementation Plan — v2

> v2 amends the original plan per the adversarial review (`fable_review.md` at repo parent):
> fixed the broken echo step (threading via dispatcher params), fixed the cap arithmetic
> (referenced 12 / merged 16, pure-KB turns unchanged at 10), per-file retrieval budget with
> per-KB-derived alpha, single query-embedding, injected-aware audit rows, corrected test
> locations (no `tests/unit/`), ADR number 0022, `KnowledgeBaseFile` import.

**Goal:** Let a chat message carry a user-selected set of matter documents (`referenced_file_ids`) that are retrieved as grounding chunks so the assistant's answer returns verified, deep-linkable citations.

**Architecture:** Add a `referenced_file_ids` field to the message-send request. Validate each id is caller-owned, `ready`, and in a Knowledge Base attached to the chat's project (matter scope, KB-only MVP) — the same validation query also returns each file's matter-KB `hybrid_alpha`. Retrieve chunks per referenced file (per-file budget, round-robin interleave) via a new file-scoped hybrid search, merge them ahead of KB-RAG chunks into the existing `retrieved_chunks` local in `send_message` so the shipped context-block + Citation Engine path cite them unchanged. Write a counts/ids-only audit row. Echo validated ids as `applied_referenced_file_ids` by threading them as a parameter into both dispatch helpers.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, Postgres + pgvector, pytest.

## Global Constraints

- Python: `ruff format` + `ruff check` both pass (separate CI gates). Type annotations on all public functions. `async def` for I/O. Raise from `app.errors` hierarchy, never bare `Exception`.
- Every new handler path gets tests; the citation wiring gets an integration regression.
- **No raw payloads in audit/log rows (P3):** ids/counts only — never file content or query text.
- **Fail restrictive (P4):** an unauthorized / out-of-matter / not-`ready` referenced id 404s id-probing-safe (message text identical to the nonexistent-id case), never error-open or broad-search fallback.
- **Atomic audit (P5):** audit rows commit on their own boundary exactly like `inference.message_files_attached`.
- **Contract is truth (P10):** update `docs/api/backend-openapi.yaml`, `docs/PRD.md`, and add ADR **0022** in the same PR. No new route → `IMPLEMENTED_ROUTES` / `EXPECTED_PATHS` unchanged.
- **Additive/non-breaking:** omitting `referenced_file_ids` reproduces today's behavior exactly — including the pure-KB merge cap of 10 (`RAG_MAX_TOTAL_CHUNKS`).
- Test invocation: `cd api && DATABASE_URL=postgresql+asyncpg://test:test@127.0.0.1:55432/lqai_test .venv/bin/pytest <paths> -q` (throwaway pgvector container; conftest auto-migrates). Linters: `.venv/bin/ruff format --check <files>` and `.venv/bin/ruff check <files>`.
- Dev-env hard rules: never host-side `alembic upgrade` on the live dev DB (127.0.0.1:5432); never `docker compose down -v`.
- Commits: imperative mood, `git commit -s`.

## File Structure

- `api/app/schemas/chats.py` — `MESSAGE_REFERENCED_FILES_MAX_LEN`, `MessageCreateRequest.referenced_file_ids`, `MessagePostResponse.applied_referenced_file_ids`.
- `api/app/knowledge/retrieval.py` — extract `_combine_and_hydrate` from `hybrid_search`; add `hybrid_search_files`.
- `api/app/api/chats.py` — `_validate_referenced_file_ids`, `_retrieve_referenced_file_context`, `_merge_retrieved_chunks`; `_retrieve_kb_context_for_chat` returns the query embedding; wire into `send_message`; thread echo through `_stream_response` / `_non_streaming_response`.
- `api/tests/test_referenced_files_schema.py` — schema tests (pure Pydantic; flat per repo layout — there is NO `tests/unit/` dir).
- `api/tests/test_retrieval_files.py` — DB-backed tests for `hybrid_search_files` (flat, like `test_knowledge_retrieval_unit.py`).
- `api/tests/integration/test_referenced_files_send.py` — validator + end-to-end send/citation/echo tests (client fixture per `tests/integration/test_attached_skills_send.py`).
- `docs/api/backend-openapi.yaml`, `docs/PRD.md`, `docs/adr/0022-referenced-file-ids-chat.md`.

---

### Task 1: Add `referenced_file_ids` to the message schema

**Files:**
- Modify: `api/app/schemas/chats.py` (constants block ~86-94; `MessageCreateRequest` ~343; `MessagePostResponse` ~563; `__all__` ~634)
- Test: `api/tests/test_referenced_files_schema.py` (new, flat — do NOT create `tests/unit/`)

**Steps (TDD):**

1. Write the failing test `api/tests/test_referenced_files_schema.py`:

```python
"""referenced-files — schema surface for referenced_file_ids (pure Pydantic, no DB)."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.chats import (
    MESSAGE_REFERENCED_FILES_MAX_LEN,
    MessageCreateRequest,
    MessagePostResponse,
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
    resp = MessagePostResponse(message=_minimal_message_response())
    assert resp.applied_referenced_file_ids == []
```

   For `_minimal_message_response()`: construct a `MessageResponse` with exactly its required fields — read the class at `api/app/schemas/chats.py:462` and supply what it actually requires (id, chat_id, role, content, created_at at minimum; adapt to the real definition, do not guess).

2. Run it — expect `ImportError: cannot import name 'MESSAGE_REFERENCED_FILES_MAX_LEN'`.

3. Add the constant after `MESSAGE_FILE_IDS_MAX_LEN` (~line 94):

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

4. Add the request field in `MessageCreateRequest`, after the `file_ids` field's docstring (~line 429):

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

5. Add the response echo in `MessagePostResponse`, after `applied_file_ids` (~line 581):

```python
    applied_referenced_file_ids: list[str] = Field(default_factory=list)
    """referenced-files: caller-selected file ids that were validated (owned +
    matter-KB + ready) and whose chunks were retrieved to ground this
    turn — the echo of :attr:`MessageCreateRequest.referenced_file_ids`.
    Turn-scoped (no ``messages.referenced_file_ids`` column): surfaces on
    the send response and the SSE ``complete`` frame only. Empty when
    none were referenced or none validated."""
```

6. Add `"MESSAGE_REFERENCED_FILES_MAX_LEN",` to `__all__` (~line 634+, keep alpha order).

7. Run test + `ruff format --check` + `ruff check` on the touched files — all pass.

8. Commit: `git commit -s -m "feat(chats): add referenced_file_ids to message schema" -m "Refs referenced-files"`

---

### Task 2: File-scoped hybrid retrieval (`hybrid_search_files`)

**Files:**
- Modify: `api/app/knowledge/retrieval.py`
- Test: `api/tests/test_retrieval_files.py` (new, flat; uses the `db_session` conftest fixture → requires `DATABASE_URL`)

**Steps (TDD):**

1. Write the failing test `api/tests/test_retrieval_files.py`. Two ready+embedded... correction: two `ready` files each with a `documents` row and 2-3 `document_chunks` rows with `content` + `content_tsv` populated (embedding may stay NULL — exercise the FTS-only path deterministically, `alpha=1.0`, `query_embedding=None`). Model the seeding on existing fixtures/tests that insert `File`/`Document`/chunk rows (grep `document_chunks` in `api/tests/`). Assertions:
   - searching with `file_ids=[file_a]` returns only file_a's chunks (`{r.file_id for r in results} == {file_a}`), non-empty;
   - `file_ids=[]` returns `[]` without touching the DB;
   - a file with `ingestion_status='processing'` (or soft-deleted) contributes nothing even when its id is passed.

2. Run — expect `ImportError: cannot import name 'hybrid_search_files'`.

3. Extract the combine+hydrate tail of `hybrid_search` (`retrieval.py:124-180`, from the `if not vector_rows and not fts_rows` guard through the final return) into:

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
```

   Body: move lines 124-180 verbatim (guard, candidate-id union, `_min_max_normalize` both sides, `(1-alpha)*v + alpha*f`, sort, `[:top_k]`, `_hydrate_chunks`, rebuild `HybridSearchResult`s, re-sort by `hybrid_score`). Replace the moved body in `hybrid_search` with a single `return await _combine_and_hydrate(db, vector_rows=vector_rows, fts_rows=fts_rows, top_k=top_k, alpha=alpha)`.

4. Add the file-scoped side queries + entry point (append to `retrieval.py`). SQL is identical to `_VECTOR_SQL`/`_FTS_SQL` except the `knowledge_base_files` join is replaced by `f.id = ANY(:file_ids)` (keep `f.deleted_at IS NULL`, `f.ingestion_status = 'ready'`, and `dc.embedding IS NOT NULL` on the vector side). Binding: pass `[str(fid) for fid in file_ids]` — the exact pattern `_HYDRATE_SQL` already uses at `retrieval.py:283,296`.

```python
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

5. Run: the new tests AND every existing retrieval/KB-search test (`pytest tests/test_retrieval_files.py tests/test_knowledge_retrieval_unit.py -q`, then `-k hybrid_search` across `tests/`) — the refactor must leave `hybrid_search` behavior byte-identical. Linters on the touched file.

6. Commit: `git commit -s -m "feat(retrieval): add file-scoped hybrid_search_files" -m "Refs referenced-files"`

---

### Task 3: Validate referenced ids (owned + matter-KB + ready) and fetch per-file alpha

**Files:**
- Modify: `api/app/api/chats.py` — add `_validate_referenced_file_ids` after `_validate_owned_file_ids` (which ends ~line 414); add `KnowledgeBaseFile` to the existing `from app.models.knowledge import KnowledgeBase` import at line 106 (`ProjectKnowledgeBase` is already imported at line 109; `NotFound` at 98; `select`/`func` at 70).
- Test: `api/tests/integration/test_referenced_files_send.py` (new)

**Signature (differs from v1 — the validation query also returns each file's matter-KB `hybrid_alpha`, so retrieval honors the operator-tuned per-KB knob without a second round-trip):**

```python
async def _validate_referenced_file_ids(
    db: AsyncSession,
    referenced_file_ids: list[str],
    *,
    owner_id: uuid.UUID,
    project_id: uuid.UUID | None,
) -> tuple[list[str], dict[str, float]]:
    """Validate caller-referenced files for file-scoped retrieval (referenced-files).

    KB-only MVP + matter scope: each id must (1) parse as a UUID, (2)
    resolve to a caller-owned, non-deleted, ``ingestion_status='ready'``
    file that (3) is attached to a Knowledge Base which is itself
    attached to the chat's ``project_id``. Any id failing any check —
    including a projectless chat (no matter, so nothing is referenceable)
    — raises :class:`NotFound` (404), id-probing-safe and message-
    identical to the nonexistent-id case, consistent with
    :func:`_validate_owned_file_ids`.

    Returns ``(validated_ids, alpha_by_id)``: ids as strings (deduped,
    order-preserving) and each file's retrieval alpha — the MIN
    ``hybrid_alpha`` across the matter KBs containing it (deterministic
    when a file sits in several attached KBs; MIN favors the vector
    side). Empty input returns ``([], {})`` without a DB round-trip.
    """
```

**Implementation:** mirror `_validate_owned_file_ids` (`chats.py:355-414`) exactly for parse/dedupe/404 (`NotFound(f"File {raw} not found.", details={"file_id": str(raw)})`). If `project_id is None` and ids were supplied, raise `NotFound` for the first parsed id (fail restrictive — P4). One SELECT:

```python
    stmt = (
        select(File.id, func.min(KnowledgeBase.hybrid_alpha))
        .join(KnowledgeBaseFile, KnowledgeBaseFile.file_id == File.id)
        .join(KnowledgeBase, KnowledgeBase.id == KnowledgeBaseFile.kb_id)
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
        .group_by(File.id)
    )
```

Build `alpha_by_id: dict[str, float]` (`str(fid) -> float(alpha)`); 404 any parsed id absent from the result; return `([str(fid) for fid in parsed], alpha_by_id)`.

**Tests (in `test_referenced_files_send.py`, direct-call, `pytestmark = pytest.mark.asyncio`):** seed user + project + KB (`hybrid_alpha` non-default, e.g. `0.7`) attached via `project_knowledge_bases` + `ready` file in `knowledge_base_files` + its `documents` row (grep existing tests for `ProjectKnowledgeBase`/`KnowledgeBaseFile` seeding patterns). Cases:
- valid file → `([str(file_id)], {str(file_id): 0.7})`;
- `project_id=None` → `NotFound`;
- random foreign uuid → `NotFound`;
- file in a KB **not** attached to the project → `NotFound`;
- `ingestion_status='processing'` file → `NotFound`;
- malformed id string → `NotFound`;
- duplicate ids in input → deduped single entry, order preserved.

Run tests + linters; commit: `git commit -s -m "feat(chats): validate referenced_file_ids (owned + matter-KB + ready, per-file alpha)" -m "Refs referenced-files"`

---

### Task 4: Retrieve (per-file budget), merge, audit, and echo in `send_message`

**Files:**
- Modify: `api/app/api/chats.py`
- Test: `api/tests/integration/test_referenced_files_send.py` (append)

**Step 4.1 — constants** (after `RAG_MAX_TOTAL_CHUNKS` ~line 952):

```python
# referenced-files — file-scoped retrieval for explicitly referenced files. An
# explicit reference means "answer over THIS document": each referenced
# file gets its own top-k budget (round-robin interleaved, so no file is
# starved by a dominant sibling), and referenced chunks take priority
# over KB-wide RAG chunks in the merged context set. When references are
# present the merged bound rises to MERGED_MAX_TOTAL_CHUNKS (explicit
# reference justifies the context spend — ADR 0022); referenced chunks
# are capped at REFERENCED_MAX_CHUNKS so KB RAG always retains at least
# four slots when it has results. Pure-KB turns keep the shipped
# RAG_MAX_TOTAL_CHUNKS bound — zero behavior change.
REFERENCED_TOP_K_PER_FILE: int = 6
REFERENCED_MAX_CHUNKS: int = 12
MERGED_MAX_TOTAL_CHUNKS: int = 16
```

**Step 4.2 — single query-embedding.** Change `_retrieve_kb_context_for_chat` (`:975`) to return a 3-tuple `(chunks, kb_ids_searched, query_embedding)` — it already computes the embedding at `:1021`; return it (or `None` on the early exits at `:1002-1007` and on embed-fetch failure). It has exactly ONE caller (`:1427`) and no test references — update the docstring and that call site. Rationale: referenced files are by construction in the project's attached KBs, so the KB pass has already embedded the query (or correctly decided not to: all-FTS KBs / embed failure). The referenced path must NOT issue a second embed call.

**Step 4.3 — retrieval + merge helpers** (after `_retrieve_kb_context_for_chat`):

```python
async def _retrieve_referenced_file_context(
    db: AsyncSession,
    *,
    referenced_file_ids: list[str],
    alpha_by_id: dict[str, float],
    query: str,
    query_embedding: list[float] | None,
) -> list[HybridSearchResult]:
    """Per-file hybrid search for explicitly referenced files (referenced-files).

    Ids are already validated (owned + matter-KB + ready) by
    :func:`_validate_referenced_file_ids`, which also supplied each
    file's matter-KB ``hybrid_alpha`` (MIN across containing KBs).
    ``query_embedding`` is the one computed by the KB pass — referenced
    files live in the same attached KBs, so no second embed call is made
    (``None`` degrades to FTS-only, the same fallback the KB path uses).

    Each file gets its own :data:`REFERENCED_TOP_K_PER_FILE` budget
    (per-file, not global top-k, so one dominant document cannot starve
    the others), and the per-file result lists are round-robin
    interleaved up to :data:`REFERENCED_MAX_CHUNKS`. A per-file search
    failure is logged and skipped (fail-soft, mirroring the per-KB loop).
    """
    if not referenced_file_ids:
        return []

    per_file: list[list[HybridSearchResult]] = []
    for fid in referenced_file_ids:
        alpha = alpha_by_id.get(fid, 0.5)
        try:
            results = await hybrid_search_files(
                db,
                file_ids=[uuid.UUID(fid)],
                query=query,
                query_embedding=query_embedding,
                top_k=REFERENCED_TOP_K_PER_FILE,
                alpha=alpha,
            )
        except Exception:
            log.exception(
                "chat-send referenced-files: hybrid_search_files failed for file; skipping",
                extra={"event": "chat_ref_file_search_failed", "file_id": fid},
            )
            continue
        if results:
            per_file.append(results)

    # Round-robin interleave so every referenced file is represented
    # before any file gets a second slot. Order determines the [N]
    # citation indices, so this is also a fairness property of the
    # context block.
    merged: list[HybridSearchResult] = []
    seen: set[uuid.UUID] = set()
    for rank in range(REFERENCED_TOP_K_PER_FILE):
        for results in per_file:
            if rank >= len(results):
                continue
            chunk = results[rank]
            if chunk.chunk_id in seen:
                continue
            seen.add(chunk.chunk_id)
            merged.append(chunk)
            if len(merged) >= REFERENCED_MAX_CHUNKS:
                return merged
    return merged


def _merge_retrieved_chunks(
    referenced: list[HybridSearchResult],
    kb: list[HybridSearchResult],
) -> list[HybridSearchResult]:
    """Merge referenced-file chunks (priority) with KB-RAG chunks.

    Referenced chunks come first (explicit user intent), then KB chunks
    not already present (deduped by ``chunk_id``). The cap is
    :data:`MERGED_MAX_TOTAL_CHUNKS` when referenced chunks are present
    (referenced ≤ REFERENCED_MAX_CHUNKS, so KB retains ≥ 4 slots) and
    the shipped :data:`RAG_MAX_TOTAL_CHUNKS` otherwise (pure-KB turns
    are byte-identical to pre-referenced-files behavior). Order determines the
    ``[N]`` citation indices in the context block.
    """
    cap = MERGED_MAX_TOTAL_CHUNKS if referenced else RAG_MAX_TOTAL_CHUNKS
    out: list[HybridSearchResult] = []
    seen: set[uuid.UUID] = set()
    for chunk in [*referenced, *kb]:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        out.append(chunk)
        if len(out) >= cap:
            break
    return out
```

**Step 4.4 — validate in `send_message`** (right after `effective_file_ids = ...` at ~`:1233`):

```python
    # referenced-files — validate caller-referenced matter files (owned + in a KB
    # attached to the chat's project + ready). 404 id-probing-safe on any
    # miss; empty/omitted is a no-op. Also yields each file's matter-KB
    # hybrid_alpha for the file-scoped retrieval below.
    effective_referenced_file_ids, referenced_alpha_by_id = await _validate_referenced_file_ids(
        db,
        payload.referenced_file_ids,
        owner_id=user.id,
        project_id=chat.project_id,
    )
```

**Step 4.5 — replace the retrieval/injection block** (`:1420-1480`, from the Wave D.1 T7b comment + `_retrieve_kb_context_for_chat` call through the KB-audit `await db.commit()`):

```python
    # Wave D.1 T7b — KB RAG across the project's attached KBs. Returns
    # the query embedding it computed so the referenced-files referenced-file pass
    # below can reuse it (referenced files live in the same attached
    # KBs; one embed call per turn).
    kb_chunks, kb_ids_searched, rag_query_embedding = await _retrieve_kb_context_for_chat(
        db,
        chat=chat,
        query=effective_content,
        gateway=gateway,
        request_id=request.headers.get("x-request-id"),
    )

    # referenced-files — per-file retrieval for explicitly referenced files.
    referenced_chunks = await _retrieve_referenced_file_context(
        db,
        referenced_file_ids=effective_referenced_file_ids,
        alpha_by_id=referenced_alpha_by_id,
        query=effective_content,
        query_embedding=rag_query_embedding,
    )

    # Merge: referenced first (explicit intent), then KB, deduped +
    # capped. The single ``retrieved_chunks`` local flows to the context
    # block AND to every _persist_message_citations call site, so both
    # KB and referenced chunks become citable with no change to the
    # citation path.
    retrieved_chunks = _merge_retrieved_chunks(referenced_chunks, kb_chunks)
    injected_chunk_ids = {c.chunk_id for c in retrieved_chunks}

    gw_messages: list[ChatCompletionMessage] = []
    if retrieved_chunks:
        context_block = _format_retrieval_context_block(retrieved_chunks)
        # M2-D2 / Decision M2-1: retrieved source documents are NOT
        # pseudonymized when sent to the provider — the model needs
        # intact source quotes for citation grounding. The skip flag
        # tells the gateway's anonymization pre-middleware to leave
        # this message's content unchanged even if the chat's other
        # content is being pseudonymized. The pre-middleware still
        # pseudonymizes the user turn + any chat-side system message.
        gw_messages.append(
            ChatCompletionMessage(
                role="system",
                content=context_block,
                lq_ai_skip_anonymization=True,
            )
        )

    # T7-shape audit row for KB retrieval. chunk_ids/chunk_count record
    # what was actually INJECTED after the referenced-files merge (Receipts
    # fidelity); retrieved_count records what the search returned. On
    # pure-KB turns the two are identical, preserving T7 semantics.
    if kb_chunks:
        kb_injected = [c for c in kb_chunks if c.chunk_id in injected_chunk_ids]
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
                "chunk_count": len(kb_injected),
                "chunk_ids": [str(c.chunk_id) for c in kb_injected],
                "retrieved_count": len(kb_chunks),
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

   Note the original KB-audit was inside `if retrieved_chunks:`; it is now gated on `if kb_chunks:` — identical semantics on pure-KB turns (empty kb_chunks ⇔ empty retrieved_chunks there). Everything downstream (the `file_ids` verbatim block `:1482-1528`, history, gw_request build) stays untouched. Run `tests/test_chat_rag.py` and `tests/test_kb_retrieval_audit.py` after this step — they assert by action name, not exact details dicts, but verify; if any asserts an exact details dict, extend the expectation with `retrieved_count` (a deliberate, documented additive change).

**Step 4.6 — thread the echo.** The `applied_file_ids` sites read `request.lq_ai_file_ids` off the gateway request inside the dispatch helpers, where `effective_referenced_file_ids` is NOT in scope. Do NOT touch the gateway `ChatCompletionRequest`. Instead:

- Add parameter `referenced_file_ids: list[str] | None = None` to `_non_streaming_response` (~`:2856`) and `_stream_response` (~`:3250`).
- Pass `referenced_file_ids=effective_referenced_file_ids` at both call sites (`:1637`, `:1652`).
- `_non_streaming_response`: add `applied_referenced_file_ids=list(referenced_file_ids or [])` to all four `MessagePostResponse(...)` builds — tool-loop final (~`:3001`), confirmation-gate placeholder (~`:3094`), MCP-auth placeholder (~`:3124`), single-shot (~`:3225`). (Validation succeeded before the gate, so the placeholders echo too — the client's picker state survives the confirmation round-trip.)
- `_stream_response`: add `"applied_referenced_file_ids": list(referenced_file_ids or []),` to the `complete` frame dict (~`:3648-3671`, next to `"applied_file_ids"`).
- `resume_tool_call`'s `complete` frame (~`:2310`, the one with `"applied_file_ids": []`): add `"applied_referenced_file_ids": [],` for shape parity (turn state does not survive the pause — known limitation, ADR 0022).

**Step 4.7 — integration tests** (append to `api/tests/integration/test_referenced_files_send.py`). Build the client fixture on the pattern in `tests/integration/test_attached_skills_send.py:64` (ASGI `AsyncClient`, dependency overrides, gateway stub). For the citation e2e, follow `tests/test_chat_citations.py` (~`:290`): patch `app.api.chats.hybrid_search_files` to return `HybridSearchResult`s pointing at REAL seeded `Document` rows whose `normalized_content` contains the quoted passage, and stub the gateway to reply `"<verbatim passage>" (Source: [1])` so Stage-1 verification persists a row. (The real `hybrid_search_files` is covered against the DB by Task 2's tests; patching here isolates the wiring under test.) Cases:

- **Citation e2e:** POST send with `referenced_file_ids=[file_id]` (non-streaming) → 200; `applied_referenced_file_ids == [str(file_id)]`; GET `/chats/{id}/messages/{msg_id}/citations` contains a row whose source file is the referenced file.
- **Foreign id:** POST with a random uuid → 404.
- **Projectless chat:** POST to a chat with no `project_id` with any referenced id → 404.
- **No-op back-compat:** POST without `referenced_file_ids` → 200, `applied_referenced_file_ids == []`, and no `inference.message_referenced_files` audit row.
- **Audit row:** after the e2e send, one `inference.message_referenced_files` audit row exists with `file_ids`, `referenced_count`, `chunk_count`, `chunk_ids` and NO content/query keys.

**Step 4.8 — gate:** run the new module + `tests/test_chat_rag.py` + `tests/test_kb_retrieval_audit.py` + `tests/test_chat_citations.py` + `tests/test_chats_send_message.py`; linters on `app/api/chats.py`.

**Step 4.9 — commit:** `git commit -s -m "feat(chats): ground + cite referenced files in send_message" -m "Refs referenced-files"`

---

### Task 5: Contract + docs (OpenAPI, PRD, ADR 0022) and full-suite gate

**Files:**
- Modify: `docs/api/backend-openapi.yaml` (`MessageCreate` request schema + the send-response schema — find the exact schema names by grepping `file_ids` in the YAML; mirror how `applied_file_ids` is documented)
- Modify: `docs/PRD.md` (§3.1 chat API surface; §3.3 Citation Engine)
- Create: `docs/adr/0022-referenced-file-ids-chat.md` (follow the template/style of `docs/adr/0021-*.md`)

**Steps:**

1. OpenAPI — add to the message-create schema:

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

   and to the send response schema:

```yaml
        applied_referenced_file_ids:
          type: array
          items:
            type: string
            format: uuid
          description: referenced-files echo of the validated referenced_file_ids.
```

2. Conformance (authoritative — never eyeball the YAML): `.venv/bin/pytest tests/test_openapi.py -q`. No new path → `EXPECTED_PATHS`/count untouched. NOTE: `docs/api/backend-openapi.yaml` does not parse with plain `yaml.safe_load` (pre-existing) — the test is the check. Also check whether the repo has a generated-OpenAPI drift guard (commit `c11e62e` added one — grep `.github/workflows` / `scripts` for openapi export) and regenerate the export if the guard requires it.

3. PRD — in §3.1 after the `file_ids` channel description add:

```markdown
  A parallel `referenced_file_ids` list (referenced-files) references matter documents that are **retrieved and cited** (KB-only MVP), as opposed to `file_ids` which injects verbatim text without citations.
```

   In §3.3 note citations may be grounded in explicitly referenced files, not only project-wide KB retrieval. Add the referenced-files entry to §9 (after DE-376) recording this shipped Phase-1 scope and the deferred Phase 2 (`@`-mention) / Phase 3 (embed-on-reference).

4. ADR 0022 — record ALL of: (a) new field vs overloading `file_ids` (chosen: new field; non-breaking, preserves verbatim small-doc channel); (b) KB-only MVP + matter scope, embed-on-reference deferred (Phase 3); (c) P9 rationale (retrieval-grounded chunks through the existing skip-anonymization context block, not a verbatim dump); (d) P2 (UI-selected set, not a model-callable tool); (e) merged-cap raise 10→16 when references present, referenced ≤ 12, pure-KB turns unchanged; (f) alpha derived per file as MIN matter-KB `hybrid_alpha` (honors operator tuning, P8; operator toggle inherits chat+KB enablement); (g) KB-wide RAG still runs alongside explicit references (referenced chunks take priority); (h) known limitations: confirmation-gate resume path persists no chunk citations (pre-existing, separate DE to file), and a validated file can contribute zero chunks yet echo as applied (audit `chunk_count` exposes it).

5. Full gate: `cd api && .venv/bin/ruff format --check . && .venv/bin/ruff check . && DATABASE_URL=... .venv/bin/pytest -m "not provider and not slow" -q`.

6. Commit: `git commit -s -m "docs(chats): document referenced_file_ids channel + ADR 0022" -m "Refs referenced-files"`
