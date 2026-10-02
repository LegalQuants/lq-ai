/** Pure helpers for chat-attached files (PR #316 review follow-ups). No Svelte, no network. */

import type { FileMeta } from '../types';

/**
 * Maximum chat-attached files per message send. Mirrors
 * MESSAGE_FILE_IDS_MAX_LEN in api/app/schemas/chats.py — the backend rejects
 * the whole send with a 422 when `file_ids` exceeds this, so the attach path
 * enforces it client-side instead of failing at send time.
 */
export const MAX_CHAT_ATTACHED_FILES = 16;

/** Attach guard: false once the panel already holds the cap. */
export function canAttachChatFile(attachedCount: number): boolean {
	return attachedCount < MAX_CHAT_ATTACHED_FILES;
}

/**
 * Build the `file_ids` payload from the panel's attached files.
 *
 * Excludes 'failed' files — they can never contribute text. Keeps
 * pending/processing files: the backend skips not-yet-ready files gracefully,
 * and dropping them would silently ignore a just-attached document.
 * Defensively slices to the cap, and returns undefined when the result is
 * empty so the field is omitted from the payload.
 */
export function selectFileIdsForSend(files: FileMeta[]): string[] | undefined {
	const ids = files
		.filter((f) => f.ingestion_status !== 'failed')
		.slice(0, MAX_CHAT_ATTACHED_FILES)
		.map((f) => f.id);
	return ids.length > 0 ? ids : undefined;
}
