# Handoff — 2026-06-16 · macOS launcher SHIPPED · STANDBY for new feature requests

**Repo:** `~/Code/lq-ai` (canonical; NEVER `~/Desktop`; the Bash cwd resets between calls, so prefix every command `cd ~/Code/lq-ai &&`).
**main HEAD = `653ec76`** (origin == tucuxi — both remotes kept byte-identical on `main`). Migration head **0047**. Version **0.4.2**.
**Latest CODE SHA for Donna's `vendor/lq-ai` pin = `c4d4482`** (everything since is the launcher = infra/images/docs + #151 chat change; see "Donna" below).

> **STATUS: No active build task — STANDBY.** Kevin will outline new feature requests next session. An untracked `docs/proposals/legal-research-and-mcp.md` is on disk (left untracked) — likely the next direction (legal research + MCP).

---

## What shipped this session — the macOS launcher (Donna-style one-click app)

A signed, notarized double-click `.dmg` that stands up the full LQ.AI stack from **pre-built public GHCR images** — no terminal, GitHub, repo checkout, or `.env` editing. **Verified end-to-end on a real fresh Mac install (Kevin) — launched and runs.** Mirrors the Donna launcher (`~/Code/Donna/desktop`), distilled in `docs/lq-ai-macos-launcher-playbook.md` (untracked).

**The pieces (all merged to main):**
- **#143** — launcher + self-contained images. `desktop/` (Electron, copied+adapted from Donna), `api/Dockerfile.release` + `gateway/Dockerfile.release` (repo-root context, **bake** the skills corpus + `gateway.yaml.example` the dev stack bind-mounts), `docker-compose.release.yml` (core-8→now 9), `release.yml` multi-arch upgrade, `desktop-release.yml` (macOS signing).
- **#147** — **the load-bearing fix.** The web shell couldn't reach the api ("Failed to fetch"). Root cause: published web bakes same-origin `/api/v1` (needs a reverse proxy) but the stack had none, AND our api + the OpenWebUI shell BOTH mount `/api/v1` (collide on one origin). Fix = **`/lq` prefix**: web built with `PUBLIC_LQ_AI_API_BASE_URL=/lq/api/v1`; a new **`lq-ai-proxy`** Caddy image (4th release image / 9th service) `handle_path /lq/*` strips→`api:8000`, everything else (`/api/config`, OpenWebUI `/api/v1/*`, ws, static)→`web:8080`. Proxy owns the user port; web is internal.
- **#144/#148** — `__version__` bumps (0.4.1, then 0.4.2). **#149** — Protocol-1 record + DE-335. **#150/#152** — 9 real screenshots into `docs/INSTALL-MAC.md` (full visual walkthrough).

**Shipped artifacts (public, verified):**
- Images: `ghcr.io/legalquants/lq-ai-{api,gateway,web,proxy}:v0.4.2` (+ `:latest`) — multi-arch (amd64+arm64), cosign-signed, SBOM'd, **public**.
- App: **`desktop-v0.4.2`** GitHub Release → `LQ.AI-0.1.0-arm64.dmg` — **signed + notarized** (Developer ID: **Tucuxi, Inc. `MC8BT9Z8GD`**; the **5 Apple secrets are set on LegalQuants/lq-ai**). `spctl` = accepted / Notarized Developer ID.
- Verification: Protocol 1 (`desktop/VERIFICATION.md`) **PASSED on published v0.4.2, browser-verified (Cypress headless)** — shell loads, login through the proxy reaches the authed app. Signing verified via `spctl`/stapler. Real-Mac install confirmed by Kevin.

**Launcher specifics:** project `lq-ai-desktop`; ports 13012/18020/18021/25442/26389/29020/29021 (coexist with dev stack + Donna launcher); **BYOK in-app** (wizard collects NO provider keys — add OpenAI/Anthropic in **Configure** after launch, hot-applied no restart); window loads `http://localhost:13012` (the proxy).

---

## ⚠️ Hard-won lessons (don't relearn these)

1. **Verify web/UI changes in a REAL headless browser, not curl.** Curl/api-direct probes gave FALSE PASSES **three times** on the launcher (api-direct login, then curl-not-browser) — each missed the actual bug because it skipped the JS bootstrap (`getBackendConfig` → `/api/config`) and the browser's web→api path. Cypress (in `web/`) is the tool. Saved as memory `feedback-verify-web-in-real-browser`.
2. **Stale local Docker images shadow the registry.** A clean launcher test needs: launcher **Reset** (or `docker compose -p lq-ai-desktop down -v` — removes volumes incl. the postgres-password volume that else crash-loops `api`, AND OpenWebUI's `webui.db`) + `docker image rm ghcr.io/legalquants/lq-ai-{api,gateway,web,proxy}:latest` + delete app-data `~/Library/Application Support/lq-ai-desktop/`.
3. **OpenWebUI `webui.db` / WAL bootstrap fragility (DE-335).** `WEBUI_AUTH=false` auto-admin only works on a *truly empty* db; sqlite WAL means deleting only `webui.db` (leaving `-wal`/`-shm`) doesn't clear it. `down -v` (the launcher Reset) handles it. Hardening tracked as DE-335.
4. **Launcher bundles its compose at BUILD time** — an installed `.dmg` carries the compose from its build. A stack/launcher change needs a **new `desktop-v*`** build, not just new images.

---

## The proven working loop (used all session — keep using it)

1. **Verify the ask against the code FIRST** — nearly every request had a wrong premise or wider blast radius than reported.
2. **Surface genuine forks to Kevin via AskUserQuestion** (options + a recommendation) BEFORE building — he makes architectural/product/authz calls.
3. **subagent-driven-development** — fresh implementer per task + independent spec-then-quality review; final holistic review for multi-task features. SendMessage isn't available in this env; dispatch a fresh "fix" agent for follow-ups.
4. **Run gates yourself**; commit `-s` + trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` (keep 4.7); stage files **explicitly** (never `git add -A` — the untracked corpus/playbook/proposal docs must stay untracked); push **both** remotes (origin=LegalQuants, tucuxi=Tucuxi-Inc).
5. PR → watch CI (3 checks, API ~12min the long pole) → merge per gating → ff main + realign tucuxi → report SHA → update memory.

**Merge gating:** `gateway/**` OR authz/auth/audit/crypto OR `.github/workflows/**` → **Kevin reviews + merges** (offer review-vs-self). Other `api/`/docs → **self-merge after CI green**. EXTERNAL/community PRs → NEVER auto/self-merge; vet adversarially per `docs/security/external-contribution-vetting.md`.

**Hard rules:** NEVER host-side `alembic upgrade` on the live dev DB `127.0.0.1:15432` — verify migrations on a throwaway pgvector container; NEVER `docker compose down -v` the dev stack; rebuild api+arq-worker+ingest-worker together after a migration; gateway is mypy `--strict`, api standard; test-suite collision guards (new route → `IMPLEMENTED_ROUTES` in `tests/test_endpoints.py` + bump `test_openapi.py` count + `EXPECTED_PATHS`); DELETE-204 uses `response_class=Response`; `backend-openapi.yaml` doesn't `safe_load` (use `test_openapi.py`).

---

## Recent non-launcher change to be aware of

**#151 (`4ff4122`) — "Replay prior chat turns to the model (multi-turn memory)"** merged this session (NOT by this assistant — Kevin or another session). Touches `api/app/api/chats.py`, `api/app/config.py`, `.env.example`, `api/tests/test_chat_history.py`. It changes chat send behavior (replays prior turns) — **Donna-relevant** (affects `POST /chats/{id}/messages`). If Donna asks about chat memory, this is the change; confirm its SHA/contract before relaying.

---

## Donna integration status (unchanged this session)

Donna pin SHA stays **`c4d4482`** — the launcher work is infra/images/docs and doesn't move the code pin (#151's chat change is on main at `4ff4122` but wasn't a Donna ask — surface it if Donna needs chat memory). Prior Donna asks all shipped (see `[[project-donna-backend-asks]]`, `[[project-donna-byok-ask]]`). Likely next: more Donna-CC asks clustering around the autonomous layer + contract accuracy — same loop.

## Open deferrals (PRD §9)
DE-329 (self-service email edit), DE-330 (typed tabular results), DE-331 (mid-run ensemble cost ceiling), DE-332 (md/txt ingest parser), DE-333 (storage-failure finding dedupe), DE-334 (pin launcher image tag, not floating `latest`), DE-335 (OpenWebUI webui.db/WAL first-run hardening).

## Next session
Kevin will outline new feature requests. Watch for `docs/proposals/legal-research-and-mcp.md` (untracked) as a likely direction. Start by reading the relevant code/PRD before proposing — same loop.
