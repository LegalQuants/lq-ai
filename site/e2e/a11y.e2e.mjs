/** Real-browser regression: all literal routes run, and violations fail. */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { once } from 'node:events';
import { it } from 'node:test';
import { auditRoutes } from '../scripts/lib/a11y.mjs';

const require = createRequire(import.meta.url);
const pa11yCi = require('pa11y-ci');
const { defaults } = require('../.pa11yci.cjs');

it('audits root, nested and 404 routes and fails on a nested-page violation', async () => {
  const visited = new Set();
  let broken = false;
  const server = createServer((req, res) => {
    visited.add(req.url);
    res.setHeader('Content-Type', 'text/html');
    res.end(`<!doctype html><html lang="en"><head><title>Audit fixture</title></head>
      <body><main><h1>Audit fixture</h1>${broken && req.url === '/guide/' ? '<button></button>' : '<p>Accessible content.</p>'}</main></body></html>`);
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const paths = ['/', '/guide/', '/404.html'];
  const urls = paths.map((path) => `http://127.0.0.1:${server.address().port}${path}`);
  try {
    assert.equal(await auditRoutes(urls, defaults, pa11yCi), 0);
    for (const path of paths) assert.ok(visited.has(path), `${path} was checked`);
    visited.clear();
    broken = true;
    assert.equal(await auditRoutes(urls, defaults, pa11yCi), 2, 'an inaccessible nested route must fail the gate');
    for (const path of paths) assert.ok(visited.has(path), `${path} was checked on the failing run`);
  } finally {
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});
