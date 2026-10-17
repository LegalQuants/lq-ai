import { describe, it, expect } from 'vitest';
import {
	formatTimestamp,
	eventDescription,
	filterEvents,
	ALL_KINDS,
	KIND_ICONS,
	KIND_LABELS,
	KIND_DESCRIPTION
} from '../components/ReceiptsList.svelte';
import type { ReceiptEvent, ReceiptEventKind } from '../api/receipts';

describe('ReceiptsList helpers', () => {
	it('formatTimestamp returns HH:MM:SS', () => {
		expect(formatTimestamp('2026-05-12T10:14:00Z')).toMatch(/^\d\d:\d\d:\d\d$/);
	});

	it('eventDescription renders per-kind summaries', () => {
		expect(
			eventDescription({
				ts: 't',
				kind: 'inference',
				detail: { provider: 'anthropic', model: 'claude-opus-4-7', tier: 3 }
			})
		).toContain('anthropic');

		expect(
			eventDescription({
				ts: 't',
				kind: 'skill',
				detail: { skill_name: 'nda-review' }
			})
		).toContain('nda-review');

		expect(
			eventDescription({
				ts: 't',
				kind: 'retrieval',
				detail: { chunk_count: 5 }
			})
		).toContain('5 chunks');

		expect(
			eventDescription({
				ts: 't',
				kind: 'error',
				detail: { refusal_reason: 'tier_mismatch' }
			})
		).toContain('tier_mismatch');
	});

	it('filterEvents respects selectedKinds', () => {
		const events: ReceiptEvent[] = [
			{ ts: 't1', kind: 'message', detail: {} },
			{ ts: 't2', kind: 'audit', detail: {} },
			{ ts: 't3', kind: 'inference', detail: {} }
		];
		const result = filterEvents(events, ['message', 'audit']);
		expect(result).toHaveLength(2);
		expect(result.map((e) => e.kind)).toEqual(['message', 'audit']);
	});

	it('describes a local reference read without presenting it as citation evidence', () => {
		expect(eventDescription({ts:'t', kind:'audit', detail:{
			action:'skill.reference_read', provider:'built-in:fixture-skill', outcome:'executed'
		}})).toBe('Reference read — built-in:fixture-skill (executed)');
	});

	it('filterEvents returns empty when no kinds match', () => {
		const events: ReceiptEvent[] = [{ ts: 't', kind: 'message', detail: {} }];
		expect(filterEvents(events, ['audit', 'error'])).toHaveLength(0);
	});

	it('ALL_KINDS contains all 6 kinds', () => {
		expect(ALL_KINDS).toEqual(['message', 'inference', 'audit', 'skill', 'retrieval', 'error']);
	});

	it('KIND_ICONS maps each kind to an emoji', () => {
		expect(KIND_ICONS.message).toBe('👤');
		expect(KIND_ICONS.retrieval).toBe('📎');
		expect(KIND_ICONS.error).toBe('🛡');
	});

	it('KIND_LABELS maps each kind to a chip label', () => {
		expect(KIND_LABELS.retrieval).toBe('retrievals');
		expect(KIND_LABELS.error).toBe('errors');
	});

	it('KIND_DESCRIPTION provides a plain-English hover for every kind', () => {
		for (const kind of ALL_KINDS) {
			const desc = KIND_DESCRIPTION[kind as ReceiptEventKind];
			expect(desc).toBeTruthy();
			expect(desc.length).toBeGreaterThan(40);
			// Hover copy reads as a complete sentence.
			expect(desc.endsWith('.')).toBe(true);
		}
	});

	it('KIND_DESCRIPTION is distinct per kind', () => {
		const descriptions = ALL_KINDS.map((k) => KIND_DESCRIPTION[k as ReceiptEventKind]);
		expect(new Set(descriptions).size).toBe(ALL_KINDS.length);
	});
});
