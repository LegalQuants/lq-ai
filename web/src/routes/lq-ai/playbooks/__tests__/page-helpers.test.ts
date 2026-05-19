import { describe, it, expect } from 'vitest';

import { sortPlaybooksByName, formatVersion } from '../page-helpers';
import type { Playbook } from '$lib/lq-ai/types';

const mkPlaybook = (overrides: Partial<Playbook>): Playbook => ({
	id: overrides.id ?? 'p',
	name: overrides.name ?? 'p',
	contract_type: overrides.contract_type ?? 'NDA',
	description: '',
	version: overrides.version ?? '1.0.0',
	created_by: null,
	created_at: '2026-05-18T00:00:00Z',
	updated_at: '2026-05-18T00:00:00Z',
	positions: []
});

describe('sortPlaybooksByName', () => {
	it('sorts case-insensitively', () => {
		const out = sortPlaybooksByName([
			mkPlaybook({ name: 'banana' }),
			mkPlaybook({ name: 'Apple' }),
			mkPlaybook({ name: 'cherry' })
		]);
		expect(out.map((p) => p.name)).toEqual(['Apple', 'banana', 'cherry']);
	});

	it('does not mutate the input array', () => {
		const input = [mkPlaybook({ name: 'b' }), mkPlaybook({ name: 'a' })];
		const out = sortPlaybooksByName(input);
		expect(input.map((p) => p.name)).toEqual(['b', 'a']);
		expect(out.map((p) => p.name)).toEqual(['a', 'b']);
	});
});

describe('formatVersion', () => {
	it('prefixes a v', () => {
		expect(formatVersion('1.0.0')).toBe('v1.0.0');
	});
	it('handles empty / null versions gracefully', () => {
		expect(formatVersion('')).toBe('');
	});
});
