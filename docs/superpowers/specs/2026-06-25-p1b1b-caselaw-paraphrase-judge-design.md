# P1-B1b — Caselaw paraphrase/content judge (SUPPORTED tier) (design)

**Date:** 2026-06-25
**Milestone:** Fiduciary-grade agentic legal work — Phase 1 (WS-B)
**Branch:** `feat/fiduciary-p1b1b-caselaw-paraphrase-judge`
**Pins:** [ADR 0018](../../adr/0018-citation-ledger-and-fiduciary-grade-output.md) D2 (verify external quotes against the materialized opinion text), D3 (fiduciary-grade gate). Realizes the [DE-280](../../PRD.md#de-280) case-content-accuracy judge as the SUPPORTED tier. Builds on **P1-A1** (caselaw verbatim verification, #218) and **P1-B1** (the gate, #225).
**Security review:** **required** (citation surface + **new gateway egress** + cost accounting; `api/app/citation/**`, `chats.py`).

## Problem

P1-A1 verifies caselaw quotes **verbatim** (cascade stages 1–2, `gateway=None`); a quote that doesn't locate verbatim in any consulted opinion is **silently dropped**. So a paraphrased-but-faithful caselaw quote never reaches a verified tier — the lawyer sees no signal that the quote is *supported* by the cited case even though it is. P1-B1b adds that tier: a **whole-opinion content judge** runs over the dropped passages (cost-bounded) and, when it judges a passage **faithfully supported** by a consulted opinion, persists a `paraphrase_judge` row. The gate (already shipped) reads that as SUPPORTED, so the turn renders `supported_only` (amber in P1-C1) instead of hiding the quote.

**Explicitly out of scope (→ P1-B1c):** persisting caselaw **FAIL** rows for fabricated/misquoted quotes. Safe FAIL requires reliable passage→opinion attribution (parsing each blockquote's `### Case Name` H3 header and matching it to a consulted opinion); without it, judging a dropped passage against *all* consulted opinions would false-positive on legitimate non-caselaw blockquotes (a statute, a KB quote) — wrongly flagging a good draft, the worst failure for a fiduciary tool. B1b ships the false-positive-free SUPPORTED tier; B1c builds the attribution parser + FAIL (pairs with the deferred [DE-279](../../PRD.md#de-279) case-cite resolution). **B1b is purely additive — it only ever writes new SUPPORTED rows; it never writes a FAIL/unverified row and never changes a turn that is fiduciary-grade today into flagged.**

## Why a whole-opinion judge (not the cascade's stage-3)

The cascade's `verify_paraphrase` (stage 3) windows ±200 chars around a **located** span. A dropped caselaw passage has **no located span**, so there is nothing to window. DE-280's design is the right one: feed the judge the **whole opinion** (10–50pp) + the candidate passage and ask "is this passage faithfully supported by this opinion?" Same `_JudgeGatewayProtocol` surface (`chat_completion`), longer context, fidelity-focused prompt — a different verification surface than stage-3 (PRD DE-280).

## Decisions (maintainer-approved 2026-06-25)

- **SUPPORTED-only.** B1b persists a `paraphrase_judge` row when the judge accepts; it does **not** persist FAIL/unverified rows. A passage no consulted opinion's judge accepts stays **dropped** (unchanged from today). Caselaw FAIL + the attribution parser are **P1-B1c**.
- **Per-message cost budget bounds spend.** Before each judge call, estimate cost (`estimate_judge_call_cost_usd` scaled by the opinion's token size) and accumulate per turn against a configured cap. When the next call would exceed the cap, **stop judging this turn** (remaining passages drop, as today). Because B1b writes no FAIL/unverified rows, exhausting the budget simply means "fewer SUPPORTED rows," never a flagged turn — so the over-budget case needs no special row, just a logged stop.
- **Whole-opinion judge over stored text.** The opinion plaintext is already stored locally (`read_opinion` / `ResearchOpinionMetadata`) — no live CourtListener fetch at verification time.
- **DE-360 stays deferred.** B1b runs the judge on a single configured longer-context tier; the cheap→capable escalation router ([DE-360](../../PRD.md#de-360)) ships later. The per-message budget bounds spend until then.
- **No gate / ledger change.** The gate already buckets `paraphrase_judge` → SUPPORTED; `assemble_ledger_entries` already maps the method onto the ledger status. B1b only produces richer rows.

## Design

### Component 1 — `api/app/citation/case_content_judge.py`

```python
async def judge_case_content(
    *, passage: str, opinion_text: str, gateway: _JudgeGatewayProtocol, judge_model: str,
) -> VerificationResult:
```

Builds a fidelity prompt (the full opinion text + the candidate passage; "is the passage faithfully supported — same holding/quote, not a distortion?"), calls `gateway.chat_completion`, and parses to `VerificationResult(verified=True, method="paraphrase_judge", confidence, partial)` on accept or `_MISS` on reject — reusing the cascade's judge-response parser (`_parse_judge_response`) and the `judge_prompts.py` conservative-bias convention (a false-positive verification is worse than a false-negative; malformed output → `_MISS`). Inference logged with `purpose='judge_case_content'` (a new `InferenceRoutingLog.purpose` string — no schema change) so cost calibration stays segregated from stage-3's `judge_paraphrase`.

### Component 2 — Cost pre-flight

```python
async def estimate_case_content_cost_usd(db, *, judge_model: str, opinion_text: str) -> Decimal:
```

`estimate_judge_call_cost_usd(db, judge_model=...)` (rolling average, `0.005` cold-start) scaled by an opinion-token estimate (`len(opinion_text) / CHARS_PER_TOKEN`). The orchestrator (Component 3) keeps a per-turn running total against a configured `CASE_CONTENT_JUDGE_BUDGET_USD` cap (a module/config constant in v1; operator-tunable later, not this slice). When the next call would exceed the cap, the orchestrator stops judging and logs the stop.

### Component 3 — `caselaw.py` orchestration

`verify_and_persist_caselaw_citations` gains `gateway: _JudgeGatewayProtocol | None = None` and a `judge_model` (default a configured longer-context tier). The existing verbatim loop is unchanged. **After** it (for passages that produced no verbatim row), **and only if `gateway` is provided**:

1. For each still-unverified passage, iterate the already-loaded consulted opinion texts:
   - **Cost pre-flight** for `(judge_model, opinion_text)`; if the turn budget would be exceeded → **stop** (break out; remaining passages drop). Log the stop.
   - Else `judge_case_content(passage, opinion_text, gateway, judge_model)`. On **accept** → append a `MessageCaselawCitation(verified=True, verification_method="paraphrase_judge", verification_confidence=…, partial=…, opinion_id=op.opinion_id, cluster_id=op.cluster_id, source_offset_start/end=…)` and **break** (one SUPPORTED row per passage, first accepting opinion wins).
2. A passage no opinion accepts → **dropped** (no row), exactly as today.
3. A per-opinion judge/gateway error is caught and treated as "no verdict" for that opinion (logged, never fatal).
4. `gateway=None` → the function behaves exactly as today (verbatim-only; deterministic; no egress, no cost).

> **Offsets for a paraphrase row.** A paraphrase has no exact span in the opinion. v1 stores the **judge-identified supporting span** when the judge returns one, else a sentinel (e.g. `0,0` is rejected by the `offset_end > offset_start` CHECK) — so the judge prompt must return a best-effort supporting char range, or B1b stores the **whole-opinion span** (`0, len(opinion_text)`) as the "passage read" with `partial=True`. **Pin in the plan (task 1):** the simplest honest choice is the whole-opinion span (the trace shows "supported by this opinion" rather than a false exact locus); confirm the `MessageCaselawCitation` offset CHECK accepts it.

### Component 4 — Migration `0060` (relax the caselaw method CHECK)

`chk_message_caselaw_citations_method_values` currently admits `('exact_match','tolerant_match')`. Add `'paraphrase_judge'`. Update the model's `CheckConstraint` to match. (`down_revision="0059"`; next migration after the gate table.)

### Component 5 — Thread the gateway at the finalize sites

The two caselaw finalize sites in `chats.py` already have a live `GatewayClient` in scope. Pass it: `verify_and_persist_caselaw_citations(db, …, gateway=gateway)`.

### Ledger + gate (no change)

`assemble_ledger_entries` maps `message_caselaw_citations.verification_method` → the ledger entry status; the gate buckets `paraphrase_judge` → SUPPORTED. A B1b SUPPORTED row makes the turn `supported_only`. **No** change to `ledger.py` / `gate.py`. P1-C1 renders it amber.

## Error handling (conservative posture)

- Gateway/judge error on an opinion → "no verdict" for that opinion (logged), never fatal; the turn proceeds.
- Malformed judge output → `_MISS` (conservative; no row).
- Budget exhausted → stop judging (remaining passages drop); no special row, no flag.
- `gateway=None` → unchanged verbatim-only behaviour (no egress, no cost).
- B1b never writes a row that could flip a turn to `flagged` (additive-only invariant).

## Testing

- **Unit (mocked gateway — no live egress):** `judge_case_content` accept → `paraphrase_judge` result; reject → `_MISS`; the prompt includes the full opinion text + passage; malformed output → `_MISS`. `estimate_case_content_cost_usd` scales with opinion length.
- **Integration (real Postgres, mocked gateway):** a turn with a paraphrased caselaw quote → one `paraphrase_judge` `MessageCaselawCitation`; `assemble_ledger_entries` + the gate → `supported_only`. A budget set below one call's estimate → **no** judge call made (assert the mock was not called) and **no** row (passage drops); the turn's gate is whatever the verbatim rows say (not flipped to flagged). `gateway=None` → identical to today (no rows beyond verbatim, no egress). A judge that rejects all consulted opinions → passage drops (no row, additive-only invariant holds).
- **Migration:** `0060` applies (conftest auto-migrate); a `paraphrase_judge` row inserts; the CHECK still rejects a bogus method.
- Gates: `ruff format` + `ruff check` + `mypy app` + full `pytest`. Mocked gateway → no `-m provider`. Host venv + throwaway pgvector; **next migration = 0060**.

## Acceptance criteria

1. A faithful but non-verbatim caselaw quote, against a consulted opinion, persists a `paraphrase_judge` `MessageCaselawCitation` and moves the turn's gate to `supported_only` (rendered amber by C1).
2. **Additive-only:** B1b never writes a FAIL/unverified caselaw row; a turn that is `fiduciary_grade` or `supported_only` today is never flipped to `flagged` by B1b. A passage no opinion accepts stays dropped.
3. The per-message cost budget bounds spend: once the cap is reached, no further judge calls are made for the turn (asserted with a call-count on the mock).
4. `gateway=None` preserves today's verbatim-only behaviour exactly (no egress); migration `0060` adds `paraphrase_judge` to the caselaw CHECK.
5. No change to `ledger.py` or `gate.py`. `ruff` + `mypy` clean; unit + integration + migration tests green; security review passes the egress/cost surface.

## Out of scope / sequencing

- **P1-B1c — caselaw FAIL + attribution** (NEW): a passage→opinion attribution parser (blockquote → nearest `### Case` H3 → matched consulted opinion) so a judge-rejected quote against its *attributed* opinion persists a FAIL row (gate → `flagged`) without false-positives on non-caselaw blockquotes. Pairs with DE-279. **To be added to the proposal's Phase-1 PR decomposition + PRD as its own (security-gated) slice.**
- **DE-360** escalation routing — deferred; B1b uses one configured judge tier.
- **Operator-tunable** budget cap / PASS set — deferred (config constant in v1).
- **C1 UI** ships **first** and renders the new `supported_only` amber state automatically once B1b lands.
