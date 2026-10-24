#!/usr/bin/env node
/**
 * Contrast gate for `src/styles/theme.css`.
 *
 * Accessibility is a gate, not a preference (mini-PRD Annex A; ADR 0028
 * requirement 4). pa11y-ci catches what a built page actually renders, but it
 * only sees the pairs that happen to appear on the pages that exist today. This
 * script checks the palette itself: every token pair that carries text, in both
 * themes, against its WCAG 2.1 AA floor.
 *
 * It reads the values out of theme.css rather than restating them, so the file
 * and the check cannot drift apart.
 *
 *   node scripts/theme-contrast.mjs        # table + exit 1 on any failure
 *
 * Labels, chips and badges are 12px or smaller, not "large text", so they are
 * held to 4.5:1 like body copy. Pairs that never carry text (hairlines, icons,
 * control borders) are held to the 3:1 non-text floor of SC 1.4.11.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { SITE_LAYOUT } from './lib/paths.mjs';

const THEME = fileURLToPath(new URL('../src/styles/theme.css', import.meta.url));
/**
 * The pathways layout (`SITE_LAYOUT=pathways`) loads a second stylesheet after
 * theme.css that redefines tokens in the same selectors. Reading both, in load
 * order, gives the values that layout renders with — so the same pairs are
 * checked against whichever palette is being built.
 */
const PATHWAYS_THEME = fileURLToPath(new URL('../src/styles/theme-pathways.css', import.meta.url));
const PATHWAYS = SITE_LAYOUT === 'pathways';

// ---------------------------------------------------------------- colour math

const toRgb = (value) => {
  const hex = value.trim().replace(/^#/, '');
  const full = hex.length === 3 ? [...hex].map((c) => c + c).join('') : hex;
  if (!/^[0-9a-f]{6}$/i.test(full)) throw new Error(`not a hex colour: ${value}`);
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
};

const luminance = (value) =>
  toRgb(value)
    .map((c) => c / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
    .reduce((acc, c, i) => acc + c * [0.2126, 0.7152, 0.0722][i], 0);

const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

// ------------------------------------------------------- read the token table

// Comments carry selector names in prose, so they go before anything is matched.
const css = [THEME, ...(PATHWAYS ? [PATHWAYS_THEME] : [])]
  .map((file) => readFileSync(file, 'utf8'))
  .join('\n')
  .replace(/\/\*[\s\S]*?\*\//g, '');

/**
 * Collect `--name: value` declarations per selector. Every rule whose selector
 * normalizes to the same string is merged, so tokens split across the shared
 * block, the typography block and the focus block all land together.
 */
const declarations = new Map();
for (const [, rawSelector, body] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
  const selector = rawSelector.trim().replace(/\s+/g, ' ');
  if (!declarations.has(selector)) declarations.set(selector, new Map());
  const tokens = declarations.get(selector);
  for (const [, name, value] of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    tokens.set(name, value.trim());
  }
}

function block(selector) {
  const tokens = declarations.get(selector);
  if (!tokens) throw new Error(`selector not found in theme.css: ${selector}`);
  return tokens;
}

/** Tokens that are the same in both themes. */
const shared = block(':root');
const themes = {
  light: block(":root[data-theme='light'], [data-theme='light'] ::backdrop"),
  dark: block(':root, ::backdrop'),
};

/** Resolve `var(--x)` chains down to a literal colour. */
function resolve(theme, name, seen = new Set()) {
  const raw = themes[theme].get(name) ?? shared.get(name);
  if (raw === undefined) throw new Error(`${theme}: token ${name} is not defined`);
  // `var(--x)` or `var(--x, var(--y))`: a fallback is what renders wherever
  // --x is not set in the stylesheet (the pathways accent is set per page).
  const ref = raw.match(/^var\((--[\w-]+)(?:,\s*var\((--[\w-]+)\))?\)$/);
  if (!ref) return raw;
  if (seen.has(name)) throw new Error(`${theme}: circular token ${name}`);
  seen.add(name);
  const defined = (token) => themes[theme].has(token) || shared.has(token);
  return resolve(theme, ref[2] && !defined(ref[1]) ? ref[2] : ref[1], seen);
}

// ------------------------------------------------------------- the pair table

/** [foreground token, background token, floor, what renders this pair] */
const TEXT_PAIRS = [
  ['--sl-color-white', '--sl-color-bg', 4.5, 'heading on page background'],
  ['--sl-color-white', '--lq-color-surface-raised', 4.5, 'heading on raised surface'],
  ['--sl-color-gray-1', '--sl-color-bg', 4.5, 'ink on page background'],
  ['--sl-color-text', '--sl-color-bg', 4.5, 'body text on page background'],
  ['--sl-color-text', '--lq-color-surface-raised', 4.5, 'body text on raised surface'],
  ['--sl-color-text', '--sl-color-bg-nav', 4.5, 'body text on the page bar'],
  ['--sl-color-text', '--sl-color-bg-inline-code', 4.5, 'inline code'],
  ['--sl-color-gray-3', '--sl-color-bg-sidebar', 4.5, 'sidebar link on sidebar'],
  ['--sl-color-gray-3', '--lq-color-control-bg', 4.5, 'search trigger text on the control surface'],
  ['--sl-color-white', '--lq-color-control-bg', 4.5, 'search trigger text, hovered'],
  ['--sl-color-gray-3', '--sl-color-bg', 4.5, 'muted text on page background'],
  ['--sl-color-gray-3', '--lq-color-surface-raised', 4.5, 'stamp / footer meta on surface'],
  ['--sl-color-gray-4', '--sl-color-bg', 4.5, 'label (12px) on page background'],
  ['--sl-color-gray-4', '--sl-color-bg-sidebar', 4.5, 'sidebar label / "Docs for agents" on sidebar'],
  ['--sl-color-gray-4', '--lq-color-surface-sunken', 4.5, 'label on the surface (search shortcut hint)'],
  ['--sl-color-gray-4', '--lq-color-surface-raised', 4.5, 'composer placeholder on raised surface'],
  ['--sl-color-text-accent', '--sl-color-bg', 4.5, 'link on page background'],
  ['--sl-color-text-accent', '--lq-color-surface-raised', 4.5, 'link on raised surface'],
  ['--sl-color-text-accent', '--sl-color-bg-sidebar', 4.5, 'link on sidebar'],
  ['--sl-color-text-invert', '--sl-color-bg-accent', 4.5, 'inverted text on an accent fill'],
  ['--sl-color-white', '--lq-color-sidebar-current-bg', 4.5, 'current sidebar item'],
  ['--lq-orange-text', '--sl-color-bg', 4.5, 'governance label on page background'],
  ['--sl-color-white', '--lq-color-surface-sunken', 4.5, 'question bubble / shaded table header row'],
  ['--sl-badge-default-text', '--sl-badge-default-bg', 4.5, 'kind badge (How-to, Explanation, Reference)'],
  ['--sl-color-gray-3', '--lq-color-surface-sunken', 4.5, 'kind chip under the page title'],
  ['--lq-status-draft-text', '--lq-status-draft-bg', 4.5, 'status chip: draft'],
  ['--lq-status-reviewed-text', '--lq-status-reviewed-bg', 4.5, 'status chip: reviewed / shipped / accepted'],
  ['--lq-status-moving-text', '--lq-status-moving-bg', 4.5, 'status chip: partial / proposed'],
  [
    '--lq-status-draft-text',
    '--lq-status-draft-bg',
    4.5,
    'status chip: scaffold / deferred / superseded / deprecated / rejected',
  ],
  ['--sl-color-gray-3', '--sl-color-bg', 4.5, 'audience chip label'],
  ['--sl-color-blue-high', '--sl-color-blue-low', 4.5, 'aside title: note'],
  ['--sl-color-white', '--sl-color-blue-low', 4.5, 'aside body: note'],
  ['--sl-color-green-high', '--sl-color-green-low', 4.5, 'aside title: tip'],
  ['--sl-color-white', '--sl-color-green-low', 4.5, 'aside body: tip'],
  ['--sl-color-orange-high', '--sl-color-orange-low', 4.5, 'aside title: caution'],
  ['--sl-color-white', '--sl-color-orange-low', 4.5, 'aside body: caution'],
  ['--sl-color-red-high', '--sl-color-red-low', 4.5, 'aside title: danger'],
  ['--sl-color-white', '--sl-color-red-low', 4.5, 'aside body: danger'],
];

/** Non-text: SC 1.4.11 holds these to 3:1 against the surface behind them. */
const UI_PAIRS = [
  ['--lq-accent', '--sl-color-bg', 3.0, 'focus ring on page background'],
  ['--lq-accent', '--lq-color-surface-raised', 3.0, 'focus ring on raised surface'],
  ['--lq-accent', '--sl-color-bg-sidebar', 3.0, 'focus ring on sidebar'],
  ['--sl-color-gray-4', '--sl-color-bg', 3.0, 'icon / control on page background'],
  ['--lq-orange', '--sl-color-bg', 3.0, 'governance mark (dot) on page background'],
  ['--lq-orange', '--sl-color-bg-sidebar', 3.0, 'governance mark (dot) on sidebar'],
  ['--lq-orange', '--lq-color-surface-raised', 3.0, 'governance mark (dot) on a card'],
  ['--lq-status-moving-line', '--sl-color-bg', 3.0, 'status chip: dashed in-motion outline'],
  ['--sl-color-blue', '--sl-color-blue-low', 3.0, 'aside rule: note'],
  ['--sl-color-green', '--sl-color-green-low', 3.0, 'aside rule: tip'],
  ['--sl-color-orange', '--sl-color-orange-low', 3.0, 'aside rule: caution'],
  ['--sl-color-red', '--sl-color-red-low', 3.0, 'aside rule: danger'],
];

/**
 * Pairs that must NOT be used. The orange mark as text on white measures
 * 3.58:1 — it is for dots and rules, and `--lq-orange-text` is the text tint.
 * The check is here so that a future "just use the mark" edit trips the gate
 * instead of shipping. Both layouts share the palette, so it runs in both.
 */
const FORBIDDEN = [['light', '--lq-orange', '--sl-color-bg', 4.5, 'orange mark as text on white']];

/**
 * The pathways layout's own pairs. A page's accent is one of three tones,
 * chosen per page; in the redesign all three are ink, and each is still
 * checked in every role the accent plays — headings and links on the page,
 * on raised surfaces and on the hover fill, and the inverted text of a filled
 * tab or button. Version B's landing cards keep a fill (ink) with inverted
 * titles.
 */
const PATHWAY_PAIRS = PATHWAYS
  ? [
      ...['a', 'b', 'c'].flatMap((tone) => [
        [
          `--lq-tone-${tone}`,
          '--sl-color-bg',
          4.5,
          `tone ${tone}: heading / link on page background`,
        ],
        [
          `--lq-tone-${tone}`,
          '--lq-color-surface-raised',
          4.5,
          `tone ${tone}: link on raised surface`,
        ],
        [`--lq-tone-${tone}`, '--lq-color-hover', 4.5, `tone ${tone}: link on hover surface`],
        ['--sl-color-text-invert', `--lq-tone-${tone}`, 4.5, `tone ${tone}: filled button text`],
        ['--lq-card-ink', `--lq-card-${tone}`, 4.5, `card ${tone}: Version B landing card title`],
      ]),
      ['--sl-color-white', '--lq-color-hover', 4.5, 'row / tab text on hover surface'],
      ['--sl-color-gray-3', '--sl-color-bg', 4.5, 'breadcrumb / intro on page background'],
    ]
  : [];

// ------------------------------------------------------------------ run them

let failures = 0;
const rows = [];

for (const theme of ['light', 'dark']) {
  for (const [fg, bg, floor, label] of [...TEXT_PAIRS, ...UI_PAIRS, ...PATHWAY_PAIRS]) {
    const fgValue = resolve(theme, fg);
    const bgValue = resolve(theme, bg);
    const ratio = contrast(fgValue, bgValue);
    const pass = ratio >= floor;
    if (!pass) failures++;
    rows.push([pass ? 'PASS' : 'FAIL', theme, ratio, floor, label, fgValue, bgValue]);
  }
}

for (const [theme, fg, bg, floor, label] of FORBIDDEN) {
  const fgValue = resolve(theme, fg);
  const bgValue = resolve(theme, bg);
  const ratio = contrast(fgValue, bgValue);
  const stillFails = ratio < floor;
  if (!stillFails) failures++;
  rows.push([
    stillFails ? 'PASS' : 'FAIL',
    theme,
    ratio,
    floor,
    `${label} — must stay below the floor`,
    fgValue,
    bgValue,
  ]);
}

for (const [verdict, theme, ratio, floor, label, fgValue, bgValue] of rows) {
  console.log(
    `${verdict}  ${theme.padEnd(5)}  ${ratio.toFixed(2).padStart(6)}:1  (min ${floor.toFixed(1)})  ` +
      `${label}  [${fgValue} on ${bgValue}]`
  );
}

console.log(
  failures === 0
    ? `\n${rows.length} pairs checked, all within WCAG 2.1 AA.`
    : `\n${failures} of ${rows.length} pairs are outside WCAG 2.1 AA.`
);

process.exit(failures === 0 ? 0 : 1);
