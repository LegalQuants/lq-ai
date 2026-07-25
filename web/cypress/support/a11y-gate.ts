/**
 * DE-232 — pure severity-ratchet logic for the a11y gate (a11y.cy.ts).
 *
 * Kept free of Cypress/axe imports so the gate semantics are unit-testable
 * in vitest (src/lib/lq-ai/__tests__/a11y-gate.test.ts) without a browser:
 *
 *   - impact "critical"         → gated, ALWAYS. No baseline escape.
 *   - impact "serious"          → gated unless the (route, rule) pair is in
 *                                 the checked-in baseline
 *                                 (cypress/a11y-baseline.json).
 *   - impact "moderate"/"minor" → never gated; logged to the report only.
 */

export interface BaselineEntry {
	/** Audited state id, e.g. "/lq-ai/matters" or "/lq-ai/matters [new-matter modal]". */
	route: string;
	/** axe rule id, e.g. "color-contrast". */
	rule: string;
	/** Impact at the time the entry was recorded (informational). */
	impact: string;
	/** Node count at recording time (informational; matching is by route+rule). */
	nodes: number;
	/** Why this entry exists / when it was accepted. */
	note: string;
}

export interface BaselineFile {
	comment: string[];
	entries: BaselineEntry[];
}

export interface RecordedViolation {
	route: string;
	rule: string;
	impact: string;
	nodes: number;
	help: string;
	helpUrl: string;
	targets: string[];
}

export function isBaselined(baseline: BaselineFile, route: string, rule: string): boolean {
	return baseline.entries.some((e) => e.route === route && e.rule === rule);
}

/**
 * The severity ratchet. Given everything recorded for one audited state and
 * the baseline, return the violations that must fail the run.
 */
export function gateViolations(
	forRoute: RecordedViolation[],
	baseline: BaselineFile
): { critical: RecordedViolation[]; newSerious: RecordedViolation[] } {
	return {
		critical: forRoute.filter((v) => v.impact === 'critical'),
		newSerious: forRoute.filter(
			(v) => v.impact === 'serious' && !isBaselined(baseline, v.route, v.rule)
		)
	};
}
