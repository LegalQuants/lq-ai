import { describe, it, expect } from 'vitest';
import { ledgerEntryState, gateBadge } from '../ledger-state';
import type { LedgerGate } from '../../types';

describe('ledgerEntryState', () => {
	it('maps verbatim methods to green states', () => {
		expect(ledgerEntryState('exact_match')).toBe('verified-exact');
		expect(ledgerEntryState('tolerant_match')).toBe('verified-tolerant');
	});
	it('maps judge/ensemble methods to paraphrase (amber)', () => {
		for (const s of ['paraphrase_judge', 'ensemble_strict', 'ensemble_majority']) {
			expect(ledgerEntryState(s)).toBe('verified-paraphrase');
		}
	});
	it('maps unverified/failed/provenance/unknown to unverified', () => {
		for (const s of ['unverified', 'failed', 'provenance', 'something_new']) {
			expect(ledgerEntryState(s)).toBe('unverified');
		}
	});
});

describe('gateBadge', () => {
	const base: Omit<LedgerGate, 'gate_status'> = {
		message_id: 'm1',
		pass_count: 2,
		supported_count: 1,
		fail_count: 1,
		total_assertions: 4,
		confidence: 0.9,
		created_at: 't'
	};
	it('returns null for undefined', () => {
		expect(gateBadge(undefined)).toBeNull();
	});
	it('maps each verdict to a tone + label', () => {
		expect(gateBadge({ ...base, gate_status: 'fiduciary_grade' })?.tone).toBe('sage');
		expect(gateBadge({ ...base, gate_status: 'supported_only' })?.tone).toBe('amber');
		expect(gateBadge({ ...base, gate_status: 'flagged' })?.tone).toBe('red');
		expect(gateBadge({ ...base, gate_status: 'flagged' })?.label).toBeTruthy();
	});
});
