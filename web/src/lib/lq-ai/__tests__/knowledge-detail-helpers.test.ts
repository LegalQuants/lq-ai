/**
 * Unit tests for the helpers exported from
 * `routes/lq-ai/knowledge/[id]/+page.svelte` <script context="module">.
 *
 * Pattern matches knowledge-page-helpers.test.ts: pure helpers exported
 * from the module-level script + tested without @testing-library/svelte.
 */
import { describe, expect, it } from 'vitest';
import {
	docStatusLabel,
	effectiveStatus,
	effectiveFailureReason,
	formatBytes,
	sortFiles,
	type DocStatus
} from '../../../routes/lq-ai/knowledge/[id]/+page.svelte';
import type { KnowledgeBaseFile, IngestionStatus } from '../types';

function makeFile(
	overrides: Partial<KnowledgeBaseFile> = {}
): KnowledgeBaseFile {
	return {
		id: 'f-default',
		owner_id: 'u1',
		filename: 'doc.pdf',
		mime_type: 'application/pdf',
		size_bytes: 100,
		hash_sha256: 'abc',
		ingestion_status: 'ready' as IngestionStatus,
		created_at: '2026-05-01T00:00:00Z',
		attached_at: '2026-05-01T00:00:00Z',
		...overrides
	};
}

describe('docStatusLabel', () => {
	it('renders the spec-mandated indicators', () => {
		const cases: Array<[DocStatus, string]> = [
			['ready', '✓ ready'],
			['processing', '⏳ processing'],
			['pending', '⏳ pending'],
			['failed', '⚠ failed'],
			// M3-0.3 / DE-276: post-parse embed states
			['embed_failed', '⚠ embed failed'],
			['partial', '⚠ partial embed']
		];
		for (const [s, expected] of cases) {
			expect(docStatusLabel(s)).toBe(expected);
		}
	});
});

describe('effectiveStatus (M3-0.3 / DE-276)', () => {
	it('passes through non-ready file-level statuses unchanged', () => {
		expect(effectiveStatus(makeFile({ ingestion_status: 'failed' }))).toBe('failed');
		expect(effectiveStatus(makeFile({ ingestion_status: 'processing' }))).toBe('processing');
		expect(effectiveStatus(makeFile({ ingestion_status: 'pending' }))).toBe('pending');
	});

	it('escalates ready+embed_failed to embed_failed (the doc-level signal wins)', () => {
		const file = makeFile({ ingestion_status: 'ready', ingest_status: 'embed_failed' });
		expect(effectiveStatus(file)).toBe('embed_failed');
	});

	it('escalates ready+partial to partial', () => {
		const file = makeFile({ ingestion_status: 'ready', ingest_status: 'partial' });
		expect(effectiveStatus(file)).toBe('partial');
	});

	it('reports ready when both signals are healthy', () => {
		expect(effectiveStatus(makeFile({ ingestion_status: 'ready', ingest_status: 'ok' }))).toBe(
			'ready'
		);
		// document-row absent (parse pipeline mid-flight) still renders as ready when
		// the file-level signal is ready — defensive but the realistic case is the
		// embed worker has not yet been triggered.
		expect(
			effectiveStatus(makeFile({ ingestion_status: 'ready', ingest_status: null }))
		).toBe('ready');
	});
});

describe('effectiveFailureReason', () => {
	it('returns ingestion_error for file-level failed', () => {
		const file = makeFile({ ingestion_status: 'failed', ingestion_error: 'parse_failed' });
		expect(effectiveFailureReason(file)).toBe('parse_failed');
	});

	it('returns ingest_failure_reason for embed_failed', () => {
		const file = makeFile({
			ingestion_status: 'ready',
			ingest_status: 'embed_failed',
			ingest_failure_reason: 'gateway unreachable'
		});
		expect(effectiveFailureReason(file)).toBe('gateway unreachable');
	});

	it('returns ingest_failure_reason for partial', () => {
		const file = makeFile({
			ingestion_status: 'ready',
			ingest_status: 'partial',
			ingest_failure_reason: 'batch 2 of 3 failed'
		});
		expect(effectiveFailureReason(file)).toBe('batch 2 of 3 failed');
	});

	it('returns null for healthy rows', () => {
		expect(effectiveFailureReason(makeFile({ ingestion_status: 'ready' }))).toBeNull();
	});
});

describe('formatBytes', () => {
	it('renders bytes', () => {
		expect(formatBytes(0)).toBe('0 B');
		expect(formatBytes(512)).toBe('512 B');
	});
	it('renders KB / MB with binary divisor', () => {
		expect(formatBytes(1024)).toBe('1.0 KB');
		expect(formatBytes(1024 * 100)).toBe('100 KB');
		expect(formatBytes(1024 * 1024)).toBe('1.0 MB');
		expect(formatBytes(1024 * 1024 * 1024 * 5)).toBe('5.0 GB');
	});
	it('handles invalid input', () => {
		expect(formatBytes(NaN)).toBe('—');
		expect(formatBytes(-1)).toBe('—');
	});
});

describe('sortFiles', () => {
	it('orders ready first, processing/pending next, failed last', () => {
		const files = [
			makeFile({ id: 'a', filename: 'a.pdf', ingestion_status: 'failed' }),
			makeFile({ id: 'b', filename: 'b.pdf', ingestion_status: 'ready' }),
			makeFile({ id: 'c', filename: 'c.pdf', ingestion_status: 'processing' }),
			makeFile({ id: 'd', filename: 'd.pdf', ingestion_status: 'ready' }),
			makeFile({ id: 'e', filename: 'e.pdf', ingestion_status: 'pending' })
		];
		const sorted = sortFiles(files).map((f) => f.id);
		expect(sorted).toEqual(['b', 'd', 'c', 'e', 'a']);
	});

	it('orders embed_failed / partial between in-flight and parse-failed', () => {
		const files = [
			makeFile({ id: 'a', filename: 'a.pdf', ingestion_status: 'failed' }),
			makeFile({
				id: 'b',
				filename: 'b.pdf',
				ingestion_status: 'ready',
				ingest_status: 'embed_failed'
			}),
			makeFile({
				id: 'c',
				filename: 'c.pdf',
				ingestion_status: 'ready',
				ingest_status: 'partial'
			}),
			makeFile({ id: 'd', filename: 'd.pdf', ingestion_status: 'ready' })
		];
		const sorted = sortFiles(files).map((f) => f.id);
		// Healthy → partial → embed_failed → parse failed.
		expect(sorted).toEqual(['d', 'c', 'b', 'a']);
	});

	it('does not mutate the input array', () => {
		const files = [
			makeFile({ id: 'z', filename: 'z.pdf', ingestion_status: 'failed' }),
			makeFile({ id: 'a', filename: 'a.pdf', ingestion_status: 'ready' })
		];
		const before = files.map((f) => f.id);
		sortFiles(files);
		expect(files.map((f) => f.id)).toEqual(before);
	});
});
