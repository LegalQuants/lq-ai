# Handoff — 2026-06-05 — Donna-CC integration asks shipped; STANDBY

> **For:** the next session continuing on **`~/Code/lq-ai`** (canonical repo — NEVER `~/Desktop/lq-ai`; the Bash cwd resets to `~/Desktop` between calls, so **prefix every command with `cd ~/Code/lq-ai &&`**).
>
> **TL;DR:** v0.4.0 (M4) is shipped. Since the 2026-06-01 handoff, a run of **Donna-CC integration asks** landed on `main`. There is **no active build task** — this is a STANDBY/maintenance state. Donna CC is building the Automations frontend against the pinned `vendor/lq-ai` and keeps surfacing small, well-scoped backend asks; work them on the proven loop (below). This handoff supersedes `HANDOFF-2026-06-01-v0.4.0-shipped-donna-asks-done.md`.

---

## 1. Where things stand

- **`main` HEAD = `0097b01`** on both remotes (`origin` = LegalQuants/lq-ai, `tucuxi` = Tucuxi-Inc/lq-ai mirror — kept identical after every merge). Both services report `__version__ = 0.4.0`. **Migration head is now `0046`** (was 0045 at the prior handoff).
- Live dev stack: not rebuilt this session (work was test-driven against throwaway DBs). Acceptance data preserved — do **NOT** `docker compose down -v`.
- **The latest SHA to give Donna for any pin bump is `0097b01`** (it contains every ask below).

### What shipped this session (newest first — all squash-merged, branches preserved)

| PR | SHA | What | Merge path |
|---|---|---|---|
| #135 | `0097b01` | **Autonomous run findings surfacing** — new `autonomous_findings` table (migration `0046`, FK `ON DELETE CASCADE`) persisted at the `emit_finding` chokepoint; paginated owner-gated `GET /api/v1/autonomous/sessions/{id}/findings` (ASC emission order); `?source_session_id=` filter on `GET /memory` (precedents excluded — recurrence-aggregated) | self-merged (api/) |
| #133 | `fc832ca` | **Matter reassign + `project_id` ownership** — `project_id` on `AutonomousSchedule/WatchUpdate` (PATCH reassigns matter, null unassigns); validate caller-owns-project (404 id-probing-safe via `_load_owned_project`) at **all 5** assignment sites (create_schedule, create_watch, run-now `_spawn_manual_session`, both updates) — closed a pre-existing IDOR | **Kevin authz-reviewed** + merged |
| #130 | `35c8bb6` | `AutonomousSessionRead.max_cost_usd`/`cost_total_usd` `number/decimal → string` (Decimal serializes as JSON string at runtime) | self-merged (docs) |
| #129 | `69a0d35` | Sync `max_cost_usd` onto 6 autonomous schedule/watch OpenAPI schemas (contract drift — was only on `ManualRunRequest`) | self-merged (docs) |
| #128 | `29c1106` | **Runtime provider API-key management (BYOK)** — gateway `/admin/v1/provider-keys` (encrypt→persist gateway.yaml→hot-apply adapter, no restart) + backend `/api/v1/admin/provider-keys` is_admin proxy. Donna ask #7 | **Kevin gateway-security-reviewed** + merged |
| #127 | `541bd6f` | **Per-column `ensemble_verification` on tabular** — Stage-4 ensemble verify per cell + cost premium + `verification_method` surfacing. Donna ask #6 | self-merged (api/) |

(Earlier: #125 navigable tabular citations `c22360a`, plus #115–#120 the original Donna asks #1–3/P1.4 — see `HANDOFF-2026-06-01`.)

---

## 2. Donna integration ledger (what to tell Donna)

Donna bumps `vendor/lq-ai` then runs `npm run gen:api`. **Current pin target: `0097b01`.** Surfaces Donna now has:

- **Tabular ensemble** (#127): per-column `ensemble_verification` honored; cells carry `verification_method` (`ensemble_strict`/`ensemble_majority`); `preview-cost` returns `ensemble_cells_count` + `ensemble_premium_usd`. **CAVEAT:** the cell `verification_method` rides the free-form `results` blob (prose-documented) → `gen:api` won't emit it typed until **DE-330** (formalize tabular `results` components). The preview-cost fields ARE typed.
- **BYOK** (#128): `GET/POST/PATCH/DELETE /api/v1/admin/provider-keys` (is_admin). Write-only secret; GET returns `{provider, type, configured, last4, source: env|runtime}`. Errors: **400** master-key-unset, **404** unknown provider, **409** revoke-env-key. `ProviderKeyStatus` is a typed component.
- **Autonomous contract** (#129/#130): every autonomous cost field (`max_cost_usd` on schedules/watches/run-now/sessions, `cost_total_usd`) is uniformly typed `string` now.
- **Matter reassign** (#133): `project_id` on `AutonomousSchedule/WatchUpdate` → editable matter control. Unowned `project_id` on create/update/run-now → **404**.
- **Findings** (#135): `GET /api/v1/autonomous/sessions/{id}/findings` → `{findings:[{id,session_id,severity,title,content,created_at}], total_count, limit, offset}` (ASC emission order, owner-gated, paginated). `severity` is free-text (treat unknown as neutral badge). `?source_session_id=` on `GET /memory` for "memories this run proposed." `AutonomousFindingRead`/`ListResponse` are typed components.

---

## 3. How to work here — the proven loop (used for every ask this session)

1. **Branch off `main`** (`git checkout main && git checkout -b <type>/<name> main`).
2. **Verify the ask against the code first** — every ask this session had at least one premise that needed correcting or a broader blast-radius than reported (e.g. the `max_cost_usd` drift was 6 schemas not 2; the `project_id` gap existed on 3 create/run sites not just the update). Don't trust the report; grep + read.
3. **Surface genuine forks to Kevin** via `AskUserQuestion` BEFORE building — he makes all architectural/product/authz calls and prefers explicit options + a recommendation. Examples this session: findings persist-vs-audit + table-vs-JSON + endpoint shape; BYOK persistence (YAML vs DB) + masking; matter-reassign create-gap scope.
4. **Subagent-driven-development** (`superpowers:subagent-driven-development`): for each task, a fresh **implementer** subagent (full task text + scene-setting + the exact reuse-surface facts — they don't share your context), then an independent **spec-compliance** reviewer, then a **code-quality** reviewer. Apply fixes (fresh agent — `SendMessage` is NOT available in this env, so dispatch a fresh "complete/​fix" agent that reads the partial work). For multi-task features, a **final holistic review** across all commits before the PR. Trivial 1-file edits (e.g. a yaml field add): do inline, no subagent.
5. **Gates** (run yourself before pushing — fresh-validation catches what lint/types miss):
   - api: `cd ~/Code/lq-ai/api && export DATABASE_URL=postgresql+asyncpg://test:test@127.0.0.1:55432/lqai_test && .venv/bin/ruff format --check app tests && .venv/bin/ruff check app tests && .venv/bin/mypy app && .venv/bin/pytest <suites> -q`
   - gateway: `cd ~/Code/lq-ai/gateway && .venv/bin/ruff format --check app tests && .venv/bin/ruff check app tests && .venv/bin/mypy --strict app && .venv/bin/pytest -q` (gateway is mypy **--strict**)
   - web (if touched): `cd web && npm run check:lq-ai && npx vitest run`
6. **Commit** `git commit -s` + trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` (keep **4.7**). Stage files **explicitly** (NOT `git add -A` — an untracked `docs/lq-ai-skill-inputs-corpus.md` lives in the tree; keep it untracked). **Push BOTH remotes.**
7. **PR → `main`** via `gh`. CI runs 3 required checks (API ~11 min — the long pole; Gateway ~2 min; Web ~1 min). Watch with `gh pr checks <n> --watch --interval 30` as a backgrounded Bash command (it re-invokes you on completion — don't poll).
8. **Merge gating (the learned rule):**
   - **`gateway/**` (security boundary) OR an authorization change → Kevin reviews + merges himself** (PR #128 gateway, #133 authz). Push + PR + drive CI green, then STOP and hand to him; offer the review-vs-self-merge choice via `AskUserQuestion` if unsure.
   - **Other `api/` / docs changes → self-merge** after CI green (`gh pr merge <n> --squash`), consistent with #127/#129/#130/#135.
   - **EXTERNAL / community PRs (from a fork, contributor you don't know) → NEVER auto-merge, NEVER self-merge.** CI green ≠ security-vetted. Treat deploy/infra/CI contributions as untrusted supply-chain until a human (Kevin) reviews. The assistant only ever merges *our own* PRs it created. See the #134 example in §5.
9. **After merge:** `git fetch origin main`, ff local `main`, **realign `tucuxi`** (`git push tucuxi main`), confirm origin==tucuxi, confirm the feature branch is **preserved** on origin (never `--delete-branch` — branch-preservation policy). **Report the merged SHA** for Donna's pin. Update memory.

---

## 4. Hard rules (memorize — these have bitten before)

- **NEVER** run host-side `alembic upgrade` against `127.0.0.1:15432/lq_ai` (the live dev DB — desyncs it, crash-loops the api trio). Verify backend (incl. migrations) via a **throwaway pgvector container** + pytest (conftest auto-migrates it): `docker run -d --name lqai-throwaway-pg -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=lqai_test -p 55432:5432 pgvector/pgvector:pg16`, `export DATABASE_URL=postgresql+asyncpg://test:test@127.0.0.1:55432/lqai_test`. Use the **pgvector** image (migrations need the `vector` extension). Remove the container after.
- **Migrations:** when one lands and you apply it to the **dev/prod stack**, **rebuild the api + arq-worker + ingest-worker together** (stale sibling workers crash-loop on a revision mismatch). #135 added migration **0046** — this applies to it.
- **Do NOT `docker compose down -v`** (preserves attorney-review acceptance data + autonomous sessions).
- **DCO sign-off + the 4.7 trailer** on every commit. **Push both remotes.** **Preserve merged branches.**
- **Test-suite collision guards** (both crash the WHOLE api suite at collection if violated): (a) any fully-implemented new route MUST be added to `IMPLEMENTED_ROUTES` in `tests/test_endpoints.py`; (b) `tests/test_openapi.py` pins an exact path count + `EXPECTED_PATHS` — a new path bumps both (count is **117** as of #135; a field/method on an existing path does NOT change it). Don't fudge the count to pass.
- **New `DELETE … 204` endpoints** use the canonical recipe (`response_class=Response` + `return Response(status_code=204)`) — see `CLAUDE.md`. (BYOK #128 applied it; the older alias DELETE still uses the legacy `JSONResponse(204, content=None)` `null`-body pattern — pre-existing, left alone.)
- **`backend-openapi.yaml` does not parse with plain `yaml.safe_load`** (a pre-existing bare-backtick at ~line 1173 in a description). Don't "validate" it that way — `api/tests/test_openapi.py` is the authoritative check. Decimal cost fields are typed `string` (Pydantic v2 serializes `Decimal`→JSON string); match that for new cost fields.

---

## 5. Open threads / deferred items

- **DE-329** — self-service **email** editing on `PATCH /users/me` (deferred from Donna #3; needs a verification/step-up decision). PRD §9.
- **DE-330** — formalize the tabular `results` OpenAPI components (typed cell/citation incl. `verification_method`/`source_*`); until then `gen:api` can't emit those typed. PRD §9.
- **DE-331** — mid-run/per-cell ensemble cost ceiling for tabular (today cost is gated up-front via preview + `confirmed_cost_usd`, not a mid-run cap like chat). PRD §9. (Filed this session.)
- **Precedent `source_session_id` filter** — deliberately NOT built in #135 (precedents are recurrence-aggregated across sessions, so a per-session filter is semantically fuzzy). If Donna needs "precedents this run touched," scope it as a fresh ask (would likely need a join table or an observation-log, not a simple WHERE).
- **`docs/lq-ai-skill-inputs-corpus.md`** — an untracked file that's lived in the working tree all session (a Donna upstream-request doc, not created by us). Every commit stages files explicitly to keep it out. Decide whether to commit, gitignore, or remove it.
- Standing DEs (DE-309/310 tabular telemetry, DE-319 LangGraph 1.x, DE-320 OCR, etc.) — community-pickup candidates in PRD §9.

### ⚠️ External PR #134 — `feat/caddy-tailscale-recipe` (ThurgyThurg, external fork) — DO NOT auto-merge
An unsolicited external PR adding a Caddy + Tailscale deployment recipe (4 new files under `deploy/caddy-tailscale/`, 0 deletions — `Caddyfile`, `docker-compose.proxy.yml`, `README.md`, `.env.example`). **Security-vetted 2026-06-05 (assistant, adversarial supply-chain review): no backdoor/exfil/foreign-tailnet vector found** — it runs NO Tailscale container (uses the host's own `tailscale serve`, no auth key, no `--login-server`, no `funnel`), official `caddy:2-alpine` image, no Docker-socket/privileged/host mounts, loopback-bound by default, gateway not exposed, all `.env` secrets are empty placeholders. Scope is a contained opt-in recipe (changes no existing code path). Minor non-blocking nits: the recipe's `.env.example` is a 374-line near-duplicate of root `.env.example` (drift risk — ask contributor to slim to the Caddy delta); a stale compose comment (`/api/v1/*` vs the actual `/lq-ai-api/v1/*`). **STILL PENDING KEVIN'S MERGE DECISION** — image isn't digest-pinned and contributor-trust is a policy call. **Rule: external/community PRs are never auto-merged or self-merged by the assistant; CI green ≠ vetted (see §3.8).**

---

## 6. Likely next work

- **More Donna-CC Automations asks** (same loop). Recent ones clustered around the autonomous layer (schedules/watches/sessions/findings/memories) and contract drift — expect more in that area as Donna builds the Automations viewer (e.g. the precedent filter, deep-link refs in notifications, or surfacing other run artifacts).
- Each ask: verify against code → surface forks to Kevin → subagent loop → gates → PR → CI → (self-merge or Kevin-review per §3.8) → realign tucuxi → report SHA → update memory.

---

*Drafted at the Donna-asks-shipped standby point, main `0097b01`. The contracts are `CLAUDE.md` (decision routing) + `docs/PRD.md`; memory anchors are `[[project-lq-ai-status]]`, `[[project-donna-backend-asks]]`, `[[project-donna-byok-ask]]`.*
