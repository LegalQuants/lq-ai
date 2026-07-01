# WS-E PR1b — Fetched-authority verification + ledger-backing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a fetched-authority quote (a GovInfo statute/reg passage) a first-class **char-fidelity-verified, ledger-backed, gate-counted** citation in the autonomous matter path — closing DE-369 — by durably storing the fetched body and reusing the existing `verify()` cascade, citation ledger, and fiduciary gate.

**Architecture:** Mirror the caselaw path exactly (ADR 0021 D3 "mirror-the-caselaw-path"). New durable `authority_text_cache` (object-storage body + metadata row, written at fetch); new `message_authority_citations` table (mirrors `message_caselaw_citations`); a 4th `citation_ledger_entry` FK slot; a thin `citation/authority.py` substrate that reuses `verify()`/`locate_passage` unchanged; and a `build_authority_citations` delivery hook in `ledger_bridge.py`. No new verifier, no new gate, no new egress. **Chat consumer is PR1c (out of scope here).**

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, pytest, ruff, mypy. Subsystems: `api/app/models/`, `api/app/citation/`, `api/app/autonomous/`, `api/alembic/`.

**Spec:** `docs/superpowers/specs/2026-06-30-wse-pr1b-authority-verification-design.md` (read it first — it has the column lists, the cache semantics, and the invariants).

## Global Constraints

- **Security-gated** (`api/app/autonomous/**`, `api/app/citation/**`, a migration): security/maintainer merges; mirror `origin/main → tucuxi` after. Claude does NOT self-merge.
- **Mirror caselaw, reuse the core** (ADR 0016 P6 / 0018): import and reuse `app.citation.verification.verify`, `app.citation.caselaw.locate_passage`, `assemble_ledger_entries`, `compute_and_record_gate` — never re-implement. `gate.py` is **unchanged** (authority reuses the method strings `exact_match`/`tolerant_match`/`paraphrase_judge`, which already bucket).
- **Never poison the session** (WS-D PR1-C1): the cache write and `build_authority_citations` are best-effort — any failure drops to a non-fatal skip / fallback, never an exception that aborts delivery or poisons the `AsyncSession`. Mirror `build_caselaw_citations`'s posture + `build_session_ledger`'s SAVEPOINT isolation.
- **P3** (ADR 0016): the body lives in object storage (read at trace time); audit/ledger rows reference the citation row + offsets only. `authority_text_cache` is a **content store** (like `ResearchOpinionMetadata`) — do NOT add it to the `_AUDIT_MODELS` no-raw-payload tripwire.
- **Cache key** `(source_type, external_ref)`; `source_type` (the registry source, "govinfo") is distinct from `content_kind` (statute/regulation, the ledger label) — both are stored columns on the citation row.
- **No new egress** — PR1b stores/verifies what PR1a already fetched; it calls the gateway nowhere.
- **Migration discipline:** `0064` down_revision `0063`. Verify on a **throwaway** `pgvector/pgvector:pg16` (conftest auto-migrates); NEVER run host `alembic upgrade` against the dev DB. When the migration lands in the dev stack, rebuild `api`+`arq-worker`+`ingest-worker` together.
- **Tests:** api host venv `api/.venv` + throwaway pgvector, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test`. **Run the api suite SOLO** (DE-368 — no concurrent pytest against the shared DB). Object storage in tests: mirror how existing research/caselaw tests stub/use the storage client (read `api/tests` for the pattern — likely a local/tmpdir or in-memory storage fixture).
- **CI gate (repo root):** `ruff check api scripts` + `ruff format --check api scripts`; `mypy app` (whole-app); full api suite. Next DE = DE-370.
- Commits: `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## File structure

| File | Change | Task |
|---|---|---|
| `api/alembic/versions/0064_*.py` | NEW migration (2 tables + alter `citation_ledger_entry`) | 1 |
| `api/app/models/message_authority_citation.py` | NEW `MessageAuthorityCitation` | 1 |
| `api/app/models/authority_text_cache.py` | NEW `AuthorityTextCache` | 1 |
| `api/app/models/citation_ledger_entry.py` | add `message_authority_citation_id` FK + 4-term CHECK | 1 |
| `api/app/models/__init__.py` | export the 2 new models | 1 |
| `api/app/citation/authority.py` | NEW substrate: `authority_target`, `store_authority_text`, `load_authority_text`, `_AuthorityCandidate` | 2 |
| `api/app/citation/ledger.py` | 4th (authority) branch in `assemble_ledger_entries` + `resolve_ledger_entries` | 3 |
| `api/app/autonomous/guard.py` | `_handle_retrieve_authority` writes cache + `data["authority"]["source"]` | 4 |
| `api/app/autonomous/planner.py` | `EvidenceItem.source` field + `collect_evidence` authority sets it | 4 |
| `api/app/autonomous/ledger_bridge.py` | `build_authority_citations` + the `"authority"` split branch + call site | 5 |

---

### Task 1: Schema — migration 0064 + the two models + the 4th ledger FK

**Files:**
- Create: `api/app/models/message_authority_citation.py`, `api/app/models/authority_text_cache.py`
- Create: `api/alembic/versions/0064_authority_citations_and_text_cache.py`
- Modify: `api/app/models/citation_ledger_entry.py`, `api/app/models/__init__.py`
- Test: `api/tests/test_authority_models.py` (new)

**Interfaces:**
- Produces:
  - `MessageAuthorityCitation` — columns: `id: UUID` (PK), `message_id: UUID` (NOT NULL FK→messages.id CASCADE), `source_type: str`, `external_ref: str`, `content_kind: str`, `source_offset_start: int`, `source_offset_end: int`, `source_text: str`, `verified: bool`, `verification_method: str | None`, `verification_confidence: float | None`, `partial: bool`, `created_at: datetime`. Table `message_authority_citations`.
  - `AuthorityTextCache` — columns: `id: UUID` (PK), `source_type: str`, `external_ref: str`, `storage_path: str`, `char_length: int`, `retrieved_at: datetime`, `created_at: datetime`. Table `authority_text_cache`, UNIQUE `(source_type, external_ref)`.
  - `CitationLedgerEntry.message_authority_citation_id: UUID | None` (FK→message_authority_citations.id CASCADE); the exactly-one CHECK now sums 4 terms.

**Steps:**

- [ ] **Step 1: Read the templates.** Read `api/app/models/message_caselaw_citation.py` (the full model + its CHECK constraints), `api/app/models/research.py:31` (`ResearchOpinionMetadata` — the content-cache shape to mirror for `AuthorityTextCache`), and `api/app/models/citation_ledger_entry.py:1-60` (the 3 existing FK slots + `chk_citation_ledger_entry_exactly_one_source`). Read the latest migration `api/alembic/versions/0063_chat_autonomous_session_id.py` for the migration style + `down_revision`.

- [ ] **Step 2: Write the failing test** (`api/tests/test_authority_models.py`). It relies on the conftest auto-migration against the throwaway pgvector, so it exercises the real migration + CHECKs:

```python
import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.message_authority_citation import MessageAuthorityCitation
from app.models.authority_text_cache import AuthorityTextCache
from app.models.citation_ledger_entry import CitationLedgerEntry


async def _a_message(db) -> uuid.UUID:
    """Create the minimal user→chat→message chain; return message_id.

    Mirror the helper used in tests/test_caselaw_*.py / tests/test_ledger_*.py —
    read one of those for the exact fixture factory and reuse it here.
    """
    ...  # reuse the existing message-factory helper from the caselaw/ledger tests


@pytest.mark.asyncio
async def test_authority_citation_round_trips(db_session):
    mid = await _a_message(db_session)
    row = MessageAuthorityCitation(
        message_id=mid, source_type="govinfo", external_ref="USCODE-2022-title15",
        content_kind="statute", source_offset_start=0, source_offset_end=10,
        source_text="Every cont", verified=True, verification_method="exact_match",
        verification_confidence=1.0, partial=False,
    )
    db_session.add(row)
    await db_session.flush()
    got = (await db_session.execute(select(MessageAuthorityCitation))).scalar_one()
    assert got.source_type == "govinfo" and got.content_kind == "statute"


@pytest.mark.asyncio
async def test_authority_method_check_rejects_bad_method(db_session):
    mid = await _a_message(db_session)
    db_session.add(MessageAuthorityCitation(
        message_id=mid, source_type="govinfo", external_ref="x", content_kind="statute",
        source_offset_start=0, source_offset_end=1, source_text="a",
        verified=True, verification_method="made_up_method", partial=False,
    ))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_authority_text_cache_unique_source_external_ref(db_session):
    db_session.add(AuthorityTextCache(
        source_type="govinfo", external_ref="USCODE-2022-title15",
        storage_path="authority/govinfo/USCODE-2022-title15", char_length=5,
    ))
    await db_session.flush()
    db_session.add(AuthorityTextCache(
        source_type="govinfo", external_ref="USCODE-2022-title15",
        storage_path="authority/govinfo/dup", char_length=9,
    ))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_ledger_entry_exactly_one_of_four_sources(db_session):
    mid = await _a_message(db_session)
    ac = MessageAuthorityCitation(
        message_id=mid, source_type="govinfo", external_ref="x", content_kind="statute",
        source_offset_start=0, source_offset_end=1, source_text="a",
        verified=True, verification_method="exact_match", partial=False,
    )
    db_session.add(ac)
    await db_session.flush()
    # exactly one (the authority slot) → OK
    ok = CitationLedgerEntry(
        chat_id=(await _chat_of(db_session, mid)), message_id=mid,
        source_kind="statute", message_authority_citation_id=ac.id,
        verification_status="exact_match",
    )
    db_session.add(ok)
    await db_session.flush()
    # zero non-null FKs → CHECK violation
    db_session.add(CitationLedgerEntry(
        chat_id=(await _chat_of(db_session, mid)), message_id=mid,
        source_kind="statute", verification_status="unverified",
    ))
    with pytest.raises(IntegrityError):
        await db_session.flush()
```

(Read `tests/test_citation_ledger*.py` for the existing `_chat_of`/message-factory helpers and reuse them rather than re-authoring — match their fixtures exactly.)

- [ ] **Step 3: Run — expect failure** (models/migration missing).

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/test_authority_models.py -v`
Expected: FAIL (ImportError / undefined table).

- [ ] **Step 4: Write the two models.** `message_authority_citation.py` mirrors `message_caselaw_citation.py` verbatim, swapping `opinion_id`/`cluster_id` (BigInteger) for `source_type`/`external_ref`/`content_kind` (Text NOT NULL), and renaming the CHECK constraints to `chk_message_authority_citations_*` (keep all five: offset_start ≥ 0, offset_end > start, method ∈ {exact_match,tolerant_match,paraphrase_judge} or NULL, confidence NULL or 0..1, verified ⇒ method NOT NULL). Index on `message_id`. `authority_text_cache.py` mirrors `ResearchOpinionMetadata` shape: the columns in the Interfaces block, `UniqueConstraint("source_type","external_ref", name="uq_authority_text_cache_source_ref")`, index on `(source_type, external_ref)`, `retrieved_at`/`created_at` TIMESTAMPTZ `server_default=func.now()`. Export both in `app/models/__init__.py`.

- [ ] **Step 5: Add the FK slot to `citation_ledger_entry.py`.** Add `message_authority_citation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("message_authority_citations.id", ondelete="CASCADE"), nullable=True)`. Replace the body of `chk_citation_ledger_entry_exactly_one_source` so it sums **four** `(... IS NOT NULL)::int` terms `= 1` (add the new column to the existing three).

- [ ] **Step 6: Write the migration** `0064_authority_citations_and_text_cache.py` (`revision="0064"`, `down_revision="0063"`). `upgrade()`: `create_table("message_authority_citations", ...)` with all columns + the 5 CHECKs + the message_id index; `create_table("authority_text_cache", ...)` with the unique constraint + index; `op.add_column("citation_ledger_entry", message_authority_citation_id ...)` + `op.create_foreign_key(...)`; then `op.drop_constraint("chk_citation_ledger_entry_exactly_one_source", ...)` + `op.create_check_constraint(...)` with the 4-term body. `downgrade()` reverses in opposite order (restore the 3-term CHECK, drop the FK+column, drop both tables). Mirror the DDL style of `0057_message_caselaw_citations.py` + `0058_citation_ledger_entry.py`.

- [ ] **Step 7: Run — expect pass.**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/test_authority_models.py -v`
Expected: PASS (conftest applied 0064 to the throwaway DB).

- [ ] **Step 8: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/models/message_authority_citation.py api/app/models/authority_text_cache.py api/app/models/citation_ledger_entry.py api/app/models/__init__.py api/alembic/versions/0064_authority_citations_and_text_cache.py api/tests/test_authority_models.py
git commit -s -m "feat(citation): authority citation + text-cache tables + 4th ledger FK (WS-E PR1b, mig 0064)"
```

---

### Task 2: `citation/authority.py` substrate — verify target + the durable text cache

**Files:**
- Create: `api/app/citation/authority.py`
- Test: `api/tests/test_authority_substrate.py` (new)

**Interfaces:**
- Consumes: `app.citation.verification.verify` + its `_DocumentProtocol`/`_CandidateProtocol`; `app.citation.caselaw.locate_passage`; the object-storage util used by `research/service.py` (`upload_bytes` + the body reader — read `research/service.py:154-208` for the exact import + signatures).
- Produces:
  - `authority_target(source_type: str, external_ref: str, text: str) -> _AuthorityVerificationTarget` — `@dataclass(slots=True)` with `id: uuid.UUID` (= `uuid.uuid5(_AUTHORITY_NS, f"{source_type}:{external_ref}")`), `normalized_content: str` (= normalized `text`), `was_ocrd: bool = False`. Duck-types `_DocumentProtocol`.
  - `_AuthorityCandidate` — `@dataclass(slots=True)` with `source_offset_start: int`, `source_offset_end: int`, `source_text: str`, `source_document_id: uuid.UUID`. Duck-types `_CandidateProtocol`.
  - `async store_authority_text(db, *, source_type: str, external_ref: str, text: str) -> None`.
  - `async load_authority_text(db, *, source_type: str, external_ref: str) -> str | None`.
  - `AUTHORITY_TEXT_TTL = timedelta(days=30)`.

**Steps:**

- [ ] **Step 1: Read the templates.** `api/app/citation/caselaw.py:143-182` (`opinion_target`, `_OpinionVerificationTarget`, `_CaselawCandidate`, `locate_passage`) and `api/app/research/service.py:154-208` (`upload_bytes(storage_path=...)`, `_load_opinion`/`_read_body(storage_path)` — the object-storage write + read util to reuse). Note the normalization helper the caselaw target uses (e.g. `verification.normalize_text` or equivalent) and reuse the same one.

- [ ] **Step 2: Write the failing tests** (`api/tests/test_authority_substrate.py`):

```python
import uuid
import pytest
from datetime import timedelta
from app.citation.authority import (
    authority_target, store_authority_text, load_authority_text, AUTHORITY_TEXT_TTL,
)
from app.citation.verification import verify


def test_authority_target_is_deterministic_and_duck_types_document():
    t1 = authority_target("govinfo", "USCODE-2022-title15", "Every contract ... illegal.")
    t2 = authority_target("govinfo", "USCODE-2022-title15", "Every contract ... illegal.")
    assert t1.id == t2.id and isinstance(t1.id, uuid.UUID)
    assert t1.normalized_content and t1.was_ocrd is False


@pytest.mark.asyncio
async def test_store_then_load_round_trips(db_session):
    body = "Every contract, combination ... in restraint of trade ... is declared to be illegal."
    await store_authority_text(db_session, source_type="govinfo",
                               external_ref="USCODE-2022-title15", text=body)
    got = await load_authority_text(db_session, source_type="govinfo",
                                    external_ref="USCODE-2022-title15")
    assert got == body


@pytest.mark.asyncio
async def test_load_returns_none_when_absent(db_session):
    assert await load_authority_text(db_session, source_type="govinfo",
                                     external_ref="missing") is None


@pytest.mark.asyncio
async def test_load_returns_none_when_stale(db_session, monkeypatch):
    await store_authority_text(db_session, source_type="govinfo",
                               external_ref="USCODE-old", text="old body")
    # age the row past the TTL
    from app.models.authority_text_cache import AuthorityTextCache
    from sqlalchemy import select, update
    from datetime import datetime, timezone
    stale = datetime.now(timezone.utc) - AUTHORITY_TEXT_TTL - timedelta(days=1)
    await db_session.execute(update(AuthorityTextCache)
                             .where(AuthorityTextCache.external_ref == "USCODE-old")
                             .values(retrieved_at=stale))
    await db_session.flush()
    assert await load_authority_text(db_session, source_type="govinfo",
                                     external_ref="USCODE-old") is None


@pytest.mark.asyncio
async def test_verify_exact_match_against_authority_target(db_session):
    body = "Every contract ... in restraint of trade ... is declared to be illegal."
    target = authority_target("govinfo", "USCODE-2022-title15", body)
    from app.citation.authority import _AuthorityCandidate
    from app.citation.caselaw import locate_passage
    quote = "in restraint of trade"
    off = locate_passage(quote, target.normalized_content)
    assert off is not None
    cand = _AuthorityCandidate(source_offset_start=off[0], source_offset_end=off[1],
                               source_text=quote, source_document_id=target.id)
    result = await verify(cand, target, gateway=None)  # deterministic stages 1-2
    assert result.verified and result.method in {"exact_match", "tolerant_match"}
```

(Use the project's existing object-storage test fixture — read `tests/test_research_service.py` / `tests/conftest.py` for how opinion-body storage is backed in tests, and reuse that backing so `store`/`load` hit the same store.)

- [ ] **Step 3: Run — expect failure** (module missing).

- [ ] **Step 4: Implement `authority.py`.** `_AUTHORITY_NS = uuid.UUID(<a fixed namespace literal, distinct from caselaw's _OPINION_NS>)`. `authority_target` builds the dataclass with `uuid5` + the same normalization the caselaw target uses. `_AuthorityCandidate` mirrors `_CaselawCandidate`. `store_authority_text`: normalize? (store the RAW body — verification normalizes the target's content, candidates carry raw offsets into normalized content exactly as caselaw does; store what `load` must return for `authority_target(text=...)`, i.e. the body the verifier will normalize — match caselaw's choice). Compute `storage_path = f"authority/{source_type}/{external_ref}"`, `upload_bytes(storage_path, text.encode("utf-8"))`, then upsert the `AuthorityTextCache` row (`select` existing by `(source_type, external_ref)`; update `storage_path`/`char_length`/`retrieved_at` or insert) — `retrieved_at = now`. `load_authority_text`: select the row; if none → `None`; if `retrieved_at < now - AUTHORITY_TEXT_TTL` → `None`; else read the body from `storage_path` via the same reader caselaw uses, decode, return.

- [ ] **Step 5: Run — expect pass.**

Run: `cd api && DATABASE_URL=... .venv/bin/python -m pytest tests/test_authority_substrate.py -v`

- [ ] **Step 6: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/citation/authority.py api/tests/test_authority_substrate.py
git commit -s -m "feat(citation): authority verify target + durable text cache (WS-E PR1b)"
```

---

### Task 3: Ledger assembly + resolve — the 4th (authority) branch

**Files:**
- Modify: `api/app/citation/ledger.py` (`assemble_ledger_entries`, `_resolve_source`, `resolve_ledger_entries`)
- Test: `api/tests/test_authority_ledger.py` (new)

**Interfaces:**
- Consumes: `MessageAuthorityCitation` (Task 1); the existing `assemble_ledger_entries(db, *, message_id)` / `resolve_ledger_entries(db, *, chat_id, message_id=None)` / `compute_and_record_gate(db, *, message_id)`.
- Produces: ledger rows for authority citations (`source_kind = ac.content_kind`, `message_authority_citation_id`, `verification_status = method if verified else "unverified"`, `provider = ac.source_type`); the read path resolves them to `{kind, passages}` blocks; the gate counts them.

**Steps:**

- [ ] **Step 1: Read** `api/app/citation/ledger.py:32-180` (the doc/caselaw/tool branches of `assemble_ledger_entries` + `_resolve_source`) and `:229-345` (`resolve_ledger_entries` batch-fetch dicts) and `api/app/citation/gate.py:25-30,83-88` (the status buckets — confirm no change needed).

- [ ] **Step 2: Write the failing tests** (`api/tests/test_authority_ledger.py`):

```python
import uuid, pytest
from sqlalchemy import select
from app.models.message_authority_citation import MessageAuthorityCitation
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.citation.ledger import assemble_ledger_entries, resolve_ledger_entries
from app.citation.gate import compute_and_record_gate


@pytest.mark.asyncio
async def test_assemble_creates_authority_ledger_entry(db_session):
    mid, cid = await _message_and_chat(db_session)  # reuse existing ledger-test helper
    db_session.add(MessageAuthorityCitation(
        message_id=mid, source_type="govinfo", external_ref="USCODE-2022-title15",
        content_kind="statute", source_offset_start=0, source_offset_end=10,
        source_text="Every cont", verified=True, verification_method="exact_match",
        verification_confidence=1.0, partial=False))
    await db_session.flush()
    await assemble_ledger_entries(db_session, message_id=mid)
    rows = (await db_session.execute(
        select(CitationLedgerEntry).where(CitationLedgerEntry.message_id == mid))).scalars().all()
    entry = next(r for r in rows if r.message_authority_citation_id is not None)
    assert entry.source_kind == "statute" and entry.verification_status == "exact_match"
    assert entry.provider == "govinfo"


@pytest.mark.asyncio
async def test_authority_unverified_flags_gate(db_session):
    mid, cid = await _message_and_chat(db_session)
    db_session.add(MessageAuthorityCitation(
        message_id=mid, source_type="govinfo", external_ref="USCODE-x",
        content_kind="statute", source_offset_start=0, source_offset_end=5,
        source_text="bogus", verified=False, verification_method=None, partial=False))
    await db_session.flush()
    await assemble_ledger_entries(db_session, message_id=mid)
    gate = await compute_and_record_gate(db_session, message_id=mid)
    assert gate.verdict == "flagged"  # unverified authority → FAIL bucket


@pytest.mark.asyncio
async def test_resolve_returns_authority_passage(db_session):
    mid, cid = await _message_and_chat(db_session)
    db_session.add(MessageAuthorityCitation(
        message_id=mid, source_type="govinfo", external_ref="USCODE-2022-title15",
        content_kind="statute", source_offset_start=0, source_offset_end=10,
        source_text="Every cont", verified=True, verification_method="exact_match",
        verification_confidence=1.0, partial=False))
    await db_session.flush()
    await assemble_ledger_entries(db_session, message_id=mid)
    resolved = await resolve_ledger_entries(db_session, chat_id=cid, message_id=mid)
    auth = [e for e in resolved if e.get("kind") in {"statute", "authority"}]
    assert auth and "Every cont" in str(auth[0])
```

(Reuse the existing `_message_and_chat`/message-factory helper from `tests/test_citation_ledger*.py`.)

- [ ] **Step 3: Run — expect failure** (no authority branch yet; assemble ignores the rows).

- [ ] **Step 4: Implement.** In `assemble_ledger_entries`, after the caselaw branch, add: `authority = (await db.execute(select(MessageAuthorityCitation).where(MessageAuthorityCitation.message_id == message_id))).scalars().all()`; per `ac` append a `CitationLedgerEntry(project_id=..., chat_id=..., message_id=message_id, source_kind=ac.content_kind, message_authority_citation_id=ac.id, verification_status=(ac.verification_method if ac.verified else "unverified"), confidence=ac.verification_confidence, provider=ac.source_type, retrieved_at=ac.created_at)`. In `resolve_ledger_entries`, add an `authority_ids` set + a bulk-fetch dict `auth_by_id`, and pass it into `_resolve_source`; in `_resolve_source` add `if entry.message_authority_citation_id is not None:` → return `{"kind": ac.content_kind, "external_ref": ac.external_ref, "provider": ac.source_type, "passages": [{"text": ac.source_text, "offset_start": ac.source_offset_start, "offset_end": ac.source_offset_end, "verified": ac.verified, "method": ac.verification_method}]}` (match the shape the caselaw branch returns). **No `gate.py` change.**

- [ ] **Step 5: Run — expect pass + the existing ledger suite (SOLO).**

Run: `cd api && DATABASE_URL=... .venv/bin/python -m pytest tests/test_authority_ledger.py tests/test_citation_ledger*.py tests/test_*gate*.py -q`

- [ ] **Step 6: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/citation/ledger.py api/tests/test_authority_ledger.py
git commit -s -m "feat(citation): route authority citations into the ledger + trace (WS-E PR1b)"
```

---

### Task 4: Autonomous fetch → cache write + thread `source` onto evidence

**Files:**
- Modify: `api/app/autonomous/guard.py` (`_handle_retrieve_authority`)
- Modify: `api/app/autonomous/planner.py` (`EvidenceItem` + `collect_evidence` authority branch)
- Test: `api/tests/autonomous/test_authority_cache_write.py` (new)

**Interfaces:**
- Consumes: `store_authority_text` (Task 2).
- Produces: after a successful `retrieve_authority`, an `AuthorityTextCache` row exists for `(params["source"], external_ref)`; `ToolResult.data["authority"]["source"] == params["source"]`; `EvidenceItem.source` AND `EvidenceItem.content_kind` carry to delivery (`content_kind` is already in `data["authority"]` from PR1a; `source` is added here).

**Steps:**

- [ ] **Step 1: Read** `api/app/autonomous/guard.py:741-868` (`_handle_retrieve_authority`, esp. the `data["authority"]` build + the docstring noting `db` is reserved for PR1b) and `api/app/autonomous/planner.py:141-210` (`EvidenceItem` dataclass + `collect_evidence`'s `retrieve_authority` branch).

- [ ] **Step 2: Write the failing tests** (`api/tests/autonomous/test_authority_cache_write.py`) — reuse the PR1a `_GovInfoGateway` double + session fixtures from `tests/autonomous/test_retrieve_authority.py`:

```python
import pytest
from sqlalchemy import select
from app.models.authority_text_cache import AuthorityTextCache
from app.autonomous.enums import ToolIntent
from app.autonomous import guard as guard_mod


@pytest.mark.asyncio
async def test_retrieve_authority_writes_cache_and_source(db_session):
    user = await _make_user(db_session)                       # reuse PR1a helpers
    sess = await _make_session(db_session, user=user, current_phase="analysis")
    gateway = _GovInfoGateway()
    result = await guard_mod.guarded_tool_call(
        sess, ToolIntent.retrieve_authority,
        {"source": "govinfo", "op": "get_authority",
         "args": {"package_id": "USCODE-2022-title15"}},
        db_session, gateway)
    assert result.data["authority"]["source"] == "govinfo"
    cached = (await db_session.execute(select(AuthorityTextCache).where(
        AuthorityTextCache.external_ref == "USCODE-2022-title15"))).scalar_one()
    assert cached.source_type == "govinfo" and cached.char_length > 0


@pytest.mark.asyncio
async def test_collect_evidence_authority_carries_source():
    from app.autonomous.planner import collect_evidence, EvidenceItem
    from app.tools.governance import ToolResult  # or wherever ToolResult lives
    res = ToolResult(cost_usd=__import__("decimal").Decimal("0"), data={"authority": {
        "text": "Every contract ... illegal.", "external_ref": "USCODE-2022-title15",
        "label": "15 U.S.C. § 1", "url": "https://...", "content_kind": "statute",
        "source": "govinfo"}})
    items = list(collect_evidence(ToolIntent.retrieve_authority, res, 1))
    assert items and items[0].kind == "authority"
    assert items[0].source == "govinfo" and items[0].ref == "USCODE-2022-title15"
```

- [ ] **Step 3: Run — expect failure.**

- [ ] **Step 4: Implement.** In `_handle_retrieve_authority`, after `authority = spec.adapter.from_response(op, payload)` and before building the result, add `data["authority"]["source"] = params["source"]` (the registry source). Then, non-fatally, write the cache:
```python
    try:
        from app.citation.authority import store_authority_text
        await store_authority_text(db, source_type=params["source"],
                                   external_ref=authority.external_ref,
                                   text=authority.citable_text)
    except Exception:
        logger.warning("autonomous.retrieve_authority: cache write failed; "
                       "verification will fall back to carried evidence text",
                       extra={"event": "authority_cache_write_failed"}, exc_info=True)
```
In `planner.py`: add `source: str | None = None` AND `content_kind: str | None = None` to the `EvidenceItem` dataclass (after `display`; both loop-local, not persisted — P3 unaffected); in `collect_evidence`'s `retrieve_authority` branch set `source=data["authority"].get("source")` and `content_kind=data["authority"].get("content_kind")` on the yielded `EvidenceItem` (leave `ref`/`content` as-is). Extend the Task-4 evidence test to also assert `items[0].content_kind == "statute"`.

- [ ] **Step 5: Run — expect pass + autonomous suite (SOLO).**

Run: `cd api && DATABASE_URL=... .venv/bin/python -m pytest tests/autonomous/test_authority_cache_write.py tests/autonomous -q`

- [ ] **Step 6: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/guard.py api/app/autonomous/planner.py api/tests/autonomous/test_authority_cache_write.py
git commit -s -m "feat(autonomous): persist fetched authority text to the cache + thread source (WS-E PR1b)"
```

---

### Task 5: Autonomous delivery — `build_authority_citations` + the session-ledger branch

**Files:**
- Modify: `api/app/autonomous/ledger_bridge.py` (`build_authority_citations` + the citation-split branch + the call site)
- Test: `api/tests/autonomous/test_session_authority_ledger.py` (new)

**Interfaces:**
- Consumes: `authority_target`, `_AuthorityCandidate`, `load_authority_text` (Task 2); `verify` + `locate_passage`; `assemble_ledger_entries` + `compute_and_record_gate` (already called by `build_session_ledger`).
- Produces: at delivery, a finding that quotes a fetched authority yields a `MessageAuthorityCitation` (verified or FAIL) → a ledger entry → a counted gate verdict.

**Steps:**

- [ ] **Step 1: Read** `api/app/autonomous/ledger_bridge.py:181-301` (`build_caselaw_citations` — the exact template) and `:309-398` (`build_session_ledger`: the `by_n` evidence index `:340-342`, the citation-split loop `:347-355` that currently drops `"authority"`, the manufactured `Message` `:371-373`, the `build_*_citations` call site `:376-381`, and the `assemble_ledger_entries`+`compute_and_record_gate` calls `:384-385`).

- [ ] **Step 2: Write the failing tests** (`api/tests/autonomous/test_session_authority_ledger.py`). Drive `build_session_ledger` directly with a findings/evidence pair (mirror the existing `build_session_ledger` tests — read `tests/autonomous/test_ledger_bridge*.py`). Seed the cache via `store_authority_text` so the load path is exercised; also cover the cache-miss → carried-content fallback:

```python
import pytest
from app.autonomous.ledger_bridge import build_session_ledger
from app.citation.authority import store_authority_text

_BODY = "Every contract, combination ... in restraint of trade ... is declared to be illegal."

def _evidence():
    return [{"n": 1, "kind": "authority", "ref": "USCODE-2022-title15",
             "content": _BODY, "display": "15 U.S.C. § 1", "source": "govinfo"}]

@pytest.mark.asyncio
async def test_verbatim_authority_quote_verified_and_counted(db_session):
    sess = await _make_session(db_session)                 # reuse ledger-bridge test helper
    await store_authority_text(db_session, source_type="govinfo",
                               external_ref="USCODE-2022-title15", text=_BODY)
    findings = [{"text": "The statute bars restraint of trade.",
                 "citations": [{"quote": "in restraint of trade", "source": 1}]}]
    out = await build_session_ledger(db_session, session=sess,
        work_product_text="… in restraint of trade …", findings=findings,
        evidence=_evidence(), gateway=None)
    assert out is not None and out["pass_count"] >= 1 and out["fail_count"] == 0

@pytest.mark.asyncio
async def test_fabricated_authority_quote_flags_gate(db_session):
    sess = await _make_session(db_session)
    await store_authority_text(db_session, source_type="govinfo",
                               external_ref="USCODE-2022-title15", text=_BODY)
    findings = [{"text": "bogus", "citations": [
        {"quote": "the statute expressly permits price fixing", "source": 1}]}]
    out = await build_session_ledger(db_session, session=sess,
        work_product_text="…", findings=findings, evidence=_evidence(), gateway=None)
    assert out is not None and out["fail_count"] >= 1 and out["gate_status"] == "flagged"

@pytest.mark.asyncio
async def test_cache_miss_falls_back_to_carried_content(db_session):
    sess = await _make_session(db_session)
    # do NOT seed the cache → load_authority_text returns None → fallback to ev["content"]
    findings = [{"text": "…", "citations": [{"quote": "in restraint of trade", "source": 1}]}]
    out = await build_session_ledger(db_session, session=sess,
        work_product_text="…", findings=findings, evidence=_evidence(), gateway=None)
    assert out is not None and out["pass_count"] >= 1
```

- [ ] **Step 3: Run — expect failure** (authority dropped → no authority citation, counts wrong).

- [ ] **Step 4: Implement.** Add `build_authority_citations(db, *, message_id, items, load_authority_text=_default_load_authority_text, gateway, judge_model="fast") -> int` mirroring `build_caselaw_citations`: for each `item` (a tuple/namedtuple `(quote, source, external_ref, content_kind, carried_text)`), `body = await load_authority_text(db, source_type=item.source, external_ref=item.external_ref)` and if `None` use `item.carried_text`; if still falsy → skip; `target = authority_target(item.source, item.external_ref, body)`; `off = locate_passage(quote, target.normalized_content)`; if `None` → a FAIL row (`verified=False, method=None`, offsets `(0,0)`? — mirror caselaw's `_fail_row` exactly for the no-locate case); else `cand = _AuthorityCandidate(off[0], off[1], quote, target.id)`, `result = await verify(cand, target, gateway=gateway, judge_model=judge_model)`, build the `MessageAuthorityCitation(message_id, source_type=item.source, external_ref=item.external_ref, content_kind=item.content_kind, source_offset_start=off[0], source_offset_end=off[1], source_text=quote, verified=result.verified, verification_method=result.method, verification_confidence=result.confidence, partial=result.partial)`. `db.add_all(rows)` + `flush`. Use `_default_load_authority_text = load_authority_text` (injectable for tests). In the split loop (`:347-355`) add the `ev["kind"] == "authority"` branch collecting `(c["quote"], ev["source"], ev["ref"], ev.get("content_kind") or "statute", ev["content"])` — `source` and `content_kind` are threaded onto the authority evidence in Task 4 (default `"statute"` only as a defensive fallback). Call `build_authority_citations(db, message_id=message.id, items=authority_items, gateway=gateway, judge_model=judge_model)` next to the caselaw call (`:376-381`), inside the same best-effort guard. (`assemble_ledger_entries` + `compute_and_record_gate` already run after — authority rows are picked up by Task 3's branch.)

- [ ] **Step 5: Run — expect pass + autonomous suite (SOLO).**

Run: `cd api && DATABASE_URL=... .venv/bin/python -m pytest tests/autonomous/test_session_authority_ledger.py tests/autonomous -q`

- [ ] **Step 6: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/ledger_bridge.py api/tests/autonomous/test_session_authority_ledger.py
git commit -s -m "feat(autonomous): verify fetched-authority quotes at delivery → ledger + gate (WS-E PR1b)"
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
- [ ] **Migration sanity:** confirm `0064` is the only new version, `down_revision="0063"`, and the conftest auto-migration applied it cleanly (the model tests prove it). Do NOT host-`alembic upgrade` the dev DB; when landing in the dev stack, rebuild `api`+`arq-worker`+`ingest-worker` together.
- [ ] **`content_kind` threading check:** confirm the authority `EvidenceItem`/`data["authority"]` carries `content_kind` end-to-end (handler → evidence → `build_authority_citations` → row). If Task 4 didn't already thread it, fold the one-line addition there and re-gate.
- [ ] **PRD bookkeeping:** mark **DE-369** SHIPPED for the autonomous path (note PR1c completes the chat path). No new DE unless one surfaces.
- [ ] **Opus whole-branch review** (SDD final) — required; it has caught a real gate-passing defect on every slice this milestone. Hunt: never-poison (cache write + `build_authority_citations` best-effort, no aborted delivery); the FAIL-on-no-locate / fabricated-quote path actually flags the gate; the 4-term ledger CHECK is genuinely enforced (not loosened); P3 (no body in audit/ledger rows; `authority_text_cache` outside `_AUDIT_MODELS`); cache TTL boundary; cache-miss fallback correctness.
- [ ] **Push origin + tucuxi → security-gated PR (NO self-merge) → mirror after merge.**

## Plan self-review (completed)
- **Spec coverage:** DE-369 criterion 1 (durable text) → Tasks 1-2 + Task 4 (write) + Task 5 (read); criterion 2 (`message_authority_citations` + char-verify) → Tasks 1, 2, 5; criterion 3 (ledger FK + gate counts) → Tasks 1, 3, 5; criterion 4 (P3) → Task 1 (content store outside tripwire) + final-gate hunt. Chat consumer explicitly deferred to PR1c.
- **Placeholder scan:** the only "read X and reuse" pointers are to concrete file:line templates (caselaw.py, ledger.py, service.py object-storage, the existing test helpers) — the asserted contracts (column lists, op output, verify reuse, ledger shape) are fixed; test code is real.
- **Type consistency:** `authority_target(source_type, external_ref, text)`, `_AuthorityCandidate(source_offset_start, source_offset_end, source_text, source_document_id)`, `store_authority_text`/`load_authority_text(db, *, source_type, external_ref[, text])`, `MessageAuthorityCitation(... source_type, external_ref, content_kind ...)`, `EvidenceItem.source`, `build_authority_citations(db, *, message_id, items, load_authority_text, gateway, judge_model)` are consistent across Tasks 1-5. `source_type` (cache/provenance key) vs `content_kind` (ledger label) are kept distinct throughout.
- **Open item flagged for Task 4/5:** `content_kind` must be threaded onto the authority evidence alongside `source` (Task 4) so Task 5 can persist it; the final gate re-checks this end-to-end.
