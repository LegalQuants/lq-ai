#!/usr/bin/env node
/**
 * The machine surface: a `.md` twin of every page, `/llms.txt`, `/llms-full.txt`.
 *
 * An agent orienting on this project should not have to parse the site's HTML
 * to read it (journey J5). Every route therefore has a plain-Markdown twin at
 * the same path plus `.md`, and the two index files give an agent the whole
 * site in one fetch — `llms.txt` as a map, `llms-full.txt` as the text.
 *
 * The twin is the **transformed** Markdown, not the source: includes expanded,
 * links already absolute, stamp in the header. What a reader sees and what a
 * machine reads are the same content, which is the only version of this worth
 * shipping — a machine surface that can drift from the page is a second
 * documentation set nobody maintains.
 *
 * Built into the project rather than taken from a plugin (ADR 0028 decision 4):
 * the machine surface is a launch commitment, and a commitment should not
 * depend on an upstream plugin continuing to exist.
 *
 * Reads `.sync-manifest.json`; writes into `dist/`. Runs after `astro build`.
 */

import { existsSync, readFileSync } from 'node:fs';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

import { DIST_DIR, MANIFEST_PATH, OUT_ROOT, canonicalUrl } from './lib/paths.mjs';
import { parsePage, reduceMdx } from './lib/markdown.mjs';

const SITE_NAME = 'LQ.AI documentation';

const SITE_SUMMARY =
  'Documentation for LQ.AI, a self-hosted, open-source AI platform for in-house legal teams: ' +
  'it runs on infrastructure the operator controls, against model-provider keys the operator ' +
  'supplies, and every artifact that shapes an answer ships as source. Each page below states ' +
  'the commit it was checked against and the canonical repository files it was checked against, ' +
  'so a claim on this site can be verified against the repository rather than taken on trust. ' +
  'Every page is also available as Markdown at its own URL plus `.md`.';

/**
 * The four-line header every twin carries. Machine-readable, not decorative —
 * which is why the values are collapsed to one line each: a description that
 * wrapped in the author's YAML would otherwise turn a four-line header into a
 * five-line one and break anything parsing it by position.
 */
const oneLine = (value) => String(value ?? '').split(/\s+/).join(' ').trim();

function header(page) {
  return [
    `title: ${oneLine(page.title)}`,
    `description: ${oneLine(page.description)}`,
    `url: ${canonicalUrl(page.route)}`,
    `checked-against: ${page.sha}${page.date ? ` (${page.date})` : ''}`,
  ].join('\n');
}

/** `start/quickstart` → `dist/start/quickstart.md`; the root → `dist/index.md`. */
const twinPath = (route) => path.join(DIST_DIR, route ? `${route}.md` : 'index.md');

function markdownFor(page) {
  const file = path.join(OUT_ROOT, page.contentFile);
  if (!existsSync(file)) return null;
  const { content } = parsePage(readFileSync(file, 'utf8'));
  return page.isMdx ? reduceMdx(content) : content.trim();
}

async function main() {
  if (!existsSync(MANIFEST_PATH)) {
    console.error(
      `postbuild: no ${path.basename(MANIFEST_PATH)} — run \`npm run sync\` before this script.`
    );
    process.exitCode = 1;
    return;
  }

  if (!existsSync(DIST_DIR)) {
    console.error(`postbuild: no ${DIST_DIR} — run \`astro build\` before this script.`);
    process.exitCode = 1;
    return;
  }

  const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8'));
  const pages = manifest.pages ?? [];

  const missing = [];
  const written = [];
  const full = [];
  const byNamespace = new Map();

  for (const page of pages) {
    const markdown = markdownFor(page);
    if (markdown === null) {
      missing.push(page.contentFile);
      continue;
    }

    const document = `${header(page)}\n\n${markdown}\n`;
    const target = twinPath(page.route);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, document, 'utf8');
    written.push(target);

    full.push(document);

    const namespace = page.namespace || '';
    if (!byNamespace.has(namespace)) byNamespace.set(namespace, []);
    byNamespace.get(namespace).push(page);
  }

  // --- llms.txt --------------------------------------------------------------
  const labelOf = (dir) =>
    manifest.namespaces?.find((entry) => entry.dir === dir)?.label ?? 'Entry';

  const llms = [`# ${SITE_NAME}`, '', `> ${SITE_SUMMARY}`, ''];
  for (const [namespace, group] of byNamespace) {
    llms.push(`## ${labelOf(namespace)}`, '');
    for (const page of group) {
      llms.push(`- [${oneLine(page.title)}](${canonicalUrl(page.route)}): ${oneLine(page.description)}`);
    }
    llms.push('');
  }
  await writeFile(path.join(DIST_DIR, 'llms.txt'), `${llms.join('\n').trimEnd()}\n`, 'utf8');

  // --- llms-full.txt ---------------------------------------------------------
  await writeFile(
    path.join(DIST_DIR, 'llms-full.txt'),
    `${[`# ${SITE_NAME}`, '', `> ${SITE_SUMMARY}`, '', ...joinDocuments(full)].join('\n').trimEnd()}\n`,
    'utf8'
  );

  if (missing.length) {
    console.error(
      `postbuild: ${missing.length} page(s) in the manifest have no generated Markdown: ${missing.join(', ')}`
    );
    process.exitCode = 1;
  }

  console.log(
    `postbuild: ${written.length} .md twin(s), llms.txt (${pages.length} entries), llms-full.txt.`
  );
}

/** A rule between pages so a reader can tell where one ends. */
const joinDocuments = (documents) =>
  documents.flatMap((document, index) => (index === 0 ? [document] : ['', '---', '', document]));

await main();
