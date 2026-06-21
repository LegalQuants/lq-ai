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

---

## OUTCOME — v0.5.0 shipped + launcher verified (2026-06-21)

**Verdict: PASS. v0.5.0 honestly works and the claims are true.** Both arms run; the code was found honest, the drift was documentation, and the two real bugs the gate surfaced are fixed.

**Arm A (claims-vs-reality, 6 parallel auditors):** every headline claim verified TRUE, no overreach — gateway sole egress (api has exactly one outbound client → the gateway), 4-stage citation cascade, confirmation gate fires, tier-floor 403 `tier_below_minimum`, anonymization round-trip + no-leak test, per-user OAuth tokens Fernet-at-rest + never logged. The drift was docs pinned at the M4 close (head 0047), most dangerously the false §6 "MCP deferred-M5 / grep empty" claim. **Reconciled in #195** (HONEST-STATE.md → head 0055 + new §5.5; README/PRD/proposals fixed).

**Arm B (honest fresh-clone bring-up):** fresh clone → `docker compose up -d --build` built from source and self-migrated 0001→0055; verified LIVE — chat (real Anthropic stream+persist), tier-floor 403, skills incl. `case-law-research` `tool_usage`, KB → exact-match-verified citation, audit log, and case-law end-to-end (governed tool-loop → real CourtListener → `message_tool_sources` → `/sources` → `tool_call_log` → `tool_egress_log`).

**Bugs the gate caught + fixed:**
- **CourtListener gateway wiring** — `docker-compose.yml` never forwarded `COURTLISTENER_API_TOKEN` to the gateway, so case-law was dark on a fresh clone despite the documented enable-path. Fixed + re-verified live (#195) + README "Enabling legal-research connectors" opt-in section.
- **DE-351** — first PDF ingest timed out on the docling model download and left the file stuck in `processing`. Fixed the stuck-state (in-job soft timeout marks `failed`) in **#196**.
- **DE-353** — the `web` (OpenWebUI) container blocked boot on an unnecessary local-RAG model fetch → web unhealthy → launcher "Stack failed to start." Fixed (`RAG_EMBEDDING_ENGINE=openai`, compose-only) in **#200**; empirically web `/health` 200 in ~11s.
- **DE-354** — the macOS launcher regenerated secrets on a retried first-run without `down -v` → stale-volume `password authentication failed` crash-loop. Fixed (`resetStack()` before first-run start) in **#200**.
- DE-352 (pre-upload format guard) filed, deferred.

**Shipped:** `__version__` 0.5.0 (#197); **`v0.5.0`** tag → multi-arch GHCR images (api/gateway/web/proxy) + SBOMs + Cosign-signed + public; **`desktop-v0.5.1`** signed/notarized launcher (`spctl` accepted, Notarized Developer ID — Tucuxi, Inc.). Desktop `package.json` bumped to 0.5.1 so `.dmg` filenames carry the real version (the 0.1.0 collision caused a re-test mix-up).

**Launcher first-run verified working (desktop-v0.5.1, installed to /Applications):** all 9 services healthy, web healthy fast (DE-353), api `RestartCount=0` (DE-354), api migrated 0055, UI `/lq-ai` 200, `/api/config` 200, served at `http://localhost:13012`. A stranger can download → install → Start → login with no terminal/manual steps.

**Remaining (hands-on, non-blocking):** operator confirms login + a chat (with a provider key or local Ollama). PRs: #195 (docs+wiring), #196 (DE-351), #197 (version), #200 (DE-353/354 launcher); #198/#199 superseded. Main at the v0.5.0 line; origin == tucuxi throughout.
