import { afterEach, describe, expect, it } from 'vitest';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { assertBaselineSource, frontendFingerprint } from '../../../../cypress/support/a11y-source';
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
