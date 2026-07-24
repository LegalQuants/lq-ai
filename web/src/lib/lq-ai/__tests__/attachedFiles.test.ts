/**
 * Unit tests for the chat-attached-files helpers (PR #316 review follow-ups
 * F-3/F-9): the client-side 16 cap and the file_ids payload selection.
 *
 * Convention note: pure-function tests, no component mount (per the
 * ChatPanel-slash-detect.test.ts header). ChatPanel wires these into the
 * attach affordance and the send payload.
 */
import { describe, expect, it } from 'vitest';

import {
	MAX_CHAT_ATTACHED_FILES,
	canAttachChatFile,
	selectFileIdsForSend
} from '../chat/attachedFiles';
import type { FileMeta, IngestionStatus } from '../types';

function meta(id: string, status?: IngestionStatus): FileMeta {
	return {
		id,
		owner_id: 'u1',
		filename: `${id}.pdf`,
		mime_type: 'application/pdf',
		size_bytes: 2048,
		ingestion_status: status,
		created_at: '2026-01-01T00:00:00Z'
	};
}

describe('MAX_CHAT_ATTACHED_FILES', () => {
	it('mirrors the backend MESSAGE_FILE_IDS_MAX_LEN cap', () => {
		expect(MAX_CHAT_ATTACHED_FILES).toBe(16);
	});
});

describe('canAttachChatFile', () => {
	it('allows attaching below the cap', () => {
		expect(canAttachChatFile(0)).toBe(true);
		expect(canAttachChatFile(MAX_CHAT_ATTACHED_FILES - 1)).toBe(true);
	});

	it('blocks the 17th attach at and above the cap', () => {
		expect(canAttachChatFile(MAX_CHAT_ATTACHED_FILES)).toBe(false);
		expect(canAttachChatFile(MAX_CHAT_ATTACHED_FILES + 1)).toBe(false);
	});
});

describe('selectFileIdsForSend', () => {
	it('returns undefined for an empty panel', () => {
		expect(selectFileIdsForSend([])).toBeUndefined();
	});

	it("excludes 'failed' files", () => {
		const files = [meta('a', 'ready'), meta('b', 'failed'), meta('c', 'ready')];
		expect(selectFileIdsForSend(files)).toEqual(['a', 'c']);
	});

	it("keeps 'pending' and 'processing' files (backend skips not-yet-ready gracefully)", () => {
		const files = [meta('a', 'pending'), meta('b', 'processing'), meta('c', 'ready')];
		expect(selectFileIdsForSend(files)).toEqual(['a', 'b', 'c']);
	});

	it('keeps files with no status yet (just-uploaded)', () => {
		expect(selectFileIdsForSend([meta('a', undefined)])).toEqual(['a']);
	});

	it('returns undefined when every file failed', () => {
		const files = [meta('a', 'failed'), meta('b', 'failed')];
		expect(selectFileIdsForSend(files)).toBeUndefined();
	});

	it('defensively slices to the 16 cap', () => {
		const files = Array.from({ length: 20 }, (_, i) => meta(`f${i}`, 'ready'));
		const ids = selectFileIdsForSend(files);
		expect(ids).toHaveLength(MAX_CHAT_ATTACHED_FILES);
		expect(ids?.[0]).toBe('f0');
		expect(ids?.[MAX_CHAT_ATTACHED_FILES - 1]).toBe('f15');
	});

	it('drops failed files before applying the cap', () => {
		// 17 files where one failed → the 16 non-failed all fit.
		const files = [
			meta('bad', 'failed'),
			...Array.from({ length: 16 }, (_, i) => meta(`f${i}`, 'ready'))
		];
		const ids = selectFileIdsForSend(files);
		expect(ids).toHaveLength(16);
		expect(ids).not.toContain('bad');
	});
});
