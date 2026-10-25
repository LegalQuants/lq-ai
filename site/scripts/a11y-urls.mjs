#!/usr/bin/env node
/**
 * Print one `http://localhost:<port><base><route>` URL per built page.
 *
 * pa11y-ci can be pointed at a sitemap, but the sitemap carries the *deployed*
 * origin (`SITE_URL`), and the gate runs against `astro preview` on localhost.
 * Reading `dist/**\/index.html` instead means the URL list is exactly the routes
 * that were built, under whatever base this build used — so the gate keeps
 * working when the site moves to a custom domain.
 *
 *   node scripts/a11y-urls.mjs [--port 4321]
 */

import { existsSync } from 'node:fs';
import { readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SITE_ROOT = fileURLToPath(new URL('..', import.meta.url));
const DIST = path.join(SITE_ROOT, 'dist');

const argv = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = argv.indexOf(`--${name}`);
  return i === -1 ? fallback : argv[i + 1];
};

const port = flag('port', process.env.PORT || '4321');
// The base path is set once, in astro.config.mjs. Reading it back from there
// (rather than restating the default) means this gate follows the site when the
// base changes, and keeps the literal out of `src/`.
const { default: astroConfig } = await import('../astro.config.mjs');
const base = astroConfig.base ?? '/';
const origin = `http://localhost:${port}`;

/** Every directory under dist/ that contains an index.html, as a route. */
async function routes(dir = DIST, prefix = '') {
  if (!existsSync(dir)) return [];
  const found = [];
  const entries = await readdir(dir, { withFileTypes: true });
  if (entries.some((e) => e.isFile() && e.name === 'index.html')) {
    found.push(prefix);
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    // Astro's client assets; no HTML pages live under here.
    if (!prefix && entry.name === '_astro') continue;
    found.push(...(await routes(path.join(dir, entry.name), `${prefix}${entry.name}/`)));
  }
  return found;
}

const prefix = base.endsWith('/') ? base : `${base}/`;
const list = (await routes()).sort();

// The 404 page is a bare file, not a directory with an index.html, so the walk
// above never finds it — and it renders the same chrome every other page does.
// `astro preview` serves it at its own path, which is enough for the gate.
if (existsSync(path.join(DIST, '404.html'))) list.push('404.html');

if (list.length === 0) {
  console.error('a11y-urls: dist/ holds no pages. Run `npm run build` first.');
  process.exit(1);
}

for (const route of list) {
  console.log(`${origin}${prefix}${route}`);
}
