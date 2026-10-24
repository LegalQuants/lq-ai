#!/usr/bin/env node
/**
 * check:rules — the mechanical part of the docs site's launch gate 2: those of
 * Annex A's failure tests (docs/contribute/mini-prds/docsite/
 * annex-a-quality-rules.md) a script can run, on every built page in `dist/`.
 *
 *   Rule 10, "Give every page an onward route": every content page's own text
 *     links to at least one other page of the site.
 *   Rule 11, "Keep one grouping": a page's place in the menu, its breadcrumb,
 *     the All documentation page and `llms.txt` agree — one home, named the
 *     same way everywhere. The address is the second lens Annex B allows
 *     ("no page has two homes"), so it may differ from the pathway; the gate
 *     text says so. `llms.txt`'s goal index ("Find instructions by goal") is
 *     that second lens for agents and isn't a home.
 *   Rule 12, "no assumed tools": every program a page's shell blocks run is
 *     named in the page's text, so the reader knows they need it.
 *
 * The rest of Annex A needs a reader; the gate's other two parts cover it.
 * The pure logic is in scripts/lib/rules.mjs (test/rules.test.mjs). Runs on
 * Version C (the pathways layout with Explore); exits 1 with every failure listed.
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { load } from 'cheerio';
import { DIST_DIR, SITE_BASE, SITE_EXPERIENCE, SITE_LAYOUT, SITE_URL } from './lib/paths.mjs';
import { llmsPlaces, onwardRoutes, shellPrograms, unnamedTools } from './lib/rules.mjs';
import { pathwayOf, relatedRoutes } from '../src/pathways.mjs';

const failures = [];
const fail = (where, rule, message) => failures.push(`  ${where} (rule ${rule}): ${message}`);

if (SITE_LAYOUT !== 'pathways' || SITE_EXPERIENCE !== 'explore') {
  console.log('check:rules: not Version C (the pathways layout with Explore); nothing to check.');
  process.exit(0);
}
if (!existsSync(path.join(DIST_DIR, 'index.html'))) {
  console.error('check:rules: dist/ has no build. Run `npm run build` first.');
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
const known = new Set(pages.keys());
const NAV = (route) => route === '' || route === 'all' || route.startsWith('pathways/') || route === '404';
const SHELL = new Set(['bash', 'sh', 'shell', 'console', 'zsh', 'powershell', 'ps1']);

const llms = llmsPlaces(readFileSync(path.join(DIST_DIR, 'llms.txt'), 'utf8'), `${SITE_URL}${SITE_BASE}`);
const GOAL_INDEX = 'Find instructions by goal';

// The All documentation page: route → the pathway and group it is listed under.
const allDocs = new Map();
{
  const $ = pages.get('all');
  $('nav[aria-label="All documentation"] .lq-all-pathway').each((_, section) => {
    const pathway = $(section).find('h2').first().text().trim();
    $(section).find('.lq-all-group').each((_, group) => {
      const title = $(group).find('h3').first().text().trim();
      $(group).find('a[href]').each((_, a) => {
        const route = $(a).attr('href').slice(SITE_BASE.length).replace(/\/+$/, '');
        if (!allDocs.has(route)) allDocs.set(route, []);
        allDocs.get(route).push([pathway, title]);
      });
    });
  });
}

let checked = 0;
for (const [route, $] of pages) {
  if (NAV(route)) continue;
  checked += 1;
  const where = `/${route}`;
  const content = $('.sl-markdown-content').first();

  // Rule 10 — an onward route in the page's own text.
  const hrefs = content.find('a[href]').map((_, a) => $(a).attr('href')).get();
  if (onwardRoutes(hrefs, { route, base: SITE_BASE, known }).size === 0) {
    fail(where, 10, 'its text links to no other page of the site (no onward route)');
  }

  // Rule 11 — one home, named alike by the menu, the breadcrumb, All documentation and llms.txt.
  const pathway = pathwayOf(route);
  if (!pathway) {
    fail(where, 11, 'is in no pathway group');
  } else {
    const { group } = relatedRoutes(route, known);
    const current = $('.lq-pathway-sidebar .lq-side-link[aria-current="true"]');
    if (current.length !== 1 || current.attr('data-pathway') !== pathway.id) {
      fail(where, 11, `the sidebar marks ${current.attr('data-pathway') ?? 'no pathway'} as current, not ${pathway.id}`);
    }
    const crumb = $('nav.lq-pw-crumbs a').last().text().trim();
    if (crumb !== pathway.title) fail(where, 11, `breadcrumb says "${crumb}", menu says "${pathway.title}"`);
    const listed = allDocs.get(route) ?? [];
    if (listed.length !== 1 || listed[0][0] !== pathway.title || listed[0][1] !== group) {
      fail(where, 11, `All documentation lists it under ${JSON.stringify(listed)}, menu says ${pathway.title} › ${group}`);
    }
    const homes = (llms.get(route) ?? []).filter((headings) => headings[0] !== GOAL_INDEX);
    if (homes.length !== 1 || homes[0][0] !== pathway.title || homes[0][1] !== group) {
      fail(where, 11, `llms.txt lists it under ${JSON.stringify(homes)}, menu says ${pathway.title} › ${group}`);
    }
  }

  // Rule 12 — every program a shell block runs is named in the page's text.
  const programs = new Set();
  content.find('pre').each((_, pre) => {
    if (!SHELL.has(($(pre).attr('data-language') ?? '').toLowerCase())) return;
    const lines = $(pre).find('.ec-line').length
      ? $(pre).find('.ec-line').map((_, line) => $(line).text()).get()
      : $(pre).text().split('\n');
    for (const program of shellPrograms(lines)) programs.add(program);
  });
  if (programs.size) {
    const prose = content.clone();
    prose.find('pre, .expressive-code').remove();
    const unnamed = unnamedTools(programs, prose.text());
    if (unnamed.length) fail(where, 12, `its commands run ${unnamed.join(', ')}, which its text never names`);
  }
}

if (failures.length) {
  console.error(`check:rules: ${failures.length} failure(s) across ${checked} content pages:\n${failures.join('\n')}`);
  process.exit(1);
}
console.log(`check:rules: ${checked} content pages pass Annex A rules 10, 11 and 12.`);
