/** Accessible Mermaid definitions stay in Markdown; only human HTML is replaced. */
import { createHash } from 'node:crypto';

/**
 * The interface redesign's greys (site/src/styles/theme.css): nodes on the
 * surface fill with ink text, lines and borders in the muted grey. Monochrome,
 * like the rest of the site (C28). Measured in test/diagrams.test.mjs.
 */
export const DIAGRAM_COLORS = {
  light: { background: '#ffffff', primaryColor: '#f1f1f3', primaryTextColor: '#111114',
    primaryBorderColor: '#4f5158', lineColor: '#4f5158', secondaryColor: '#f9f9fa',
    tertiaryColor: '#e9e9ec', clusterBkg: '#f9f9fa', clusterBorder: '#686a72',
    edgeLabelBackground: '#ffffff', titleColor: '#111114' },
  dark: { background: '#0e0f12', primaryColor: '#1a1b1f', primaryTextColor: '#f4f4f5',
    primaryBorderColor: '#b4b4bb', lineColor: '#b4b4bb', secondaryColor: '#141518',
    tertiaryColor: '#1e1f23', clusterBkg: '#141518', clusterBorder: '#8e8e96',
    edgeLabelBackground: '#0e0f12', titleColor: '#f4f4f5' },
};

export function diagramMetadata(source) {
  const title = /^\s*accTitle\s*:\s*(.+)$/m.exec(source)?.[1].trim();
  const description = /^\s*accDescr\s*:\s*(.+)$/m.exec(source)?.[1].trim();
  // Ordinary examples stay code. Opting into rendering requires both text
  // alternatives, so a missing description cannot become an empty image.
  if (!title && !description) return null;
  if (!title || !description) throw new Error('rendered Mermaid needs accTitle and a one-line accDescr');
  if (source.length > 20000) throw new Error('diagram exceeds the 20,000-character limit');
  if (/%%\s*\{|^\s*---\s*$|^\s*click\s+/m.test(source)) {
    throw new Error('diagram configuration and click directives are not allowed');
  }
  return { title, description };
}

/** Fence-aware extraction, with line numbers for build diagnostics. */
export function findDiagrams(markdown) {
  const lines = String(markdown).split('\n');
  const diagrams = [];
  let fence = null;
  for (let index = 0; index < lines.length; index++) {
    const match = /^\s{0,3}(`{3,}|~{3,})(.*)$/.exec(lines[index]);
    if (!fence && match) {
      fence = { marker: match[1], language: match[2].trim(), start: index };
    } else if (fence && match && match[1][0] === fence.marker[0]
      && match[1].length >= fence.marker.length && !match[2].trim()) {
      if (fence.language === 'mermaid') {
        const source = lines.slice(fence.start + 1, index).join('\n');
        try {
          const metadata = diagramMetadata(source);
          if (metadata) diagrams.push({ ...metadata, source, start: fence.start, end: index, line: fence.start + 1 });
        } catch (error) {
          throw new Error(`line ${fence.start + 1}: ${error.message}`);
        }
      }
      fence = null;
    }
  }
  if (fence?.language === 'mermaid') throw new Error(`line ${fence.start + 1}: unclosed Mermaid fence`);
  return diagrams;
}

/** Same graph, portrait layout. Definitions and edge meaning are unchanged. */
export function portraitSource(source) {
  let portrait = source.replace(/^(\s*(?:flowchart|graph))\s+(?:LR|RL)\b/m, '$1 TB')
    .replace(/^(\s*direction)\s+(?:LR|RL)\b/gm, '$1 TB')
    .replace(/^([ \t]*)%% portrait-stack:\s*(.+)$/gm, (_match, indent, list) => {
      const ids = list.trim().split(/\s+/);
      if (ids.length < 2 || ids.length > 12 || new Set(ids).size !== ids.length
        || ids.some((id) => !/^[A-Za-z_]\w*$/.test(id)
          || !new RegExp(`\\b${id}\\s*[\\[({]`).test(source))) {
        throw new Error('portrait-stack must name 2–12 distinct declared nodes');
      }
      // Invisible links constrain rank only. They never add a visible flow.
      return `${indent}%% Narrow-screen layout constraint\n${indent}${ids.join(' ~~~ ')}`;
    });
  if (/^\s*%% portrait-flat\s*$/m.test(source)) {
    let group = null;
    const wrap = (text) => {
      const lines = [''];
      for (const word of text.split(/\s+/)) {
        if (lines.at(-1).length + (lines.at(-1) ? 1 : 0) + word.length > 16 && lines.at(-1)) lines.push('');
        lines[lines.length - 1] += (lines.at(-1) ? ' ' : '') + word;
      }
      return lines.join('\n');
    };
    portrait = portrait.split('\n').flatMap((line) => {
      const start = /^\s*subgraph\s+\w+\["([^"]+)"\]\s*$/.exec(line);
      if (start) {
        if (group) throw new Error('portrait-flat supports single-level labelled subgraphs');
        group = start[1];
        return [];
      }
      if (/^\s*subgraph\b/.test(line)) throw new Error('portrait-flat needs single-level labelled subgraphs');
      if (line.trim() === 'end' && group) { group = null; return []; }
      if (/^\s*(?:direction\s+|%% portrait-flat)/.test(line)) return [];
      if (group) {
        const withoutLabels = line.replace(/"[^"]*"/g, '""');
        if (/\b\w+\s*(?:\(|\{|\[\[|\[\(|\[(?!"))/.test(withoutLabels)
          || /\b\w+\["[^"\n]*`/.test(line)) {
          throw new Error('portrait-flat needs quoted rectangular node labels');
        }
      }
      return [group ? line.replace(/\b(\w+)\["([^"`]+)"\]/g,
        (_match, id, label) => `${id}["\`${wrap(group)}\n${wrap(label)}\`"]`) : line];
    }).join('\n');
    if (group) throw new Error('unclosed portrait-flat subgraph');
  }
  return portrait;
}

export function diagramKey(source, theme, rendererVersion) {
  return createHash('sha256').update(JSON.stringify({ source, theme,
    colors: DIAGRAM_COLORS[theme], rendererVersion })).digest('hex').slice(0, 20);
}

const escape = (text) => String(text).replace(/[&<>"'{}]/g,
  (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '{': '&#123;', '}': '&#125;' })[character]);

export function diagramFigure(diagram, assets) {
  const picture = (theme) => `<picture class="lq-diagram-${theme}"><source media="(max-width: 1000px)" srcset="${escape(assets[theme].portrait)}" /><img src="${escape(assets[theme].landscape)}" alt="${escape(diagram.title)}" loading="lazy" decoding="async" /></picture>`;
  return `<figure class="lq-diagram" aria-label="${escape(diagram.title)}">
<figcaption><strong>${escape(diagram.title)}</strong></figcaption>
${picture('light')}
${picture('dark')}
<p class="lq-diagram-description">${escape(diagram.description)}</p>
<div class="lq-diagram-actions"><a class="lq-diagram-light" href="${escape(assets.light.landscape)}" target="_blank" rel="noopener">Open full-size diagram</a><a class="lq-diagram-dark" href="${escape(assets.dark.landscape)}" target="_blank" rel="noopener">Open full-size diagram</a>
<details data-pagefind-ignore><summary>Diagram source</summary><pre><code>${escape(diagram.source)}</code></pre></details></div>
</figure>`;
}

/** Replace only the opted-in code fences; other Markdown is untouched. */
export async function replaceDiagrams(markdown, render) {
  const lines = String(markdown).split('\n');
  const diagrams = findDiagrams(markdown);
  // Work backwards so each original line range remains valid.
  for (const diagram of [...diagrams].reverse()) {
    const assets = await render(diagram);
    lines.splice(diagram.start, diagram.end - diagram.start + 1, diagramFigure(diagram, assets));
  }
  return { markdown: lines.join('\n'), count: diagrams.length };
}

/** Defensive contract for the local renderer's output, not arbitrary SVG input. */
export function validateSvg(svg) {
  if (!/^<svg\b/.test(svg.trim()) || !/viewBox=/.test(svg)) throw new Error('renderer did not return an SVG with a viewBox');
  if (/<(?:script|foreignObject|iframe)\b|\bon\w+\s*=|(?:href\s*=\s*["']\s*(?:https?:|javascript:))|url\(\s*["']?https?:/i.test(svg)) {
    throw new Error('renderer returned active or remote SVG content');
  }
  for (const match of svg.matchAll(/\b(?:xlink:)?href\s*=\s*["']([^"']*)["']|url\(\s*([^)]+)\)/gi)) {
    const value = (match[1] ?? match[2]).trim().replace(/^["']|["']$/g, '');
    if (!value.startsWith('#')) throw new Error('renderer returned active or remote SVG content');
  }
  return svg;
}

/** SVG's percentage width has no useful intrinsic size when loaded as an img. */
export function intrinsicSvg(svg) {
  validateSvg(svg);
  const viewBox = /\bviewBox\s*=\s*["']([^"']+)["']/.exec(svg)?.[1]
    .trim().split(/[\s,]+/).map(Number);
  if (!viewBox || viewBox.length !== 4 || !viewBox.every(Number.isFinite)
    || viewBox[2] <= 0 || viewBox[3] <= 0) throw new Error('invalid diagram viewBox');
  return svg.trim().replace(/^<svg\b([^>]*)>/, (_match, attributes) => {
    const sized = attributes.replace(/\s(?:width|height)\s*=\s*["'][^"']*["']/g, '');
    return `<svg${sized} width="${Math.ceil(viewBox[2])}" height="${Math.ceil(viewBox[3])}">`;
  });
}
