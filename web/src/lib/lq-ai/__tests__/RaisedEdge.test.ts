/**
 * Raised surfaces keep an edge in dark.
 *
 * ADR 0045 §1: "light keeps a soft shadow on raised surfaces; dark has none."
 * Every shadow mixes `--lq-shadow-ink`, which is transparent in dark. A dialog
 * that relied on its shadow alone, on a fill that is the page's colour, would
 * then have nothing but the dimmed page behind it to mark where it ends.
 *
 * `--lq-raised-edge` is that missing edge: transparent in light, the border
 * colour in dark, drawn as a one-pixel ring so nothing changes size:
 *
 *     box-shadow: <the shadow>, 0 0 0 1px var(--lq-raised-edge);
 *
 * The rule this test keeps: a style rule that draws a shadow and has no border
 * of its own carries the ring. It reads `.svelte` and `.css` files under
 * `src/lib/lq-ai` and `src/routes/lq-ai`, outside `__tests__/`.
 *
 * What it cannot see: a dialog with neither shadow nor border. The one that
 * exists today (`TierFloorOverrideModal`) is named below.
 */
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(here, '..', '..', '..', '..');
const roots = [join(webRoot, 'src', 'lib', 'lq-ai'), join(webRoot, 'src', 'routes', 'lq-ai')];
const practice = readFileSync(
	join(webRoot, 'src', 'lib', 'lq-ai', 'styles', 'practice.css'),
	'utf8'
);

function walk(dir: string, out: string[] = []): string[] {
	for (const name of readdirSync(dir)) {
		if (name === '__tests__') continue;
		const path = join(dir, name);
		if (statSync(path).isDirectory()) walk(path, out);
		else if (/\.(svelte|css)$/.test(name)) out.push(path);
	}
	return out;
}

type Rule = { file: string; selector: string; body: string };

function rulesOf(file: string, src: string): Rule[] {
	const css = file.endsWith('.svelte')
		? [...src.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]).join('\n')
		: src;
	const clean = css.replace(/\/\*[\s\S]*?\*\//g, '');
	return [...clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
		file: relative(webRoot, file).split('\\').join('/'),
		selector: m[1].trim().replace(/\s+/g, ' '),
		body: m[2]
	}));
}

const hasShadow = (body: string) => /box-shadow\s*:[^;]*--lq-shadow-ink/.test(body);
const hasBorder = (body: string) => /(?<![\w-])border(?:-color|-width|-style)?\s*:/.test(body);
const hasEdge = (body: string) => /box-shadow\s*:[^;]*0 0 0 1px var\(--lq-raised-edge\)/.test(body);

const allRules = roots.flatMap((root) =>
	walk(root).flatMap((file) => rulesOf(file, readFileSync(file, 'utf8')))
);

function block(selector: string): string {
	const start = practice.indexOf(selector);
	expect(start, `${selector} block`).toBeGreaterThan(-1);
	return practice.slice(start, practice.indexOf('}', start));
}

describe('raised surfaces keep an edge in dark (ADR 0045 §1)', () => {
	it('defines the edge as clear in light and as the border colour in dark', () => {
		expect(block(':root {')).toMatch(/--lq-raised-edge:\s*transparent;/);
		const dark = block(":root[data-lq-theme='dark']");
		expect(dark).toMatch(/--lq-raised-edge:\s*var\(--lq-border\);/);
		// The reason the edge is needed: dark removes every shadow.
		expect(dark).toMatch(/--lq-shadow-ink:\s*transparent;/);
	});

	it('finds the shadowed rules it is meant to check', () => {
		expect(allRules.filter((rule) => hasShadow(rule.body)).length).toBeGreaterThanOrEqual(15);
	});

	it('gives every shadowed rule without a border the edge', () => {
		const missing = allRules
			.filter((rule) => hasShadow(rule.body) && !hasBorder(rule.body) && !hasEdge(rule.body))
			.map((rule) => `${rule.file}: ${rule.selector}`);
		expect(missing).toEqual([]);
	});

	it('keeps the edge on the dialog that has neither a shadow nor a border', () => {
		const rule = allRules.find(
			(r) => r.file.endsWith('components/TierFloorOverrideModal.svelte') && r.selector === '.modal'
		);
		expect(rule, 'TierFloorOverrideModal .modal').toBeDefined();
		expect(hasBorder(rule!.body)).toBe(false);
		expect(rule!.body).toMatch(/box-shadow\s*:\s*0 0 0 1px var\(--lq-raised-edge\)/);
	});

	it('reads borders and edges the way the rule needs', () => {
		expect(hasBorder('border: 1px solid var(--lq-border);')).toBe(true);
		expect(hasBorder('border-color: var(--lq-accent);')).toBe(true);
		expect(hasBorder('border-radius: 12px; border-top: 0;')).toBe(false);
		expect(
			hasShadow('box-shadow: 0 1px 2px color-mix(in srgb, var(--lq-shadow-ink) 5%, transparent);')
		).toBe(true);
		expect(hasShadow('box-shadow: 0 0 0 1px var(--lq-raised-edge);')).toBe(false);
		expect(
			hasEdge(
				'box-shadow:\n\t0 24px 64px color-mix(in srgb, var(--lq-shadow-ink) 18%, transparent),\n\t0 0 0 1px var(--lq-raised-edge);'
			)
		).toBe(true);
		expect(
			hasEdge('box-shadow: 0 24px 64px color-mix(in srgb, var(--lq-shadow-ink) 18%, transparent);')
		).toBe(false);
	});
});
