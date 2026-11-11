/**
 * Boundary test: LQ.AI code must not import OpenWebUI code.
 *
 * ADR 0009 keeps the LQ.AI shell beside the OpenWebUI fork in one SvelteKit
 * app. The rebase runbook (§5.5) records the property that makes that cheap:
 * every `$lib` import under `src/lib/lq-ai` and `src/routes/lq-ai` points back
 * into `$lib/lq-ai`. The runbook re-measures it with a grep each quarter. This
 * test runs the same check on every PR, and widens it to relative and
 * root-absolute imports and to CSS `@import`, so a new coupling fails CI the day
 * it is written rather than being found at the next rebase.
 *
 * What counts as crossing the boundary: any import or `@import` from a file
 * under the LQ.AI roots whose target is a file outside those roots and inside
 * `web/`. Packages (`svelte`, `marked`, `node:fs`, …) and SvelteKit's own
 * aliases (`$app/*`, `$env/*`) are not the boundary and are allowed.
 *
 * Crossings that exist on purpose are listed in ALLOWED with a reason. The
 * list must stay exact: an entry that no longer matches anything fails the
 * test too, so it cannot go stale.
 */
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
/** `web/`, resolved from this file so the test does not depend on the cwd. */
const webRoot = resolve(here, '..', '..', '..', '..');
const roots = [join(webRoot, 'src', 'lib', 'lq-ai'), join(webRoot, 'src', 'routes', 'lq-ai')];
const scannedExtensions = new Set(['.svelte', '.ts', '.js', '.css', '.html']);

interface Allowed {
	/** Path relative to `web/`, with forward slashes. */
	file: string;
	/** The import specifier exactly as written in the file. */
	specifier: string;
	why: string;
}

const ALLOWED: readonly Allowed[] = [
	{
		file: 'src/lib/lq-ai/__tests__/a11y-gate.test.ts',
		specifier: '../../../../cypress/support/a11y-gate',
		why: "LQ.AI's own Cypress support module; the unit test exercises the accessibility gate"
	},
	{
		file: 'src/lib/lq-ai/__tests__/a11y-source.test.ts',
		specifier: '../../../../cypress/support/a11y-source',
		why: "LQ.AI's own Cypress support module; the unit test exercises baseline provenance"
	},
	{
		file: 'src/lib/lq-ai/__tests__/fixtures/design-primitives.html',
		specifier: '/src/tailwind.css',
		why: 'PR 282 local review harness; reproduces the global stylesheet the root wrapper loads'
	},
	{
		file: 'src/lib/lq-ai/__tests__/fixtures/design-primitives.html',
		specifier: '/src/app.css',
		why: 'PR 282 local review harness; reproduces the global stylesheet the root wrapper loads'
	}
];

interface Crossing {
	file: string;
	specifier: string;
}

/** ES `import … from '…'`, bare `import '…'`, and `export … from '…'`. */
const staticImport = /(?:^|[^\w$.])(?:import|export)\s*(?:[^'";]*?\bfrom\s*)?['"]([^'"\n]+)['"]/g;
/** `import('…')` */
const dynamicImport = /\bimport\s*\(\s*['"]([^'"\n]+)['"]\s*\)/g;
/** CSS `@import '…'` and `@import url('…')` */
const cssImport = /@import\s+(?:url\(\s*)?['"]([^'"\n]+)['"]/g;

function walk(dir: string, out: string[] = []): string[] {
	for (const name of readdirSync(dir)) {
		const full = join(dir, name);
		if (statSync(full).isDirectory()) {
			walk(full, out);
		} else if (scannedExtensions.has(extensionOf(name))) {
			out.push(full);
		}
	}
	return out;
}

function extensionOf(name: string): string {
	const dot = name.lastIndexOf('.');
	return dot === -1 ? '' : name.slice(dot);
}

function specifiersIn(source: string): string[] {
	const found: string[] = [];
	for (const pattern of [staticImport, dynamicImport, cssImport]) {
		for (const match of source.matchAll(pattern)) found.push(match[1]);
	}
	return found;
}

function isInsideRoots(absolutePath: string): boolean {
	return roots.some((root) => absolutePath === root || absolutePath.startsWith(root + sep));
}

function toPosix(path: string): string {
	return path.split(sep).join('/');
}

/**
 * Returns the crossing, or null when the specifier stays inside the LQ.AI
 * roots or names something that is not part of `web/` (a package, a SvelteKit
 * alias, a Node builtin).
 */
function crossingFor(file: string, specifier: string): Crossing | null {
	let target: string | null = null;
	if (specifier.startsWith('$lib/') || specifier === '$lib') {
		target = join(webRoot, 'src', 'lib', specifier.slice('$lib'.length));
	} else if (specifier.startsWith('$')) {
		return null; // $app/*, $env/*, $service-worker: SvelteKit, not OpenWebUI
	} else if (specifier.startsWith('.')) {
		target = resolve(dirname(file), specifier);
	} else if (specifier.startsWith('/')) {
		target = join(webRoot, specifier); // Vite root-absolute import
	} else {
		return null; // bare package or builtin
	}
	return isInsideRoots(target) ? null : { file: toPosix(relative(webRoot, file)), specifier };
}

describe('LQ.AI code stays inside the LQ.AI roots', () => {
	const files = roots.flatMap((root) => walk(root));
	const crossings: Crossing[] = [];
	for (const file of files) {
		for (const specifier of specifiersIn(readFileSync(file, 'utf8'))) {
			const crossing = crossingFor(file, specifier);
			if (crossing) crossings.push(crossing);
		}
	}

	it('scans the LQ.AI source tree', () => {
		expect(files.length).toBeGreaterThan(100);
	});

	it('imports nothing from OpenWebUI code', () => {
		const unexpected = crossings.filter(
			(c) => !ALLOWED.some((a) => a.file === c.file && a.specifier === c.specifier)
		);
		expect(unexpected, 'new import across the LQ.AI boundary; see ALLOWED for the rule').toEqual(
			[]
		);
	});

	it('keeps the allowlist exact', () => {
		const stale = ALLOWED.filter(
			(a) => !crossings.some((c) => c.file === a.file && c.specifier === a.specifier)
		);
		expect(stale, 'ALLOWED entry no longer matches a real import; remove it').toEqual([]);
	});
});
