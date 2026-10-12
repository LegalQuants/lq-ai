/**
 * Unit tests for the chat-attached-files helpers (PR #316 review follow-ups
 * F-3/F-9): the client-side 16 cap and the file_ids payload selection.
 *
 * Convention note: pure-function tests, no component mount (per the
 * ChatPanel-slash-detect.test.ts header). ChatPanel wires these into the
 * attach affordance and the send payload.
 */
import { describe, expect, it, vi } from 'vitest';

import {
	MAX_CHAT_ATTACHED_FILES,
	canAttachChatFile,
	createProcessingFileWarningHandler,
	hasAppliedProcessingFile,
	processingFileNames,
	readyFileNames,
	selectFileIdsForSend
} from '../chat/attachedFiles';
import type { FileMeta, IngestionStatus, MessageCompleteFrame } from '../types';

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

describe('hasAppliedProcessingFile', () => {
	it('detects a file that was still ingesting when the backend accepted it', () => {
		expect(hasAppliedProcessingFile(['pending-id'], ['ready-id', 'pending-id'])).toBe(true);
	});

	it('does not warn when no still-ingesting file was applied', () => {
		expect(hasAppliedProcessingFile(['pending-id'], ['ready-id'])).toBe(false);
		expect(hasAppliedProcessingFile(['pending-id'], undefined)).toBe(false);
	});
});

describe('processing attachment warning ownership', () => {
	const complete: MessageCompleteFrame = {
		type: 'complete',
		lq_ai_message_id: 'message-a',
		message: {
			id: 'message-a',
			chat_id: 'chat-a',
			role: 'assistant',
			content: 'Answer',
			created_at: '2026-10-11T00:00:00Z'
		},
		applied_file_ids: ['pending-id']
	};

	it("does not show chat A's warning after switching to chat B before completion", () => {
		let activeChatId: string | null = 'chat-a';
		const showWarning = vi.fn();
		const onComplete = createProcessingFileWarningHandler(
			['pending-id'],
			() => activeChatId,
			showWarning
		);

		// The callback was created for A's send, but its stream completes in B.
		activeChatId = 'chat-b';
		onComplete(complete);
		expect(showWarning).not.toHaveBeenCalled();
	});

	it('still warns when the completing turn belongs to the visible chat', () => {
		const showWarning = vi.fn();
		const onComplete = createProcessingFileWarningHandler(
			['pending-id'],
			() => 'chat-a',
			showWarning
		);

		onComplete(complete);
		expect(showWarning).toHaveBeenCalledOnce();
		expect(showWarning.mock.calls[0][0]).toContain('its contents may not have been available');
	});

	it('does not warn when there is no active chat or no applied processing file', () => {
		const showWarning = vi.fn();
		createProcessingFileWarningHandler(['pending-id'], () => null, showWarning)(complete);
		createProcessingFileWarningHandler(
			['pending-id'],
			() => 'chat-a',
			showWarning
		)({
			...complete,
			applied_file_ids: ['ready-id']
		});
		expect(showWarning).not.toHaveBeenCalled();
	});
});

describe('readyFileNames / processingFileNames', () => {
	// A skill's required document input may only lean on a file whose text
	// the backend will actually inject, i.e. a 'ready' one.
	const files = [meta('a', 'ready'), meta('b', 'failed'), meta('c', 'processing'), meta('d')];

	it('counts only ready files as ready', () => {
		expect(readyFileNames(files)).toEqual(['a.pdf']);
		expect(readyFileNames([meta('c', 'pending')])).toEqual([]);
	});

	it('counts pending, processing and status-less files as processing, never failed ones', () => {
		expect(processingFileNames(files)).toEqual(['c.pdf', 'd.pdf']);
		expect(processingFileNames([meta('b', 'failed'), meta('a', 'ready')])).toEqual([]);
	});
});
