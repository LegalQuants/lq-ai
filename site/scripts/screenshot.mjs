#!/usr/bin/env node
/**
 * Design-QA screenshots — a development tool, not part of any gate.
 * ================================================================
 *
 * Captures full-page PNGs of a handful of representative routes at two widths
 * (1280 desktop, 400 phone) in both themes, so a human — or an agent — can look
 * at the rendered pages rather than reason about CSS in the abstract.
 *
 * It is deliberately NOT wired into `npm run check`: it needs a running
 * `astro preview`, it writes outside the repository by default, and comparing
 * screenshots is a judgement, not a pass/fail. The a11y gate (`check:a11y`) and
 * the contrast gate (`check:contrast`) are the automated halves of the same job.
 *
 * Chrome comes from the `puppeteer` package that `pa11y-ci` already installs, so
 * this adds no dependency (§7 of the build brief).
 *
 * Usage:
 *
 *     npm run build
 *     node node_modules/astro/bin/astro.mjs preview --port 4331
 *     node scripts/screenshot.mjs --out /tmp/screens --origin http://localhost:4331
 *     node node_modules/astro/bin/astro.mjs preview stop
 *
 * Options:
 *   --out <dir>       where the PNGs go (default: ./.screens, git-ignored)
 *   --origin <url>    preview origin (default: http://localhost:4321)
 *   --widths a,b      viewport widths (default: 1280,400)
 *   --themes a,b      'light' and/or 'dark' (default: light,dark)
 *   --routes a,b      route paths relative to the base (default: the list below)
 *   --focus           also capture the keyboard-focus walk through the header
 *
 * Files are named `<route-slug>-<width>-<theme>.png`, where the slug is the
 * route with slashes turned into dashes (`/` itself becomes `home`).
 */

import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const SITE_ROOT = fileURLToPath(new URL('..', import.meta.url));

/** The base path is configuration, read back from the Astro config (never restated). */
const { default: astroConfig } = await import('../astro.config.mjs');
const BASE = astroConfig.base ?? '/';

/** Routes worth looking at: one of each shape the site builds. */
const DEFAULT_ROUTES = [
  '/', // MDX entry hub — CardGrid, LinkCards
  '/start/', // namespace hub
  '/start/is-it-for-you/', // prose page with tables
  '/operate/install-docker-compose/', // long procedure, code blocks, asides
  '/trust/', // namespace hub
  '/skills/catalogue/', // generated, wide table
  '/reference/configuration/', // generated, widest tables on the site
  '/changelog/', // generated index
];

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) continue;
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) {
      out[key] = true;
    } else {
      out[key] = next;
      i += 1;
    }
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
const OUT_DIR = path.resolve(SITE_ROOT, args.out ?? '.screens');
const ORIGIN = (args.origin ?? 'http://localhost:4321').replace(/\/$/, '');
const WIDTHS = String(args.widths ?? '1280,400')
  .split(',')
  .map((w) => Number(w.trim()))
  .filter(Boolean);
const THEMES = String(args.themes ?? 'light,dark')
  .split(',')
  .map((t) => t.trim())
  .filter(Boolean);
const ROUTES = args.routes ? String(args.routes).split(',').map((r) => r.trim()) : DEFAULT_ROUTES;

/** `/` → `home`; `/skills/catalogue/` → `skills-catalogue`. */
function slugOf(route) {
  const trimmed = route.replace(/^\/|\/$/g, '');
  return trimmed === '' ? 'home' : trimmed.replace(/\//g, '-');
}

function urlOf(route) {
  const base = BASE.endsWith('/') ? BASE.slice(0, -1) : BASE;
  return `${ORIGIN}${base}${route}`;
}

const puppeteer = require('puppeteer');

await mkdir(OUT_DIR, { recursive: true });

const browser = await puppeteer.launch({
  /**
   * `'shell'` is the old headless binary (`chrome-headless-shell`), not a
   * deprecated flag: puppeteer ships both and `headless: true` selects the
   * full browser. The full browser's `Page.captureScreenshot` can wedge
   * indefinitely on macOS — every capture times out, including one of
   * `<h1>hello</h1>` — while the shell captures the same page in
   * milliseconds. Screenshots are all this script does, so it asks for the
   * binary that takes them. (`pa11y-ci`, which needs a real browser to run
   * axe, keeps the default.)
   */
  headless: process.env.SCREENSHOT_HEADLESS ?? 'shell',
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1'],
  // `/reference/configuration/` is ~45,000px tall at 400px wide; a full-page
  // capture of it can outrun the default 180s CDP timeout on a busy machine.
  protocolTimeout: 600_000,
});

const written = [];

try {
  for (const theme of THEMES) {
    for (const width of WIDTHS) {
      const page = await browser.newPage();
      await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
      // Starlight's ThemeProvider reads `starlight-theme` from localStorage on
      // first paint, so seeding it before navigation avoids a flash of the other
      // theme in the capture. `prefers-color-scheme` is matched to it too, so
      // any media-query-driven rule agrees with the attribute.
      await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: theme }]);
      await page.evaluateOnNewDocument((t) => {
        try {
          localStorage.setItem('starlight-theme', t);
        } catch {
          /* private mode — the media emulation above still applies */
        }
      }, theme);

      for (const route of ROUTES) {
        const url = urlOf(route);
        const response = await page.goto(url, { waitUntil: 'networkidle0', timeout: 30_000 });
        // `response.ok()` is false for 304, which the preview server returns
        // freely once a page has been cached within the run. Anything under 400
        // rendered a page.
        if (!response || response.status() >= 400) {
          throw new Error(`${url} → ${response ? response.status() : 'no response'}`);
        }
        // The table-wrapping script measures on load and on resize; give the
        // layout one frame to settle before the capture. `requestAnimationFrame`
        // can stall indefinitely on a headless page the compositor has decided
        // is not visible, so the wait is raced against a timer.
        await page.evaluate(
          () =>
            new Promise((resolve) => {
              const done = () => resolve(null);
              requestAnimationFrame(done);
              setTimeout(done, 500);
            })
        );
        const file = path.join(OUT_DIR, `${slugOf(route)}-${width}-${theme}.png`);
        await page.screenshot({ path: file, fullPage: true });
        written.push(file);
      }

      await page.close();
    }
  }

  if (args.focus) {
    // Focus walk: tab from the top of the document and capture the first few
    // stops (skip link → wordmark → namespace nav), so the focus ring can be
    // judged rather than assumed. Viewport-only shots; the chrome is at the top.
    for (const theme of THEMES) {
      const page = await browser.newPage();
      await page.setViewport({ width: 1280, height: 420, deviceScaleFactor: 1 });
      await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: theme }]);
      await page.evaluateOnNewDocument((t) => {
        try {
          localStorage.setItem('starlight-theme', t);
        } catch {
          /* ignore */
        }
      }, theme);
      await page.goto(urlOf('/start/'), { waitUntil: 'networkidle0' });
      for (const stop of [1, 2, 3, 4]) {
        await page.keyboard.press('Tab');
        const label = await page.evaluate(() => {
          const el = document.activeElement;
          if (!el) return 'none';
          return `${el.tagName.toLowerCase()}:${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 24)}`;
        });
        const file = path.join(OUT_DIR, `focus-${stop}-1280-${theme}.png`);
        await page.screenshot({ path: file, fullPage: false });
        written.push(file);
        process.stdout.write(`focus stop ${stop} (${theme}): ${label}\n`);
      }
      await page.close();
    }
  }
} finally {
  await browser.close();
}

process.stdout.write(`screenshot: ${written.length} PNG(s) in ${OUT_DIR}\n`);
