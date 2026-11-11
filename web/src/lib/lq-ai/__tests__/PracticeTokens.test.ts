/**
 * The LQ.AI token values are ADR 0045's light theme (docs/adr/0045-lq-ai-shell-redesign.md).
 *
 * practice.css is the one place the palette lives, so these tests read it and
 * resolve each token the way a browser would (var() chains and
 * color-mix(in srgb, …)), then check:
 *   - the values against ADR 0045 §1 and §5;
 *   - the ADR's contrast table, recomputed from the shipped values;
 *   - that the ADR 0043 primitives' inline fallbacks (they render outside the
 *     shell by design) carry the same values as practice.css;
 *   - the system typeface and the absence of a shipped web font (§4);
 *   - pill buttons and the governance tone in the primitives.
 */
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { render } from 'svelte/server';

import LqButton from '../components/shared/LqButton.svelte';
import LqPill from '../components/shared/LqPill.svelte';
import LqAlert from '../components/shared/LqAlert.svelte';

const here = dirname(fileURLToPath(import.meta.url));
const lqRoot = resolve(here, '..');
const webRoot = resolve(lqRoot, '..', '..', '..');
const read = (p: string) => readFileSync(p, 'utf8');

function rootDeclarations(css: string): Map<string, string> {
	const body = css.replace(/\/\*[\s\S]*?\*\//g, '').match(/:root\s*\{([\s\S]*?)\n\}/);
	if (!body) throw new Error('no :root block');
	const map = new Map<string, string>();
	for (const m of body[1].matchAll(/(--lq-[\w-]+)\s*:\s*([^;]+);/g)) map.set(m[1], m[2].trim());
	return map;
}

const tokens = rootDeclarations(read(join(lqRoot, 'styles', 'practice.css')));

type Rgb = [number, number, number];

function hexToRgb(hex: string): Rgb {
	let h = hex.replace('#', '').toLowerCase();
	if (h.length === 3) h = [...h].map((c) => c + c).join('');
	return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as Rgb;
}
const rgbToHex = (c: Rgb) =>
	'#' + c.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');

/** Resolve a token to a final value: a hex for colours, the literal otherwise. */
function resolveToken(name: string, depth = 0): string {
	if (depth > 10) throw new Error(`var() cycle at ${name}`);
	const raw = tokens.get(name);
	if (raw === undefined) throw new Error(`${name} is not defined in practice.css`);
	return resolveValue(raw, depth);
}

function resolveValue(raw: string, depth = 0): string {
	const v = raw.trim();
	const alias = v.match(/^var\((--lq-[\w-]+)\)$/);
	if (alias) return resolveToken(alias[1], depth + 1);
	const mix = v.match(/^color-mix\(in srgb,\s*(.+?)\s+(\d+(?:\.\d+)?)%,\s*(.+)\)$/);
	if (mix) {
		const a = hexToRgb(resolveValue(mix[1], depth + 1));
		const b = hexToRgb(resolveValue(mix[3], depth + 1));
		const p = Number(mix[2]) / 100;
		return rgbToHex(a.map((x, i) => x * p + b[i] * (1 - p)) as Rgb);
	}
	if (/^#[0-9a-f]{3,6}$/i.test(v)) return rgbToHex(hexToRgb(v));
	return v;
}

function luminance(hex: string): number {
	const lin = hexToRgb(hex).map((c) => {
		const s = c / 255;
		return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}
function contrast(a: string, b: string): number {
	const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
	return (x + 0.05) / (y + 0.05);
}

describe('practice.css carries ADR 0045 light values', () => {
	it('sets the neutral, ink, governance and danger values of ADR 0045 §1', () => {
		const expected: Record<string, string> = {
			'--lq-canvas': '#ffffff',
			'--lq-inset': '#f9f9fa',
			'--lq-surface-muted': '#f1f1f3',
			'--lq-raised': '#ffffff',
			'--lq-selected': '#e9e9ec',
			'--lq-border': '#e4e4e7',
			'--lq-border-strong': '#80828a',
			'--lq-text': '#111114',
			'--lq-text-secondary': '#4f5158',
			'--lq-text-tertiary': '#65676f',
			'--lq-accent': '#111114',
			'--lq-on-accent': '#ffffff',
			'--lq-governance': '#a34a00',
			'--lq-danger': '#b42318'
		};
		for (const [name, value] of Object.entries(expected))
			expect(resolveToken(name), name).toBe(value);
	});

	it('makes info and warning neutral ink, moves the tier to governance and has no success colour', () => {
		for (const name of [
			'--lq-info',
			'--lq-warning',
			'--lq-warn',
			'--lq-success',
			'--lq-success-text'
		])
			expect(resolveToken(name), name).toBe(resolveToken('--lq-text'));
		for (const name of ['--lq-tier'])
			expect(resolveToken(name), name).toBe(resolveToken('--lq-governance'));
		expect(resolveToken('--lq-error')).toBe(resolveToken('--lq-danger'));
		expect(resolveToken('--lq-inset-secure')).toBe(resolveToken('--lq-surface-muted'));
		// --lq-surface stays white (ADR 0045 §1; the grey is --lq-surface-muted).
		expect(resolveToken('--lq-surface')).toBe('#ffffff');
	});

	it('uses no hue outside ink, governance orange and danger red', () => {
		for (const name of tokens.keys()) {
			const value = resolveToken(name);
			if (!value.startsWith('#')) continue;
			const [r, g, b] = hexToRgb(value);
			if (Math.max(r, g, b) - Math.min(r, g, b) <= 12) continue; // a neutral (cool) grey
			const raw = tokens.get(name) ?? '';
			const governanceOrDanger =
				['#a34a00', '#b42318'].includes(value) || /--lq-(governance|danger|tier|error)\b/.test(raw);
			expect(governanceOrDanger, `${name} = ${value} is a hue outside ADR 0045 §1`).toBe(true);
		}
	});

	it('sets the radii of ADR 0045 §5', () => {
		expect(resolveToken('--lq-radius-tile')).toBe('10px');
		expect(resolveToken('--lq-radius-input')).toBe('12px');
		expect(resolveToken('--lq-radius-card')).toBe('16px');
		expect(resolveToken('--lq-radius-list')).toBe('18px');
		expect(resolveToken('--lq-radius-composer')).toBe('24px');
		expect(resolveToken('--lq-radius-pill')).toBe('999px');
		// The 4, 6 and 8 px radii are replaced.
		for (const name of ['--lq-radius-sm', '--lq-radius', '--lq-radius-lg'])
			expect(['4px', '6px', '8px']).not.toContain(resolveToken(name));
	});
});

describe('contrast, recomputed from the shipped values (ADR 0045 §1)', () => {
	const surfaces = [
		'--lq-canvas',
		'--lq-inset',
		'--lq-surface-muted',
		'--lq-raised',
		'--lq-selected'
	];
	const texts = [
		'--lq-text',
		'--lq-text-secondary',
		'--lq-text-tertiary',
		'--lq-governance',
		'--lq-danger'
	];

	it('meets 4.5:1 for every text colour on every light surface', () => {
		for (const t of texts)
			for (const s of surfaces) {
				const ratio = contrast(resolveToken(t), resolveToken(s));
				expect(ratio, `${t} on ${s} = ${ratio.toFixed(2)}`).toBeGreaterThanOrEqual(4.5);
			}
	});

	it('meets 3:1 for field and control edges on every light surface', () => {
		for (const s of surfaces) {
			const ratio = contrast(resolveToken('--lq-border-strong'), resolveToken(s));
			expect(ratio, `--lq-border-strong on ${s} = ${ratio.toFixed(2)}`).toBeGreaterThanOrEqual(3);
		}
	});

	it('meets 4.5:1 for text on an ink fill and for each role on its own soft shade', () => {
		expect(
			contrast(resolveToken('--lq-on-accent'), resolveToken('--lq-accent'))
		).toBeGreaterThanOrEqual(4.5);
		for (const [fg, bg] of [
			['--lq-accent', '--lq-accent-soft'],
			['--lq-governance', '--lq-governance-soft'],
			['--lq-danger', '--lq-danger-soft'],
			['--lq-info', '--lq-info-soft'],
			['--lq-warning', '--lq-warning-soft']
		]) {
			const ratio = contrast(resolveToken(fg), resolveToken(bg));
			expect(ratio, `${fg} on ${bg} = ${ratio.toFixed(2)}`).toBeGreaterThanOrEqual(4.5);
		}
	});
});

describe('the ADR 0043 primitives follow practice.css', () => {
	const sharedDir = join(lqRoot, 'components', 'shared');
	const files: string[] = [];
	const walk = (dir: string) => {
		for (const name of readdirSync(dir)) {
			const p = join(dir, name);
			if (statSync(p).isDirectory()) walk(p);
			else if (/\.(svelte|ts)$/.test(name)) files.push(p);
		}
	};
	walk(sharedDir);

	it('carries inline fallbacks equal to the practice.css values', () => {
		let checked = 0;
		for (const file of files) {
			for (const m of read(file).matchAll(/var\((--lq-[\w-]+),\s*([^)]+)\)/g)) {
				const [, name, fallback] = m;
				// --lq-font-* live in typography.css; checked in the typeface block below.
				if (name.startsWith('--lq-font-')) continue;
				const want = fallback.trim().startsWith('#') ? resolveValue(fallback) : fallback.trim();
				expect(want, `${file}: ${name}`).toBe(resolveToken(name));
				checked++;
			}
		}
		expect(checked).toBeGreaterThan(50);
	});

	it('draws buttons as pills', () => {
		const button = read(join(sharedDir, 'LqButton.svelte'));
		const base = button.match(/\.lq-btn\s*\{([\s\S]*?)\}/);
		expect(base?.[1]).toContain('border-radius: var(--lq-radius-pill, 999px)');
	});

	it('styles a governance tone in every toned primitive and renders its class', () => {
		for (const [name, selector] of [
			['LqButton.svelte', '.lq-tone-governance.lq-btn-outline'],
			['LqPill.svelte', '.lq-pill-tone-governance'],
			['LqAlert.svelte', '.lq-alert-tone-governance'],
			['LqSwitch.svelte', ".lq-switch-tone-governance[data-state='checked']"]
		]) {
			const src = read(join(sharedDir, name));
			expect(src, name).toContain(selector);
			expect(src, name).toContain('var(--lq-governance, #a34a00)');
		}
		expect(render(LqButton, { props: { tone: 'governance' } }).body).toContain(
			'lq-tone-governance'
		);
		expect(render(LqPill, { props: { text: 'Tier 1', tone: 'governance' } }).body).toContain(
			'lq-pill-tone-governance'
		);
		expect(render(LqAlert, { props: { tone: 'governance' } }).body).toContain(
			'lq-alert-tone-governance'
		);
	});
});

describe('the system typeface (ADR 0045 §4)', () => {
	const typography = read(join(lqRoot, 'styles', 'typography.css'));
	const type = rootDeclarations(typography);

	it('uses the system stack and the ADR code stack', () => {
		expect(type.get('--lq-font-sans')).toBe(`-apple-system, 'SF Pro Text', 'Segoe UI', sans-serif`);
		expect(type.get('--lq-font-mono')).toBe(`ui-monospace, 'SF Mono', Menlo, Consolas, monospace`);
		expect(read(join(lqRoot, 'components', 'shared', 'LqText.svelte'))).toContain(
			`var(--lq-font-mono, ${type.get('--lq-font-mono')})`
		);
	});

	it('ships no web font', () => {
		expect(typography).not.toMatch(/@import|@font-face|Inter/);
		const pkg = JSON.parse(read(join(webRoot, 'package.json')));
		expect(Object.keys({ ...pkg.dependencies, ...pkg.devDependencies })).not.toContain(
			'@fontsource-variable/inter'
		);
	});
});
