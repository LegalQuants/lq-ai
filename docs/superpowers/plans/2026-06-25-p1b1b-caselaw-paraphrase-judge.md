# P1-B1b — Caselaw paraphrase/content judge (SUPPORTED-only) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a non-verbatim caselaw blockquote that a whole-opinion judge finds faithfully supported a `paraphrase_judge` row (gate → `supported_only`), cost-bounded, **additive-only** (no FAIL/unverified rows).

**Architecture:** A new `case_content_judge.py` runs a whole-opinion fidelity judge over the already-stored opinion text via the existing `_JudgeGatewayProtocol`, reusing the cascade's judge-response parser. A per-message cost pre-flight bounds egress. `caselaw.py` gains a `gateway` param: after the verbatim loop, dropped passages are judged (cost-gated) and a SUPPORTED row is written on accept. A migration relaxes the caselaw method CHECK. No change to the gate or the ledger assembler.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic (migration 0060), pytest with a **mocked gateway** (no live egress), throwaway pgvector.

## Global Constraints

- **Additive-only (load-bearing invariant).** B1b writes **only** `verified=True, verification_method='paraphrase_judge'` rows. It never writes a FAIL/unverified caselaw row and never flips a turn that is `fiduciary_grade`/`supported_only` today into `flagged`. Caselaw FAIL is P1-B1c. A passage no consulted opinion's judge accepts stays **dropped** (unchanged from today).
- **Whole-opinion judge.** Feed the judge the full opinion text + the candidate passage (a dropped passage has no located span, so the cascade's ±200-char window doesn't apply). Same `_JudgeGatewayProtocol` surface (`chat_completion`) as stage-3.
- **Per-message cost budget bounds spend.** Estimate each judge call's cost; accumulate per turn against a configured cap (`CASE_CONTENT_JUDGE_BUDGET_USD`). When the next call would exceed it, **stop judging this turn** (remaining passages drop) — no special row.
- **Conservative parse.** Malformed judge output → `_MISS` (no row). A per-opinion gateway error → "no verdict" for that opinion (logged), never fatal.
- **`gateway=None` is unchanged behaviour.** Verbatim-only, deterministic, no egress, no cost — preserves every existing caller/test.
- **No gate / ledger change.** The gate already buckets `paraphrase_judge`→SUPPORTED; `assemble_ledger_entries` already maps the method. Do not touch `gate.py` or `ledger.py`.
- **P5:** persistence flushes (the existing `verify_and_persist_caselaw_citations` already flushes; do not add a commit).
- **Migration:** new revision `0060`, `down_revision="0059"`. NEVER host `alembic upgrade` the dev DB; the conftest auto-migrates the throwaway pgvector. Register nothing new (no new model — only a CHECK change).
- **Offsets for a paraphrase row:** a paraphrase has no exact span; store the **whole-opinion span** `source_offset_start=0, source_offset_end=len(opinion_text)`, `partial=True` (satisfies the `offset_end > offset_start` CHECK; the trace reads "supported by this opinion," not a false exact locus).
- **Security review (CODEOWNERS):** `api/app/citation/**` + `chats.py` + new egress — do not self-merge.
- **Tests:** host venv + throwaway pgvector (`DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test`); mocked gateway → no `-m provider`. `ruff format` + `ruff check` + `mypy app` + `pytest`. **Next migration = 0060.**
- **Commits:** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: `case_content_judge.py` — whole-opinion judge + cost pre-flight

**Files:**
- Create: `api/app/citation/case_content_judge.py`
- Modify: `api/app/citation/cost.py` (generalize `estimate_judge_call_cost_usd` with a `purpose` param)
- Test: `api/tests/test_case_content_judge.py` (unit, mocked gateway)

**Interfaces:**
- Consumes: `verify` internals from `verification.py` — `VerificationResult`, `_MISS`, `_parse_judge_response`, `_JudgeGatewayProtocol`, and the `ChatCompletionRequest` shape used by `verify_paraphrase`; `estimate_judge_call_cost_usd` from `cost.py`.
- Produces: `async def judge_case_content(*, passage: str, opinion_text: str, gateway, judge_model: str) -> VerificationResult`; `async def estimate_case_content_cost_usd(db, *, judge_model: str, opinion_text: str) -> Decimal`; constants `CHARS_PER_TOKEN`, `TYPICAL_PARAPHRASE_TOKENS`, `CASE_CONTENT_JUDGE_BUDGET_USD`. Consumed by Task 3.

- [ ] **Step 1: Generalize the cost estimator.** In `api/app/citation/cost.py`, change `estimate_judge_call_cost_usd` to accept `purpose` (default preserves today's behaviour):

```python
async def estimate_judge_call_cost_usd(
    db: AsyncSession | None,
    *,
    judge_model: str,
    purpose: str = "judge_paraphrase",
) -> Decimal:
    ...
    # in the WHERE clause, replace the literal with the param:
    #   InferenceRoutingLog.purpose == purpose,
```

Existing callers pass no `purpose` → unchanged. (Confirm the one query predicate at ~line 143 now uses the `purpose` variable.)

- [ ] **Step 2: Write the failing judge test** `api/tests/test_case_content_judge.py` (mock the gateway — a fake with `async def chat_completion(...)` returning a canned judge response; mirror how `verification.py`'s paraphrase tests mock the judge — read an existing `verify_paraphrase` test for the exact fake-gateway shape and the judge-response JSON the parser expects):

```python
import pytest
from decimal import Decimal
from app.citation.case_content_judge import (
    judge_case_content, estimate_case_content_cost_usd, CHARS_PER_TOKEN,
)

pytestmark = pytest.mark.unit


class _FakeGateway:
    def __init__(self, verdict_json: str):
        self._verdict = verdict_json
        self.calls = 0
    async def chat_completion(self, request, *, request_id=None):
        self.calls += 1
        # shape this to match what _parse_judge_response reads (see verify_paraphrase tests)
        return _judge_completion(self._verdict)


@pytest.mark.asyncio
async def test_accept_yields_paraphrase_judge():
    gw = _FakeGateway(verdict='{"verdict":"yes","confidence":"high"}')
    r = await judge_case_content(passage="The court held X.", opinion_text="...full opinion...", gateway=gw, judge_model="fast")
    assert r.verified is True
    assert r.method == "paraphrase_judge"
    assert gw.calls == 1


@pytest.mark.asyncio
async def test_reject_yields_miss():
    gw = _FakeGateway(verdict='{"verdict":"no"}')
    r = await judge_case_content(passage="Fabricated holding.", opinion_text="...", gateway=gw, judge_model="fast")
    assert r.verified is False
    assert r.method is None


@pytest.mark.asyncio
async def test_malformed_output_is_miss():
    gw = _FakeGateway(verdict="not json at all")
    r = await judge_case_content(passage="x", opinion_text="...", gateway=gw, judge_model="fast")
    assert r.verified is False


@pytest.mark.asyncio
async def test_prompt_includes_opinion_and_passage(monkeypatch):
    captured = {}
    class _CapGW:
        async def chat_completion(self, request, *, request_id=None):
            captured["request"] = request
            return _judge_completion('{"verdict":"yes","confidence":"medium"}')
    await judge_case_content(passage="UNIQUE_PASSAGE", opinion_text="UNIQUE_OPINION_BODY", gateway=_CapGW(), judge_model="fast")
    text = _serialize_messages(captured["request"])  # helper: concat message contents
    assert "UNIQUE_PASSAGE" in text and "UNIQUE_OPINION_BODY" in text


@pytest.mark.asyncio
async def test_cost_estimate_scales_with_opinion_length():
    short = await estimate_case_content_cost_usd(None, judge_model="fast", opinion_text="x" * 1000)
    long = await estimate_case_content_cost_usd(None, judge_model="fast", opinion_text="x" * (1000 * CHARS_PER_TOKEN * 50))
    assert long > short
```

(The `_judge_completion` / `_serialize_messages` helpers + the exact judge-response JSON shape come from the existing paraphrase-judge tests — read `api/tests/` for the cascade's judge test to reuse them verbatim.)

- [ ] **Step 3: Run it (fails)** — `cd api && DATABASE_URL=... .venv/bin/pytest tests/test_case_content_judge.py -v` → FAIL (module missing).

- [ ] **Step 4: Implement** `api/app/citation/case_content_judge.py`:

```python
"""Whole-opinion caselaw content judge (DE-280, P1-B1b).

For a caselaw blockquote that did not match any consulted opinion verbatim,
ask an LLM judge whether the passage is faithfully supported by the *whole*
opinion text (10-50pp) — the SUPPORTED tier. Reuses the cascade's judge
surface (``_JudgeGatewayProtocol``) and response parser; conservative bias
(a false-positive verification is worse than a false-negative). Cost-bounded
by a per-message budget enforced in the caselaw orchestrator.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.citation.cost import estimate_judge_call_cost_usd
from app.citation.verification import (
    VerificationResult,
    _MISS,
    _parse_judge_response,
    _JudgeGatewayProtocol,
)
# reuse the ChatCompletionRequest construction pattern from verify_paraphrase.

log = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4
TYPICAL_PARAPHRASE_TOKENS = 1500  # stage-3 chunk+window baseline the calibration reflects
CASE_CONTENT_JUDGE_BUDGET_USD = Decimal("0.25")  # per assistant turn; config constant in v1
_PURPOSE = "judge_case_content"


def _build_prompt(passage: str, opinion_text: str): ...
    # Build the same ChatCompletionRequest shape verify_paraphrase uses, but:
    #  - system/user content asks: "Is the PASSAGE faithfully supported by the
    #    OPINION (same holding/quote, not a distortion)? Answer the judge schema."
    #  - include the WHOLE opinion_text (not a ±200-char window) + the passage.
    #  - carry purpose=_PURPOSE so the inference is logged as judge_case_content
    #    (follow how verify_paraphrase tags purpose on its request).


async def judge_case_content(
    *, passage: str, opinion_text: str, gateway: _JudgeGatewayProtocol, judge_model: str
) -> VerificationResult:
    try:
        request = _build_prompt(passage, opinion_text)
        response = await gateway.chat_completion(request)
    except Exception as exc:  # gateway/transport error -> no verdict
        log.warning("case-content judge call failed: %r", exc)
        return _MISS
    result = _parse_judge_response(response)  # -> VerificationResult(method="paraphrase_judge"...) or _MISS
    return result


async def estimate_case_content_cost_usd(
    db: AsyncSession | None, *, judge_model: str, opinion_text: str
) -> Decimal:
    per_call = await estimate_judge_call_cost_usd(db, judge_model=judge_model, purpose=_PURPOSE)
    opinion_tokens = max(1, len(opinion_text) // CHARS_PER_TOKEN)
    scale = Decimal(opinion_tokens) / Decimal(TYPICAL_PARAPHRASE_TOKENS)
    if scale < 1:
        scale = Decimal(1)
    return per_call * scale
```

> **Implementer:** `_parse_judge_response` must return `method="paraphrase_judge"` for this judge too (it is method-agnostic — it parses the verdict; confirm by reading it). If it hard-codes a method, pass/override the method to `"paraphrase_judge"`. Read `verify_paraphrase` for the exact `ChatCompletionRequest` construction + how `purpose`/`judge_model` are threaded, and reuse it in `_build_prompt`.

- [ ] **Step 5: Run the tests (pass)** — `cd api && DATABASE_URL=... .venv/bin/pytest tests/test_case_content_judge.py -v` → all PASS.

- [ ] **Step 6: Lint + type, commit**

```bash
cd api && .venv/bin/ruff format app/citation/case_content_judge.py app/citation/cost.py tests/test_case_content_judge.py && .venv/bin/ruff check app/citation tests/test_case_content_judge.py && .venv/bin/mypy app/citation/case_content_judge.py app/citation/cost.py
```
```bash
git add api/app/citation/case_content_judge.py api/app/citation/cost.py api/tests/test_case_content_judge.py
git commit -s -m "feat(citation): whole-opinion caselaw content judge + cost estimate (P1-B1b)

judge_case_content runs an LLM fidelity judge over the full opinion text
(DE-280) reusing the cascade judge surface + parser; accept ->
paraphrase_judge, reject/malformed -> MISS. estimate_case_content_cost_usd
scales the per-judge cost by opinion length; estimate_judge_call_cost_usd
gains a purpose param (judge_case_content) for segregated calibration.

Refs ADR 0018 D2, DE-280.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Migration 0060 — relax the caselaw method CHECK

**Files:**
- Create: `api/alembic/versions/0060_caselaw_method_paraphrase.py`
- Modify: `api/app/models/message_caselaw_citation.py` (CHECK string)
- Test: `api/tests/integration/test_caselaw_paraphrase_method.py`

**Interfaces:** none new — schema only.

- [ ] **Step 1: Write the failing test** `api/tests/integration/test_caselaw_paraphrase_method.py`:

```python
import uuid
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.chat import Chat, Message
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.user import User

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def msg(db_session):
    u = User(email=f"cm-{uuid.uuid4().hex[:8]}@e.com", hashed_password="x", role="member")
    db_session.add(u); await db_session.flush()
    c = Chat(owner_id=u.id, title="t"); db_session.add(c); await db_session.flush()
    m = Message(chat_id=c.id, role="assistant", kind="ai", content="a"); db_session.add(m); await db_session.flush()
    return m.id


@pytest.mark.asyncio
async def test_paraphrase_judge_method_accepted(db_session, msg):
    db_session.add(MessageCaselawCitation(
        message_id=msg, opinion_id=1, cluster_id=1, source_offset_start=0, source_offset_end=10,
        source_text="held that", verified=True, verification_method="paraphrase_judge",
        verification_confidence=0.7, partial=True))
    await db_session.flush()  # must NOT raise


@pytest.mark.asyncio
async def test_bogus_method_rejected(db_session, msg):
    db_session.add(MessageCaselawCitation(
        message_id=msg, opinion_id=1, cluster_id=1, source_offset_start=0, source_offset_end=10,
        source_text="x", verified=True, verification_method="made_up", verification_confidence=0.5))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
```

- [ ] **Step 2: Run it (fails)** — the `paraphrase_judge` insert raises `IntegrityError` against the current CHECK. `cd api && DATABASE_URL=... .venv/bin/pytest tests/integration/test_caselaw_paraphrase_method.py -v` → first test FAILs.

- [ ] **Step 3: Update the model** `api/app/models/message_caselaw_citation.py` CHECK:

```python
        CheckConstraint(
            "verification_method IS NULL OR verification_method IN "
            "('exact_match', 'tolerant_match', 'paraphrase_judge')",
            name="chk_message_caselaw_citations_method_values",
        ),
```

- [ ] **Step 4: Create migration** `api/alembic/versions/0060_caselaw_method_paraphrase.py`:

```python
"""relax message_caselaw_citations method CHECK to allow paraphrase_judge (P1-B1b)

Revision ID: 0060
Revises: 0059
"""
from __future__ import annotations
from collections.abc import Sequence
from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "chk_message_caselaw_citations_method_values"
_TABLE = "message_caselaw_citations"


def upgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(
        _NAME, _TABLE,
        "verification_method IS NULL OR verification_method IN "
        "('exact_match', 'tolerant_match', 'paraphrase_judge')",
    )


def downgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(
        _NAME, _TABLE,
        "verification_method IS NULL OR verification_method IN ('exact_match', 'tolerant_match')",
    )
```

- [ ] **Step 5: Run the tests (pass)** — `cd api && DATABASE_URL=... .venv/bin/pytest tests/integration/test_caselaw_paraphrase_method.py -v` → both PASS (conftest auto-applies 0060).

- [ ] **Step 6: Lint + commit**

```bash
cd api && .venv/bin/ruff format app/models/message_caselaw_citation.py alembic/versions/0060_caselaw_method_paraphrase.py tests/integration/test_caselaw_paraphrase_method.py && .venv/bin/ruff check app/models alembic/versions/0060_caselaw_method_paraphrase.py tests/integration/test_caselaw_paraphrase_method.py
```
```bash
git add api/app/models/message_caselaw_citation.py api/alembic/versions/0060_caselaw_method_paraphrase.py api/tests/integration/test_caselaw_paraphrase_method.py
git commit -s -m "feat(citation): migration 0060 — allow paraphrase_judge on caselaw citations (P1-B1b)

Refs ADR 0018 D2.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `caselaw.py` orchestration + thread the gateway at finalize

**Files:**
- Modify: `api/app/citation/caselaw.py` (gateway param + SUPPORTED judge pass)
- Modify: `api/app/api/chats.py` (pass `gateway=gateway` at the two caselaw finalize sites — ~lines 2920, 3503)
- Test: `api/tests/integration/test_caselaw_paraphrase_judge.py`

**Interfaces:**
- Consumes: `judge_case_content`, `estimate_case_content_cost_usd`, `CASE_CONTENT_JUDGE_BUDGET_USD` (Task 1).

- [ ] **Step 1: Write the failing integration tests** `api/tests/integration/test_caselaw_paraphrase_judge.py` (real Postgres, mocked judge; reuse P1-A1's `test_caselaw_citations.py` seeding of `ResearchOpinionMetadata` + the `load_opinion_text` injection point — read it for the exact fixture shape):

```python
# Cover (using the existing caselaw test fixtures + an injected load_opinion_text):
# 1. A paraphrased blockquote (not verbatim) + a mocked judge that ACCEPTS ->
#    exactly one MessageCaselawCitation with verification_method='paraphrase_judge',
#    verified=True, offsets (0, len(opinion)), partial=True. assemble_ledger_entries
#    + compute_and_record_gate -> gate_status == 'supported_only'.
# 2. A mocked judge that REJECTS all consulted opinions -> NO row written (drop),
#    gate unaffected (additive-only invariant).
# 3. Budget set below one call's estimate (monkeypatch CASE_CONTENT_JUDGE_BUDGET_USD
#    to Decimal('0')) -> the judge mock is NEVER called and NO row is written.
# 4. gateway=None -> behaves exactly as today (verbatim path only; no judge, no rows).
```

(Write these out fully against the real `verify_and_persist_caselaw_citations` signature + a `_FakeGateway` whose `chat_completion` returns accept/reject, plus a `load_opinion_text` stub returning a known opinion body. Assert the mock's call count for cases 3–4.)

- [ ] **Step 2: Run (fails)** — judge pass not implemented → no `paraphrase_judge` rows. `cd api && DATABASE_URL=... .venv/bin/pytest tests/integration/test_caselaw_paraphrase_judge.py -v` → FAIL.

- [ ] **Step 3: Implement the orchestration** in `api/app/citation/caselaw.py`. Add params and, after the existing verbatim loop, a SUPPORTED judge pass over passages that produced no row. Keep the verbatim loop unchanged; track which passages remain unverified.

```python
async def verify_and_persist_caselaw_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    assistant_text: str,
    tool_sources: Sequence[ToolSourceRecord],
    load_opinion_text: _LoadOpinionText = _default_load_opinion_text,
    gateway: _JudgeGatewayProtocol | None = None,
    judge_model: str = "fast",
) -> int:
    ...
    # (existing verbatim loop builds `rows`; track passages that matched verbatim)
    matched = {id(p) for p in passages if _passage_has_row(p, rows)}  # or track inline
    # --- SUPPORTED judge pass (additive; only with a gateway) ---
    if gateway is not None:
        spent = Decimal("0")
        for passage in passages:
            if _already_verbatim(passage):   # skip passages that got a verbatim row
                continue
            for op, text in texts:
                est = await estimate_case_content_cost_usd(db, judge_model=judge_model, opinion_text=text)
                if spent + est > CASE_CONTENT_JUDGE_BUDGET_USD:
                    log.info("case-content judge: per-turn budget reached; stopping")
                    break  # stop judging this turn
                spent += est
                try:
                    result = await judge_case_content(passage=passage, opinion_text=text, gateway=gateway, judge_model=judge_model)
                except Exception as exc:
                    log.warning("case-content judge error on opinion %s: %r", op.opinion_id, exc)
                    continue
                if not result.verified:
                    continue  # this opinion's judge rejected; try next
                rows.append(MessageCaselawCitation(
                    message_id=message_id, opinion_id=op.opinion_id, cluster_id=op.cluster_id,
                    source_offset_start=0, source_offset_end=len(text),
                    source_text=passage, verified=True, verification_method="paraphrase_judge",
                    verification_confidence=result.confidence, partial=True))
                break  # one SUPPORTED row per passage, first accepting opinion wins
            else:
                continue
            # (inner break already advanced to next passage)
    if rows:
        db.add_all(rows)  # NOTE: keep a single add_all/flush; see below
        await db.flush()
    return len(rows)
```

> **Implementer:** the existing function already builds `rows` from the verbatim loop and does one `add_all` + `flush` at the end — fold the judge-pass rows into the **same** `rows` list and the existing single `add_all`/`flush` (don't add a second flush). Track "which passages got a verbatim row" cleanly (e.g. collect verbatim-matched passage strings into a set during the first loop, then `if passage in verbatim_matched: continue` in the judge pass). The budget `break` must stop the whole judge pass for the turn (not just the inner opinion loop) — restructure with a flag or early-return so the per-turn cap is honored.

Add the imports: `from decimal import Decimal`, `from app.citation.case_content_judge import judge_case_content, estimate_case_content_cost_usd, CASE_CONTENT_JUDGE_BUDGET_USD`, and the `_JudgeGatewayProtocol` type.

- [ ] **Step 4: Thread the gateway at the two finalize sites** in `api/app/api/chats.py` (~2920 and ~3503): add `gateway=gateway` to both `verify_and_persist_caselaw_citations(...)` calls (the `GatewayClient` is already in scope at both — confirm the local variable name and pass it).

- [ ] **Step 5: Run the integration tests (pass)** — `cd api && DATABASE_URL=... .venv/bin/pytest tests/integration/test_caselaw_paraphrase_judge.py -v` → all PASS (accept→supported_only; reject→drop; budget=0→no call/no row; gateway=None→unchanged).

- [ ] **Step 6: Full gate**

```bash
cd api && .venv/bin/ruff format app tests && .venv/bin/ruff check app tests && .venv/bin/mypy app && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest -q
```
Expected: ruff + mypy clean; full suite green (no decrease). In particular the **existing** caselaw tests (`gateway=None` default) must be unchanged.

- [ ] **Step 7: Commit**

```bash
git add api/app/citation/caselaw.py api/app/api/chats.py api/tests/integration/test_caselaw_paraphrase_judge.py
git commit -s -m "feat(citation): caselaw paraphrase judge SUPPORTED pass + wire gateway (P1-B1b)

After the verbatim loop, dropped caselaw passages are judged against the
consulted opinions (cost-gated, per-turn budget); a judge-accepted
passage persists a paraphrase_judge row (gate -> supported_only).
Additive-only: no FAIL/unverified rows; gateway=None is unchanged.
Gateway threaded at the two caselaw finalize sites.

Refs ADR 0018 D2/D3, DE-280.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Whole-opinion judge (DE-280) over stored text → Task 1 (`judge_case_content`). ✓
- Per-message cost budget + stop-when-exceeded → Task 1 (`estimate_case_content_cost_usd`) + Task 3 (the `spent`/budget loop). ✓
- SUPPORTED `paraphrase_judge` row on accept; drop on reject (additive-only) → Task 3. ✓
- Migration 0060 relaxes the caselaw method CHECK → Task 2. ✓
- Thread gateway at the two finalize sites → Task 3 Step 4. ✓
- `gateway=None` unchanged; no gate/ledger change → Global Constraints + Task 3 (default param; tests assert it). ✓
- Whole-opinion offsets `(0, len)` + `partial=True` → Task 3 + Global Constraints. ✓
- Caselaw FAIL explicitly NOT here (B1c) → no FAIL row anywhere in the plan. ✓

**Placeholder scan:** The `_build_prompt` body and `judge_case_content` reuse points carry "read `verify_paraphrase` for the exact `ChatCompletionRequest`/`purpose` threading" instructions with the named source symbol — precise reuse, not a TODO. The Task-1 test helpers (`_judge_completion`/`_serialize_messages`) are sourced from the existing cascade judge tests by name. Task-3 Step-1 enumerates the four required tests with exact expected outcomes + assertions (call-count for budget/None cases). No "TBD"/"implement later". ✓

**Type consistency:** `judge_case_content(*, passage, opinion_text, gateway, judge_model) -> VerificationResult` and `estimate_case_content_cost_usd(db, *, judge_model, opinion_text) -> Decimal` are defined in Task 1 and consumed identically in Task 3. `verification_method="paraphrase_judge"` matches the CHECK relaxed in Task 2 and the gate's SUPPORTED set. The `gateway`/`judge_model` params added to `verify_and_persist_caselaw_citations` match the call-site threading in Task 3 Step 4. ✓

**Note for executor:** Before Task 1, read `verify_paraphrase` + `_parse_judge_response` + an existing paraphrase-judge test in `api/tests/` to copy the `ChatCompletionRequest` construction, the `purpose` tagging, the fake-gateway shape, and the judge-response JSON. Before Task 3, read P1-A1's `verify_and_persist_caselaw_citations` end-to-end and `test_caselaw_citations.py` to fold the judge pass into the existing `rows`/`add_all`/`flush` without a second flush and to reuse the opinion-seeding fixtures. Confirm the `GatewayClient` variable name at chats.py:2920 / 3503.
