# WS-D PR1 — Governed Agentic Loop + Matter Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the autonomous `analysis` phase into a governed `plan → act → observe → replan` loop for matter-scoped sessions — the planner picks the next observe-intent from `PHASE_GRANTS[analysis]` each step (all through `guarded_tool_call`), observations fold back compactly, and a final `run_skill` synthesis produces the structured findings the rest of the graph already consumes.

**Architecture:** A new closed-set `ToolIntent.plan` (a gateway-inference intent). A `planner.py` module (prompt builder + parser + observation summarizer). The loop is a `while` inside `analysis_node` — **no LangGraph change** — gated on `state["query"]` so query-less sessions are byte-identical to today. Bounded by a step cap + the existing R4 budget. No ledger/gate (that is PR2).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 (async), LangGraph, arq, pytest, ruff, mypy. Subsystem: `api/app/autonomous/`.

## Global Constraints

- **Security-gated** (`api/app/autonomous/**` — the governance chokepoint): security/maintainer merges; mirror `origin/main → tucuxi` after. Claude does NOT self-merge.
- **No migration** — `ToolIntent` is a `StrEnum` not persisted under a DB CHECK; the audit `action` is `autonomous_session.<event>` (event-keyed, Python-closed-set), not the intent. Task 1 confirms this before relying on it. Next migration stays `0063`; next DE = DE-368.
- **Strictly additive / backward-compat (load-bearing):** the planner loop engages ONLY when `state["query"]` is non-empty. Query-less sessions (cron/watch/schedule) take the UNCHANGED single-`run_skill` path — same intents, same audit rows, same outputs.
- **Every loop step is governed:** the planner call and every action go through `guarded_tool_call` (R5→R6→R4 unchanged). No tool path bypasses the chokepoint. No new brake machinery.
- **Synthesis contract (load-bearing):** however the loop ends (`planner_done` / `step_cap` / `planner_unparseable` / `planner_out_of_set`), a final `run_skill` synthesis always produces the fenced-JSON structured findings that `drafting`'s `parse_structured_output` expects, as `analysis_content`. A cap-halt yields a partial-but-honest result, never a fabricated-complete one.
- **Planner action allowlist:** the planner may choose ONLY observe intents — `retrieve_chunks`, `retrieve_caselaw`, `call_mcp_tool` — or signal done. `run_skill`/`run_playbook` are reserved for the final synthesis; `propose_precedent` and the emit intents are not planner-driven in PR1.
- **Args are model-generated, handler-validated:** the planner emits `args` for the chosen intent; the intent's existing handler validates them (the closed-set boundary, ADR 0015). A bad arg is a non-fatal tool outcome summarized as a failed observation — it never escapes the governed path.
- **P3:** observations + the plan trace hold counts / ids / case-names / short snippets / the planner's own rationale — NEVER full opinion or chunk payloads.
- **Bounded:** `DEFAULT_MAX_ANALYSIS_STEPS = 6`, `params["max_analysis_steps"]` override, plus R4's `max_cost_usd` ($5 default).
- **Tests:** host venv `api/.venv` + throwaway pgvector `:55432`, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test`. Stub gateway/planner → no `-m provider`.
- **CI gate (thrice-burned LESSON):** from the **repo root** — `ruff check api scripts`, `ruff format --check api scripts`, gateway equivalents, `mypy app` whole-app, both full suites. Never per-file / `app tests`-only.
- Commits: `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## File structure

| File | Change | Task |
|---|---|---|
| `api/app/autonomous/enums.py` | add `ToolIntent.plan` + grant in `PHASE_GRANTS[analysis]` | 1 |
| `api/app/autonomous/cost.py` | `plan` ∈ `_INFERENCE_INTENTS` (R4 costs it as inference) | 1 |
| `api/app/autonomous/guard.py` | route `plan` through `_handle_gateway_inference` in `_dispatch` | 1 |
| `api/app/autonomous/planner.py` | NEW — `PlannerDecision`, `build_planner_messages`, `parse_planner_decision`, `summarize_observation`, `PLANNER_ALLOWLIST` | 2, 3 |
| `api/app/autonomous/prompts.py` | NEW `assemble_synthesis_messages` | 4 |
| `api/app/autonomous/nodes.py` | the loop + backward-compat gate in `make_analysis_node` | 5 |
| `api/app/config.py` | `DEFAULT_MAX_ANALYSIS_STEPS` (or in `enums.py`) | 5 |
| `api/app/autonomous/receipt.py` | surface the plan trace (P3) | 6 |

---

### Task 1: `ToolIntent.plan` — closed-set extension, grant, cost, dispatch

**Files:**
- Modify: `api/app/autonomous/enums.py` (`ToolIntent`, `PHASE_GRANTS[Phase.analysis]`)
- Modify: `api/app/autonomous/cost.py` (`_INFERENCE_INTENTS`)
- Modify: `api/app/autonomous/guard.py:549` (the inference branch in `_dispatch`)
- Test: `api/tests/autonomous/test_plan_intent.py` (new)

**Interfaces:**
- Produces: `ToolIntent.plan = "plan"`, granted in `PHASE_GRANTS[Phase.analysis]`; `guarded_tool_call(session, ToolIntent.plan, {"model": ..., "messages": [...], "anonymize": False}, db, gateway)` runs a gateway inference and returns `ToolResult(data={"content": <text>, ...})`, costed by R4 as inference.

- [ ] **Step 1: Verify no migration is needed.** Confirm `ToolIntent` is not persisted under a DB CHECK: `grep -rn "run_skill\|retrieve_chunks\|tool_intent" api/alembic/versions/` returns no CHECK on intent values, and `api/app/models/audit.py`'s `action` column is a free `String`. Record the finding in the task report. (If a CHECK is found, STOP and report — the plan's no-migration assumption is wrong.)

- [ ] **Step 2: Write the failing test** (`api/tests/autonomous/test_plan_intent.py`)

```python
import pytest
from app.autonomous.enums import PHASE_GRANTS, Phase, ToolIntent
from app.autonomous.cost import _INFERENCE_INTENTS, estimate_tool_cost

pytestmark = pytest.mark.asyncio


def test_plan_is_a_tool_intent_granted_in_analysis():
    assert ToolIntent.plan == "plan"
    assert ToolIntent.plan in PHASE_GRANTS[Phase.analysis]
    # not granted elsewhere
    assert ToolIntent.plan not in PHASE_GRANTS[Phase.drafting]
    assert ToolIntent.plan not in PHASE_GRANTS[Phase.intake]


def test_plan_is_an_inference_intent():
    assert ToolIntent.plan in _INFERENCE_INTENTS


async def test_estimate_tool_cost_treats_plan_as_inference():
    # db=None → estimator returns its conservative default (non-None Decimal), not 0
    cost = await estimate_tool_cost(ToolIntent.plan, {"model": "fast"}, None)
    from decimal import Decimal
    assert isinstance(cost, Decimal)
    # contrast: a non-inference intent is exactly 0
    zero = await estimate_tool_cost(ToolIntent.retrieve_caselaw, {}, None)
    assert zero == Decimal("0")
```

- [ ] **Step 3: Run — expect failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_plan_intent.py -v`
Expected: FAIL — `ToolIntent` has no `plan`.

- [ ] **Step 4: Implement.**

In `enums.py`, add the member to `ToolIntent` (after `call_mcp_tool`):
```python
    call_mcp_tool = "call_mcp_tool"
    # WS-D PR1: the planner's next-step decision call (a gateway inference).
    # Granted only in analysis; the agentic loop dispatches it each iteration.
    plan = "plan"
```
And add it to `PHASE_GRANTS[Phase.analysis]`:
```python
            ToolIntent.call_mcp_tool,
            # WS-D PR1: the agentic planner decision call.
            ToolIntent.plan,
```

In `cost.py`, add `plan` to `_INFERENCE_INTENTS` (find its definition — it currently holds `run_skill`, `run_playbook`):
```python
_INFERENCE_INTENTS = frozenset(
    {ToolIntent.run_skill, ToolIntent.run_playbook, ToolIntent.plan}
)
```

In `guard.py:549`, extend the inference branch:
```python
    if intent in (ToolIntent.run_skill, ToolIntent.run_playbook, ToolIntent.plan):
        return await _handle_gateway_inference(
            intent, params, gateway=gateway, estimated_cost=estimated_cost
        )
```
(`_handle_gateway_inference` reads `params["messages"]`/`params["model"]`/`params["anonymize"]` and returns `ToolResult(data={"content": ...})` — the planner call is just another inference. Confirm its docstring/branching doesn't reject an unknown intent; it keys on `params`, not the intent name.)

- [ ] **Step 5: Run — expect pass + the autonomous suite for regressions**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_plan_intent.py tests/autonomous -v`
Expected: PASS (new + no autonomous regressions).

- [ ] **Step 6: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/enums.py api/app/autonomous/cost.py api/app/autonomous/guard.py api/tests/autonomous/test_plan_intent.py
git commit -s -m "feat(autonomous): ToolIntent.plan — closed-set planner intent (WS-D PR1)"
```

---

### Task 2: planner prompt + decision parser

**Files:**
- Create: `api/app/autonomous/planner.py`
- Test: `api/tests/autonomous/test_planner_decision.py` (new)

**Interfaces:**
- Produces:
  - `PLANNER_ALLOWLIST: frozenset[ToolIntent]` = `{retrieve_chunks, retrieve_caselaw, call_mcp_tool}` (observe intents the planner may choose).
  - `@dataclass(slots=True) PlannerDecision(done: bool, next_intent: ToolIntent | None, args: dict[str, Any], rationale: str)`
  - `build_planner_messages(*, goal: str, observations: list[str], allowlist: frozenset[ToolIntent]) -> list[dict[str, str]]`
  - `parse_planner_decision(content: str | None) -> PlannerDecision | None` — `None` on unparseable / unknown structure; a `done` decision when the planner signals completion; a valid action decision otherwise. A `next_intent` not in `allowlist` → `None` (the loop treats it as `planner_out_of_set`).

- [ ] **Step 1: Write the failing tests** (`api/tests/autonomous/test_planner_decision.py`)

```python
import json
import pytest
from app.autonomous.enums import ToolIntent
from app.autonomous.planner import (
    PLANNER_ALLOWLIST, PlannerDecision, build_planner_messages, parse_planner_decision,
)


def test_allowlist_is_observe_intents_only():
    assert PLANNER_ALLOWLIST == frozenset(
        {ToolIntent.retrieve_chunks, ToolIntent.retrieve_caselaw, ToolIntent.call_mcp_tool}
    )


def test_prompt_carries_goal_observations_and_allowlist():
    msgs = build_planner_messages(
        goal="Is the assignment clause enforceable?",
        observations=["retrieve_caselaw → 2 results: [Smith (9th 2021); Doe (2d 2019)]"],
        allowlist=PLANNER_ALLOWLIST,
    )
    assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
    body = msgs[0]["content"] + msgs[1]["content"]
    assert "assignment clause" in body
    assert "Smith (9th 2021)" in body
    for intent in PLANNER_ALLOWLIST:
        assert intent.value in body  # the allowlist is shown to the planner


def test_parse_action_decision():
    out = parse_planner_decision(json.dumps({
        "next_intent": "retrieve_caselaw",
        "args": {"query": "assignment clause change of control"},
        "rationale": "Need controlling authority on assignment survival.",
    }))
    assert out == PlannerDecision(
        done=False, next_intent=ToolIntent.retrieve_caselaw,
        args={"query": "assignment clause change of control"},
        rationale="Need controlling authority on assignment survival.",
    )


def test_parse_done_decision():
    out = parse_planner_decision(json.dumps({"done": True, "rationale": "Enough authority gathered."}))
    assert out is not None and out.done is True and out.next_intent is None


@pytest.mark.parametrize("bad", [
    None, "", "not json",
    json.dumps({"next_intent": "emit_finding", "args": {}, "rationale": "x"}),   # out of allowlist
    json.dumps({"next_intent": "run_skill", "args": {}, "rationale": "x"}),       # reserved for synthesis
    json.dumps(["retrieve_caselaw"]),                                            # not a dict
    json.dumps({"args": {}, "rationale": "x"}),                                   # no next_intent, no done
])
def test_parse_returns_none_on_garbage_or_out_of_set(bad):
    assert parse_planner_decision(bad) is None
```

- [ ] **Step 2: Run — expect failure** (module missing)

Run: `cd api && .venv/bin/python -m pytest tests/autonomous/test_planner_decision.py -v`
Expected: FAIL — `ModuleNotFoundError: app.autonomous.planner`.

- [ ] **Step 3: Implement** (`api/app/autonomous/planner.py`)

```python
"""WS-D PR1 — the agentic planner: prompt, decision parser, observation summarizer.

The planner is a gateway inference (ToolIntent.plan) that, given the matter
goal + compact observations + the observe-intent allowlist, returns either the
next governed action to take or a 'done' signal. It NEVER selects outside the
closed allowlist (an out-of-set proposal parses to None → the loop stops
conservatively). It does not execute anything — the loop dispatches its choice
through guarded_tool_call (ADR 0020 D1).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.autonomous.enums import ToolIntent

log = logging.getLogger(__name__)

# The planner may choose ONLY observe intents (gather), or signal done.
# run_skill/run_playbook are reserved for the final synthesis; emit/side-effect
# intents are not planner-driven in PR1.
PLANNER_ALLOWLIST: frozenset[ToolIntent] = frozenset(
    {ToolIntent.retrieve_chunks, ToolIntent.retrieve_caselaw, ToolIntent.call_mcp_tool}
)

_SYSTEM_PROMPT = """\
You are the research planner for a governed legal-matter agent. Given the
MATTER GOAL and the OBSERVATIONS gathered so far, decide the SINGLE next
research action, or that enough has been gathered.

You may choose ONLY from this closed set of actions (you cannot invent tools):
{allowlist}

Respond with STRICTLY VALID JSON, one of:

  {{"next_intent": "<one action above>",
    "args": {{ ...arguments for that action... }},
    "rationale": "<one sentence: why this next step>"}}

or, when enough authority/context has been gathered:

  {{"done": true, "rationale": "<one sentence: why you are finished>"}}

Output ONLY the JSON object. No preamble, no markdown fencing."""


@dataclass(slots=True)
class PlannerDecision:
    done: bool
    next_intent: ToolIntent | None
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""


def build_planner_messages(
    *, goal: str, observations: list[str], allowlist: frozenset[ToolIntent]
) -> list[dict[str, str]]:
    allow = ", ".join(sorted(i.value for i in allowlist))
    system = _SYSTEM_PROMPT.format(allowlist=allow)
    obs = "\n".join(f"- {o}" for o in observations) if observations else "(none yet)"
    user = f"MATTER GOAL:\n{goal}\n\nOBSERVATIONS SO FAR:\n{obs}\n\nDecide the next action as JSON."
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_planner_decision(content: str | None) -> PlannerDecision | None:
    if not content:
        return None
    text = content.strip()
    if text.startswith("```"):  # tolerate an accidental fence
        text = text.strip("`")
        text = text[text.find("{") :] if "{" in text else text
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        log.info("planner produced non-JSON", extra={"event": "autonomous_planner_malformed"})
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("done") is True:
        return PlannerDecision(done=True, next_intent=None, rationale=str(payload.get("rationale", "")))
    raw_intent = payload.get("next_intent")
    if not isinstance(raw_intent, str):
        return None
    try:
        intent = ToolIntent(raw_intent)
    except ValueError:
        return None
    if intent not in PLANNER_ALLOWLIST:
        log.info("planner chose out-of-allowlist intent %r", raw_intent,
                 extra={"event": "autonomous_planner_out_of_set"})
        return None
    args = payload.get("args")
    if not isinstance(args, dict):
        args = {}
    return PlannerDecision(
        done=False, next_intent=intent, args=args, rationale=str(payload.get("rationale", "")),
    )
```

- [ ] **Step 4: Run — expect pass**

Run: `cd api && .venv/bin/python -m pytest tests/autonomous/test_planner_decision.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/planner.py api/tests/autonomous/test_planner_decision.py
git commit -s -m "feat(autonomous): planner prompt + decision parser (WS-D PR1)"
```

---

### Task 3: observation summarizer (compact, P3-clean)

**Files:**
- Modify: `api/app/autonomous/planner.py` (add `summarize_observation`)
- Test: `api/tests/autonomous/test_observation_summary.py` (new)

**Interfaces:**
- Consumes: `ToolResult` from `app.autonomous.guard` (`.data`, `.outcome`).
- Produces: `summarize_observation(intent: ToolIntent, rationale: str, result: ToolResult) -> str` — a one-line compact summary (counts / ids / case-names / short snippets), NEVER full payloads. A failed/`outcome != "success"` result → a `"<intent> → failed (<outcome>)"` line.

- [ ] **Step 1: Write the failing tests** (`api/tests/autonomous/test_observation_summary.py`)

```python
from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult
from app.autonomous.planner import summarize_observation


def test_caselaw_summary_lists_case_names_not_full_text():
    result = ToolResult(data={"results": [
        {"case_name": "Smith v. Jones", "court": "ca9", "date_filed": "2021-01-01",
         "opinion_text": "X" * 5000},
        {"case_name": "Doe v. Roe", "court": "ca2", "date_filed": "2019-06-01"},
    ]}, outcome="success")
    s = summarize_observation(ToolIntent.retrieve_caselaw, "find authority", result)
    assert "Smith v. Jones" in s and "Doe v. Roe" in s
    assert "XXXX" not in s            # no full opinion text
    assert len(s) < 400


def test_chunks_summary_counts_and_files():
    result = ToolResult(data={"chunks": [
        {"chunk_id": "c1", "file_name": "nda.pdf", "content": "Y" * 4000},
        {"chunk_id": "c2", "file_name": "nda.pdf", "content": "Z" * 4000},
    ]}, outcome="success")
    s = summarize_observation(ToolIntent.retrieve_chunks, "read clause", result)
    assert "2" in s and "nda.pdf" in s
    assert "YYYY" not in s


def test_failed_result_is_summarized_not_raised():
    result = ToolResult(data=None, outcome="gateway_error")
    s = summarize_observation(ToolIntent.retrieve_caselaw, "x", result)
    assert "failed" in s and "gateway_error" in s
```

- [ ] **Step 2: Run — expect failure**

Run: `cd api && .venv/bin/python -m pytest tests/autonomous/test_observation_summary.py -v`
Expected: FAIL — `summarize_observation` undefined.

- [ ] **Step 3: Implement** — append to `planner.py`:

```python
_SNIPPET = 120


def summarize_observation(intent: ToolIntent, rationale: str, result: "object") -> str:
    """One-line, P3-clean summary of a tool result for the planner's context.

    Never includes full opinion/chunk payloads — only counts, ids, case names,
    and short snippets. ``result`` is a guard.ToolResult (duck-typed to avoid a
    circular import: read ``.outcome`` and ``.data``)."""
    outcome = getattr(result, "outcome", "success")
    data = getattr(result, "data", None) or {}
    if outcome != "success":
        return f"{intent.value} → failed ({outcome})"
    if intent == ToolIntent.retrieve_caselaw:
        items = data.get("results") or data.get("matches") or []
        names = [
            f"{(i.get('case_name') or '?')} ({i.get('court') or '?'} {i.get('date_filed') or '?'})"
            for i in items[:5] if isinstance(i, dict)
        ]
        more = "" if len(items) <= 5 else f" +{len(items) - 5} more"
        return f"{intent.value} → {len(items)} result(s): [{'; '.join(names)}]{more}"
    if intent == ToolIntent.retrieve_chunks:
        chunks = data.get("chunks") or []
        files = sorted({c.get("file_name") for c in chunks if isinstance(c, dict) and c.get("file_name")})
        return f"{intent.value} → {len(chunks)} chunk(s) from {files or '(no files)'}"
    if intent == ToolIntent.call_mcp_tool:
        payload = data if isinstance(data, dict) else {}
        keys = sorted(payload.keys())[:8]
        return f"{intent.value} → payload keys {keys}"
    snippet = str(data)[:_SNIPPET]
    return f"{intent.value} → {snippet}"
```

(Use a forward-ref / duck type for `result` to avoid importing `guard` into `planner` — `guard` already imports the enums; keep the dependency one-directional.)

- [ ] **Step 4: Run — expect pass**

Run: `cd api && .venv/bin/python -m pytest tests/autonomous/test_observation_summary.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/planner.py api/tests/autonomous/test_observation_summary.py
git commit -s -m "feat(autonomous): compact P3-clean observation summarizer (WS-D PR1)"
```

---

### Task 4: synthesis messages

**Files:**
- Modify: `api/app/autonomous/prompts.py` (add `assemble_synthesis_messages`)
- Test: `api/tests/autonomous/test_synthesis_messages.py` (new)

**Interfaces:**
- Consumes: `assemble_analysis_messages(session, *, chunks, db)` (existing — returns `[system, user]` with the skill body + `STRUCTURED_OUTPUT_INSTRUCTION` in `system`).
- Produces: `assemble_synthesis_messages(session, *, goal: str, observations: list[str], chunks: list[dict], db) -> list[dict[str, str]]` — the same `system` (so the structured-findings JSON contract holds), with the matter goal + observations appended to the `user` content.

- [ ] **Step 1: Write the failing test** (`api/tests/autonomous/test_synthesis_messages.py`)

```python
import pytest
from app.autonomous.prompts import assemble_synthesis_messages
# Reuse the autonomous test helpers that seed a session with a skill_ref.
# Match the seeding used by api/tests/autonomous/test_prompts*.py (a session
# whose params carry a skill_ref pointing at a seeded skill).

pytestmark = pytest.mark.asyncio


async def test_synthesis_preserves_structured_contract_and_adds_goal_and_observations(
    db_session, seeded_skill_session  # adapt fixture names to the existing prompts test
):
    msgs = await assemble_synthesis_messages(
        seeded_skill_session, goal="Is the clause enforceable?",
        observations=["retrieve_caselaw → 1 result: [Smith (9th 2021)]"],
        chunks=[], db=db_session,
    )
    assert msgs[0]["role"] == "system" and msgs[-1]["role"] == "user"
    # the structured-output JSON contract is still instructed (from assemble_analysis_messages)
    assert "findings" in msgs[0]["content"] and "```json" in msgs[0]["content"]
    # goal + observations are in the user content
    user_blob = " ".join(m["content"] for m in msgs if m["role"] == "user")
    assert "Is the clause enforceable?" in user_blob
    assert "Smith (9th 2021)" in user_blob
```

> Adapt `seeded_skill_session` to whatever fixture `api/tests/autonomous/test_prompts*.py` already uses to build a session with a resolvable `skill_ref`. If none exists, seed inline following `assemble_analysis_messages`'s expectations (a `Skill` row with `content_md`, and `session.params["skill_ref"]`).

- [ ] **Step 2: Run — expect failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_synthesis_messages.py -v`
Expected: FAIL — `assemble_synthesis_messages` undefined.

- [ ] **Step 3: Implement** — add to `prompts.py`:

```python
async def assemble_synthesis_messages(
    session: AutonomousSession,
    *,
    goal: str,
    observations: list[str],
    chunks: list[dict[str, Any]],
    db: AsyncSession,
    registry: SkillRegistry | None = None,
) -> list[dict[str, str]]:
    """Build the final-synthesis messages for the agentic loop (WS-D PR1).

    Reuses :func:`assemble_analysis_messages` (so the skill/playbook system
    prompt and STRUCTURED_OUTPUT_INSTRUCTION are identical — the synthesis must
    still emit the fenced-JSON findings the drafting node parses), then appends
    a user block carrying the matter GOAL and the loop's compact OBSERVATIONS.
    """
    messages = await assemble_analysis_messages(session, chunks=chunks, db=db, registry=registry)
    obs = "\n".join(f"- {o}" for o in observations) if observations else "(no research steps were run)"
    messages.append({
        "role": "user",
        "content": (
            f"MATTER GOAL:\n{goal}\n\nRESEARCH OBSERVATIONS (gathered by the agent):\n{obs}\n\n"
            "Synthesize your analysis of the MATTER GOAL using the observations and any "
            "chunks above, then return the final JSON object as instructed."
        ),
    })
    return messages
```

- [ ] **Step 4: Run — expect pass**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_synthesis_messages.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/prompts.py api/tests/autonomous/test_synthesis_messages.py
git commit -s -m "feat(autonomous): synthesis messages preserve the structured-findings contract (WS-D PR1)"
```

---

### Task 5: the governed loop in `analysis_node` (the integration heart)

**Files:**
- Modify: `api/app/autonomous/nodes.py` (`make_analysis_node` — add the gate + loop)
- Modify: `api/app/config.py` (`DEFAULT_MAX_ANALYSIS_STEPS = 6`)
- Test: `api/tests/autonomous/test_agentic_loop.py` (new)

**Interfaces:**
- Consumes: `build_planner_messages`, `parse_planner_decision`, `summarize_observation`, `PLANNER_ALLOWLIST` (Tasks 2-3); `assemble_synthesis_messages` (Task 4); `guarded_tool_call`, `ToolResult` (guard); `ToolIntent`, `Phase` (enums).
- Produces: a matter-scoped (`state["query"]`) analysis node that runs the loop; query-less sessions unchanged. Returns `{"current_phase", "analysis_content", "analysis_outcome", "analysis_plan_trace"}`.

- [ ] **Step 1: Write the failing integration tests** (`api/tests/autonomous/test_agentic_loop.py`)

```python
import json
from types import SimpleNamespace
import pytest
from app.autonomous.enums import ToolIntent
# Reuse the autonomous test seeding (a session with skill_ref + retrieved_chunks state).
# Match the fixtures used by api/tests/autonomous/test_nodes*.py.

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# A stub gateway whose chat_completion returns canned planner/synthesis JSON.
# The loop calls guarded_tool_call(plan, ...) → _handle_gateway_inference →
# gateway.chat_completion; and guarded_tool_call(run_skill, synthesis) likewise.
# The stub distinguishes planner calls (system mentions "research planner")
# from synthesis calls (system carries STRUCTURED_OUTPUT_INSTRUCTION).

def _resp(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                           usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10))


class _ScriptedGateway:
    def __init__(self, planner_script):
        self.planner_script = list(planner_script)  # list of dicts the planner returns in order
    async def chat_completion(self, request, *, request_id=None):
        system = request.messages[0].content
        if "research planner" in system:
            return _resp(json.dumps(self.planner_script.pop(0)))
        # synthesis call → return the structured findings JSON
        return _resp('```json\n{"findings": [{"title": "t", "summary": "s", '
                     '"severity": "info", "source_chunk_ids": []}], "suggested_memories": [], '
                     '"suggested_precedents": [], "privilege_concerns": [], "scope_concerns": []}\n```')


async def test_query_less_session_is_unchanged(db_session, seeded_skill_session_no_query):
    # No state["query"] → single run_skill path; NO plan intent ever audited.
    ... # build the analysis node, run it with state lacking "query",
        # assert analysis_content is the single-call content and no audit row has intent "plan".


async def test_loop_runs_planner_then_done_then_synthesis(db_session, seeded_matter_session):
    gw = _ScriptedGateway([
        {"next_intent": "retrieve_caselaw", "args": {"query": "assignment clause"}, "rationale": "find authority"},
        {"done": True, "rationale": "enough"},
    ])
    ... # build analysis node bound to gw; run with state["query"]="...".
        # assert: retrieve_caselaw ran through guarded_tool_call (audit has it);
        # the final synthesis produced analysis_content with parseable findings;
        # the return dict's analysis_plan_trace has 1 step + halt_reason "planner_done".


async def test_step_cap_halts_and_still_synthesizes(db_session, seeded_matter_session):
    # planner never says done → loop stops at max_analysis_steps; synthesis still runs.
    gw = _ScriptedGateway([{"next_intent": "retrieve_caselaw", "args": {}, "rationale": "x"}] * 20)
    ... # set session.params["max_analysis_steps"]=2; assert exactly 2 act steps,
        # halt_reason "step_cap", analysis_content still present (partial-but-honest).


async def test_unparseable_planner_stops_loop_then_synthesizes(db_session, seeded_matter_session):
    gw = _ScriptedGateway(["not json at all"])  # planner returns junk
    ... # assert: no action dispatched, halt_reason "planner_unparseable",
        # synthesis still runs, analysis_content present.
```

> Fill the `...` bodies against the existing autonomous node tests (`api/tests/autonomous/test_nodes*.py`) — reuse their session/skill/state seeding and their `make_analysis_node` invocation pattern. Build `seeded_matter_session` = a `seeded_skill_session` whose `params["query"]` is set; `seeded_skill_session_no_query` = the same without `query`. Assert audit intents via the `audit_log`/`autonomous_audit` rows those tests already query. If wiring the full node proves heavy, an acceptable interim is to test an extracted `_run_analysis_loop(...)` helper directly — but prefer the node.

- [ ] **Step 2: Run — expect failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_agentic_loop.py -v`
Expected: FAIL — node has no loop; query-sessions take the single-call path; no `analysis_plan_trace`.

- [ ] **Step 3: Implement.** Add `DEFAULT_MAX_ANALYSIS_STEPS = 6` to `config.py` (a module constant near the other autonomous defaults). In `nodes.py`, add the imports (`build_planner_messages, parse_planner_decision, summarize_observation, PLANNER_ALLOWLIST` from `app.autonomous.planner`; `assemble_synthesis_messages` from `app.autonomous.prompts`) and insert the gate + loop. After the existing degenerate-target guard (the `if not skill_ref and not playbook_id` block) and before the existing single-call path, branch on the query:

```python
        query = (state.get("query") or "").strip()
        settings = get_settings()
        model = params.get("model") or settings.autonomous_default_model

        if query:
            return await _run_analysis_loop(
                session, query=query, params=params, chunks=state.get("retrieved_chunks") or [],
                model=model, db=db, gateway=gateway,
            )

        # ---- unchanged single-call path (query-less sessions) ----
        chunks = state.get("retrieved_chunks") or []
        messages = await assemble_analysis_messages(session, chunks=chunks, db=db)
        intent = ToolIntent.run_playbook if playbook_id else ToolIntent.run_skill
        result = await guarded_tool_call(
            session, intent, {"model": model, "messages": messages, "anonymize": True}, db, gateway,
        )
        return {
            "current_phase": str(Phase.analysis),
            "analysis_content": (result.data or {}).get("content"),
            "analysis_outcome": result.outcome,
        }
```

Add the loop helper (module-level in `nodes.py`):

```python
async def _run_analysis_loop(
    session: AutonomousSession, *, query: str, params: dict[str, Any],
    chunks: list[dict[str, Any]], model: str, db: AsyncSession, gateway: Any,
) -> dict[str, Any]:
    """The governed plan→act→observe→replan loop (WS-D PR1). Every step goes
    through guarded_tool_call (R5→R6→R4); bounded by max_analysis_steps + R4."""
    from app.config import DEFAULT_MAX_ANALYSIS_STEPS

    max_steps = int(params.get("max_analysis_steps") or DEFAULT_MAX_ANALYSIS_STEPS)
    observations: list[str] = []
    trace: list[dict[str, str]] = []
    halt_reason = "step_cap"
    steps = 0
    while steps < max_steps:
        plan_res = await guarded_tool_call(
            session, ToolIntent.plan,
            {"model": model,
             "messages": build_planner_messages(
                 goal=query, observations=observations, allowlist=PLANNER_ALLOWLIST),
             "anonymize": False},
            db, gateway,
        )
        decision = parse_planner_decision((plan_res.data or {}).get("content"))
        if decision is None:
            halt_reason = "planner_unparseable"
            break
        if decision.done:
            halt_reason = "planner_done"
            trace.append({"step": str(steps), "intent": "done", "rationale": decision.rationale})
            break
        assert decision.next_intent is not None  # parser guarantees: action ⇒ next_intent set
        act = await guarded_tool_call(session, decision.next_intent, decision.args, db, gateway)
        observations.append(summarize_observation(decision.next_intent, decision.rationale, act))
        trace.append({"step": str(steps), "intent": decision.next_intent.value,
                      "rationale": decision.rationale})
        steps += 1

    synth = await guarded_tool_call(
        session, ToolIntent.run_skill,
        {"model": model,
         "messages": await assemble_synthesis_messages(
             session, goal=query, observations=observations, chunks=chunks, db=db),
         "anonymize": True},
        db, gateway,
    )
    return {
        "current_phase": str(Phase.analysis),
        "analysis_content": (synth.data or {}).get("content"),
        "analysis_outcome": synth.outcome,
        "analysis_plan_trace": {"steps": steps, "halt_reason": halt_reason, "decisions": trace},
    }
```

(`analysis_plan_trace` is a JSONable dict — counts/intents/rationales/halt only, P3. A mid-loop brake — `SessionHalted`/`CostCapReached` — propagates out of `guarded_tool_call` exactly as today; the executor's terminal handler owns it.)

Add `analysis_plan_trace: dict | None` to `AutonomousSessionState` in `state.py`.

- [ ] **Step 4: Run — expect pass + the full autonomous suite (regressions)**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous -v`
Expected: PASS (new loop tests + every existing autonomous test — the query-less path must be untouched).

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/nodes.py api/app/autonomous/state.py api/app/config.py api/tests/autonomous/test_agentic_loop.py
git commit -s -m "feat(autonomous): governed plan-act-observe-replan loop in the analysis phase (WS-D PR1)"
```

---

### Task 6: surface the plan trace in the receipt (D5 transparency)

**Files:**
- Modify: `api/app/autonomous/receipt.py` (include the plan trace)
- Modify: the delivery node / executor so `analysis_plan_trace` reaches the receipt (thread state → `session.result`)
- Test: `api/tests/autonomous/test_receipt_plan_trace.py` (new)

**Interfaces:**
- Consumes: `analysis_plan_trace` from `AutonomousSessionState` (Task 5).
- Produces: the session `result`/receipt carries `plan_trace` = `{steps, halt_reason, decisions:[{step, intent, rationale}]}` — counts/types/short-rationale only (P3).

- [ ] **Step 1: Write the failing test** (`api/tests/autonomous/test_receipt_plan_trace.py`)

```python
import pytest
pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# Run a matter session end-to-end (scripted gateway from Task 5's helper) and
# assert the persisted session.result / receipt includes plan_trace with the
# step count, halt_reason, and per-decision intents+rationales — and NO full
# tool payloads (P3).
async def test_receipt_carries_plan_trace(db_session, seeded_matter_session):
    ...  # drive the graph (or build_receipt over the state) and assert:
    # result["plan_trace"]["halt_reason"] in {"planner_done","step_cap",...}
    # result["plan_trace"]["decisions"][0]["intent"] == "retrieve_caselaw"
    # no value in the trace exceeds a short length (no payloads)
```

> Match how the existing receipt tests (`api/tests/autonomous/test_receipt*.py`) drive `build_receipt` / read `session.result`. If the receipt is built purely from `audit_log`, thread `analysis_plan_trace` through the delivery node into `session.result` (the executor already writes `result` at delivery) and assert there; reuse the existing end-to-end session-run helper if one exists.

- [ ] **Step 2: Run — expect failure**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_receipt_plan_trace.py -v`
Expected: FAIL — no `plan_trace` in the receipt/result.

- [ ] **Step 3: Implement.** Thread `analysis_plan_trace` from state into `session.result` where the receipt is assembled (the delivery node / `build_receipt`). Include it as `result["plan_trace"]`. Keep it counts/types/short-rationale only — do not add tool payloads. (Exact wiring: follow how `findings_count` / the existing receipt fields flow from state to `result`.)

- [ ] **Step 4: Run — expect pass**

Run: `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest tests/autonomous/test_receipt_plan_trace.py tests/autonomous -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
cd api && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
git add api/app/autonomous/receipt.py api/app/autonomous/nodes.py api/tests/autonomous/test_receipt_plan_trace.py
git commit -s -m "feat(autonomous): surface the agentic plan trace in the receipt (WS-D PR1)"
```

---

## Final gate (before requesting review — the thrice-burned CI LESSON)

- [ ] **api full gates at CI scope (repo root):**
```bash
cd /Users/kevinkeller/Code/lq-ai
api/.venv/bin/ruff check api scripts && api/.venv/bin/ruff format --check api scripts
cd api && .venv/bin/mypy app
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/python -m pytest -q
```
- [ ] **gateway full gates:** `cd gateway && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app --strict && .venv/bin/python -m pytest -q` (PR1 doesn't touch gateway; confirm no incidental break).
- [ ] **PRD/ADR bookkeeping:** note WS-D PR1 status; no DE unless one surfaces.
- [ ] **Opus whole-branch review** (SDD final) — required; it has caught a real gate-passing defect on every slice this milestone.

## Plan self-review (completed)

- **Spec coverage:** `ToolIntent.plan` + grant + cost + dispatch → Task 1; planner prompt+parser → Task 2; observation summarizer → Task 3; synthesis-contract messages → Task 4; the loop + backward-compat gate + step cap → Task 5; receipt/D5 transparency → Task 6. Out-of-scope (ledger/gate, UI, source registry, intake-LLM step) explicitly deferred. Migration caveat resolved in Task 1 Step 1.
- **Placeholder scan:** real code/commands throughout. The `...` test bodies in Tasks 5-6 are deliberately delegated to the existing autonomous test seeding (named: `test_nodes*.py`, `test_receipt*.py`) with the asserted contract fixed — integration points against existing fixtures, not logic placeholders.
- **Type consistency:** `PlannerDecision(done, next_intent, args, rationale)`, `PLANNER_ALLOWLIST`, `build_planner_messages(*, goal, observations, allowlist)`, `parse_planner_decision(content) -> PlannerDecision | None`, `summarize_observation(intent, rationale, result) -> str`, `assemble_synthesis_messages(session, *, goal, observations, chunks, db)`, `_run_analysis_loop(...)`, and `analysis_plan_trace` are consistent across Tasks 1-6.
