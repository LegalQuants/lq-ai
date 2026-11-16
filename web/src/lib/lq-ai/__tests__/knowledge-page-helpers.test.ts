/**
 * Unit tests for the helpers exported from
 * `routes/lq-ai/knowledge/+page.svelte` <script context="module">.
 *
 * Pattern matches AttachKBModal.test.ts: no @testing-library/svelte; we
 * exercise the pure decision functions and trust the Svelte template to
 * compose them correctly. The status roll-up is the load-bearing logic
 * for the spec's `✓ indexed / ⏳ indexing / ⚠ failed` pill — getting it
 * wrong shows the wrong badge on every card on the page.
 */
import { describe, expect, it } from 'vitest';
import {
	kbListStatus,
	kbStatusIcon,
	kbStatusLabel,
	type KBListStatus,
	type StatusIcon
} from '../../../routes/lq-ai/knowledge/+page.svelte';
import type { KnowledgeBase } from '../types';

function makeKB(overrides: Partial<KnowledgeBase> = {}): KnowledgeBase {
	return {
		id: 'kb-default',
		name: 'Default KB',
		owner_id: 'u1',
		hybrid_alpha: 0.5,
		file_count: 0,
		chunk_count: 0,
		created_at: '2026-05-01T00:00:00Z',
		updated_at: '2026-05-01T00:00:00Z',
		...overrides
	};
}

describe('kbListStatus', () => {
	it('returns "indexed" when ingestion_status is ready', () => {
		expect(kbListStatus(makeKB({ ingestion_status: 'ready' }))).toBe('indexed');
	});

	it('returns "failed" when ingestion_status is failed', () => {
		expect(kbListStatus(makeKB({ ingestion_status: 'failed' }))).toBe('failed');
	});

	it('returns "indexing" while pending or processing', () => {
		expect(kbListStatus(makeKB({ ingestion_status: 'pending' }))).toBe('indexing');
		expect(kbListStatus(makeKB({ ingestion_status: 'processing' }))).toBe('indexing');
	});

	it('falls back to "empty" when no files attached and no rollup status', () => {
		expect(kbListStatus(makeKB({ file_count: 0, chunk_count: 0 }))).toBe('empty');
	});

	it('falls back to "indexed" when chunks present and no rollup status', () => {
		expect(
			kbListStatus(makeKB({ file_count: 3, chunk_count: 200 }))
		).toBe('indexed');
	});

	it('falls back to "indexing" when files present but no chunks yet', () => {
		expect(
			kbListStatus(makeKB({ file_count: 2, chunk_count: 0 }))
		).toBe('indexing');
	});
});

describe('kbStatusLabel', () => {
	it('renders the spec-mandated indicators', () => {
		const cases: Array<[KBListStatus, string]> = [
			['indexed', 'indexed'],
			['indexing', 'indexing'],
			['failed', 'failed'],
			['empty', 'empty']
		];
		for (const [status, expected] of cases) {
			expect(kbStatusLabel(status)).toBe(expected);
		}
	});

	it('pairs each status with an icon instead of a glyph (ADR 0045 §5, WCAG 1.4.1)', () => {
		const cases: Array<[KBListStatus, StatusIcon]> = [
			['indexed', 'check'],
			['indexing', 'hourglass'],
			['failed', 'warning'],
			['empty', null]
		];
		for (const [s, icon] of cases) expect(kbStatusIcon(s), s).toBe(icon);
	});
});
