import type { MessageCreate } from '../types';

type AttachedSkill = NonNullable<MessageCreate['attached_skills']>[number];

/** Keep the UI aligned with the backend's direct-attachment request cap. */
export const MAX_DIRECT_CHAT_ATTACHMENTS = 4;

export function canAttachChatFile(currentFileCount: number): boolean {
	return currentFileCount < MAX_DIRECT_CHAT_ATTACHMENTS;
}

/** A pending upload is part of the draft, so it must settle before sending. */
export function canSendChatMessage(content: string, uploading: boolean): boolean {
	return content.trim().length > 0 && !uploading;
}

/** Bind a freshly-mounted composer to an already-selected chat. */
export function initializeChatFilesChatId(
	currentChatId: string | null,
	activeChatId: string | null
): string | null {
	return currentChatId ?? activeChatId;
}

export interface ChatAttachmentState<T> {
	chatId: string | null;
	files: ReadonlyArray<T>;
	attachmentSources: Readonly<Record<string, string>>;
}

export function chatAttachmentStateAfterSelection<T>(
	state: ChatAttachmentState<T>,
	nextChatId: string
): ChatAttachmentState<T> & { files: T[]; attachmentSources: Record<string, string> } {
	return {
		chatId: nextChatId,
		files: state.chatId === nextChatId ? [...state.files] : [],
		// Skill/file attachment provenance is draft state and must never leak
		// into another selected chat.
		attachmentSources: {}
	};
}

export function isCurrentChatFileUpload(
	uploadChatId: string | null,
	uploadGeneration: number,
	selectedChatId: string | null,
	currentGeneration: number
): boolean {
	return (
		uploadChatId !== null &&
		uploadChatId === selectedChatId &&
		uploadGeneration === currentGeneration
	);
}

interface OptimisticSendState {
	optimisticUserId: string;
	draftAssistantId: string;
	streamStarted: boolean;
}

function isKnownPrePersistenceSendFailure(error: unknown): boolean {
	if (typeof error !== 'object' || error === null) return false;

	const code = 'code' in error && typeof error.code === 'string' ? error.code : null;
	const status = 'status' in error && typeof error.status === 'number' ? error.status : null;
	return (
		code === 'attachments_not_ready' ||
		code === 'not_found' ||
		code === 'validation_error' ||
		status === 422
	);
}

/**
 * Reconcile optimistic bubbles after a send failure. Attachment readiness,
 * ownership/not-found, and request-validation errors are all rejected before
 * the backend persists the user message, so both draft bubbles are client-only.
 * Other failures before the SSE `start` frame may happen after user-message
 * persistence; retain that user bubble and remove only the unconfirmed
 * assistant draft. Once started, keep both bubbles for the existing mid-stream
 * error UI.
 */
export function reconcileChatSendFailure<T extends { id: string }>(
	messages: ReadonlyArray<T>,
	state: OptimisticSendState,
	error: unknown
): { messages: T[]; errorMessage: string } {
	let nextMessages = [...messages];
	if (!state.streamStarted) {
		const removeOptimisticUser = isKnownPrePersistenceSendFailure(error);
		const optimisticIds = new Set([
			state.draftAssistantId,
			...(removeOptimisticUser ? [state.optimisticUserId] : [])
		]);
		nextMessages = messages.filter((message) => !optimisticIds.has(message.id));
	}
	return {
		messages: nextMessages,
		errorMessage: error instanceof Error ? error.message : 'Stream failed'
	};
}

interface BuildChatMessageCreateOptions<T extends { id: string }> {
	content: string;
	model?: string | null;
	attachedSkills: ReadonlyArray<AttachedSkill>;
	files: ReadonlyArray<T>;
	skillInputs: Record<string, Record<string, unknown>>;
	setSticky?: boolean | null;
}

/** Build the complete streaming MessageCreate body used by ChatPanel. */
export function buildChatMessageCreate<T extends { id: string }>(
	options: BuildChatMessageCreateOptions<T>
): MessageCreate {
	const fileIds = [...new Set(options.files.map((file) => file.id))];

	return {
		content: options.content,
		model: options.model ?? undefined,
		attached_skills: options.attachedSkills.length > 0 ? [...options.attachedSkills] : undefined,
		// Do not filter on client-side ingestion status: upload metadata can
		// remain stale `pending` after asynchronous parsing has completed. The
		// backend owns the authoritative readiness check.
		file_ids: fileIds.length > 0 ? fileIds : undefined,
		skill_inputs: Object.keys(options.skillInputs).length > 0 ? options.skillInputs : undefined,
		set_sticky: options.setSticky,
		stream: true
	};
}
