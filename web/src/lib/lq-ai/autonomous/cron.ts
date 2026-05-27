/**
 * Pure cron helpers for the Schedules surface (M4-C2 Task 15).
 *
 * - presetToCron   — compiles a frequency preset + options into a 5-field cron string.
 * - nextRun        — returns the next matching minute after `from` for a standard
 *                    5-field cron expression. Advisory only — the backend validates
 *                    and 422s invalid/unsatisfiable expressions.
 *
 * Supports: '*', single integers, and comma-separated lists per field.
 * That covers all presets plus common custom expressions. Step syntax (e.g. slash-5)
 * is NOT supported; the UI labels the preview as advisory when the raw field
 * is in use.
 */

export type CronPreset = 'daily' | 'weekly' | 'monthly' | 'custom';

/** Compile a preset + params into a standard 5-field cron string. */
export function presetToCron(
	p: CronPreset,
	opts: { hour: number; minute: number; dow?: number; dom?: number }
): string {
	const { hour, minute, dow = 1, dom = 1 } = opts;
	switch (p) {
		case 'daily':
			return `${minute} ${hour} * * *`;
		case 'weekly':
			return `${minute} ${hour} * * ${dow}`;
		case 'monthly':
			return `${minute} ${hour} ${dom} * *`;
		case 'custom':
			return '';
	}
}

/**
 * Match a single cron field against a calendar value.
 *
 * Rules:
 *   - '*' always matches.
 *   - Comma-separated list: each token must be a parseable integer; if any
 *     token is non-numeric (e.g. a step like '* /5' or a range '1-5') the
 *     entire field is considered unsupported and returns false so nextRun
 *     returns null rather than silently mismatching.
 */
function matchField(field: string, value: number): boolean {
	if (field === '*') return true;
	const tokens = field.split(',');
	// Require all tokens to be non-empty pure integers (no ranges, no steps).
	for (const tok of tokens) {
		const trimmed = tok.trim();
		if (trimmed === '' || !/^-?\d+$/.test(trimmed)) return false;
	}
	return tokens.some((tok) => Number(tok.trim()) === value);
}

/**
 * Next run after `from` for a standard 5-field cron expression.
 *
 * Supports '*', single ints, and comma-separated int lists per field —
 * enough for all presets and common custom expressions.
 *
 * Returns null if:
 *   - The expression is not exactly 5 whitespace-separated fields.
 *   - Any field contains unsupported syntax (ranges, steps, non-numeric tokens).
 *   - No match is found within 366 days (366 * 24 * 60 minute iterations).
 */
export function nextRun(cron: string, from: Date = new Date()): Date | null {
	const parts = cron.trim().split(/\s+/);
	if (parts.length !== 5) return null;

	const [min, hr, dom, mon, dow] = parts;

	// Walk forward minute-by-minute from (from + 1 minute), capped at ~366 days.
	const d = new Date(from.getTime());
	d.setSeconds(0, 0);
	d.setMinutes(d.getMinutes() + 1);

	const limit = 366 * 24 * 60;
	for (let i = 0; i < limit; i++) {
		// matchField returns false for unsupported syntax → no match → null.
		if (
			matchField(min, d.getMinutes()) &&
			matchField(hr, d.getHours()) &&
			matchField(dom, d.getDate()) &&
			matchField(mon, d.getMonth() + 1) &&
			matchField(dow, d.getDay())
		) {
			return new Date(d.getTime());
		}
		d.setMinutes(d.getMinutes() + 1);
	}
	return null;
}
