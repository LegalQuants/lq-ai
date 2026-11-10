/**
 * Shared set-up for the browser journeys: serve the built site with Astro's
 * preview server and drive it with the Chrome that `pa11y-ci` already installs
 * (the same source `check-tables.mjs` uses — no new dependency).
 */
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const SITE_ROOT = fileURLToPath(new URL('..', import.meta.url));
const puppeteer = require('puppeteer');
const astroBin = path.join(path.dirname(require.resolve('astro/package.json', { paths: [SITE_ROOT] })), 'bin', 'astro.mjs');

const PORT = process.env.E2E_PORT || '4325';
export const BASE = process.env.SITE_BASE ?? '/lq-ai/';
export const ORIGIN = `http://localhost:${PORT}`;
export const url = (route = '') => `${ORIGIN}${BASE}${route}`;

function astro(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [astroBin, ...args], { cwd: SITE_ROOT, stdio: 'ignore' });
    child.on('error', reject);
    child.on('close', (code) => resolve(code ?? 1));
  });
}

async function waitForServer(target, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try { if ((await fetch(target, { redirect: 'manual' })).status < 500) return; } catch { /* not yet */ }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`e2e: ${target} did not answer within ${timeoutMs / 1000}s`);
}

/** Start the preview server and Chrome; returns `{ browser, stop }`. */
export async function startSite() {
  await astro(['preview', 'stop']).catch(() => 0);
  if (await astro(['preview', '--background', '--port', PORT]) !== 0) throw new Error('e2e: could not start the preview server');
  await waitForServer(url());
  const browser = await puppeteer.launch({
    headless: process.env.SCREENSHOT_HEADLESS ?? 'shell',
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-device-scale-factor=1'],
  });
  return { browser, stop: async () => { await browser.close(); await astro(['preview', 'stop']).catch(() => 0); } };
}

/** A fresh page in its own context (its own sessionStorage) at one width. */
export async function openPage(browser, width, height = 900) {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  await page.setViewport({ width, height });
  // Script errors are collected; each journey asserts there were none.
  page.errors = [];
  page.on('pageerror', (error) => page.errors.push(error.message));
  return page;
}

/** Type a question into Explore's composer and wait for its turn to appear. */
export async function searchOnExplore(page, query) {
  await page.waitForSelector('#lq-docs-question:not([disabled])');
  const before = await page.$$eval('.lq-search-turn', (turns) => turns.length);
  await page.click('#lq-docs-question', { count: 3 });
  await page.type('#lq-docs-question', query);
  await page.keyboard.press('Enter');
  await page.waitForFunction((n) => document.querySelectorAll('.lq-search-turn').length > n, { timeout: 20000 }, before);
}
