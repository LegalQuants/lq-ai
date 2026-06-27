# WS-G PR2 — the treatment-classifying judge (design)

**Date:** 2026-06-26
**Milestone:** Fiduciary-grade agentic legal work — Phase 2, WS-G (transparent validity/treatment layer)
**ADR:** [0019](../../adr/0019-transparent-validity-treatment-layer.md) — this spec resolves its §"Open questions" for PR2.
**Builds on:** WS-G PR1 (`citation_treatment` graph signal, mig 0061, `derive_treatment_for_message`, the async `treatment_derivation_job`).
**Security-gated:** yes — new judge egress reasoning + the citing-graph surface (`gateway/**`, `api/app/citation/**`). Kevin/security merges; mirror `origin/main → tucuxi` after.
**Next migration:** `0062`. **Next DE:** DE-365.

---

## 1. What this delivers

PR1 ships the *graph-level* treatment signal: "case X is cited by N later opinions; here they are (court + date)." PR2 adds the **classification**: for a prioritized, capped subset of those citing opinions, an LLM judge classifies *how* each one treats case X — `followed / distinguished / criticized / questioned / overruled / superseded / neutral` — and the per-passage classifications roll up to a **strongest-negative case-level signal** ("overruled by 1; questioned by 2; distinguished by 5; otherwise neutral — derived as of <date>").

The signal stays **derived, not editorial** (ADR 0019 D1): every contributing classification links to the exact citing opinion and carries the judge's reasoning + confidence; the rollup never collapses to a single "good law / bad law" verdict. Treatment **never** gates the fiduciary verdict (ADR 0018 D3 / 0019 D2) — it enriches the ledger entry.

### In scope
- A new treatment judge (new prompt + verdict schema) over the existing judge rails.
- Snippet-based passage localization (extend `get_citing_opinions` to return CourtListener's per-result `snippet`).
- A `citation_treatment_signal` child table + rollup columns on `citation_treatment` (mig 0062).
- A budget-bounded judge pass folded into the existing async `treatment_derivation_job`.
- A real `estimate_tool_cost` for `get_citing_opinions` (DE-344 first bite).
- P3 tripwire coverage for the new child table.

### Out of scope (deferred, each its own slice)
- **DE-360 cheap→capable escalation routing** — PR2 establishes the budget + `purpose='judge_treatment'` cost tag so calibration data accrues; the escalation loop (re-judge low-confidence passages with a capable model) is a follow-up.
- **Court-seniority re-rank** — needs a CourtListener court-code → seniority map; deferred as a DE. PR2 prioritizes by recency (the stored order).
- **Whole-opinion fallback** for low-confidence snippet classifications — deferred as a DE.
- **Trace UI** for the classification (the PR1-UI analog for PR2) — its own web slice after this backend lands.
- **Refresh/staleness re-derivation surfacing** beyond PR1's existing 30-day TTL.

---

## 2. The keystone: snippet localization + the P3 ruling

To classify how citing opinion *B* treats case *X*, the judge needs *B*'s text where it discusses *X*. PR1 stores only refs (`cluster_id, opinion_id, case_name, court, date_filed`) — no text. CourtListener's `/search/?q=cites:(X)` returns a `snippet` (a highlighted excerpt around the citing match) that the gateway op currently discards. **PR2 judges that snippet.** Treatment language ("we decline to follow", "overruled", "we are not persuaded by") sits adjacent to the citation, which is exactly what the snippet captures. No per-citing-opinion materialization egress — honoring ADR 0019 D4/D10 ("phase the cost in").

### The P3 ruling (load-bearing, maintainer-confirmed 2026-06-26)

ADR 0019 D7 / ADR 0016 P3 forbid raw opinion payload in the index — the passage is to be "read from the content layer at trace time." The snippet model has **no materialized citing opinion** to read at trace time. Resolution:

> **Persist the derived artifacts, never the raw snippet.** Each `citation_treatment_signal` row stores `citing_opinion_id`, `classification`, `confidence`, and the **judge's short justification** — our *derived reasoning* ("the citing court expressed doubt about X's holding"), not opinion payload. The raw snippet is **transient** input to the judge at derivation time and never lands in the index. The (future) trace UI shows classification + judge reasoning + a **link out to the opinion on CourtListener** for the full passage.

This keeps `citation_treatment_signal` P3-clean (derived classifications + reasoning, same posture as PR1's refs-only JSONB). The judge prompt **instructs the judge to describe the treatment rather than quote the opinion**, so the persisted justification is our derived artifact. The new child table joins the ADR 0016 P3 no-raw-payload tripwire in this PR.

---

## 3. Components

### 3.1 Gateway — extend `get_citing_opinions` (security-gated, `gateway/**`)
- Add `snippet` to each citing result in `_get_citing_opinions` (`gateway/app/providers/tool/courtlistener.py`). CourtListener returns it on `/search/` opinion results; map the upstream snippet/highlight field, defensively (absent → `None`).
- Add a **real** `estimate_tool_cost` for `get_citing_opinions` (currently `Decimal(0)`) — a small per-call metered-egress estimate so the R4 economic brake can read it (DE-344 first bite). Value + where R4 reads it pinned in the plan.

### 3.2 API — the treatment judge (`api/app/citation/`)
- **New** `treatment_judge.py`:
  - `build_treatment_judge_prompt(*, cited_case_name, snippet)` — new system prompt; output contract `{"treatment": <one of 7 classes>, "confidence": "high|medium|low", "justification": "<≤2 sentences, describe don't quote>"}`. Conservative calibration: when uncertain between a negative class and `neutral`, **prefer `neutral`** (a false "overruled" is worse than a missed one — mirrors the cascade's conservative bias, inverted toward non-alarm).
  - `parse_treatment_response(response) -> TreatmentJudgment | None` — new parser (the existing `_parse_judge_response` hard-codes `yes/partial/no`; not reused). Returns `None` (skip, classify nothing) on malformed JSON / unknown class / unknown confidence / gateway error — never raises.
  - `judge_treatment(*, cited_case_name, snippet, gateway, judge_model) -> TreatmentJudgment | None` — one structured-JSON call, `purpose='judge_treatment'`, `temperature=0.0`, `anonymize=False`, `max_tokens≈400`.
  - `estimate_treatment_cost_usd(db, *, judge_model)` — reuses `estimate_judge_call_cost_usd(purpose='judge_treatment')`; snippet is short + fixed-ish, so no opinion-length scaling (unlike `case_content_judge`).
- **`TreatmentJudgment`** dataclass: `classification: str`, `confidence: float` (via `_CONFIDENCE_MAP`), `justification: str`.
- **Rollup** (`treatment.py` or a small `treatment_rollup.py`): pure function `roll_up(signals) -> (strongest_negative_class | None, per_class_counts, case_confidence)`. Severity order `overruled > superseded > criticized > questioned > distinguished`; non-negative `followed`, `neutral`. Case confidence = strongest-negative contributor's confidence + `min(0.05·(K−1), …)` corroboration bump, capped `0.95`. Pure + unit-tested.

### 3.3 API — extend the derivation (`api/app/citation/treatment.py`)
`derive_treatment_for_message` (PR1) gains a judge pass **after** the graph upsert, per cited cluster:
1. Take the stored `citing_opinions` (already capped 30, recency-sorted); select **top-N=10**.
2. **Pre-flight budget:** `estimate_treatment_cost_usd × N ≤ per-case budget (~$0.25)`; if the full pass would exceed it, judge as many as the budget allows (greedy, in priority order) and stop — never abandon the graph signal.
3. For each selected citing opinion with a non-empty snippet: `judge_treatment(...)`; on a real classification, write a `citation_treatment_signal` child row. Per-passage non-fatal (logged, skipped) — mirrors PR1's per-case posture.
4. Compute the rollup; write `strongest_negative_class`, `judged_count`, `judge_as_of` onto the parent; set `derived_method='citation_graph+judge'`.
- **Idempotent / refresh-safe:** re-derivation deletes-and-replaces this cluster's child signals (or upserts by `(treatment_id, citing_opinion_id)`), so a stale-TTL refresh re-judges cleanly. Pinned in the plan.

### 3.4 Worker wiring (the integration risk)
PR1's `treatment_derivation_job` is **async in the arq worker** and graph-only — it has no `GatewayClient`. PR2's judge needs a gateway **in the worker**. Resolution (settle in the plan, recommended path): construct/inject a `GatewayClient` + resolve the operator's treatment-judge model inside the job, exactly as the chat-send path resolves it for B1b, gated so a worker without gateway config degrades to **graph-only** (PR1 behavior) rather than failing. The judge pass is strictly additive: no gateway / no judge model / no snippet → the PR1 graph row stands unchanged.

### 3.5 Schema (migration 0062)
- **New** `citation_treatment_signal`: `id` (uuid pk), `treatment_id` (uuid FK → `citation_treatment.id`, `ON DELETE CASCADE`), `citing_opinion_id` (bigint), `classification` (text, CHECK ∈ the 7 classes), `confidence` (float), `justification` (text), `created_at`. Unique `(treatment_id, citing_opinion_id)`. **No snippet column** (P3). Add to `_AUDIT_MODELS` P3 tripwire.
- **Alter** `citation_treatment`: add `strongest_negative_class` (text, nullable, CHECK ∈ negative classes), `judged_count` (int, nullable), `judge_as_of` (timestamptz, nullable); relax `chk_citation_treatment_method_values` → `IN ('citation_graph', 'citation_graph+judge')`.

### 3.6 Read path
`resolve_ledger_entries` (`ledger.py`) extends the `treatment` object it already exposes on `/chats/{id}/ledger` with the rollup fields + the per-signal child rows (batch-loaded by `treatment_id`, no N+1). Additive; existing graph-only consumers see the new fields as null/empty.

---

## 4. Data flow

```
turn finalize (×3 sites, unchanged)
  └─ treatment_derivation_job (arq, async, off critical path)        [PR1]
       └─ derive_treatment_for_message
            ├─ per cited cluster: graph upsert (cited_by_count, refs) [PR1]
            └─ JUDGE PASS (new):                                      [PR2]
                 ├─ select top-N=10 citing (recency)
                 ├─ pre-flight budget gate (~$0.25/case)
                 ├─ per citing op w/ snippet → judge_treatment
                 │     └─ write citation_treatment_signal child row
                 ├─ roll_up(signals) → strongest-negative + counts + confidence
                 └─ parent: strongest_negative_class, judged_count,
                            judge_as_of, derived_method='citation_graph+judge'

read: GET /chats/{id}/ledger
  └─ resolve_ledger_entries → treatment{ graph + rollup + signals[] }  (no N+1)
```

## 5. Error handling & conservative posture
- Per-passage judge failure (gateway error, malformed JSON, unknown class) → **skip that passage**, never raise; the case keeps its graph signal + whatever passages succeeded.
- Budget exhausted mid-pass → judge what the budget covered, mark `judged_count` accordingly; the rollup reflects only judged passages ("derived from N of M citing opinions").
- No snippet on a citing result → skip (cannot localize) — counts toward neither negative nor neutral.
- Worker without gateway/judge-model config → graph-only (byte-identical to PR1).
- Calibration bias: judge prefers `neutral` over a negative class on uncertainty (a false negative-treatment flag is the worse error for a derived validity signal).

## 6. Testing
- **Unit:** new prompt builder shape; `parse_treatment_response` across all 7 classes + every malformed/unknown path → `None`; `roll_up` severity ordering + corroboration-bump + cap (pure, exhaustive); budget pre-flight greedy selection; cost estimator.
- **Integration (throwaway pgvector):** `derive_treatment_for_message` judge pass writes child rows + rollup; idempotent re-derivation; per-passage non-fatal; graph-only degradation with `gateway=None`; CHECK-constraint coverage on the new columns; `/ledger` read exposes the rollup + signals.
- **Gateway:** `get_citing_opinions` returns `snippet`; `estimate_tool_cost` non-zero.
- **P3:** tripwire asserts `citation_treatment_signal` holds no opinion payload.
- **CI gate (LESSON):** Task-6 must run api `mypy app` (whole-app) + `ruff format --check` per-subsystem, gateway `mypy app` + `ruff format --check`, both full suites. Not per-file.

## 7. Open items for the plan (not the brainstorm)
- Exact per-case budget value + `estimate_tool_cost` value for `get_citing_opinions` + R4 read site (DE-344).
- The upstream CourtListener snippet field name + its emptiness behavior (verify live or via fixture).
- Worker gateway-client construction vs. injection.
- Child-signal refresh strategy (delete-replace vs upsert) on TTL re-derivation.

## 8. Decisions log (this spec)
- **Localization:** search snippet, not whole-opinion materialization (cost; ADR 0019 D4/D10).
- **P3:** persist derived classification + confidence + judge justification; never the raw snippet; trace links out to CourtListener.
- **Prioritization:** recency-first, cap N=10, per-case budget; court-rank re-rank → DE.
- **Schema:** child `citation_treatment_signal` table + parent rollup columns.
- **Escalation (DE-360):** deferred; PR2 tags `purpose='judge_treatment'` so calibration accrues.
- **Rollup:** most-severe-class present + per-class counts; confidence = strongest-negative confidence + corroboration bump (cap 0.95).
