# WS-G PR2 — Treatment-Classifying Judge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify how each citing opinion treats a cited case (`followed/distinguished/criticized/questioned/overruled/superseded/neutral`) over a recency-capped, budget-bounded subset, and roll the per-passage classifications up to a strongest-negative case-level signal on `citation_treatment`.

**Architecture:** Extends WS-G PR1's async `treatment_derivation_job` with a judge pass. A new treatment judge (new prompt + verdict schema over the existing judge rails) classifies CourtListener `snippet`s; results land in a new `citation_treatment_signal` child table + rollup columns on the parent. The raw snippet is transient judge input — never persisted (P3). Treatment never gates the fiduciary verdict.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, arq, pytest, ruff, mypy. Gateway: CourtListener provider adapter.

## Global Constraints

- **Security-gated** (`gateway/**`, `api/app/citation/**`): Kevin/security merges; mirror `origin/main → tucuxi` after. Claude does NOT self-merge.
- **Next migration = `0062`** (revises `0061`). **Next DE = DE-365.**
- **Derive-don't-assert (ADR 0019 D1):** no "good/bad law" verdict; rollup surfaces strongest-negative + counts + per-signal links/confidence/reasoning, labeled "derived as of <date>."
- **P3 (ADR 0016):** `citation_treatment_signal` stores derived classification + confidence + judge justification + refs ONLY. **Never the raw snippet or opinion text.** Add the child model to the `_AUDIT_MODELS` tripwire in the same PR.
- **Strictly additive:** worker without gateway/judge-model config → graph-only (byte-identical to PR1). No gateway / no judge model / no snippet → PR1 row stands.
- **Treatment never gates the turn** (ADR 0018 D3 / 0019 D2): no change to `gate.py` or the fiduciary verdict.
- **Conservative judge calibration:** on uncertainty between a negative class and `neutral`, prefer `neutral` (a false negative-treatment flag is the worse error).
- **DE-344 scope for PR2 (pinned to WS-E, maintainer-confirmed 2026-06-26):** the **per-case judge budget** is PR2's cost bound (ships + bites in the worker) — the milestone's first real external-work cost control. The autonomous-layer `estimate_tool_cost`/R4 wiring (`api/app/autonomous/cost.py`, keyed by `ToolIntent` — `get_citing_opinions` is not an autonomous intent and the worker bypasses R4) is **explicitly scheduled to land in WS-E**, whose first metered source is DE-344's own "when-to-ship" trigger. Update the DE-344 PRD entry to record this (per the Final-gate bookkeeping step). PR2 does not contort R4.
- **Tests:** host venv + throwaway pgvector `lqai-test-pg` on `:55432`, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test` (conftest auto-migrates). Mocked gateway/fetch → no `-m provider`.
- **CI gate (LESSON):** run, repo-wide: api `mypy app` (whole-app) + `ruff format --check api` + `ruff check api`; gateway `mypy app --strict` + `ruff format --check gateway` + `ruff check gateway`; both full suites. Per-file checks miss whole-app mypy + unformatted test files.
- Commits: `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## Canonical constants (use verbatim across tasks)

```python
# Treatment taxonomy (ADR 0019 D5)
TREATMENT_CLASSES = (
    "followed", "distinguished", "criticized",
    "questioned", "overruled", "superseded", "neutral",
)
# Negative classes, STRONGEST FIRST (index 0 = most severe).
NEGATIVE_SEVERITY = ("overruled", "superseded", "criticized", "questioned", "distinguished")
# Non-negative classes (never a "strongest negative"): "followed", "neutral".

N_JUDGED_CAP = 10                              # top-N most-recent citing opinions judged
TREATMENT_JUDGE_BUDGET_USD = Decimal("0.25")   # per-cited-case hard cap (B1b-style pre-flight)
_TREATMENT_PURPOSE = "judge_treatment"         # cost-calibration + routing-log tag
CORROBORATION_BUMP = 0.05                       # per additional agreeing passage
CONFIDENCE_CAP = 0.95                           # rollup confidence ceiling
```

## File structure

| File | Responsibility | Task |
|---|---|---|
| `gateway/app/providers/tool/courtlistener.py` | add `snippet` to each citing result | 1 |
| `gateway/tests/test_courtlistener_adapter.py` | snippet present/absent tests | 1 |
| `api/app/models/citation_treatment_signal.py` | NEW child model | 2 |
| `api/app/models/citation_treatment.py` | add rollup cols + relax CHECK | 2 |
| `api/alembic/versions/0062_citation_treatment_signal.py` | NEW migration | 2 |
| `api/tests/test_transparency_invariants.py` | add child to `_AUDIT_MODELS` | 2 |
| `api/app/citation/treatment_judge.py` | NEW: prompt + parser + judge + cost + `TreatmentJudgment` | 3 |
| `api/app/citation/treatment_rollup.py` | NEW: pure `roll_up` | 4 |
| `api/app/citation/treatment.py` | judge pass in `derive_treatment_for_message` | 5 |
| `api/app/workers/treatment_worker.py` | thread gateway + judge_model; graph-only degrade | 6 |
| `api/app/citation/ledger.py` | expose rollup + signals on `/ledger` read | 7 |

---

### Task 1: Gateway — return the citing `snippet`

**Files:**
- Modify: `gateway/app/providers/tool/courtlistener.py:319-329` (`_get_citing_opinions`)
- Test: `gateway/tests/test_courtlistener_adapter.py`

**Interfaces:**
- Produces: each item in `payload["citing"]` gains `"snippet": str | None` (CourtListener's per-result highlighted excerpt; `None` when absent). Other ref fields unchanged.

- [ ] **Step 1: Write the failing test** (append to `test_courtlistener_adapter.py`)

```python
@pytest.mark.unit
async def test_get_citing_opinions_includes_snippet(monkeypatch) -> None:
    adapter = _adapter(monkeypatch)
    results = [
        {
            "cluster_id": 1000,
            "caseName": "Citing Case",
            "court": "ca9",
            "dateFiled": "2021-05-01",
            "opinions": [{"id": 5000, "snippet": "We decline to follow Smith v. Jones."}],
        },
        {  # no snippet anywhere → None, never raises
            "cluster_id": 1001,
            "caseName": "Quiet Case",
            "court": "ca2",
            "dateFiled": "2021-04-01",
            "opinions": [{"id": 5001}],
        },
    ]
    with respx.mock:
        respx.get(f"{BASE}/search/").mock(
            return_value=httpx.Response(200, json={"count": 2, "results": results, "next": None})
        )
        try:
            result = await adapter.invoke_tool(
                "get_citing_opinions", {"opinion_id": 42}, request_id="r"
            )
        finally:
            await adapter.aclose()
    citing = result.payload["citing"]
    assert citing[0]["snippet"] == "We decline to follow Smith v. Jones."
    assert citing[1]["snippet"] is None
    assert "snippet" in set(citing[0])
```

> NOTE: CourtListener returns the opinion `snippet` inside each `result["opinions"][i]`. Verify the exact field against a live fixture during implementation; if upstream places it at the result top level instead, read `r.get("snippet")` as the fallback. The test above asserts the contract; adjust only the extraction expression, not the contract.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gateway && python -m pytest tests/test_courtlistener_adapter.py::test_get_citing_opinions_includes_snippet -v`
Expected: FAIL — `KeyError: 'snippet'`.

- [ ] **Step 3: Implement** — in `_get_citing_opinions`, extend the comprehension:

```python
        citing = [
            {
                "cluster_id": r.get("cluster_id"),
                "opinion_id": (r.get("opinions") or [{}])[0].get("id"),
                "case_name": r.get("caseName"),
                "court": r.get("court"),
                "date_filed": r.get("dateFiled"),
                # WS-G PR2: the highlighted excerpt around the citing match.
                # Transient treatment-judge input — NEVER persisted (P3).
                "snippet": (r.get("opinions") or [{}])[0].get("snippet") or r.get("snippet"),
            }
            for r in (data.get("results") or [])[:_CITING_TOP_N]
        ]
```

- [ ] **Step 4: Update the existing shape test.** In `test_get_citing_opinions_shapes_count_and_capped_list`, change the field-set assertion:

```python
    assert set(payload["citing"][0]) == {
        "cluster_id", "opinion_id", "case_name", "court", "date_filed", "snippet",
    }
```

- [ ] **Step 5: Run the adapter tests**

Run: `cd gateway && python -m pytest tests/test_courtlistener_adapter.py -v`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add gateway/app/providers/tool/courtlistener.py gateway/tests/test_courtlistener_adapter.py
git commit -s -m "feat(gateway): return citing snippet from get_citing_opinions (WS-G PR2)"
```

---

### Task 2: Schema — `citation_treatment_signal` child + parent rollup columns + migration 0062 + P3 tripwire

**Files:**
- Create: `api/app/models/citation_treatment_signal.py`
- Modify: `api/app/models/citation_treatment.py:26-33` (`__table_args__`) + add 3 columns
- Create: `api/alembic/versions/0062_citation_treatment_signal.py`
- Modify: `api/tests/test_transparency_invariants.py` (`_AUDIT_MODELS`)
- Test: `api/tests/test_citation_treatment_signal_model.py` (new)

**Interfaces:**
- Produces:
  - `CitationTreatmentSignal(id, treatment_id, citing_opinion_id, classification, confidence, justification, created_at)`; unique `(treatment_id, citing_opinion_id)`; `classification` CHECK ∈ `TREATMENT_CLASSES`; FK `ON DELETE CASCADE`.
  - `CitationTreatment` gains `strongest_negative_class: str | None`, `judged_count: int | None`, `judge_as_of: datetime | None`; `derived_method` CHECK now ∈ `('citation_graph', 'citation_graph+judge')`.

- [ ] **Step 1: Write the failing model test** (`api/tests/test_citation_treatment_signal_model.py`)

```python
import uuid
import pytest
from sqlalchemy import select
from app.models.citation_treatment import CitationTreatment
from app.models.citation_treatment_signal import CitationTreatmentSignal

pytestmark = pytest.mark.asyncio


async def _treatment(db) -> CitationTreatment:
    t = CitationTreatment(
        cluster_id=111, opinion_id=222, cited_by_count=5,
        citing_opinions=[], derived_method="citation_graph+judge",
        strongest_negative_class="questioned", judged_count=3,
    )
    db.add(t)
    await db.flush()
    return t


async def test_signal_round_trips_and_cascades(db_session) -> None:
    t = await _treatment(db_session)
    db_session.add(CitationTreatmentSignal(
        treatment_id=t.id, citing_opinion_id=5000,
        classification="questioned", confidence=0.7,
        justification="The citing court doubted the holding.",
    ))
    await db_session.flush()
    rows = (await db_session.execute(
        select(CitationTreatmentSignal).where(CitationTreatmentSignal.treatment_id == t.id)
    )).scalars().all()
    assert len(rows) == 1 and rows[0].classification == "questioned"
    # CASCADE: deleting the parent removes its signals.
    await db_session.delete(t)
    await db_session.flush()
    remaining = (await db_session.execute(select(CitationTreatmentSignal))).scalars().all()
    assert remaining == []


async def test_bad_classification_rejected(db_session) -> None:
    from sqlalchemy.exc import IntegrityError
    t = await _treatment(db_session)
    db_session.add(CitationTreatmentSignal(
        treatment_id=t.id, citing_opinion_id=1, classification="bogus", confidence=0.5,
        justification="x",
    ))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_parent_allows_graph_plus_judge_method(db_session) -> None:
    db_session.add(CitationTreatment(
        cluster_id=9, opinion_id=9, cited_by_count=0, citing_opinions=[],
        derived_method="citation_graph+judge",
    ))
    await db_session.flush()  # must not raise
```

> Use the project's existing `db_session` fixture (the throwaway-pgvector session). If the fixture name differs, match the one used in `api/tests/test_citation_treatment_model.py`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/test_citation_treatment_signal_model.py -v`
Expected: FAIL — `ModuleNotFoundError: app.models.citation_treatment_signal`.

- [ ] **Step 3: Create the child model** (`api/app/models/citation_treatment_signal.py`)

```python
"""citation_treatment_signal — one judged citing passage's treatment (WS-G PR2).

One row per citing opinion the treatment judge classified for a cited case.
Stores the DERIVED classification + confidence + the judge's short
justification (our reasoning) + the citing opinion ref — NEVER the raw
snippet or opinion text (ADR 0016 P3 / ADR 0019 D7). Joins the P3 tripwire.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

_CLASS_LIST = "'followed','distinguished','criticized','questioned','overruled','superseded','neutral'"


class CitationTreatmentSignal(Base):
    __tablename__ = "citation_treatment_signal"
    __table_args__ = (
        UniqueConstraint(
            "treatment_id", "citing_opinion_id",
            name="uq_treatment_signal_treatment_citing",
        ),
        CheckConstraint(
            f"classification IN ({_CLASS_LIST})",
            name="chk_treatment_signal_classification",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    treatment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("citation_treatment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    citing_opinion_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    classification: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: Add parent columns + relax CHECK** (`api/app/models/citation_treatment.py`)

In `__table_args__`, replace the `derived_method` CHECK:

```python
        CheckConstraint(
            "derived_method IN ('citation_graph', 'citation_graph+judge')",
            name="chk_citation_treatment_method_values",
        ),
        CheckConstraint(
            "strongest_negative_class IS NULL OR strongest_negative_class IN "
            "('overruled','superseded','criticized','questioned','distinguished')",
            name="chk_citation_treatment_strongest_negative",
        ),
```

Add three columns after `derived_method`:

```python
    strongest_negative_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    judged_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    judge_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 5: Create migration 0062** (`api/alembic/versions/0062_citation_treatment_signal.py`)

```python
"""citation_treatment_signal + parent rollup columns (WS-G PR2 treatment judge)

Revision ID: 0062
Revises: 0061
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLASSES = "'followed','distinguished','criticized','questioned','overruled','superseded','neutral'"
_NEGATIVE = "'overruled','superseded','criticized','questioned','distinguished'"


def upgrade() -> None:
    op.create_table(
        "citation_treatment_signal",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("treatment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("citing_opinion_id", sa.BigInteger(), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["treatment_id"], ["citation_treatment.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("treatment_id", "citing_opinion_id",
                            name="uq_treatment_signal_treatment_citing"),
        sa.CheckConstraint(f"classification IN ({_CLASSES})",
                           name="chk_treatment_signal_classification"),
    )
    op.create_index("ix_treatment_signal_treatment_id", "citation_treatment_signal", ["treatment_id"])

    op.add_column("citation_treatment", sa.Column("strongest_negative_class", sa.Text(), nullable=True))
    op.add_column("citation_treatment", sa.Column("judged_count", sa.Integer(), nullable=True))
    op.add_column("citation_treatment", sa.Column("judge_as_of", sa.DateTime(timezone=True), nullable=True))

    op.drop_constraint("chk_citation_treatment_method_values", "citation_treatment", type_="check")
    op.create_check_constraint(
        "chk_citation_treatment_method_values", "citation_treatment",
        "derived_method IN ('citation_graph', 'citation_graph+judge')",
    )
    op.create_check_constraint(
        "chk_citation_treatment_strongest_negative", "citation_treatment",
        f"strongest_negative_class IS NULL OR strongest_negative_class IN ({_NEGATIVE})",
    )


def downgrade() -> None:
    op.drop_constraint("chk_citation_treatment_strongest_negative", "citation_treatment", type_="check")
    op.drop_constraint("chk_citation_treatment_method_values", "citation_treatment", type_="check")
    op.create_check_constraint(
        "chk_citation_treatment_method_values", "citation_treatment",
        "derived_method IN ('citation_graph')",
    )
    op.drop_column("citation_treatment", "judge_as_of")
    op.drop_column("citation_treatment", "judged_count")
    op.drop_column("citation_treatment", "strongest_negative_class")
    op.drop_index("ix_treatment_signal_treatment_id", table_name="citation_treatment_signal")
    op.drop_table("citation_treatment_signal")
```

- [ ] **Step 6: Add the child model to the P3 tripwire** (`api/tests/test_transparency_invariants.py`)

Add the import and extend `_AUDIT_MODELS`:

```python
from app.models.citation_treatment_signal import CitationTreatmentSignal
# ... in _AUDIT_MODELS tuple, add:
    CitationTreatmentSignal,
```

- [ ] **Step 7: Register the model + run.** Ensure `CitationTreatmentSignal` is imported wherever models are collected for metadata (mirror how `CitationTreatment` is imported in `app/models/__init__.py` if such a file exists; otherwise the alembic env / conftest import path used by `0061`).

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/test_citation_treatment_signal_model.py tests/test_transparency_invariants.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add api/app/models/citation_treatment_signal.py api/app/models/citation_treatment.py \
        api/alembic/versions/0062_citation_treatment_signal.py \
        api/tests/test_transparency_invariants.py api/tests/test_citation_treatment_signal_model.py \
        api/app/models/__init__.py
git commit -s -m "feat(db): citation_treatment_signal child + rollup columns, mig 0062 (WS-G PR2)"
```

---

### Task 3: API — the treatment judge (`treatment_judge.py`)

**Files:**
- Create: `api/app/citation/treatment_judge.py`
- Test: `api/tests/test_treatment_judge.py`

**Interfaces:**
- Consumes: `build_judge_prompt` is NOT reused (new prompt); reuses `_JudgeGatewayProtocol`, `estimate_judge_call_cost_usd`, `_CONFIDENCE_MAP`, `ChatCompletionRequest`/`ChatCompletionMessage`.
- Produces:
  - `@dataclass TreatmentJudgment(classification: str, confidence: float, justification: str)`
  - `build_treatment_judge_prompt(*, cited_case_name: str, snippet: str) -> list[ChatCompletionMessage]`
  - `parse_treatment_response(response: Any) -> TreatmentJudgment | None`
  - `async judge_treatment(*, cited_case_name: str, snippet: str, gateway: _JudgeGatewayProtocol, judge_model: str) -> TreatmentJudgment | None`
  - `async estimate_treatment_cost_usd(db, *, judge_model: str) -> Decimal`
  - `TREATMENT_CLASSES`, `_TREATMENT_PURPOSE`

- [ ] **Step 1: Write failing tests** (`api/tests/test_treatment_judge.py`)

```python
import json
import pytest
from types import SimpleNamespace
from app.citation.treatment_judge import (
    TreatmentJudgment, build_treatment_judge_prompt, parse_treatment_response,
    judge_treatment, TREATMENT_CLASSES,
)


def _resp(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_prompt_includes_case_and_snippet():
    msgs = build_treatment_judge_prompt(cited_case_name="Smith v. Jones", snippet="We overrule Smith.")
    assert msgs[0].role == "system" and msgs[1].role == "user"
    assert "Smith v. Jones" in msgs[1].content and "We overrule Smith." in msgs[1].content


@pytest.mark.parametrize("cls", TREATMENT_CLASSES)
def test_parse_accepts_every_class(cls):
    out = parse_treatment_response(_resp(json.dumps(
        {"treatment": cls, "confidence": "high", "justification": "x"})))
    assert out == TreatmentJudgment(classification=cls, confidence=0.90, justification="x")


@pytest.mark.parametrize("bad", [
    "not json", json.dumps({"treatment": "bogus", "confidence": "high", "justification": "x"}),
    json.dumps({"treatment": "overruled", "confidence": "??", "justification": "x"}),
    json.dumps({"confidence": "high", "justification": "x"}),       # missing treatment
    json.dumps(["overruled"]),                                       # not a dict
    "",
])
def test_parse_returns_none_on_garbage(bad):
    assert parse_treatment_response(_resp(bad)) is None


def test_parse_none_on_no_choices():
    assert parse_treatment_response(SimpleNamespace(choices=[])) is None


@pytest.mark.asyncio
async def test_judge_treatment_swallows_gateway_error():
    class Boom:
        async def chat_completion(self, request, *, request_id=None):
            raise RuntimeError("down")
    assert await judge_treatment(
        cited_case_name="X", snippet="y", gateway=Boom(), judge_model="fast") is None


@pytest.mark.asyncio
async def test_judge_treatment_tags_purpose_and_parses():
    seen = {}
    class GW:
        async def chat_completion(self, request, *, request_id=None):
            seen["purpose"] = request.lq_ai_purpose
            seen["anonymize"] = request.anonymize
            return _resp(json.dumps({"treatment": "questioned", "confidence": "medium",
                                     "justification": "doubted it"}))
    out = await judge_treatment(cited_case_name="X", snippet="y", gateway=GW(), judge_model="fast")
    assert out == TreatmentJudgment("questioned", 0.70, "doubted it")
    assert seen["purpose"] == "judge_treatment" and seen["anonymize"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd api && python -m pytest tests/test_treatment_judge.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** (`api/app/citation/treatment_judge.py`)

```python
"""Treatment-classifying judge over a citing snippet (WS-G PR2).

A NEW judge prompt + verdict schema (the cascade judge speaks yes/partial/no;
this speaks the 7-class treatment taxonomy). Reuses the judge RAILS only:
the gateway protocol, the cost estimator, the _CONFIDENCE_MAP scale, and the
parse-or-skip discipline. The snippet is transient input — never persisted (P3).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.cost import estimate_judge_call_cost_usd
from app.citation.verification import _CONFIDENCE_MAP, _JudgeGatewayProtocol
from app.schemas.gateway import ChatCompletionMessage, ChatCompletionRequest

log = logging.getLogger(__name__)

TREATMENT_CLASSES = (
    "followed", "distinguished", "criticized",
    "questioned", "overruled", "superseded", "neutral",
)
_TREATMENT_PURPOSE = "judge_treatment"

_SYSTEM_PROMPT = """\
You are a Legal Treatment Classifier for a legal AI assistant.

You are given the NAME of a CITED case and a SNIPPET from a LATER opinion
that cites it. Classify how the later opinion TREATS the cited case, using
EXACTLY ONE of these labels:

* "overruled"    — the later court overrules/abrogates the cited case.
* "superseded"   — the cited case is superseded (e.g., by statute/rule).
* "criticized"   — the later court criticizes the cited case's reasoning.
* "questioned"   — the later court doubts/questions the cited case.
* "distinguished"— the later court distinguishes the cited case on its facts.
* "followed"     — the later court follows/applies the cited case favorably.
* "neutral"      — a bare citation with no discernible treatment signal.

Respond with STRICTLY VALID JSON in this exact shape:

  {"treatment": "<one label above>",
   "confidence": "high" | "medium" | "low",
   "justification": "<one or two sentences; DESCRIBE the treatment in your
                      own words — do NOT quote the opinion text>"}

CALIBRATION — IMPORTANT. When uncertain between a negative label
(overruled/superseded/criticized/questioned/distinguished) and "neutral",
choose "neutral". A false negative-treatment flag is worse than a missed
one. Only assert a negative label when the snippet clearly supports it.

Output ONLY the JSON object. No preamble, no markdown fencing."""


@dataclass(slots=True)
class TreatmentJudgment:
    classification: str
    confidence: float
    justification: str


def build_treatment_judge_prompt(*, cited_case_name: str, snippet: str) -> list[ChatCompletionMessage]:
    user = (
        f"CITED CASE:\n\"\"\"\n{cited_case_name}\n\"\"\"\n\n"
        f"SNIPPET FROM THE LATER (CITING) OPINION:\n\"\"\"\n{snippet}\n\"\"\"\n\n"
        "How does the later opinion treat the CITED CASE? Respond with the JSON object only."
    )
    return [
        ChatCompletionMessage(role="system", content=_SYSTEM_PROMPT),
        ChatCompletionMessage(role="user", content=user),
    ]


def parse_treatment_response(response: Any) -> TreatmentJudgment | None:
    try:
        choices = response.choices
        if not choices:
            return None
        content = choices[0].message.content
    except AttributeError:
        return None
    if not content:
        return None
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        log.info("treatment judge produced non-JSON", extra={"event": "treatment_judge_malformed"})
        return None
    if not isinstance(payload, dict):
        return None
    treatment = payload.get("treatment")
    confidence_label = payload.get("confidence")
    justification = payload.get("justification")
    if treatment not in TREATMENT_CLASSES:
        log.info("treatment judge unknown class %r", treatment,
                 extra={"event": "treatment_judge_unknown_class"})
        return None
    if confidence_label not in _CONFIDENCE_MAP:
        return None
    if not isinstance(justification, str) or not justification.strip():
        return None
    return TreatmentJudgment(
        classification=treatment,
        confidence=_CONFIDENCE_MAP[confidence_label],
        justification=justification.strip(),
    )


async def judge_treatment(
    *, cited_case_name: str, snippet: str,
    gateway: _JudgeGatewayProtocol, judge_model: str,
) -> TreatmentJudgment | None:
    request = ChatCompletionRequest(
        model=judge_model,
        messages=build_treatment_judge_prompt(cited_case_name=cited_case_name, snippet=snippet),
        max_tokens=400,
        temperature=0.0,
        anonymize=False,
        lq_ai_purpose=_TREATMENT_PURPOSE,
    )
    try:
        response = await gateway.chat_completion(request)
    except Exception as exc:
        log.warning("treatment judge gateway call failed: %r", exc,
                    extra={"event": "treatment_judge_error", "error_type": type(exc).__name__})
        return None
    return parse_treatment_response(response)


async def estimate_treatment_cost_usd(db: AsyncSession | None, *, judge_model: str) -> Decimal:
    """Per-call estimate. The snippet is short + bounded, so (unlike the
    whole-opinion judge) no opinion-length scaling is applied."""
    return await estimate_judge_call_cost_usd(db, judge_model=judge_model, purpose=_TREATMENT_PURPOSE)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd api && python -m pytest tests/test_treatment_judge.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add api/app/citation/treatment_judge.py api/tests/test_treatment_judge.py
git commit -s -m "feat(citation): treatment-classifying judge prompt+parser (WS-G PR2)"
```

---

### Task 4: API — the rollup (`treatment_rollup.py`)

**Files:**
- Create: `api/app/citation/treatment_rollup.py`
- Test: `api/tests/test_treatment_rollup.py`

**Interfaces:**
- Consumes: `TreatmentJudgment` (only `.classification`, `.confidence`).
- Produces:
  - `@dataclass Rollup(strongest_negative_class: str | None, per_class_counts: dict[str, int], case_confidence: float | None, judged_count: int)`
  - `roll_up(signals: Sequence[TreatmentJudgment]) -> Rollup`
  - `NEGATIVE_SEVERITY: tuple[str, ...]`

- [ ] **Step 1: Write failing tests** (`api/tests/test_treatment_rollup.py`)

```python
from app.citation.treatment_judge import TreatmentJudgment
from app.citation.treatment_rollup import roll_up, Rollup, NEGATIVE_SEVERITY


def _j(cls, conf=0.7):
    return TreatmentJudgment(classification=cls, confidence=conf, justification="x")


def test_severity_order_is_fixed():
    assert NEGATIVE_SEVERITY == ("overruled", "superseded", "criticized", "questioned", "distinguished")


def test_empty():
    r = roll_up([])
    assert r == Rollup(None, {}, None, 0)


def test_all_non_negative_has_no_strongest():
    r = roll_up([_j("followed"), _j("neutral"), _j("followed")])
    assert r.strongest_negative_class is None
    assert r.case_confidence is None
    assert r.per_class_counts == {"followed": 2, "neutral": 1}
    assert r.judged_count == 3


def test_picks_most_severe_negative():
    r = roll_up([_j("distinguished"), _j("questioned"), _j("overruled"), _j("followed")])
    assert r.strongest_negative_class == "overruled"
    assert r.per_class_counts["distinguished"] == 1


def test_corroboration_bumps_confidence():
    # two "questioned" @0.70 → 0.70 + 0.05*(2-1) = 0.75
    r = roll_up([_j("questioned", 0.70), _j("questioned", 0.70), _j("followed")])
    assert r.strongest_negative_class == "questioned"
    assert abs(r.case_confidence - 0.75) < 1e-9


def test_confidence_capped():
    sig = [_j("criticized", 0.90)] * 6  # 0.90 + 0.05*5 = 1.15 → cap 0.95
    r = roll_up(sig)
    assert abs(r.case_confidence - 0.95) < 1e-9


def test_confidence_uses_strongest_class_only():
    # strongest = overruled (one @0.50); the questioned ones don't corroborate it
    r = roll_up([_j("overruled", 0.50), _j("questioned", 0.90), _j("questioned", 0.90)])
    assert r.strongest_negative_class == "overruled"
    assert abs(r.case_confidence - 0.50) < 1e-9
```

- [ ] **Step 2: Run to verify failure**

Run: `cd api && python -m pytest tests/test_treatment_rollup.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** (`api/app/citation/treatment_rollup.py`)

```python
"""Roll per-passage treatment judgments up to a case-level signal (WS-G PR2).

Strongest-negative posture (ADR 0019 D5): the case-level signal is the most
SEVERE negative class present; confidence (D6) is that class's strongest
contributor confidence plus a small corroboration bump per additional
agreeing passage, capped. Absence of any negative class → None (surfaced as
"no negative treatment found as of <date>", never "good law"). Pure + total.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from app.citation.treatment_judge import TreatmentJudgment

# Strongest first.
NEGATIVE_SEVERITY: tuple[str, ...] = (
    "overruled", "superseded", "criticized", "questioned", "distinguished",
)
_CORROBORATION_BUMP = 0.05
_CONFIDENCE_CAP = 0.95


@dataclass(slots=True)
class Rollup:
    strongest_negative_class: str | None
    per_class_counts: dict[str, int]
    case_confidence: float | None
    judged_count: int


def roll_up(signals: Sequence[TreatmentJudgment]) -> Rollup:
    counts = Counter(s.classification for s in signals)
    per_class = dict(counts)
    strongest: str | None = next((c for c in NEGATIVE_SEVERITY if counts.get(c)), None)
    if strongest is None:
        return Rollup(None, per_class, None, len(signals))
    agreeing = [s.confidence for s in signals if s.classification == strongest]
    base = max(agreeing)
    bumped = base + _CORROBORATION_BUMP * (len(agreeing) - 1)
    confidence = min(bumped, _CONFIDENCE_CAP)
    return Rollup(strongest, per_class, confidence, len(signals))
```

- [ ] **Step 4: Run to verify pass**

Run: `cd api && python -m pytest tests/test_treatment_rollup.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/citation/treatment_rollup.py api/tests/test_treatment_rollup.py
git commit -s -m "feat(citation): treatment rollup (strongest-negative + corroboration) (WS-G PR2)"
```

---

### Task 5: API — judge pass in `derive_treatment_for_message`

**Files:**
- Modify: `api/app/citation/treatment.py`
- Test: `api/tests/test_treatment_judge_pass.py` (new)

**Interfaces:**
- Consumes: `judge_treatment`, `estimate_treatment_cost_usd`, `_TREATMENT_PURPOSE` (Task 3); `roll_up` (Task 4); `CitationTreatmentSignal` (Task 2); `_JudgeGatewayProtocol`.
- Produces: `derive_treatment_for_message(..., gateway: _JudgeGatewayProtocol | None = None, judge_model: str = "fast", judge_budget_usd: Decimal = TREATMENT_JUDGE_BUDGET_USD, n_judged_cap: int = N_JUDGED_CAP)`. When `gateway is None` → behavior byte-identical to PR1 (graph-only). The fetched `citing` snippets feed the judge; the **persisted** `citing_opinions` JSONB strips `snippet` (P3).

- [ ] **Step 1: Write failing integration tests** (`api/tests/test_treatment_judge_pass.py`)

```python
import uuid
from datetime import UTC, datetime
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.citation.treatment import derive_treatment_for_message
from app.citation.treatment_judge import TreatmentJudgment
from app.models.citation_treatment import CitationTreatment
from app.models.citation_treatment_signal import CitationTreatmentSignal

pytestmark = pytest.mark.asyncio

# Build: a message with one caselaw citation + ledger entry, cluster 7 / opinion 700.
# (Reuse the PR1 test's fixture helpers — import or copy _seed_caselaw_turn from
#  tests/test_treatment.py so the message_caselaw_citation + ledger entry exist.)
from tests.test_treatment import _seed_caselaw_turn  # noqa: E402


async def _fetch_with_snippets(opinion_id: int):
    return {
        "cited_by_count": 3,
        "citing": [
            {"cluster_id": 90, "opinion_id": 900, "case_name": "A", "court": "ca9",
             "date_filed": "2021-01-01", "snippet": "We overrule the cited case."},
            {"cluster_id": 91, "opinion_id": 901, "case_name": "B", "court": "ca2",
             "date_filed": "2020-01-01", "snippet": "Citing for background."},
        ],
    }


class _GW:
    """Returns 'overruled' for opinion 900's snippet, 'neutral' otherwise."""
    async def chat_completion(self, request, *, request_id=None):
        import json
        from types import SimpleNamespace
        body = request.messages[1].content
        cls = "overruled" if "overrule" in body else "neutral"
        conf = "high" if cls == "overruled" else "low"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({"treatment": cls, "confidence": conf, "justification": "x"})))])


async def test_judge_pass_writes_signals_and_rollup(db_session):
    msg_id = await _seed_caselaw_turn(db_session, cluster_id=7, opinion_id=700)
    await derive_treatment_for_message(
        db_session, message_id=msg_id, now=datetime.now(UTC),
        fetch_citing=_fetch_with_snippets, gateway=_GW(), judge_model="fast",
    )
    t = (await db_session.execute(
        select(CitationTreatment).where(CitationTreatment.cluster_id == 7)
    )).scalar_one()
    assert t.derived_method == "citation_graph+judge"
    assert t.strongest_negative_class == "overruled"
    assert t.judged_count == 2
    # P3: persisted refs carry NO snippet.
    assert all("snippet" not in ref for ref in t.citing_opinions)
    sigs = (await db_session.execute(
        select(CitationTreatmentSignal).where(CitationTreatmentSignal.treatment_id == t.id)
    )).scalars().all()
    assert {s.classification for s in sigs} == {"overruled", "neutral"}


async def test_graph_only_when_no_gateway(db_session):
    msg_id = await _seed_caselaw_turn(db_session, cluster_id=8, opinion_id=800)
    await derive_treatment_for_message(
        db_session, message_id=msg_id, now=datetime.now(UTC), fetch_citing=_fetch_with_snippets,
    )  # gateway omitted
    t = (await db_session.execute(
        select(CitationTreatment).where(CitationTreatment.cluster_id == 8)
    )).scalar_one()
    assert t.derived_method == "citation_graph"
    assert t.strongest_negative_class is None
    sigs = (await db_session.execute(select(CitationTreatmentSignal))).scalars().all()
    assert sigs == []


async def test_budget_stops_pass_but_keeps_graph(db_session):
    msg_id = await _seed_caselaw_turn(db_session, cluster_id=9, opinion_id=900)
    await derive_treatment_for_message(
        db_session, message_id=msg_id, now=datetime.now(UTC), fetch_citing=_fetch_with_snippets,
        gateway=_GW(), judge_model="fast", judge_budget_usd=Decimal("0"),  # zero budget
    )
    t = (await db_session.execute(
        select(CitationTreatment).where(CitationTreatment.cluster_id == 9)
    )).scalar_one()
    assert t.cited_by_count == 3              # graph survived
    assert t.derived_method == "citation_graph"  # no passages judged
    sigs = (await db_session.execute(select(CitationTreatmentSignal))).scalars().all()
    assert sigs == []


async def test_re_derive_replaces_signals(db_session):
    msg_id = await _seed_caselaw_turn(db_session, cluster_id=7, opinion_id=700)
    now = datetime.now(UTC)
    for _ in range(2):  # derive twice → no duplicate child rows, TTL forces refetch
        await derive_treatment_for_message(
            db_session, message_id=msg_id, now=now, fetch_citing=_fetch_with_snippets,
            gateway=_GW(), judge_model="fast", ttl_days=0,
        )
    sigs = (await db_session.execute(select(CitationTreatmentSignal))).scalars().all()
    assert len(sigs) == 2  # not 4
```

> If `_seed_caselaw_turn` does not already exist in `tests/test_treatment.py`, extract the turn-seeding setup from PR1's treatment test into that named helper as the first step of this task (it is shared fixture plumbing, not new behavior).

- [ ] **Step 2: Run to verify failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/test_treatment_judge_pass.py -v`
Expected: FAIL — `derive_treatment_for_message` rejects `gateway=` kwarg.

- [ ] **Step 3: Implement.** Extend `treatment.py`:

1. Imports + constants at module top:

```python
from decimal import Decimal

from app.citation.treatment_judge import (
    _TREATMENT_PURPOSE, estimate_treatment_cost_usd, judge_treatment,
)
from app.citation.treatment_rollup import roll_up
from app.citation.verification import _JudgeGatewayProtocol
from app.models.citation_treatment_signal import CitationTreatmentSignal

N_JUDGED_CAP = 10
TREATMENT_JUDGE_BUDGET_USD = Decimal("0.25")


def _strip_snippet(citing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist refs only — the snippet is transient judge input (P3)."""
    return [{k: v for k, v in ref.items() if k != "snippet"} for ref in citing]
```

2. New signature (add the four kwargs, defaulting to PR1 behavior):

```python
async def derive_treatment_for_message(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    now: datetime,
    ttl_days: int = TREATMENT_TTL_DAYS,
    fetch_citing: _FetchCiting = _default_fetch_citing,
    gateway: _JudgeGatewayProtocol | None = None,
    judge_model: str = "fast",
    judge_budget_usd: Decimal = TREATMENT_JUDGE_BUDGET_USD,
    n_judged_cap: int = N_JUDGED_CAP,
) -> int:
```

3. In the per-cluster loop, when building/refreshing the row, **strip the snippet** from the persisted JSONB and keep the raw `payload["citing"]` (with snippets) in a local for the judge pass:

```python
            payload = await fetch_citing(opinion_id)
            raw_citing = list(payload.get("citing") or [])
            persisted_citing = _strip_snippet(raw_citing)
            # ... use persisted_citing for row.citing_opinions / existing.citing_opinions
```

   Replace both `list(payload.get("citing") or [])` assignments to `citing_opinions` with `persisted_citing`.

4. After the row is upserted and flushed (so `row.id` exists), run the judge pass **only when `gateway is not None`**, in the same loop iteration, capturing `treatment_row` (the new or existing `CitationTreatment`):

```python
            if gateway is not None:
                await _run_judge_pass(
                    db, treatment_row=treatment_row, cited_case_name=<case_name>,
                    raw_citing=raw_citing, now=now, gateway=gateway,
                    judge_model=judge_model, judge_budget_usd=judge_budget_usd,
                    n_judged_cap=n_judged_cap,
                )
```

   `<case_name>`: load `ResearchClusterMetadata.case_name` by `cluster_id` (mirror B1c, which reads `ResearchClusterMetadata.case_name`). If unavailable, fall back to the citing ref's own context — but the cited case name is required for the prompt; if it cannot be resolved, skip the judge pass for that cluster (graph signal stands).

5. New helper `_run_judge_pass`:

```python
async def _run_judge_pass(
    db: AsyncSession,
    *,
    treatment_row: CitationTreatment,
    cited_case_name: str,
    raw_citing: list[dict[str, Any]],
    now: datetime,
    gateway: _JudgeGatewayProtocol,
    judge_model: str,
    judge_budget_usd: Decimal,
    n_judged_cap: int,
) -> None:
    """Judge top-N citing snippets, write child signals + rollup. Non-fatal per passage."""
    # Idempotent refresh: clear this row's prior signals.
    await db.execute(
        delete(CitationTreatmentSignal).where(
            CitationTreatmentSignal.treatment_id == treatment_row.id
        )
    )
    per_call = await estimate_treatment_cost_usd(db, judge_model=judge_model)
    spent = Decimal("0")
    judgments = []
    # raw_citing is already recency-sorted; take the cap.
    for ref in raw_citing[:n_judged_cap]:
        snippet = ref.get("snippet")
        citing_opinion_id = ref.get("opinion_id")
        if not snippet or citing_opinion_id is None:
            continue
        if spent + per_call > judge_budget_usd:
            break  # budget exhausted — keep what we judged
        spent += per_call
        try:
            judgment = await judge_treatment(
                cited_case_name=cited_case_name, snippet=snippet,
                gateway=gateway, judge_model=judge_model,
            )
        except Exception as exc:  # defense in depth; judge_treatment already swallows
            log.warning("treatment judge raised for opinion %s: %r", citing_opinion_id, exc)
            continue
        if judgment is None:
            continue
        db.add(CitationTreatmentSignal(
            treatment_id=treatment_row.id, citing_opinion_id=int(citing_opinion_id),
            classification=judgment.classification, confidence=judgment.confidence,
            justification=judgment.justification,
        ))
        judgments.append(judgment)
    if not judgments:
        return  # nothing classified — leave graph-only
    rollup = roll_up(judgments)
    treatment_row.strongest_negative_class = rollup.strongest_negative_class
    treatment_row.judged_count = rollup.judged_count
    treatment_row.judge_as_of = now
    treatment_row.derived_method = "citation_graph+judge"
    await db.flush()
```

   Add `from sqlalchemy import delete, select` (extend the existing import). Track `treatment_row` in the loop: set it to the `row`/`existing` object on each branch so it is in scope for the judge pass. When a cluster reuses a fresh cache (the `existing.as_of >= stale_before` continue branch), do not re-run the judge pass (the cached row already carries its judged signals).

- [ ] **Step 4: Run to verify pass**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/test_treatment_judge_pass.py tests/test_treatment.py -v`
Expected: PASS (new + PR1 regression).

- [ ] **Step 5: Commit**

```bash
git add api/app/citation/treatment.py api/tests/test_treatment_judge_pass.py api/tests/test_treatment.py
git commit -s -m "feat(citation): judge pass + rollup in derive_treatment_for_message (WS-G PR2)"
```

---

### Task 6: Worker — thread gateway + judge model (graph-only degrade)

**Files:**
- Modify: `api/app/workers/treatment_worker.py`
- Test: `api/tests/test_treatment_worker.py` (extend or create)

**Interfaces:**
- Consumes: `derive_treatment_for_message(gateway=, judge_model=)` (Task 5); `get_gateway_client`, `GatewayClient.get_citation_engine_judge_model`.
- Produces: `run_treatment_derivation` resolves a gateway + judge model and passes them; on any resolution failure → graph-only (gateway=None). A `gateway` kwarg allows test injection.

- [ ] **Step 1: Write failing tests** (`api/tests/test_treatment_worker.py`)

```python
import uuid
import pytest
from app.workers import treatment_worker

pytestmark = pytest.mark.asyncio


async def test_run_resolves_gateway_and_passes_it(db_session, monkeypatch):
    captured = {}
    async def fake_derive(db, *, message_id, now, fetch_citing=None, gateway=None, judge_model="fast"):
        captured["gateway"] = gateway
        captured["judge_model"] = judge_model
        return 0
    monkeypatch.setattr(treatment_worker, "derive_treatment_for_message", fake_derive)

    class GW:
        async def get_citation_engine_judge_model(self, *, fallback="fast"):
            return "balanced"
    await treatment_worker.run_treatment_derivation(db_session, message_id=uuid.uuid4(), gateway=GW())
    assert isinstance(captured["gateway"], GW)
    assert captured["judge_model"] == "balanced"


async def test_run_degrades_to_graph_only_on_gateway_failure(db_session, monkeypatch):
    captured = {}
    async def fake_derive(db, *, message_id, now, fetch_citing=None, gateway=None, judge_model="fast"):
        captured["gateway"] = gateway
        return 0
    monkeypatch.setattr(treatment_worker, "derive_treatment_for_message", fake_derive)

    class BadGW:
        async def get_citation_engine_judge_model(self, *, fallback="fast"):
            raise RuntimeError("no gateway config")
    await treatment_worker.run_treatment_derivation(db_session, message_id=uuid.uuid4(), gateway=BadGW())
    assert captured["gateway"] is None  # degraded
```

- [ ] **Step 2: Run to verify failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/test_treatment_worker.py -v`
Expected: FAIL — `run_treatment_derivation` has no `gateway` kwarg.

- [ ] **Step 3: Implement** (`treatment_worker.py`)

```python
from app.clients.gateway import GatewayClient, get_gateway_client


async def run_treatment_derivation(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    fetch_citing: _FetchCiting = _default_fetch_citing,
    gateway: GatewayClient | None = None,
) -> int:
    """Resolve a gateway + judge model for the PR2 judge pass; degrade to
    graph-only if the gateway/judge-model can't be resolved (worker without
    gateway config). Then derive + commit."""
    resolved_gateway = gateway if gateway is not None else get_gateway_client()
    judge_model = "fast"
    try:
        judge_model = await resolved_gateway.get_citation_engine_judge_model()
    except Exception as exc:
        log.warning("treatment judge-model resolve failed; graph-only: %r", exc,
                    extra={"event": "treatment_judge_model_unavailable"})
        resolved_gateway = None

    linked = await derive_treatment_for_message(
        db, message_id=message_id, now=datetime.now(UTC),
        fetch_citing=fetch_citing, gateway=resolved_gateway, judge_model=judge_model,
    )
    await db.commit()
    return linked
```

> Keep `treatment_derivation_job` unchanged — it calls `run_treatment_derivation(db, message_id=...)`, which now self-resolves the gateway.

- [ ] **Step 4: Run to verify pass**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/test_treatment_worker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/workers/treatment_worker.py api/tests/test_treatment_worker.py
git commit -s -m "feat(worker): resolve gateway+judge model for treatment judge pass (WS-G PR2)"
```

---

### Task 7: Read path — expose rollup + signals on `/chats/{id}/ledger`

**Files:**
- Modify: `api/app/citation/ledger.py` (`resolve_ledger_entries`, the `treatment` object builder)
- Test: `api/tests/test_ledger_treatment_read.py` (new) — and extend the existing ledger read test if one asserts the `treatment` shape.

**Interfaces:**
- Consumes: `CitationTreatmentSignal`, `CitationTreatment` rollup columns; `roll_up` (for per-class counts + confidence at read time).
- Produces: the `treatment` dict each caselaw ledger entry exposes gains:
  `strongest_negative_class`, `judged_count`, `judge_as_of`, `per_class_counts: dict[str,int]`, `case_confidence: float | None`, and `signals: list[{citing_opinion_id, classification, confidence, justification}]`. Batch-loaded by `treatment_id` (no N+1). Graph-only rows return the new keys as null/empty.

- [ ] **Step 1: Write failing test** (`api/tests/test_ledger_treatment_read.py`)

```python
import pytest
pytestmark = pytest.mark.asyncio
# Seed a turn whose ledger resolves to a treatment with judged signals
# (reuse Task 5's fetch/_GW + _seed_caselaw_turn), then call the same
# resolve_ledger_entries path the GET /chats/{id}/ledger handler uses.
from app.citation.ledger import resolve_ledger_entries  # adjust to the real entry point


async def test_ledger_exposes_treatment_rollup_and_signals(db_session):
    # ... seed + derive (gateway=_GW) as in Task 5, get message_id ...
    entries = await resolve_ledger_entries(db_session, message_id=msg_id)  # match real signature
    caselaw = [e for e in entries if e["source_kind"] == "caselaw"][0]
    t = caselaw["treatment"]
    assert t["strongest_negative_class"] == "overruled"
    assert t["per_class_counts"]["overruled"] == 1
    assert isinstance(t["case_confidence"], float)
    assert any(s["classification"] == "overruled" for s in t["signals"])
    assert all("snippet" not in s for s in t["signals"])  # P3
```

> Match the real `resolve_ledger_entries` signature + return shape (it returns the resolved entry objects/dicts with a `treatment` key from PR1). Adjust the assertions' access pattern to the actual shape; keep the asserted *fields*.

- [ ] **Step 2: Run to verify failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/test_ledger_treatment_read.py -v`
Expected: FAIL — `treatment` dict lacks the rollup/signals keys.

- [ ] **Step 3: Implement.** In `ledger.py` where PR1 builds the per-entry `treatment` object:

1. Batch-load signals for all resolved `treatment_id`s once:

```python
    from app.citation.treatment_judge import TreatmentJudgment
    from app.citation.treatment_rollup import roll_up
    from app.models.citation_treatment_signal import CitationTreatmentSignal

    signal_rows = (await db.execute(
        select(CitationTreatmentSignal).where(
            CitationTreatmentSignal.treatment_id.in_(treatment_ids)
        )
    )).scalars().all() if treatment_ids else []
    signals_by_treatment: dict[uuid.UUID, list[CitationTreatmentSignal]] = {}
    for s in signal_rows:
        signals_by_treatment.setdefault(s.treatment_id, []).append(s)
```

2. When building each `treatment` dict, add the rollup + signals:

```python
        sigs = signals_by_treatment.get(treatment.id, [])
        rollup = roll_up([
            TreatmentJudgment(classification=s.classification, confidence=s.confidence,
                              justification=s.justification)
            for s in sigs
        ])
        treatment_obj.update({
            "strongest_negative_class": treatment.strongest_negative_class,
            "judged_count": treatment.judged_count,
            "judge_as_of": treatment.judge_as_of.isoformat() if treatment.judge_as_of else None,
            "per_class_counts": rollup.per_class_counts,
            "case_confidence": rollup.case_confidence,
            "signals": [
                {"citing_opinion_id": s.citing_opinion_id, "classification": s.classification,
                 "confidence": s.confidence, "justification": s.justification}
                for s in sigs
            ],
        })
```

   `treatment_ids` = the set of non-null `treatment_id`s already gathered when PR1 batch-loads `CitationTreatment`. Reuse that collection; do not add a second pass.

- [ ] **Step 4: Run to verify pass + full citation/ledger regression**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest tests/test_ledger_treatment_read.py tests/test_ledger.py tests/test_treatment.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/citation/ledger.py api/tests/test_ledger_treatment_read.py
git commit -s -m "feat(citation): expose treatment rollup + signals on ledger read (WS-G PR2)"
```

---

## Final gate (run before requesting review — the CI LESSON)

- [ ] **api full gates (whole-app, not per-file):**
```bash
cd api
ruff check app tests && ruff format --check app tests
mypy app
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test python -m pytest -q
```
- [ ] **gateway full gates:**
```bash
cd gateway
ruff check app tests && ruff format --check app tests
mypy app --strict
python -m pytest -q
```
- [ ] **OpenAPI conformance** if the `/ledger` response schema is pinned in `docs/api/backend-openapi.yaml` — update the `treatment` object schema there and run `tests/test_openapi.py`. (The ledger response is an object; adding keys is additive — confirm the schema test still passes.)
- [ ] **PRD / DE bookkeeping:** the DE-344 PRD entry is updated (this PR) to pin its remaining autonomous-`estimate_tool_cost`/R4 scope to **WS-E** (its first-metered-source trigger) and record that PR2 shipped the per-case judge budget portion. Confirm that edit is on the branch. File **DE-365** if the court-seniority re-rank or whole-opinion low-confidence fallback warrants its own tracked item.
- [ ] **Opus whole-branch review** (SDD final): it has caught a real gate-passing defect on every slice this milestone. Required before PR.

## Plan self-review (completed)

- **Spec coverage:** §1 in-scope items → Tasks 1–7; snippet localization (§2) → Task 1+5 (`_strip_snippet`); P3 ruling → Task 2 (tripwire) + Task 5 (`_strip_snippet`) + Task 7 (no-snippet assertion); taxonomy/rollup (§3.3) → Task 4; new judge (§3.4) → Task 3; schema (§3.5) → Task 2; worker (§3.4 wiring) → Task 6; read (§3.6) → Task 7; budget/DE-344 (§3.1/§6) → Task 5 budget + Global Constraints scope note. Deferred items (escalation, court-rank, whole-opinion fallback, trace UI) explicitly out.
- **Placeholder scan:** all steps carry real code/commands. The two "match the real signature" notes (Tasks 5 helper `_seed_caselaw_turn`, Task 7 `resolve_ledger_entries`) are integration points against existing PR1 code, with the asserted contract fixed — not placeholders.
- **Type consistency:** `TreatmentJudgment(classification, confidence, justification)`, `roll_up → Rollup`, `derive_treatment_for_message(gateway=, judge_model=, judge_budget_usd=, n_judged_cap=)`, `_TREATMENT_PURPOSE='judge_treatment'`, severity tuple, and the 7-class CHECK are identical across Tasks 2–7.
