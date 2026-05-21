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
| `src/taskpane/` | React 18 + TypeScript task pane shell. `taskpane.html` is the page Office loads; `taskpane.tsx` is the React entry point; `components/` holds the header, tab strip, and deep-link card. |
| `src/commands/` | Office.js ribbon command surface (no commands wired in M3-B1; feature work lands here). |
| `assets/` | Manifest icons (placeholders for v0.3.0; design pass before v0.3.0 final). |
| `webpack.config.js` | Bundles to `dist/`. Per [Decision B-1](../docs/superpowers/plans/2026-05-21-m3-phase-b-word-addin-plumbing.md), webpack is the bundler of record. |

---

## Prerequisites

- **Node 18+** (the project pins this in `package.json` engines).
- For local Word-desktop testing: a Word for Microsoft 365 client (macOS or Windows) and the `office-addin-debugging` toolchain (installed automatically via the `devDependencies` of this package).

---

## Build

```bash
cd word-addin
npm install
npm run build           # production build → dist/
npm run build:dev       # dev build with source maps
npm run watch           # rebuild on every change
```

The build output is `word-addin/dist/`. Until M3-B8 ships the deployment-served bundle endpoint, deploy by copying `dist/` to the operator's `web/static/word-addin/` directory (or via the `docker-compose.yml` volume mount documented in the root `docker-compose.yml` `web` service).

## Validate the manifest

```bash
npm run validate
```

Runs `office-addin-manifest validate manifest.xml`. The CI workflow at `.github/workflows/word-addin-ci.yml` (added when M3-B7 lands) runs the same check on every PR.

## Run inside Word for local testing

```bash
npm run start
```

`office-addin-debugging start manifest.xml` opens Word with the add-in sideloaded against a local dev server at `https://localhost:3001`. Useful for component-level UI iteration without going through the deployment's static-file serving path.

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
