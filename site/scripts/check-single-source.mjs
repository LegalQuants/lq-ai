#!/usr/bin/env node
/**
 * One source of truth per page (ADR 0028 decision 3).
 *
 * `docs/site/` is navigation and generated-page companions — never a second
 * copy of a page's content. This gate enforces both halves of that:
 *
 *  - Every `.md`/`.mdx` file under `docs/site/` is one of: the entry hub
 *    (`index.mdx`), a namespace or nested hub ("index.md" or "index.mdx" in
 *    any directory), `start/choose-your-path.md`, or a generated page's
 *    ".intro.md" companion. `README.md`, `_data/` and `routes/` are not pages
 *    and are not checked here. Anything else is content that belongs at its
 *    canonical repository path, reached through a `docs/site/routes/` YAML
 *    entry, not through a docs/site wrapper.
 *  - No route manifest's `source:` may itself sit under `docs/site/` — that
 *    would be the same fork the first half refuses, just pointed at from the
 *    other direction.
 *
 * `npm run sync` already refuses a broken or overlapping manifest at build
 * time; this gate exists so the rule is checkable on its own, fast, without a
 * full sync, and so CI fails with one clear reason rather than a sync log to
 * read through.
 */

import { existsSync, readdirSync } from 'node:fs';
import path from 'node:path';

import { DOCS_SITE_DIR } from './lib/paths.mjs';
import { loadRouteManifests, ROUTES_DIRNAME } from './lib/routes.mjs';

const NOT_A_PAGE_DIRS = new Set(['_data', ROUTES_DIRNAME]);

/** Namespace/nested hubs, `*.intro.md` companions, and the one named exception. */
function isAllowed(relPath) {
  const base = path.basename(relPath);
  if (base === 'index.md' || base === 'index.mdx') return true;
  if (base.endsWith('.intro.md')) return true;
  if (relPath === 'start/choose-your-path.md') return true;
  return false;
}

function pageFiles(dir, prefix = '') {
  if (!existsSync(dir)) return [];
  const found = [];
  for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) =>
    a.name.localeCompare(b.name)
  )) {
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      if (!prefix && NOT_A_PAGE_DIRS.has(entry.name)) continue;
      found.push(...pageFiles(path.join(dir, entry.name), rel));
    } else if (/\.mdx?$/.test(entry.name) && entry.name !== 'README.md') {
      found.push(rel);
    }
  }
  return found;
}

function main() {
  const offenders = pageFiles(DOCS_SITE_DIR).filter((rel) => !isAllowed(rel));

  const manifestProblems = [];
  loadRouteManifests({
    routesDir: path.join(DOCS_SITE_DIR, ROUTES_DIRNAME),
    report: (problem) => manifestProblems.push(problem),
  });
  const errors = manifestProblems.filter((problem) => problem.level === 'error');

  if (offenders.length === 0 && errors.length === 0) {
    console.log('check:single-source: docs/site/ holds only navigation and generated-page companions.');
    return;
  }

  if (offenders.length) {
    console.error(
      `check:single-source: ${offenders.length} page(s) under docs/site/ are not a hub, ` +
        '"start/choose-your-path.md", or a generated page\'s ".intro.md" companion. Move the ' +
        'content to its canonical repository location and map it with a docs/site/routes/*.yaml entry.'
    );
    for (const rel of offenders) console.error(`  docs/site/${rel}`);
  }

  if (errors.length) {
    console.error(`check:single-source: ${errors.length} route-manifest problem(s):`);
    for (const problem of errors) {
      console.error(`  ${problem.page}:${problem.line} — ${problem.message}`);
    }
  }

  process.exitCode = 1;
}

main();
