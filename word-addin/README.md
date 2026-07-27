# LQ.AI Word add-in

> **M3-B1 scope:** scaffold only. The task pane loads, the tab strip renders, and each tab shows a deep-link card pointing at the equivalent LQ.AI web app surface (per [Phase B prep doc](../docs/superpowers/plans/2026-05-21-m3-phase-b-word-addin-plumbing.md) Decision B-4). The feature surfaces inside each tab (chat, skills, playbook execution, Inference Tier badge) are descoped to M4 / community contribution per [PRD §9 DE-287](../docs/PRD.md#de-287--word-add-in-feature-surface-chat-skills-playbooks-tier-badge--deferred-to-m4--community-contribution).
>
> **Status at v0.3.0:** the add-in is installable + authenticated against a self-hosted LQ.AI deployment (OAuth lands in M3-B2; signed manifest lands in M3-B7).

---

## What this directory is

Office.js task pane add-in for Microsoft Word. The manifest, task pane JS bundle, and admin-side installation UI ship as part of v0.3.0 (M3 Phase B plumbing); the inside-the-tab feature work ships under DE-287.

| File | What it is |
|---|---|
| `manifest.xml` | Office Add-in XML manifest 1.1+ template. Tokens like `{{ DEPLOYMENT_ORIGIN }}` are substituted by the LQ.AI admin UI's "Generate manifest" flow before an operator sideloads via Microsoft 365 Admin Center. |
| `taskpane.html` / `commands.html` | Vite's multi-page entry HTML, at the project root (standard Vite convention). Office loads these directly. |
| `src/taskpane/` | React + TypeScript task pane shell. `taskpane.tsx` is the React entry point; `components/` holds the header, tab strip, and chat/skills surfaces. |
| `src/commands/` | Office.js ribbon command surface (no commands wired in M3-B1; feature work lands here). |
| `assets/` | Manifest icons (placeholders for v0.3.0; design pass before v0.3.0 final). |
| `vite.config.ts` | Bundles straight to `../web/static/word-addin/`. Per [ADR 0022](../docs/adr/0022-word-addin-vite-over-webpack.md), Vite is the bundler of record (supersedes the original webpack decision — see the ADR for why). |

---

## Prerequisites

- **Node 18+** (the project pins this in `package.json` engines).
- For local Word-desktop testing: a Word for Microsoft 365 client (macOS or Windows) and the `office-addin-debugging` toolchain (installed automatically via the `devDependencies` of this package).

---

## Build

```bash
cd word-addin
npm install
npm run build           # production build
npm run build:dev       # dev-mode build with source maps
npm run watch           # rebuild on every change
```

The build output goes straight to `web/static/word-addin/` (not a local `dist/`) — the existing `web` container's `COPY . .` picks it up automatically, no manual copy step or volume mount needed.

## Validate the manifest

```bash
npm run validate
```

Runs `office-addin-manifest validate manifest.xml`. The CI workflow at `.github/workflows/word-addin-ci.yml` (added when M3-B7 lands) runs the same check on every PR.

## Local development

The manifest checked into this directory is a **template** — `{{ DEPLOYMENT_ORIGIN }}` and friends are only substituted by the admin UI's "Generate manifest" flow (`GET /api/v1/admin/word-addin/manifest`), which requires a running, authenticated LQ.AI deployment. For local iteration you don't want that dependency, so there's a separate dev path:

1. **Trust a local HTTPS cert.** Office Add-ins require the task pane to be served over HTTPS even in dev — Word's embedded browser enforces it, no exceptions. One-time per machine:
   ```bash
   npx office-addin-dev-certs install
   ```
   This generates and trusts a cert for `localhost`, matching the `server` block in `vite.config.ts` (port 3001, `https` set from this same cert).

2. **Generate a dev manifest pointed at `localhost`, not a real deployment:**
   ```bash
   npm run manifest:dev
   ```
   Writes `manifest.dev.xml` (gitignored — never commit a manifest with a live deployment origin). Uses the same 4-token substitution as the backend's `render_manifest()` (`api/app/api/word_addin.py`), pointed at `https://localhost:3001`.

3. **Build and serve the bundle:**
   ```bash
   npm run watch          # rebuild on change, or:
   npm run dev-server      # Vite dev server on https://localhost:3001/word-addin/
   ```
   `dev-server` proxies `/api` through to `http://localhost:8000` (the `api`
   container's default host port — set `LQ_AI_DEV_API_ORIGIN` if yours maps
   elsewhere) so `auth.ts`'s `deploymentOrigin()` — which resolves to
   `window.location.origin`, i.e. this dev server — still reaches a real
   backend for login/refresh/version-check instead of 404ing against
   the dev server itself. Bring up at least `postgres`, `redis`, and
   `api` from the repo-root `docker-compose.yml` first.

4. **Sideload into Word:**
   ```bash
   npm run start:dev
   ```
   Runs `manifest:dev` then `office-addin-debugging start manifest.dev.xml`. This tool claims macOS support via a `--desktop-platform mac` flag, but sideload automation on Mac has known reliability gaps. **If it doesn't work, use the manual fallback** (always reliable, Microsoft-documented):
   - Finder → `Cmd+Shift+G` → go to `/Users/<you>/Library/Containers/com.microsoft.Word/Data/Documents/wef` (create the `wef` folder if it doesn't exist).
   - Copy `manifest.dev.xml` into that folder.
   - Restart Word, open a document, **Home → Add-ins**, select LQ.AI.

   `npm run stop:dev` un-registers the sideload when you're done (automated path only — the manual path is undone by deleting the file from `wef`).

This path bypasses the deployment's static-file serving, but real login now goes through the proxy to a genuine `api` backend (see step 3) — there's no fake/bypassed session. To test against the fully-dockerized stack instead (built assets served by `web`, no dev server), use the `npm run start` / M365 Admin Center path below against a deployment running the actual `docker-compose.yml` stack.

## Lint + format + typecheck

```bash
npm run lint
npm run format
npm run typecheck
```

---

## Sideload via Microsoft 365 Admin Center (operator path)

1. In LQ.AI admin UI, navigate to **Admin → Word add-in**.
2. Click **Generate manifest**. The page writes the operator's deployment URL + a fresh GUID into the manifest template and downloads `lq-ai-word-addin-manifest.xml`.
3. In Microsoft 365 Admin Center, go to **Settings → Integrated apps → Upload custom apps**, choose **Office Add-in**, and upload the manifest.
4. Assign to the relevant users / groups.
5. Users see "LQ.AI" appear in Word's Home ribbon within a few minutes (Office checks the manifest catalog on Word startup; force-refresh by closing/reopening Word).

M3-B7 will ship the signed distribution package (`word-addin-v0.3.0.zip`) as a GitHub Release asset alongside the v0.3.0 tag, with code-signing per the Phase B prep doc Decision B-5.

---

## Roadmap inside this directory

Every line item below is a roadmap commitment, not a maintainer-team work item. Community contributors are welcome to claim any of them via a tracking issue.

| Surface | Tracked at | Status |
|---|---|---|
| Chat tab against the open document | DE-287 (M3-B3) | Deep-link card placeholder today |
| Skills tab with tracked-changes + comments | DE-287 (M3-B4) | Deep-link card placeholder today |
| Playbooks tab with per-position rendering | DE-287 (M3-B5) | Deep-link card placeholder today |
| Inference Tier badge in the header | DE-287 (M3-B6) | Inert placeholder in the header today |
| OAuth (Office.js Dialog API) | M3-B2 plumbing | Lands with the next Phase B PR |
| Signed manifest + distribution package | M3-B7 plumbing | Lands when the code-signing cert arrives |
| Version handshake + bundle endpoint | M3-B8 plumbing | Lands with the next Phase B PR |
| Unified JSON manifest migration | DE follow-on | Pending JSON manifest GA for Word |

See [PRD §3.9 Word Add-In (M3)](../docs/PRD.md#39-word-add-in-m3) and [PRD §9 DE-287](../docs/PRD.md#de-287--word-add-in-feature-surface-chat-skills-playbooks-tier-badge--deferred-to-m4--community-contribution) for the full design surface.
