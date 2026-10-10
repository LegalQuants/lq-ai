import { defineConfig } from 'cypress';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import {
	compareFindings,
	validateBaseline,
	validateBaselineUpdate,
	validateCoverage,
	type Baseline,
	type Finding
} from './cypress/support/a11y-gate';
import { stateIds } from './cypress/support/a11y-states';

const baselinePath = 'cypress/fixtures/a11y-baseline.json';
const reportPath = 'cypress/results/a11y-report.json';
export default defineConfig({
	video: false,
	screenshotsFolder: 'cypress/results/screenshots',
	retries: 0,
	e2e: {
		baseUrl: 'http://127.0.0.1:4173',
		specPattern: 'cypress/e2e/lq-ai-a11y.cy.ts',
		supportFile: 'cypress/support/a11y.ts',
		setupNodeEvents(on, config) {
			const capture = process.env.A11Y_CAPTURE_BASELINE === '1';
			if (capture && process.env.CI)
				throw new Error('Baseline capture is local-only; never a CI bypass');
			config.env.captureBaseline = capture;
			const axeVersion = JSON.parse(
				readFileSync('node_modules/axe-core/package.json', 'utf8')
			).version;
			const sourceSha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
			let baseline: Baseline | undefined;
			if (!capture) {
				baseline = validateBaseline(JSON.parse(readFileSync(baselinePath, 'utf8')));
				if (
					baseline.axeVersion !== axeVersion ||
					JSON.stringify(baseline.states) !== JSON.stringify(stateIds)
				)
					throw new Error('Baseline scanner/state matrix mismatch');
				if (process.env.GITHUB_EVENT_PATH && process.env.CI) {
					const event = JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'));
					const base = event.pull_request?.base?.sha ?? event.before;
					if (!/^[a-f0-9]{40}$/.test(base) || /^0+$/.test(base))
						throw new Error('Cannot establish baseline comparison base');
					execFileSync('git', ['cat-file', '-e', `${base}^{commit}`]);
					const path = 'web/' + baselinePath;
					const existing = execFileSync('git', ['ls-tree', '--name-only', base, '--', path], {
						encoding: 'utf8'
					}).trim();
					if (existing)
						validateBaselineUpdate(
							JSON.parse(execFileSync('git', ['show', `${base}:${path}`], { encoding: 'utf8' })),
							baseline
						);
					else if (baseline.sourceSha !== base)
						throw new Error('Initial baseline must be measured from the PR base');
				}
			}
			const audits: Array<{ state: string; findings: Finding[]; incompleteRules: string[] }> = [];
			const report = {
				schemaVersion: 1,
				sourceSha,
				axeVersion,
				expectedStates: stateIds,
				audits,
				status: 'not-completed',
				runnerFailures: 0,
				regressions: [] as Finding[],
				stale: [] as Finding[]
			};
			const save = () => {
				mkdirSync('cypress/results', { recursive: true });
				writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
			};
			on('before:run', save);
			on('task', {
				'a11y:record'(audit) {
					if (!stateIds.includes(audit.state) || audits.some((a) => a.state === audit.state))
						throw new Error('Unexpected/duplicate state');
					audits.push(audit);
					save();
					return null;
				}
			});
			on('after:run', (results) => {
				report.runnerFailures = 'totalFailed' in results ? results.totalFailed : 1;
				report.status = 'failed';
				save();
				validateCoverage(
					stateIds,
					audits.map((a) => a.state)
				);
				const findings = audits.flatMap((a) => a.findings);
				if (capture) {
					if (
						report.runnerFailures ||
						findings.some((f) => f.impact === 'critical' || f.impact === 'unknown')
					)
						throw new Error('Capture failed; critical/unknown findings cannot be accepted');
					const candidate = validateBaseline({
						schemaVersion: 1,
						sourceSha,
						axeVersion,
						states: stateIds,
						recordedAt: new Date().toISOString(),
						owner: '@houfu',
						reason:
							'Measured pre-existing noncritical findings on current main; source credit @SaifAlYounan #437',
						entries: findings
					});
					writeFileSync(
						'cypress/results/a11y-baseline.candidate.json',
						JSON.stringify(candidate, null, 2) + '\n'
					);
				} else {
					const comparison = compareFindings(findings, baseline!);
					report.regressions = comparison.regressions;
					report.stale = comparison.stale;
				}
				report.status =
					report.runnerFailures || report.regressions.length || report.stale.length
						? 'failed'
						: 'passed';
				save();
				if (report.status === 'failed')
					throw new Error(
						'Accessibility gate failed; inspect sanitized a11y-report.json (including stale exceptions to shrink)'
					);
			});
			return config;
		}
	}
});
