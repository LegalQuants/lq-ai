# Word Add-In

> The Word Add-In brings LQ.AI into Microsoft Word as an Office.js
> task pane that authenticates against the operator's self-hosted
> deployment. Per PRD §3.9 / §1.3 (transparency as a founding
> principle): what shipped in M3 Phase B is **plumbing** — install,
> authenticate, version-check — not the rich in-Word feature surface.
> This document is scrupulous about that boundary because overclaiming
> a half-built feature is exactly the failure mode the project's
> conservative posture exists to prevent.

This doc describes the add-in's architecture, the unsigned-manifest
install path, the OAuth flow over the Office.js Dialog API, and the
M3-B8 version handshake. It is the implementation companion to
[PRD §3.9 Word Add-In](PRD.md#39-word-add-in-m3). The add-in lives in
[`word-addin/`](../word-addin/); its backend surface is
[`api/app/api/word_addin.py`](../api/app/api/word_addin.py).

---

## Scope

"The Word Add-In" can mean two very different things, and M3 ships only
the first. Both are tracked explicitly so the boundary is unambiguous.

1. **The plumbing** *(this surface, shipped in M3 Phase B)* — the
   add-in is installable into Word via an unsigned XML manifest, it
   authenticates against the deployment over OAuth, and it checks its
   own version against the deployment on mount. After authenticating,
   the task pane renders a tab strip whose every tab shows a
   **deep-link card** pointing at the equivalent LQ.AI web-app surface.
   The add-in is usable — sign in, see the document is recognized,
   click through to the web app — but it does not yet act on the open
   document.

2. **The feature surface** *(not built; tracked at
   [PRD §9 DE-287](PRD.md#de-287--word-add-in-feature-surface-chat-skills-playbooks-tier-badge--deferred-to-m4--community-contribution))*
   — chat against the open document, running skills with redlines as
   tracked changes and assessments as Word comments, playbook
   execution with per-position rendering, and the Inference Tier badge.
   This is the work the PRD §3.9 user stories describe ("click Apply
   MSA-SaaS Playbook; the system applies tracked changes + comments").
   It is descoped to M4 / community contribution. At v0.3.0 each tab is
   a deep-link card placeholder.

A third concern — the **signed manifest + enterprise distribution
package** (M3-B7) — is descoped to a community-led effort and tracked
at [PRD §9 DE-295](PRD.md#de-295--word-add-in-code-signing-certificate--signed-manifest-ci-community-led).
Only the unsigned-manifest sideload path verifies in M3. References to
"the Word Add-In" elsewhere in the codebase mean the M3 plumbing unless
explicitly qualified.

---

## Architecture

The add-in is a standard Office.js task pane add-in: a manifest that
registers a ribbon button + a hosted HTML/JS bundle Word loads into a
sandboxed iframe when the user opens the pane.

| Piece | Where | What it is |
|---|---|---|
| Manifest | [`word-addin/manifest.xml`](../word-addin/manifest.xml) | Office Add-in **XML 1.1+** manifest template. Registers the `TabHome` ribbon button + the task-pane URL. Carries four `{{ DOUBLE_BRACE }}` tokens substituted at install time. |
| Task pane shell | [`word-addin/src/taskpane/`](../word-addin/src/taskpane/) | React 18 + TypeScript. `taskpane.html` is the page Office loads; `taskpane.tsx` mounts `App.tsx`. |
| Commands | [`word-addin/src/commands/`](../word-addin/src/commands/) | Office.js ribbon command surface. No commands wired in M3; feature work lands here. |
| Bundler | [`word-addin/webpack.config.js`](../word-addin/webpack.config.js) | Webpack (bundler of record per Phase B Decision B-1). Bundles to `dist/`. |

The XML manifest — not the JSON unified manifest — is the production
path for v0.3.0 per **Phase B Decision B-2**: the JSON unified manifest
was still in preview for Word as of early 2026. Migration to the unified
manifest is a deferred follow-on once it reaches GA for Word.

The add-in talks to the **same FastAPI backend as the web app** over
the same OpenAPI surface. There are no Word-specific backend endpoints
for the feature path — the two endpoints in
[`api/app/api/word_addin.py`](../api/app/api/word_addin.py) exist purely
for the plumbing (manifest generation and version handshake); OAuth
reuses `/api/v1/auth/login`, `/auth/refresh`, and `/auth/logout`.

### Bundle hosting

Per the PRD §3.9 open question, the chosen hosting model is **(a) the
self-hosted deployment serves its own add-in bundle**, minimizing
external dependencies. The manifest points `SourceLocation` at
`{deployment_origin}/word-addin/taskpane.html`, so the bundle is served
from the operator's own origin. The version handshake's
`taskpane_bundle_url` exists so a future deployment can relocate the
bundle (CDN, operator-chosen path) without re-issuing the manifest.

---

## Unsigned-manifest install path

This is the install path that verifies in M3. The operator generates a
manifest from the admin UI and sideloads it via Microsoft 365 Admin
Center.

### Admin-side manifest generation

`GET /api/v1/admin/word-addin/manifest` (admin-only,
[`get_manifest`](../api/app/api/word_addin.py)) renders the template and
returns `application/xml` with a `Content-Disposition: attachment`
header so the browser downloads `lq-ai-word-addin-manifest.xml` rather
than rendering it inline.

The template carries four `{{ TOKEN }}` placeholders. Rendering is a
pure function ([`render_manifest`](../api/app/api/word_addin.py),
separated from the handler so unit tests cover every substitution path
without the app). The token regex tolerates extra whitespace inside the
braces but treats token names as case-sensitive `[A-Z_]+`:

| Token | Source | Default |
|---|---|---|
| `ADDIN_ID` | Freshly generated `uuid4` per invocation when not overridden — each install is uniquely addressable in the M365 catalog. | new GUID |
| `DEPLOYMENT_ORIGIN` | Resolved from the request; trailing slash stripped. | request origin |
| `DEPLOYMENT_DISPLAY_NAME` | `display_name` query param. Surfaced in Word's ribbon + GetStarted message. | `LQ.AI` |
| `PROVIDER_NAME` | `provider_name` query param. The `ProviderName` M365 Admin Center surfaces. | `LegalQuants` |

`render_manifest` **raises `ValueError` on an unknown token** — if the
template drifts to reference a token the renderer doesn't supply,
generation fails loudly rather than emitting a half-substituted
manifest. The rendered output is fixed at `<Version>0.3.0.0</Version>`
(the manifest's own version, distinct from the deployment version).

### Deployment-origin resolution

[`_resolve_deployment_origin`](../api/app/api/word_addin.py) derives the
origin baked into the manifest, in preference order:

1. An explicit `deployment_origin` query param — lets one ops team
   generate a manifest for a different deployment than the one serving
   the admin UI.
2. `X-Forwarded-Proto` + `X-Forwarded-Host`/`Host` headers — what the
   reverse proxy reports, matching what users see in the address bar.
3. The request URL's scheme + netloc — final fallback for single-process
   dev setups.

### Template sync

The template is bundled into the api image at
`api/app/data/word_addin_manifest.xml` and loaded at request time via
`importlib.resources` ([`_load_manifest_template`](../api/app/api/word_addin.py)).
The source of truth is the sibling `word-addin/manifest.xml`; a sync
test in `api/tests/test_word_addin_endpoints.py` asserts the two files
match byte-for-byte so any change to the add-in's manifest flows into
the api package.

### Operator sideload flow

Per [`word-addin/README.md`](../word-addin/README.md):

1. Admin UI → **Admin → Word add-in** → **Generate manifest** (downloads
   the rendered XML).
2. Microsoft 365 Admin Center → **Settings → Integrated apps → Upload
   custom apps** → **Office Add-in** → upload the manifest.
3. Assign to users / groups.
4. Users see the branded button appear in Word's Home ribbon within a
   few minutes (Office checks the catalog on Word startup).

**M365 will warn about the unsigned add-in during install.** That
warning is expected at v0.3.0 — the signed distribution package is
DE-295 (see [Threat model](#threat-model--security)). The signed
`word-addin-v0.3.x.zip` GitHub Release asset lands as a community PR once
code-signing certificate procurement closes.

---

## OAuth flow (M3-B2)

The task pane cannot use a browser popup for OAuth — it runs inside a
sandboxed Office iframe. It uses Office's own dialog primitive instead,
and per **Phase B Decision B-3** it authenticates against the LQ.AI
deployment's **existing JWT issuer**, not MSAL/WAM.

The flow ([`dialog.ts`](../word-addin/src/taskpane/dialog.ts),
[`SignInGate.tsx`](../word-addin/src/taskpane/components/SignInGate.tsx),
[`auth.ts`](../word-addin/src/taskpane/auth.ts)):

1. The user clicks **Sign in** in the `SignInGate`.
2. `openOAuthDialog()` calls `Office.context.ui.displayDialogAsync`
   against `{deployment_origin}/lq-ai/word-addin/oauth-start` — a
   SvelteKit route on the same deployment rendering a standard LQ.AI
   login form. Office opens this in a separate managed window.
3. On successful login the dialog page calls
   `Office.context.ui.messageParent` with a JSON `oauth-success` payload
   mirroring the backend's `LoginResponse` wire shape.
4. The task pane parses the message, closes the dialog, and hands the
   payload to `storeSession()`.
5. Subsequent API calls go through `authenticatedFetch`, which attaches
   the bearer token and handles the 401-refresh-retry.

The dialog wrapper resolves to one of three outcomes — `success`,
`error`, or `cancelled` — translating Office's callback-based,
error-coded API into a clean async contract. Office error `12006` (the
documented "dialog closed" code) maps to `cancelled` and is silent; the
user dismissed the dialog deliberately. Other non-zero error codes
surface as `error`.

### Token storage and lifecycle

- **Storage:** `localStorage` under `lq-ai-word-addin-session`, **not**
  `Office.context.document.settings`. The deliberate choice
  (documented in `auth.ts`): document settings would tie the auth to a
  specific Word document; `localStorage` is cross-document and
  cross-session per browser profile, so a user signs in once and the
  session follows them across documents in the same client + profile.
- **Refresh:** on a 401, `authenticatedFetch` attempts a single refresh
  via `POST /api/v1/auth/refresh`; on failure it drops the session and
  the next render surfaces the sign-in gate. Concurrent refreshes
  **coalesce** around one in-flight promise so a burst of parallel API
  calls triggers one refresh, not N.
- **Expiry:** `expires_at` is computed from the wire `expires_in` at
  storage time (avoiding clock-skew drift). The local expiry check is
  best-effort — the backend remains the authority and will 401 if the
  local guess is wrong.
- **Logout:** best-effort — calls `/api/v1/auth/logout` to invalidate
  the refresh token server-side, then clears `localStorage` regardless
  of whether the server call succeeded.

### No add-in-scoped token

v0.3.0 uses the **same bearer token shape as the web app** — no
`aud: word-addin` claim, no per-client audience scoping. A future DE may
add per-client audience scoping if endpoint-level revocation becomes
load-bearing. Documenting this is the honest posture: the add-in is not
a separate trust principal from the web app today.

---

## Version handshake (M3-B8)

The handshake exists so an out-of-date add-in surfaces an "Update
needed" overlay rather than getting stuck against a breaking-change API
call after the user has already signed in. It is **real and works** —
distinct from the deferred feature surface.

### Backend

`GET /api/v1/word-addin/version`
([`get_version`](../api/app/api/word_addin.py)) is **unauthenticated** —
the task pane consults it on mount, before the user has signed in, so
the route is mounted on `public_router` with no `ActiveUser` gate (same
pattern as the bootstrap router). It returns `WordAddinVersionResponse`:

| Field | Value | Notes |
|---|---|---|
| `deployment_version` | api package `__version__` = `0.3.0` | Informational only — the add-in does **not** use this for compatibility decisions; it surfaces it in the overlay so the user can quote it to support. |
| `addin_min_compatible_version` | `0.3.0` (`ADDIN_MIN_COMPATIBLE_VERSION`) | Lowest add-in version the deployment accepts. Bumped when a breaking change lands in the task-pane bundle, forcing operators to redistribute the manifest. |
| `addin_max_compatible_version` | `0.3.99` (`ADDIN_MAX_COMPATIBLE_VERSION`) | Highest recognized version. Defaults to accept every `0.3.x` patch so cosmetic add-in fixes don't require a deployment bump; raises when M4 features ship. |
| `taskpane_bundle_url` | `{origin}/word-addin/taskpane.html` | Canonical bundle entry point. Exists so a future deployment can relocate the bundle without re-issuing the manifest. |
| `taskpane_bundle_hash` | `null` | Optional SHA-256 of the deployed bundle JS. **Ships nullable in M3-B8**; signing CI (DE-295) would populate it. `null` means "don't enforce" — not an error. |

`deployment_version` is sourced from
[`api/app/__init__.py`](../api/app/__init__.py) `__version__`, currently
`"0.3.0"`.

### Add-in side

[`version.ts`](../word-addin/src/taskpane/version.ts) `fetchVersionInfo()`
runs once on mount in `App.tsx`. The installed version is
`__ADDIN_VERSION__` — a string webpack's `DefinePlugin` bakes into the
bundle from `package.json` (currently `0.3.0-dev`; `parseVersion` strips
the non-numeric suffix to `[0, 3, 0]`). Baking it in means **a tampered
API response can't lie about the installed version** — the comparison
floor comes from the bundle, not the network.

`classifyVersion` compares the installed version against the range using
a simple int-segment lexicographic compare (`compareVersions`). Four
outcomes:

| `installed` vs range | Status | UI |
|---|---|---|
| `< min` | `addin_outdated` | Blocking overlay — operator redistributes a newer manifest. |
| `> max` | `deployment_outdated` | Blocking overlay — operator updates the deployment. |
| within range | `compatible` | Normal sign-in / authenticated layout. |
| handshake failed | `unknown` | **Non-blocking** soft banner; the add-in still renders so an offline operator isn't locked out. |

`fetchVersionInfo` never throws — a network or parse failure yields
`status="unknown"` rather than crashing the pane. This is the
best-effort posture: a misconfigured or offline deployment should not
prevent the user from seeing the task pane at all.

### Three exclusive App states

[`App.tsx`](../word-addin/src/taskpane/components/App.tsx) renders
exactly one of:

1. **Update-needed overlay**
   ([`UpdateNeededOverlay`](../word-addin/src/taskpane/components/UpdateNeededOverlay.tsx))
   — only for the two strict-incompatibility statuses. Blocks every
   other path so an out-of-date add-in can't proceed to a doomed OAuth
   handshake. Shows installed/deployment/range versions for the user to
   quote to their admin.
2. **Sign-in gate** — version compatible (or `unknown`) but no stored
   session. A `unknown` handshake adds a soft `VersionUnknownBanner`.
3. **Authenticated layout** — header + tab strip + deep-link card per
   tab. The card bodies state plainly that the in-Word feature is on the
   M4 / community roadmap (DE-287) and link to the equivalent web-app
   surface.

---

## Configuration

The add-in has a deliberately small operator-facing configuration
surface — most of it is baked at manifest-generation time, not runtime
config.

- **Manifest tokens** — `display_name` and `provider_name` are
  per-request query params on the generate-manifest call;
  `deployment_origin` and `addin_id` resolve automatically (origin from
  the request, GUID freshly generated). No `gateway.yaml` /
  `settings`-level knobs.
- **Compatibility range** — `ADDIN_MIN_COMPATIBLE_VERSION` /
  `ADDIN_MAX_COMPATIBLE_VERSION` are **module constants** in
  `word_addin.py`, not operator config. They are bumped by maintainers
  when breaking changes land, not tuned per deployment.
- **Bundle hosting** — served by the deployment from
  `/word-addin/taskpane.html`. Build with `npm run build` in
  `word-addin/`; deploy by copying `dist/` to the deployment's
  static-serving path (see `word-addin/README.md`).

---

## Threat model / security

The add-in is an **external trust boundary**: Office.js code runs inside
the user's Word client (desktop, Online, or iPad), in an iframe under
the deployment's origin, and authenticates against the deployment over
the network. Several properties of the M3 posture matter for security
review.

### Unsigned-manifest posture

v0.3.0 ships **only the unsigned-manifest install path**. Microsoft 365
Admin Center will warn the admin that the add-in is unsigned during
upload. Implications:

- The warning is **expected and correct** at v0.3.0 — the project does
  not yet hold a code-signing certificate. The signed manifest + signed
  distribution package is DE-295, descoped to a community-led effort
  (SignPath open-source sponsorship is the recommended first path;
  community-funded DigiCert EV / Sectigo OV are alternatives).
- The trust decision at install time rests with the **admin**, who is
  uploading a manifest they generated from their own deployment's admin
  UI. The manifest points only at the operator's own
  `DEPLOYMENT_ORIGIN` (the single `<AppDomain>`), so the install does
  not widen the navigation surface beyond the deployment the admin
  already trusts.
- A signed manifest would let the admin verify provenance
  cryptographically rather than trust the generation flow. Until DE-295
  lands, **document this gap honestly** — do not represent the unsigned
  path as equivalent to a signed enterprise distribution.

### OAuth and token handling

- Auth reuses the deployment's existing JWT issuer over the Office.js
  Dialog API; no third-party IdP, no MSAL. The dialog navigates only to
  `{deployment_origin}/lq-ai/word-addin/oauth-start`, same origin as the
  pane.
- Tokens live in `localStorage`, readable by any script running under
  the deployment origin in that browser profile. This is the same
  exposure surface as the web app's own token storage; the add-in does
  not weaken it, but it is not document-scoped — a shared Word client +
  browser profile shares the session.
- No add-in-scoped audience claim today — the add-in is the same
  principal as the web app. Endpoint-level revocation of the add-in
  specifically is not possible without the future per-client audience
  DE.
- `messageParent` payloads from the dialog are parsed defensively:
  malformed JSON, unexpected payload types, and dialog-API failures all
  resolve to a typed `error`/`cancelled` outcome rather than throwing.

### Document permissions

The manifest requests `ReadWriteDocument` permission. At v0.3.0 the
task pane **does not exercise it** — there is no feature code reading or
writing the document yet (that is DE-287). The permission is declared
ahead of the feature surface so the manifest doesn't need re-issuing
when DE-287 lands; reviewers should note that the granted permission
currently exceeds what the shipped code uses.

### Version handshake integrity

The installed version is baked into the bundle (`__ADDIN_VERSION__`),
not read from the API, so a tampered handshake response cannot
misrepresent the add-in's own version to bypass the compatibility gate.
The handshake endpoint is unauthenticated by necessity (it runs
pre-sign-in) and returns only non-sensitive version/URL metadata.

---

## Known limitations

The M3 plumbing is install-authenticate-version-check only. The
limitations below are scope boundaries, not bugs.

### Feature surface is deep-link placeholders — by design

Every authenticated tab (chat, skills, playbooks) renders a
`DeepLinkCard` whose copy states the in-Word feature is on the M4 /
community roadmap and links to the equivalent web-app surface. The
Inference Tier badge is an inert placeholder in the header. This is
[DE-287](PRD.md#de-287--word-add-in-feature-surface-chat-skills-playbooks-tier-badge--deferred-to-m4--community-contribution),
not unfinished work — the add-in is intentionally a usable shell over
the web app until the feature work is claimed.

### No signed distribution package

Only the unsigned-manifest sideload path ships and verifies in M3. The
signed `word-addin-v0.3.x.zip` distribution package and the signing CI
are [DE-295](PRD.md#de-295--word-add-in-code-signing-certificate--signed-manifest-ci-community-led),
gated on code-signing certificate procurement.

### `taskpane_bundle_hash` is always null

The handshake field exists and the add-in knows how to consume it, but
M3-B8 ships it `null` (don't-enforce). Populating it from a build
manifest is part of the signing CI work under DE-295. Until then the
add-in cannot detect that Office served a stale-cached bundle.

### XML manifest, not JSON unified manifest

v0.3.0 ships the XML manifest per Phase B Decision B-2 because the JSON
unified manifest was still in preview for Word in early 2026. Migration
to the unified manifest is a deferred follow-on once it reaches GA for
Word.

### `ReadWriteDocument` declared but unused

See [Threat model](#document-permissions) — the permission is declared
ahead of the DE-287 feature surface; no shipped code reads or writes the
document yet.

---

## References

- [PRD §3.9 Word Add-In (M3)](PRD.md#39-word-add-in-m3) — capability spec
- [PRD §9 DE-287](PRD.md#de-287--word-add-in-feature-surface-chat-skills-playbooks-tier-badge--deferred-to-m4--community-contribution) — feature surface deferred to M4 / community
- [PRD §9 DE-295](PRD.md#de-295--word-add-in-code-signing-certificate--signed-manifest-ci-community-led) — signed manifest / distribution package, community-led
- [`api/app/api/word_addin.py`](../api/app/api/word_addin.py) — backend: manifest generation + version handshake
- [`api/app/__init__.py`](../api/app/__init__.py) — `__version__` feeding `deployment_version`
- [`word-addin/manifest.xml`](../word-addin/manifest.xml) — XML manifest template with the four substitution tokens
- [`word-addin/README.md`](../word-addin/README.md) — build + sideload instructions
- [`word-addin/src/taskpane/auth.ts`](../word-addin/src/taskpane/auth.ts) — session storage + refresh coalescing
- [`word-addin/src/taskpane/dialog.ts`](../word-addin/src/taskpane/dialog.ts) — Office.js Dialog API OAuth wrapper
- [`word-addin/src/taskpane/version.ts`](../word-addin/src/taskpane/version.ts) — version handshake client
- [`word-addin/src/taskpane/components/App.tsx`](../word-addin/src/taskpane/components/App.tsx) — three-state root component
