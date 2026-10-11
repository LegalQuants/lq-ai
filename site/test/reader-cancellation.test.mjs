import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { it } from 'node:test';
import { transform } from 'esbuild';

// Use Astro's installed TypeScript transpiler to exercise the real controller.
const source = readFileSync(new URL('../src/scripts/guide-reader.ts', import.meta.url), 'utf8');
const compiled = await transform(source, { loader: 'ts', format: 'esm', target: 'es2022' });
const moduleSource = compiled.code.replace(/(['"])\.\.\/lib\/explore-state\.mjs\1/,
  JSON.stringify(new URL('../src/lib/explore-state.mjs', import.meta.url).href));
const { GuideReader } = await import(`data:text/javascript;base64,${Buffer.from(moduleSource).toString('base64')}`);

it('returning to Explore while the first registry loads does not reopen a stale reader', async (t) => {
  const previous = new Map(['document', 'location'].map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  Object.assign(globalThis, {
    document: { title: 'Explore', body: { classList: { remove() {} } }, querySelectorAll: () => [], getElementById: () => null },
    location: { origin: 'https://docs.example' },
  });
  t.after(() => {
    for (const [key, descriptor] of previous) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  });
  let fetches = 0;
  t.mock.method(globalThis, 'fetch', async () => {
    fetches++;
    return { ok: true, json: async () => ({ schemaVersion: 1 }) };
  });

  let finishRegistry;
  const pendingRegistry = new Promise((resolve) => { finishRegistry = resolve; });
  const dialog = { open: false, close() { this.open = false; } };
  let articleChanges = 0;
  const reader = Object.assign(Object.create(GuideReader.prototype), {
    base: '/', request: 0, current: null, cache: new Map(), dialog,
    rootTitle: 'Explore', body: { replaceChildren() { articleChanges++; } }, status: {},
    index: () => pendingRegistry,
    show: () => { dialog.open = true; },
  });

  const opening = reader.open('/start/example/');
  reader.close(false);
  finishRegistry({ pages: { 'start/example': { url: '/start/example/', asset: '/_reader/start/example.json' } } });
  await opening;

  assert.equal(dialog.open, false, 'a cancelled lookup must not reopen the reader');
  assert.equal(articleChanges, 0, 'a cancelled lookup must not replace the article');
  assert.equal(fetches, 0, 'a cancelled lookup must not fetch a guide');
});
