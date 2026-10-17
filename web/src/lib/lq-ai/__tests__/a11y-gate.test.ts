import { describe, expect, it } from 'vitest';
import {
	compareFindings,
	validateBaseline,
	validateBaselineUpdate,
	validateCoverage,
	fingerprint,
	type Baseline,
	type Finding
} from '../../../../cypress/support/a11y-gate';

const finding = (patch: Partial<Finding> = {}): Finding => ({
	state: 'login/desktop/light',
	rule: 'color-contrast',
	impact: 'serious',
	target: ['#label'],
	count: 1,
	...patch
});
const baseline = (entries: Finding[] = []): Baseline => ({
	schemaVersion: 1,
	sourceSha: 'a'.repeat(40),
	axeVersion: '4.14.0',
	states: ['login/desktop/light'],
	recordedAt: '2026-10-10T00:00:00Z',
	owner: 'maintainer',
	reason: 'Measured existing findings',
	entries
});
describe('Exact accessibility exceptions', () => {
	it.each(['critical', 'serious', 'moderate', 'minor', 'unknown'] as const)(
		'rejects a new %s violation',
		(impact) => {
			expect(compareFindings([finding({ impact })], baseline()).regressions).toHaveLength(1);
		}
	);
	it('permits only the measured exact noncritical finding', () => {
		expect(compareFindings([finding()], baseline([finding()])).regressions).toEqual([]);
	});
	it('rejects a new node under an already-exempted route/rule', () => {
		const observed = [finding(), finding({ target: ['#new-label'] })];
		expect(compareFindings(observed, baseline([finding()])).regressions).toEqual([observed[1]]);
	});
	it('does not offset a new node with an old node disappearing', () => {
		expect(
			compareFindings([finding({ target: ['#replacement'] })], baseline([finding()])).regressions
		).toHaveLength(1);
	});
	it('rejects growth in duplicate multiplicity', () => {
		expect(
			compareFindings([finding(), finding()], baseline([finding()])).regressions[0].count
		).toBe(2);
	});
	it.each(['login/phone/light', 'login/desktop/dark', 'matters/desktop/light'])(
		'distinguishes %s',
		(state) => {
			expect(compareFindings([finding({ state })], baseline([finding()])).regressions).toHaveLength(
				1
			);
		}
	);
	it('preserves complete frame/shadow target paths and selector whitespace', () => {
		expect(fingerprint(finding({ target: [['iframe', '#field']] }))).not.toBe(
			fingerprint(finding({ target: ['iframe', '#field'] }))
		);
		expect(fingerprint(finding({ target: ['[title="a  b"]'] }))).not.toBe(
			fingerprint(finding({ target: ['[title="a b"]'] }))
		);
	});
	it('rejects an impact change on an existing target', () => {
		expect(
			compareFindings([finding({ impact: 'critical' })], baseline([finding()])).regressions
		).toHaveLength(1);
	});
	it('flags fixed exceptions for removal', () => {
		expect(compareFindings([], baseline([finding()])).stale).toHaveLength(1);
	});
	it.each([0, -1, 1.5, NaN])('rejects invalid counts (%s)', (count) => {
		expect(() => validateBaseline(baseline([finding({ count })]))).toThrow();
	});
	it.each(['critical', 'unknown'] as const)('does not allow %s baseline entries', (impact) => {
		expect(() => validateBaseline(baseline([finding({ impact })]))).toThrow();
	});
	it('rejects duplicate fingerprints and foreign states', () => {
		expect(() => validateBaseline(baseline([finding(), finding()]))).toThrow();
		expect(() => validateBaseline(baseline([finding({ state: 'foreign' })]))).toThrow();
	});
	it('rejects malformed metadata/targets', () => {
		expect(() => validateBaseline({ ...baseline(), sourceSha: 'old' })).toThrow();
		expect(() => validateBaseline(baseline([finding({ target: [] })]))).toThrow();
		expect(() => validateBaseline(baseline([finding({ target: [['']] })]))).toThrow();
	});
	it('enforces shrink-only updates', () => {
		expect(() =>
			validateBaselineUpdate(baseline([finding({ count: 2 })]), baseline([finding()]))
		).not.toThrow();
		expect(() =>
			validateBaselineUpdate(baseline([finding()]), baseline([finding({ count: 2 })]))
		).toThrow();
		expect(() =>
			validateBaselineUpdate(baseline([finding()]), baseline([finding({ target: ['#new'] })]))
		).toThrow();
		expect(() =>
			validateBaselineUpdate(baseline(), { ...baseline(), axeVersion: 'new' })
		).toThrow();
	});
	it('requires every state, including zero-violation states, exactly once', () => {
		expect(() => validateCoverage(['a', 'b'], ['a', 'b'])).not.toThrow();
		for (const actual of [[], ['a'], ['a', 'a'], ['a', 'b', 'c']])
			expect(() => validateCoverage(['a', 'b'], actual)).toThrow();
	});
});
