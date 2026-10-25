#!/usr/bin/env node
/**
 * `_guides/index.json`: one entry per guide and navigation page, which Explore
 * loads with its first search to show a selected result's details beside the
 * conversation (src/scripts/guide-details.ts). Built from this build's pages.
 */
import { readFile, mkdir, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { DIST_DIR, MANIFEST_PATH, SITE_BASE, SITE_LAYOUT } from './lib/paths.mjs';
import { detailsPage, guideDetails } from './lib/guide-details.mjs';
import { pathwayOf } from '../src/pathways.mjs';
import { releaseFor } from './lib/git.mjs';

if (SITE_LAYOUT === 'pathways') {
  const manifest = JSON.parse(await readFile(MANIFEST_PATH, 'utf8'));
  const pages = [...manifest.pages, ...manifest.navigation].filter((page) => page.route && page.route !== '404')
    .map((page) => ({ ...detailsPage(page, SITE_BASE), ...releaseFor(page, page.sha) }));
  const output = path.join(DIST_DIR, '_guides');
  await rm(output, { recursive: true, force: true });
  await mkdir(output, { recursive: true });
  const index = { schemaVersion: 2, base: SITE_BASE, pages: {} };
  for (const page of pages) {
    const html = await readFile(path.join(DIST_DIR, page.route, 'index.html'), 'utf8');
    const pathway = pathwayOf(page.route);
    index.pages[page.route] = { ...guideDetails(html, page), pathway: pathway?.id ?? null,
      governance: Boolean(pathway?.governance), markdown: `${SITE_BASE}${page.route}.md` };
  }
  await writeFile(path.join(output, 'index.json'), JSON.stringify(index));
  console.log(`guides: details for ${pages.length} guide/navigation pages.`);
}
