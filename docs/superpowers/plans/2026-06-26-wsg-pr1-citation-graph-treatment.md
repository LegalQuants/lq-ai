# WS-G PR1 — Citation-graph treatment signal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive a cited case's citation-graph signal ("cited by N later opinions; here are the most recent N") off the turn's critical path, cache it per case, and populate the ledger's reserved `treatment_id` slot — no LLM-judge (that is PR2).

**Architecture:** A new `get_citing_opinions` CourtListener gateway op (Search API `cites:` filter) → a thin `research.service` wrapper → a `derive_treatment_for_message` service that upserts a `citation_treatment` row per cited case and links the turn's caselaw ledger entries → an arq job enqueued after turn finalize → `resolve_ledger_entries` exposes the signal on the `/ledger` read. Strictly additive; treatment never gates the turn.

**Tech Stack:** Python 3.12, async SQLAlchemy + Alembic, FastAPI, arq (Redis), pytest/pytest-asyncio. Gateway is `mypy --strict`. No new dependency.

## Global Constraints

- **Security-gated** (`gateway/**` + `api/app/citation/**`): **do not self-merge**; Kevin/security merges; mirror `origin/main → tucuxi` after.
- **No judge in PR1.** No LLM call anywhere in this PR. The signal is graph-only (`derived_method="citation_graph"`).
- **Graph signal:** `cited_by_count` (the upstream total) + a capped list of **N=30** citing-opinion refs, ordered **most-recent-first** (`order_by=dateFiled desc`). *(The spec's "highest-court-then-recent" is not server-orderable on CourtListener's Search API; court-rank re-ranking of the materialized subset is PR2. v1 = most-recent-first. `cited_by_count` is the upstream `count`, NEVER the truncated list length.)*
- **P3:** `citation_treatment.citing_opinions` holds **structured refs only** (`cluster_id`, `opinion_id`, `case_name`, `court`, `date_filed`) — never opinion text. The model joins the P3 tripwire (`_AUDIT_MODELS`). No column name may match the tripwire denylist (`text`, `content`, `body`, `payload`, `*_opinions` is fine — not on the list).
- **Treatment never gates the turn.** The fiduciary-grade gate (ADR 0018 D3) is untouched; derivation runs async after `_audit_message_sent`; absent treatment → `treatment: null` on the read.
- **`cites:` keys on opinion id.** `message_caselaw_citations` carries both `opinion_id` and `cluster_id`; derivation cites-searches the `opinion_id` and caches keyed by `cluster_id`.
- **Tests:** host venv + throwaway pgvector (`lqai-test-pg` :55432, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test`, conftest auto-migrates). Gateway tests mock `_request`; api tests mock the citing fetch — **no `-m provider`**, no live CourtListener. Run `ruff format` AND `ruff check` on touched files; gateway is `mypy --strict`.
- **Commits:** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Next migration = `0061`.

---

### Task 1: Gateway op `get_citing_opinions` (CourtListener Search `cites:` filter)

**Files:**
- Modify: `gateway/app/providers/tool/courtlistener.py` (`list_tools` add a `ToolSpec`; `invoke_tool` add a branch; add `_get_citing_opinions` + a `_CITING_TOP_N` const)
- Test: `gateway/tests/providers/tool/test_courtlistener.py` (extend; if absent, create — locate the existing CL provider test first)

**Interfaces:**
- Consumes: the provider's `self._request(method, path, params=...)`, `self._result(tool, payload, *, sent, received)`, `_cursor_from`, and the existing `_search_case_law` result-mapping shape.
- Produces: tool `get_citing_opinions`, input `{"opinion_id": int}`, payload `{"cited_by_count": int, "citing": [{"cluster_id", "opinion_id", "case_name", "court", "date_filed"}]}` (≤30, most-recent-first).

- [ ] **Step 1: Write the failing test**

Locate the existing CL provider test (`grep -rl "class.*CourtListener\|_search_case_law\|get_cases" gateway/tests`). Mirror its HTTP-mock style (it stubs `_request`/httpx). Add:

```python
@pytest.mark.asyncio
async def test_get_citing_opinions_shapes_count_and_capped_list(monkeypatch) -> None:
    provider = _make_provider()  # mirror the existing helper in this test module
    # 32 citing results upstream; count=412 total.
    results = [
        {"cluster_id": 1000 + i, "caseName": f"Citing Case {i}", "court": "ca9",
         "dateFiled": f"2020-01-{(i % 28) + 1:02d}", "citation": [], "absolute_url": "/x"}
        for i in range(32)
    ]
    captured = {}

    async def fake_request(method, path, *, params=None, json_body=None):
        captured["method"], captured["path"], captured["params"] = method, path, params
        return _FakeResp({"count": 412, "results": results, "next": None})

    monkeypatch.setattr(provider, "_request", fake_request)
    result = await provider.invoke_tool("get_citing_opinions", {"opinion_id": 2812209}, request_id="r")
    payload = result.payload  # adapt to how ToolResult exposes payload in this test module

    assert captured["method"] == "GET"
    assert captured["path"] == "/search/"
    assert captured["params"]["q"] == "cites:(2812209)"
    assert captured["params"]["type"] == "o"
    assert captured["params"]["order_by"] == "dateFiled desc"
    assert payload["cited_by_count"] == 412          # upstream total, NOT 30
    assert len(payload["citing"]) == 30              # capped at N
    assert payload["citing"][0]["case_name"] == "Citing Case 0"
    assert payload["citing"][0]["court"] == "ca9"
    assert set(payload["citing"][0]) == {"cluster_id", "opinion_id", "case_name", "court", "date_filed"}


@pytest.mark.asyncio
async def test_get_citing_opinions_requires_integer_opinion_id() -> None:
    provider = _make_provider()
    with pytest.raises(ToolProviderInvalidRequestError):
        await provider.invoke_tool("get_citing_opinions", {"opinion_id": "x"}, request_id="r")
```

*(Adapt `_make_provider`, `_FakeResp`, and `result.payload` access to the existing test module's conventions — read it first.)*

- [ ] **Step 2: Run to verify it fails**

Run: `cd gateway && .venv/bin/python -m pytest tests/providers/tool/test_courtlistener.py -k citing -v` (adjust path)
Expected: FAIL — `unknown tool 'get_citing_opinions'`.

- [ ] **Step 3: Implement the op**

In `gateway/app/providers/tool/courtlistener.py`, add near the top (module constant):

```python
_CITING_TOP_N = 30
```

Add to the `list_tools` list (after the `get_cases` ToolSpec):

```python
ToolSpec(
    name="get_citing_opinions",
    description="List later opinions that CITE a given opinion id (the "
    "'cited by' direction), via the CourtListener Search API. Returns the "
    "total cited-by count + the most recent citing opinions (capped).",
    parameters={
        "type": "object",
        "properties": {"opinion_id": {"type": "integer"}},
        "required": ["opinion_id"],
    },
    read_only=True,
),
```

Add to `invoke_tool` (before the final `raise`):

```python
if tool == "get_citing_opinions":
    return await self._get_citing_opinions(args)
```

Add the method (mirrors `_search_case_law`):

```python
async def _get_citing_opinions(self, args: dict[str, Any]) -> ToolResult:
    opinion_id = args.get("opinion_id")
    if not isinstance(opinion_id, int) or isinstance(opinion_id, bool):
        raise ToolProviderInvalidRequestError(
            "get_citing_opinions requires integer 'opinion_id'", upstream_status=400
        )
    params = {"q": f"cites:({opinion_id})", "type": "o", "order_by": "dateFiled desc"}
    resp = await self._request("GET", "/search/", params=params)
    data = resp.json()
    citing = [
        {
            "cluster_id": r.get("cluster_id"),
            "opinion_id": (r.get("opinions") or [{}])[0].get("id"),
            "case_name": r.get("caseName"),
            "court": r.get("court"),
            "date_filed": r.get("dateFiled"),
        }
        for r in (data.get("results") or [])[:_CITING_TOP_N]
    ]
    payload = {"cited_by_count": data.get("count"), "citing": citing}
    return self._result("get_citing_opinions", payload, sent=params, received=data)
```

*(The Search `type=o` result nests the opinion id under `opinions[0].id`; `opinion_id` is best-effort and may be `None` for a result without a nested opinion — acceptable for PR1, the cluster_id is the load-bearing ref.)*

- [ ] **Step 4: Run to verify pass + mypy strict**

Run: `cd gateway && .venv/bin/python -m pytest tests/providers/tool/test_courtlistener.py -k citing -v && ruff format app/providers/tool/courtlistener.py && ruff check app/providers/tool/courtlistener.py && mypy app/providers/tool/courtlistener.py`
Expected: tests PASS; ruff clean; mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add gateway/app/providers/tool/courtlistener.py gateway/tests/providers/tool/test_courtlistener.py
git commit -s -m "feat(gateway): get_citing_opinions CourtListener op (WS-G PR1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `citation_treatment` model + migration 0061 + P3 tripwire

**Files:**
- Create: `api/app/models/citation_treatment.py`
- Create: `api/alembic/versions/0061_citation_treatment.py`
- Modify: `api/app/models/__init__.py` (export `CitationTreatment`), `api/tests/test_transparency_invariants.py` (add to `_AUDIT_MODELS`)
- Test: `api/tests/test_citation_treatment_model.py` (create)

**Interfaces:**
- Produces: `CitationTreatment` ORM model (table `citation_treatment`); columns `id, cluster_id (unique), opinion_id, cited_by_count, citing_opinions (JSONB), derived_method, as_of, created_at, updated_at`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_citation_treatment_model.py`:

```python
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.citation_treatment import CitationTreatment

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_citation_treatment_roundtrip(db_session: AsyncSession) -> None:
    row = CitationTreatment(
        cluster_id=2812209,
        opinion_id=2812209,
        cited_by_count=412,
        citing_opinions=[
            {"cluster_id": 1001, "opinion_id": 9001, "case_name": "X v. Y", "court": "ca9", "date_filed": "2021-01-01"}
        ],
        derived_method="citation_graph",
    )
    db_session.add(row)
    await db_session.flush()
    got = (
        await db_session.execute(select(CitationTreatment).where(CitationTreatment.cluster_id == 2812209))
    ).scalar_one()
    assert got.cited_by_count == 412
    assert got.citing_opinions[0]["case_name"] == "X v. Y"
    assert got.derived_method == "citation_graph"
    assert got.as_of is not None  # server_default now()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/test_citation_treatment_model.py -v`
Expected: FAIL — `ModuleNotFoundError: app.models.citation_treatment`.

- [ ] **Step 3: Create the model**

`api/app/models/citation_treatment.py` (mirror `message_caselaw_citation.py` conventions):

```python
"""citation_treatment — derived validity/treatment signal per cited case (WS-G).

One row per cited case (``cluster_id``), holding the citation-graph signal:
the total cited-by count + a capped list of recent citing-opinion *references*
(ids + case_name + court + date — never opinion text, P3). ADR 0019 D2/D7.
PR1 (this) is graph-only (``derived_method='citation_graph'``); PR2 extends the
row with judge-classified treatment. Reference-only → joins the P3 tripwire.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CitationTreatment(Base):
    __tablename__ = "citation_treatment"
    __table_args__ = (
        UniqueConstraint("cluster_id", name="uq_citation_treatment_cluster_id"),
        CheckConstraint("cited_by_count >= 0", name="chk_citation_treatment_count_nonneg"),
        CheckConstraint(
            "derived_method IN ('citation_graph')",
            name="chk_citation_treatment_method_values",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    cluster_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    opinion_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cited_by_count: Mapped[int] = mapped_column(Integer, nullable=False)
    citing_opinions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    derived_method: Mapped[str] = mapped_column(Text, nullable=False)
    as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

Export it in `api/app/models/__init__.py` (add `from app.models.citation_treatment import CitationTreatment` and add `"CitationTreatment"` to `__all__` — keep both alphabetically sorted to satisfy ruff I001/RUF022).

- [ ] **Step 4: Create migration 0061**

`api/alembic/versions/0061_citation_treatment.py` (mirror 0060's header; this one is `create_table`):

```python
"""create citation_treatment (WS-G PR1 citation-graph signal)

Revision ID: 0061
Revises: 0060
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "citation_treatment",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("cluster_id", sa.BigInteger(), nullable=False),
        sa.Column("opinion_id", sa.BigInteger(), nullable=True),
        sa.Column("cited_by_count", sa.Integer(), nullable=False),
        sa.Column("citing_opinions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("derived_method", sa.Text(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_citation_treatment"),
        sa.UniqueConstraint("cluster_id", name="uq_citation_treatment_cluster_id"),
        sa.CheckConstraint("cited_by_count >= 0", name="chk_citation_treatment_count_nonneg"),
        sa.CheckConstraint("derived_method IN ('citation_graph')", name="chk_citation_treatment_method_values"),
    )
    op.create_index("ix_citation_treatment_cluster_id", "citation_treatment", ["cluster_id"])


def downgrade() -> None:
    op.drop_index("ix_citation_treatment_cluster_id", table_name="citation_treatment")
    op.drop_table("citation_treatment")
```

- [ ] **Step 5: Add to the P3 tripwire**

In `api/tests/test_transparency_invariants.py`: add `from app.models.citation_treatment import CitationTreatment` (with the other model imports) and add `CitationTreatment,` to the `_AUDIT_MODELS` tuple. *(All `citation_treatment` column names are tripwire-safe: none match `_DENIED_EXACT`/`_DENIED_SUFFIX`/`_DENIED_PREFIX` — `citing_opinions` is not on any list.)*

- [ ] **Step 6: Run model + migration + tripwire**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/test_citation_treatment_model.py tests/test_transparency_invariants.py -v`
Expected: PASS (conftest auto-migrates 0061; tripwire green with the new model).

- [ ] **Step 7: Lint + commit**

```bash
cd api && ruff format app/models/citation_treatment.py app/models/__init__.py alembic/versions/0061_citation_treatment.py tests/test_citation_treatment_model.py tests/test_transparency_invariants.py && ruff check app/models/citation_treatment.py app/models/__init__.py alembic/versions/0061_citation_treatment.py tests/test_citation_treatment_model.py tests/test_transparency_invariants.py
git add api/app/models/citation_treatment.py api/app/models/__init__.py api/alembic/versions/0061_citation_treatment.py api/tests/test_citation_treatment_model.py api/tests/test_transparency_invariants.py
git commit -s -m "feat(api): citation_treatment table + migration 0061 (WS-G PR1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `research.service` wrapper + `derive_treatment_for_message` service

**Files:**
- Modify: `api/app/research/service.py` (add `get_citing_opinions` wrapper)
- Create: `api/app/citation/treatment.py`
- Test: `api/tests/citation/test_treatment_derivation.py` (create)

**Interfaces:**
- Consumes: `app.research.service.get_citing_opinions` (Task 3a), `MessageCaselawCitation` (opinion_id/cluster_id), `CitationTreatment` (Task 2), `CitationLedgerEntry` (`treatment_id`, `message_caselaw_citation_id`).
- Produces:
  ```python
  TREATMENT_TTL_DAYS = 30
  async def derive_treatment_for_message(
      db, *, message_id: uuid.UUID, now: datetime,
      ttl_days: int = TREATMENT_TTL_DAYS,
      fetch_citing: _FetchCiting = _default_fetch_citing,
  ) -> int   # number of ledger entries linked
  ```
  where `_FetchCiting = Callable[[int], Awaitable[dict[str, Any]]]` taking an opinion_id, returning `{"cited_by_count": int, "citing": [...]}`.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/citation/test_treatment_derivation.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.treatment import TREATMENT_TTL_DAYS, derive_treatment_for_message
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 26, tzinfo=timezone.utc)


def _citing(n: int) -> dict:
    return {"cited_by_count": 412, "citing": [
        {"cluster_id": 1000 + i, "opinion_id": 9000 + i, "case_name": f"C{i}", "court": "ca9", "date_filed": "2021-01-01"}
        for i in range(n)
    ]}


@pytest.fixture
async def seeded(db_session: AsyncSession):
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(user); await db_session.flush()
    chat = Chat(owner_id=user.id, title="t"); db_session.add(chat); await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x")
    db_session.add(msg); await db_session.flush()
    cc = MessageCaselawCitation(
        message_id=msg.id, opinion_id=2812209, cluster_id=2812209,
        source_offset_start=0, source_offset_end=5, source_text="quote",
        verified=True, verification_method="exact_match",
    )
    db_session.add(cc); await db_session.flush()
    entry = CitationLedgerEntry(
        chat_id=chat.id, message_id=msg.id, source_kind="caselaw",
        message_caselaw_citation_id=cc.id, verification_status="exact_match",
    )
    db_session.add(entry); await db_session.flush()
    return msg.id, chat.id, cc, entry


@pytest.mark.asyncio
async def test_derives_fetches_and_links(db_session, seeded):
    message_id, _chat, _cc, entry = seeded
    calls = []
    async def fake_fetch(opinion_id: int) -> dict:
        calls.append(opinion_id); return _citing(32)
    n = await derive_treatment_for_message(db_session, message_id=message_id, now=_NOW, fetch_citing=fake_fetch)
    assert n == 1
    assert calls == [2812209]
    row = (await db_session.execute(select(CitationTreatment).where(CitationTreatment.cluster_id == 2812209))).scalar_one()
    assert row.cited_by_count == 412
    assert len(row.citing_opinions) == 32  # service stores what the op returns (op already capped at 30; service does not re-cap)
    assert row.derived_method == "citation_graph"
    await db_session.refresh(entry)
    assert entry.treatment_id == row.id


@pytest.mark.asyncio
async def test_reuses_fresh_cache_without_fetch(db_session, seeded):
    message_id, _chat, _cc, entry = seeded
    db_session.add(CitationTreatment(
        cluster_id=2812209, opinion_id=2812209, cited_by_count=10,
        citing_opinions=[], derived_method="citation_graph", as_of=_NOW - timedelta(days=5),
    ))
    await db_session.flush()
    calls = []
    async def fake_fetch(opinion_id: int) -> dict:
        calls.append(opinion_id); return _citing(1)
    n = await derive_treatment_for_message(db_session, message_id=message_id, now=_NOW, fetch_citing=fake_fetch)
    assert n == 1
    assert calls == []  # fresh cache reused, no fetch
    await db_session.refresh(entry)
    assert entry.treatment_id is not None


@pytest.mark.asyncio
async def test_refetches_when_stale(db_session, seeded):
    message_id, *_ = seeded
    db_session.add(CitationTreatment(
        cluster_id=2812209, opinion_id=2812209, cited_by_count=10,
        citing_opinions=[], derived_method="citation_graph",
        as_of=_NOW - timedelta(days=TREATMENT_TTL_DAYS + 1),
    ))
    await db_session.flush()
    calls = []
    async def fake_fetch(opinion_id: int) -> dict:
        calls.append(opinion_id); return _citing(3)
    await derive_treatment_for_message(db_session, message_id=message_id, now=_NOW, fetch_citing=fake_fetch)
    assert calls == [2812209]  # stale → refetch
    row = (await db_session.execute(select(CitationTreatment).where(CitationTreatment.cluster_id == 2812209))).scalar_one()
    assert row.cited_by_count == 412  # upserted


@pytest.mark.asyncio
async def test_per_case_fetch_error_is_non_fatal(db_session, seeded):
    message_id, *_ = seeded
    async def boom(opinion_id: int) -> dict:
        raise RuntimeError("upstream down")
    n = await derive_treatment_for_message(db_session, message_id=message_id, now=_NOW, fetch_citing=boom)
    assert n == 0  # nothing linked, but no raise
    rows = (await db_session.execute(select(CitationTreatment))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_no_caselaw_citations_is_noop(db_session):
    # a message with no caselaw citations
    user = User(email=f"t-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(user); await db_session.flush()
    chat = Chat(owner_id=user.id, title="t"); db_session.add(chat); await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x"); db_session.add(msg); await db_session.flush()
    called = []
    async def fake_fetch(opinion_id: int) -> dict:
        called.append(opinion_id); return _citing(1)
    n = await derive_treatment_for_message(db_session, message_id=msg.id, now=_NOW, fetch_citing=fake_fetch)
    assert n == 0
    assert called == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/citation/test_treatment_derivation.py -v`
Expected: FAIL — `ModuleNotFoundError: app.citation.treatment`.

- [ ] **Step 3a: Add the `research.service` wrapper**

In `api/app/research/service.py`, add (mirrors `search_case_law`):

```python
async def get_citing_opinions(opinion_id: int, *, request_id: str | None = None) -> dict[str, Any]:
    provider = await _resolve_provider(request_id=request_id)
    result = await get_gateway_client().call_tool(
        provider, "get_citing_opinions", {"opinion_id": opinion_id}, request_id=request_id
    )
    return result["payload"]
```

- [ ] **Step 3b: Implement the derivation service**

Create `api/app/citation/treatment.py`:

```python
"""Derive the citation-graph treatment signal for a turn's cited cases (WS-G PR1).

Graph-only: for each case a turn cited, reuse a fresh ``citation_treatment`` row
or fetch the citing graph via the gateway and upsert one, then link the turn's
caselaw ledger entries to it. No LLM-judge (that is PR2). Per-case non-fatal
(conservative posture). ADR 0019 D2.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.message_caselaw_citation import MessageCaselawCitation

log = logging.getLogger(__name__)

TREATMENT_TTL_DAYS = 30

_FetchCiting = Callable[[int], Awaitable[dict[str, Any]]]


async def _default_fetch_citing(opinion_id: int) -> dict[str, Any]:
    from app.research import service as research_service

    return await research_service.get_citing_opinions(opinion_id)


async def derive_treatment_for_message(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    now: datetime,
    ttl_days: int = TREATMENT_TTL_DAYS,
    fetch_citing: _FetchCiting = _default_fetch_citing,
) -> int:
    """Derive/refresh graph treatment for each case this turn cited; link entries.

    Returns the number of caselaw ledger entries linked to a treatment row.
    Never raises on a per-case failure (logged and skipped).
    """
    citations = (
        (
            await db.execute(
                select(MessageCaselawCitation).where(
                    MessageCaselawCitation.message_id == message_id
                )
            )
        )
        .scalars()
        .all()
    )
    if not citations:
        return 0

    # One derivation per distinct cited cluster; remember a representative opinion_id.
    by_cluster: dict[int, int] = {}
    for c in citations:
        by_cluster.setdefault(c.cluster_id, c.opinion_id)

    cluster_to_treatment: dict[int, uuid.UUID] = {}
    stale_before = now - timedelta(days=ttl_days)
    for cluster_id, opinion_id in by_cluster.items():
        try:
            existing = (
                await db.execute(
                    select(CitationTreatment).where(CitationTreatment.cluster_id == cluster_id)
                )
            ).scalar_one_or_none()
            if existing is not None and existing.as_of >= stale_before:
                cluster_to_treatment[cluster_id] = existing.id
                continue
            payload = await fetch_citing(opinion_id)
            if existing is None:
                row = CitationTreatment(
                    cluster_id=cluster_id,
                    opinion_id=opinion_id,
                    cited_by_count=int(payload.get("cited_by_count") or 0),
                    citing_opinions=list(payload.get("citing") or []),
                    derived_method="citation_graph",
                    as_of=now,
                )
                db.add(row)
                await db.flush()
                cluster_to_treatment[cluster_id] = row.id
            else:
                existing.cited_by_count = int(payload.get("cited_by_count") or 0)
                existing.citing_opinions = list(payload.get("citing") or [])
                existing.derived_method = "citation_graph"
                existing.opinion_id = opinion_id
                existing.as_of = now
                await db.flush()
                cluster_to_treatment[cluster_id] = existing.id
        except Exception as exc:  # per-case non-fatal (conservative posture)
            log.warning("treatment derivation failed for cluster %s: %r", cluster_id, exc)

    if not cluster_to_treatment:
        return 0

    # Link this turn's caselaw ledger entries to their cluster's treatment row.
    cc_id_to_cluster = {c.id: c.cluster_id for c in citations}
    entries = (
        (
            await db.execute(
                select(CitationLedgerEntry).where(
                    CitationLedgerEntry.message_id == message_id,
                    CitationLedgerEntry.source_kind == "caselaw",
                )
            )
        )
        .scalars()
        .all()
    )
    linked = 0
    for e in entries:
        cluster_id = cc_id_to_cluster.get(e.message_caselaw_citation_id)
        treatment_id = cluster_to_treatment.get(cluster_id) if cluster_id is not None else None
        if treatment_id is not None:
            e.treatment_id = treatment_id
            linked += 1
    if linked:
        await db.flush()
    return linked
```

*(Confirm `CitationLedgerEntry.message_caselaw_citation_id` is the column name during implementation — it is the caselaw FK from P1-A2.)*

- [ ] **Step 4: Run to verify pass**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/citation/test_treatment_derivation.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint + commit**

```bash
cd api && ruff format app/research/service.py app/citation/treatment.py tests/citation/test_treatment_derivation.py && ruff check app/research/service.py app/citation/treatment.py tests/citation/test_treatment_derivation.py
git add api/app/research/service.py api/app/citation/treatment.py api/tests/citation/test_treatment_derivation.py
git commit -s -m "feat(api): citation-graph treatment derivation service (WS-G PR1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Async job + enqueue at the two turn-finalize sites

**Files:**
- Create: `api/app/workers/treatment_worker.py` (the job)
- Modify: `api/app/workers/queue.py` (an `enqueue_treatment_derivation_job` helper), `api/app/workers/document_pipeline.py` (register the job in the ingest `WorkerSettings.functions`), `api/app/api/chats.py` (enqueue at both finalize sites)
- Test: `api/tests/integration/test_treatment_job.py` (create)

**Interfaces:**
- Consumes: `derive_treatment_for_message` (Task 3); the existing `_get_pool()` enqueue pattern in `queue.py`; the `db_session`/session-factory pattern an existing ingest job uses.
- Produces: `treatment_derivation_job(ctx, message_id_str) -> dict`; `enqueue_treatment_derivation_job(message_id: uuid.UUID) -> bool`.

- [ ] **Step 1: Write the failing test** (exercise the job body against a real DB; mock the citing fetch)

Create `api/tests/integration/test_treatment_job.py`:

```python
from __future__ import annotations

import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_run_treatment_derivation_writes_row_and_links(db_session: AsyncSession, monkeypatch):
    # Seed a turn with a caselaw citation + ledger entry (as in Task 3's fixture).
    user = User(email=f"j-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(user); await db_session.flush()
    chat = Chat(owner_id=user.id, title="j"); db_session.add(chat); await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x"); db_session.add(msg); await db_session.flush()
    cc = MessageCaselawCitation(message_id=msg.id, opinion_id=2812209, cluster_id=2812209,
        source_offset_start=0, source_offset_end=5, source_text="q", verified=True, verification_method="exact_match")
    db_session.add(cc); await db_session.flush()
    entry = CitationLedgerEntry(chat_id=chat.id, message_id=msg.id, source_kind="caselaw",
        message_caselaw_citation_id=cc.id, verification_status="exact_match")
    db_session.add(entry); await db_session.flush()

    # The job's _run helper takes an injected session + fetch so we can test it without Redis/arq.
    from app.workers.treatment_worker import run_treatment_derivation

    async def fake_fetch(opinion_id: int) -> dict:
        return {"cited_by_count": 7, "citing": [{"cluster_id": 1, "opinion_id": 2, "case_name": "A", "court": "ca9", "date_filed": "2022-01-01"}]}

    linked = await run_treatment_derivation(db_session, message_id=msg.id, fetch_citing=fake_fetch)
    assert linked == 1
    row = (await db_session.execute(select(CitationTreatment).where(CitationTreatment.cluster_id == 2812209))).scalar_one()
    assert row.cited_by_count == 7
    await db_session.refresh(entry)
    assert entry.treatment_id == row.id
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/integration/test_treatment_job.py -v`
Expected: FAIL — `ModuleNotFoundError: app.workers.treatment_worker`.

- [ ] **Step 3: Implement the worker job**

Create `api/app/workers/treatment_worker.py`. Read an existing ingest job (`api/app/workers/document_pipeline.py` or `easy_playbook_worker.py`) for the exact session-factory + `now`/UTC + ctx conventions, then:

```python
"""arq job — derive citation-graph treatment for an assistant turn (WS-G PR1)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.treatment import _FetchCiting, _default_fetch_citing, derive_treatment_for_message

log = logging.getLogger(__name__)


async def run_treatment_derivation(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    fetch_citing: _FetchCiting = _default_fetch_citing,
) -> int:
    """Session-injected core (testable without arq/Redis)."""
    linked = await derive_treatment_for_message(
        db, message_id=message_id, now=datetime.now(timezone.utc), fetch_citing=fetch_citing
    )
    await db.commit()
    return linked


async def treatment_derivation_job(ctx: dict[str, Any], message_id_str: str) -> dict[str, Any]:
    """arq entrypoint. Opens a session, runs derivation, commits."""
    message_id = uuid.UUID(message_id_str)
    # Use the same async-session factory the other ingest jobs use (read one for the exact import).
    from app.db.session import async_session_factory  # confirm the actual factory path

    async with async_session_factory() as db:
        try:
            linked = await run_treatment_derivation(db, message_id=message_id)
        except Exception as exc:  # never crash the worker on one turn
            log.warning("treatment_derivation_job failed for %s: %r", message_id, exc)
            return {"message_id": message_id_str, "linked": 0, "ok": False}
    return {"message_id": message_id_str, "linked": linked, "ok": True}
```

*(Pin the real `async_session_factory`/session-context import from a sibling ingest job during implementation — do not invent it.)*

Add the enqueue helper to `api/app/workers/queue.py` (mirror `enqueue_easy_playbook_generation_job`, but use the **ingest** `_get_pool()`):

```python
async def enqueue_treatment_derivation_job(message_id: uuid.UUID) -> bool:
    try:
        pool = await _get_pool()
        await pool.enqueue_job("treatment_derivation_job", str(message_id))
        return True
    except Exception as exc:
        logger.warning("failed to enqueue treatment_derivation_job for %s: %r", message_id, exc)
        return False
```

Register the job: add `treatment_derivation_job` to the ingest `WorkerSettings.functions` in `api/app/workers/document_pipeline.py` (import it at top).

- [ ] **Step 4: Enqueue at both finalize sites**

In `api/app/api/chats.py`, immediately **after** the `await _audit_message_sent(...)` call at **both** finalize sites (~line 2941–2953 and ~3533–3545 — locate by the `_audit_message_sent` call), add a best-effort enqueue (import `enqueue_treatment_derivation_job` at top):

```python
try:
    await enqueue_treatment_derivation_job(assistant_message_id)
except Exception as treatment_exc:  # never block the turn response
    log.warning("treatment derivation enqueue failed: %r", treatment_exc)
```

*(The enqueue helper already swallows its own errors; the extra guard is defense-in-depth and matches the surrounding best-effort posture. Confirm the message-id variable name at each site — `assistant_message_id`.)*

- [ ] **Step 5: Run the job test + a focused chats import smoke**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/integration/test_treatment_job.py -v`
Expected: PASS. Then confirm chats.py still imports/collects: `.venv/bin/python -m pytest tests/test_endpoints.py -q` (collection must not break).

- [ ] **Step 6: Lint + commit**

```bash
cd api && ruff format app/workers/treatment_worker.py app/workers/queue.py app/workers/document_pipeline.py app/api/chats.py tests/integration/test_treatment_job.py && ruff check app/workers/treatment_worker.py app/workers/queue.py app/workers/document_pipeline.py app/api/chats.py tests/integration/test_treatment_job.py
git add api/app/workers/treatment_worker.py api/app/workers/queue.py api/app/workers/document_pipeline.py api/app/api/chats.py api/tests/integration/test_treatment_job.py
git commit -s -m "feat(api): async treatment-derivation job enqueued at turn finalize (WS-G PR1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Expose the treatment signal on the `/ledger` read

**Files:**
- Modify: `api/app/citation/ledger.py` (`resolve_ledger_entries` — resolve `treatment_id` → a `treatment` object)
- Test: `api/tests/integration/test_ledger_treatment_exposure.py` (create)

**Interfaces:**
- Consumes: `CitationTreatment` (Task 2); the existing `resolve_ledger_entries` batch-load + per-entry dict shape (`treatment_id` already present).
- Produces: each resolved entry gains `"treatment": {...} | None`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/integration/test_ledger_treatment_exposure.py`:

```python
from __future__ import annotations

import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.ledger import resolve_ledger_entries
from app.models.chat import Chat, Message
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.citation_treatment import CitationTreatment
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_ledger_entry_carries_resolved_treatment(db_session: AsyncSession):
    user = User(email=f"l-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(user); await db_session.flush()
    chat = Chat(owner_id=user.id, title="l"); db_session.add(chat); await db_session.flush()
    msg = Message(chat_id=chat.id, role="assistant", kind="ai", content="x"); db_session.add(msg); await db_session.flush()
    cc = MessageCaselawCitation(message_id=msg.id, opinion_id=2812209, cluster_id=2812209,
        source_offset_start=0, source_offset_end=5, source_text="q", verified=True, verification_method="exact_match")
    db_session.add(cc); await db_session.flush()
    treatment = CitationTreatment(cluster_id=2812209, opinion_id=2812209, cited_by_count=412,
        citing_opinions=[{"cluster_id": 1, "opinion_id": 2, "case_name": "A", "court": "ca9", "date_filed": "2021-01-01"}],
        derived_method="citation_graph")
    db_session.add(treatment); await db_session.flush()
    linked = CitationLedgerEntry(chat_id=chat.id, message_id=msg.id, source_kind="caselaw",
        message_caselaw_citation_id=cc.id, verification_status="exact_match", treatment_id=treatment.id)
    unlinked = CitationLedgerEntry(chat_id=chat.id, message_id=msg.id, source_kind="caselaw",
        message_caselaw_citation_id=cc.id, verification_status="exact_match")
    db_session.add_all([linked, unlinked]); await db_session.flush()

    entries = await resolve_ledger_entries(db_session, chat_id=chat.id, message_id=msg.id)
    by_treatment = {bool(e.get("treatment")): e for e in entries}
    assert by_treatment[True]["treatment"]["cited_by_count"] == 412
    assert by_treatment[True]["treatment"]["derived_method"] == "citation_graph"
    assert by_treatment[True]["treatment"]["citing"][0]["case_name"] == "A"
    assert by_treatment[False]["treatment"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/integration/test_ledger_treatment_exposure.py -v`
Expected: FAIL — entries carry no `treatment` key (KeyError / None).

- [ ] **Step 3: Resolve treatment in `resolve_ledger_entries`**

In `api/app/citation/ledger.py`, in `resolve_ledger_entries`: after the entry rows are loaded and before building the per-entry dicts, **batch-load** the referenced treatments:

```python
treatment_ids = {e.treatment_id for e in entries if e.treatment_id is not None}
treatments: dict[uuid.UUID, CitationTreatment] = {}
if treatment_ids:
    treatments = {
        t.id: t
        for t in (
            await db.execute(select(CitationTreatment).where(CitationTreatment.id.in_(treatment_ids)))
        ).scalars().all()
    }
```

(Add `from app.models.citation_treatment import CitationTreatment` at top.) Then in the per-entry dict, add a `treatment` key:

```python
"treatment": (
    {
        "cited_by_count": treatments[e.treatment_id].cited_by_count,
        "as_of": treatments[e.treatment_id].as_of.isoformat(),
        "derived_method": treatments[e.treatment_id].derived_method,
        "citing": treatments[e.treatment_id].citing_opinions,
    }
    if e.treatment_id is not None and e.treatment_id in treatments
    else None
),
```

- [ ] **Step 4: Run to verify pass**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/integration/test_ledger_treatment_exposure.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd api && ruff format app/citation/ledger.py tests/integration/test_ledger_treatment_exposure.py && ruff check app/citation/ledger.py tests/integration/test_ledger_treatment_exposure.py
git add api/app/citation/ledger.py api/tests/integration/test_ledger_treatment_exposure.py
git commit -s -m "feat(api): expose citation-graph treatment on the ledger read (WS-G PR1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Full gates

**Files:** none (verification + any lint/collision fixes surfaced).

- [ ] **Step 1: Full api suite** — `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest -q`. Expected: PASS, no collection errors. (No new route → `test_endpoints.py`/`test_openapi.py` path counts unchanged.)
- [ ] **Step 2: Gateway suite** — `cd gateway && .venv/bin/python -m pytest -q && mypy app`. Expected: PASS; mypy `Success`.
- [ ] **Step 3:** If either gate surfaces a lint/collision issue, fix in the owning task's files and re-run. Commit any fix with a clear message.

---

## Final review (after Task 6)

- [ ] **Opus whole-branch review** vs `main`. Focus: treatment never affects the fiduciary gate (gate independence); the derivation is genuinely non-fatal per case (one bad case never sinks the turn or the others); the `cited_by_count` vs capped-list distinction; the enqueue is best-effort at BOTH finalize sites; P3 tripwire covers `citation_treatment`; no LLM call sneaks in; gateway `mypy --strict` holds.
- [ ] **Push both remotes** (`origin` + `tucuxi`).
- [ ] **Open the PR** (origin). **Security-gated — do NOT self-merge.** Kevin/security merges; then mirror `origin/main → tucuxi main` and confirm `origin == tucuxi`.

## Self-review against the spec

- **Spec coverage:** Component 1 (gateway op) → Task 1; Component 2 (model+migration+P3) → Task 2; Component 3 (derivation service + research wrapper) → Task 3; Component 4 (async job + enqueue) → Task 4; Component 5 (read exposure) → Task 5; "no judge / additive / gate-independent" → Global Constraints + Tasks 3–5 tests; P3 tripwire → Task 2; DE-363 (lazy fallback) correctly **out of scope** (filed in the spec).
- **Spec deviation (recorded):** ordering is **most-recent-first** (`dateFiled desc`), not "highest-court-then-recent" — CourtListener's Search API has no server-side court-rank sort; court-rank re-ranking of the materialized subset is PR2. The capped list still pre-stages PR2's subset.
- **Placeholder scan:** the "confirm during implementation" notes (the CL test module's helpers, the `async_session_factory` import, the `message_caselaw_citation_id` column name, the exact finalize-site line numbers) are real-anchor confirmations, not vague placeholders — each names exactly what to verify and where.
- **Type consistency:** `derive_treatment_for_message(db, *, message_id, now, ttl_days, fetch_citing) -> int`, `_FetchCiting = Callable[[int], Awaitable[dict]]`, `run_treatment_derivation(db, *, message_id, fetch_citing) -> int`, `treatment_derivation_job(ctx, message_id_str) -> dict`, `enqueue_treatment_derivation_job(message_id) -> bool`, payload `{cited_by_count, citing[]}`, entry `treatment` `{cited_by_count, as_of, derived_method, citing}` — consistent across Tasks 1–5.
