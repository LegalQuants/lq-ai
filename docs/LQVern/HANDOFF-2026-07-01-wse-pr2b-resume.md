# HANDOFF — WS-E PR2b (EUR-Lex authority source), resume mid-SDD

**Written:** 2026-07-01. **For:** the next Claude Code session resuming WS-E PR2b.
**Branch:** `feat/wse-pr2b-eurlex-authority` (off `main` @ `c11e62e`). Pushed? **NO — not yet pushed to any remote.**

## Session-start
Read, in order: this file → the plan `docs/superpowers/plans/2026-07-01-wse-pr2b-eurlex-authority.md` (authoritative task detail) → the spec `docs/superpowers/specs/2026-07-01-wse-pr2b-eurlex-authority-design.md` → the SDD ledger `.superpowers/sdd/progress.md` (git-ignored scratch; may be absent in a fresh clone — this handoff restates its essentials). You are executing the plan via **superpowers:subagent-driven-development** (fresh implementer per task + two-stage review + Opus whole-branch review at the end).

## What this PR is
Add **EUR-Lex** as the 3rd free authority source (after GovInfo + SEC EDGAR), **get_authority-by-CELEX only**, on the generic ADR-0021 registry + `retrieve_authority` + verify path. Completes WS-E PR2's "≥2 new free sources." **No new ADR** (ADR 0021 D6 scopes it), **NO migration**, `gate.py`/`ledger.py`/`alembic` untouched. **Security-gated** (gateway egress + citation surface + shared chat schema) → Kevin/security merges, NO self-merge, mirror origin→tucuxi after.

## Progress (from git — durable)
- **Task 1 DONE + review-clean** — commit `3bc2249` "feat(gateway): EUR-Lex tool adapter (get_authority by CELEX)". Gateway `EurLexToolAdapter`: Cellar content-negotiation, User-Agent auth (no key), manual redirect-follow with **http→https upgrade + per-hop SSRF re-validate** (egress is https-only), unsafe-CELEX reject pre-egress, CELEX→content_kind. Reviewer Approved; 2 Minors deferred to final review: (a) `eurlex.py` dead `except EgressRefused: raise` no-op; (b) non-live `health_check`.
- **Task 2 COMMITTED `16c6a39` "feat(research): EurLexAdapter + SOURCE_REGISTRY eurlex entry (get-only)" — REVIEW STILL PENDING.** Thin backend adapter + `SOURCE_REGISTRY["eurlex"]` (`ops=("get_authority",)`, content_kinds eu_regulation/eu_directive/eu_decision/eu_caselaw/eu_legislation) + tests in `api/tests/test_source_registry.py`. Focused gate was green (3 eurlex + 35 consumer tests; ruff/format/mypy clean). No `task-2-report.md` was written (implementer stalled then committed on a retry).

## RESUME HERE (exact next steps)
1. **Review Task 2 first** (it was committed but never reviewed). Generate the package and dispatch a task reviewer (sonnet), diff-only (no report exists):
   `<sdd-skill>/scripts/review-package 3bc2249 16c6a39` → dispatch `task-reviewer-prompt.md` with the printed path + the Task 2 brief (regenerate via `scripts/task-brief <plan> 2`) + the Global Constraints from the plan. Fix any Critical/Important; record Minors.
2. **Then Tasks 3, 4, 5** per the plan (fresh implementer each; sonnet; two-stage review):
   - **Task 3** — per-op chat tool schemas in `api/app/chat/tool_schemas.py`: a source appears under `search_authority`/`get_authority` only if its registry `ops` include that op → EUR-Lex (get-only) shows only `get_authority`; GovInfo/EDGAR (both) unchanged. **Behavior-preserving; existing GovInfo/EDGAR schema tests must stay green.** (This is the one shared-code touch — Task 3's brief has the target behavior + tests; the exact refactor adapts to the current `build_authority_tool_schemas` signature.)
   - **Task 4** — add the 5 `eu_*` kinds to `_VERIFIABLE_CONTENT_KINDS` in `api/app/citation/authority.py` + a verify test with `content_kind="eu_regulation"`.
   - **Task 5** — `gateway.yaml.example` `eurlex-prod` block + PRD WS-E status; **file DE-374** (EUR-Lex SPARQL full-text search) + **DE-375** (treaty/corrigendum CELEX support). (Next unused DE = DE-374.)
3. **Final gates** (see plan's Final-gates section): `git diff --name-only main..HEAD` shows NO gate.py/ledger.py/alembic; full **DB-backed SOLO** api suite with `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test` (the REAL gate — unset = hollow skip-green); ruff/format/mypy from root; gateway suite + mypy --strict; confirm **DE-373 drift-guard `test_openapi_export` stays green** (EUR-Lex adds no route → export unchanged); `test_openapi`/`test_endpoints` path counts unchanged.
4. **Opus whole-branch review** (most capable model) — triage the accrued Minors (Task 1 a/b above + any from Tasks 2-5). Fix Critical/Important.
5. **Sync main into branch** (pick up anything new), push origin+tucuxi, open the **security-gated PR** (Kevin merges, NO self-merge), watch CI, mirror origin→tucuxi, delete branch. Update memory `project-fiduciary-grade-milestone` to PR2b MERGED.

## Load-bearing invariants (do not regress)
- EUR-Lex auth = User-Agent, no key; host allowlist `[publications.europa.eu]`; skip_anonymization=True; read_only=True; free → R4 no-op.
- Egress https-only (`validate_egress_target` refuses non-https); Cellar 303 target is http → adapter upgrades to https + re-validates each hop; NEVER httpx auto-follow.
- external_ref = plain CELEX, `^[A-Za-z0-9._-]+$`; treaty/corrigendum CELEX rejected at gateway (DE-375).
- content_kind derived from CELEX in the gateway adapter, carried through by the backend adapter; all 5 eu_* kinds must be in `_VERIFIABLE_CONTENT_KINDS` or quotes silently drop.
- Verified live (2026-07-01, https): `GET publications.europa.eu/resource/celex/{CELEX}` + `Accept: application/xhtml+xml` + `Accept-Language: eng` (MANDATORY) → 303→http manifestation → upgrade https → 200 xhtml; missing CELEX → 404.

## Process lesson from this session
An implementer subagent left Task 2 **uncommitted** on its first stop AND spawned an **orphaned full-suite pytest** (DE-368 hazard). Always, after an implementer returns: `git log`/`git status` to confirm the commit landed, and `pgrep -fl pytest` to catch an orphaned suite, before dispatching the next agent. Task-notifications can fire more than once for the same agent.

## Repo pins
main @ `c11e62e`; branch head `16c6a39` (4 commits off c11e62e: spec 5310481, plan 8cf6fef, T1 3bc2249, T2 16c6a39). origin==tucuxi==c11e62e. Test DB: throwaway pgvector `lqai-test-pg` :55432.
