# Playbook — give LQ-AI its own GHCR images + a macOS launcher (like Donna)

**Audience:** the LQ-AI maintainer / LQ-AI Claude Code session. **Goal:** make running LQ-AI on macOS
as easy as Donna is now — a signed, notarized double-click app that stands up the LQ-AI stack from
**pre-built images on GHCR**, with no terminal, GitHub, or `.env` editing.

This is a **complete, self-contained** playbook distilled from building exactly this for Donna
(`github.com/LegalQuants/Donna`, `desktop/` + `docker-compose.release.yml` + the two workflows). It
includes the parts that took the most iterations — **code signing/notarization** and the
**first-real-launch bugs** — so you don't re-discover them. Where something is LQ-AI-specific and we
couldn't see it from Donna's side, it's marked **[confirm in lq-ai]**.

> **The big simplification for LQ-AI:** Donna couldn't edit its vendored `lq-ai` submodule, so it
> published *wrapper* images (`donna-api` = lq-ai api + baked skills, etc.). **LQ-AI owns its code, so
> it publishes its `api`/`gateway`/`web` images directly** — no wrapper layer. That makes the images
> half of this *easier* for you than it was for Donna.

The single best shortcut: **copy Donna's `desktop/` directory wholesale and adapt ~10 values.** It's
~1k lines of well-factored TS (pure core + thin Electron glue) and already encodes every fix below.

---

## Part A — Publish LQ-AI images to GHCR

### A1. A release workflow
Add `.github/workflows/release.yml` that builds and pushes your runtime images **multi-arch**
(`linux/amd64,linux/arm64`) to `ghcr.io/<your-namespace>/lq-ai-*` on a `v*` tag or manual dispatch.
You publish whatever the stack needs as images — at minimum **`api`**, **`gateway`**, and **`web`**
(your reference frontend); Postgres/Redis/MinIO use stock public images. Bake what the dev stack
mounts at runtime **into** the images so no bind-mounts are needed:
- the **skills corpus** into the api image (`COPY skills /skills`, `ENV LQ_AI_SKILLS_DIR=/skills`) —
  Donna had to do this in a wrapper; you do it in your own api Dockerfile. **[confirm in lq-ai: skills
  path]**
- the default **gateway config** into the gateway image so it self-seeds `/etc/lq-ai/gateway.yaml` on
  first boot. **[confirm in lq-ai]**

Model the steps on Donna's `release.yml` (multi-arch via `docker/setup-qemu-action` +
`docker/build-push-action`, `permissions: packages: write`, login with `GITHUB_TOKEN`). Tag both
`:vX.Y.Z` and `:latest`.

> ⚠️ When you cut a release, **build from a ref that contains the Dockerfiles + workflow** (e.g.
> `main`), not an older source tag that predates them. Pass the *image* tag separately
> (`-f ref=main -f tag=v0.2.0`).

### A2. An image-only compose
Add `docker-compose.release.yml` — your dev compose with every `build:` replaced by
`image: ghcr.io/<namespace>/lq-ai-<svc>:${LQ_AI_IMAGE_TAG:-latest}`, all required secrets as
`${VAR:?required}`, host ports as `${VAR:-default}`, and **`127.0.0.1` bind addresses** (local-only).
Keep `LQ_AI_SKIP_MIGRATIONS=1` on the workers and let **one** service (the `api`) run migrations.
Provide a `.env.example` with the required secrets + ports. Make the namespace overridable
(`${LQ_AI_IMAGE_NAMESPACE:-<namespace>}`) so it's fork/mirror-portable.

### A3. Make the packages public — the org-policy trap
GitHub publishes packages **private**. If "Change visibility → Public" is **greyed out**
("disabled by organization administrators"), an **org owner** (not a member) must first enable public
packages at `github.com/organizations/<org>/settings/packages` → *Package creation* → allow **Public**.
Then flip each package's visibility to Public (org → Packages → package → settings → Change
visibility). **There is no reliable REST API for this — it's a UI action.** Verify anonymous pull:
```bash
TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:<org>/lq-ai-api:pull" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" "https://ghcr.io/v2/<org>/lq-ai-api/manifests/v0.2.0"   # 200 = public
```

---

## Part B — The macOS launcher (copy Donna's `desktop/`)

Donna's launcher is an **Electron** app with a **pure, unit-tested core** (`desktop/src/core/`, zero
Electron imports) and **thin Electron glue** (`main`/`preload`/`renderer`). It shells out to
`docker-compose.release.yml`, generates secrets, writes a `chmod-600 .env` in app-data, runs the stack
+ first-run admin fixture, and opens the web UI in a native window. **Copy it and change these:**

| Value | In Donna | Change for LQ-AI |
|---|---|---|
| compose **project name** | `donna-desktop` (`src/main/paths.ts`) | `lq-ai-desktop` — **must differ from the dev stack's project** (see gotcha #2) |
| **services** list | the 8 in `EXPECTED_SERVICES` (`src/core/types.ts`) | your stack's service names **[confirm in lq-ai]** |
| **web** service + port | `donna-web` :3000 → host `13002`; window opens `http://localhost:13002` | your `web` service + its port **[confirm in lq-ai]** |
| `.env` keys (`renderEnv`) | POSTGRES/MINIO/S3/LQ_AI_GATEWAY_KEY/JWT_SECRET/ORIGIN/… | your release `.env.example` keys |
| **admin fixture** | `exec -T api python -m app.cli reset-admin-password --email admin@lq.ai --password <p> --no-force-change` | same CLI (LQ-AI owns it) — confirm the email it bootstraps |
| bundled compose | `resources/docker-compose.release.yml` (copied at build) | your release compose |
| appId / productName | `ai.lq.donna.desktop` / `Donna` | e.g. `ai.lq.app.desktop` / `LQ.AI` |
| image tag default | `DONNA_IMAGE_TAG=v0.1.0` | `LQ_AI_IMAGE_TAG=v0.2.0` |

Everything else — the lifecycle state machine (`deriveLauncherState`), the wizard, the control panel,
the Docker-PATH handling, the Reset action — carries over unchanged. Build with **electron-vite**,
package with **electron-builder**. Gates: `vitest` (pure core) + `tsc --noEmit` + `npm run build`.

---

## Part C — Code signing & notarization (the recipe that actually works)

This took the most iterations on Donna. electron-builder (24.13) does **not** produce a
Gatekeeper-passing DMG out of the box. *(For Donna we signed as "Tucuxi, Inc."; LQ-AI can use the same
Apple Developer team or its own — the mechanics are identical.)*

### One-time setup → 5 GitHub Actions secrets
1. **Developer ID Application certificate** (the only type for non-App-Store distribution — *not*
   "Apple Development", *not* "Developer ID Installer"). Xcode → Settings → Accounts → Manage
   Certificates → + → *Developer ID Application*. Then:
   ```bash
   security find-identity -v -p codesigning | grep "Developer ID Application"
   #  → "Developer ID Application: <Org> (TEAMID1234)"   ← TEAMID is APPLE_TEAM_ID
   ```
2. **Export** the cert **with its private key** → `.p12` (Keychain Access → My Certificates →
   right-click → Export, set a password), then `base64 -i cert.p12 -o cert.b64`.
3. **App-specific password** (account.apple.com → Sign-In and Security → App-Specific Passwords) for
   notarytool. Requires 2FA.
4. Set on the repo (`gh secret set` keeps values out of shell history):
   `MAC_CSC_LINK` (`< cert.b64`), `MAC_CSC_KEY_PASSWORD`, `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`,
   `APPLE_TEAM_ID`. Then `rm cert.p12 cert.b64`.

### `electron-builder.yml` — the working config + the 3 traps
```yaml
mac:
  hardenedRuntime: true
  entitlements: build/entitlements.mac.plist
  entitlementsInherit: build/entitlements.mac.plist
  notarize:
    teamId: <TEAMID>                 # TRAP 1: required IN CONFIG (not read from APPLE_TEAM_ID env)
afterAllArtifactBuild: build/notarize-dmg.cjs   # TRAP 2
dmg:
  sign: true                          # TRAP 2
```
- **TRAP 1:** `notarize: true` fails *"The teamId property is required when using notarization with
  password credentials."* electron-builder does **not** read `APPLE_TEAM_ID` from env here — put
  `teamId` in the config.
- **TRAP 2:** native notarize signs+notarizes **only the `.app`**, then builds a **bare `.dmg`**
  (unsigned, un-stapled) → the downloaded dmg is rejected by Gatekeeper ("Apple cannot check it for
  malicious software"). You must **`dmg.sign: true`** *and* an `afterAllArtifactBuild` hook that
  notarizes+staples the dmg:
  ```js
  // build/notarize-dmg.cjs  — no-op without Apple creds (local builds)
  const { execFileSync } = require('node:child_process')
  exports.default = async function (buildResult) {
    const { APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD, APPLE_TEAM_ID } = process.env
    const dmgs = (buildResult.artifactPaths || []).filter(p => p.endsWith('.dmg'))
    if (!dmgs.length || !APPLE_ID || !APPLE_APP_SPECIFIC_PASSWORD || !APPLE_TEAM_ID) return []
    for (const dmg of dmgs) {
      execFileSync('xcrun', ['notarytool','submit',dmg,'--apple-id',APPLE_ID,
        '--password',APPLE_APP_SPECIFIC_PASSWORD,'--team-id',APPLE_TEAM_ID,'--wait'], {stdio:'inherit'})
      execFileSync('xcrun', ['stapler','staple',dmg], {stdio:'inherit'})
    }
    return []
  }
  ```
  A *stapled-but-unsigned* dmg still fails (`spctl` → "no usable signature"); it needs **both**.
- **TRAP 3:** electron-vite emits the preload as **`out/preload/index.mjs`** (ESM, `"type":"module"`).
  The main process must load `../preload/index.mjs` (not `.js`) or `window.<bridge>` is `undefined`.
  Keep `sandbox: false` (a sandboxed preload can't be ESM); `contextIsolation` (default on) is the
  real boundary.

### CI + verify the *published* artifact
`desktop-release.yml` on `macos-14`: map `MAC_CSC_LINK`→`CSC_LINK`, `MAC_CSC_KEY_PASSWORD`→
`CSC_KEY_PASSWORD`, pass the three `APPLE_*`, run tests+typecheck, then `npm run dist`, publish the
`.dmg` to a Release. **Verify the downloaded dmg, not the CI exit code:**
```bash
spctl -a -vvv -t open --context context:primary-signature /tmp/LQ-AI-*.dmg
#   want: accepted / source=Notarized Developer ID
```

---

## Part D — First-real-launch bugs (every one of these bit Donna; pre-fix them)

These do **not** show up in CI or an automated stack test — only when you launch the **signed app from
Finder**. They're all already handled in Donna's `desktop/`; if you copy it you inherit the fixes.

1. **`spawn docker ENOENT` though Docker is installed.** Finder apps get a minimal PATH without
   `/usr/local/bin`. Prepend the docker bin dirs (`/usr/local/bin`, `/opt/homebrew/bin`,
   `/Applications/Docker.app/Contents/Resources/bin`) before spawning (`core/dockerPath.ts`). And give
   **every** `spawn` an `error` handler — a missing one on the log-tail crashed the whole app.
2. **Use your own compose project name** (`lq-ai-desktop`), never the dev stack's. Sharing the name
   reuses the dev `*_pgdata` volume, whose Postgres password differs from the launcher's generated one
   → `api` "password authentication failed" crash-loop (Postgres only sets the password on first init
   of an empty volume). `-p` overrides the compose `name:`.
3. **Persist config only after success** (stack healthy + admin created). Otherwise a failed first run
   strands a half-config and skips the wizard next launch. (Write the `.env` before `up`, but save the
   first-run-complete marker last.)
4. **Admin model.** The api auto-bootstraps a **fixed admin** (Donna: `admin@lq.ai`); the CLI is only
   `reset-admin-password` (**no create-user**). The wizard must **set that admin's password**, not
   invent an email, and **must check the fixture's exit code** (don't show "Running" with no usable
   login). Users rename later in Settings. **[confirm in lq-ai: the bootstrap admin email]**
5. **"Reset" must `down -v`.** Clearing app config alone leaves volumes whose old password collides
   with the next wizard's fresh secrets.
6. **`gh run watch --exit-status` can report 0 on a failed run.** Trust `gh run view --json conclusion`
   + verify the artifact (`spctl`), not the watch.
7. **First-run "models" are doc-processing models** (embeddings/Docling/OCR in the ingest worker), not
   chat LLMs — they download in the background; login works once the stack is HEALTHY. Show live
   `N/8 ready`, not a static "downloading models" message.

App data convention: `~/Library/Application Support/<appName>/` (`config.enc` + chmod-600 `.env`).

---

## Part E — Verify

1. **Automated isolated boot test** (no GUI): bring the **published** images up under a *distinct
   project + shifted ports*, wait for all services healthy, run the admin fixture, then authenticate
   against the web app (`POST /login` with an `Origin` header → expect session cookies). Tear down
   `down -v`. Proves the images work for a stranger.
2. **Real-Mac run** of the signed `.dmg` on a clean machine (or after wiping
   `<project>` containers+volumes + app-config): install → wizard → HEALTHY → login →
   Stop/relaunch/engine-absent. Only this catches Part D. Record it.

---

## Reference implementation
Everything above is implemented and verified in Donna:
- `desktop/` (the launcher), `docker/*.Dockerfile` + `.github/workflows/release.yml` (images),
  `.github/workflows/desktop-release.yml` (signed app), `docker-compose.release.yml`,
  `desktop/electron-builder.yml` + `desktop/build/notarize-dmg.cjs` (the recipe).
- `docs/BUILD-AND-RELEASE.md` (operator guide), `docs/INSTALL-MAC.md` (end-user), `desktop/VERIFICATION.md`.
Copy from there; it already encodes every fix in Parts C and D.
