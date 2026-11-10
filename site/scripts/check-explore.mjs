#!/usr/bin/env node
/**
 * check:explore — Version C's Explore and guide-page contracts, read from the
 * built site in `dist/` (no browser; `check:e2e` drives the behaviour).
 *
 *   1. No page shows a "draft" chip: only a reviewed page carries a status chip
 *      (StatusBadge.astro).
 *   2. Every page's top bar has the Explore button, pointing at Explore, so the
 *      way back survives the sidebar folding behind the menu.
 *   3. Every footer stamp names the release it describes, when the clone has
 *      release tags (`releaseOf` in scripts/lib/git.mjs).
 *   4. `_guides/index.json` (Explore's sidebar) points only at built pages and
 *      at anchors those pages have — never "undefined".
 *   5. Explore is one conversation: the introduction's questions, then "Where
 *      do I go from here?", then the (empty) place searches are appended.
 *   6. A guide page's right column reads About this page, On this page, …,
 *      Text copies, in that order.
 *
 * Runs on the default build (C). Exits 1 with every failure listed.
 */
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { load } from 'cheerio';
import { DIST_DIR, REPO_ROOT, SITE_BASE, SITE_LAYOUT } from './lib/paths.mjs';

const failures = [];
const fail = (where, message) => failures.push(`  ${where}: ${message}`);

if (SITE_LAYOUT !== 'pathways') {
  console.log('check:explore: not the pathways layout; nothing to check.');
  process.exit(0);
}
if (!existsSync(path.join(DIST_DIR, 'index.html'))) {
  console.error('check:explore: dist/ has no build. Run `npm run build` first.');
  process.exit(1);
}

function htmlFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name.startsWith('_') || entry.name === 'pagefind' ? [] : htmlFiles(full);
    return entry.name === 'index.html' ? [full] : [];
  });
}

const routeOf = (file) => path.relative(DIST_DIR, path.dirname(file)).split(path.sep).join('/');
const pages = new Map(htmlFiles(DIST_DIR).map((file) => [routeOf(file), load(readFileSync(file, 'utf8'))]));

let hasTags = false;
try {
  hasTags = execFileSync('git', ['tag', '--list', 'v*', '--merged', 'HEAD'], { cwd: REPO_ROOT, encoding: 'utf8' }).trim() !== '';
} catch { /* no git: the release check is skipped */ }

const NAV = (route) => route === '' || route === 'all' || route.startsWith('pathways/');

for (const [route, $] of pages) {
  const where = `/${route}`;
  // 1. No draft chip.
  if ($('.lq-status--draft').length) fail(where, 'shows a "draft" status chip');
  // 2. The Explore button.
  const explore = $('.lq-pw-actions a[aria-label="Explore"]');
  if (explore.length !== 1) fail(where, 'has no Explore button in the top bar');
  else if (explore.attr('href') !== SITE_BASE) fail(where, `Explore button points at ${explore.attr('href')}`);
  if (route === '' && explore.attr('aria-current') !== 'page') fail(where, 'Explore button is not marked current on Explore');
  // 3. The release beside every footer stamp.
  if (hasTags && $('.lq-footer .lq-stamp__line').length && !$('.lq-footer .lq-stamp__release').text().trim()) {
    fail(where, 'footer stamp names no release');
  }
  // 6. The guide page's right column.
  if (!NAV(route) && $('html').is('[data-has-toc]')) {
    const panel = $('.right-sidebar-panel').html() ?? '';
    const at = (marker) => panel.indexOf(marker);
    const order = [['About this page', at('lq-facts--about')], ['On this page', at('starlight__on-this-page')], ['Text copies', at('lq-facts-text')]];
    for (const [name, index] of order) if (index === -1) fail(where, `right column has no "${name}"`);
    const found = order.map(([, index]) => index).filter((index) => index !== -1);
    if (found.some((index, i) => i > 0 && index < found[i - 1])) fail(where, 'right column panels are out of order');
  }
}

// 4. Explore's sidebar data.
const indexPath = path.join(DIST_DIR, '_guides', 'index.json');
if (!existsSync(indexPath)) fail('_guides/index.json', 'missing');
else {
  const index = JSON.parse(readFileSync(indexPath, 'utf8'));
  if (index.base !== SITE_BASE) fail('_guides/index.json', `base is ${index.base}, the build's is ${SITE_BASE}`);
  for (const [route, entry] of Object.entries(index.pages)) {
    const where = `_guides ${route}`;
    if (JSON.stringify(entry).includes('undefined')) fail(where, 'contains "undefined"');
    if (entry.url !== `${SITE_BASE}${route}/`) { fail(where, `url ${entry.url} is not ${SITE_BASE}${route}/`); continue; }
    const $ = pages.get(route);
    if (!$) { fail(where, 'points at a page that was not built'); continue; }
    for (const section of entry.sections) if (!$(`[id="${section.id}"]`).length) fail(where, `section #${section.id} is not on the page`);
  }
}

// 5. Explore is one conversation.
const $explore = pages.get('');
if ($explore) {
  const asks = $explore('.lq-explore .lq-answer > h2.lq-ask').map((_i, el) => $explore(el).text().trim()).get();
  if (asks.length !== 4) fail('/', `expected three introductory questions and "Where do I go from here?", found ${asks.length} question(s)`);
  else if (asks[3] !== 'Where do I go from here?') fail('/', `the fourth question is "${asks[3]}"`);
  const html = $explore('.lq-explore').html() ?? '';
  const readNext = html.indexOf('lq-read-next');
  const conversation = html.indexOf('data-lq-search-history');
  if (readNext === -1 || conversation === -1 || conversation < readNext) fail('/', 'searches are not appended after "Where do I go from here?"');
  if ($explore('h2').filter((_i, el) => $explore(el).text().trim() === 'Search documentation').length) fail('/', 'still has a "Search documentation" heading');
}

if (failures.length) {
  console.error(`check:explore: ${failures.length} problem(s):\n${failures.join('\n')}`);
  process.exit(1);
}
console.log(`check:explore: ${pages.size} page(s), the guide index and Explore's conversation all hold${hasTags ? '' : ' (no release tags: release check skipped)'}.`);
