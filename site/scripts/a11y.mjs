#!/usr/bin/env node
/**
 * Run the accessibility gate against a real server.
 *
 *   1. stop any preview server left behind by an earlier run;
 *   2. start `astro preview` in the background on the gate's port;
 *   3. wait for it to answer;
 *   4. run pa11y-ci over every route in `dist/`;
 *   5. stop the server, whatever happened.
 *
 * Astro 7's `preview` is a daemon: the CLI process returns as soon as the server
 * is up, and the server is stopped with `astro preview stop` rather than by
 * signalling the process that started it. Doing this through Node's `spawn`
 * rather than a shell one-liner keeps the behaviour identical on macOS and on
 * the Linux CI runner — no `&`, no `wait-on`, no `lsof`, no shell-specific trap.
 *
 * Violations are reported, never suppressed — the exit code is pa11y-ci's.
 */

import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const SITE_ROOT = fileURLToPath(new URL('..', import.meta.url));

const PORT = process.env.PA11Y_PORT || '4321';
// The base path is set once, in astro.config.mjs; it is read back rather than
// restated so the gate follows the site if the base ever changes.
const { default: astroConfig } = await import('../astro.config.mjs');
const BASE = astroConfig.base ?? '/';
const ORIGIN = `http://localhost:${PORT}`;
const READY_URL = ORIGIN + (BASE.endsWith('/') ? BASE : `${BASE}/`);

// Astro's `exports` map does not expose its bin, so it is located from the
// package root. Both binaries are run through `process.execPath` rather than
// through `node_modules/.bin`, whose extensionless symlink would be loaded as
// CommonJS and fail on the ESM entry point.
const astroBin = path.join(
  path.dirname(require.resolve('astro/package.json', { paths: [SITE_ROOT] })),
  'bin',
  'astro.mjs'
);
const pa11yCiBin = require.resolve('pa11y-ci/bin/pa11y-ci.js', { paths: [SITE_ROOT] });

/** Run a node script and resolve with its exit code. */
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

/** Collect a node script's stdout. */
function capture(script, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script, ...args], { cwd: SITE_ROOT });
    let out = '';
    let err = '';
    child.stdout.on('data', (chunk) => (out += chunk));
    child.stderr.on('data', (chunk) => (err += chunk));
    child.on('error', reject);
    child.on('close', (code) =>
      code === 0 ? resolve(out) : reject(new Error(err.trim() || `exit ${code}`))
    );
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
  throw new Error(`a11y: ${url} did not answer within ${timeoutMs / 1000}s`);
}

const urls = (await capture(path.join(SITE_ROOT, 'scripts', 'a11y-urls.mjs'), ['--port', PORT]))
  .split('\n')
  .map((line) => line.trim())
  .filter(Boolean);

console.log(`a11y: ${urls.length} route(s) to check against ${ORIGIN}.`);

// A server left over from an interrupted run would serve a stale dist/, so the
// gate always starts from a clean one.
await stopPreview();

let code = 1;
try {
  const started = await run(astroBin, ['preview', '--background', '--port', PORT]);
  if (started !== 0) throw new Error('a11y: could not start the preview server.');
  await waitForServer(READY_URL);
  code = await run(pa11yCiBin, urls);
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  code = 1;
} finally {
  await stopPreview();
}

process.exit(code);
