#!/usr/bin/env node
/**
 * Prints every `docs/site/routes/*.yaml` `source:` file, one per line, as a
 * path relative to this script's working directory (`site/`).
 *
 * `check:docs-links` runs `docs/audits/check_doc_links.py` — the same checker
 * that proves a docs/site page's links still work as plain Markdown on
 * GitHub — over a file list built by shell interpolation. A route-manifest
 * source is exactly as much a page as a docs/site file is, so it has to be in
 * that list too; this script is how `package.json` builds that half of it
 * without duplicating the manifest-reading logic in shell.
 *
 * Validation is `npm run sync`'s job, not this script's: a manifest entry
 * that fails a check still has its source listed here, as long as `route` and
 * `source` themselves could be read, so a broken entry's links get checked
 * too rather than silently skipped.
 */

import path from 'node:path';

import { DOCS_SITE_DIR, REPO_ROOT } from './lib/paths.mjs';
import { loadRouteManifests, ROUTES_DIRNAME } from './lib/routes.mjs';

const entries = loadRouteManifests({
  routesDir: path.join(DOCS_SITE_DIR, ROUTES_DIRNAME),
  report: () => {}, // npm run sync is where a manifest problem is reported
});

for (const entry of entries) {
  console.log(path.relative(process.cwd(), path.resolve(REPO_ROOT, entry.source)));
}
