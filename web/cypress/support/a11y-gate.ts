/**
 * Exact DE-232 exceptions, reimplemented from the design proposed by
 * @SaifAlYounan in LegalQuants/lq-ai#437. No route/rule-wide exemptions.
 */
export type Impact = 'critical' | 'serious' | 'moderate' | 'minor' | 'unknown';
export type Target = (string | string[])[];
export interface Finding {
	state: string;
	rule: string;
	impact: Impact;
	target: Target;
	count: number;
}
export interface Baseline {
	schemaVersion: 1;
	sourceSha: string;
	axeVersion: string;
	states: string[];
	recordedAt: string;
	owner: string;
	reason: string;
	entries: Finding[];
}
export function fingerprint(f: Pick<Finding, 'state' | 'rule' | 'target'>): string {
	return JSON.stringify([f.state, f.rule, f.target]);
}
function validFinding(value: unknown): value is Finding {
	const f = value as Finding;
	return (
		!!f &&
		typeof f.state === 'string' &&
		!!f.state &&
		typeof f.rule === 'string' &&
		!!f.rule &&
		['critical', 'serious', 'moderate', 'minor', 'unknown'].includes(f.impact) &&
		Number.isSafeInteger(f.count) &&
		f.count > 0 &&
		Array.isArray(f.target) &&
		f.target.length > 0 &&
		f.target.every((x) =>
			typeof x === 'string'
				? !!x.trim()
				: Array.isArray(x) && x.length > 0 && x.every((s) => typeof s === 'string' && !!s.trim())
		)
	);
}
export function validateBaseline(value: unknown): Baseline {
	const b = value as Baseline;
	if (
		!b ||
		b.schemaVersion !== 1 ||
		!/^[a-f0-9]{40}$/.test(b.sourceSha) ||
		typeof b.axeVersion !== 'string' ||
		!b.axeVersion ||
		typeof b.recordedAt !== 'string' ||
		!Number.isFinite(Date.parse(b.recordedAt)) ||
		typeof b.owner !== 'string' ||
		!b.owner ||
		typeof b.reason !== 'string' ||
		!b.reason ||
		!Array.isArray(b.states) ||
		!b.states.length ||
		!b.states.every((s) => typeof s === 'string' && !!s) ||
		new Set(b.states).size !== b.states.length ||
		!Array.isArray(b.entries)
	)
		throw new Error('Invalid accessibility baseline metadata');
	const seen = new Set<string>();
	for (const f of b.entries) {
		if (
			!validFinding(f) ||
			!b.states.includes(f.state) ||
			f.impact === 'critical' ||
			f.impact === 'unknown'
		)
			throw new Error('Invalid baseline finding');
		const key = fingerprint(f);
		if (seen.has(key)) throw new Error('Duplicate baseline fingerprint');
		seen.add(key);
	}
	return b;
}
export function compareFindings(findings: Finding[], value: unknown) {
	const baseline = validateBaseline(value);
	const actual = new Map<string, Finding>();
	for (const f of findings) {
		if (!validFinding(f)) throw new Error('Invalid observed finding');
		const key = fingerprint(f),
			prior = actual.get(key);
		if (prior && prior.impact !== f.impact) throw new Error('Inconsistent observed impact');
		actual.set(key, { ...f, count: f.count + (prior?.count ?? 0) });
	}
	const allowed = new Map(baseline.entries.map((f) => [fingerprint(f), f]));
	const regressions = [...actual.values()].filter((f) => {
		const old = allowed.get(fingerprint(f));
		return (
			f.impact === 'critical' ||
			f.impact === 'unknown' ||
			!old ||
			old.impact !== f.impact ||
			f.count > old.count
		);
	});
	const stale = baseline.entries.filter((f) => (actual.get(fingerprint(f))?.count ?? 0) < f.count);
	return { regressions, stale };
}
export function validateBaselineUpdate(previous: unknown, current: unknown): void {
	const before = validateBaseline(previous),
		after = validateBaseline(current);
	if (
		before.axeVersion !== after.axeVersion ||
		JSON.stringify(before.states) !== JSON.stringify(after.states)
	)
		throw new Error('Scanner/matrix changes need a separate baseline policy decision');
	const old = new Map(before.entries.map((f) => [fingerprint(f), f]));
	for (const f of after.entries) {
		const prior = old.get(fingerprint(f));
		if (!prior || prior.impact !== f.impact || f.count > prior.count)
			throw new Error('Baseline exceptions may only shrink');
	}
}
export function validateCoverage(expected: string[], actual: string[]): void {
	if (
		actual.length !== expected.length ||
		new Set(actual).size !== actual.length ||
		expected.some((s) => !actual.includes(s))
	)
		throw new Error('Incomplete/duplicate accessibility state inventory');
}
