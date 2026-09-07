/**
 * DE-232 — unit tests for the a11y severity ratchet (cypress/support/a11y-gate.ts).
 *
 * The Cypress spec (cypress/e2e/a11y.cy.ts) asserts `gateViolations(...)`
 * returns empty sets for every audited state; these tests prove, with
 * synthetic violations, that the ratchet actually fails what it must fail:
 *
 *   - a NEW critical violation gates even when a baseline entry exists for
 *     the same (route, rule) — critical has no baseline escape;
 *   - a NEW serious violation gates unless its (route, rule) is baselined;
 *   - moderate/minor never gate.
 */

import { describe, expect, it } from 'vitest';

import {
	gateViolations,
	isBaselined,
	type BaselineFile,
	type RecordedViolation
} from '../../../../cypress/support/a11y-gate';

function violation(overrides: Partial<RecordedViolation>): RecordedViolation {
	return {
		route: '/lq-ai/matters',
		rule: 'color-contrast',
		impact: 'serious',
		nodes: 1,
		help: 'help text',
		helpUrl: 'https://dequeuniversity.com/rules/axe/4.12/example',
		targets: ['main'],
		...overrides
	};
}

const emptyBaseline: BaselineFile = { comment: [], entries: [] };

function baselineWith(route: string, rule: string): BaselineFile {
	return {
		comment: [],
		entries: [{ route, rule, impact: 'serious', nodes: 1, note: 'test entry' }]
	};
}

describe('a11y gate — critical violations', () => {
	it('a critical violation gates against an empty baseline', () => {
		const v = violation({ rule: 'image-alt', impact: 'critical' });
		const gate = gateViolations([v], emptyBaseline);
		expect(gate.critical).toEqual([v]);
	});

	it('a critical violation gates EVEN IF (route, rule) is in the baseline — no escape', () => {
		const v = violation({ rule: 'button-name', impact: 'critical' });
		const gate = gateViolations([v], baselineWith(v.route, v.rule));
		expect(gate.critical).toEqual([v]);
	});
});

describe('a11y gate — serious violations ratchet against the baseline', () => {
	it('a serious violation NOT in the baseline gates', () => {
		const v = violation({ impact: 'serious' });
		const gate = gateViolations([v], emptyBaseline);
		expect(gate.newSerious).toEqual([v]);
		expect(gate.critical).toEqual([]);
	});

	it('a serious violation in the baseline passes (pre-existing, accepted)', () => {
		const v = violation({ impact: 'serious' });
		const gate = gateViolations([v], baselineWith(v.route, v.rule));
		expect(gate.newSerious).toEqual([]);
		expect(gate.critical).toEqual([]);
	});

	it('baseline matching is per-route: same rule on a different route still gates', () => {
		const v = violation({ route: '/lq-ai/knowledge', impact: 'serious' });
		const gate = gateViolations([v], baselineWith('/lq-ai/matters', v.rule));
		expect(gate.newSerious).toEqual([v]);
	});

	it('baseline matching distinguishes page states of the same route', () => {
		const v = violation({ route: '/lq-ai/matters [new-matter modal]', impact: 'serious' });
		const gate = gateViolations([v], baselineWith('/lq-ai/matters', v.rule));
		expect(gate.newSerious).toEqual([v]);
	});
});

describe('a11y gate — moderate/minor never gate', () => {
	it('moderate and minor violations are log-only', () => {
		const moderate = violation({ rule: 'meta-viewport', impact: 'moderate' });
		const minor = violation({ rule: 'region', impact: 'minor' });
		const gate = gateViolations([moderate, minor], emptyBaseline);
		expect(gate.critical).toEqual([]);
		expect(gate.newSerious).toEqual([]);
	});
});

describe('isBaselined', () => {
	it('matches on exact (route, rule) pairs only', () => {
		const b = baselineWith('/lq-ai/login', 'color-contrast');
		expect(isBaselined(b, '/lq-ai/login', 'color-contrast')).toBe(true);
		expect(isBaselined(b, '/lq-ai/login', 'list')).toBe(false);
		expect(isBaselined(b, '/lq-ai', 'color-contrast')).toBe(false);
	});
});
