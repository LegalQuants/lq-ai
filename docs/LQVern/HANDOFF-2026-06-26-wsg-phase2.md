# Handoff — 2026-06-26 — Phase 2 underway: WS-G validity/treatment layer

`main` (LegalQuants + tucuxi, both == **`b08e178`**) at session end. Everything below is **merged to `main`** unless marked otherwise. Next migration = **`0062`**. Next DE = **DE-365**.

---

## ⭐ SESSION-START NOTE — read first

**Phase 1 (Citation Ledger + fiduciary gate) is COMPLETE and merged.** **Phase 2 is underway** — first workstream is **WS-G, the transparent validity/treatment layer** (the KeyCite analog, done as *derive-don't-assert*). **ADR 0019** is accepted+merged. **WS-G PR1** (the citation-graph backend) is merged. **WS-G PR1-UI** (#234) is built + reviewed + CI-passing the web check — **finish it first** (one mechanical step, below), then the next real work is **WS-G PR2** (the treatment-classifying judge).

### Immediate first action — finish WS-G PR1-UI (#234)
- **PR #234** (`feat/wsg-pr1-ui-treatment-trace`, head `27f5d0a`) — renders the treatment signal in the C1 trace. **Web-only, NOT security-gated → self-merge after CI.** At handoff: **Web check GREEN**; API + Gateway checks were still running (they run the full suites repo-wide even for a web-only diff).
- **Do:** `gh pr checks 234 --repo LegalQuants/lq-ai` → when all three green, `gh pr merge 234 --repo LegalQuants/lq-ai --squash --delete-branch`, then fast-forward local main + **mirror** `git push tucuxi origin/main:main` and confirm `origin==tucuxi`. Delete the local branch.
- If CI fails: it'll be the repo-wide `mypy app` / `ruff format --check` gate, not the web logic (the web diff is tested + svelte-check-clean). Same class of miss as WS-G PR1's CI round-1 — see the LESSON below.

### Then — WS-G PR2 (the treatment-classifying judge) — brainstorm → spec → plan → SDD
- **Goal:** classify each citing passage `followed / distinguished / criticized / questioned / overruled / superseded / neutral` and roll up to a **strongest-negative** case-level signal, over a **prioritized, capped** subset of the citing opinions PR1 already stores. **Security-gated** (judge egress + citation surface) → no self-merge. First proving ground for **DE-360** (cheap→capable escalation) and where **DE-344 / R4** budget enforcement becomes real.
- **Reuse:** the judge rails (`_JudgeGatewayProtocol`, `build_judge_prompt`, `_parse_judge_response`, the cost estimator, `case_content_judge.py` as the whole-opinion analog) — but a **new prompt + verdict schema** (the existing judge speaks `yes/partial/no`, not treatment classes). PR1's `citation_treatment` table is designed to **extend** (add nullable judge-classification + rollup columns / a child table; new `derived_method` values; the `chk_citation_treatment_method_values` CHECK currently allows only `'citation_graph'` → relax it). Read the WS-G PR2 open questions in ADR 0019 §"Open questions" (prioritization ranking, rollup/confidence aggregation, citing-passage localization).
- **Spec/plan dir:** `docs/superpowers/{specs,plans}/`. Brainstorm forks → AskUserQuestion. SDD per-task reviews + **Opus whole-branch review** (it has caught a real defect on every slice this milestone).

### Two DEs committed to land before Phase 2 closes (do NOT let them slip)
- **DE-363** — WS-G lazy-on-trace-open treatment fallback (PR1 ships async-only; null treatment renders nothing). PRD §9.
- **DE-364** — per-cluster `begin_nested()` SAVEPOINT isolation in `derive_treatment_for_message` (concurrent same-uncached-case `flush` IntegrityError poisons the session → multi-cluster turn loses remaining derivations; non-crashing, DE-363-recoverable). PRD §9. From the WS-G PR1 Opus review.

### After WS-G — the rest of Phase 2 (each ADR-first)
- **WS-D** — plain-language matter intake → agentic session (on the autonomous layer; reuses PHASE_GRANTS + brakes).
- **WS-E** — content-source registry + free-source expansion (GovInfo/EUR-Lex/SEC EDGAR); forces R4 economic brake real (DE-344).
- **WS-F** — MCP-server *ingress* (Phase 3; largest new security surface; ADR-gated). Stays last.

---

## What shipped this session

| Item | What | Squash / head | Gated |
|---|---|---|---|
| #231 | **P1-B1c** — caselaw FAIL tier via H3 attribution (closed Phase 1) | `efc1611` | sec ✓ |
| #232 | **ADR 0019** — validity/treatment layer (accepted) | `a2360fe` | docs |
| #233 | **WS-G PR1** — citation-graph treatment signal (backend, mig 0061) | `b08e178` | sec ✓ |
| #234 | **WS-G PR1-UI** — treatment signal in the C1 trace (web) | head `27f5d0a` | — (web; **merge-pending CI**) |

Each non-trivial slice: brainstorm (forks → AskUserQuestion) → spec → writing-plans → subagent-driven-development (per-task spec+quality reviews + an **Opus whole-branch review**) → PR. Specs/plans dated `2026-06-26` under `docs/superpowers/{specs,plans}/`. ADR at `docs/adr/0019-transparent-validity-treatment-layer.md`.

## WS-G state (the active workstream)

```
ADR 0019  validity/treatment layer ........ ACCEPTED + MERGED (#232)
WS-G PR1  citation-graph signal ............ MERGED (#233, mig 0061)
WS-G PR1-UI  C1 trace render ............... BUILT, PR #234 (merge when CI green)
WS-G PR2  treatment-classifying judge ...... NEXT (security-gated; DE-360 + DE-344 first bite here)
DE-363 / DE-364 ............................ before Phase 2 closes
```

**What's on `main` today (PR1):** when an assistant turn cites a case, an arq job (`treatment_derivation_job`, enqueued best-effort after `_audit_message_sent` at all **3** finalize sites) derives the case's citation-graph signal **off the turn's critical path** — `get_citing_opinions` CourtListener op (Search API **`cites:(opinion_id)`** filter, `order_by=dateFiled desc`, capped N=30, `cited_by_count`=upstream total) → `derive_treatment_for_message` (`api/app/citation/treatment.py`: per-cited-case cache-reuse-or-fetch, 30-day TTL, in-place upsert, **per-case non-fatal**, `flush` not `commit`) → upserts a `citation_treatment` row (mig 0061; keyed by `cluster_id`; JSONB `citing_opinions` = **refs only**, P3, in the `_AUDIT_MODELS` tripwire) → links the turn's caselaw ledger entries' `treatment_id`. `resolve_ledger_entries` resolves it into a `treatment` object on the `/chats/{id}/ledger` read (no N+1). **Gate-independent** — treatment never affects the fiduciary verdict (ADR 0018 D3 / 0019 D2). **No LLM** (judge is PR2). PR1-UI (#234) renders it as a muted, neutral "⚖ Cited by N · derived <date>" line + 5-preview disclosure — **no validity coloring** (anti-overclaiming, ADR 0019 D1).

## Workflow reminders (load-bearing)

- **Branch off `main`** (never commit on `main`); push feature branches to **origin + tucuxi**; after a PR merges, **mirror `origin/main → tucuxi main`** (`git push tucuxi origin/main:main`) and confirm `origin == tucuxi`. Planning docs (spec/plan/ADR) commit on the feature branch.
- **Security review per CODEOWNERS** for `gateway/**`, `api/app/citation/**`, `chats.py`, auth/authz/audit/crypto — Kevin/security merges; **Claude does NOT self-merge gated branches.** **Docs-only + `web/`-only PRs are NOT gated** (self-merge after CI).
- **Tests via host venv + a throwaway pgvector** (conftest auto-migrates): `lqai-test-pg` on `:55432`, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test`. Mocked gateway/fetch in tests → **no `-m provider`**. **NEVER** host `alembic upgrade` the dev DB (port 15432). **Next migration = `0062`.**
- **CI gate — LESSON from WS-G PR1 (cost a CI round):** the Task-6 "full gates" step must run, for `api/`, **`mypy app` (whole-app, NOT just per-file)** AND **`ruff format --check`** per subsystem (not just `ruff format <file>`), plus the gateway `mypy app` + `ruff format --check gateway`. CI runs these repo-wide; per-file checks miss (1) a whole-app mypy error from a new module's nullable type flowing through a `dict.get`, and (2) an unformatted *test* file when only the *app* file was formatted.
- **web has no Svelte component-test harness** — put logic in pure, **Vitest**-tested helpers (`web/src/lib/lq-ai/citations/*.ts`); keep `.svelte` thin (`npm run check:lq-ai` svelte-check only). For a visual claim, a throwaway **headless-Chrome** render of a static HTML mock of the component's exact markup + local CSS is cheap real evidence (`"/Applications/Google Chrome.app/.../Google Chrome" --headless=new --screenshot=out.png file://mock.html`). **CSS must be defined locally** in the component (Svelte scopes `<style>` per component — the recurring P1-C1 bug). **Don't run repo-wide `npm run format`** (rewrites 161 unrelated files) — format only touched files with `npx prettier --write <files>`. The 5 svelte-check WARNINGS / 3 FILES_WITH_PROBLEMS are **pre-existing** (ComingSoonModal, SkillDetailTabs, TierFloorOverrideModal) — not ours; CI gates on 0 ERRORS only.
- **Opus for the final whole-branch review** — it has caught a real gate-passing defect on every slice this milestone (P1-C1 CSS scoping; P1-B1b config/cost; P1-B1c false-FAIL on judge-output noise; WS-G PR1 concurrency session-poisoning → DE-364; WS-G PR1-UI broken `aria-expanded` button). Worth the cost every slice.
- Commits: `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. SDD ledger lives at `.superpowers/sdd/progress.md` (git-ignored scratch).

## Pointers
- Strategy: `docs/proposals/fiduciary-grade-agentic-legal-work.md` (Phase 2 = WS-D/E/G; Phase 3 = WS-F)
- ADR: `docs/adr/0019-transparent-validity-treatment-layer.md` (D1–D10; §Open questions = WS-G PR2 inputs)
- WS-G PR1 spec/plan: `docs/superpowers/{specs,plans}/2026-06-26-wsg-pr1-citation-graph-treatment*`
- WS-G PR1-UI spec/plan: `docs/superpowers/{specs,plans}/2026-06-26-wsg-pr1-ui-treatment-trace*`
- Memory: `project-fiduciary-grade-milestone` (current state), `MEMORY.md` index
- Prior handoff: `docs/LQVern/HANDOFF-2026-06-26-fiduciary-phase1-p1b1c-kickoff.md`
