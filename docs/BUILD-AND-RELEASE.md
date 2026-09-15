# Building & releasing LQ.AI — container images + the macOS app

This is the operator's guide for shipping LQ.AI: the **pre-built container images** published to GHCR
and the **"LQ.AI for Mac" desktop launcher** (a signed, notarized `.dmg`). It is written for whoever
cuts the next release, and it records the **dead-ends and fixes** hit the first time so they don't get
re-discovered.

> Because LQ.AI owns its own code, it publishes its `api`/`gateway`/`web` images **directly** — there
> is no wrapper-image layer. The launcher (`desktop/`) is a thin Electron app that shells out to
> `docker-compose.release.yml`; it reimplements no backend or web logic.

**The two pipelines**

| What | Workflow | Trigger | Output |
|---|---|---|---|
| Container images | [`.github/workflows/release.yml`](../.github/workflows/release.yml) | push a `vX.Y.Z` tag (or `workflow_dispatch`) | multi-arch images → `ghcr.io/legalquants/lq-ai-{api,gateway,web}` |
| macOS app | [`.github/workflows/desktop-release.yml`](../.github/workflows/desktop-release.yml) | push a `desktop-vX.Y.Z` tag (or `workflow_dispatch` with a `tag` input) | signed + notarized `.dmg` on a GitHub Release |

The two are **independent tags** so they can be cut separately. Cut the image release first (the
launcher pulls those images), then the desktop release.

---

## ⭐ Manual steps checklist (Kevin only — these cannot be automated)

CI runs on **`origin` = `github.com/LegalQuants/lq-ai`**, so the secrets and package visibility live
there. Do these once (secrets/visibility), then per-release (cut the tags).

### 1. Apple signing secrets (5) on the `LegalQuants/lq-ai` repo

The desktop workflow needs five secrets. The Developer ID is the existing **"Developer ID Application:
Tucuxi, Inc." (team `MC8BT9Z8GD`)** cert (valid to 2030, already on the build Mac).

| Secret | Value | Status |
|---|---|---|
| `MAC_CSC_LINK` | base64 of the re-exported `.p12` (cert + private key) | ⏳ pending |
| `MAC_CSC_KEY_PASSWORD` | the `.p12` export password | ⏳ pending |
| `APPLE_ID` | the Apple account email on the dev team | ⏳ pending |
| `APPLE_APP_SPECIFIC_PASSWORD` | a fresh app-specific password for notarytool | ✅ already set |
| `APPLE_TEAM_ID` | `MC8BT9Z8GD` | ⏳ pending |

Commands (run on the build Mac):

```bash
# (a) Confirm the identity + read the team ID (should print MC8BT9Z8GD):
security find-identity -v -p codesigning | grep "Developer ID Application"
#   → "Developer ID Application: Tucuxi, Inc. (MC8BT9Z8GD)"

# (b) Export the cert WITH its private key to a .p12, then base64 it.
#     In Keychain Access → My Certificates → right-click the cert that has a ▸ private key →
#     Export → save as cert.p12, set an export password. Then:
base64 -i cert.p12 -o cert.b64

# (c) App-specific password (only if regenerating): account.apple.com → Sign-In and Security →
#     App-Specific Passwords → generate (format abcd-efgh-ijkl-mnop). Requires 2FA.
#     NOTE: APPLE_APP_SPECIFIC_PASSWORD is already set on the repo.

# (d) Set the secrets on origin (gh keeps values out of shell history):
gh secret set MAC_CSC_LINK          -R LegalQuants/lq-ai < cert.b64
gh secret set MAC_CSC_KEY_PASSWORD  -R LegalQuants/lq-ai          # paste the .p12 export password
gh secret set APPLE_ID              -R LegalQuants/lq-ai          # paste the Apple ID email
gh secret set APPLE_TEAM_ID         -R LegalQuants/lq-ai --body "MC8BT9Z8GD"
# APPLE_APP_SPECIFIC_PASSWORD already set — skip unless rotating.

# (e) Delete the local key material:
rm cert.p12 cert.b64
```

`desktop-release.yml` maps `MAC_CSC_LINK`→`CSC_LINK`, `MAC_CSC_KEY_PASSWORD`→`CSC_KEY_PASSWORD`
(electron-builder signs with these) and passes the three `APPLE_*` through for notarization. The team
ID is **also** hardcoded in `desktop/electron-builder.yml` (`mac.notarize.teamId`) — electron-builder
does not read `APPLE_TEAM_ID` from the env for the native `.app` notarize step (Part C, Trap 1 of the
playbook). Both places are required.

### 2. GHCR package visibility — Public (org-policy trap)

GitHub Actions publishes packages **private**. Two layers, both UI actions (there is no reliable REST
API for this):

1. **Org policy.** If "Change visibility → Public" is **greyed out** ("disabled by organization
   administrators"), an **org owner** (not a plain member) must first enable public packages at
   `https://github.com/organizations/LegalQuants/settings/packages` → *Package creation* → allow
   **Public**.
2. **Per-package.** Then for each of `lq-ai-api`, `lq-ai-gateway`, `lq-ai-web`: org → Packages →
   package → *Package settings* → *Change visibility* → **Public**.

Verify anonymous pull (200 = public):

```bash
for img in lq-ai-api lq-ai-gateway lq-ai-web; do
  TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:legalquants/$img:pull" \
    | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
  code=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
    "https://ghcr.io/v2/legalquants/$img/manifests/vX.Y.Z")
  echo "$img -> $code"   # 200 = anonymously pullable
done
```

### 3. Cut the release

> **Versioning policy: [ADR 0025](adr/0025-release-versioning-and-pipeline-ordering.md).**
> `api`, `gateway`, `web`, and `proxy` share one release version — the `vX.Y.Z` image
> tag — and are bumped together on every release, including patch releases where only
> one component substantively changed. Before tagging, set **both**
> `api/app/__init__.py` and `gateway/app/__init__.py` to `X.Y.Z`; the
> `version-consistency` job in `release.yml` fails the tag push if they disagree with
> each other or with the tag. `web/package.json` tracks the OpenWebUI fork upstream and
> is **not** bumped to match.
>
> The desktop launcher versions independently (`desktop-vX.Y.Z`) and records which
> `vX.Y.Z` image set it ships against — see *Image ↔ launcher relationship* below.

#### 3a. Decide the number first

The number is **computed from what is on `main`**, not chosen from a milestone.
Milestones are planning tools; they do not decide the version.

```bash
# What has landed since the last release?
#   --merged main: web/ is a fork of OpenWebUI, and rebasing it brought upstream's
#   own vX.Y.Z tags into this repo (v0.9.2, v0.11.0). They are not reachable from
#   main, and without this filter they sort above the real last release. release.yml's
#   breaking-change gate applies the same filter.
git log "$(git tag --list 'v*.*.*' --merged main --sort=-v:refname \
             | grep -v '^desktop-' | head -1)"..main --no-merges --oneline
```

Read that list and ask one question of each entry: **does a working install need a
human to touch it after this upgrade?** A new environment variable, a changed
config key, a manual migration step, a required header, a removed endpoint — all
yes. Bug fixes, dependency bumps and output-side hardening — no.

- **Any "yes" in the list → the next release is a minor bump** (`0.6.x` → `0.7.0`).
- **All "no" → patch** (`0.6.2` → `0.6.3`).

A breaking PR does **not** wait for a `0.7.0` milestone to exist before merging.
Merging it is what makes the next release `0.7.0`.

Apply the **`breaking-change`** label at review time, so this is a lookup rather
than an act of memory:

```bash
gh pr list -R LegalQuants/lq-ai --label breaking-change --state merged --limit 100 \
  --json number,title,mergedAt
```

`release.yml`'s `version-consistency` job enforces this on tag push: it walks the
commit range back to the previous release tag, intersects the PR numbers it finds
with the `breaking-change` label, and **fails a patch tag** when any turn up. The
override is `[allow-breaking-in-patch]` in the tagged commit message — justify it
in the release PR.

> The gate is only as good as the labelling. An unlabelled breaking PR is
> invisible to it, so the label goes on at review time, not at release time.

> ⚠️ **Once a breaking change is on `main`, you can no longer cut a patch from
> `main`.** If an urgent fix has to ship *without* also shipping that change,
> branch from the last release tag, cherry-pick the fix, and cut from there:
>
> ```bash
> git checkout -b release/0.6.x v0.6.1
> git cherry-pick <fix-sha>
> # bump api + gateway __version__ to 0.6.2, commit, then tag from this branch
> ```
>
> This is deliberately manual — see ADR 0025 *Cadence* on why a standing
> release-branch discipline isn't worth its overhead at current capacity.

#### 3b. Tag

```bash
# (a) Images first — tag from a ref that CONTAINS the release Dockerfiles + release.yml (main):
git tag vX.Y.Z && git push origin vX.Y.Z
#   …or dispatch: gh workflow run release.yml -R LegalQuants/lq-ai
# release.yml then publishes multi-arch lq-ai-{api,gateway,web}:vX.Y.Z (+ :latest).

# (b) The macOS app — separate tag, runs on macos-14, needs the 5 Apple secrets:
git tag desktop-vX.Y.Z && git push origin desktop-vX.Y.Z
#   …or dispatch: gh workflow run desktop-release.yml -R LegalQuants/lq-ai -f tag=desktop-vX.Y.Z
```

> ⚠️ **Build images from a ref that actually contains the release Dockerfiles + `release.yml`** (e.g.
> `main`), not an older source tag that predates the pre-built-images feature. If you dispatch, pass
> the *image* tag separately (`-f tag=vX.Y.Z`) and point `ref` at `main`. Pushing a `vX.Y.Z` tag from
> `main` does this for you.

---

## Image ↔ launcher relationship

- The launcher renders an `.env` at runtime and runs `docker-compose.release.yml` under its own compose
  project (`lq-ai-desktop`), pulling `ghcr.io/${LQ_AI_IMAGE_NAMESPACE:-legalquants}/lq-ai-<svc>:${LQ_AI_IMAGE_TAG}`.
- **`LQ_AI_IMAGE_TAG`** pins the image version the launcher runs. The launcher config persists a tag
  — **today the shipped default is `latest`** (`desktop/src/main/index.ts`), so a fresh install floats
  to the newest published images rather than the set the `.dmg` was verified against. ADR 0025
  decides that each `desktop-vX.Y.Z` should instead record the `vX.Y.Z` it ships against; changing
  the default is tracked with that work. A hand-run stack pins it in `.env`
  ([`.env.release.example`](../.env.release.example)). Pin to a released `vX.Y.Z` for reproducibility;
  `latest` follows the newest published images.
- **`LQ_AI_IMAGE_NAMESPACE`** (default `legalquants`) overrides the GHCR namespace for forks/mirrors
  that publish `lq-ai-{api,gateway,web}` elsewhere — set it in `.env` (hand-run) so the compose pulls
  from your namespace.
- The release images are **self-contained**: the `api` image bakes the `skills/` corpus
  (`LQ_AI_SKILLS_DIR=/skills`) and the `gateway` image bakes the default gateway config it self-seeds —
  so the launcher needs **no bind mounts** (unlike the dev stack). The dev stack
  (`docker-compose.yml`) is untouched and keeps bind-mounting both.

---

## The desktop launcher (`desktop/`)

Layout (keep this split):

```
desktop/
  src/core/      PURE, unit-tested (vitest), NO electron import:
                 secrets · env (renderEnv) · ports · compose · engine · state · dockerPath · config
  src/main/      Electron main: lifecycle+IPC · runner (spawn) · store (safeStorage + .env) ·
                 orchestrator · paths · netcheck
  src/preload/   contextBridge IPC surface
  src/renderer/  vanilla-TS wizard + control panel
  electron.vite.config.ts · electron-builder.yml · build/ (entitlements + notarize-dmg.cjs) ·
  resources/ (compose copied in at build time by prepack:compose)
```

Gates: `cd desktop && npx vitest run` · `npx tsc --noEmit` · `npm run build` (electron-vite).
A local **unsigned** smoke build (no Apple creds needed): `CSC_IDENTITY_AUTO_DISCOVERY=false npm run dist`
→ an unsigned `.dmg` (`build/notarize-dmg.cjs` no-ops when Apple creds are absent).

---

## Code signing & notarization (the hard-won recipe)

electron-builder (24.13) does **not** produce a Gatekeeper-passing DMG out of the box. The working
config (`desktop/electron-builder.yml`) and the 3 traps:

```yaml
mac:
  hardenedRuntime: true
  entitlements: build/entitlements.mac.plist
  entitlementsInherit: build/entitlements.mac.plist
  notarize:
    teamId: MC8BT9Z8GD              # TRAP 1
afterAllArtifactBuild: build/notarize-dmg.cjs   # TRAP 2
dmg:
  sign: true                       # TRAP 2
```

- **Trap 1 — `notarize: true` fails "the teamId property is required."** electron-builder does *not*
  read `APPLE_TEAM_ID` from the env for native notarization; `teamId` **must** be in the config.
- **Trap 2 — native notarize only signs+notarizes the `.app`,** then builds a **bare `.dmg`** that is
  neither signed nor stapled → the *downloaded* dmg fails Gatekeeper. Fix: `dmg.sign: true` **plus** an
  `afterAllArtifactBuild` hook (`build/notarize-dmg.cjs`) that runs
  `xcrun notarytool submit <dmg> --apple-id … --team-id … --wait` then `xcrun stapler staple <dmg>`. A
  *stapled-but-unsigned* dmg still fails ("no usable signature") — it needs **both**.
- **Trap 3 — the preload must be `.mjs`.** electron-vite emits `out/preload/index.mjs` (the package is
  `"type": "module"`); the main process must reference `../preload/index.mjs` or the IPC bridge is
  `undefined`. `sandbox: false` is kept (a sandboxed preload can't be ESM); `contextIsolation` (on by
  default) is the real boundary.

The dmg artifact name electron-builder produces is `${productName}-${version}-${arch}.dmg` →
**`LQ.AI-<version>-<arch>.dmg`** (e.g. `LQ.AI-0.4.0-arm64.dmg`).

### Verify the *published* artifact (not the CI exit code)

`gh run watch --exit-status` can report exit 0 on a *failed* run — trust `gh run view <id> --json
conclusion` AND verify the actual artifact:

```bash
gh release download desktop-vX.Y.Z -R LegalQuants/lq-ai -p '*.dmg' -D /tmp --clobber
spctl -a -vvv -t open --context context:primary-signature /tmp/LQ.AI-*.dmg
#   want: accepted / source=Notarized Developer ID / origin=Developer ID Application: Tucuxi, Inc. (MC8BT9Z8GD)
xcrun stapler validate /tmp/LQ.AI-*.dmg     # "The validate action worked!"
```

---

## See also

- [`docs/INSTALL-MAC.md`](INSTALL-MAC.md) — the end-user install guide.
- [`desktop/VERIFICATION.md`](../desktop/VERIFICATION.md) — the release-time verification protocol.
- [`docs/lq-ai-macos-launcher-playbook.md`](lq-ai-macos-launcher-playbook.md) — the full playbook this
  is distilled from (Parts C/D/E carry the signing + real-launch detail).
