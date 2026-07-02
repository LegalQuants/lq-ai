/**
 * Regression tests for the chat-attach-file-context bugfix.
 *
 * Convention note: matches the ChatPanel-slash-detect.test.ts pattern —
 * pure helpers are exported from <script context="module"> in the .svelte
 * file and exercised here without mounting the (large) component, since
 * @testing-library/svelte is unavailable for this file (see that test's
 * header for the full rationale).
 *
 * Covers two fixes:
 *   - Attached chat files never reached the model because sendMessage()
 *     never included file_ids in the request body. fileIdsForSend() is
 *     the extracted mapping.
 *   - The attached-file status badge stayed frozen at "pending" forever
 *     because nothing re-fetched ingestion_status after upload.
 *     hasPendingFileStatus() is the extracted predicate the polling loop
 *     keys off.
 */
import { describe, expect, it } from 'vitest';

import { hasPendingFileStatus, fileIdsForSend } from '../components/ChatPanel.svelte';
import type { FileMeta } from '../types';

function makeFile(overrides: Partial<FileMeta> = {}): FileMeta {
	return {
		id: 'file-1',
		owner_id: 'user-1',
		filename: 'contract.pdf',
		mime_type: 'application/pdf',
		size_bytes: 1024,
		ingestion_status: 'pending',
		created_at: '2026-01-01T00:00:00Z',
		...overrides
	};
}

describe('hasPendingFileStatus', () => {
	it('returns false for an empty file list', () => {
		expect(hasPendingFileStatus([])).toBe(false);
	});

	it('returns true when a file is pending', () => {
		expect(hasPendingFileStatus([makeFile({ ingestion_status: 'pending' })])).toBe(true);
	});

	it('returns true when a file is processing', () => {
		expect(hasPendingFileStatus([makeFile({ ingestion_status: 'processing' })])).toBe(true);
	});

	it('returns false when all files are ready', () => {
		expect(hasPendingFileStatus([makeFile({ ingestion_status: 'ready' })])).toBe(false);
	});

	it('returns false when all files are failed', () => {
		expect(hasPendingFileStatus([makeFile({ ingestion_status: 'failed' })])).toBe(false);
	});

	it('returns true if any file among several is still pending', () => {
		const files = [
			makeFile({ id: 'a', ingestion_status: 'ready' }),
			makeFile({ id: 'b', ingestion_status: 'pending' }),
			makeFile({ id: 'c', ingestion_status: 'failed' })
		];
		expect(hasPendingFileStatus(files)).toBe(true);
	});

	it('returns false when ingestion_status is undefined (no non-terminal match)', () => {
		expect(hasPendingFileStatus([makeFile({ ingestion_status: undefined })])).toBe(false);
	});
});

describe('fileIdsForSend', () => {
	it('returns undefined for an empty file list (omits the field, not [])', () => {
		expect(fileIdsForSend([])).toBeUndefined();
	});

	it('returns the id of a single attached file', () => {
		expect(fileIdsForSend([makeFile({ id: 'abc-123' })])).toEqual(['abc-123']);
	});

	it('preserves attachment order across multiple files', () => {
		const files = [makeFile({ id: 'first' }), makeFile({ id: 'second' }), makeFile({ id: 'third' })];
		expect(fileIdsForSend(files)).toEqual(['first', 'second', 'third']);
	});
});
