/**
 * Plain-text formatting shared by the run helpers.
 *
 * Every function here returns a plain string and never markup. The components
 * render these strings with Svelte interpolation, which escapes them. Nothing in
 * `run/` may return HTML (ADR 0038 D2: model- and document-derived text is data).
 */

/** "1 task", "2 tasks". */
export function pluralise(count: number, one: string, many: string = `${one}s`): string {
	return `${count} ${count === 1 ? one : many}`;
}

/**
 * Look a server-supplied code up in a fixed table. Only the table's own keys
 * match, so a code such as `constructor` or `__proto__` finds nothing.
 */
export function own<T>(table: Record<string, T>, key: string | null | undefined): T | undefined {
	return typeof key === 'string' && Object.prototype.hasOwnProperty.call(table, key)
		? table[key]
		: undefined;
}

/** `probe_stamp` -> "Probe stamp". Empty input gives an empty string. */
export function humanise(code: string | null | undefined): string {
	const text = (code ?? '').replace(/[_\-.]+/g, ' ').trim();
	if (!text) return '';
	return text.charAt(0).toUpperCase() + text.slice(1);
}

const AMOUNT = /^(-?)(\d+)(?:\.(\d+))?$/;

/**
 * Format an API money value for display.
 *
 * The API sends Decimal fields as strings ("0.7434", "2.0000"). The figures are
 * allowances and charges, so up to four decimals are kept; trailing zeros are
 * dropped down to two ("2.0000" -> "$2.00", "0.0648" -> "$0.0648"). Done on the
 * string so no floating-point rounding is introduced. Digits beyond the fourth
 * decimal are cut, not rounded.
 */
export function formatUsd(value: string | number | null | undefined): string {
	if (value === null || value === undefined) return '—';
	let text = typeof value === 'number' ? String(value) : value.trim();
	if (text === '') return '—';
	let match = AMOUNT.exec(text);
	if (!match) {
		// Another numeric form, such as an exponent: try its fixed form once. A value
		// with no fixed form (1e21 and up) or no numeric meaning is shown as written.
		const parsed = Number(text);
		if (!Number.isFinite(parsed)) return text;
		text = parsed.toFixed(4);
		match = AMOUNT.exec(text);
		if (!match) return text;
	}
	const [, sign, whole, fraction = ''] = match;
	let decimals = fraction.slice(0, 4).replace(/0+$/, '');
	if (decimals.length < 2) decimals = decimals.padEnd(2, '0');
	return `${sign}$${whole}.${decimals}`;
}

/** 120 -> "2 minutes", 45 -> "45 seconds", 7200 -> "2 hours". */
export function formatDuration(seconds: number | null | undefined): string {
	if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
		return '—';
	}
	const whole = Math.round(seconds);
	if (whole >= 3600 && whole % 3600 === 0) return pluralise(whole / 3600, 'hour');
	if (whole >= 60 && whole % 60 === 0) return pluralise(whole / 60, 'minute');
	return pluralise(whole, 'second');
}

/** A date for display, or the input unchanged when it is not a date. */
export function formatDeadline(iso: string | null | undefined): string {
	if (!iso) return '—';
	const date = new Date(iso);
	return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

const MAX_VALUE_CHARS = 160;

/**
 * Render one value of a step's `summary` as text. Never throws: an unexpected
 * shape (a nested object, a cycle) is stringified and cut.
 */
export function formatValue(value: unknown): string {
	if (value === null || value === undefined) return '—';
	if (typeof value === 'string') return value;
	if (typeof value === 'number' || typeof value === 'bigint') return String(value);
	if (typeof value === 'boolean') return value ? 'yes' : 'no';
	let text: string;
	try {
		text = JSON.stringify(value) ?? String(value);
	} catch {
		text = String(value);
	}
	return text.length > MAX_VALUE_CHARS ? `${text.slice(0, MAX_VALUE_CHARS)}…` : text;
}
