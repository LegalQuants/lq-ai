# Session Handoff — 2026-05-21 (night) — M3-C1 shipped + M3-C2 substrate ready → cost.py + executor next

> **Purpose:** Context transfer for the next session. The 2026-05-21 night session executed the reconciliation that brought M3-A6 onto `main` (PR #61), opened a draft Phase C PR, and shipped two clean chunks of Phase C work: M3-C1 (`output_format: table` Skill mode, fully complete) and the M3-C2 backend substrate (migration 0036 + ORM + Pydantic schemas, CI-confirmed). The next session continues M3-C2 with the cost estimator + LangGraph executor + worker + endpoints.
>
> Read time: ~7 minutes. Detail lives in memory at `~/.claude/projects/.../memory/project_lq_ai_status.md` and in the Phase C prep doc on the feature branch.

---

## 1. State at handoff

| Branch / Tag | SHA | Meaning |
|---|---|---|
| `main` | `fa62142` | M3-A6 Easy Playbook wizard merged via PR #61 (this session's reconciliation work). Phase A is now on `main`. |
| `m3-phase-c-tabular-review` | `c0476e6` | Feature branch for Phase C. Three commits: prep doc + M3-C1 + M3-C2 substrate. **Draft PR #62 open against `main`** — single PR will land the full Phase C bundle (Decision C-8). |
| `v0.2.0` (tag) | `8a1b3fc` | Unchanged. v0.3.0 at M3-close. |
| `sync/m3-a6-to-main` | `e901f8a` | Source branch for PR #61 (preserved per branch-preservation policy). |
| `m3-development` | `a7aa719` | Still on origin at the pre-reconciliation tip per branch-preservation policy; functionally superseded by `main`'s `fa62142`. Historical archive only — do NOT branch new work off it. |

---

## 2. What shipped this session

### 2.1 Reconciliation — PR #61 squash-merged to `main` (`fa62142`)

Brought the M3-A6 Easy Playbook wizard (PR #57's squash commit `a7aa719`) onto `main`. **Path chosen: cherry-pick** onto a sync branch (`sync/m3-a6-to-main`) rather than the literal `m3-development → main` merge in the prior handoff. Rationale:

| Path | Conflicts | Side effects |
|---|---|---|
| Literal `m3-development` → `main` merge | 12 files (many `add/add` from squash-merge history divergence) | Drags `37aadac` stale pre-PR-#58 handoff doc onto `main` |
| Cherry-pick `a7aa719` onto sync branch (chosen) | 4 files (clean) | Pure M3-A6 delta; `m3-development` untouched on `origin` |

**Four conflict resolutions made** (load-bearing — verify against PR #61's diff if you need to audit):

1. **`api/tests/test_endpoints.py`** — merged IMPLEMENTED_ROUTES to include both PR #59 Word add-in routes AND M3-A6's 5 new playbook routes (POST/PATCH/DELETE `/playbooks` + 2 `/playbooks/easy`).
2. **`api/tests/test_openapi.py`** — kept both comment blocks; updated `assert len(actual) == 83` (NOT 86 — M3-A6's CRUD methods share existing paths from M3-A4's GET endpoints; only the two `/easy` endpoints are net-new paths). Fixed in commit `e901f8a` after CI surfaced the off-by-three.
3. **`docs/PRD.md` §9** — inserted DE-284/285/286 (M3-A6 follow-ons) numerically before DE-287/.../DE-295 (PR #58 + PR #59's descope DEs). No content lost from either side.
4. **`docs/architecture.md` §M3** — kept HEAD's plumbing-only Slack/Teams framing + Word add-in delivery-flow paragraph; added the `arq-worker` infrastructure bullet from M3-A6.

### 2.2 Phase C prep doc — `ad11040` on `m3-phase-c-tabular-review`

`docs/superpowers/plans/2026-05-21-m3-phase-c-tabular-review.md` (203 lines). **10 design decisions locked** at Phase C kickoff. Compact list (full rationale in the prep doc itself):

| # | Choice |
|---|---|
| C-1 | `lq_ai.output_format: table` + `lq_ai.columns: [{name, query, ensemble_verification?, minimum_inference_tier?}]`; untyped cells; validator in existing `api/app/skills/schema.py` (no new `validators.py` — was a M3 plan doc nit, fixed). |
| C-2 | Hybrid citation surface: chip in each cell + click opens existing M2-C2 `CitationDrawer` (no new component). |
| C-3 | Always ARQ; reuse existing `arq:m3a6` queue (rename constant `M3A6_QUEUE_NAME → M3_PLAYBOOK_QUEUE_NAME` with backward-compat alias; queue string stays `arq:m3a6`). |
| C-4 | `openpyxl ≥ 3.1.0` new dep for XLSX; CSV uses stdlib. |
| C-5 | Cost-preview modal matching M3-A4 `PlaybookExecuteModal`; $1.00 confirmation-checkbox threshold. |
| C-6 | Migration `0036_tabular_executions.py` — schema includes 5-state enum, document_ids JSONB, results JSONB, cost-estimate-vs-actual, soft-delete, `parent_execution_id` self-FK. (**Shipped this session.**) |
| C-7 | 3-source document selection (KB / Project / free-pick); 200-doc cap via `LQ_AI_TABULAR_MAX_DOCS` deployment-config knob. |
| C-8 | Single PR for C1+C2+C3+C4 (Phase B precedent); split fallback at backend/UI seam if LOC exceeds ~5K by end of C2. |
| C-9 | Bulk ops spawn sibling `tabular_executions` rows with `parent_execution_id` FK; original grid is immutable; results render as tabs on the result view. |
| C-10 | Failed cells render as italic "not found" + amber chip + drawer-on-click; distinct from Citation Engine's red-unverified state. |

### 2.3 M3-C1 — fully shipped at `b3e1b82` on `m3-phase-c-tabular-review`

| Surface | Substance |
|---|---|
| `api/app/skills/schema.py` | New `ColumnSpec` Pydantic model (required `name` + `query`; optional `ensemble_verification` + `minimum_inference_tier` bounded 1-5). `LQAIFrontmatter.columns: list[ColumnSpec] \| None`. Cross-field `model_validator` enforces `output_format == "table"` requires non-empty `columns`. Exported via `__all__`. |
| `api/tests/test_skill_table_mode.py` | 13 unit tests (TDD-driven; 3 cycles RED→GREEN; all green locally + on CI). Covers ColumnSpec creation, LQAIFrontmatter.columns parsing, full SkillFrontmatter table-mode parse, cross-field validation, derive_summary surface. |
| `skills/contract-snapshot/SKILL.md` | Reference skill — 4-column NDA grid (Term / Survival / Carveouts / Governing Law). Demonstrates both per-column overrides (`ensemble_verification: true` on Survival, `minimum_inference_tier: 3` on Governing Law). Carries Decision F disclaimer + fork-and-tune guidance for community contributors. Loader smoke verified 12 skills load including this one. |
| `docs/skill-authoring-guide.md` | New Table-mode section with worked example + constraints + reference-skill pointer. |
| `docs/PRD.md` §3.4 | Frontmatter snippet adds `columns:` comment; new paragraph explains table mode + per-column overrides + loader rejection of malformed skills. |
| `docs/api/backend-openapi.yaml` | New `ColumnSpec` schema; `Skill` detail gains `columns` field (nullable, items: ColumnSpec). |
| `docs/M3-IMPLEMENTATION-PLAN.md` | §M3-C1 doc nit fixed (`api/app/skills/validators.py` → `api/app/skills/schema.py`). |

**CI: green on all three jobs** (PR #62 first CI run after M3-C1 push).

### 2.4 M3-C2 substrate — committed at `c0476e6` on `m3-phase-c-tabular-review`

The persistence + wire-shape foundation for the Tabular Review backend. Shipped as its own commit so CI could exercise the migration independently before the heavier executor work lands.

| File | Substance |
|---|---|
| `api/alembic/versions/0036_tabular_executions.py` | Single new table. 5-state status enum (`pending → running → completed \| failed \| cancelled`). `document_ids` ARRAY[UUID] (not FK; matches M3-A6 pattern). `skill_name` text NULL (skills are filesystem-canonical, not DB-backed). `columns` JSONB snapshot. `results` JSONB nullable. `cost_estimate_usd` + `cost_actual_usd` Numeric(10,4). `parent_execution_id` UUID self-FK NULL (bulk-op siblings; Decision C-9). `deleted_at` soft delete. Two partial indexes: `(user_id, created_at DESC) WHERE deleted_at IS NULL` and `(parent_execution_id) WHERE parent_execution_id IS NOT NULL`. |
| `api/app/models/tabular.py` | `TabularExecution` ORM model mirroring the migration column-for-column. 15 columns confirmed match migration order via local smoke. |
| `api/app/models/__init__.py` | `TabularExecution` registered + exported via `__all__`. |
| `api/app/schemas/tabular.py` | Pydantic wire shapes: `ColumnSpec` (mirrors skills-side but independently versioned), `Citation`, `CellResult` (with `confidence: high\|medium\|low\|failed` per Decision C-10), `TabularRow`, `TabularResults`, `TabularExecutionCreate`, `TabularPreviewCost{Request,Response}`, `TabularExecutionResponse`, `TabularExecutionSummary`, `TabularBulkOpRequest`. |

**CI: green on all three jobs** (PR #62's second CI run after substrate push — including the load-bearing API job that runs alembic against a real Postgres as part of test setup).

---

## 3. What's queued for the next session — finish M3-C2

The substrate is in. The remaining M3-C2 work is the executor + cost + worker + endpoints, all built on top of the persisted shape that's now stable.

### 3.1 Cost estimator — `api/app/tabular/cost.py` (~1-2 hr, locally TDD-able)

**Pattern to mirror:** `api/app/citation/cost.py` (M2-E2 rolling-average estimator). Per Decision C-5, the tabular cost estimator:

- Queries `inference_routing_log` filtered by `purpose='tabular_extraction'` (new purpose value; gateway-side tagging arrives with the cell node implementation).
- Rolling average over the last 100 calls (or last 30 days, whichever cuts smaller).
- Cold-start fallback: `DEFAULT_PER_CELL_USD = Decimal("0.005")` (matches the M2-D1 conservative default; intentionally permissive so the pre-flight errs toward fallback).
- Cache TTL 300 sec (matches the M2-E2 + Anthropic prompt-cache horizon).
- Returns `(cells_count, estimated_tokens, estimated_cost_usd, per_tier_breakdown)` from a single `estimate_tabular_execution_cost()` entry point.

**TDD locally** (the local Python 3.13 environment can run pure pydantic + sqlalchemy unit tests, just not async DB integration tests — those need CI). Test the cold-start path, the rolling-average path with seeded routing-log rows, and the per-tier breakdown logic.

### 3.2 LangGraph executor + nodes + state — `api/app/tabular/{executor,nodes,state}.py` (~3-4 hr)

**Pattern to mirror:** `api/app/playbooks/executor.py` + `api/app/playbooks/nodes.py` + `api/app/playbooks/state.py` (M3-A2).

- `state.py` — `TabularExecutionState` Pydantic model carrying the in-flight workflow state (execution_id, document_ids, columns, partial results, current cell index, error transitions).
- `nodes.py` — `cell_extraction_node` (one cell extraction via Citation Engine; sets `purpose='tabular_extraction'` on the gateway call so M2-E2's cost calibration sees the new traffic) + `aggregation_node` (assembles per-cell results into the grid shape).
- `executor.py` — LangGraph `StateGraph` walking `documents × columns`. Status transitions persisted to `tabular_executions` row at each phase boundary.

**Local-test what you can:** node logic with mocked LLM calls (respx pattern in the project — see `api/tests/test_easy_playbook_extractor.py` for the M3-A6 precedent). Full executor integration needs the docker stack.

### 3.3 ARQ worker — `api/app/workers/tabular_worker.py` (~1.5 hr)

**Pattern to mirror:** `api/app/workers/easy_playbook_worker.py`. The new function:

```python
async def tabular_execution_job(ctx: dict[str, Any], execution_id: str) -> str:
    """Walk the execution's documents × columns via the LangGraph
    executor; persist progress + final results."""
```

Register in `app/workers/arq_setup.py` `WorkerSettings.functions` (alongside `noop_job` + `easy_playbook_generation_job`). Per Decision C-3, queue stays `arq:m3a6` — rename the constant `M3A6_QUEUE_NAME → M3_PLAYBOOK_QUEUE_NAME` with a backward-compat alias so in-flight Easy Playbook jobs aren't orphaned at deploy.

`app/workers/queue.py` gains `enqueue_tabular_execution_job(pool, execution_id)`.

### 3.4 API endpoints — `api/app/api/tabular.py` + register (~2 hr)

Six endpoints per Decision C-6:

- `POST /api/v1/tabular/preview-cost` — synchronous; returns the cost-estimator's output (cells_count + estimated_tokens + estimated_cost_usd + per_tier_breakdown).
- `POST /api/v1/tabular/execute` — request validates `confirmed_cost_usd` echoes the preview value; creates `tabular_executions` row; enqueues the worker job; returns 202 + execution_id.
- `GET /api/v1/tabular/executions` — list paginated, recent-first, soft-deleted excluded.
- `GET /api/v1/tabular/executions/{id}` — full state + grid results.
- `DELETE /api/v1/tabular/executions/{id}` — soft delete (sets `deleted_at`).
- `POST /api/v1/tabular/executions/{id}/cancel` — sets status to `cancelled`; worker checks the status on next cell-iteration boundary.

Register in `app/api/__init__.py`. Update `tests/test_endpoints.py` IMPLEMENTED_ROUTES + `tests/test_openapi.py` count (current count is 83 after M3-A6; tabular adds 6 method-tuples but only 4 unique paths — `/tabular/preview-cost`, `/tabular/execute`, `/tabular/executions`, `/tabular/executions/{id}` — so the path-count assertion becomes 87, NOT 89). The `/cancel` endpoint reuses the `/executions/{id}` path with a different action; depending on how it's structured (sub-resource or query-param), the count math may differ — count locally before pushing.

### 3.5 Integration tests + commit

Per the project test discipline:
- Unit tests for cost.py (TDD locally; commit alongside cost.py)
- Unit tests for executor nodes with mocked LLM (TDD locally)
- Integration tests for the endpoint surface (CI-only; needs FastAPI + real DB)
- Migration smoke (already covered by the substrate commit's CI run)

---

## 4. Sequenced next steps

1. **Read the prep doc** at `docs/superpowers/plans/2026-05-21-m3-phase-c-tabular-review.md` on the `m3-phase-c-tabular-review` branch. The 10 decisions are the contract for the rest of Phase C.
2. **Re-check PR #62 CI** before adding commits — confirm the substrate is still green on the latest `main` (in case main moved between sessions).
3. **Implement `cost.py` first** — smallest, locally TDD-able, no DB writes. Commit + push for CI confirmation.
4. **Then executor + nodes + state.** Mirror M3-A2 / M3-A6's structure. Most logic is local-testable with mocked LLM calls.
5. **Then worker + queue enqueue.** Update `arq_setup.py` to register the new job function; rename the queue constant per Decision C-3.
6. **Then endpoints.** Register in `app/api/__init__.py`. Update the two route-count tests carefully (count locally before pushing — the M3-C1 push had an off-by-three on the openapi count that surfaced only in CI).
7. **Per-commit ruff format AND ruff check both before push** (see `feedback_ruff_format_check.md`; CI runs them as separate gates).
8. **When all of M3-C2 lands green on CI**, pause for the next session to start M3-C3 (UI).

---

## 5. Operator-side action items outstanding

* **Corpus question for Phase E** (parked from this session; not blocking Phase C): existing 5 NDAs + 5 MSAs in `docs/quickstart/sample-*/` satisfy the M3-E1 documented verification criterion as-is. For a richer reviewing-attorney walkthrough, three optional corpus additions worth considering before fresh-install:
  - **Recommended:** 2-3 NDA variants with intentionally-missing clauses (no survival period, no carveouts list) — surfaces Decision C-10's "not found" rendering, which is the most credibility-sensitive UX state.
  - **Optional:** Sample DPA corpus (3-5 docs) + sample MSA-Commercial-Purchase corpus (3-5 docs) to demonstrate tabular works across the playbook families M3-A5 shipped.
  - **Stretch:** Larger 15-20 doc corpus for perf walkthrough of sticky-row + sticky-col grid renderer.

  Decide at Phase C close whether to schedule corpus generation before Phase E or defer to v0.3.1 / community contribution. Filed for next session decision.

* No code-signing cert procurement progress to report (DE-295 is community-led; no maintainer work in this session).

---

## 6. Memory references the next session should re-read first

* `~/.claude/projects/-Users-kevinkeller-Desktop-lq-ai/memory/project_lq_ai_status.md` (most recent block to be added: "Status end-of-session 2026-05-21 night — M3-C1 shipped on m3-phase-c-tabular-review; M3-C2 substrate ready").
* `~/.../memory/feedback_honest_framing.md` — surface scope changes as choices, not unilaterally absorb.
* `~/.../memory/feedback_ruff_format_check.md` — both ruff gates locally before push (CI's openapi count assertion bit us once this session; cheap pre-push counts beat CI surprise).
* `~/.../memory/feedback_migration_rebuild_all_workers.md` — when a migration lands (0036 already shipped), rebuild api + arq-worker + ingest-worker together. The next session's executor work will require the operator to rebuild after the worker registration changes.

---

## 7. What's NOT in scope for the next session

Per the conservative-posture rule, named explicitly:

* **No Phase D / E work** until Phase C lands cleanly.
* **No M3-C3 (UI) work** until M3-C2 is functionally complete (executor + worker + endpoints all working against the dev stack).
* **No M3-C4 (bulk ops + export) work** until M3-C3 is functionally complete.
* **No typed columns** — Decision C-1 holds; every cell is a string in v0.3.0.
* **No queue split** — Decision C-3 holds; `arq:m3a6` is shared between Easy Playbook and Tabular. Splitting is a DE if contention is measurable.
* **No corpus generation in this Phase C window** unless explicitly scheduled by Kevin.

---

## 8. What to say to the next CC session

Paste the following into the next CC session's first message:

> Resume the M3 work parked at the end of the 2026-05-21 night session.
>
> Read in order:
>
> 1. `~/.claude/projects/-Users-kevinkeller-Desktop-lq-ai/memory/project_lq_ai_status.md` (most recent block: "Status end-of-session 2026-05-21 night — M3-C1 shipped on m3-phase-c-tabular-review; M3-C2 substrate ready")
> 2. `docs/SESSION-HANDOFF-2026-05-21-night-m3-c1-shipped-c2-substrate-cost-next.md` (this doc)
> 3. `docs/superpowers/plans/2026-05-21-m3-phase-c-tabular-review.md` on the `m3-phase-c-tabular-review` branch (the prep doc; 10 design decisions locked)
>
> Then:
>
> - Checkout `m3-phase-c-tabular-review` (PR #62 draft is open against main).
> - Re-confirm CI on PR #62 is still green at the latest `main`.
> - Continue M3-C2 in this order: cost.py → executor + nodes + state → worker → endpoints → commit + push for CI on each chunk.
> - Pause for the next session to start M3-C3 once all of M3-C2 is green on CI.
>
> Estimated maintainer effort: ~6-10 hr to close M3-C2.

---

*End of handoff. Next session opens with continuing M3-C2 per §3 above. M3-C1 + substrate detail lives in this doc + memory; refer there rather than re-deriving from the diff.*
