# LQ.AI for Mac — release verification protocol

> **STATUS: PARTIALLY EXECUTED (2026-06-14).** The signed-`.dmg` Gatekeeper/notarization checks in
> **Protocol 2 → "Verify the downloaded dmg"** have been run against the real published
> `desktop-v0.4.0` release and passed (results filled in below). **Protocol 1** has now been run on
> `fix/launcher-reverse-proxy` as a full 9-service boot with the **/lq prefix** routing (locally-built
> `web` baked with `PUBLIC_LQ_AI_API_BASE_URL=/lq/api/v1` + locally-built `lq-ai-proxy`, on top of the
> published `v0.4.1` api/gateway). It was verified **in a real headless browser (Cypress)**: the web
> shell loads at `/` WITHOUT redirecting to `/error`, the LQ.AI login form renders, and login through
> the proxy reaches the authed app (results + screenshot finding below). This supersedes both the
> earlier api-direct Protocol 1 record (#146) AND the first attempt at this fix (commit `7841121`),
> which used a blanket `/api/*` proxy that stole OpenWebUI's `/api/config` and broke first paint.
> Still pending: re-running Protocol 1 against the *published* proxy image + the `/lq`-baked web image
> once they ship to GHCR, and the **Protocol 2 launcher-lifecycle** boxes (needs a clean Mac).
> Unchecked boxes are genuinely not-yet-run — **do not pre-fill them.**

**What this proves:** the **published images** stand up to a real login for a stranger, and the
**signed/notarized `.dmg`** installs and runs on a Mac with Docker but **no LQ.AI repo cloned**.

**Artifacts under test (fill in at release time):**

- Images: `ghcr.io/legalquants/lq-ai-{api,gateway,web,proxy}:vX.Y.Z` (public). The `proxy` image
  (reverse proxy, fix/launcher-reverse-proxy) is the 4th release image and the 9th stack service. The
  `web` image is built with `--build-arg PUBLIC_LQ_AI_API_BASE_URL=/lq/api/v1` (release.yml passes this
  build-arg for the `web` matrix entry only), so the LQ.AI client addresses its own `/lq`-prefixed
  origin and never collides with OpenWebUI's same-origin `/api`.
- App: `LQ.AI-<version>-arm64.dmg` from the `desktop-vX.Y.Z` GitHub Release (Developer ID:
  Tucuxi, Inc., team `MC8BT9Z8GD` — signed, notarized, stapled).

---

## Protocol 1 — Automated isolated boot of the published images (no GUI)

> **Why this protocol changed (fix/launcher-reverse-proxy).** The earlier Protocol 1 (and PR #146)
> recorded a login PASS, but that test authenticated against the **api port directly** — NOT the
> browser's web→api path. It therefore never exercised the same-origin call the web shell actually
> makes, and so missed a whole class of bug: the published web image bakes a relative, same-origin
> `PUBLIC_LQ_AI_API_BASE_URL`, which by design needs a reverse proxy fronting web + api on ONE origin.
> The core-8 stack had none, so the real browser login failed with "Failed to fetch" even though the
> api-direct test was green.
>
> A first fix (commit `7841121`) added a proxy with a **blanket `/api/*` → api** route. That was wrong:
> the web image runs the OpenWebUI Python backend, which serves `/api/config` (the SPA fetches it at
> first paint via `getBackendConfig()`) AND its own `/api/v1/*` groups — so the blanket rule stole
> `/api/config` (404 on our api) and the shell redirected to `/error` before it could render.
>
> The resolution gives the LQ.AI client its OWN path prefix: the `web` image is built with
> `PUBLIC_LQ_AI_API_BASE_URL=/lq/api/v1`, so its calls are `/lq/api/v1/*`. The proxy
> (`lq-ai-proxy` image) `handle_path /lq/*` STRIPS the `/lq` prefix and forwards to `api:8000` (which
> mounts `/api/v1`), and routes EVERYTHING else — `/api/config`, OpenWebUI's own `/api/v1/*`,
> websockets, static — to `web:8080`. The proxy owns the user-facing `WEB_HOST_PORT`; web is internal.
> **Protocol 1 below now verifies the actual browser path IN A REAL HEADLESS BROWSER (Cypress) — the
> shell loads without `/error` and login through the proxy reaches the authed app — and the stack is 9
> services, not 8.**

Proves the published images work for a fresh install, independent of the launcher chrome. Run under a
**distinct compose project + the shifted ports** so it cannot touch the dev stack or a launcher stack.
Tear down with `down -v` (the throwaway project only — never the dev stack).

```bash
# 1. Confirm the images are anonymously pullable (200 = public). NOTE the proxy image:
for img in lq-ai-api lq-ai-gateway lq-ai-web lq-ai-proxy; do
  TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:legalquants/$img:pull" \
    | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
  curl -s -o /dev/null -w "$img -> %{http_code}\n" -H "Authorization: Bearer $TOKEN" \
    "https://ghcr.io/v2/legalquants/$img/manifests/vX.Y.Z"
done

# 2. Bring the stack up under a throwaway project + shifted ports (LQ_AI_IMAGE_TAG pins the version):
#    Use a temp .env from .env.release.example with the four required secrets filled in.
LQ_AI_IMAGE_TAG=vX.Y.Z docker compose -f docker-compose.release.yml -p lq-ai-reltest \
  --env-file /tmp/reltest.env up -d

# 3. Wait for all 9 services healthy (the 9th is the reverse proxy):
docker compose -f docker-compose.release.yml -p lq-ai-reltest --env-file /tmp/reltest.env ps

# 4. Create the admin login fixture:
docker compose -f docker-compose.release.yml -p lq-ai-reltest --env-file /tmp/reltest.env \
  exec -T api python -m app.cli reset-admin-password \
  --email admin@lq.ai --password 'Reltest123456!' --no-force-change

# 5. curl PRE-CHECKS through the proxy origin (necessary, NOT sufficient — see step 6).
#    (a) /api/config must reach WEB (proves the blanket-/api regression is gone): expect 200.
curl -sS -o /dev/null -w "/api/config -> %{http_code}\n" http://127.0.0.1:${WEB_HOST_PORT}/api/config
#    (b) /lq/api/v1/auth/login must STRIP /lq and reach the api: expect 200 + access_token.
curl -sS -X POST http://127.0.0.1:${WEB_HOST_PORT}/lq/api/v1/auth/login \
  -H "Origin: http://localhost:${WEB_HOST_PORT}" -H 'Content-Type: application/json' \
  -d '{"email":"admin@lq.ai","password":"Reltest123456!"}'
#    (c) /api/v1/auth/login is OpenWebUI's namespace now (must NOT reach our api): expect 404/405 from web.
curl -sS -o /dev/null -w "/api/v1/auth/login -> %{http_code}\n" -X POST \
  http://127.0.0.1:${WEB_HOST_PORT}/api/v1/auth/login -H 'Content-Type: application/json' -d '{}'

# 6. REQUIRED real-browser check (curl alone has missed JS-bootstrap bugs three times). Drive a
#    headless browser to load http://127.0.0.1:${WEB_HOST_PORT}/ and assert it does NOT redirect to
#    /error and the LQ.AI login form renders, then log in and assert the authed app appears. Cypress
#    ships in web/ — write a one-off spec asserting (i) location does not include /error, (ii) the
#    [data-testid="lq-ai-login-*"] form renders, (iii) after submit, localStorage 'lq_ai_auth' holds an
#    access_token and the URL leaves /login — then:
#      cd web && npx cypress run --spec '<spec>' --config baseUrl=http://127.0.0.1:${WEB_HOST_PORT}
#    NOTE: OpenWebUI keeps its OWN sqlite (web container /app/backend/data/webui.db) and honors
#    WEBUI_AUTH=false only on a TRULY FRESH OpenWebUI db. If any non-default OpenWebUI user exists,
#    auto-signin 400s ("can't turn off authentication … existing users") and the root guard parks the
#    SPA at /auth. A throwaway project (or the launcher's Reset = `down -v`) removes the whole web
#    volume, so it's clean. CAVEAT: OpenWebUI runs sqlite in WAL mode — removing only `webui.db`
#    leaves `webui.db-wal`/`webui.db-shm`, which still carry the user. To re-bootstrap WITHOUT a full
#    `down -v`, remove all three (`rm webui.db webui.db-wal webui.db-shm`) then restart web. Tracked
#    for hardening as DE-335.

# 7. Tear down the throwaway project (NEVER -v the dev stack):
docker compose -f docker-compose.release.yml -p lq-ai-reltest --env-file /tmp/reltest.env down -v
```

Results — **EXECUTED 2026-06-14** on `fix/launcher-reverse-proxy`, against the published `api` +
`gateway` images at **`v0.4.1`** + a **locally-built `web`** (built with
`--build-arg PUBLIC_LQ_AI_API_BASE_URL=/lq/api/v1`, simulating the release build) + a **locally-built
`lq-ai-proxy`** (proxy + /lq-baked web are not published yet — built from this branch). All four ran
under a dedicated `:lqtest` tag so the live `:latest` the `lq-ai-desktop` launcher uses was untouched.
Throwaway project `lqai-lqtest`, shifted ports (WEB 13700 / API 18700 / GATEWAY 18701 / PG 25700 /
REDIS 26700 / MINIO 29700-29701). The dev stack + the live `lq-ai-desktop` launcher were untouched.

- [x] Images anonymously pullable (HTTP 200) — **N/A for this run** (proxy + /lq-web unpublished; tested
      with locally-built proxy + /lq-baked web + the published `v0.4.1` api/gateway). The 4-image
      public-pull check above reruns at the real release once these ship to GHCR. Confirmed the web bundle
      baked the right value: `/app/build/_app/env.js` → `{"PUBLIC_LQ_AI_API_BASE_URL":"/lq/api/v1"}`.
- [x] All **9** services reach **Healthy** — ✅ `9/9 healthy`: api, arq-worker, gateway, ingest-worker,
      minio, postgres, **proxy**, redis, web (all `running`/`healthy`).
- [x] Admin fixture created the login (exit 0) — ✅ `RESET_EXIT=0` ("Reset password for admin@lq.ai…").
- [x] **curl (a)** `GET /api/config` (→ web) — ✅ **HTTP 200** (JSON name/features). The blanket-`/api`
      regression that broke first paint is gone.
- [x] **curl (b)** `POST /lq/api/v1/auth/login` (Origin `http://localhost:13700`) — ✅ **HTTP 200 +
      access_token** (259 chars). The `/lq` prefix is stripped and reaches the api.
- [x] **curl (c)** `POST /api/v1/auth/login` (OpenWebUI's namespace) — ✅ **HTTP 405** from web (does
      NOT reach our api), confirming the same-origin separation.
- [x] **REAL BROWSER (Cypress 13.17.0, Electron headless)** — ✅ **2/2 passing.** (i) `GET /` does NOT
      redirect to `/error` and the shell renders; (ii) the LQ.AI login form (`lq-ai-login-*` testids)
      renders at `/lq-ai/login`; (iii) after submit, `localStorage['lq_ai_auth']` holds an `access_token`
      (>20 chars) and the URL leaves `/login`. Authed-app screenshot showed the "You're now logged in."
      toast + "Welcome back, LQ.AI Administrator" home with the full LQ.AI nav. **Finding:** the first
      browser attempt parked at `/auth` — OpenWebUI keeps its OWN sqlite (`webui.db`) and refuses
      `WEBUI_AUTH=false` once a non-default OpenWebUI user exists (a prior Cypress run had created one).
      Removing the webui.db sqlite set (`webui.db` **+ `webui.db-wal` + `webui.db-shm`** — OpenWebUI runs
      WAL mode, so deleting only `webui.db` leaves the user in the WAL) + restarting web re-bootstrapped
      the clean default user (matching the live dev launcher, whose OpenWebUI user is `admin@localhost`),
      after which the browser flow passed. The launcher's Reset (`down -v`) removes the whole volume so
      this can't bite a normal user; hardening tracked as DE-335. This is
      an OpenWebUI bootstrap-state artifact, NOT a proxy defect — the live dev launcher reaches
      `/lq-ai/login` with the form rendered, confirmed by the same Cypress harness against `:13012`.
- [x] `down -v` on the throwaway project only; dev stack untouched — ✅ `lqai-lqtest` removed (volumes +
      network), `lq-ai-desktop` stack still running, temp env removed.

Also confirmed (still true of the published images): the `ghcr.io/legalquants/lq-ai-{api,gateway}:v0.4.1`
images are **multi-arch** (`linux/amd64` + `linux/arm64`, native on Apple Silicon); the **baked assets**
are present (api `/skills` corpus, `LQ_AI_SKILLS_DIR=/skills`; gateway seeds `/etc/lq-ai/gateway.yaml`
from the baked `/usr/share/lq-ai/gateway.yaml.example`); the stack boots fully healthy with **no
provider keys** (BYOK).

---

## Protocol 2 — Real-Mac run of the signed `.dmg`

The only way to catch the first-real-Finder-launch bugs (PATH, project/volume isolation, stranded
config, admin model). Run on a clean Mac, or wipe the `lq-ai-desktop` containers + volumes + app-data
(`~/Library/Application Support/lq-ai-desktop/`) first so first-launch behaves like a new machine.

### Verify the downloaded dmg is Gatekeeper-clean (not the CI exit code)

```bash
gh release download desktop-vX.Y.Z -R LegalQuants/lq-ai -p '*.dmg' -D /tmp --clobber
spctl -a -vvv -t open --context context:primary-signature /tmp/LQ.AI-*.dmg
#   want: accepted / source=Notarized Developer ID /
#         origin=Developer ID Application: Tucuxi, Inc. (MC8BT9Z8GD)
xcrun stapler validate /tmp/LQ.AI-*.dmg     # "The validate action worked!"
```

Results — **EXECUTED 2026-06-14** against `desktop-v0.4.0` (asset `LQ.AI-0.1.0-arm64.dmg`, from
`https://github.com/LegalQuants/lq-ai/releases/tag/desktop-v0.4.0`; built + signed + notarized on the
`macos-14` runner, [run 27511342826](https://github.com/LegalQuants/lq-ai/actions/runs/27511342826),
first attempt):

- [x] `spctl` → **accepted / source=Notarized Developer ID** — ✅ `origin=Developer ID Application: Tucuxi, Inc. (MC8BT9Z8GD)`
- [x] `xcrun stapler validate` → **worked** — ✅ "The validate action worked!" (ticket stapled → opens offline)
- [x] `codesign -dv` authority chain — ✅ `Developer ID Application: Tucuxi, Inc. (MC8BT9Z8GD)` → Developer ID CA → Apple Root CA; `TeamIdentifier=MC8BT9Z8GD`

### Launcher lifecycle (real Finder launch)

- [ ] **Install** — `.dmg` opens, `LQ.AI.app` → Applications, launches with **no Gatekeeper warning** — _____
- [ ] **Wizard** — sets a password (login shown as `admin@lq.ai`), **Start LQ.AI** — no terminal, no hand-edited `.env` — _____
- [ ] **No provider key asked for** in the wizard (BYOK is in-app) — _____
- [ ] **Live progress** — shows live "N/9 services ready" (honest state, not a fake "ready") — _____
- [ ] **Healthy** — reaches **Running**; **Open LQ.AI** enabled — _____
- [ ] **Open LQ.AI** — window loads the web login page (`http://localhost:13012`) — _____
- [ ] **Login** — `admin@lq.ai` + the wizard password → reaches the authed app — _____
- [ ] **BYOK** — add a provider key in **Configure**; chat works after (hot-applied, no restart) — _____
- [ ] **Stop** — panel → **Stopped**, stack down — _____
- [ ] **Relaunch** — reopen → **no wizard** (config reused) → **Start** back to **Running** — _____
- [ ] **Engine-absent** — quit Docker → panel reads **Docker is not running** with install guidance (no crash, no fake ready) — _____

---

## Verdict

- [ ] **Release `vX.Y.Z` / `desktop-vX.Y.Z` verified.** _(fill in date + tester + any notes)_
