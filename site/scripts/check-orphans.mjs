#!/usr/bin/env node
/**
 * Nothing is orphaned.
 *
 * Every page in the collection has to be reachable from the sidebar. A page
 * that exists but is in no navigation is a page nobody finds except through
 * search, and on a documentation site that is the same as not having written
 * it — the authoring contract promises this, and this is what enforces it.
 *
 * The check reads the sidebar out of one built page rather than re-deriving it
 * from the config. The sidebar is identical on every page (Starlight renders
 * the whole tree and marks the current item), so one page is the whole answer,
 * and reading the built HTML tests what a reader will actually be served rather
 * than what the configuration intended.
 *
 * The entry hub (`/`) is exempt: it is the site title's link in the header, not
 * a sidebar item.
 */

import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

import { DIST_DIR, MANIFEST_PATH, SITE_BASE, withBase } from './lib/paths.mjs';

/** Starlight's sidebar landmark. */
const SIDEBAR_START = /<nav\b[^>]*aria-label\s*=\s*["']Main["'][^>]*>/i;

function sidebarLinks(html) {
  const start = SIDEBAR_START.exec(html);
  if (!start) return undefined;
  const from = start.index + start[0].length;
  const end = html.indexOf('</nav>', from);
  const markup = html.slice(from, end === -1 ? undefined : end);

  const links = new Set();
  for (const match of markup.matchAll(/href\s*=\s*(?:"([^"]*)"|'([^']*)')/gi)) {
    const href = (match[1] ?? match[2] ?? '').split('#')[0].split('?')[0];
    if (href.startsWith(SITE_BASE)) links.add(href);
  }
  return links;
}

function main() {
  if (!existsSync(MANIFEST_PATH)) {
    console.error('check:orphans: no .sync-manifest.json — run `npm run build` first.');
    process.exitCode = 1;
    return;
  }

  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const pages = (manifest.pages ?? []).filter((page) => page.route !== '');

  if (pages.length === 0) {
    console.log('check:orphans: no pages to check.');
    return;
  }

  // Any built page carries the whole sidebar; take the first one that exists.
  let html;
  let source;
  for (const page of pages) {
    const file = path.join(DIST_DIR, page.route, 'index.html');
    if (existsSync(file)) {
      html = readFileSync(file, 'utf8');
      source = page.route;
      break;
    }
  }

  if (!html) {
    console.error(`check:orphans: none of the ${pages.length} manifest routes was built.`);
    process.exitCode = 1;
    return;
  }

  const links = sidebarLinks(html);
  if (!links) {
    console.error(
      `check:orphans: could not find the sidebar in dist/${source}/index.html — the check cannot ` +
        'prove anything, so it fails rather than passing silently. Starlight may have changed the ' +
        'nav landmark this script looks for.'
    );
    process.exitCode = 1;
    return;
  }

  const orphans = pages.filter((page) => !links.has(withBase(page.route)));

  if (orphans.length) {
    console.error(`check:orphans: ${orphans.length} page(s) are not reachable from the sidebar.`);
    for (const page of orphans) {
      console.error(`  ${withBase(page.route)} — ${page.page ?? page.kind}`);
    }
    process.exitCode = 1;
    return;
  }

  console.log(
    `check:orphans: all ${pages.length} page(s) appear in the sidebar (read from dist/${source}/index.html; ${links.size} sidebar link(s)).`
  );
}

main();
