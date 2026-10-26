// Production-bundle browser checks; no API/compose/model process is started.
import { spawn, type ChildProcess } from 'node:child_process';
import { readFileSync, rmSync, copyFileSync } from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';

const mode = process.argv[2] ?? 'gate';
if (!['gate', 'capture', 'proof'].includes(mode))
	throw new Error('Expected gate, capture or proof');
if (mode === 'capture' && process.env.CI)
	throw new Error('Baseline capture is never allowed in CI');
rmSync('cypress/results/a11y-report.json', { force: true });
const server = spawn(
	'node',
	[
		'node_modules/vite/bin/vite.js',
		'preview',
		'--host',
		'127.0.0.1',
		'--port',
		'4173',
		'--strictPort'
	],
	{ stdio: 'inherit' }
);
let browser: ChildProcess | undefined;
const stop = () => {
	browser?.kill('SIGTERM');
	server.kill('SIGTERM');
};
process.on('SIGINT', () => {
	stop();
	process.exit(130);
});
process.on('SIGTERM', () => {
	stop();
	process.exit(143);
});
try {
	let ready = false;
	for (let i = 0; i < 120; i++) {
		if (server.exitCode !== null) throw new Error('Preview server exited before readiness');
		try {
			if ((await fetch('http://127.0.0.1:4173/lq-ai/login')).ok) {
				ready = true;
				break;
			}
		} catch {
			/* Preview may still be starting. */
		}
		await delay(500);
	}
	if (!ready) throw new Error('Preview readiness timed out');
	browser = spawn(
		'node',
		[
			'node_modules/cypress/bin/cypress',
			'run',
			'--config-file',
			'cypress.a11y.config.ts',
			...(mode === 'proof' ? ['--env', 'injectViolation=true'] : [])
		],
		{
			stdio: 'inherit',
			env: { ...process.env, A11Y_CAPTURE_BASELINE: mode === 'capture' ? '1' : '0' }
		}
	);
	const code = await new Promise<number | null>((resolve, reject) => {
		browser!.on('error', reject);
		browser!.on('exit', resolve);
	});
	if (mode === 'proof') {
		const report = JSON.parse(readFileSync('cypress/results/a11y-report.json', 'utf8'));
		const injected = report.regressions.some(
			(f: { rule: string; target: (string | string[])[] }) =>
				f.rule === 'button-name' && f.target.flat().some((t) => t.includes('a11y-negative-probe'))
		);
		if (
			code === null ||
			code === 0 ||
			!injected ||
			report.runnerFailures !== 1 ||
			report.regressions.length !== 1 ||
			report.stale.length !== 0
		)
			throw new Error('Negative proof did not reject the injected unnamed button');
		console.log('Negative proof passed: new unnamed button made the accessibility job fail.');
	} else if (code !== 0) throw new Error(`Cypress accessibility run failed (exit ${code})`);

	copyFileSync('cypress/results/a11y-report.json', `cypress/results/a11y-${mode}-report.json`);
} finally {
	stop();
}
