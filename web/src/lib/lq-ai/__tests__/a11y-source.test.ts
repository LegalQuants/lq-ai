import { afterEach, describe, expect, it } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import {
	assertBaselineSource,
	baselineComparisonBase,
	frontendFingerprint
} from '../../../../cypress/support/a11y-source';
let dir: string;
function git(...args: string[]) {
	return execFileSync('git', args, { cwd: dir, encoding: 'utf8' }).trim();
}
function file(path: string, value: string) {
	const full = join(dir, path);
	mkdirSync(join(full, '..'), { recursive: true });
	writeFileSync(full, value);
}
function commit() {
	git('add', '.');
	git(
		'-c',
		'user.name=Fixture',
		'-c',
		'user.email=fixture@example.invalid',
		'-c',
		'commit.gpgsign=false',
		'commit',
		'--quiet',
		'-m',
		'Fixture'
	);
	return git('rev-parse', 'HEAD');
}
function setup() {
	dir = mkdtempSync(join(tmpdir(), 'a11y-source-'));
	git('init', '--quiet');
	file('web/src/page.svelte', '<h1>Hello</h1>');
	file(
		'web/package.json',
		JSON.stringify({
			version: '1',
			dependencies: { runtime: '1' },
			scripts: { build: 'vite build' }
		})
	);
	file(
		'web/package-lock.json',
		JSON.stringify({ packages: { 'node_modules/runtime': { version: '1' } } })
	);
	return commit();
}
afterEach(() => {
	if (dir) rmSync(dir, { recursive: true, force: true });
});

describe('Baseline comparison base', () => {
	function mergeFixture() {
		const oldBase = setup();
		git('checkout', '-q', '-b', 'pr');
		file('api/dependency.txt', 'dependency update');
		const head = commit();
		git('checkout', '-q', '-b', 'base', oldBase);
		file('web/cypress/fixtures/a11y-baseline.json', '{}');
		const base = commit();
		git(
			'-c',
			'user.name=Fixture',
			'-c',
			'user.email=fixture@example.invalid',
			'-c',
			'commit.gpgsign=false',
			'merge',
			'--no-ff',
			'--no-edit',
			head
		);
		return { oldBase, head, base, merge: git('rev-parse', 'HEAD') };
	}
	it('uses the tested merge base when the event predates baseline adoption', () => {
		const { oldBase, head, base, merge } = mergeFixture();
		const actual = baselineComparisonBase(
			{ pull_request: { head: { sha: head }, base: { sha: oldBase } } },
			merge,
			dir
		);
		expect(actual).toBe(base);
		expect(git('show', `${actual}:web/cypress/fixtures/a11y-baseline.json`)).toBe('{}');
		expect(() => assertBaselineSource(base, oldBase, dir)).toThrow();
	});
	it('rejects a different event head instead of accepting an unrelated merge', () => {
		const { oldBase, base, merge } = mergeFixture();
		expect(() =>
			baselineComparisonBase(
				{ pull_request: { head: { sha: oldBase }, base: { sha: base } } },
				merge,
				dir
			)
		).toThrow('Expected the tested PR merge');
	});
	it('rejects a head-only checkout for a pull request', () => {
		const { oldBase, head } = mergeFixture();
		expect(() =>
			baselineComparisonBase(
				{ pull_request: { head: { sha: head }, base: { sha: oldBase } } },
				head,
				dir
			)
		).toThrow('Expected the tested PR merge');
	});
	it('keeps push comparisons on the previous commit', () => {
		const before = setup();
		file('api/new.py', '# new');
		const head = commit();
		expect(baselineComparisonBase({ before }, head, dir)).toBe(before);
	});
	it('rejects an absent or all-zero push comparison base', () => {
		const head = setup();
		expect(() => baselineComparisonBase({}, head, dir)).toThrow('Cannot establish');
		expect(() => baselineComparisonBase({ before: '0'.repeat(40) }, head, dir)).toThrow(
			'Cannot establish'
		);
	});
});

describe('Initial baseline source provenance', () => {
	it('accepts a newer base with only docs, backend and test changes', () => {
		const before = setup();
		file('docs/PRD.md', 'new');
		file('api/app.py', 'new');
		file('web/src/__tests__/page.test.ts', 'new');
		const after = commit();
		expect(after).not.toBe(before);
		expect(() => assertBaselineSource(before, after, dir)).not.toThrow();
	});
	it('uses repository-root paths even when invoked from web/', () => {
		const before = setup();
		expect(frontendFingerprint(before, join(dir, 'web'))).toBe(frontendFingerprint(before, dir));
	});
	it('rejects a changed shared frontend component', () => {
		const before = setup();
		file('web/src/page.svelte', '<h1>Changed</h1>');
		const after = commit();
		expect(() => assertBaselineSource(before, after, dir)).toThrow('Frontend changed');
	});
	it('rejects changed production dependencies even without a source edit', () => {
		const before = setup();
		file(
			'web/package-lock.json',
			JSON.stringify({ packages: { 'node_modules/runtime': { version: '2' } } })
		);
		expect(() => assertBaselineSource(before, commit(), dir)).toThrow('Frontend changed');
	});
	it('ignores only accessibility-tool additions and unrelated script changes', () => {
		const before = setup();
		file(
			'web/package.json',
			JSON.stringify({
				version: '1',
				dependencies: { runtime: '1' },
				scripts: { build: 'vite build', test: 'new test' },
				devDependencies: { 'axe-core': '1' }
			})
		);
		file(
			'web/package-lock.json',
			JSON.stringify({
				packages: {
					'node_modules/runtime': { version: '1' },
					'node_modules/axe-core': { version: '1', dev: true }
				}
			})
		);
		expect(frontendFingerprint(commit(), dir)).toBe(frontendFingerprint(before, dir));
	});
	it('rejects a frontend build-tool change even if source is unchanged', () => {
		const before = setup();
		file(
			'web/package.json',
			JSON.stringify({
				version: '1',
				dependencies: { runtime: '1' },
				scripts: { build: 'vite build' },
				devDependencies: { vite: '2' }
			})
		);
		expect(() => assertBaselineSource(before, commit(), dir)).toThrow('Frontend changed');
	});
	it('rejects a changed locked compiler even when the manifest is unchanged', () => {
		setup();
		file(
			'web/package-lock.json',
			JSON.stringify({
				packages: {
					'node_modules/runtime': { version: '1' },
					'node_modules/vite': { version: '1', dev: true }
				}
			})
		);
		const before = commit();
		file(
			'web/package-lock.json',
			JSON.stringify({
				packages: {
					'node_modules/runtime': { version: '1' },
					'node_modules/vite': { version: '2', dev: true }
				}
			})
		);
		expect(() => assertBaselineSource(before, commit(), dir)).toThrow('Frontend changed');
	});
	it('rejects a measurement commit outside adopted base history', () => {
		const before = setup();
		file('docs/new.md', 'new');
		const after = commit();
		expect(() => assertBaselineSource(after, before, dir)).toThrow();
	});
});
