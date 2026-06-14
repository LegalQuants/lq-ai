# LQ.AI for Mac — release verification protocol

> **STATUS: TEMPLATE — to be executed at release time.** Nothing below has been run yet; the result
> boxes are empty on purpose. Fill in each ✅/❌ + note as you run it against a real published release,
> then commit this file as that release's evidence. **Do not pre-fill results.**

**What this proves:** the **published images** stand up to a real login for a stranger, and the
**signed/notarized `.dmg`** installs and runs on a Mac with Docker but **no LQ.AI repo cloned**.

**Artifacts under test (fill in at release time):**

- Images: `ghcr.io/legalquants/lq-ai-{api,gateway,web}:vX.Y.Z` (public).
- App: `LQ.AI-<version>-arm64.dmg` from the `desktop-vX.Y.Z` GitHub Release (Developer ID:
  Tucuxi, Inc., team `MC8BT9Z8GD` — signed, notarized, stapled).

---

## Protocol 1 — Automated isolated boot of the published images (no GUI)

Proves the published images work for a fresh install, independent of the launcher chrome. Run under a
**distinct compose project + the shifted ports** so it cannot touch the dev stack or a launcher stack.
Tear down with `down -v` (the throwaway project only — never the dev stack).

```bash
# 1. Confirm the images are anonymously pullable (200 = public):
for img in lq-ai-api lq-ai-gateway lq-ai-web; do
  TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:legalquants/$img:pull" \
    | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
  curl -s -o /dev/null -w "$img -> %{http_code}\n" -H "Authorization: Bearer $TOKEN" \
    "https://ghcr.io/v2/legalquants/$img/manifests/vX.Y.Z"
done

# 2. Bring the stack up under a throwaway project + shifted ports (LQ_AI_IMAGE_TAG pins the version):
#    Use a temp .env from .env.release.example with the four required secrets filled in.
LQ_AI_IMAGE_TAG=vX.Y.Z docker compose -f docker-compose.release.yml -p lq-ai-reltest \
  --env-file /tmp/reltest.env up -d

# 3. Wait for all 8 services healthy:
docker compose -f docker-compose.release.yml -p lq-ai-reltest --env-file /tmp/reltest.env ps

# 4. Create the admin login fixture:
docker compose -f docker-compose.release.yml -p lq-ai-reltest --env-file /tmp/reltest.env \
  exec -T api python -m app.cli reset-admin-password \
  --email admin@lq.ai --password 'Reltest123456!' --no-force-change

# 5. Authenticate end-to-end through the web BFF (Origin header required) and confirm session cookies:
#    expect HTTP 200 + Set-Cookie session tokens.
#    (web is published on the shifted WEB_HOST_PORT — default 13012 for the hand-run defaults.)

# 6. Tear down the throwaway project (NEVER -v the dev stack):
docker compose -f docker-compose.release.yml -p lq-ai-reltest --env-file /tmp/reltest.env down -v
```

Results (fill in):

- [ ] All 3 `ghcr.io/legalquants/lq-ai-*:vX.Y.Z` images anonymously pullable (HTTP 200) — _____
- [ ] All 8 services reach **Healthy** — _____
- [ ] Admin fixture created the login (exit 0) — _____
- [ ] `POST /login` (with `Origin` header) returns session cookies — _____
- [ ] `down -v` on the throwaway project only; dev stack untouched — _____

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

Results (fill in):

- [ ] `spctl` → **accepted / source=Notarized Developer ID** — _____
- [ ] `xcrun stapler validate` → **worked** — _____

### Launcher lifecycle (real Finder launch)

- [ ] **Install** — `.dmg` opens, `LQ.AI.app` → Applications, launches with **no Gatekeeper warning** — _____
- [ ] **Wizard** — sets a password (login shown as `admin@lq.ai`), **Start LQ.AI** — no terminal, no hand-edited `.env` — _____
- [ ] **No provider key asked for** in the wizard (BYOK is in-app) — _____
- [ ] **Live progress** — shows live "N/8 services ready" (honest state, not a fake "ready") — _____
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
