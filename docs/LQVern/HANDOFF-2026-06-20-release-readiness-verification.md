# Handoff — 2026-06-20 · Release-readiness verification (the "100% honest" gate) · PR6 milestone

**Repo:** `~/Code/lq-ai` (canonical; Bash cwd resets — prefix `cd ~/Code/lq-ai &&`). **main = `f6ffa23`** — **ALL WS5 code merged: 6a–6e done** (6e = DE-341 stub retirement, PR #193, merged + synced origin==tucuxi, branch deleted). The legal-research+MCP milestone's code is COMPLETE; only the release-readiness verification + tag remain.

> Read memories: `[[project-pr6-release-completion-gate]]` (the gate + Kevin's 100%-honesty directive), `[[project-pr6-transparency-posture-narrative]]`, `[[project-legal-research-mcp-milestone]]`, `[[feedback-commit-planning-docs-on-branch]]`.

## Kevin's directive (2026-06-20) — the standard

"We've done stuff probably no other legal-tech product has pulled off — make sure it HONESTLY works… stand behind it 100%… not because it's done, but because everything we claim is true, the functionality we promise works, it's transparent, adheres to our principles. Principled building, no marketing bullshit." This is PRD §1.3 (transparency) applied to release. **Kevin chose: finish 6e first (done), then Claude DRIVES the full verification and reports a written readiness verdict with evidence; Kevin reviews + approves the tag (next = v0.5.0; current tags reach v0.4.2).**

## Two arms

### Arm A — claims-vs-reality audit (breadth)
Walk every public capability claim and verify it's actually implemented AND works — "this is true," not "tests pass." A full **claims inventory (~150 claims)** was generated this session (in conversation; regenerate via an Explore agent over README.md + docs/PRD.md §3 + `web/src/routes/lq-ai/learn/**` + `web/static/learn/playgrounds/governed-tool-flow.html` if lost). **Big asset:** `docs/HONEST-STATE.md` is the project's own shipped-vs-deferred catalog — audit reduces to "does HONEST-STATE.md + README + Learn match the code, and does the code run?" The project is ALREADY disciplined (14 explicit honest caveats: Word-addin scaffold, Slack/Teams OAuth unverified DE-312/288, Playbook+Tabular citations deferred DE-309, Presidio legal-corpus recall unmeasured DE-282, OCR not implemented DE-320, ethics-review light v1). So Arm A focuses on:
1. **Newest/freshest (PR6, least battle-tested):** the governed chat tool-loop + confirmation gate (6b), CourtListener case-law + "Sources consulted" provenance (6c, `message_tool_sources`), the case-law-research skill + C5 `tool_usage` surfacing (6d), the stub retirement (6e).
2. **Headline claims whose falsehood would be worst:** citation engine character-verification (4-stage), gateway = sole egress + holds keys, tier-floor enforcement (403 `tier_below_minimum`), anonymization round-trip, per-user tokens never logged.
3. **Stale-caveat sweep:** e.g. `docs/proposals/legal-research-and-mcp.md:14` "Today only a stub exists… not wired" is FALSE since PR4+6e — apply a "delivered (PR4–6)" status banner to such proposal docs **consistently** (don't fix one line ad hoc). Re-grep proposals/PRD for present-tense claims contradicted by shipped code.
Run as parallel auditor subagents, one per cluster, each returning a claim→verdict→evidence(file:line/test) table. Synthesize.

### Arm B — honest end-to-end bring-up (depth; the load-bearing "it works" proof)
Follow ONLY public docs (README + Quick Start). **Compose builds from source** (`docker-compose.yml` uses `build:` for api/gateway/web/workers/bridges; `image:` only for postgres/redis/minio/ollama) — so the honest test is a **fresh clone → `docker compose up -d --build`** (the running dev stack is up 4 days but that's NOT the honest "stranger can run it" test). Then exercise the real flows against the running stack and capture evidence:
- chat (streaming, markdown, persistence) · skills attach + run (e.g. nda-review on a real doc) · KB upload + hybrid retrieval + citations (the 4 visual states) · projects + privilege/tier-floor (force a 403 `tier_below_minimum`) · the governed tool-loop: a CourtListener case-law lookup → the "Sources consulted" panel + provenance pills → a destructive-tool confirmation gate (approve/deny resumes the turn) → the case-law skill's `tool_usage` "Uses: CourtListener" note · audit log rows · anonymization round-trip.
- Every doc gap found (a missing env var, an unstated step, a broken link) is a **deliverable** — fix the docs, because "a stranger can run it from the public repo" IS the honesty test.
- THEN the mechanical gate (per `[[project-pr6-release-completion-gate]]`): build + push GHCR images (`docs/lq-ai-macos-launcher-playbook.md`) → rebuild the signed/notarized macOS launcher → verify for an external user → **tag v0.5.0**.

## Output
A written **readiness verdict** with evidence: per claim/flow — works / broken / claim-overreaches → fix applied or DE filed. Kevin reviews + approves the tag. **Do NOT tag until Arm B's fresh-clone bring-up + external-user verify pass.**

## Gotchas (don't relearn)
- Tests: api/gateway via host venv from `api/`/`gateway/`; throwaway pg `lq-test-pg` on `127.0.0.1:15433` (`DATABASE_URL=postgresql+asyncpg://lq_ai:test@127.0.0.1:15433/lq_ai`). Web: `npm run check:lq-ai` + `npx vitest run` (from `web/`). **`web/backend/` Python has NO CI gate** (repo ruff excludes `web/`; Web CI = svelte-check on lq-ai code + Vitest) — `py_compile`/build manually.
- Dev-stack rules (CLAUDE.md): NEVER host `alembic upgrade` on live dev DB (15432); NEVER `docker compose down -v`; rebuild `api`+`arq-worker`+`ingest-worker` together on a migration; `web` is a pre-built bundle (rebuild to view UI changes).
- Branch-first always (commit spec/plan on the branch, never local main — see `[[feedback-commit-planning-docs-on-branch]]`). Push origin + tucuxi (kept identical on main). Commit `-s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Migration head 0055; `EXPECTED_PATHS` 134 (6c added `…/sources`).
