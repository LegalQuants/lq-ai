/** Product captures belong to the site transform, alongside their descriptions. */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { isHeading, scanLines, selectSection } from './markdown.mjs';
import { SITE_BASE, SITE_ROOT } from './paths.mjs';

export const SCREENSHOTS_CONFIG = 'site/product-captures/screenshots.json';
export const productScreenshots = JSON.parse(readFileSync(path.join(SITE_ROOT, 'product-captures/screenshots.json'), 'utf8'));

export function validateScreenshots(config, publicDir = path.join(SITE_ROOT, 'public/product')) {
  if (config.schemaVersion !== 1 || !config.capture?.note || !Array.isArray(config.screenshots) || !Array.isArray(config.placements)) throw new Error('unsupported product screenshot configuration');
  const ids = new Set();
  for (const shot of config.screenshots) {
    if (!/^[a-z][a-z0-9-]*$/.test(shot.id) || ids.has(shot.id)) throw new Error('invalid or duplicate screenshot id');
    ids.add(shot.id);
    if (!/^[a-z0-9-]+\.(?:jpg|png)$/.test(shot.file) || !existsSync(path.join(publicDir, shot.file))) throw new Error(`missing or invalid screenshot asset: ${shot.file}`);
    if (!shot.alt?.trim() || !shot.caption?.trim() || !Number.isInteger(shot.width) || !Number.isInteger(shot.height) || shot.width <= 0 || shot.height <= 0) throw new Error(`incomplete screenshot description: ${shot.id}`);
  }
  const placements = new Set();
  for (const placement of config.placements) {
    const key = `${placement.route}:${placement.source}:${placement.heading}`;
    if (typeof placement.route !== 'string' || !placement.source || !/^#{1,6} /.test(placement.heading) || ![undefined, 'after-paragraph', 'after-section'].includes(placement.position) || placements.has(key) || !placement.screenshots?.length || new Set(placement.screenshots).size !== placement.screenshots.length || placement.screenshots.some((id) => !ids.has(id))) throw new Error(`invalid screenshot placement: ${key}`);
    placements.add(key);
  }
}

const escape = (value) => String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const assetUrl = (shot, base) => `${base}product/${shot.file}`;

/** Descriptions and qualifications are identical in HTML and agent Markdown. */
export function renderScreenshots(placement, { html = false, base = SITE_BASE, config = productScreenshots } = {}) {
  const shots = placement.screenshots.map((id) => config.screenshots.find((shot) => shot.id === id));
  const galleryHeading = '#'.repeat(Math.min(6, placement.heading.match(/^#+/)[0].length + 1));
  if (!html) return [`${galleryHeading} LQ.AI in action`, '', config.capture.note, '', ...shots.flatMap((shot) => [
    `![${shot.alt}](${assetUrl(shot, base)})`, '', shot.caption, ...(shot.note ? ['', shot.note] : []), '',
    ...(shot.capturedOn || shot.recordedOn ? [`${shot.capturedOn ? 'Captured' : 'Recorded'}: ${shot.capturedOn ?? shot.recordedOn}; product revision ${shot.revision}.`, ''] : []),
  ])].join('\n').trim();
  const figure = (shot) => `<figure class="lq-product-shot"><a href="${assetUrl(shot, base)}" aria-label="Open full-size screenshot: ${escape(shot.caption)}"><img src="${assetUrl(shot, base)}" width="${shot.width}" height="${shot.height}" loading="lazy" decoding="async" alt="${escape(shot.alt)}" /></a><figcaption>${escape(shot.caption)}${shot.note ? ` <span class="lq-product-qualification">${escape(shot.note)}</span>` : ''} <a href="${assetUrl(shot, base)}">Open full-size screenshot</a></figcaption></figure>`;
  return `<section class="lq-product-screens" aria-label="LQ.AI in action"><p class="lq-product-title"><strong>LQ.AI in action</strong></p>${figure(shots[0])}<p class="lq-product-note">${escape(config.capture.note)}</p>${shots.length > 1 ? `<details class="lq-product-setup"><summary>See more product examples</summary>${shots.slice(1).map(figure).join('')}</details>` : ''}</section>`;
}

function afterFirstParagraph(markdown, insert) {
  const lines = scanLines(markdown);
  const start = lines.findIndex(({ line }) => line.trim());
  if (start < 0 || lines[start].inFence || isHeading(lines[start]) || /^\s*(?:[<>]|[-*] |\d+\. )/.test(lines[start].line)) throw new Error('screenshot placement needs an introductory paragraph');
  let end = start;
  while (end < lines.length && lines[end].line.trim() && !lines[end].inFence && !isHeading(lines[end])) end++;
  const text = lines.map(({ line }) => line);
  text.splice(end, 0, '', insert, '');
  return text.join('\n');
}

/** Match the canonical file as well as its route; fixtures and other docs stay intact. */
export function addProductScreenshots(markdown, { route, sources = [], heading, html = false, base = SITE_BASE, config = productScreenshots }) {
  let output = markdown;
  for (const placement of config.placements.filter((p) => p.route === route && sources.includes(p.source) && (!heading || p.heading === heading))) {
    const insertion = renderScreenshots(placement, { html, base, config });
    if (heading) {
      output = afterFirstParagraph(output, insertion);
      continue;
    }
    const section = selectSection(output, placement.heading);
    const lines = scanLines(output);
    const start = lines.findIndex((entry) => isHeading(entry) && entry.line.trim() === placement.heading);
    const level = placement.heading.match(/^#+/)[0].length;
    let end = start + 1;
    while (end < lines.length && !(isHeading(lines[end]) && lines[end].line.match(/^#+/)[0].length <= level)) end++;
    const text = lines.map(({ line }) => line);
    const body = placement.position === 'after-section' ? `${section.markdown}\n\n${insertion}` : afterFirstParagraph(section.markdown, insertion);
    text.splice(start + 1, end - start - 1, '', body, '');
    output = text.join('\n');
  }
  return output;
}
