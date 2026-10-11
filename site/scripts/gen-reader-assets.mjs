#!/usr/bin/env node
/** Lazy reading assets generated from this build's complete guide pages. */
import { readFile, mkdir, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { DIST_DIR, MANIFEST_PATH, SITE_BASE, SITE_LAYOUT } from './lib/paths.mjs';
import { readerPayload } from './lib/reader-assets.mjs';
import { pathwayOf } from '../src/pathways.mjs';

if (SITE_LAYOUT === 'pathways') {
  const manifest = JSON.parse(await readFile(MANIFEST_PATH, 'utf8'));
  const pages = [...manifest.pages, ...manifest.navigation].filter((page) => page.route && page.route !== '404');
  const output = path.join(DIST_DIR, '_reader');
  await rm(output, { recursive: true, force: true });
  await mkdir(output, { recursive: true });
  const index = { schemaVersion: 1, base: SITE_BASE, pages: {} };
  for (const page of pages) {
    const html = await readFile(path.join(DIST_DIR, page.route, 'index.html'), 'utf8');
    const payload = readerPayload(html, page);
    const file = path.join(output, `${page.route}.json`);
    await mkdir(path.dirname(file), { recursive: true });
    await writeFile(file, JSON.stringify(payload));
    index.pages[page.route] = { title: page.title, url: page.url, status: page.status,
      kind: payload.kind, pathway: pathwayOf(page.route)?.id ?? null,
      tone: pathwayOf(page.route)?.tone ?? 'a',
      asset: `${SITE_BASE}_reader/${page.route}.json`, markdown: `${SITE_BASE}${page.route}.md` };
  }
  await writeFile(path.join(output, 'index.json'), JSON.stringify(index));
  console.log(`reader: ${pages.length} current guide/navigation assets; articles load on demand.`);
}
