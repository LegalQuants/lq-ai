#!/usr/bin/env node
/** Build-only Mermaid: use the existing Chrome tooling, ship SVGs and plain text. */
import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir, rm, readdir, copyFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { existsSync } from 'node:fs';
import { OUT_ROOT, SITE_ROOT, SITE_BASE, MANIFEST_PATH } from './lib/paths.mjs';
import { DIAGRAM_COLORS, diagramKey, portraitSource, replaceDiagrams, intrinsicSvg } from './lib/diagrams.mjs';

const require = createRequire(import.meta.url);
const mermaidDist = path.dirname(require.resolve('mermaid'));
const mermaidPackage = JSON.parse(await readFile(path.join(mermaidDist, '..', 'package.json'), 'utf8'));
const rendererVersion = mermaidPackage.version + ':' + createHash('sha256')
  .update(await readFile(fileURLToPath(import.meta.url)))
  .update(await readFile(new URL('./lib/diagrams.mjs', import.meta.url)))
  .digest('hex');
const cacheDir = path.join(SITE_ROOT, '.diagram-cache');
const outputDir = path.join(OUT_ROOT, 'public', '_diagrams');
let browser;
let page;

async function renderSvg(source, theme, portrait = false) {
  const key = diagramKey(source, theme, `${rendererVersion}:${portrait ? 'portrait' : 'landscape'}`);
  const filename = `${key}.svg`;
  const cached = path.join(cacheDir, filename);
  if (!existsSync(cached)) {
    if (!browser) {
      const puppeteer = require('puppeteer');
      browser = await puppeteer.launch({ headless: true,
        args: process.env.CI ? ['--no-sandbox', '--disable-dev-shm-usage'] : [] });
      page = await browser.newPage();
      await page.setRequestInterception(true);
      page.on('request', (request) => request.url().startsWith('data:') || request.url() === 'about:blank'
        ? request.continue() : request.abort());
      await page.setContent('<!doctype html><html><body></body></html>');
      await page.addScriptTag({ path: path.join(mermaidDist, 'mermaid.min.js') });
    }
    const svg = await page.evaluate(async ({ source, key, colors, portrait }) => {
      document.body.replaceChildren();
      globalThis.mermaid.initialize({ startOnLoad: false, securityLevel: 'strict',
        theme: 'base', themeVariables: { ...colors, fontFamily: 'Arial, sans-serif', fontSize: '18px' },
        fontFamily: 'Arial, sans-serif', htmlLabels: false,
        flowchart: { htmlLabels: false, nodeSpacing: portrait ? 12 : 50, rankSpacing: portrait ? 36 : 50 },
        deterministicIds: true, deterministicIDSeed: key, maxTextSize: 20000, maxEdges: 200,
      });
      const result = await globalThis.mermaid.render(`diagram-${key}`, source);
      return result.svg;
    }, { source, key, colors: DIAGRAM_COLORS[theme], portrait });
    await writeFile(cached, intrinsicSvg(svg), 'utf8');
  }
  await copyFile(cached, path.join(outputDir, filename));
  return `${SITE_BASE}_diagrams/${filename}`;
}

async function assetsFor(diagram) {
  const portrait = portraitSource(diagram.source);
  const assets = {};
  // Mermaid renders into one local DOM; keep calls sequential.
  for (const theme of ['light', 'dark']) {
    assets[theme] = { landscape: await renderSvg(diagram.source, theme),
      portrait: await renderSvg(portrait, theme, true) };
  }
  return assets;
}

async function main() {
  if (!existsSync(MANIFEST_PATH)) throw new Error('run npm run sync before rendering diagrams');
  const manifest = JSON.parse(await readFile(MANIFEST_PATH, 'utf8'));
  const inputsDir = path.join(OUT_ROOT, 'src', 'generated', 'diagram-inputs');
  await mkdir(cacheDir, { recursive: true });
  await rm(outputDir, { recursive: true, force: true });
  await mkdir(outputDir, { recursive: true });
  // Navigation Markdown and normalized machine files are deliberately not
  // replaced: they must retain the original definitions and descriptions.
  const files = (manifest.pages ?? []).map((entry) => path.join(OUT_ROOT, entry.contentFile));
  const exploreDir = path.join(OUT_ROOT, 'src', 'content', 'explore');
  if (existsSync(exploreDir)) files.push(...(await readdir(exploreDir))
    .filter((name) => name.endsWith('.md')).map((name) => path.join(exploreDir, name)));
  let count = 0;
  try {
    for (const file of files) {
      try {
        // Preserve the pre-diagram generated input until the next sync. This
        // makes rerunning the renderer safe instead of deleting still-used SVGs.
        const inputFile = path.join(inputsDir, path.relative(OUT_ROOT, file));
        if (!existsSync(inputFile)) {
          await mkdir(path.dirname(inputFile), { recursive: true });
          await copyFile(file, inputFile);
        }
        const input = await readFile(inputFile, 'utf8');
        const output = await replaceDiagrams(input, assetsFor);
        if (output.count) await writeFile(file, output.markdown, 'utf8');
        count += output.count;
      } catch (error) {
        throw new Error(`${path.relative(OUT_ROOT, file)}: ${error.message}`, { cause: error });
      }
    }
  } finally {
    if (browser) await browser.close();
  }
  console.log(`diagrams: ${count} rendered view(s); canonical Markdown and agent definitions preserved.`);
}

await main();
