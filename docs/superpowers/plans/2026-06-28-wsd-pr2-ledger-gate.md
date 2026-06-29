# WS-D PR2 — Fiduciary Ledger + Gate for Matter Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make an autonomous matter session produce the same citation-ledger + fiduciary-gate rows a chat turn does, by manufacturing a hidden session-owned chat/message and routing the session's structured citations through the existing character-fidelity verifier → `assemble_ledger_entries` → `compute_and_record_gate`.

**Architecture:** Reuse, do not fork (ADR 0016 P6 / 0020 D6). The synthesis output gains structured per-finding citations (`{quote, source}`); the analysis loop accumulates a P3-safe evidence registry; at delivery a new `ledger_bridge` module manufactures a hidden `Chat`+`Message`, builds `MessageCitation`/`MessageCaselawCitation` rows from the structured citations via the existing `verify()` primitive, then calls the unchanged `assemble_ledger_entries` + `compute_and_record_gate`, and embeds the gate verdict in `session.result`. A read endpoint exposes the session's ledger.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), LangGraph, alembic, pytest, ruff, mypy. Subsystems: `api/app/autonomous/`, `api/app/citation/`, `api/app/api/chats.py`.

## Global Constraints

- **Security-gated** (`api/app/autonomous/**`, `api/app/citation/**`, `api/app/api/chats.py`, migration): security/maintainer merges; mirror `origin/main → tucuxi` after. Claude does NOT self-merge.
- **Reuse, do not fork (load-bearing):** write the SAME `message_citations`/`message_caselaw_citations`/`citation_ledger_entry`/`work_product_fiduciary_gate` rows the chat path writes; reuse `verify()` (`api/app/citation/verification.py:545`), `assemble_ledger_entries` (`api/app/citation/ledger.py:32`), `compute_and_record_gate` (`api/app/citation/gate.py:33`) UNCHANGED. No parallel ledger/gate.
- **Strictly additive / backward-compat (load-bearing):** only matter sessions (a parsed work product with citations) run the cascade. Query-less / non-matter sessions are byte-identical — no manufactured chat, no ledger/gate, `session.result` unchanged.
- **Best-effort, never blocks delivery (load-bearing):** the cascade is wrapped (try/except → log `event="autonomous_ledger_bridge_failed"`); a failure leaves the session delivered with an honest receipt sans `fiduciary_gate`, never crash-loops the worker (DE-325 discipline).
- **P3 (ADR 0016 / 0019 D7):** the planner keeps seeing only compact observations; audit / `analysis_plan_trace` / ledger rows store offsets/labels/status/ids — never raw payloads. The evidence registry is loop-local + synthesis context only; it is NOT written to `analysis_plan_trace`/audit.
- **Hidden chat invisible:** a chat with `autonomous_session_id IS NOT NULL` never appears in `list_chats`/`search_chats`; reachable only by direct id.
- **Honest labeling (ADR 0018 D3):** unverifiable quotes are dropped (KB) / FAIL-row (caselaw) exactly as the chat path — never fabricated to inflate the gate.
- **No migration host-run against the dev DB** (port 15432). Tests use host venv `api/.venv` + throwaway pgvector on `:55432`, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test` (conftest auto-migrates). Mocked gateway → no `-m provider`.
- **Run the api suite SOLO** (DE-368: concurrent pytest against the shared `lqai_test` DB produces spurious research-test failures).
- **CI gate (repo root):** `ruff check api scripts` + `ruff format --check api scripts` + whole-app `mypy app` + both full suites. Next migration = `0063`. Next DE = DE-369.
- Commits: `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## File structure

| File | Change | Task |
|---|---|---|
| `api/alembic/versions/0063_chat_autonomous_session_id.py` | NEW migration | 1 |
| `api/app/models/chat.py` | `Chat.autonomous_session_id` column | 1 |
| `api/app/api/chats.py` | filter session chats out of `list_chats` + `search_chats` | 1 |
| `docs/db-schema.md` | document `chats.autonomous_session_id` | 1 |
| `api/app/citation/extraction.py` | promote `_locate_in_chunk` → `locate_in_chunk` | 2 |
| `api/app/autonomous/planner.py` | `summarize_observation` caselaw includes `cluster_id`; `EvidenceItem` | 3 |
| `api/app/autonomous/nodes.py` | loop evidence registry; thread to synthesis + delivery | 3, 6 |
| `api/app/autonomous/prompts.py` | numbered-source block + citation instruction in `assemble_synthesis_messages` | 4 |
| `api/app/autonomous/structured_output.py` | tolerant parse of finding `citations` | 4 |
| `api/app/autonomous/ledger_bridge.py` | NEW — KB + caselaw structured citation builders + `build_session_ledger` | 5, 6, 7 |
| `api/app/api/autonomous.py` (or the sessions router) | `GET /sessions/{id}/ledger` | 8 |

---

### Task 1: Migration 0063 + hidden session-owned chat plumbing

**Files:**
- Create: `api/alembic/versions/0063_chat_autonomous_session_id.py`
- Modify: `api/app/models/chat.py` (add `Chat.autonomous_session_id`)
- Modify: `api/app/api/chats.py` (`list_chats` ~743, `search_chats` ~655/681)
- Modify: `docs/db-schema.md` (chats table)
- Test: `api/tests/test_chats_endpoints.py` (add a hidden-chat-excluded test) and a migration sanity assert in `api/tests/autonomous/test_session_ledger.py` (new file, reused by later tasks)

**Interfaces:**
- Produces: `Chat.autonomous_session_id: Mapped[uuid.UUID | None]` (FK `autonomous_sessions.id`, `ON DELETE SET NULL`); `list_chats`/`search_chats` exclude rows where it is non-null.

- [ ] **Step 1: Write the failing test** — append to `api/tests/test_chats_endpoints.py`:

```python
@pytest.mark.integration
async def test_session_owned_chat_excluded_from_list(
    db_session: AsyncSession, client: AsyncClient, owner_user: User
) -> None:
    from app.models.autonomous import AutonomousSession
    from app.models.chat import Chat

    sess = AutonomousSession(user_id=owner_user.id, trigger_kind="manual", params={})
    db_session.add(sess)
    await db_session.flush()
    visible = Chat(owner_id=owner_user.id, title="Visible")
    hidden = Chat(owner_id=owner_user.id, title="Session", autonomous_session_id=sess.id)
    db_session.add_all([visible, hidden])
    await db_session.commit()

    resp = await client.get("/api/v1/chats", headers={"Authorization": _bearer_for(owner_user)})
    assert resp.status_code == 200
    titles = {c["title"] for c in resp.json()}
    assert "Visible" in titles
    assert "Session" not in titles  # session-owned chat is hidden from the list
```

- [ ] **Step 2: Run — expect failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/test_chats_endpoints.py::test_session_owned_chat_excluded_from_list -v`
Expected: FAIL — `Chat` has no `autonomous_session_id` (and the column doesn't exist).

- [ ] **Step 3: Write the migration** (`api/alembic/versions/0063_chat_autonomous_session_id.py`) — template `0056_chat_sticky_skills.py`:

```python
"""chats.autonomous_session_id — hidden session-owned chats (WS-D PR2).

Revision ID: 0063
Revises: 0062
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column("autonomous_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_chats_autonomous_session_id",
        "chats",
        "autonomous_sessions",
        ["autonomous_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_chats_autonomous_session_id",
        "chats",
        ["autonomous_session_id"],
        postgresql_where=sa.text("autonomous_session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_chats_autonomous_session_id", table_name="chats")
    op.drop_constraint("fk_chats_autonomous_session_id", "chats", type_="foreignkey")
    op.drop_column("chats", "autonomous_session_id")
```

- [ ] **Step 4: Add the ORM column** in `api/app/models/chat.py` (in the `Chat` class, after `project_id` ~line 85):

```python
    autonomous_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("autonomous_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=False,  # partial index created in migration 0063
    )
```

(Confirm `ForeignKey` and `UUID` are already imported in chat.py; they are used by `owner_id`/`project_id`.)

- [ ] **Step 5: Filter session chats out of the list + search.** In `api/app/api/chats.py` `list_chats` (~743), change the base statement:

```python
    stmt = select(Chat).where(
        Chat.owner_id == user.id,
        Chat.autonomous_session_id.is_(None),
    )
```

In `search_chats` add `Chat.autonomous_session_id.is_(None)` to BOTH subquery WHERE clauses (~655 and ~681), pattern-matching the existing `Chat.archived_at.is_(None)` filter there.

- [ ] **Step 6: Document the column.** In `docs/db-schema.md`, in the `chats` table section, add a row: `autonomous_session_id | uuid | nullable, FK→autonomous_sessions.id ON DELETE SET NULL | session-owned chat marker (WS-D PR2); excluded from chat list`.

- [ ] **Step 7: Run — expect pass + chats regression**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/test_chats_endpoints.py -v`
Expected: PASS (new test + no chats regressions).

- [ ] **Step 8: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/alembic/versions/0063_chat_autonomous_session_id.py api/app/models/chat.py api/app/api/chats.py docs/db-schema.md api/tests/test_chats_endpoints.py
git commit -s -m "feat(chats): hidden session-owned chat marker — migration 0063 (WS-D PR2)"
```

---

### Task 2: Promote `_locate_in_chunk` → public `locate_in_chunk`

**Files:**
- Modify: `api/app/citation/extraction.py:128` (rename + keep a private alias if any internal caller uses it)
- Test: `api/tests/citation/test_extraction.py` (add a direct call test)

**Interfaces:**
- Produces: `locate_in_chunk(quote: str, chunk_content: str) -> tuple[int, int] | None` (public; same body, same `_ALIGNMENT_THRESHOLD`). Used by the KB citation builder (Task 5).

- [ ] **Step 1: Write the failing test** — append to `api/tests/citation/test_extraction.py`:

```python
def test_locate_in_chunk_public_exact_and_miss():
    from app.citation.extraction import locate_in_chunk

    content = "The Receiving Party shall hold Confidential Information in confidence."
    span = locate_in_chunk("hold Confidential Information", content)
    assert span is not None
    start, end = span
    assert content[start:end] == "hold Confidential Information"
    assert locate_in_chunk("text that is absent", content) is None
```

- [ ] **Step 2: Run — expect failure**

Run: `cd api && .venv/bin/python -m pytest tests/citation/test_extraction.py::test_locate_in_chunk_public_exact_and_miss -v`
Expected: FAIL — `cannot import name 'locate_in_chunk'`.

- [ ] **Step 3: Rename.** In `api/app/citation/extraction.py`, rename `def _locate_in_chunk(` to `def locate_in_chunk(`. Update the internal call site inside `extract_citations` (~line 190/210) to `locate_in_chunk(...)`. If any other module imports `_locate_in_chunk`, add `_locate_in_chunk = locate_in_chunk` below the def as a back-compat alias (grep first: `grep -rn "_locate_in_chunk" api/app api/tests`).

- [ ] **Step 4: Run — expect pass + extraction regression**

Run: `cd api && .venv/bin/python -m pytest tests/citation/test_extraction.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/citation/extraction.py api/tests/citation/test_extraction.py
git commit -s -m "refactor(citation): promote _locate_in_chunk to public locate_in_chunk (WS-D PR2)"
```

---

### Task 3: Loop evidence registry + caselaw `cluster_id` in observation

**Files:**
- Modify: `api/app/autonomous/planner.py` (`summarize_observation` caselaw branch; add `EvidenceItem` dataclass + `collect_evidence`)
- Modify: `api/app/autonomous/nodes.py` (`_run_analysis_loop` accumulates evidence; returns it in state)
- Modify: `api/app/autonomous/state.py` (`analysis_evidence` state key — loop-local, NOT in trace)
- Test: `api/tests/autonomous/test_evidence_registry.py` (new)

**Interfaces:**
- Produces:
  - `@dataclass(slots=True) EvidenceItem(n: int, kind: str, ref: str, content: str, display: str)` — `kind` ∈ `{"kb","caselaw"}`; `ref` is the `chunk_id` (kb) or `cluster_id` (caselaw) as str; `content` is the authoritative text used for citation verification; `display` is a P3 one-liner.
  - `collect_evidence(intent: ToolIntent, result, start_n: int) -> list[EvidenceItem]` — turns a `ToolResult` into numbered evidence items (empty on failure / non-observe intents).
  - `summarize_observation(...)` caselaw line now includes `cluster_id` (P3-safe id).
  - `_run_analysis_loop` returns `analysis_evidence: list[dict]` in its result dict (each `EvidenceItem` as a JSONable dict).

- [ ] **Step 1: Write the failing tests** (`api/tests/autonomous/test_evidence_registry.py`):

```python
from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult
from app.autonomous.planner import EvidenceItem, collect_evidence, summarize_observation


def test_caselaw_observation_includes_cluster_id():
    result = ToolResult(data={"results": [
        {"case_name": "Smith v. Jones", "court": "ca9", "date_filed": "2021-01-01", "cluster_id": 42},
    ]}, outcome="success")
    s = summarize_observation(ToolIntent.retrieve_caselaw, "find authority", result)
    assert "Smith v. Jones" in s
    assert "42" in s  # cluster_id is shown so the synthesis can cite it


def test_collect_evidence_numbers_kb_chunks():
    result = ToolResult(data={"chunks": [
        {"chunk_id": "c1", "file_name": "nda.pdf", "content": "Confidential Information clause text."},
        {"chunk_id": "c2", "file_name": "nda.pdf", "content": "Term clause text."},
    ]}, outcome="success")
    items = collect_evidence(ToolIntent.retrieve_chunks, result, start_n=1)
    assert [i.n for i in items] == [1, 2]
    assert items[0].kind == "kb" and items[0].ref == "c1"
    assert items[0].content == "Confidential Information clause text."


def test_collect_evidence_numbers_caselaw():
    result = ToolResult(data={"results": [
        {"case_name": "Smith v. Jones", "cluster_id": 42, "opinion_text": "It is held that..."},
    ]}, outcome="success")
    items = collect_evidence(ToolIntent.retrieve_caselaw, result, start_n=5)
    assert items[0].n == 5 and items[0].kind == "caselaw" and items[0].ref == "42"
    assert "held" in items[0].content


def test_collect_evidence_empty_on_failure():
    assert collect_evidence(ToolIntent.retrieve_caselaw, ToolResult(data=None, outcome="error"), 1) == []
```

- [ ] **Step 2: Run — expect failure**

Run: `cd api && .venv/bin/python -m pytest tests/autonomous/test_evidence_registry.py -v`
Expected: FAIL — `EvidenceItem`/`collect_evidence` undefined; caselaw summary lacks cluster_id.

- [ ] **Step 3: Implement in `planner.py`.** Add near the top (after `summarize_observation`):

```python
@dataclass(slots=True)
class EvidenceItem:
    """A numbered piece of gathered authority the synthesis may quote-and-cite.

    ``content`` is the authoritative text used at delivery to verify a quoted
    span (chunk text for kb, opinion text for caselaw). Loop-local + synthesis
    context only — NEVER written to analysis_plan_trace/audit (P3)."""

    n: int
    kind: str  # "kb" | "caselaw"
    ref: str   # chunk_id (kb) | cluster_id (caselaw), as str
    content: str
    display: str


def collect_evidence(intent: ToolIntent, result: "object", start_n: int) -> list[EvidenceItem]:
    outcome = getattr(result, "outcome", "success")
    data = getattr(result, "data", None) or {}
    if outcome != "success":
        return []
    items: list[EvidenceItem] = []
    n = start_n
    if intent == ToolIntent.retrieve_chunks:
        for c in data.get("chunks") or []:
            if not isinstance(c, dict) or not c.get("chunk_id"):
                continue
            items.append(EvidenceItem(
                n=n, kind="kb", ref=str(c["chunk_id"]), content=str(c.get("content") or ""),
                display=f"{c.get('file_name') or '?'} (chunk {c['chunk_id']})",
            ))
            n += 1
    elif intent == ToolIntent.retrieve_caselaw:
        rows = data.get("results") or data.get("matches") or []
        for r in rows:
            if not isinstance(r, dict) or not r.get("cluster_id"):
                continue
            items.append(EvidenceItem(
                n=n, kind="caselaw", ref=str(r["cluster_id"]),
                content=str(r.get("opinion_text") or r.get("text") or ""),
                display=f"{r.get('case_name') or '?'} ({r.get('court') or '?'} {r.get('date_filed') or '?'})",
            ))
            n += 1
    return items
```

And in `summarize_observation`'s caselaw branch, include the cluster_id in each name entry, e.g.:

```python
        names = [
            f"{(i.get('case_name') or '?')} ({i.get('court') or '?'} {i.get('date_filed') or '?'}; cl={i.get('cluster_id') or '?'})"
            for i in items[:5] if isinstance(i, dict)
        ]
```

- [ ] **Step 4: Accumulate evidence in `_run_analysis_loop`** (`nodes.py`). Add `from app.autonomous.planner import collect_evidence` to the existing planner import. Initialize `evidence: list[EvidenceItem] = []` before the loop; in the action branch, after a successful `act`, extend it:

```python
        try:
            validate_action_args(decision.next_intent, decision.args)
            act = await guarded_tool_call(session, decision.next_intent, decision.args, db, gateway)
            observations.append(summarize_observation(decision.next_intent, decision.rationale, act))
            evidence.extend(collect_evidence(decision.next_intent, act, start_n=len(evidence) + 1))
        except AutonomousBrake:
            raise
        except Exception as exc:
            observations.append(f"{decision.next_intent.value} → failed ({type(exc).__name__})")
```

Pass `evidence` into the synthesis messages (Task 4 adds the param) and include it in the return dict:

```python
    return {
        "current_phase": str(Phase.analysis),
        "analysis_content": (synth.data or {}).get("content"),
        "analysis_outcome": synth.outcome,
        "analysis_plan_trace": {"steps": steps, "halt_reason": halt_reason, "decisions": trace},
        "analysis_evidence": [vars(e) for e in evidence],  # JSONable; consumed by delivery (P3: not in trace)
    }
```

Add `analysis_evidence: list[dict]` to `AutonomousSessionState` in `state.py` with a comment: "loop-gathered evidence for the synthesis + delivery ledger bridge; NOT surfaced in the receipt/trace (P3)."

- [ ] **Step 5: Run — expect pass + autonomous suite**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_evidence_registry.py tests/autonomous -q`
Expected: PASS (new + no autonomous regressions; the query-less path emits no evidence and is unchanged).

- [ ] **Step 6: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/planner.py api/app/autonomous/nodes.py api/app/autonomous/state.py api/tests/autonomous/test_evidence_registry.py
git commit -s -m "feat(autonomous): loop evidence registry + cluster_id in observations (WS-D PR2)"
```

---

### Task 4: Synthesis structured citations (schema + prompt + tolerant parse)

**Files:**
- Modify: `api/app/autonomous/prompts.py` (`assemble_synthesis_messages` gains `evidence` param + numbered-source block + citation instruction)
- Modify: `api/app/autonomous/structured_output.py` (parse finding `citations`)
- Modify: `api/app/autonomous/nodes.py` (pass `evidence` to `assemble_synthesis_messages`)
- Test: `api/tests/autonomous/test_synthesis_messages.py` (extend), `api/tests/autonomous/test_structured_output.py` (extend)

**Interfaces:**
- Consumes: `EvidenceItem` (Task 3).
- Produces:
  - `assemble_synthesis_messages(session, *, goal, observations, chunks, evidence: list[dict], db, registry=None)` — appends a numbered SOURCES block (from `evidence`) and instructs: support each finding with verbatim quotes tagged `{"quote": "...", "source": N}`.
  - `parse_structured_output(...)` — each parsed finding dict additionally carries `citations: list[dict]` (each `{"quote": str, "source": int}`); absent → `[]`; malformed entries dropped.

- [ ] **Step 1: Write the failing tests.** Append to `api/tests/autonomous/test_synthesis_messages.py`:

```python
async def test_synthesis_includes_numbered_evidence_and_citation_instruction(
    db_session, session_with_skill_ref
):
    msgs = await assemble_synthesis_messages(
        session_with_skill_ref, goal="Is the clause enforceable?",
        observations=["retrieve_caselaw → 1 result"],
        chunks=[],
        evidence=[
            {"n": 1, "kind": "kb", "ref": "c1", "content": "Confidential clause.", "display": "nda.pdf (chunk c1)"},
            {"n": 2, "kind": "caselaw", "ref": "42", "content": "It is held...", "display": "Smith (ca9 2021; cl=42)"},
        ],
        db=db_session,
    )
    blob = " ".join(m["content"] for m in msgs)
    assert "[1]" in blob and "nda.pdf" in blob          # numbered source list
    assert "[2]" in blob and "Smith" in blob
    assert "quote" in blob and "source" in blob          # citation instruction present
```

Append to `api/tests/autonomous/test_structured_output.py`:

```python
def test_parse_finding_citations():
    raw = (
        "```json\n{\"findings\": [{\"title\": \"T\", \"summary\": \"S\", \"severity\": \"info\", "
        "\"source_chunk_ids\": [], \"citations\": [{\"quote\": \"Confidential clause.\", \"source\": 1}]}], "
        "\"suggested_memories\": [], \"suggested_precedents\": [], "
        "\"privilege_concerns\": [], \"scope_concerns\": []}\n```"
    )
    parsed = parse_structured_output(raw)
    assert parsed.is_structured
    assert parsed.findings[0]["citations"] == [{"quote": "Confidential clause.", "source": 1}]


def test_parse_finding_citations_absent_defaults_empty():
    raw = (
        "```json\n{\"findings\": [{\"title\": \"T\", \"summary\": \"S\", \"severity\": \"info\", "
        "\"source_chunk_ids\": []}], \"suggested_memories\": [], \"suggested_precedents\": [], "
        "\"privilege_concerns\": [], \"scope_concerns\": []}\n```"
    )
    parsed = parse_structured_output(raw)
    assert parsed.findings[0].get("citations", []) == []
```

- [ ] **Step 2: Run — expect failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_synthesis_messages.py tests/autonomous/test_structured_output.py -v`
Expected: FAIL — `assemble_synthesis_messages` has no `evidence` param; findings carry no `citations`.

- [ ] **Step 3: Implement the prompt.** In `prompts.py`, change `assemble_synthesis_messages` to accept `evidence: list[dict[str, Any]]` and build a numbered source block + instruction before the existing user append:

```python
async def assemble_synthesis_messages(
    session: AutonomousSession,
    *,
    goal: str,
    observations: list[str],
    chunks: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    db: AsyncSession,
    registry: SkillRegistry | None = None,
) -> list[dict[str, str]]:
    messages = await assemble_analysis_messages(session, chunks=chunks, db=db, registry=registry)
    obs = "\n".join(f"- {o}" for o in observations) if observations else "(no research steps were run)"
    if evidence:
        sources = "\n".join(
            f"[{e['n']}] ({e['kind']}) {e['display']}\n    \"\"\"{e['content'][:1500]}\"\"\""
            for e in evidence
        )
        cite_block = (
            "\n\nNUMBERED SOURCES (cite these by number):\n" + sources +
            "\n\nFor every finding, support it with VERBATIM quotes from the numbered sources. "
            "In each finding's JSON, include a \"citations\" array of objects "
            "{\"quote\": \"<exact text copied from the source>\", \"source\": <source number>}. "
            "Copy quotes character-for-character; do not paraphrase inside a quote."
        )
    else:
        cite_block = ""
    messages.append({
        "role": "user",
        "content": (
            f"MATTER GOAL:\n{goal}\n\nRESEARCH OBSERVATIONS (gathered by the agent):\n{obs}{cite_block}\n\n"
            "Synthesize your analysis of the MATTER GOAL using the observations, the numbered sources, and any "
            "chunks above, then return the final JSON object as instructed."
        ),
    })
    return messages
```

In `nodes.py` `_run_analysis_loop`, pass `evidence=[vars(e) for e in evidence]` to `assemble_synthesis_messages`.

- [ ] **Step 4: Implement the parse.** In `structured_output.py`, where each finding dict is built from the parsed JSON, carry a sanitized `citations` list:

```python
        raw_citations = finding.get("citations")
        citations: list[dict[str, Any]] = []
        if isinstance(raw_citations, list):
            for c in raw_citations:
                if isinstance(c, dict) and isinstance(c.get("quote"), str) and isinstance(c.get("source"), int) \
                        and not isinstance(c.get("source"), bool):
                    citations.append({"quote": c["quote"], "source": c["source"]})
        normalized_finding["citations"] = citations
```

(Adapt `finding`/`normalized_finding` to the existing variable names in `parse_structured_output`. Keep `citations` OUT of the dict that `emit_finding` dispatches if the handler is strict about keys — confirm `emit_finding` ignores extra keys; if it does not, strip `citations` before the `emit_finding` call in the drafting node. Grep `_handle_emit_finding` in `guard.py`.)

- [ ] **Step 5: Run — expect pass + autonomous suite**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_synthesis_messages.py tests/autonomous/test_structured_output.py tests/autonomous -q`
Expected: PASS.

- [ ] **Step 6: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/prompts.py api/app/autonomous/structured_output.py api/app/autonomous/nodes.py api/tests/autonomous/test_synthesis_messages.py api/tests/autonomous/test_structured_output.py
git commit -s -m "feat(autonomous): structured per-finding citations in synthesis (WS-D PR2)"
```

---

### Task 5: KB structured-citation builder (`ledger_bridge.build_kb_citations`)

**Files:**
- Create: `api/app/autonomous/ledger_bridge.py`
- Test: `api/tests/autonomous/test_ledger_bridge_kb.py` (new)

**Interfaces:**
- Consumes: `locate_in_chunk` (Task 2), `verify` (`verification.py:545`), `CitationCandidate` (`extraction.py:87`), `DocumentChunk`/`Document` models, `MessageCitation`.
- Produces: `async build_kb_citations(db, *, message_id: uuid.UUID, citations: list[tuple[str, str]], gateway, judge_model: str = "fast") -> int` where each tuple is `(quote, chunk_id)`. Resolves the chunk + its document, verifies the quote, adds verified `MessageCitation` rows (`db.add` + flush), returns the count added.

- [ ] **Step 1: Write the failing test** (`api/tests/autonomous/test_ledger_bridge_kb.py`). Reuse `kb_with_one_indexed_file` (gives a real chunk with known text) + a manufactured chat/message:

```python
import pytest
from app.autonomous.ledger_bridge import build_kb_citations
from app.models.chat import Chat, Message, MessageCitation
from app.models.document import DocumentChunk
from sqlalchemy import select

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _msg(db, owner_id):
    chat = Chat(owner_id=owner_id, title="t")
    db.add(chat)
    await db.flush()
    msg = Message(chat_id=chat.id, role="assistant", content="wp")
    db.add(msg)
    await db.flush()
    return msg


async def test_build_kb_citations_verifies_and_persists(db_session, kb_with_one_indexed_file):
    chunk = (await db_session.execute(
        select(DocumentChunk).where(DocumentChunk.id == kb_with_one_indexed_file.chunk_id)
    )).scalar_one()
    quote = chunk.content[:40]  # an exact verbatim span
    # owner: reuse the chunk's KB owner via the document's file owner is heavy; make a fresh user.
    from app.models.user import User
    from app.security import hash_password
    user = User(email="kb-bridge@x.com", hashed_password=hash_password("p"), role="member",
                is_admin=False, mfa_enabled=False, must_change_password=False)
    db_session.add(user)
    await db_session.flush()
    msg = await _msg(db_session, user.id)

    n = await build_kb_citations(
        db_session, message_id=msg.id,
        citations=[(quote, str(kb_with_one_indexed_file.chunk_id))], gateway=None,
    )
    assert n == 1
    rows = (await db_session.execute(
        select(MessageCitation).where(MessageCitation.message_id == msg.id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].verified is True
    assert rows[0].source_text == quote
    assert rows[0].verification_method is not None


async def test_build_kb_citations_drops_unverifiable(db_session, kb_with_one_indexed_file):
    from app.models.user import User
    from app.security import hash_password
    user = User(email="kb-bridge2@x.com", hashed_password=hash_password("p"), role="member",
                is_admin=False, mfa_enabled=False, must_change_password=False)
    db_session.add(user)
    await db_session.flush()
    msg = await _msg(db_session, user.id)
    n = await build_kb_citations(
        db_session, message_id=msg.id,
        citations=[("text that does not appear anywhere", str(kb_with_one_indexed_file.chunk_id))],
        gateway=None,
    )
    assert n == 0  # honest: unverifiable quote dropped, no row
```

- [ ] **Step 2: Run — expect failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_ledger_bridge_kb.py -v`
Expected: FAIL — module/function missing.

- [ ] **Step 3: Implement** (`api/app/autonomous/ledger_bridge.py`):

```python
"""WS-D PR2 — bridge a matter session's structured citations into the chat-path
ledger + fiduciary gate. Reuses the character-fidelity verifier + assemble +
gate unchanged; only the citation-candidate front-end is session-specific.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.extraction import CitationCandidate, locate_in_chunk
from app.citation.verification import verify
from app.models.chat import MessageCitation
from app.models.document import Document, DocumentChunk

log = logging.getLogger(__name__)


async def build_kb_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    citations: list[tuple[str, str]],  # (quote, chunk_id)
    gateway: Any,
    judge_model: str = "fast",
) -> int:
    added = 0
    for quote, chunk_id in citations:
        try:
            chunk = (await db.execute(
                select(DocumentChunk).where(DocumentChunk.id == uuid.UUID(str(chunk_id)))
            )).scalar_one_or_none()
            if chunk is None:
                continue
            span = locate_in_chunk(quote, chunk.content)
            if span is None:
                continue
            in_start, in_end = span
            doc = (await db.execute(
                select(Document).where(Document.id == chunk.document_id)
            )).scalar_one_or_none()
            if doc is None:
                continue
            candidate = CitationCandidate(
                source_file_id=chunk.document.file_id if hasattr(chunk, "document") else doc.file_id,
                source_document_id=chunk.document_id,
                source_offset_start=chunk.char_offset_start + in_start,
                source_offset_end=chunk.char_offset_start + in_end,
                source_page=chunk.page_start,
                source_text=quote,
            )
            result = await verify(candidate, doc, gateway=gateway, judge_model=judge_model)
            if not result.verified:
                continue
            db.add(MessageCitation(
                message_id=message_id,
                source_file_id=candidate.source_file_id,
                source_offset_start=candidate.source_offset_start,
                source_offset_end=candidate.source_offset_end,
                source_page=candidate.source_page,
                source_text=quote,
                verified=True,
                verification_method=result.method,
                verification_confidence=result.confidence,
                partial=result.partial,
                tier_envelope=result.tier_envelope,
            ))
            added += 1
        except Exception:  # one bad citation must not sink the rest (honest, per-item)
            log.warning("kb citation build skipped", extra={"event": "autonomous_kb_citation_skip"}, exc_info=True)
    await db.flush()
    return added
```

(Confirm `verify`'s exact signature/kwargs at `verification.py:545` and `Document`'s document-protocol fields — it must satisfy `_DocumentProtocol` (`normalized_content`, `was_ocrd`, `id`). If `verify` needs a `_DocumentProtocol` wrapper rather than the raw `Document`, build the same wrapper `_persist_message_citations` uses — grep `chats.py:_persist_message_citations` for the doc object it passes.)

- [ ] **Step 4: Run — expect pass**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_ledger_bridge_kb.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/ledger_bridge.py api/tests/autonomous/test_ledger_bridge_kb.py
git commit -s -m "feat(autonomous): KB structured-citation ledger builder (WS-D PR2)"
```

---

### Task 6: Caselaw structured-citation builder (`ledger_bridge.build_caselaw_citations`)

**Files:**
- Modify: `api/app/autonomous/ledger_bridge.py`
- Test: `api/tests/autonomous/test_ledger_bridge_caselaw.py` (new)

**Interfaces:**
- Consumes: `locate_passage`/`opinion_target`/`_CaselawCandidate` (`caselaw.py:153/162/170`), `verify`, `ResearchOpinionMetadata`, `read_opinion` (`research/service.py:210`), `MessageCaselawCitation`.
- Produces: `async build_caselaw_citations(db, *, message_id, citations: list[tuple[str, str]], gateway, judge_model="fast", load_opinion_text=...) -> int` where each tuple is `(quote, cluster_id)`.

- [ ] **Step 1: Write the failing test** (`api/tests/autonomous/test_ledger_bridge_caselaw.py`). Seed a `ResearchOpinionMetadata` row + stub `read_opinion` to return known text:

```python
import pytest
from app.autonomous.ledger_bridge import build_caselaw_citations
from app.models.chat import Chat, Message
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.research import ResearchOpinionMetadata
from app.models.user import User
from app.security import hash_password
from sqlalchemy import select

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

OPINION_TEXT = "The court holds that the assignment clause survives the change of control."


async def _msg(db):
    user = User(email=f"cl-{__import__('uuid').uuid4().hex[:6]}@x.com", hashed_password=hash_password("p"),
                role="member", is_admin=False, mfa_enabled=False, must_change_password=False)
    db.add(user)
    await db.flush()
    chat = Chat(owner_id=user.id, title="t")
    db.add(chat)
    await db.flush()
    msg = Message(chat_id=chat.id, role="assistant", content="wp")
    db.add(msg)
    await db.flush()
    return msg


async def test_build_caselaw_citations_verifies(db_session):
    db_session.add(ResearchOpinionMetadata(opinion_id=900, cluster_id=42, storage_path="x/900"))
    await db_session.flush()
    msg = await _msg(db_session)

    async def fake_load(db, *, opinion_id):
        return {"text": OPINION_TEXT}

    n = await build_caselaw_citations(
        db_session, message_id=msg.id,
        citations=[("assignment clause survives the change of control", "42")],
        gateway=None, load_opinion_text=fake_load,
    )
    assert n == 1
    row = (await db_session.execute(
        select(MessageCaselawCitation).where(MessageCaselawCitation.message_id == msg.id)
    )).scalar_one()
    assert row.cluster_id == 42 and row.opinion_id == 900 and row.verified is True


async def test_build_caselaw_citations_unknown_cluster_skipped(db_session):
    msg = await _msg(db_session)

    async def fake_load(db, *, opinion_id):
        return {"text": OPINION_TEXT}

    n = await build_caselaw_citations(
        db_session, message_id=msg.id, citations=[("x", "9999")], gateway=None, load_opinion_text=fake_load,
    )
    assert n == 0  # no metadata for cluster 9999
```

- [ ] **Step 2: Run — expect failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_ledger_bridge_caselaw.py -v`
Expected: FAIL — function missing.

- [ ] **Step 3: Implement** — append to `ledger_bridge.py`:

```python
from collections.abc import Awaitable, Callable

from app.citation.caselaw import _CaselawCandidate, locate_passage, opinion_target
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.research import ResearchOpinionMetadata
from app.research.service import read_opinion as _default_read_opinion

_LoadOpinion = Callable[..., Awaitable[dict[str, Any]]]


async def build_caselaw_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    citations: list[tuple[str, str]],  # (quote, cluster_id)
    gateway: Any,
    judge_model: str = "fast",
    load_opinion_text: _LoadOpinion = _default_read_opinion,
) -> int:
    added = 0
    for quote, cluster_id in citations:
        try:
            meta = (await db.execute(
                select(ResearchOpinionMetadata).where(
                    ResearchOpinionMetadata.cluster_id == int(cluster_id)
                )
            )).scalars().first()
            if meta is None:
                continue
            opinion = await load_opinion_text(db, opinion_id=meta.opinion_id)
            text = str((opinion or {}).get("text") or "")
            span = locate_passage(quote, text)
            if span is None:
                continue
            start, end = span
            target = opinion_target(meta.opinion_id, text)
            candidate = _CaselawCandidate(
                source_offset_start=start, source_offset_end=end,
                source_text=quote, source_document_id=target.id,
            )
            result = await verify(candidate, target, gateway=gateway, judge_model=judge_model)
            if not result.verified:
                continue
            db.add(MessageCaselawCitation(
                message_id=message_id, opinion_id=meta.opinion_id, cluster_id=meta.cluster_id,
                source_offset_start=start, source_offset_end=end, source_text=quote,
                verified=True, verification_method=result.method,
                verification_confidence=result.confidence, partial=result.partial,
            ))
            added += 1
        except Exception:
            log.warning("caselaw citation build skipped",
                        extra={"event": "autonomous_caselaw_citation_skip"}, exc_info=True)
    await db.flush()
    return added
```

(Confirm `locate_passage`/`opinion_target`/`_CaselawCandidate` are importable from `caselaw.py`; if module-private (`_`-prefixed), import them by their actual names — grep `caselaw.py`. Confirm `read_opinion`'s kwargs.)

- [ ] **Step 4: Run — expect pass**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_ledger_bridge_caselaw.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/ledger_bridge.py api/tests/autonomous/test_ledger_bridge_caselaw.py
git commit -s -m "feat(autonomous): caselaw structured-citation ledger builder (WS-D PR2)"
```

---

### Task 7: Bridge orchestration (`build_session_ledger`) + delivery wiring

**Files:**
- Modify: `api/app/autonomous/ledger_bridge.py` (`build_session_ledger`)
- Modify: `api/app/autonomous/nodes.py` (delivery node calls the bridge; embeds verdict in `session.result`)
- Test: `api/tests/autonomous/test_session_ledger.py` (new — end-to-end-ish)

**Interfaces:**
- Consumes: `build_kb_citations`/`build_caselaw_citations` (Tasks 5/6), `assemble_ledger_entries` (`ledger.py:32`), `compute_and_record_gate` (`gate.py:33`), `Chat`/`Message` models, `AutonomousSession`.
- Produces: `async build_session_ledger(db, *, session: AutonomousSession, work_product_text: str, findings: list[dict], evidence: list[dict], gateway, judge_model="fast") -> dict | None` — manufactures the hidden chat+message, splits each finding's `citations` into kb/caselaw by the evidence registry `kind`, builds rows, runs assemble+gate, returns `{gate_status, pass_count, supported_count, fail_count, total_assertions, confidence}` (or `None` if no citations resolved / on failure).

- [ ] **Step 1: Write the failing test** (`api/tests/autonomous/test_session_ledger.py`):

```python
import pytest
from app.autonomous.ledger_bridge import build_session_ledger
from app.models.autonomous import AutonomousSession
from app.models.chat import Chat
from app.models.citation_ledger_entry import CitationLedgerEntry
from app.models.work_product_fiduciary_gate import WorkProductFiduciaryGate
from app.models.user import User
from app.security import hash_password
from sqlalchemy import select

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_build_session_ledger_creates_hidden_chat_entries_and_gate(db_session, kb_with_one_indexed_file):
    from app.models.document import DocumentChunk
    chunk = (await db_session.execute(
        select(DocumentChunk).where(DocumentChunk.id == kb_with_one_indexed_file.chunk_id)
    )).scalar_one()
    quote = chunk.content[:40]
    user = User(email="sl@x.com", hashed_password=hash_password("p"), role="member",
                is_admin=False, mfa_enabled=False, must_change_password=False)
    db_session.add(user)
    await db_session.flush()
    sess = AutonomousSession(user_id=user.id, trigger_kind="manual", params={"query": "q"})
    db_session.add(sess)
    await db_session.flush()

    verdict = await build_session_ledger(
        db_session, session=sess, work_product_text="Work product.",
        findings=[{"title": "T", "summary": "S", "severity": "info",
                   "citations": [{"quote": quote, "source": 1}]}],
        evidence=[{"n": 1, "kind": "kb", "ref": str(kb_with_one_indexed_file.chunk_id),
                   "content": chunk.content, "display": "nda.pdf"}],
        gateway=None,
    )
    assert verdict is not None and verdict["gate_status"] in {"fiduciary_grade", "supported_only", "flagged"}

    chat = (await db_session.execute(
        select(Chat).where(Chat.autonomous_session_id == sess.id)
    )).scalar_one()  # hidden chat manufactured
    entries = (await db_session.execute(
        select(CitationLedgerEntry).where(CitationLedgerEntry.chat_id == chat.id)
    )).scalars().all()
    assert len(entries) >= 1
    gate = (await db_session.execute(
        select(WorkProductFiduciaryGate).where(WorkProductFiduciaryGate.chat_id == chat.id)
    )).scalar_one()
    assert gate.gate_status == verdict["gate_status"]


async def test_build_session_ledger_no_citations_returns_none(db_session):
    user = User(email="sl2@x.com", hashed_password=hash_password("p"), role="member",
                is_admin=False, mfa_enabled=False, must_change_password=False)
    db_session.add(user)
    await db_session.flush()
    sess = AutonomousSession(user_id=user.id, trigger_kind="manual", params={"query": "q"})
    db_session.add(sess)
    await db_session.flush()
    verdict = await build_session_ledger(
        db_session, session=sess, work_product_text="No citations.",
        findings=[{"title": "T", "summary": "S", "severity": "info", "citations": []}],
        evidence=[], gateway=None,
    )
    assert verdict is None  # nothing to ledger → no manufactured chat
    assert (await db_session.execute(
        select(Chat).where(Chat.autonomous_session_id == sess.id)
    )).scalar_one_or_none() is None
```

- [ ] **Step 2: Run — expect failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_session_ledger.py -v`
Expected: FAIL — `build_session_ledger` missing.

- [ ] **Step 3: Implement** — append to `ledger_bridge.py`:

```python
from app.citation.gate import compute_and_record_gate
from app.citation.ledger import assemble_ledger_entries
from app.models.autonomous import AutonomousSession
from app.models.chat import Chat, Message


async def build_session_ledger(
    db: AsyncSession,
    *,
    session: AutonomousSession,
    work_product_text: str,
    findings: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    gateway: Any,
    judge_model: str = "fast",
) -> dict[str, Any] | None:
    by_n = {int(e["n"]): e for e in evidence if isinstance(e.get("n"), int)}
    kb: list[tuple[str, str]] = []
    cl: list[tuple[str, str]] = []
    for f in findings:
        for c in f.get("citations") or []:
            ev = by_n.get(c.get("source"))
            if ev is None or not isinstance(c.get("quote"), str):
                continue
            if ev["kind"] == "kb":
                kb.append((c["quote"], ev["ref"]))
            elif ev["kind"] == "caselaw":
                cl.append((c["quote"], ev["ref"]))
    if not kb and not cl:
        return None  # nothing citable → no manufactured chat, no gate

    chat = Chat(
        owner_id=session.user_id,
        project_id=session.project_id,
        title=f"Matter session {session.id}",
        autonomous_session_id=session.id,
    )
    db.add(chat)
    await db.flush()
    message = Message(chat_id=chat.id, role="assistant", content=work_product_text)
    db.add(message)
    await db.flush()

    await build_kb_citations(db, message_id=message.id, citations=kb, gateway=gateway, judge_model=judge_model)
    await build_caselaw_citations(db, message_id=message.id, citations=cl, gateway=gateway, judge_model=judge_model)
    await assemble_ledger_entries(db, message_id=message.id)
    gate = await compute_and_record_gate(db, message_id=message.id)
    if gate is None:
        return None
    return {
        "gate_status": gate.gate_status,
        "pass_count": gate.pass_count,
        "supported_count": gate.supported_count,
        "fail_count": gate.fail_count,
        "total_assertions": gate.total_assertions,
        "confidence": float(gate.confidence) if gate.confidence is not None else None,
    }
```

- [ ] **Step 4: Wire the delivery node** (`nodes.py` `make_delivery_node` → `delivery_node`). Before `session.result = await build_receipt_safe(...)`, for a matter session, call the bridge best-effort and merge the verdict into the receipt:

```python
        receipt = await build_receipt_safe(session, db)
        plan_trace = state.get("analysis_plan_trace")
        if isinstance(receipt, dict) and plan_trace is not None:
            receipt["plan_trace"] = plan_trace
        # WS-D PR2: fiduciary ledger + gate for matter sessions (best-effort).
        findings = state.get("findings") or []
        evidence = state.get("analysis_evidence") or []
        work_product = state.get("analysis_content") or ""
        if findings and evidence and work_product:
            try:
                from app.autonomous.ledger_bridge import build_session_ledger

                verdict = await build_session_ledger(
                    db, session=session, work_product_text=work_product,
                    findings=findings, evidence=evidence, gateway=gateway,
                )
                if verdict is not None and isinstance(receipt, dict):
                    receipt["fiduciary_gate"] = verdict
            except Exception:
                logger.warning("autonomous ledger bridge failed",
                               extra={"event": "autonomous_ledger_bridge_failed",
                                      "session_id": session_id}, exc_info=True)
        session.result = receipt
```

NOTE: `state["findings"]` carries the drafting node's emitted findings WITHOUT the `citations` key (drafting strips/ignores it). The bridge needs findings WITH `citations`. Resolve by having the drafting node forward the parsed findings (incl. `citations`) in a separate state key `analysis_findings_with_citations`, OR re-parse `analysis_content` in the delivery wiring via `parse_structured_output(work_product)`. PREFER re-parsing in delivery (single source, no extra state): replace `findings = state.get("findings") or []` with:

```python
        from app.autonomous.structured_output import parse_structured_output
        parsed = parse_structured_output(state.get("analysis_content"))
        findings = parsed.findings if parsed.is_structured else []
```

- [ ] **Step 5: Run — expect pass + autonomous suite (solo)**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_session_ledger.py tests/autonomous -q`
Expected: PASS (incl. the existing delivery/receipt tests — query-less sessions emit no findings/evidence → bridge not called → `session.result` unchanged).

- [ ] **Step 6: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/ledger_bridge.py api/app/autonomous/nodes.py api/tests/autonomous/test_session_ledger.py
git commit -s -m "feat(autonomous): session ledger bridge + delivery wiring (WS-D PR2)"
```

---

### Task 8: Session-ledger read endpoint

**Files:**
- Modify: the autonomous sessions router (grep `@router.get` in `api/app/api/autonomous.py` — confirm the file/prefix; sessions live under `/api/v1/autonomous/sessions`)
- Test: `api/tests/autonomous/test_session_ledger_endpoint.py` (new)

**Interfaces:**
- Consumes: the chat ledger read path — find the function the chat `GET /chats/{chat_id}/ledger` handler calls (grep `def .*ledger` in `api/app/api/chats.py` and `api/app/citation/ledger.py`; likely a `resolve_ledger`/`resolve_gates` pair). Reuse it scoped to the manufactured chat.
- Produces: `GET /api/v1/autonomous/sessions/{session_id}/ledger` → the same response shape the chat ledger endpoint returns; `404` if the session has no ledger (no manufactured chat yet); `403`/`404` if the session is not owned by the caller.

- [ ] **Step 1: Write the failing test** (`api/tests/autonomous/test_session_ledger_endpoint.py`). Build a session ledger via `build_session_ledger` (Task 7) then GET it:

```python
import pytest
from app.autonomous.ledger_bridge import build_session_ledger
from app.models.autonomous import AutonomousSession
from app.models.document import DocumentChunk
from sqlalchemy import select

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_session_ledger_endpoint_returns_entries(
    db_session, client, kb_with_one_indexed_file, owner_user
):
    chunk = (await db_session.execute(
        select(DocumentChunk).where(DocumentChunk.id == kb_with_one_indexed_file.chunk_id)
    )).scalar_one()
    quote = chunk.content[:40]
    sess = AutonomousSession(user_id=owner_user.id, trigger_kind="manual", params={"query": "q"})
    db_session.add(sess)
    await db_session.flush()
    await build_session_ledger(
        db_session, session=sess, work_product_text="wp",
        findings=[{"title": "T", "summary": "S", "severity": "info",
                   "citations": [{"quote": quote, "source": 1}]}],
        evidence=[{"n": 1, "kind": "kb", "ref": str(kb_with_one_indexed_file.chunk_id),
                   "content": chunk.content, "display": "nda.pdf"}],
        gateway=None,
    )
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/ledger",
        headers={"Authorization": _bearer_for(owner_user)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["gate"]["gate_status"] in {"fiduciary_grade", "supported_only", "flagged"}
    assert len(body["entries"]) >= 1


async def test_session_ledger_endpoint_404_without_ledger(db_session, client, owner_user):
    sess = AutonomousSession(user_id=owner_user.id, trigger_kind="manual", params={})
    db_session.add(sess)
    await db_session.commit()
    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/ledger",
        headers={"Authorization": _bearer_for(owner_user)},
    )
    assert resp.status_code == 404
```

(Adapt `client`/`owner_user`/`_bearer_for` to the autonomous router's existing endpoint-test fixtures — grep `api/tests/autonomous/test_sessions_api.py` for the established client + auth pattern and reuse it verbatim.)

- [ ] **Step 2: Run — expect failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_session_ledger_endpoint.py -v`
Expected: FAIL — 404 route not found.

- [ ] **Step 3: Implement the endpoint.** First grep the chat ledger handler to find the reusable resolve function:
`grep -n "ledger" api/app/api/chats.py | head` and `grep -n "def resolve" api/app/citation/ledger.py api/app/citation/gate.py`.
Then add to the autonomous sessions router (mirror the existing GET handlers' auth dependency + ownership check):

```python
@router.get("/sessions/{session_id}/ledger")
async def get_session_ledger(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    session = await db.get(AutonomousSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="session not found")
    chat = (await db.execute(
        select(Chat).where(Chat.autonomous_session_id == session_id)
    )).scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail="session has no ledger")
    entries = await resolve_ledger(db, chat_id=chat.id)   # reuse the chat ledger read path
    gates = await resolve_gates(db, chat_id=chat.id)
    return {"entries": entries, "gate": gates[0] if gates else None}
```

(Use the EXACT reuse functions + response serialization the chat `/ledger` endpoint uses — match its response schema so the PR2-UI can reuse the chat ledger component. If the chat endpoint returns Pydantic models, return the same models, not raw dicts.)

- [ ] **Step 4: Register the route count.** If `api/tests/test_openapi.py` pins the exact path count + `EXPECTED_PATHS`, add `/api/v1/autonomous/sessions/{session_id}/ledger` and bump the count; add the route to `IMPLEMENTED_ROUTES` in `api/tests/test_endpoints.py` if present (collision-guard — see CLAUDE.md).

- [ ] **Step 5: Run — expect pass + openapi/endpoints guards**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_session_ledger_endpoint.py tests/test_openapi.py tests/test_endpoints.py -v`
Expected: PASS.

- [ ] **Step 6: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/api/autonomous.py api/tests/autonomous/test_session_ledger_endpoint.py api/tests/test_openapi.py api/tests/test_endpoints.py
git commit -s -m "feat(autonomous): session-ledger read endpoint (WS-D PR2)"
```

---

## Final gate (before requesting review — CI scope, repo root, SOLO suite)

- [ ] **api full gates:**
```bash
cd /Users/kevinkeller/Code/lq-ai
api/.venv/bin/ruff check api scripts && api/.venv/bin/ruff format --check api scripts
cd api && .venv/bin/mypy app
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest -q   # SOLO — no concurrent pytest (DE-368)
```
- [ ] **gateway full gates:** `cd gateway && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app --strict && .venv/bin/python -m pytest -q` (PR2 doesn't touch gateway; confirm no incidental break).
- [ ] **migration verified** on a throwaway pgvector (0063 up/down).
- [ ] **PRD/ADR bookkeeping:** note WS-D PR2 status; file DE-369 only if one surfaces.
- [ ] **Opus whole-branch review** (SDD final) — required; it has caught a real gate-passing defect on every slice this milestone.
- [ ] **Push origin + tucuxi → open the security-gated PR (NO self-merge) → mirror after merge.**

## Plan self-review (completed)

- **Spec coverage:** C1 hidden chat → Task 1; `locate_in_chunk` promotion → Task 2; C2 evidence registry → Task 3; C3 structured citations → Task 4; C4 KB builder → Task 5, caselaw builder → Task 6, orchestration + delivery → Task 7; C5 read endpoint → Task 8. Best-effort/P3/backward-compat constraints are folded into Tasks 3/7. PR2-UI explicitly deferred.
- **Placeholder scan:** real code + commands throughout. The two "grep + confirm" notes (verify()'s doc-protocol wrapper in Task 5; the chat ledger resolve function names in Task 8) are explicit verification steps against existing code, not logic placeholders — the implementer confirms the exact existing signature before calling it.
- **Type consistency:** `EvidenceItem(n,kind,ref,content,display)`, `collect_evidence`, `build_kb_citations((quote,chunk_id))`, `build_caselaw_citations((quote,cluster_id))`, `build_session_ledger(...) -> dict|None` with `{gate_status,pass_count,supported_count,fail_count,total_assertions,confidence}`, and the `findings[*].citations=[{quote,source}]` shape are consistent across Tasks 3–8.
