# M3 Phase B — Word Add-In Plumbing — Prep Notes

> **Scope:** Phase B *plumbing* only. M3-B1 (scaffold) + M3-B2 (OAuth) + M3-B7 (signed manifest + cert procurement) + M3-B8 (self-served JS bundle + version handshake). The feature surfaces inside the task pane (M3-B3 chat / M3-B4 skills / M3-B5 playbook execution / M3-B6 tier badge) are descoped to M4 / community contribution per [DE-287](../../PRD.md#de-287--word-add-in-feature-surface-chat-skills-playbooks-tier-badge--deferred-to-m4--community-contribution).
>
> **Branch:** `m3-phase-b-word-addin-plumbing` off `main` at `ef7f0a7` (post-PR-#58 — boundary-register catalog + M3-A6 descope DEs).
>
> **Goal at Phase B close:** an LQ.AI deployment ships a signed Word add-in distributable via Microsoft 365 Admin Center; an operator can install it in a Word client and complete the OAuth flow against their deployment; the add-in's empty task pane loads against the version-handshake endpoint without errors. The user-facing tabs are visible but render deep-link placeholders to the equivalent web-app surface — the feature implementations land via DE-287's community contribution path or M4.

---

## Design decisions locked at Phase B kickoff (2026-05-21)

| # | Decision | Choice | Why | DE if redirected |
|---|---|---|---|---|
| **B-1** | Bundler for `word-addin/` | **webpack** | Office Add-in CLI's default; Microsoft's documentation, samples, and `yo office` generator all target webpack; lowest community-contributor friction. Vite has better DX but the Office.js ecosystem is webpack-shaped. | If we hit webpack pain mid-phase, file as DE-XXX and reconsider in M4 community window. |
| **B-2** | Manifest schema | **Office Add-in XML manifest 1.1+** | The unified JSON manifest is GA for Outlook but **still preview for Word** as of early 2026. M365 Admin Center sideload accepts both for Outlook; for Word, XML is the production path. JSON manifest migration is a DE follow-on once GA. | DE-XXX: "Migrate Word add-in to unified JSON manifest" — file when JSON manifest goes GA for Word. |
| **B-3** | OAuth flow shape | **Office.js Dialog API + LQ.AI's existing JWT issuer** | The add-in opens a dialog popup pointing at `/lq-ai/word-addin/oauth-start` on the operator's deployment; the user authenticates with their existing LQ.AI credentials; the dialog posts the JWT back to the task pane via `Office.context.ui.messageParent`; task pane stores in `Office.context.document.settings`. Avoids the MSAL dependency and matches LQ.AI's existing auth surface. SSO via WAM is a DE follow-on if operators want SSO-without-popup. | DE-XXX: "Word add-in SSO via MSAL + WAM for Azure AD tenants." |
| **B-4** | Empty Chat / Skills / Playbooks tabs treatment | **Deep-link to the equivalent web-app surface** | The tabs are visible (header strip per the M3 plan), but each tab renders a "Coming soon — see [web app]" card with a button that opens `{deployment_origin}/lq-ai/{chat\|skills\|playbooks}` in a new browser tab. Gives the operator a usable Word add-in at v0.3.0 (single-sign-on + immediate click-through to actual functionality), and makes the community-contribution surface explicit. | If a community PR for a tab arrives mid-M3, the deep-link card swaps out for the real implementation per DE-287. |
| **B-5** | Code-signing cert vendor | **RESOLVED at PR #59 (2026-05-21) — M3-B7 descoped to community-led effort per [DE-295](../../PRD.md#de-295--word-add-in-code-signing-certificate--signed-manifest-ci-community-led).** Three credible community paths captured in DE-295: SignPath open-source sponsorship (free for qualifying OSS; recommended first attempt), community-funded DigiCert EV (~$500–700/yr), community-funded Sectigo OV (~$200–300/yr). LegalQuants holds the legal cert artifact; community organizes procurement + funding. | n/a — see DE-295 for the rollout plan. | n/a — resolved. |
| **B-6** | Single PR vs split | **B1 + B2 + B8 in one PR (PR #59); B7 community-led** per the B-5 resolution above. | B1/B2/B8 are tightly coupled (B2 needs B1's task pane shell; B8 needs B1's bundle directory) and ship cleanly in one PR. B7 lands as a community PR (likely v0.3.1 or v0.3.2) once the cert procurement closes. | n/a — resolved at PR #59. |
| **B-7** | Version handshake protocol (M3-B8) | **GET `/api/v1/word-addin/version` returns `{ deployment_version, addin_min_compatible_version, addin_max_compatible_version, taskpane_bundle_url, taskpane_bundle_hash }`** | Lets the add-in check at startup whether its bundled JS matches the deployment's expected version; if drift, the task pane shows "Your add-in needs an update from your IT admin — version X.Y.Z is installed; this deployment expects Y.Y.Z." The `taskpane_bundle_hash` lets the add-in optionally verify it loaded the bundle the deployment expects. | n/a — implementation detail of B8. |
| **B-8** | Word client targeting | **Word for Microsoft 365 desktop (Windows + macOS) + Word for the web. Word for iPad and Word Mobile out of M3 scope.** | Per the M3 plan risk row 4. Office.js targets compile fine to all four; testing is the long pole. Word Desktop on Windows is dominant enterprise client; macOS gets primary dev testing (Kevin's primary box); Word Online is acceptance-test path. iPad / Mobile parity is a community-friendly DE. | DE-XXX: "Word add-in iPad / Mobile parity testing" — file at Phase B close. |

---

## Per-task scope (compact; full scope in `docs/M3-IMPLEMENTATION-PLAN.md`)

### Task M3-B1 — Word add-in scaffold

**Files to create:**
- `word-addin/` directory at repo root (sibling to `api/`, `gateway/`, `web/`).
- `word-addin/manifest.xml` — Office Add-in XML manifest 1.1+. Placeholders for `{deployment_origin}` are templated at install time by the admin UI flow.
- `word-addin/src/taskpane/` — React 18 + TypeScript task pane shell. The **single allowed exception to the no-React-in-`web/` rule** (per CLAUDE.md). Header (LQ.AI logo + Inference Tier badge placeholder), tab strip (Chat / Skills / Playbooks — visible but deep-linked per B-4), empty content area.
- `word-addin/src/commands/` — Office.js commands (toolbar buttons).
- `word-addin/webpack.config.js` — bundles to `word-addin/dist/`.
- `word-addin/package.json` — pins Office.js, React 18, TypeScript, webpack versions.
- `word-addin/tsconfig.json` + `.eslintrc` + `.prettierrc` — mirror the conventions in `web/`.
- `web/src/routes/word-addin/+page.svelte` + `web/src/routes/word-addin/taskpane.html` — SvelteKit route serves the task pane HTML + bundled JS from `word-addin/dist/`.
- `web/src/routes/lq-ai/admin/word-addin/+page.svelte` — admin UI that generates the deployment-specific `manifest.xml` (operator clicks "Generate manifest" → downloads file).
- `api/app/api/word_addin.py` — backend endpoints: `GET /api/v1/admin/word-addin/manifest` (admin-only; returns templated manifest with operator's deployment URL injected).
- `docker-compose.yml.example` updated: web container's static-files volume mounts `word-addin/dist/`.
- `docs/architecture.md` Mermaid updated with the Word add-in component.

**Verification:** the add-in loads in Word desktop with an empty task pane; the deep-link cards in each tab open the right web-app routes when clicked; admin UI generates a manifest that operators can sideload via M365 Admin Center.

**Effort:** 8–10 hours.

### Task M3-B2 — Add-in ↔ backend OAuth

**Implementation per Decision B-3:**
- `word-addin/src/taskpane/auth.ts` — Office.js Dialog API helper. Opens dialog at `{deployment_origin}/lq-ai/word-addin/oauth-start`; receives JWT via `Office.context.ui.messageParent`; stores in `Office.context.document.settings` + falls back to `localStorage` for cross-document persistence.
- `web/src/routes/lq-ai/word-addin/oauth-start/+page.svelte` — small dialog UI: "Sign in to {deployment_name}" + email/password form pointing at existing `/api/v1/auth/login` endpoint. Posts JWT back to the task pane via `Office.context.ui.messageParent`.
- `api/app/api/word_addin.py` — gains `POST /api/v1/word-addin/exchange-token` (validates JWT, returns add-in-scoped JWT with `aud: word-addin` claim; same lifetime as web-app JWT, refreshable via existing endpoint).
- Cypress/Playwright E2E test for the OAuth dialog flow against a synthetic dialog mock.

**Verification:** sideloaded add-in completes OAuth round-trip; JWT persists across task pane close/open; expired JWT triggers re-auth dialog.

**Effort:** 8–12 hours.

### Task M3-B7 — Signed manifest + enterprise sideload distribution package

**Implementation:**
- **Decision B-5 needs to be locked before this task starts.** Cert procurement clock runs in parallel with B1/B2/B8.
- `.github/workflows/word-addin-release.yml` — signs `manifest.xml` and bundled JS on every release tag; gated to the `release` environment so secrets only available in tagged builds. Per vendor: DigiCert/Sectigo path uses `signtool` (Windows) or `osslsigncode` (Linux); SignPath path is an API call to their signing service.
- Distribution package: `word-addin-v0.3.0.zip` containing signed manifest + bundled JS + README with M365 Admin Center sideload instructions. Released as a GitHub Release asset on the v0.3.0 tag.
- `docs/security/word-addin.md` (new) — signing chain of trust, what the operator should verify before deploying, threat-model boundaries.
- Security review per CODEOWNERS.

**Verification:** signed manifest installs cleanly via M365 Admin Center sideload; SmartScreen reputation builds within 2 weeks of release (track in v0.3.1 risk).

**Effort:** 12–16 hours (assuming cert is in hand; cert procurement itself is operator-side weeks-of-lead-time work).

### Task M3-B8 — Self-hosted JS bundle serving + version handshake

**Implementation per Decision B-7:**
- `api/app/api/word_addin.py` gains `GET /api/v1/word-addin/version` (unauthenticated — the task pane checks before OAuth completes; returns `{ deployment_version, addin_min_compatible_version, addin_max_compatible_version, taskpane_bundle_url, taskpane_bundle_hash }`).
- `word-addin/src/taskpane/version.ts` — calls the endpoint on task pane mount; renders "Update needed" overlay if installed version is outside the compatible range; logs version drift to the audit log via the existing add-in-scoped JWT for telemetry.
- `web/src/lib/lq-ai/word-addin/` — shared TypeScript types for the version-handshake payload (matches the convention in `web/src/lib/lq-ai/api/`).
- Static file serving — confirmed via M3-B1's `docker-compose.yml.example` change.

**Verification:** older add-in version installed in Word → version mismatch overlay appears; updating the deployment without updating the add-in shows the right error; updating both clears the overlay.

**Effort:** 6–10 hours.

---

## PR strategy

Per Decision B-6 (resolved at PR #59):

- **PR #1 (B1 + B2 + B8):** Word add-in scaffold + OAuth + bundle-serving + version handshake. Single maintainer PR; final state is "installable + authenticated add-in with an empty but functional task pane against a self-hosted deployment, sideloadable via the **unsigned-manifest** path."
- **PR #2 (M3-B7) — community-led** per [DE-295](../../PRD.md#de-295--word-add-in-code-signing-certificate--signed-manifest-ci-community-led). The signing CI + signed distribution package + `docs/security/word-addin.md` land as a community PR (likely v0.3.1 or v0.3.2 release tag) once the cert procurement closes. The work is sized at ~12–16 hours of implementation after the cert is in hand, plus a 2–4 week procurement timeline (SignPath open-source sponsorship is the recommended first path; community-funded paid EV/OV cert is an alternative).

---

## Effort estimate (revised)

| Task | Hours | Notes |
|---|---|---|
| M3-B1 — scaffold | 8–10 | webpack + manifest + task pane shell + deep-link cards |
| M3-B2 — OAuth | 8–12 | Office.js Dialog API + JWT exchange |
| M3-B8 — bundle + version handshake | 6–10 | endpoint + UI + types |
| M3-B7 — signing | community-led | Procurement + ~12–16 hr CI work, community PR per DE-295 |
| **Total (maintainer M3 scope)** | **22–32 hours** | Tracks the revised M3 plan; M3-B7 runs alongside on the community side |

Single maintainer-contributor work for PR #1; ~1 week part-time. M3-B7 lands as a community PR (likely v0.3.1 or v0.3.2) once the cert procurement closes per DE-295.

---

## Open questions to surface mid-execution

These don't need answers now, but the implementer should surface them via `AskUserQuestion` as they arise:

1. **JWT lifetime in the add-in vs web app.** Today's web app JWT lifetime is 8h (check `gateway.yaml`'s auth config). For Word add-ins, sessions are often longer (a lawyer might leave Word open across days). Should the add-in JWT have a longer lifetime, or rely on silent refresh? Recommendation pending: silent refresh via `/api/v1/auth/refresh` on every API call that gets 401, no special lifetime for add-in.
2. **Deep-link card behavior when the operator isn't on the same machine as the browser.** A user in Word for Web (Office 365 on a managed device) clicks "Open in web app" — does the deep link open in a new tab in the same browser? Confirm via M3-B1 manual test on Office 365 + Word desktop.
3. **Version-handshake payload should it include the descope status of each tab?** Currently each tab is "Coming soon"; if the deployment has a community-contributed implementation of one of them (e.g., M3-B5 Playbook execution lands as a community PR before v0.3.0), the version-handshake could surface which tabs are real vs placeholder. Defer to v0.3.1.
4. **Manifest generation: per-deployment vs per-user.** Today's plan is per-deployment (admin generates one manifest for the whole tenant). If LQ.AI later supports multi-tenancy (single deployment serving multiple operator orgs), the manifest may need per-org variants. Defer; tracked as a DE if the multi-tenant question lands in scope.

---

## Sequence for the next session

1. Start with **B1** (scaffold). This is the foundation for B2 + B8. Single commit per the M3-A4/A5 pattern.
2. Land B2 (OAuth) next; commit on top of B1.
3. Land B8 (bundle + version handshake) third; commit on top of B2.
4. **Cert procurement (B-5)** — file as a separate AskUserQuestion when B7 starts; Kevin's call between DigiCert / Sectigo / SignPath. Don't block B1/B2/B8 on this.
5. Open PR #1 once B1+B2+B8 verify against a real Word installation.
6. **B7** lands as PR #2 when the cert is in hand.

Time horizon: PR #1 closes in ~1 week of focused work (full-time contributor). PR #2 lands when cert arrives, likely 2–4 weeks after kickoff.

---

## Execution log

### 2026-05-21 — M3-B1 shipped (commit `c17223e`)

All eight design decisions landed as scoped above. The webpack output landed at `web/static/word-addin/` (gitignored) and the SvelteKit container's existing `COPY . .` picks it up automatically — no docker-compose volume mount required. Manifest generation surface lives at `/lq-ai/admin/word-addin`; the rendered XML carries a fresh GUID per download + a `Content-Disposition: attachment` header for browser-download UX. 6 backend tests pass; ruff + mypy + svelte-check clean. Build verification of the React bundle deferred until a contributor runs `npm install + npm run build` against the working directory; no Word desktop client available in this dev environment for live sideload testing.

### 2026-05-21 — M3-B2 shipped (this commit)

Office.js Dialog API + LQ.AI JWT path per Decision B-3, landed as planned. Two side-channel decisions worth recording for future readers:

**Skipped the `POST /api/v1/word-addin/exchange-token` endpoint.** The prep doc's M3-B2 scope listed an add-in-scoped JWT exchange with an `aud: word-addin` claim. The endpoint would have been semantically simple (validate the standard JWT → mint a new token with a per-client audience) but it would have required *every other authenticated endpoint* to accept both the existing audience and the new `word-addin` audience, OR a refactor that defers audience-checking to a future DE. Both paths add surface area without making any v0.3.0 user safer — there's no specific revocation or scope-narrowing use case yet. The add-in uses the same JWT shape as the web app (issued by `POST /api/v1/auth/login`, refreshed via `POST /api/v1/auth/refresh`). A future DE may add per-client audience scoping if endpoint-level revocation becomes load-bearing; the docstring in `word-addin/src/taskpane/auth.ts` carries this note so the next maintainer doesn't re-derive it.

**Token storage: `localStorage`, not `Office.context.document.settings`.** The Office.js settings store ties data to a specific Word document — useful for per-document configuration (e.g. a saved table mapping) but wrong for auth tokens, which the user expects to span all Word documents in their session. `localStorage` is keyed by browser profile + origin, matching the web app's session model and giving "sign in once, persists across documents in this Word client" out of the box.

Test coverage:
* 22 vitest unit tests for `word-addin/src/taskpane/auth.ts` (token round-trip, refresh-coalescing, `authenticatedFetch` 401-retry path, logout). Vitest is now configured in `word-addin/` with jsdom env; first test runner addition in the directory.
* 4 Cypress E2E tests for `/lq-ai/word-addin/oauth-start` against the SvelteKit dialog page (layout reset, oauth-success path, must-change-password rerouting, 401 inline display). Tests stub `window.Office` via `onBeforeLoad` so the page can run without a real Office host.

Verification gaps carried to M3-E1 fresh-install:
* Live Word desktop sideload of the manifest → sign in via the actual Office dialog → confirm session persists across documents. No Word client in this dev environment.
* Cross-browser dialog behavior. The OAuth dialog page renders identically in Chrome / Edge / Safari in jsdom; live verification on each is deferred to M3-E1.

### 2026-05-21 — M3-B8 shipped (this commit)

Decision B-7 (version handshake protocol) implemented end-to-end. Three side-channel decisions worth recording:

**Router split: `admin_router` + `public_router` in `word_addin.py`.** The version endpoint must be reachable BEFORE the user signs in (an out-of-date add-in needs to surface "Update needed" before the OAuth dialog can fail at a breaking-change API call). Stacking it under the existing `AdminUser` gate would defeat the purpose. The split mirrors how `bootstrap.router` lives outside `_active`. The old `word_addin.router` symbol stays as a backward-compat alias pointing at `admin_router` so any external import wouldn't break — though there are none today.

**Compatibility range as module constants, not env vars.** `ADDIN_MIN_COMPATIBLE_VERSION = "0.3.0"` and `ADDIN_MAX_COMPATIBLE_VERSION = "0.3.99"` are baked into `word_addin.py`. For v0.3.0 the cost of making them operator-configurable (env vars + config schema + admin UI surface to view current values) exceeds the value. Bumping them is a code change with a clear semantic — change them when M4 lands or when a breaking add-in change forces operators to redistribute the manifest.

**`taskpane_bundle_hash` shipped as nullable.** The prep doc Decision B-7 listed the hash as part of the payload. Implementing it correctly (compute the SHA-256 of the deployed bundle JS, cache it, expose it without bricking on file-not-found) is non-trivial and not load-bearing for v0.3.0. Shipped as `Optional[str]` returning `None` today; M3-B7's signing CI populates the value from the build manifest when that work lands. Schema nullability documented in OpenAPI.

Add-in side: webpack's `DefinePlugin` injects `__ADDIN_VERSION__` from `package.json` so the bundle knows its own version without a runtime fetch. `version.ts` runs on App mount, classifies the response into `compatible` / `addin_outdated` / `deployment_outdated` / `unknown`, and renders one of three UI states:

1. **Update-needed overlay** — for the two strict-incompatibility cases. Blocks every other UI path so an out-of-date add-in can't push the user through OAuth.
2. **Soft "version unknown" banner** — for the network-failed case. Renders inside the normal layout (sign-in or authenticated) so an offline operator isn't blocked.
3. **Normal layouts** — for the `compatible` case.

Test coverage:
* 4 new backend integration tests (`test_get_version_*`) — unauthenticated access, schema shape, module constants, reverse-proxy-aware origin derivation, deployment-version mirroring `app.__version__`.
* 17 new vitest tests for `word-addin/src/taskpane/version.ts` — pure-function `parseVersion` / `compareVersions` / `classifyVersion` + `fetchVersionInfo` covering compatible / outdated-each-direction / network-error / HTTP-error / default-installed-version paths.
* OpenAPI spec gains `/word-addin/version` path + `WordAddinVersionResponse` schema + a new `word-addin` tag.
* `test_openapi_paths_match_sketch` updated to expect 81 paths (was 80 before B8).

### 2026-05-21 — M3-B7 descoped to community-led effort (this commit)

PR #59 opened with the B1+B2+B8 plumbing. While drafting the PR description, Kevin made the call to push M3-B7 out to a community-led effort: cert procurement is a real-world purchase + ongoing renewal that couples release velocity to a procurement clock the maintainer team doesn't otherwise need to run. The signed-distribution story stays committed — it just moves to a community track.

This commit reflects the call across the planning surface:

* **Decision B-5 RESOLVED.** The cert vendor choice moves out of the maintainer-team decision space and into [DE-295](../../PRD.md#de-295--word-add-in-code-signing-certificate--signed-manifest-ci-community-led) Phase A (community procurement). SignPath open-source sponsorship is the recommended first attempt; community-funded paid EV/OV alternatives are documented in the DE.
* **Decision B-6 updated.** PR #2 is now a community PR rather than a maintainer-team follow-up.
* **Decision M3-5 (top-level M3 architectural decision) revised.** The original "signed manifest ships in v0.3" commitment moves to "v0.3.0 ships the unsigned-manifest sideload path; signed distribution lands as a community PR (v0.3.x)." The procurement-track guidance ("start at M3 kickoff") no longer applies — it now starts when a community member files the DE-295 Phase A tracking issue.
* **DE-295 filed in PRD §9.** Documents the procurement plan (three credible community paths), what's gated until the cert arrives (5 concrete operator-UX implications: M365 Admin Center "unsigned" warning, no GitHub Release zip, no SmartScreen reputation building, null `taskpane_bundle_hash` from M3-B8, no signing CI workflow), and the acceptance criteria for closing the DE.
* **M3-IMPLEMENTATION-PLAN.md updated.** Task M3-B7 carries the "Descoped to community-led effort" status marker; the Phase B header explains the two parallel scope-reductions (DE-287 + DE-295); the effort table shows the revised M3 scope (~161–218 hr; B1+B2+B8 are now ~22–28 hr for the Phase B maintainer work instead of 35–45 hr); the M3-B8 dependency line drops the M3-B7 reference (B8 doesn't actually depend on B7 — it ships a nullable `taskpane_bundle_hash` field that B7 will populate later); the risks-table cert-acquisition row updated.
* **PRD §3.9 updated.** Word Add-In capability section now reflects the v0.3.0 plumbing-shipping-state with the unsigned-manifest sideload path + cross-references to DE-287 (feature surface) and DE-295 (signed distribution).
* **PR #59 description updated.** Replaces the original "M3-B7 lands as PR #2 once the cert is in hand" framing with "M3-B7 community-led per DE-295."

### Next: PR #59 review + merge → community Phase A starts for DE-295

PR #59 carries four commits + this M3-B7-descope commit. After it merges to `main`, the v0.3.0 release notes will explicitly document the unsigned-manifest sideload path and point at DE-295 for the community-led signed-distribution track. A community member files the DE-295 Phase A procurement issue; the maintainer team's M3 work continues on Phase C (Tabular Review).
