# LQ-AI macOS launcher + self-contained GHCR images

**Date:** 2026-06-14 · **Branch:** `feat/macos-launcher` · **Base:** main (`f91149a`)
**Source:** `docs/lq-ai-macos-launcher-playbook.md` (distilled from Donna's build). Donna's
launcher is locally copyable at `~/Code/Donna/desktop`.

## Goal

Make running LQ-AI on macOS a signed, notarized double-click `.dmg` that stands up the
stack from **pre-built GHCR images** — no terminal, GitHub, repo checkout, or `.env`
editing. Replicate Donna's experience for LQ-AI, which (owning its code) publishes its
`api`/`gateway`/`web` images **directly** rather than via wrapper images.

## Decisions (Kevin, 2026-06-14)

- **L-1 Signing:** reuse the **Tucuxi, Inc. Apple Developer team `MC8BT9Z8GD`** (cert valid to
  2030, already on the build Mac). Kevin sets the 5 repo secrets with a fresh app-specific
  password. App is signed/notarized as "Tucuxi, Inc." (team ID is non-secret; embedded in
  every notarized artifact).
- **L-2 Service scope:** **Core 8** — postgres, redis, minio, gateway, api, ingest-worker,
  arq-worker, web. No ollama, no slack/teams bridges (they need OAuth, defeat zero-config).
- **L-3 Provider keys:** **in-app BYOK after launch** — the stack boots healthy with zero
  provider keys; the user adds OpenAI/Anthropic keys via the runtime provider-keys admin UI
  (#128, hot-applied no restart). Wizard collects NO provider secrets. (Chat needs a key
  before first use; the launcher messaging says so.)
- **L-4 Execution:** build everything that needs no Kevin credentials; hand Kevin a short
  manual-steps checklist (5 Apple secrets, GHCR public visibility, cut tag).
- **L-5 Dev-stack safety (derived):** the actively-used dev stack stays **100% untouched**.
  Dev keeps bind-mounting `skills/` + `gateway.yaml.example`; only the *release* build path
  bakes them. No change to `docker-compose.yml`, `api/Dockerfile`, or `gateway/Dockerfile`.

## Key facts (verified against the tree)

- `release.yml` already builds + cosign-signs + SBOMs `lq-ai-{api,gateway,web}` to
  `ghcr.io/legalquants` — but **single-arch** (no `platforms:`), and from **subdir contexts**
  (`./api`, `./gateway`, `./web`) so it cannot bake the repo-root `skills/` or
  `gateway.yaml.example`.
- Gateway entrypoint already seeds `/etc/lq-ai/gateway.yaml` from a baked example at
  `/usr/share/lq-ai/gateway.yaml.example` (`gateway/entrypoint.sh`) — dev bind-mounts that
  path; the release image just needs to `COPY` it.
- api + workers need the **skills corpus** at `/skills` (`LQ_AI_SKILLS_DIR=/skills`,
  load-bearing for skill_ref resolution per #139). Dev bind-mounts `./skills:/skills:ro`.
- web Dockerfile (context `./web`) is self-contained (no repo-root deps) → release just adds
  multi-arch.
- Donna's `EXPECTED_SERVICES` = postgres, redis, minio, gateway, api, ingest-worker,
  arq-worker, **donna-web**; LQ-AI keeps the service name **`web`**.
- Donna launcher ports: 13002/18000/18001/25432/26379/29000/29001. LQ-AI launcher must use a
  **distinct** set so it coexists with BOTH the dev stack AND a Donna launcher on one Mac.

## Tasks

### T1 — Self-contained release images (bake + multi-arch)

- **`api/Dockerfile.release`** (NEW): repo-root build context; mirrors `api/Dockerfile`'s build
  (COPY paths prefixed `api/`) and adds `COPY skills /skills` + `ENV LQ_AI_SKILLS_DIR=/skills`.
  Header comment: "keep build steps in sync with api/Dockerfile; exists to bake the skills
  corpus (bind-mounted in dev) for the zero-checkout launcher." Used for the api + both workers
  (same image).
- **`gateway/Dockerfile.release`** (NEW): repo-root context; mirrors `gateway/Dockerfile` and
  adds `COPY gateway.yaml.example /usr/share/lq-ai/gateway.yaml.example` (the path the
  entrypoint already seeds from).
- **`.dockerignore`** (NEW, repo root): keep the repo-root build context lean — exclude `.git`,
  `**/node_modules`, `web/` build junk, `desktop/`, `docs/`, `tests/` fixtures, `*.md`, etc.
  (without excluding `skills/`, `api/`, `gateway/`, the entrypoints).
- **`.github/workflows/release.yml`**: add `docker/setup-qemu-action`; set
  `platforms: linux/amd64,linux/arm64`; api job → `context: .`, `file: api/Dockerfile.release`;
  gateway job → `context: .`, `file: gateway/Dockerfile.release`; web job unchanged
  (`context: ./web`) + multi-arch. Keep cosign/SBOM/SLSA (they handle multi-arch indexes).
- **Verify:** `docker buildx build` each release image for the local arch succeeds; `docker run
  --rm <api-release> ls /skills` shows the corpus; `<gateway-release>` has the example file.
  Do NOT push. Do NOT touch the dev stack.

### T2 — `docker-compose.release.yml` + `.env.example`

- Core-8 services only. App services:
  `image: ghcr.io/${LQ_AI_IMAGE_NAMESPACE:-legalquants}/lq-ai-<svc>:${LQ_AI_IMAGE_TAG:-latest}`.
- Required secrets `${VAR:?...}` (LQ_AI_GATEWAY_KEY, JWT_SECRET, POSTGRES_PASSWORD, MinIO
  creds, …); ports `${VAR:-<shifted default>}`; binds `127.0.0.1`.
- **No** skills / gateway.yaml bind mounts (baked). Keep the `gateway-config` named volume for
  runtime hot-reload writes (entrypoint seeds it from the baked example).
- `LQ_AI_SKIP_MIGRATIONS=1` on both workers; api runs migrations.
- `.env.example`: required secrets + shifted ports; note provider keys are optional (add
  in-app via Configure / BYOK).
- **Verify:** `docker compose -f docker-compose.release.yml config` renders; isolated boot
  using LOCALLY-built+tagged release images under a **distinct project + the shifted ports**
  → all 8 healthy → `exec -T api python -m app.cli reset-admin-password --email admin@lq.ai
  --password <p> --no-force-change` → `POST /login` with Origin header returns session
  cookies. Tear down `down -v` (the throwaway project only — never the dev stack).

### T3 — Desktop launcher (copy Donna's `desktop/` + adapt)

- Copy `~/Code/Donna/desktop` → `~/Code/lq-ai/desktop`; drop `node_modules/`, `out/`, `dist/`.
  Adapt the ~10 values:
  - `PROJECT_NAME` → `lq-ai-desktop` (`src/main/paths.ts`).
  - `EXPECTED_SERVICES` → the core-8 with `web` (not `donna-web`) (`src/core/types.ts`).
  - `DEFAULT_PORTS` → distinct from dev AND Donna: web 13012, api 18020, gateway 18021,
    postgres 25442, redis 26389, minioApi 29020, minioConsole 29021 (confirm no Donna clash).
  - `renderEnv` keys → LQ-AI release `.env.example` keys.
  - admin fixture → `exec -T api python -m app.cli reset-admin-password --email admin@lq.ai
    --password <p> --no-force-change` (confirm flag names against `api/app/cli.py`).
  - `appId: ai.lq.app.desktop`, `productName: LQ.AI` (electron-builder.yml + paths).
  - image-tag env → `LQ_AI_IMAGE_TAG` (default to the version we'll tag).
  - bundled compose → our `docker-compose.release.yml` (the `prepack:compose` copy step).
  - branding strings / window title / app name.
- Update the pure-core vitest tests (`types.test.ts`, `state.test.ts`) to the new
  services/ports. Keep Donna's lifecycle state machine, wizard, control panel, Docker-PATH
  handling (Part D fix #1), own-project-name (#2), persist-after-success (#3), admin
  exit-code check (#4), Reset `down -v` (#5), `N/8 ready` messaging (#7) — all carry over.
- **Gates:** `vitest` (pure core) + `tsc --noEmit` + `npm run build` (electron-vite). Keep the
  ESM-preload path (`out/preload/index.mjs`, Trap 3); `sandbox:false`, `contextIsolation` on.

### T4 — Signing config + desktop-release workflow + docs

- **`desktop/electron-builder.yml`**: `appId`/`productName`; `mac.hardenedRuntime: true` +
  entitlements; `mac.notarize.teamId: MC8BT9Z8GD` (Trap 1 — teamId in config, not env);
  `afterAllArtifactBuild: build/notarize-dmg.cjs` + `dmg.sign: true` (Trap 2). Copy
  `build/notarize-dmg.cjs` (no-op without Apple creds) + `build/entitlements.mac.plist`.
- **`.github/workflows/desktop-release.yml`** on `macos-14`: map `MAC_CSC_LINK`→`CSC_LINK`,
  `MAC_CSC_KEY_PASSWORD`→`CSC_KEY_PASSWORD`, pass `APPLE_ID`/`APPLE_APP_SPECIFIC_PASSWORD`/
  `APPLE_TEAM_ID`; run vitest + tsc, `npm run dist`, publish the `.dmg` to a Release.
- **Docs:** `docs/BUILD-AND-RELEASE.md` (operator: cut a release, the manual-steps checklist),
  `docs/INSTALL-MAC.md` (end-user: download, open, wizard, add a provider key in Configure),
  `desktop/VERIFICATION.md` (the isolated-boot + real-Mac checklists incl. the `spctl` verify).
- The **manual-steps checklist for Kevin** lives in BUILD-AND-RELEASE.md: (1) set the 5 Apple
  secrets (`APPLE_TEAM_ID=MC8BT9Z8GD`, fresh app-specific password); (2) flip the 3 GHCR
  packages to Public (org UI — `Package creation → allow Public`, then per-package visibility);
  (3) cut the `vX.Y.Z` tag from a ref containing the Dockerfiles+workflow.

### T5 — Final holistic review + PR

- Holistic review across all artifacts; then push both remotes, open PR.
- **Merge gating:** this touches `gateway/**` (new Dockerfile.release) AND `.github/workflows/**`
  (release.yml + desktop-release.yml) — both CODEOWNERS security-review paths → **Kevin reviews
  + merges**. Offer review-vs-self.

## Gates / conventions

DCO `-s` + `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`; explicit
staging (corpus doc stays untracked); push both remotes; never `docker compose down -v` on the
dev stack (throwaway projects only); never host-side alembic on the dev DB.

## What Kevin must do (the manual external steps — can't be automated)

1. **Apple secrets** on the lq-ai repo: re-export the existing "Developer ID Application:
   Tucuxi, Inc." cert → `.p12` → base64 → `MAC_CSC_LINK`; `MAC_CSC_KEY_PASSWORD`; `APPLE_ID`;
   a **fresh** `APPLE_APP_SPECIFIC_PASSWORD`; `APPLE_TEAM_ID=MC8BT9Z8GD`.
2. **GHCR visibility**: org owner enables public packages, then flip
   `lq-ai-{api,gateway,web}` to Public; verify anonymous pull.
3. **Cut the tag** (`vX.Y.Z` from `main`) → release.yml publishes multi-arch images;
   then run/trigger `desktop-release.yml` → notarized `.dmg`.
