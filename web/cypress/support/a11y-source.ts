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

type BaselineEvent = {
	pull_request?: { head: { sha: string }; base: { sha: string } };
	before?: string;
};

/** Use the base actually tested by checkout's PR merge, even if the event is older. */
export function baselineComparisonBase(
	event: BaselineEvent,
	sourceSha: string,
	cwd?: string
): string {
	if (!/^[a-f0-9]{40}$/.test(sourceSha)) throw new Error('Invalid checkout SHA');
	let base = event.before;
	if (event.pull_request) {
		const head = event.pull_request.head.sha;
		if (!/^[a-f0-9]{40}$/.test(head)) throw new Error('Invalid PR head SHA');
		const parents = git(['rev-list', '--parents', '-n', '1', sourceSha], cwd).trim().split(/\s+/);
		// Default pull_request checkout is a two-parent merge: base first, PR head second.
		// Reject a head-only checkout or another merge rather than trusting an arbitrary ref.
		if (parents.length !== 3 || parents[0] !== sourceSha || parents[2] !== head)
			throw new Error('Expected the tested PR merge with the event head as its second parent');
		base = parents[1];
	}
	if (!base || !/^[a-f0-9]{40}$/.test(base) || /^0+$/.test(base))
		throw new Error('Cannot establish baseline comparison base');
	git(['cat-file', '-e', `${base}^{commit}`], cwd);
	return base;
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
