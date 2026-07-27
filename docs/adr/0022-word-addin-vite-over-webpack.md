# ADR 0022 — Word add-in bundler: Vite instead of webpack

**Status:** Accepted (2026-07-15) — maintainer-directed change, implemented same-day.
**Decision-makers:** Simon Booth (maintainer)
**Affected components:** `word-addin/` (build tooling only — no application-code behavior change)
**Related:** [Phase B Decision B-1 (2026-05-21 prep doc)](../superpowers/plans/2026-05-21-m3-phase-b-word-addin-plumbing.md) — this ADR supersedes that decision; `web/`'s own `vite.config.ts` (SvelteKit's Vite setup, unaffected but now the sibling precedent this ADR aligns with)

---

## Context

The Word add-in's build tooling was originally set on webpack per Phase B Decision B-1: "webpack is the bundler of record — matches Office Add-in CLI's default toolchain and the documentation Microsoft ships for new add-in projects." That reasoning holds on its own terms — Microsoft's `yo office` generator and official samples default to webpack, and `office-addin-debugging`/`office-addin-dev-certs`/manifest sideloading were historically validated against that shape.

Two things changed the calculus:

1. **`web/` (the SvelteKit shell) already runs on Vite** (`web/package.json`'s `vite@^5.4.21` — SvelteKit's own dev server and build are Vite under the hood). `word-addin/` was the only webpack holdout in the repo's two frontend surfaces.
2. The add-in is under active, fast-moving iteration right now (skills/chat state layer, dev-sideload proxy, etc.) — webpack's `ts-loader`-per-file transpilation is the slower half of that dev loop compared to Vite/esbuild.

Vite has no technical blocker for Office Add-ins: `server.https` accepts the same `{key, cert}` shape `office-addin-dev-certs` already returns (drop-in with webpack-dev-server's identical use of that shape), and multi-page builds (`taskpane.html` + `commands.html`, two independent Office.js entry surfaces) are a standard, documented Vite pattern via `build.rollupOptions.input`.

## Decision

Replace `webpack.config.js` with `vite.config.ts`, one-for-one on every webpack feature this project actually uses:

| Webpack feature | Vite equivalent |
|---|---|
| `entry: {taskpane, commands}` + `HtmlWebpackPlugin` × 2 | `build.rollupOptions.input` pointing at root-level `taskpane.html`/`commands.html` (moved from `src/taskpane/`, `src/commands/` — standard Vite multi-page shape; script tags reference their TS entries directly, no template injection needed) |
| `output.path` / `publicPath` (→ `web/static/word-addin/`) | `build.outDir` + `base: "/word-addin/"` |
| `ts-loader` | `@vitejs/plugin-react` (esbuild-based transform; new dependency — the standard Vite React plugin, no substitute avoids it) |
| `webpack.DefinePlugin` (`__ADDIN_VERSION__`) | Vite's `define` config option |
| `CopyWebpackPlugin` (`manifest.xml`, `assets/`) | A ~10-line inline Vite plugin (`closeBundle` hook, plain `fs.copyFileSync`/`fs.cpSync`) — avoids adding `vite-plugin-static-copy` as a dependency for two file-copy calls |
| `devServer` (port, HTTPS via `office-addin-dev-certs`, CORS header, `/api` proxy) | Vite's `server` config — same shape, same cert source, same proxy target |

No application code changes. `tsconfig.json` is unaffected (`moduleResolution: "Bundler"` already Vite-compatible). Tests (`vitest`) are untouched — they never depended on webpack.

## Consequences

### Positive
- One bundler across the repo's two frontend surfaces (`web/`, `word-addin/`) instead of two.
- Faster dev-server rebuilds during active iteration (esbuild transform vs. `ts-loader`).
- Fewer devDependencies overall: drops `webpack`, `webpack-cli`, `webpack-dev-server`, `ts-loader`, `html-webpack-plugin`, `copy-webpack-plugin`, `html-loader`, `css-loader`, `style-loader`, `source-map-loader` (10 packages) for `vite` + `@vitejs/plugin-react` (2 packages).

### Negative
- Less community prior art for Vite + Office Add-ins specifically than webpack (Microsoft's own samples/generator still default to webpack) — if a genuinely Office-Add-in-specific bundler quirk surfaces, we're debugging it without a documented precedent to lean on.
- `taskpane.html`/`commands.html` moved from `src/taskpane/`/`src/commands/` to the project root — a one-time structural move (standard Vite convention, not a workaround).

### Neutral
- `office-addin-debugging`, `office-addin-manifest`, and the manifest-templating flow (`api/app/api/word_addin.py`) are all bundler-agnostic — none of them reference webpack, so none of them change.

## Companion artifacts

- `word-addin/vite.config.ts` — replaces `webpack.config.js` (deleted).
- `word-addin/taskpane.html`, `word-addin/commands.html` — moved from `src/taskpane/`, `src/commands/`.
- `word-addin/package.json` — scripts (`build`, `build:dev`, `watch`, `dev-server`) now invoke `vite`; dependency swap per the table above.
- `word-addin/README.md` — dev-server instructions updated (`vite dev` in place of `webpack serve`); the underlying proxy-to-`api` and HTTPS-cert setup are unchanged.

## Alternatives considered

### Keep webpack
Rejected: no longer buys anything not already covered by Vite, and leaves `word-addin/` as the repo's only webpack surface for no functional reason once the toolchain-consistency and dev-speed points are on the table.

### `vite-plugin-static-copy` for manifest/assets copying
Rejected in favor of a ~10-line inline plugin: the copy need is two `fs` calls (one file, one directory), not worth a new dependency per this repo's "don't add libraries without justification" convention.
