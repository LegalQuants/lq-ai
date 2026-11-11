# Building & releasing LQ.AI — container images + the macOS app

This is the operator's guide for shipping LQ.AI: the **pre-built container images** published to GHCR
and the **"LQ.AI for Mac" desktop launcher** (a signed, notarized `.dmg`). It is written for whoever
cuts the next release, and it records the **dead-ends and fixes** hit the first time so they don't get
re-discovered.

> Because LQ.AI owns its own code, it publishes its `api`/`gateway`/`web`/`proxy` images **directly** — there
> is no wrapper-image layer. The launcher (`desktop/`) is a thin Electron app that shells out to
> `docker-compose.release.yml`; it reimplements no backend or web logic.

**The two pipelines**

| What | Workflow | Trigger | Output |
|---|---|---|---|
| Container images | [`.github/workflows/release.yml`](../.github/workflows/release.yml) | push a `vX.Y.Z` tag (`workflow_dispatch` only rehearses; see 3b) | multi-arch images → `ghcr.io/legalquants/lq-ai-{api,gateway,web,proxy}` |
| macOS app | [`.github/workflows/desktop-release.yml`](../.github/workflows/desktop-release.yml) | push a `desktop-vX.Y.Z` tag (or `workflow_dispatch` with a `tag` input) | signed + notarized `.dmg` on a GitHub Release |

The documentation site follows on its own: `docs/releases/vX.Y.Z.md` in the release PR becomes the
release page when that PR merges, and when the image release finishes,
[`.github/workflows/docs-site.yml`](../.github/workflows/docs-site.yml) redeploys `main` so the
release-notes index lists the new tag. Nothing to run by hand; `workflow_dispatch` on that workflow
rebuilds it if a tag is added or moved later.

The two are **independent tags** so they can be cut separately. Cut the image release first (the
launcher pulls those images), then the desktop release.

---

## ⭐ Manual steps checklist — one-time setup, now done; keep for rotation

CI runs in **`github.com/LegalQuants/lq-ai`**, so the secrets and package visibility live there.
Any maintainer who can push tags there can cut a release, including the signed `.dmg`. Steps 1
and 2 are one-time setup and are done; keep them for rotation. Step 3 is per release.

### 1. Apple signing secrets (5) on the `LegalQuants/lq-ai` repo

The desktop workflow needs five secrets. The Developer ID is the existing **"Developer ID Application:
Tucuxi, Inc." (team `MC8BT9Z8GD`)** cert (valid to 2030, already on the build Mac). It lives in
Tucuxi, Inc.'s Apple Developer account, which [ADR 0025](adr/0025-release-versioning-and-pipeline-ordering.md)
*Cadence* says is tied to the founder's own developer account. Only that account's Account Holder
can accept a new Apple agreement, rotate the certificate or mint a new app-specific password.

All five secrets are set: `desktop-v0.8.0` signed and notarized with them. `desktop-v0.9.0` failed
at notarization on a missing or expired Apple agreement, not on a secret (see 3d).
`gh run list -R LegalQuants/lq-ai --workflow desktop-release.yml --limit 5` shows recent runs.

| Secret | Value |
|---|---|
| `MAC_CSC_LINK` | base64 of the re-exported `.p12` (cert + private key) |
| `MAC_CSC_KEY_PASSWORD` | the `.p12` export password |
| `APPLE_ID` | the Apple account email on the dev team |
| `APPLE_APP_SPECIFIC_PASSWORD` | an app-specific password for notarytool |
| `APPLE_TEAM_ID` | `MC8BT9Z8GD` |

Commands, only after a certificate or password rotation (run on the build Mac):

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
2. **Per-package.** Then for each of `lq-ai-api`, `lq-ai-gateway`, `lq-ai-web`, `lq-ai-proxy`: org → Packages →
   package → *Package settings* → *Change visibility* → **Public**.

Verify anonymous pull (200 = public). The images are OCI indexes, and without the `Accept`
header GHCR answers 404 even for a public image:

```bash
ACCEPT='application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json'
for img in lq-ai-api lq-ai-gateway lq-ai-web lq-ai-proxy; do
  TOKEN=$(curl -s "https://ghcr.io/token?scope=repository:legalquants/$img:pull" \
    | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
  code=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
    -H "Accept: $ACCEPT" "https://ghcr.io/v2/legalquants/$img/manifests/vX.Y.Z")
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
> each other or with the tag. Regenerate the committed backend OpenAPI export with
> `make openapi` so its `info.version` matches the API version; the export drift guard
> checks it in CI. `web/package.json` tracks the OpenWebUI fork upstream and is **not**
> bumped to match.
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

**After 1.0** ([ADR 0029](adr/0029-definition-of-1.0.md) R3), the same question
answers what each level asks of an operator: a **patch** is a blind upgrade; a
**minor** means read the release notes and expect that operator action may be
needed; a **major** can break a working install's data, configuration or API
contracts — plan for it. Per [ADR 0031](adr/0031-headless-api-only-use.md), the
patch and minor promises do not extend to third-party API clients; "API
contracts" means the contracts the project's own clients rely on.

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

#### 3a-bis. Prepare the release PR

Everything here lands on `main`, in the release PR, before the tag. A pushed release tag does not
move, so none of it can wait until after.

1. Set `api/app/__init__.py` and `gateway/app/__init__.py` to `X.Y.Z`, then run `make openapi`.
2. `cd desktop && npm version X.Y.Z --no-git-tag-version`. Expect a three-line diff (`package.json`,
   and the lockfile's root and `packages[""]`). Nothing in CI checks this, and the `.dmg` is named
   from it.
3. Write `docs/releases/vX.Y.Z.md`, then cross-check it against the range. List the PRs merged since
   the last release and compare them with the PR numbers the notes cite:

   ```bash
   prev=$(git tag --list 'v*.*.*' --merged main --sort=-v:refname | grep -v '^desktop-' | head -1)
   git log "$prev"..main --no-merges --pretty=%s | grep -oE '\(#[0-9]+\)$' | tr -d '(#)' | sort -u > in-range
   ```

   A squash commit without a `(#N)` suffix needs a look by hand.
4. Audit the `breaking-change` label on this release's PRs only (3a's lookup lists the label's whole
   history):

   ```bash
   gh pr list -R LegalQuants/lq-ai --label breaking-change --state merged --limit 200 \
     --json number -q '.[].number' | sort -u > labelled
   comm -12 in-range labelled   # each line is a PR that fails a patch tag
   ```

   Remove a wrong label, or make the release a minor. The `[allow-breaking-in-patch]` and
   `[allow-version-drift]` overrides are read from the tagged commit's message, which is the release
   PR's squash message, so decide them before the merge.
5. Mutation evidence: follow *Preserve validated mutation evidence* below, or write "mutation score
   unavailable" in the notes.
6. Rehearse before the PR leaves draft. Dry-run the image pipeline on a branch in
   `LegalQuants/lq-ai` (`gh workflow run release.yml -R LegalQuants/lq-ai --ref <branch> -f dry_run=true`;
   nothing is pushed or signed). Then do a fresh install, and an upgrade from the previous release
   with its data preserved, on release images built from the branch.
7. Once the release PR merges, merge nothing else to `main` until the tag is pushed, or redo 3 and 4.

##### Preserve validated mutation evidence (DE-229)

The scoped nightly workflow is informational, not a release score threshold.
Before publishing a percentage, select a run with valid evidence for **both**
packages; a successful old PR CI run is not a mutation baseline.

```bash
# Discover a valid candidate and download to separate package directories:
gh run list -R LegalQuants/lq-ai --workflow=mutation.yml --status=success -L 5
gh run download <run-id> -R LegalQuants/lq-ai -n mutation-api-<run-id> -D /tmp/mutation-api
gh run download <run-id> -R LegalQuants/lq-ai -n mutation-gateway-<run-id> -D /tmp/mutation-gateway
```

Confirm both `mutation-score.json` reports have `status: valid` and `measurement_origin: github-actions`, identify the
measured commit and agree with the raw counts. Check module/test selections,
configuration/lock digests and tool version before comparing to older scores.
Use a fresh run if the tested code, configuration, dependency tree or tool has
changed. Label any difference between the measured commit and the release commit.
If no valid, applicable run exists, publish **“mutation score unavailable”**;
do not reuse an older or incomplete number.

Preserve each package's report, raw CI counts and outcome list in separate
`api/` and `gateway/` directories under
`docs/quality/mutation-baselines/<release>/` in the release PR. Add the history row
in `docs/quality/mutation-scores.md` with permanent links to those files; reference
the same links and measured commits in release notes. The source run URL remains
in each report. GitHub's 90-day artifacts are diagnostic storage only and are
not the durable source for a future README badge.

Full DE-229 acceptance, including the badge/feed and excluded scopes, remains
open in PRD §9 and follow-up tracker [#718](https://github.com/LegalQuants/lq-ai/issues/718). Issue #380
closes with the scoped Python implementation in PR #434, not full DE-229 acceptance.

#### 3b. Tag the images

Tag from a dedicated clone of `LegalQuants/lq-ai`. In a fork checkout `origin` is the fork, so
commands written with `origin` would tag a stale commit there and push the tag where it publishes
nothing.

```bash
# --no-tags keeps OpenWebUI's bare tags (its v0.9.1 is one) out of this clone. It also leaves the
# clone with no release tags, so do 3a and 3a-bis in your normal clone and use this one only to tag.
git clone --no-tags --single-branch --branch main https://github.com/LegalQuants/lq-ai.git /tmp/lq-ai-release
cd /tmp/lq-ai-release
git remote get-url origin        # must print https://github.com/LegalQuants/lq-ai.git
# Both tags must be unused on the remote:
test -z "$(git ls-remote --tags origin refs/tags/vX.Y.Z refs/tags/desktop-vX.Y.Z)" || echo "TAG ALREADY EXISTS - stop"
RELEASE_COMMIT=PASTE_FULL_SHA    # the merged release PR's squash commit, never a branch name
git show -s --format='%H %s' "$RELEASE_COMMIT"    # confirm it is the release PR
git merge-base --is-ancestor "$RELEASE_COMMIT" origin/main && echo ok
git tag -a vX.Y.Z "$RELEASE_COMMIT" -m "Release vX.Y.Z"
git push origin refs/tags/vX.Y.Z
# release.yml then publishes multi-arch lq-ai-{api,gateway,web,proxy}:vX.Y.Z (+ :latest).
```

> ⚠️ **If you tag from your normal clone instead, check the tag name is free there first:**
> `git tag -l vX.Y.Z` must print nothing.
> A clone that once fetched OpenWebUI's tags bare can hold upstream's tag of the same name (its
> `v0.9.1` is an April 2026 OpenWebUI commit). `git tag -a` then refuses, and pushing the existing
> tag would publish OpenWebUI's commit as `vX.Y.Z` on LegalQuants and run whatever tag-triggered
> workflows that commit carries. Confirm with `git log -1 vX.Y.Z` that it is
> not LQ.AI's, delete it locally with `git tag -d vX.Y.Z`, and see the
> [rebase runbook](openwebui-rebase-runbook.md) for keeping upstream's tags under `owui/`.
> The `ls-remote` check above is the stronger one: it asks LegalQuants, not your clone.

> ⚠️ **`release.yml` cannot cut a release by dispatch.** Its only input is `dry_run`, and a
> dispatched run is tagged `dryrun-<sha7>`. `gh workflow run release.yml -R LegalQuants/lq-ai
> --ref <branch> -f dry_run=true` rehearses the build; nothing is pushed or signed. Never pass
> `dry_run=false` from a branch: it publishes `:dryrun-<sha7>` and moves `:latest`. Cut a release
> only by pushing the `vX.Y.Z` tag, on a commit that contains the release Dockerfiles and
> `release.yml`.

#### 3c. Verify what actually published

The green tick is not the artifact. Within a build stage one image can push while a sibling fails
([ADR 0025](adr/0025-release-versioning-and-pipeline-ordering.md) *Consequences*), and each image's
own build moves `:latest`.

1. `gh run view <run-id> -R LegalQuants/lq-ai --json conclusion,jobs`: the run and every job in it
   must be `success`.
2. The anonymous-pull loop in step 2: four 200s.
3. Signatures, the SBOM attestation and provenance for all four images, with the commands in
   [`docs/security/releases/README.md`](security/releases/README.md). They were checked against
   v0.9.0 with cosign 3.1.4. If cosign's major version or the commands change, run them against
   the previous release first. On cosign 3 they fail without `--new-bundle-format=false`, because
   `release.yml` signs with cosign 2.4 in the older registry layout.
4. Bring the stack up from the published `vX.Y.Z` images under its own project name
   ([`desktop/VERIFICATION.md`](../desktop/VERIFICATION.md) Protocol 1), and repeat the upgrade
   check from the previous release on them.
5. The api's and the gateway's `/health` both report `X.Y.Z`.

Do not cut `desktop-vX.Y.Z` until 1 to 3 pass.

#### 3d. Cut the desktop release

`desktop-vX.Y.Z` bakes the image tag `vX.Y.Z` into the launcher, so the images must already be
public and verified (3c). The workflow runs on macos-14 and needs the five Apple secrets.

**Before tagging, confirm Apple will accept a submission.** Notarization fails after the build, not
before it, and only the Apple Developer Account Holder can fix a missing or expired agreement (step
1). On the build Mac, with the credentials the secrets hold:

```bash
xcrun notarytool history --apple-id "$APPLE_ID" --team-id MC8BT9Z8GD --password "$APPLE_APP_SPECIFIC_PASSWORD" | head
```

A list of submissions, or an empty one, means go. `HTTP status code: 403. A required agreement is
missing or has expired` means stop: the Account Holder signs in at developer.apple.com and accepts
the updated agreement, then run the command again. `desktop-v0.9.0` failed this way on 8 October
2026 (runs 37742473395 and 37744182078).

Then, in the release clone from 3b:

```bash
git tag -a desktop-vX.Y.Z "$RELEASE_COMMIT" -m "Desktop release vX.Y.Z"
git push origin refs/tags/desktop-vX.Y.Z
#   …or dispatch: gh workflow run desktop-release.yml -R LegalQuants/lq-ai -f tag=desktop-vX.Y.Z
```

Verify the `.dmg` as in *Verify the published artifact* below.

| Symptom in `desktop-release.yml` | Meaning | Do |
|---|---|---|
| `Unexpected token 'E', "Error: HTT"... is not valid JSON` | notarytool printed an HTTP error instead of JSON, hiding the real one | Run the `notarytool history` command above; a 403 means the agreement |
| Signing succeeds, then notarization fails with 403 "A required agreement is missing or has expired" | The Apple account, not a repository secret | The Account Holder accepts the agreement, then rerun the failed run (`gh run rerun <run-id>`). It builds from the tagged commit, so the tag need not move; this has not yet been tried on this workflow. |

#### 3e. Publish and tidy

`release.yml` creates no GitHub Release page. The desktop workflow publishes its own page and does
not set Latest, so the order of the two decides which page GitHub calls Latest.

- After the desktop run has finished, create the `vX.Y.Z` page from the existing tag with the notes
  as its body:
  `gh release create vX.Y.Z -R LegalQuants/lq-ai --verify-tag --title "vX.Y.Z — <summary>" --notes-file docs/releases/vX.Y.Z.md --latest`.
  If the `.dmg` is not ready, publish anyway and say in the body that it will follow. Check that
  `gh release list -R LegalQuants/lq-ai` shows `vX.Y.Z`, not `desktop-vX.Y.Z`, as Latest;
  `gh release edit vX.Y.Z -R LegalQuants/lq-ai --latest` fixes it.
- Close the `vX.Y.Z` milestone, and move any open issues to the next one.

---

## Image ↔ launcher relationship

- The launcher renders an `.env` at runtime and runs `docker-compose.release.yml` under its own compose
  project (`lq-ai-desktop`), pulling `ghcr.io/${LQ_AI_IMAGE_NAMESPACE:-legalquants}/lq-ai-<svc>:${LQ_AI_IMAGE_TAG}`.
- **`LQ_AI_IMAGE_TAG`** pins the image version the launcher runs. The desktop release workflow
  converts `desktop-vX.Y.Z` to `vX.Y.Z` and bakes it into the main process at build time. New installs
  persist that exact tag; each launcher upgrade aligns the encrypted config and generated `.env` to
  its baked release tag. Local developer builds retain `latest`. This implements ADR 0025 decision 2
  and gives ADR 0037's migration walk a known target. A hand-run stack sets the same variable in
  [`.env.release.example`](../.env.release.example), which ships as `latest`; pin it to the release
  tag.
- **`LQ_AI_IMAGE_NAMESPACE`** (default `legalquants`) overrides the GHCR namespace for forks/mirrors
  that publish `lq-ai-{api,gateway,web,proxy}` elsewhere — set it in `.env` (hand-run) so the compose pulls
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

- [`docs/quality/mutation-scores.md`](quality/mutation-scores.md) — the per-release mutation-score
  record (step 3a-bis above).
- [`docs/INSTALL-MAC.md`](INSTALL-MAC.md) — the end-user install guide.
- [`desktop/VERIFICATION.md`](../desktop/VERIFICATION.md) — the release-time verification protocol.
- [`docs/lq-ai-macos-launcher-playbook.md`](lq-ai-macos-launcher-playbook.md) — the full playbook this
  is distilled from (Parts C/D/E carry the signing + real-launch detail).
