/** Immutable frontend/build inputs; standalone axe additions and unit tests are excluded. */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';

export const productPaths = [
	'web/src',
	'web/static',
	'web/svelte.config.js',
	'web/vite.config.ts',
	'web/tailwind.config.js',
	'web/postcss.config.js',
	'web/tsconfig.json'
];
const isTest = (path: string) => /(?:^|\/)__tests__\/|\.(?:test|spec)\.[^/]+$/.test(path);
function git(args: string[], cwd?: string): string {
	const root = execFileSync('git', ['rev-parse', '--show-toplevel'], {
		encoding: 'utf8',
		cwd
	}).trim();
	return execFileSync('git', args, { encoding: 'utf8', cwd: root });
}
function stable(value: unknown): string {
	if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
	if (value && typeof value === 'object')
		return (
			'{' +
			Object.keys(value)
				.sort()
				.map((key) => JSON.stringify(key) + ':' + stable((value as Record<string, unknown>)[key]))
				.join(',') +
			'}'
		);
	return JSON.stringify(value);
}
export function frontendFingerprint(ref: string, cwd?: string): string {
	if (!/^[a-f0-9]{40}$/.test(ref)) throw new Error('Expected an immutable frontend source SHA');
	const tree = git(['ls-tree', '-r', '-z', ref, '--', ...productPaths], cwd)
		.split('\0')
		.filter((row) => row && !isTest(row.split('\t')[1]))
		.join('\0');
	const pkg = JSON.parse(git(['show', `${ref}:web/package.json`], cwd));
	const lock = JSON.parse(git(['show', `${ref}:web/package-lock.json`], cwd));
	const frontendLock = Object.fromEntries(
		Object.entries(lock.packages as Record<string, { dev?: boolean }>).filter(
			([name]) => name && !['node_modules/axe-core', 'node_modules/cypress-axe'].includes(name)
		)
	);
	return createHash('sha256')
		.update(tree)
		.update(
			stable({
				version: pkg.version,
				dependencies: pkg.dependencies,
				type: pkg.type,
				buildDependencies: Object.fromEntries(
					Object.entries(pkg.devDependencies ?? {}).filter(
						([name]) => !['axe-core', 'cypress-axe'].includes(name)
					)
				),
				build: pkg.scripts?.build,
				pyodide: pkg.scripts?.['pyodide:fetch'],
				frontendLock
			})
		)
		.digest('hex');
}
export function assertBaselineSource(measured: string, base: string, cwd?: string): void {
	// Measurement must come from adopted base history, never an arbitrary PR commit.
	if (!/^[a-f0-9]{40}$/.test(measured) || !/^[a-f0-9]{40}$/.test(base))
		throw new Error('Invalid source SHA');
	git(['merge-base', '--is-ancestor', measured, base], cwd);
	if (frontendFingerprint(measured, cwd) !== frontendFingerprint(base, cwd))
		throw new Error('Frontend changed since the initial baseline; remeasure on current main');
}
export function assertCaptureSource(measured: string, head: string): void {
	if (frontendFingerprint(measured) !== frontendFingerprint(head))
		throw new Error('Capture frontend differs from the selected measurement source');
	git([
		'diff',
		'--exit-code',
		head,
		'--',
		...productPaths,
		':(exclude)**/__tests__/**',
		':(exclude)**/*.test.*',
		':(exclude)**/*.spec.*'
	]);
}
