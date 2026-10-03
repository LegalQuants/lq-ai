#!/usr/bin/env node
/**
 * The tables gate: no table-shaped content overflows the reading column.
 *
 * 118 Markdown tables on 40 of 78 pages used to render as generic wide
 * `<table>`s inside a scrollable region — 102 had content off-screen at
 * 1280px, 116 at 400px. `scripts/lib/rehype-lq-tables.mjs` renders each table
 * by its content's shape instead (definition list / records / grid); this
 * gate is the census script that measured the original problem
 * (`table-census.mjs`), turned into a pass/fail check modelled on
 * `scripts/a11y.mjs`: start `astro preview` in the background, wait for it,
 * measure every route in `dist/llms.txt` at two viewport widths, stop the
 * server whatever happened.
 *
 * A failure means an element inside `.sl-markdown-content` — a `<table>`,
 * `.lq-table`, `.lq-records`, or `.lq-dl` — has content wider than its box
 * (`scrollWidth > clientWidth + 1`; the `+1` absorbs sub-pixel rounding).
 * `pre`/`.expressive-code` code blocks are excluded — they scroll by design
 * and are the a11y gate's concern (a focusable scroll region), not this
 * gate's. A `[tabindex="0"][role="region"]` wrapper anywhere is also a
 * failure: that was the old scroll-box pattern, and none should remain.
 *
 *   node scripts/check-tables.mjs [--port 4321]
 */

import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const SITE_ROOT = fileURLToPath(new URL('..', import.meta.url));
const DIST_LLMS_TXT = path.join(SITE_ROOT, 'dist', 'llms.txt');

const argv = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = argv.indexOf(`--${name}`);
  return i === -1 ? fallback : argv[i + 1];
};

const PORT = flag('port', process.env.TABLES_PORT || '4321');
const ORIGIN = `http://localhost:${PORT}`;

// Astro's `exports` map does not expose its bin, so it is located from the
// package root — same pattern as `scripts/a11y.mjs`.
const astroBin = path.join(
  path.dirname(require.resolve('astro/package.json', { paths: [SITE_ROOT] })),
  'bin',
  'astro.mjs'
);

// Chrome comes from the `puppeteer` package `pa11y-ci` already installs —
// no new dependency (same source `scripts/screenshot.mjs` uses).
const puppeteer = require('puppeteer');

/** Run a node/binary script and resolve with its exit code. */
function run(script, args, { quiet = false } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script, ...args], {
      cwd: SITE_ROOT,
      stdio: quiet ? 'ignore' : 'inherit',
    });
    child.on('error', reject);
    child.on('close', (code) => resolve(code ?? 1));
  });
}

const stopPreview = () => run(astroBin, ['preview', 'stop'], { quiet: true }).catch(() => 0);

async function waitForServer(url, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { redirect: 'manual' });
      if (response.status < 500) return;
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`check-tables: ${url} did not answer within ${timeoutMs / 1000}s`);
}

/** Every route `dist/llms.txt` lists, as `[Title](https://…)` markdown links — same
 * extraction the original census script used. Pathnames already carry the site's
 * base path, so prepending the local preview origin is enough to reach them. */
function routesFromLlmsTxt() {
  let text;
  try {
    text = readFileSync(DIST_LLMS_TXT, 'utf8');
  } catch {
    console.error(`check-tables: ${DIST_LLMS_TXT} not found. Run \`npm run build\` first.`);
    process.exit(1);
  }
  const links = text.match(/\]\((https?:[^)]+)\)/g) ?? [];
  const pathnames = links.map((m) => new URL(m.slice(2, -1)).pathname);
  return [...new Set(pathnames)].sort();
}

const WIDTHS = [1280, 400];

/**
 * In-page measurement, run once per route per width via `page.evaluate`.
 * Targets `.sl-markdown-content` descendants that render as a table shape
 * (`table`, `.lq-table`, `.lq-records`, `.lq-dl`); `pre`/`.expressive-code`
 * scroll by design and are the a11y gate's concern, not this one's.
 */
function measurePage() {
  const overflows = [];
  const targets = document.querySelectorAll(
    '.sl-markdown-content table, .sl-markdown-content .lq-table, .sl-markdown-content .lq-records, .sl-markdown-content .lq-dl'
  );
  for (const el of targets) {
    if (el.closest('pre, .expressive-code')) continue;
    const hidden = el.scrollWidth - el.clientWidth;
    if (hidden > 1) {
      overflows.push({
        selector:
          el.className && typeof el.className === 'string'
            ? `${el.tagName.toLowerCase()}.${el.className.split(/\s+/).join('.')}`
            : el.tagName.toLowerCase(),
        hidden: Math.round(hidden),
      });
    }
  }
  const scrollRegions = document.querySelectorAll('[tabindex="0"][role="region"]');
  return { overflows, scrollRegionCount: scrollRegions.length };
}

async function main() {
  const routes = routesFromLlmsTxt();
  console.log(`check-tables: ${routes.length} route(s) to check against ${ORIGIN}.`);

  // A server left over from an interrupted run would serve a stale dist/.
  await stopPreview();

  let exitCode = 1;
  const browser = await puppeteer.launch({
    headless: process.env.SCREENSHOT_HEADLESS ?? 'shell',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1'],
  });

  try {
    const started = await run(astroBin, ['preview', '--background', '--port', PORT]);
    if (started !== 0) throw new Error('check-tables: could not start the preview server.');
    await waitForServer(ORIGIN + routes[0]);

    const failuresByWidth = new Map(WIDTHS.map((w) => [w, []]));

    const page = await browser.newPage();
    for (const width of WIDTHS) {
      await page.setViewport({ width, height: 900 });
      for (const route of routes) {
        await page.goto(ORIGIN + route, { waitUntil: 'load' });
        const { overflows, scrollRegionCount } = await page.evaluate(measurePage);
        for (const o of overflows) {
          failuresByWidth.get(width).push(`  ${route}  ${o.selector}  ${o.hidden}px overflow`);
        }
        if (scrollRegionCount > 0) {
          failuresByWidth
            .get(width)
            .push(`  ${route}  [tabindex="0"][role="region"]  ${scrollRegionCount} wrapper(s) remain`);
        }
      }
    }
    await page.close();

    let totalFailures = 0;
    for (const width of WIDTHS) {
      const failures = failuresByWidth.get(width);
      totalFailures += failures.length;
      console.log(`\n@${width}px: ${failures.length} failure(s)`);
      for (const line of failures) console.log(line);
    }

    exitCode = totalFailures === 0 ? 0 : 1;
    console.log(`\ncheck-tables: ${exitCode === 0 ? 'PASS' : 'FAIL'} (${totalFailures} total)`);
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    exitCode = 1;
  } finally {
    await browser.close();
    await stopPreview();
  }

  process.exit(exitCode);
}

await main();
