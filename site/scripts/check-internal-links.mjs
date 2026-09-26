#!/usr/bin/env node
/**
 * Nothing links nowhere.
 *
 * Walks every `href` and `src` in `dist/**` and fails when one that points
 * inside this site does not resolve to a file that was built. This is the gate
 * behind the mini-PRD's "nothing is orphaned, nothing links nowhere" rule, and
 * it is deliberately a *post-build* check rather than a source check: the sync
 * already refuses a `.md` link that resolves to nothing, but only the built
 * output can tell you whether the route it produced actually rendered.
 *
 * What counts as resolving:
 *
 *  - a directory URL (`…/trust/threat-model/`) → `dist/trust/threat-model/index.html`
 *  - a file URL (`…/start/quickstart.md`, `…/llms.txt`, an image) → that file
 *  - the base itself (`/lq-ai/`) → `dist/index.html`
 *
 * External URLs are not checked. A trust centre that fetched every outbound
 * link on every build would be slow, flaky, and rate-limited; the stamp is what
 * makes an outbound repository link verifiable, not a HEAD request.
 */

import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

import { DIST_DIR, MANIFEST_PATH, SITE_BASE } from './lib/paths.mjs';

// `href="…"`, `href='…'`, and the unquoted form some minifiers emit.
const ATTRIBUTE = /\b(?:href|src)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'<>`]+))/gi;

const decodeEntities = (value) =>
  value
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#(\d+);/g, (_match, code) => String.fromCharCode(Number(code)));

function htmlFiles(dir) {
  const found = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      // Pagefind ships its own bundled assets and index shards; they are not
      // pages and their internal references are not site links.
      if (entry.name === 'pagefind') continue;
      found.push(...htmlFiles(full));
    } else if (entry.name.endsWith('.html')) {
      found.push(full);
    }
  }
  return found;
}

/** Where a site-internal URL should have landed in `dist/`. */
function targetFor(url) {
  const withoutFragment = url.split('#')[0].split('?')[0];
  if (!withoutFragment.startsWith(SITE_BASE)) return undefined;

  let rest = withoutFragment.slice(SITE_BASE.length);
  try {
    rest = decodeURIComponent(rest);
  } catch {
    /* a URL we cannot decode is reported as written */
  }

  if (rest === '' || rest.endsWith('/')) return path.join(DIST_DIR, rest, 'index.html');
  return path.join(DIST_DIR, rest);
}

function main() {
  if (!existsSync(DIST_DIR)) {
    console.error(`check:links: no ${DIST_DIR} — run \`npm run build\` first.`);
    process.exitCode = 1;
    return;
  }

  const files = htmlFiles(DIST_DIR);
  const failures = [];
  let checked = 0;

  for (const file of files) {
    const html = readFileSync(file, 'utf8');
    const seen = new Set();
    for (const match of html.matchAll(ATTRIBUTE)) {
      const raw = decodeEntities(match[1] ?? match[2] ?? match[3] ?? '');
      if (!raw || raw.startsWith('#') || raw.startsWith('data:')) continue;
      if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(raw)) continue;
      if (!raw.startsWith(SITE_BASE)) {
        // A root-absolute URL that is not under the base can never resolve on a
        // site served from a subdirectory. Report it rather than skip it.
        if (raw.startsWith('/')) {
          failures.push({ file, url: raw, why: `outside the base path (${SITE_BASE})` });
        }
        continue;
      }
      if (seen.has(raw)) continue;
      seen.add(raw);

      const target = targetFor(raw);
      checked += 1;
      if (!target || !existsSync(target) || statSync(target).isDirectory()) {
        failures.push({ file, url: raw, why: `no file at ${path.relative(DIST_DIR, target ?? '')}` });
      }
    }
  }

  const routes = existsSync(MANIFEST_PATH)
    ? JSON.parse(readFileSync(MANIFEST_PATH, 'utf8')).pages?.length ?? 0
    : 0;

  if (failures.length) {
    console.error(`check:links: ${failures.length} internal link(s) resolve to nothing.`);
    for (const failure of failures) {
      console.error(`  ${path.relative(DIST_DIR, failure.file)} → ${failure.url} (${failure.why})`);
    }
    process.exitCode = 1;
    return;
  }

  console.log(
    `check:links: ${checked} internal link(s) across ${files.length} built page(s) all resolve (${routes} route(s) in the manifest).`
  );
}

main();
