/**
 * Plain-text formatting shared by the run helpers: counts, codes, money, durations,
 * dates and the values of a step's summary. Every function returns a string.
 */
import { describe, expect, it } from 'vitest';

import {
	formatDeadline,
	formatDuration,
	formatUsd,
	formatValue,
	humanise,
	own,
	pluralise
} from '../format';
import { run } from './fixtures';

describe('pluralise', () => {
	it('says one of a thing in the singular and every other count in the plural', () => {
		expect(pluralise(1, 'task')).toBe('1 task');
		expect(pluralise(0, 'task')).toBe('0 tasks');
		expect(pluralise(2, 'task')).toBe('2 tasks');
		expect(pluralise(8, 'document')).toBe('8 documents');
	});

	it('takes the plural it is given', () => {
		expect(pluralise(1, 'quotation')).toBe('1 quotation');
		expect(pluralise(3, 'index', 'indices')).toBe('3 indices');
		expect(pluralise(1, 'index', 'indices')).toBe('1 index');
	});
});

describe('own', () => {
	const table = { known: 'a sentence', empty: '' };

	it('finds what the table holds', () => {
		expect(own(table, 'known')).toBe('a sentence');
		expect(own(table, 'empty')).toBe('');
	});

	it('finds nothing for a code the table does not hold, however it is spelled', () => {
		expect(own(table, 'unknown')).toBeUndefined();
		expect(own(table, 'KNOWN')).toBeUndefined();
		expect(own(table, '')).toBeUndefined();
	});

	it('finds nothing for a missing or odd key', () => {
		for (const key of [null, undefined, 7, {}, []] as unknown[]) {
			expect(own(table, key as string), String(JSON.stringify(key))).toBeUndefined();
		}
	});

	it('does not mistake what every object has for something the table holds', () => {
		for (const key of [
			'constructor',
			'__proto__',
			'toString',
			'hasOwnProperty',
			'valueOf',
			'isPrototypeOf'
		]) {
			expect(own(table, key), key).toBeUndefined();
		}
	});
});

describe('humanise', () => {
	it('turns a code into a short phrase', () => {
		expect(humanise('probe_stamp')).toBe('Probe stamp');
		expect(humanise('waiting_children')).toBe('Waiting children');
		expect(humanise('read-document')).toBe('Read document');
		expect(humanise('tool.not.granted')).toBe('Tool not granted');
		expect(humanise('step_2')).toBe('Step 2');
	});

	it('collapses and trims separators', () => {
		expect(humanise('__a___b__')).toBe('A b');
		expect(humanise('  spaced out  ')).toBe('Spaced out');
	});

	it('leaves an already readable phrase alone', () => {
		expect(humanise('Done')).toBe('Done');
		expect(humanise('already fine')).toBe('Already fine');
	});

	it('is empty for nothing', () => {
		for (const code of ['', '   ', '_', '-_.', null, undefined]) {
			expect(humanise(code), String(code)).toBe('');
		}
	});
});

describe('formatUsd', () => {
	it.each([
		['2.0000', '$2.00'],
		['0.7434', '$0.7434'],
		['0.0648', '$0.0648'],
		['0.0000', '$0.00'],
		['0', '$0.00'],
		['10', '$10.00'],
		['1.5', '$1.50'],
		['0.10', '$0.10'],
		['3.4686', '$3.4686'],
		['1234.5678', '$1234.5678'],
		['-0.5', '-$0.50']
	])('%s is %s', (value, shown) => {
		expect(formatUsd(value)).toBe(shown);
	});

	it('keeps up to four decimals and drops trailing zeros down to two', () => {
		expect(formatUsd('0.1200')).toBe('$0.12');
		expect(formatUsd('0.1230')).toBe('$0.123');
		expect(formatUsd('0.1234')).toBe('$0.1234');
	});

	it('cuts digits beyond the fourth decimal and does not round them', () => {
		expect(formatUsd('0.12999')).toBe('$0.1299');
		expect(formatUsd('1.99999')).toBe('$1.9999');
		expect(formatUsd('0.00009')).toBe('$0.00');
	});

	it('does the same for a number, without floating-point noise', () => {
		expect(formatUsd(2)).toBe('$2.00');
		expect(formatUsd(0.7434)).toBe('$0.7434');
		expect(formatUsd(0.1 + 0.2)).toBe('$0.30');
		expect(formatUsd(1e-7)).toBe('$0.00');
	});

	it('reads a value written another way', () => {
		expect(formatUsd('1e3')).toBe('$1000.00');
		expect(formatUsd('.5')).toBe('$0.50');
		expect(formatUsd('+5')).toBe('$5.00');
		expect(formatUsd('  3.1 ')).toBe('$3.10');
	});

	it('shows a dash for an amount that is not there, which is not the same as zero', () => {
		for (const value of [null, undefined, '']) expect(formatUsd(value)).toBe('—');
		expect(formatUsd('0')).toBe('$0.00');
	});

	it('shows what it cannot read as it was sent, rather than as zero or as NaN', () => {
		expect(formatUsd('abc')).toBe('abc');
		expect(formatUsd('1,000.50')).toBe('1,000.50');
		expect(formatUsd('n/a')).toBe('n/a');
	});

	it('words every amount in the recorded runs as money', () => {
		const recorded = run('documents.completed');
		const amounts = [
			recorded.spent_usd,
			recorded.reserved_usd,
			recorded.planning.budget_usd,
			recorded.planning.root_allowance_usd,
			recorded.planning.planning_allowance_usd,
			...recorded.tree!.plan.children.map((child) => child.budget_usd),
			...recorded.effects.map((effect) => effect.charged_usd)
		];
		for (const amount of amounts)
			expect(formatUsd(amount), String(amount)).toMatch(/^\$\d+\.\d{2,4}$/);
	});

	it('shows a blank or whitespace-only value as a dash, as it does for an empty one', () => {
		for (const value of [' ', '  ', '\t', '\n', ' \r\n\t ', ' ']) {
			expect(formatUsd(value), JSON.stringify(value)).toBe('—');
		}
		// Padding around an amount is not blankness.
		expect(formatUsd(' 0 ')).toBe('$0.00');
	});

	// `toFixed(4)` gives the exponent form again for 1e21 and up, which is not an amount: the value
	// is shown as it is, and the formatter does not call itself for ever.
	it('shows a number with no fixed form as it is, and does not recurse on it', () => {
		for (const value of [1e21, '1e21', '1E21', 1e22, -1e21, '-1e21']) {
			expect(() => formatUsd(value), String(value)).not.toThrow();
			expect(formatUsd(value), String(value)).toMatch(/^-?1e\+?2[12]$/i);
		}
		expect(formatUsd('1e400')).toBe('1e400');
		expect(formatUsd('-1e400')).toBe('-1e400');
		expect(formatUsd(Number.MAX_VALUE)).toMatch(/^1\.797\d*e\+308$/);
	});

	it('always gives a string and never throws, whatever it is given', () => {
		const odd: (string | number)[] = [
			1e21,
			1e308,
			Number.MAX_VALUE,
			Number.MIN_VALUE,
			Number.NaN,
			Number.POSITIVE_INFINITY,
			Number.NEGATIVE_INFINITY,
			'Infinity',
			'-Infinity',
			'NaN',
			'1_000',
			'12abc',
			'$5',
			'5 USD',
			'١٢٣',
			'9'.repeat(400),
			'0.'.padEnd(400, '9'),
			'<img src=x onerror=alert(1)>'
		];
		for (const value of odd) {
			expect(() => formatUsd(value), String(value).slice(0, 20)).not.toThrow();
			const shown = formatUsd(value);
			expect(typeof shown).toBe('string');
			expect(shown.length).toBeGreaterThan(0);
		}
		expect(formatUsd('Infinity')).toBe('Infinity');
		expect(formatUsd(Number.NaN)).toBe('NaN');
	});
});

describe('formatDuration', () => {
	it.each([
		[1, '1 second'],
		[45, '45 seconds'],
		[60, '1 minute'],
		[90, '90 seconds'],
		[120, '2 minutes'],
		[300, '5 minutes'],
		[3600, '1 hour'],
		[5400, '90 minutes'],
		[7200, '2 hours'],
		[0, '0 seconds']
	])('%s seconds is %s', (seconds, shown) => {
		expect(formatDuration(seconds)).toBe(shown);
	});

	it('rounds to a whole second first', () => {
		expect(formatDuration(59.6)).toBe('1 minute');
		expect(formatDuration(120.4)).toBe('2 minutes');
	});

	it('words the attempt limits the profiles record', () => {
		expect(formatDuration(120)).toBe('2 minutes');
		expect(formatDuration(300)).toBe('5 minutes');
	});

	it('shows a dash for a length of time that is not there or makes no sense', () => {
		for (const seconds of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY, -1]) {
			expect(formatDuration(seconds)).toBe('—');
		}
	});
});

describe('formatDeadline', () => {
	it('shows a dash when there is no deadline', () => {
		for (const value of [null, undefined, '']) expect(formatDeadline(value)).toBe('—');
	});

	it('shows a timestamp as a date and time for the reader, not as it was sent', () => {
		const iso = run('documents.awaiting-approval').tree!.plan.deadline;
		const shown = formatDeadline(iso);
		expect(shown).not.toBe(iso);
		// In the reader's own locale and time zone, whatever those are where the test runs.
		expect(shown).toBe(new Date(iso).toLocaleString());
	});

	it('gives back what is not a date as it was sent', () => {
		expect(formatDeadline('not a date')).toBe('not a date');
		expect(formatDeadline('soon')).toBe('soon');
	});
});

describe('formatValue', () => {
	it('shows a dash for nothing', () => {
		expect(formatValue(null)).toBe('—');
		expect(formatValue(undefined)).toBe('—');
	});

	it('shows text as it is, however long, and keeps an empty string empty', () => {
		expect(formatValue('note-terms.md')).toBe('note-terms.md');
		expect(formatValue('x'.repeat(500))).toBe('x'.repeat(500));
		expect(formatValue('')).toBe('');
	});

	it('shows numbers as digits and booleans as yes or no', () => {
		expect(formatValue(3)).toBe('3');
		expect(formatValue(0)).toBe('0');
		expect(formatValue(2.5)).toBe('2.5');
		expect(formatValue(10n)).toBe('10');
		expect(formatValue(true)).toBe('yes');
		expect(formatValue(false)).toBe('no');
	});

	it('shows a structure as compact JSON', () => {
		expect(formatValue({ a: [1, 2] })).toBe('{"a":[1,2]}');
		expect(formatValue([1, 'two', null])).toBe('[1,"two",null]');
	});

	it('cuts a structure that is too long, after 160 characters, and marks the cut', () => {
		// {"a":"…"} is the value plus eight characters.
		const exact = formatValue({ a: 'x'.repeat(152) });
		expect(exact).toHaveLength(160);
		expect(exact.endsWith('…')).toBe(false);
		const over = formatValue({ a: 'x'.repeat(153) });
		expect(over).toHaveLength(161);
		expect(over.endsWith('…')).toBe(true);
		expect(over.slice(0, 160)).toBe(JSON.stringify({ a: 'x'.repeat(153) }).slice(0, 160));
	});

	it('does not throw on a value that cannot be written as JSON, or on one that points back at itself', () => {
		const cyclic: Record<string, unknown> = {};
		cyclic.self = cyclic;
		expect(() => formatValue(cyclic)).not.toThrow();
		expect(() => formatValue({ big: 10n })).not.toThrow();
		expect(() => formatValue(Symbol('x'))).not.toThrow();
		expect(() => formatValue(() => 1)).not.toThrow();
		expect(typeof formatValue(cyclic)).toBe('string');
		expect(formatValue(Symbol('x'))).toBe('Symbol(x)');
	});

	it('cuts a function’s source too, rather than printing all of it', () => {
		const long = new Function(`return '${'y'.repeat(400)}';`);
		expect(formatValue(long).length).toBeLessThanOrEqual(161);
	});
});
